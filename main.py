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
import PyPDF2
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask_sqlalchemy import SQLAlchemy
from pathlib import Path

# Importation des modèles
from models import db, Plat, Reservation

# Importation du blueprint de réservation
from reservation_client import reservation_bp

app = Flask(__name__)
app.register_blueprint(reservation_bp, url_prefix='/reservation')
app.secret_key = 'votre_cle_secrète_plus_secrete_encore_123456'
# Configuration de la base de données
basedir = Path(__file__).parent
DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{basedir}/data/restaurant.db')

# Utiliser pg8000 comme driver PostgreSQL pour éviter les problèmes de compatibilité
if DATABASE_URL and DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+pg8000://')

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

def creer_tables():
    try:
        with app.app_context():
            db.create_all()
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
        reservations = Reservation.query.order_by(Reservation.date.desc(), Reservation.heure.desc()).all()
        
        # Ajouter la date et l'heure actuelles pour l'impression
        return render_template('admin_reservations.html', 
                             reservations=reservations,
                             email=None,
                             now=datetime.now())
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération des réservations: {e}")
        flash("Une erreur est survenue lors de la récupération des réservations.", "error")
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
        reservation.statut = nouveau_statut
        db.session.commit()
        flash(f'Le statut de la réservation a été mis à jour avec succès.', 'success')
    except Exception as e:
        app.logger.error(f"Erreur lors de la mise à jour du statut: {e}")
        flash('Une erreur est survenue lors de la mise à jour du statut.', 'error')
    
    return redirect(url_for('afficher_toutes_reservations'))

@app.route('/menu')
@app.route('/carte')
def menu():
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
            
        # Si l'utilisateur est admin, on affiche la vue admin
        if session.get('admin_logged_in'):
            return render_template('admin_menu.html', 
                                menu_par_categorie=menu_par_categorie)
        # Sinon, on affiche la vue client
        return render_template('menu.html', 
                            menu_par_categorie=menu_par_categorie)
    except Exception as e:
        app.logger.error(f"Erreur dans la route menu: {str(e)}")
        flash('Une erreur est survenue lors du chargement du menu.', 'error')
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
            
        return render_template('admin_menu.html', 
                            menu_par_categorie=menu_par_categorie)
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

import random
import string

def generate_reference():
    """Generate a unique reference for reservations"""
    chars = string.ascii_uppercase + string.digits
    return 'RES-' + ''.join(random.choices(chars, k=8))

def extraire_plats_depuis_texte(texte):
    """
    Extrait les plats, descriptions et prix à partir du texte brut du PDF
    Cette fonction est basique et devra être adaptée selon le format de votre PDF
    """
    plats = []
    # Ceci est un exemple très basique - à adapter selon votre format de PDF
    # On cherche les lignes qui ressemblent à des plats (nom, description, prix)
    lignes = [ligne.strip() for ligne in texte.split('\n') if ligne.strip()]
    
    i = 0
    while i < len(lignes):
        ligne = lignes[i]
        # Si la ligne contient un prix (format XX.XX€ ou XX,XX€)
        match = re.search(r'(\d+[,\.]\d+)\s*€?$', ligne)
        if match:
            prix = match.group(1).replace(',', '.')
            try:
                prix = float(prix)
                # On suppose que la ligne précédente est la description
                # et celle d'avant est le nom
                if i >= 2:
                    nom = lignes[i-2]
                    description = lignes[i-1]
                    plats.append({
                        'nom': nom,
                        'description': description,
                        'prix': prix,
                        'categorie': 'plat_principal'  # Par défaut
                    })
            except ValueError:
                pass
        i += 1
    
    return plats
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
                # Lire le contenu du PDF
                pdf_reader = PyPDF2.PdfReader(fichier)
                texte_complet = ""
                
                # Extraire le texte de chaque page
                for page in pdf_reader.pages:
                    texte_complet += page.extract_text() + "\n"
                
                # Extraire les plats du texte
                plats = extraire_plats_depuis_texte(texte_complet)
                
                # Enregistrer les plats dans la base de données
                plats_ajoutes = 0
                
                for plat in plats:
                    try:
                        nouveau_plat = Plat(
                            nom=plat['nom'],
                            description=plat['description'],
                            prix=plat['prix'],
                            categorie=plat['categorie']
                        )
                        db.session.add(nouveau_plat)
                        plats_ajoutes += 1
                    except Exception:
                        # Ignorer les doublons
                        pass
                
                db.session.commit()
                
                flash(f'Import réussi : {plats_ajoutes} plats ajoutés au menu', 'success')
                return redirect(url_for('admin_menu'))
                
            except Exception as e:
                app.logger.error(f'Erreur lors de l\'import du menu : {str(e)}')
                flash('Une erreur est survenue lors de l\'import du menu', 'error')
                return redirect(request.url)
        else:
            flash('Format de fichier non supporté. Veuillez sélectionner un fichier PDF.', 'error')
            return redirect(request.url)
    
    return render_template('importer_menu.html')

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
            flash('La réservation a été mise à jour avec succès.', 'success')
            return redirect(url_for('afficher_toutes_reservations'))
        
        # Pour les requêtes GET, afficher le formulaire de modification
        return render_template('modifier_reservation.html', reservation=reservation)
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur lors de la modification de la réservation: {str(e)}")
        flash('Une erreur est survenue lors de la modification de la réservation.', 'error')
        return redirect(url_for('afficher_toutes_reservations'))

@app.route('/confirmation/<reference>')
def confirmation(reference):
    try:
        reservation = Reservation.query.filter_by(reference=reference).first()
        
        if reservation is None:
            flash('Réservation non trouvée.', 'error')
            return redirect(url_for('accueil'))
            
        # Format the date for display
        if reservation.date:
            try:
                date_obj = datetime.strptime(str(reservation.date), '%Y-%m-%d')
                reservation.date_formatted = date_obj.strftime('%d/%m/%Y')
            except (ValueError, TypeError) as e:
                app.logger.error(f"Erreur de formatage de date: {e}")
                reservation.date_formatted = reservation.date
                
        return render_template('confirmation.html', reservation=reservation)
        
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération de la réservation: {str(e)}")
        flash('Une erreur est survenue lors de la récupération de votre réservation.', 'error')
        return redirect(url_for('accueil'))
   

if __name__ == '__main__':
    app.run(debug=True,host='0.0.0.0',port=5000)