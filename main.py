import os
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, make_response
import logging
from functools import wraps
from datetime import datetime, date
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from io import BytesIO
import pymupdf
import hmac
import secrets
from datetime import timedelta
from flask_sqlalchemy import SQLAlchemy
from pathlib import Path

# Importation des modèles
from models import db, Plat, Reservation, MenuDocument, MenuDocumentPage, EmailEnvoi, JourFerme

# Importation du blueprint de réservation
import reservation_client as rc
from reservation_client import reservation_bp, en_arriere_plan, mail_client, donnees_reservation

app = Flask(__name__)
app.register_blueprint(reservation_bp, url_prefix='/reservation')

# Cle secrete des sessions : a definir dans Railway (variable SECRET_KEY).
# L'ancienne cle etait ecrite dans le code public, ce qui permettait de
# fabriquer une session admin sans mot de passe.
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
if not os.environ.get('SECRET_KEY'):
    print("⚠️  SECRET_KEY non définie : clé temporaire utilisée (les sessions admin seront perdues à chaque redémarrage).")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',   # bloque les formulaires envoyes depuis un autre site
    SESSION_COOKIE_SECURE=bool(os.environ.get('RAILWAY_ENVIRONMENT_NAME') or os.environ.get('RAILWAY_ENVIRONMENT')
                               or os.environ.get('COOKIE_SECURE')),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)
# Configuration de la base de données
basedir = Path(__file__).parent
# En local (pas de DATABASE_URL) : SQLite. Sur Railway avec le plugin PostgreSQL :
# DATABASE_URL est fourni automatiquement et utilisé tel quel pour une persistance fiable.
DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{basedir}/data/restaurant.db')

# Utiliser psycopg2 comme driver PostgreSQL pour une meilleure stabilité SSL
if DATABASE_URL and DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg2://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300
}

# Initialiser la base de données avec l'application
db.init_app(app)

# Configuration de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def migrer_colonnes_manquantes():
    # Pas d'outil de migration en place : on ajoute ici les colonnes qui
    # manqueraient sur une base existante, sans toucher aux donnees.
    inspector = db.inspect(db.engine)
    if 'reservations' in inspector.get_table_names():
        colonnes = {c['name'] for c in inspector.get_columns('reservations')}
        if 'groupe_reference' not in colonnes:
            db.session.execute(db.text('ALTER TABLE reservations ADD COLUMN groupe_reference VARCHAR(20)'))
            db.session.commit()
        if 'source' not in colonnes:
            db.session.execute(db.text("ALTER TABLE reservations ADD COLUMN source VARCHAR(20) DEFAULT 'web'"))
            db.session.commit()
        # Etendre la colonne reference a VARCHAR(30) pour le format Table1-2026-08-28
        # (PostgreSQL uniquement : SQLite, utilise en local, ne connait pas cette syntaxe)
        if db.engine.dialect.name == 'postgresql':
            db.session.execute(db.text('ALTER TABLE reservations ALTER COLUMN reference TYPE VARCHAR(30)'))
            db.session.commit()

def creer_tables():
    try:
        with app.app_context():
            db.create_all()
            migrer_colonnes_manquantes()
            app.logger.info("Tables créées avec succès.")
    except Exception as e:
        app.logger.error(f"Erreur lors de la création des tables: {e}")

# Configuration de l'admin : identifiants dans les variables Railway
# ADMIN_USERNAME et ADMIN_PASSWORD (plus jamais dans le code, qui est public).
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
if not ADMIN_PASSWORD:
    print("⚠️  ADMIN_PASSWORD non défini : la connexion admin est désactivée.")

# Protection des routes admin
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def identifiants_valides(username, password):
    if not ADMIN_PASSWORD:
        return False
    return (hmac.compare_digest((username or '').encode(), ADMIN_USERNAME.encode())
            and hmac.compare_digest((password or '').encode(), ADMIN_PASSWORD.encode()))

# Route de connexion admin
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        cle = f'login:{rc.adresse_ip()}'
        # 5 essais ratés en 15 minutes : on bloque (protection contre les
        # robots qui testent des mots de passe).
        if rc.limite_atteinte(cle, 5, 900, enregistrer=False):
            flash('Trop de tentatives. Réessayez dans 15 minutes.', 'danger')
            return render_template('admin_login.html'), 429
        username = request.form.get('username')
        password = request.form.get('password')
        if identifiants_valides(username, password):
            session.clear()
            session.permanent = True
            session['admin_logged_in'] = True
            return redirect(url_for('afficher_toutes_reservations'))
        rc.limite_atteinte(cle, 5, 900)   # compte l'essai rate
        if not ADMIN_PASSWORD:
            flash("Connexion désactivée : le mot de passe admin n'est pas configuré (variable ADMIN_PASSWORD).", 'danger')
        else:
            flash('Identifiants incorrects', 'danger')
    return render_template('admin_login.html')

# Route de déconnexion admin
@app.route('/admin/logout')
@login_required
def admin_logout():
    # Nettoyage complet de la session
    session.clear()  # Efface toutes les données de session
    flash('Vous avez été déconnecté avec succès.', 'success')
    return redirect(url_for('accueil'))

# ---------------------------------------------------------------------------
# Suivi des emails dans l'admin
# ---------------------------------------------------------------------------

def etat_emails(reservations):
    """Dernier email client (reception, confirmation ou annulation) connu
    pour chaque reservation : {id: EmailEnvoi ou None}."""
    refs = set()
    for r in reservations:
        refs.add(r.reference)
        if r.groupe_reference:
            refs.add(r.groupe_reference)
    if not refs:
        return {}
    journaux = (EmailEnvoi.query
                .filter(EmailEnvoi.reference.in_(refs),
                        EmailEnvoi.type_mail.in_(rc.TYPES_MAIL_CLIENT))
                .order_by(EmailEnvoi.created_at.asc(), EmailEnvoi.id.asc())
                .all())
    dernier = {}
    for j in journaux:
        dernier[j.reference] = j   # le plus recent remplace les precedents
    etats = {}
    for r in reservations:
        candidats = [c for c in (dernier.get(r.reference), dernier.get(r.groupe_reference)) if c]
        etats[r.id] = max(candidats, key=lambda c: (c.created_at, c.id)) if candidats else None
    return etats


def alertes_admin():
    """Messages affiches en haut de la liste des reservations."""
    alertes = []
    if rc.TEST_EMAIL_REDIRECT:
        alertes.append(('danger', "Mode test actif (variable TEST_EMAIL_REDIRECT) : tous les emails partent "
                                  f"vers {rc.TEST_EMAIL_REDIRECT} et aucun client ne reçoit les siens."))
    if not (rc.SMTP_USER and rc.SMTP_PASSWORD) and not rc.BREVO_API_KEY and not rc.RESEND_API_KEY:
        alertes.append(('danger', "Aucun service d'envoi d'emails n'est configuré : les clients ne reçoivent aucun email."))

    aujourd_hui = date.today().isoformat()
    a_venir = Reservation.query.filter(Reservation.date >= aujourd_hui, Reservation.statut != 'annulee').all()
    etats = etat_emails(a_venir)
    echecs = [r for r in a_venir if etats.get(r.id) is not None and etats[r.id].statut == 'echec']
    if echecs:
        noms = ', '.join(f"{r.nom} ({r.telephone or 'pas de tél.'}, {rc.date_fr(r.date, False)})" for r in echecs[:8])
        suite = '…' if len(echecs) > 8 else ''
        alertes.append(('danger', f"{len(echecs)} client(s) n'ont pas reçu leur dernier email : {noms}{suite}. "
                                  "Renvoyez-le (bouton ✉) ou appelez-les."))

    limite = datetime.utcnow() - timedelta(hours=24)
    en_retard = Reservation.query.filter(Reservation.statut == 'en_attente',
                                         Reservation.created_at < limite,
                                         Reservation.date >= aujourd_hui).count()
    if en_retard:
        alertes.append(('warning', f"{en_retard} demande(s) attendent une validation depuis plus de 24 h. "
                                   "Tant qu'elles ne sont pas confirmées, les clients n'ont pas de confirmation."))
    return alertes


# Exemple de route protégée
@app.route('/admin/reservations')
@login_required
def afficher_toutes_reservations():
    try:
        # Vérifier si la table reservations existe
        inspector = db.inspect(db.engine)
        if 'reservations' not in inspector.get_table_names():
            app.logger.error("La table 'reservations' n'existe pas dans la base de données")
            flash("La base de données n'est pas initialisée correctement. Veuillez contacter l'administrateur.", "error")
            return redirect(url_for('accueil'))

        # Filtrage par statut (paramètre ?statut=en_attente|confirmee|annulee)
        statut = request.args.get('statut')
        query = Reservation.query
        if statut in ('en_attente', 'confirmee', 'annulee'):
            query = query.filter(Reservation.statut == statut)
        reservations = query.order_by(Reservation.date.desc(), Reservation.heure.desc()).all()

        # Ajouter la date et l'heure actuelles pour l'impression
        return render_template('admin_reservations.html',
                             reservations=reservations,
                             email=None,
                             statut_actuel=statut,
                             now=datetime.now(),
                             etats=etat_emails(reservations),
                             alertes=alertes_admin())
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération des réservations: {e}")
        app.logger.error(f"Type d'erreur: {type(e).__name__}")
        import traceback
        app.logger.error(f"Traceback: {traceback.format_exc()}")
        flash(f"Une erreur est survenue lors de la récupération des réservations: {str(e)}", "error")
        return redirect(url_for('accueil'))


@app.route('/admin/reservations/par-date')
@login_required
def reservations_par_date():
    try:
        inspector = db.inspect(db.engine)
        if 'reservations' not in inspector.get_table_names():
            flash("La base de données n'est pas initialisée correctement.", "error")
            return redirect(url_for('accueil'))

        # On ne compte que les réservations non annulées pour le nombre de tables
        reservations = Reservation.query.filter(
            Reservation.statut != 'annulee'
        ).order_by(Reservation.date.asc(), Reservation.heure.asc()).all()

        # Grouper par date
        par_date = {}
        for r in reservations:
            par_date.setdefault(r.date, []).append(r)

        # Construire un résumé trié par date croissante
        resume = []
        for date_str in sorted(par_date.keys()):
            liste = par_date[date_str]
            nb_tables = len(liste)
            nb_personnes = sum(r.personnes for r in liste)
            # Statut breakdown
            confirmees = sum(1 for r in liste if r.statut == 'confirmee')
            en_attente = sum(1 for r in liste if r.statut == 'en_attente')
            resume.append({
                'date': date_str,
                'nb_tables': nb_tables,
                'nb_personnes': nb_personnes,
                'confirmees': confirmees,
                'en_attente': en_attente,
                'reservations': liste,
            })

        return render_template('admin_reservations_par_date.html',
                             resume=resume,
                             now=datetime.now())
    except Exception as e:
        app.logger.error(f"Erreur lors du regroupement par date: {e}")
        import traceback
        app.logger.error(f"Traceback: {traceback.format_exc()}")
        flash(f"Une erreur est survenue : {str(e)}", "error")
        return redirect(url_for('accueil'))



# Créer les tables au démarrage
with app.app_context():
    creer_tables()

@app.route('/')
def accueil():
    return redirect(url_for('page_accueil'))

@app.route('/accueil')
def page_accueil():
    return render_template('accueil.html', today=date.today().isoformat())

@app.route('/ajouter_menu')
@login_required
def ajouter_menu():
    return render_template('ajouter-menu.html')

@app.route('/admin/ajouter_plat')
@login_required
def ajouter_plat():
    return render_template('ajouter-menu.html')

@app.route('/admin/modifier_plat/<int:plat_id>', methods=['GET', 'POST'])
@login_required
def modifier_plat(plat_id):
    plat = Plat.query.get_or_404(plat_id)
    
    if request.method == 'POST':
        try:
            # Récupération des données du formulaire
            plat.nom = request.form.get('nom_plat')
            plat.description = request.form.get('description')
            plat.prix = float(request.form.get('prix'))
            plat.categorie = request.form.get('categorie')
            
            # Validation des données
            if not all([plat.nom, plat.description, plat.prix, plat.categorie]):
                flash('Tous les champs sont obligatoires', 'error')
                return render_template('modifier-menu.html', plat=plat)
            
            # Sauvegarde en base de données
            db.session.commit()
            flash('Plat mis à jour avec succès!', 'success')
            return redirect(url_for('admin_menu'))
            
        except ValueError:
            flash('Le prix doit être un nombre valide', 'error')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erreur lors de la mise à jour du plat {plat_id}: {str(e)}")
            flash('Une erreur est survenue lors de la mise à jour du plat', 'error')
    
    # Si c'est une requête GET ou en cas d'erreur POST
    return render_template('modifier-menu.html', plat=plat)
            

            
 

@app.route('/admin/ajouter_plat_action', methods=['POST'])
@login_required
def admin_ajouter_plat_action():
    if request.method == 'POST':
        nom_plat = request.form.get('nom_plat')
        description = request.form.get('description')
        prix = request.form.get('prix')
        categorie = request.form.get('categorie', 'plat_principal')  # Valeur par défaut
        
        try:
            prix = float(prix)
            nouveau_plat = Plat(
                nom=nom_plat,
                description=description,
                prix=prix,
                categorie=categorie
            )
            db.session.add(nouveau_plat)
            db.session.commit()
            flash('Plat ajouté avec succès!', 'success')
            return redirect(url_for('admin_menu'))
        except ValueError:
            flash('Le prix doit être un nombre valide', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout du plat: {str(e)}', 'error')
        return redirect(url_for('ajouter_plat'))
    return redirect(url_for('ajouter_plat'))

@app.route('/changer_statut/<int:id>', methods=['POST'])
@login_required
def changer_statut(id):
    if 'nouveau_statut' not in request.form:
        flash('Statut non spécifié', 'error')
        return redirect(url_for('afficher_toutes_reservations'))
    
    nouveau_statut = request.form['nouveau_statut']
    if nouveau_statut not in ['en_attente', 'confirmee', 'annulee']:
        flash('Statut invalide', 'error')
        return redirect(url_for('afficher_toutes_reservations'))
    
    try:
        reservation = Reservation.query.get_or_404(id)
        ancien_statut = reservation.statut
        reservation.statut = nouveau_statut
        db.session.commit()

        # Envoyer l'email au client uniquement après la décision de l'admin,
        # et seulement lorsque le statut change réellement. L'envoi se fait
        # en arrière-plan et il est noté dans le journal des emails (colonne
        # « Email » de la liste) : un échec n'est plus silencieux.
        if nouveau_statut != ancien_statut and nouveau_statut in ('confirmee', 'annulee'):
            type_mail = 'confirmation' if nouveau_statut == 'confirmee' else 'annulation'
            en_arriere_plan(mail_client, type_mail, [donnees_reservation(reservation)])

        flash(f'Le statut de la réservation a été mis à jour avec succès.', 'success')
    except Exception as e:
        app.logger.error(f"Erreur lors de la mise à jour du statut: {e}")
        flash('Une erreur est survenue lors de la mise à jour du statut.', 'error')
    
    return redirect(url_for('afficher_toutes_reservations'))

@app.route('/menu')
@app.route('/carte')
def menu():
    try:
        # Vérifier si la table menu existe
        inspector = db.inspect(db.engine)
        if 'menu' not in inspector.get_table_names():
            app.logger.error("La table 'menu' n'existe pas dans la base de données")
            flash("La base de données n'est pas initialisée correctement. Veuillez contacter l'administrateur.", "error")
            return redirect(url_for('accueil'))
        
        plats = Plat.query.order_by(Plat.categorie, Plat.nom).all()

        # Grouper les plats par catégorie
        menu_par_categorie = {}
        for plat in plats:
            categorie = plat.categorie or 'Autres'
            if categorie not in menu_par_categorie:
                menu_par_categorie[categorie] = []
            menu_par_categorie[categorie].append({
                'id': plat.id,
                'nom': plat.nom,
                'description': plat.description,
                'prix': plat.prix,
                'categorie': plat.categorie,
                'image': plat.image
            })

        menu_pdf = MenuDocument.query.order_by(MenuDocument.date_upload.desc()).first()

        # Si l'utilisateur est admin, on affiche la vue admin
        if session.get('admin_logged_in'):
            return render_template('admin_menu.html',
                                menu_par_categorie=menu_par_categorie,
                                menu_pdf=menu_pdf)
        # Sinon, on affiche la vue client
        return render_template('menu.html',
                            menu_par_categorie=menu_par_categorie,
                            menu_pdf=menu_pdf)
    except Exception as e:
        app.logger.error(f"Erreur dans la route menu: {str(e)}")
        app.logger.error(f"Type d'erreur: {type(e).__name__}")
        import traceback
        app.logger.error(f"Traceback: {traceback.format_exc()}")
        flash(f"Une erreur est survenue lors du chargement du menu: {str(e)}", 'error')
        return redirect(url_for('accueil'))
@app.route('/admin/menu')
@login_required
def admin_menu():
    try:
        plats = Plat.query.order_by(Plat.categorie, Plat.nom).all()
        
        # Grouper les plats par catégorie
        menu_par_categorie = {}
        for plat in plats:
            categorie = plat.categorie or 'Autres'
            if categorie not in menu_par_categorie:
                menu_par_categorie[categorie] = []
            menu_par_categorie[categorie].append({
                'id': plat.id,
                'nom': plat.nom,
                'description': plat.description,
                'prix': plat.prix,
                'categorie': plat.categorie,
                'image': plat.image
            })

        menu_pdf = MenuDocument.query.order_by(MenuDocument.date_upload.desc()).first()

        return render_template('admin_menu.html',
                            menu_par_categorie=menu_par_categorie,
                            menu_pdf=menu_pdf)
    except Exception as e:
        app.logger.error(f"Erreur dans la route menu admin: {str(e)}")
        flash('Une erreur est survenue lors du chargement du menu.', 'error')
        return redirect(url_for('accueil'))


@app.route('/admin/menu/export_pdf')
@login_required
def export_menu_pdf():
    try:
        # Récupérer les données du menu
        plats = Plat.query.order_by(Plat.categorie, Plat.nom).all()
        
        # Grouper les plats par catégorie
        menu_par_categorie = {}
        for plat in plats:
            categorie = plat.categorie or 'Autres'
            if categorie not in menu_par_categorie:
                menu_par_categorie[categorie] = []
            menu_par_categorie[categorie].append({
                'nom': plat.nom,
                'description': plat.description,
                'prix': plat.prix
            })
        
        # Créer le PDF
        response = make_response()
        response.mimetype = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename=menu_restaurant.pdf'
        
        # Créer le document PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, 
                              rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=72)
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', 
                                   parent=styles['Heading1'],
                                   fontSize=24,
                                   spaceAfter=30,
                                   alignment=1)  # 1 = center
        
        # Contenu du PDF
        elements = []
        
        # Titre
        elements.append(Paragraph("Menu du Restaurant", title_style))
        elements.append(Spacer(1, 20))
        
        # Date d'édition
        date_style = ParagraphStyle('Date',
                                  parent=styles['Normal'],
                                  fontSize=10,
                                  alignment=2)  # 2 = right
        elements.append(Paragraph(f"Édité le {date.today().strftime('%d/%m/%Y')}", date_style))
        elements.append(Spacer(1, 30))
        
        # Pour chaque catégorie
        for categorie, plats in menu_par_categorie.items():
            # Titre de la catégorie
            elements.append(Paragraph(categorie.upper(), styles['Heading2']))
            elements.append(Spacer(1, 10))
            
            # Tableau des plats
            data = [['Nom', 'Description', 'Prix']]
            for plat in plats:
                data.append([
                    plat['nom'],
                    plat['description'],
                    f"{plat['prix']:.2f} €"
                ])
            
            # Style du tableau
            table_style = TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),  # Aligner la colonne de prix à droite
            ])
            
            # Créer et styliser le tableau
            table = Table(data, colWidths=[doc.width/3.0]*3)
            table.setStyle(table_style)
            elements.append(table)
            elements.append(Spacer(1, 20))
        
        # Générer le PDF
        doc.build(elements)
        
        # Récupérer le contenu du buffer et le renvoyer
        pdf = buffer.getvalue()
        buffer.close()
        response.data = pdf
        
        return response
    except Exception as e:
        app.logger.error(f"Erreur lors de la génération du PDF: {str(e)}")
        flash('Une erreur est survenue lors de la génération du PDF.', 'error')
        return redirect(url_for('admin_menu'))    



@app.route('/supprimer_plat/<int:plat_id>', methods=['POST'])
@login_required
def supprimer_plat(plat_id):
    try:
        plat = Plat.query.get_or_404(plat_id)
        db.session.delete(plat)
        db.session.commit()
        flash('Plat supprimé avec succès!', 'success')
    except Exception as e:
        flash(f'Erreur lors de la suppression du plat: {str(e)}', 'error')
    return redirect(url_for('menu'))

@app.route('/admin/reservation/supprimer/<int:id>', methods=['POST'])
@login_required
def supprimer_reservation(id):
    try:
        reservation = Reservation.query.get_or_404(id)
        db.session.delete(reservation)
        db.session.commit()
        flash('La réservation a été supprimée avec succès.', 'success')
    except Exception as e:
        flash(f'Une erreur est survenue lors de la suppression de la réservation : {str(e)}', 'error')
    
    return redirect(url_for('afficher_toutes_reservations'))

@app.route('/admin/reservations/supprimer_multiple', methods=['POST'])
@login_required
def supprimer_reservations_multiple():
    ids = request.form.getlist('ids[]')
    if not ids:
        flash('Aucune réservation sélectionnée.', 'warning')
        return redirect(url_for('afficher_toutes_reservations'))
    try:
        count = 0
        for rid in ids:
            reservation = Reservation.query.get(int(rid))
            if reservation:
                db.session.delete(reservation)
                count += 1
        db.session.commit()
        flash(f'{count} réservation(s) supprimée(s) avec succès.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de la suppression multiple : {str(e)}', 'error')

    return redirect(url_for('afficher_toutes_reservations'))

def generate_reference(date=None):
    """Generate a sequential reference like Table1-2026-08-28, Table2-2026-08-28, etc.
    If date is provided, the counter resets for each date."""
    from models import Reservation
    if date:
        count = Reservation.query.filter_by(date=date).count()
        return f'Table{count + 1}-{date}'
    else:
        count = Reservation.query.count()
        return f'Table{count + 1}'

MENU_PDF_TAILLE_MAX = 5 * 1024 * 1024  # 5 Mo

@app.route('/admin/menu/importer', methods=['GET', 'POST'])
@login_required
def importer_menu():
    if request.method == 'POST':
        if 'fichier' not in request.files:
            flash('Aucun fichier sélectionné', 'error')
            return redirect(request.url)

        fichier = request.files['fichier']
        if fichier.filename == '':
            flash('Aucun fichier sélectionné', 'error')
            return redirect(request.url)

        if fichier and fichier.filename.lower().endswith('.pdf'):
            try:
                contenu = fichier.read()
                if len(contenu) > MENU_PDF_TAILLE_MAX:
                    flash('Le fichier dépasse la taille maximale autorisée (5 Mo).', 'error')
                    return redirect(request.url)

                # On ne garde qu'un seul PDF de menu à la fois : le plus récent remplace le précédent
                MenuDocument.query.delete()
                document = MenuDocument(nom_fichier=fichier.filename, contenu=contenu)
                db.session.add(document)
                db.session.flush()

                # On convertit chaque page en image : affichage direct et fiable,
                # sans dépendre d'un lecteur PDF intégré au navigateur.
                pdf = pymupdf.open(stream=contenu, filetype="pdf")
                matrice = pymupdf.Matrix(3, 3)
                for numero, page in enumerate(pdf, start=1):
                    pixmap = page.get_pixmap(matrix=matrice)
                    db.session.add(MenuDocumentPage(
                        document_id=document.id, numero=numero, image=pixmap.tobytes("png")
                    ))
                pdf.close()

                db.session.commit()

                flash('Le menu PDF a été mis à jour avec succès.', 'success')
                return redirect(url_for('admin_menu'))

            except Exception as e:
                db.session.rollback()
                app.logger.error(f'Erreur lors de l\'import du menu : {str(e)}')
                flash('Une erreur est survenue lors de l\'import du menu', 'error')
                return redirect(request.url)
        else:
            flash('Format de fichier non supporté. Veuillez sélectionner un fichier PDF.', 'error')
            return redirect(request.url)

    return render_template('importer_menu.html')

@app.route('/menu/pdf')
def menu_pdf():
    document = MenuDocument.query.order_by(MenuDocument.date_upload.desc()).first()
    if document is None:
        flash("Aucun menu PDF n'a encore été mis en ligne.", 'error')
        return redirect(url_for('menu'))

    response = make_response(document.contenu)
    response.mimetype = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename="{document.nom_fichier}"'
    return response

@app.route('/menu/pdf/page/<int:page_id>')
def menu_pdf_page(page_id):
    page = MenuDocumentPage.query.get_or_404(page_id)
    response = make_response(page.image)
    response.mimetype = 'image/png'
    return response

@app.route('/admin/menu/pdf/supprimer', methods=['POST'])
@login_required
def supprimer_menu_pdf():
    try:
        # Supprimer d'abord les pages du document (table enfant)
        MenuDocumentPage.query.delete()
        # Puis supprimer les documents (table parente)
        MenuDocument.query.delete()
        db.session.commit()
        flash('Le menu PDF a été retiré du site.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur lors de la suppression du menu PDF: {str(e)}")
        flash('Une erreur est survenue lors de la suppression du menu PDF.', 'error')
    return redirect(url_for('admin_menu'))


@app.route('/reserver')
def reserver():
    """Rediriger vers le blueprint de réservation pour maintenir la compatibilité"""
    return redirect(url_for('reservation.reserver'))

@app.route('/admin/reservation/modifier/<int:id>', methods=['GET', 'POST'])
@login_required
def modifier_reservation(id):
    try:
        reservation = Reservation.query.get_or_404(id)
        
        if request.method == 'POST':
            ancien_statut = reservation.statut
            # Récupérer les données du formulaire
            reservation.nom = request.form.get('nom')
            reservation.email = request.form.get('email')
            reservation.telephone = request.form.get('telephone')
            reservation.date = request.form.get('date')
            reservation.heure = request.form.get('heure')
            reservation.personnes = int(request.form.get('personnes', 1))
            reservation.message = request.form.get('message', '')
            reservation.statut = request.form.get('statut')
            
            db.session.commit()

            # Notifier le client uniquement lorsque l'admin fait passer
            # la réservation à "confirmee" ou "annulee" (envoi en
            # arrière-plan, noté dans le journal des emails).
            if reservation.statut != ancien_statut and reservation.statut in ('confirmee', 'annulee'):
                type_mail = 'confirmation' if reservation.statut == 'confirmee' else 'annulation'
                en_arriere_plan(mail_client, type_mail, [donnees_reservation(reservation)])

            flash('La réservation a été mise à jour avec succès.', 'success')
            return redirect(url_for('afficher_toutes_reservations'))
        
        # Pour les requêtes GET, afficher le formulaire de modification
        return render_template('modifier_reservation.html', reservation=reservation)
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur lors de la modification de la réservation: {str(e)}")
        flash('Une erreur est survenue lors de la modification de la réservation.', 'error')
        return redirect(url_for('afficher_toutes_reservations'))

@app.route('/confirmation-groupe/<groupe_reference>')
def confirmation_groupe(groupe_reference):
    # Page visible uniquement par la personne qui vient de reserver (ou
    # par l'admin) : les anciennes references de groupe etaient
    # sequentielles, donc faciles a deviner (noms des clients visibles).
    if session.get('derniere_reservation') != groupe_reference and not session.get('admin_logged_in'):
        flash(f"Cette page n'est plus disponible. Pour toute question sur votre réservation, appelez-nous au {rc.RESTAURANT_TEL}.", 'info')
        return redirect(url_for('page_accueil'))
    try:
        reservations = Reservation.query.filter_by(groupe_reference=groupe_reference).order_by(Reservation.date).all()

        if not reservations:
            flash('Réservation non trouvée.', 'error')
            return redirect(url_for('accueil'))

        for reservation in reservations:
            try:
                date_obj = datetime.strptime(str(reservation.date), '%Y-%m-%d')
                reservation.date_formatted = date_obj.strftime('%d/%m/%Y')
            except (ValueError, TypeError) as e:
                app.logger.error(f"Erreur de formatage de date: {e}")
                reservation.date_formatted = reservation.date

        toutes_confirmees = all(r.statut == 'confirmee' for r in reservations)
        return render_template('confirmation_groupe.html', reservations=reservations, premiere=reservations[0],
                               toutes_confirmees=toutes_confirmees, telephone_resto=rc.RESTAURANT_TEL,
                               lien_modif=url_for('reservation.modifier', jeton=rc.jeton_modification(groupe_reference)))

    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération de la réservation: {str(e)}")
        flash('Une erreur est survenue lors de la récupération de votre réservation.', 'error')
        return redirect(url_for('accueil'))


# ---------------------------------------------------------------------------
# Admin : renvoyer un email, saisir une réservation prise par téléphone,
# gérer les jours de fermeture
# ---------------------------------------------------------------------------

@app.route('/admin/reservation/<int:id>/renvoyer', methods=['POST'])
@login_required
def renvoyer_email(id):
    reservation = Reservation.query.get_or_404(id)
    if not reservation.email:
        flash("Pas d'adresse email pour ce client : appelez-le.", 'warning')
    elif reservation.statut == 'en_attente':
        flash("Cette réservation est encore en attente : confirmez-la (✓) pour envoyer la confirmation.", 'warning')
    else:
        type_mail = 'confirmation' if reservation.statut == 'confirmee' else 'annulation'
        en_arriere_plan(mail_client, type_mail, [donnees_reservation(reservation)])
        flash(f"Email de {type_mail} renvoyé à {reservation.email}. Le résultat s'affiche dans la colonne « Email ».", 'success')
    return redirect(url_for('afficher_toutes_reservations'))


@app.route('/admin/reservations/ajouter', methods=['GET', 'POST'])
@login_required
def ajouter_reservation_admin():
    """Saisie d'une réservation prise par téléphone (ou au comptoir) :
    elle entre dans la même liste et compte dans les places du jour."""
    valeurs = request.form if request.method == 'POST' else request.args   # ?date=AAAA-MM-JJ pre-remplit la date
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        telephone = request.form.get('telephone', '').strip()
        email = request.form.get('email', '').strip()
        jour = request.form.get('date', '').strip()
        message = request.form.get('message', '').strip()
        statut = request.form.get('statut', 'confirmee')
        forcer = request.form.get('forcer') == '1'
        envoyer = request.form.get('envoyer_email') == '1'
        try:
            personnes = int(request.form.get('personnes', ''))
        except ValueError:
            personnes = 0

        erreurs = []
        if not nom:
            erreurs.append('Le nom est obligatoire.')
        if email and not rc.EMAIL_RE.match(email):
            erreurs.append("L'adresse email ne semble pas correcte.")
        if not 1 <= personnes <= rc.GROUPE_MAX:
            erreurs.append(f'Nombre de personnes : de 1 à {rc.GROUPE_MAX}.')
        if statut not in ('confirmee', 'en_attente'):
            statut = 'confirmee'
        try:
            jour_obj = datetime.strptime(jour, '%Y-%m-%d').date()
            if jour_obj.weekday() >= 5:
                erreurs.append('Le restaurant est fermé le week-end.')
        except ValueError:
            erreurs.append('La date est obligatoire.')
            jour_obj = None

        if not erreurs and jour_obj:
            fermes = rc.jours_fermes()
            occupees = rc.places_occupees(jour)
            maximum = rc.max_personnes_pour_date(jour)
            if jour in fermes and not forcer:
                erreurs.append(f"Ce jour est noté comme fermé ({fermes[jour]}). Cochez « Forcer » pour l'enregistrer quand même.")
            elif occupees + personnes > maximum and not forcer:
                erreurs.append(f"Plus assez de place ce jour-là ({occupees}/{maximum} déjà inscrits). "
                               "Cochez « Forcer » pour l'enregistrer quand même.")

        if erreurs:
            for e in erreurs:
                flash(e, 'danger')
            return render_template('admin_ajouter_reservation.html', valeurs=valeurs,
                                   heures=rc.HEURES_SERVICE)

        reservation = Reservation(
            reference=rc.prochaine_reference(jour),
            groupe_reference=rc.nouvelle_reference_groupe(),
            nom=nom, email=email, telephone=telephone, date=jour,
            heure=request.form.get('heure') if request.form.get('heure') in rc.HEURES_SERVICE else rc.HEURES_SERVICE[0],
            personnes=personnes, message=message, statut=statut, source='telephone',
        )
        db.session.add(reservation)
        db.session.commit()
        if envoyer and email and statut == 'confirmee':
            en_arriere_plan(mail_client, 'confirmation', [donnees_reservation(reservation)])
        flash(f"Réservation enregistrée : {nom}, {personnes} pers., {rc.date_fr(jour)}.", 'success')
        return redirect(url_for('afficher_toutes_reservations'))

    return render_template('admin_ajouter_reservation.html', valeurs=valeurs, heures=rc.HEURES_SERVICE)


@app.route('/admin/fermetures', methods=['GET', 'POST'])
@login_required
def admin_fermetures():
    """Jours sans service : ils sont grisés dans le calendrier du site."""
    if request.method == 'POST':
        debut = request.form.get('debut', '').strip()
        fin = request.form.get('fin', '').strip() or debut
        motif = request.form.get('motif', '').strip()[:120] or 'Fermé'
        try:
            d1 = datetime.strptime(debut, '%Y-%m-%d').date()
            d2 = datetime.strptime(fin, '%Y-%m-%d').date()
        except ValueError:
            flash('Indiquez au moins une date de début.', 'danger')
            return redirect(url_for('admin_fermetures'))
        if d2 < d1:
            d1, d2 = d2, d1
        if (d2 - d1).days > 120:
            flash('Période trop longue (120 jours maximum à la fois).', 'danger')
            return redirect(url_for('admin_fermetures'))
        deja = {j.date for j in JourFerme.query.all()}
        ajoutes, jour = 0, d1
        while jour <= d2:
            iso = jour.isoformat()
            if jour.weekday() < 5 and iso not in deja:
                db.session.add(JourFerme(date=iso, motif=motif))
                ajoutes += 1
            jour += timedelta(days=1)
        db.session.commit()
        flash(f'{ajoutes} jour(s) de fermeture ajouté(s).', 'success')
        return redirect(url_for('admin_fermetures'))

    aujourd_hui = date.today().isoformat()
    jours = JourFerme.query.filter(JourFerme.date >= aujourd_hui).order_by(JourFerme.date).all()
    # Reservations deja prises sur un jour ferme : a prevenir
    conflits = {}
    if jours:
        for r in Reservation.query.filter(Reservation.date.in_([j.date for j in jours]),
                                          Reservation.statut != 'annulee').all():
            conflits.setdefault(r.date, []).append(r)
    return render_template('admin_fermetures.html', jours=jours, conflits=conflits, date_fr=rc.date_fr)


@app.route('/admin/fermetures/<int:id>/supprimer', methods=['POST'])
@login_required
def supprimer_fermeture(id):
    jour = JourFerme.query.get_or_404(id)
    db.session.delete(jour)
    db.session.commit()
    flash(f'Le {rc.date_fr(jour.date)} est de nouveau ouvert aux réservations.', 'success')
    return redirect(url_for('admin_fermetures'))


@app.context_processor
def outils_templates():
    return {'date_fr': rc.date_fr, 'tel_lien': rc.RESTAURANT_TEL_LIEN, 'tel_resto': rc.RESTAURANT_TEL}


@app.template_filter('heure_locale')
def heure_locale(dt, fmt='%d/%m à %H:%M'):
    """Les heures sont enregistrees en UTC : affichage a l'heure belge."""
    if not dt:
        return ''
    try:
        from datetime import timezone
        from zoneinfo import ZoneInfo
        return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Brussels')).strftime(fmt)
    except Exception:
        return dt.strftime(fmt) + ' (UTC)'


if __name__ == '__main__':
    app.run(debug=True,host='0.0.0.0',port=5000)
