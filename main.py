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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask_sqlalchemy import SQLAlchemy
from pathlib import Path

# Importation des modèles
from models import db, Plat, Reservation, MenuDocument, MenuDocumentPage

# Importation du blueprint de réservation
from reservation_client import (
    reservation_bp,
    envoyer_confirmation_email,
    envoyer_annulation_email,
)

app = Flask(__name__)
app.register_blueprint(reservation_bp, url_prefix='/reservation')
app.secret_key = 'votre_cle_secrète_plus_secrete_encore_123456'
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
        # Etendre la colonne reference a VARCHAR(30) pour le format Table1-2026-08-28
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

# Configuration de l'admin
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"  # À changer en production

# Protection des routes admin
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# Route de connexion admin
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('afficher_toutes_reservations'))
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
        
        reservations = Reservation.query.order_by(Reservation.date.desc(), Reservation.heure.desc()).all()
        
        # Ajouter la date et l'heure actuelles pour l'impression
        return render_template('admin_reservations.html', 
                             reservations=reservations,
                             email=None,
                             now=datetime.now())
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
        # et seulement lorsque le statut change réellement.
        if nouveau_statut != ancien_statut:
            try:
                if nouveau_statut == 'confirmee':
                    envoyer_confirmation_email(
                        reservation.nom, reservation.email, reservation.date,
                        reservation.heure, reservation.personnes, reservation.reference
                    )
                elif nouveau_statut == 'annulee':
                    envoyer_annulation_email(
                        reservation.nom, reservation.email, reservation.date,
                        reservation.heure, reservation.personnes, reservation.reference
                    )
            except Exception as email_error:
                # Ne pas échouer la mise à jour du statut si l'email ne part pas
                app.logger.error(f"Erreur lors de l'envoi de l'email: {email_error}")

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
            # la réservation à "confirmee" ou "annulee".
            if reservation.statut != ancien_statut:
                try:
                    if reservation.statut == 'confirmee':
                        envoyer_confirmation_email(
                            reservation.nom, reservation.email, reservation.date,
                            reservation.heure, reservation.personnes, reservation.reference
                        )
                    elif reservation.statut == 'annulee':
                        envoyer_annulation_email(
                            reservation.nom, reservation.email, reservation.date,
                            reservation.heure, reservation.personnes, reservation.reference
                        )
                except Exception as email_error:
                    app.logger.error(f"Erreur lors de l'envoi de l'email: {email_error}")

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

        return render_template('confirmation_groupe.html', reservations=reservations, premiere=reservations[0])

    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération de la réservation: {str(e)}")
        flash('Une erreur est survenue lors de la récupération de votre réservation.', 'error')
        return redirect(url_for('accueil'))
   

if __name__ == '__main__':
    app.run(debug=True,host='0.0.0.0',port=5000)
