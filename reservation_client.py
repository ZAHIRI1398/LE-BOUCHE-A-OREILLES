from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from flask_login import login_required
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# Création d'un Blueprint pour les routes de réservation
reservation_bp = Blueprint('reservation', __name__)

# Configuration de l'email (à remplacer par vos informations SMTP)
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_USERNAME = 'jemathsia@gmail.com'  # À remplacer
SMTP_PASSWORD = 'uwvq aiqx caos xfcg'     # À remplacer
EMAIL_FROM = 'jemathsia@gmail.com'     # À remplacer
EMAIL_SUBJECT = 'Confirmation de votre réservation - Restaurant Bouche à Oreille'

# Plus besoin de ces fonctions - nous utilisons SQLAlchemy

@reservation_bp.route('/reserver')
def reserver():
    return render_template('reservation_form.html')

def envoyer_confirmation_email(nom, email, date, heure, personnes, reference):
    try:
        # Formatage de la date
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        date_formatee = date_obj.strftime('%d/%m/%Y')
        
        # Création du message
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = email
        msg['Subject'] = EMAIL_SUBJECT
        
        # Corps du message en HTML
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 10px; border-left: 4px solid #28a745;">
                <h2 style="color: #28a745; margin-top: 0;">✅ Confirmation de réservation</h2>
                <p>Bonjour <strong>{nom}</strong>,</p>
                <p>Nous avons bien reçu votre réservation et nous vous en remercions.</p>
            </div>
            
            <div style="background-color: #ffffff; padding: 20px; border: 1px solid #dee2e6; border-radius: 10px; margin: 20px 0;">
                <h3 style="color: #495057; border-bottom: 2px solid #28a745; padding-bottom: 10px;">Détails de votre réservation</h3>
                <ul style="list-style: none; padding: 0;">
                    <li style="margin: 10px 0;"><strong>📋 Référence :</strong> {reference}</li>
                    <li style="margin: 10px 0;"><strong>📅 Date :</strong> {date_formatee}</li>
                    <li style="margin: 10px 0;"><strong>🕐 Heure :</strong> {heure}</li>
                    <li style="margin: 10px 0;"><strong>👥 Nombre de personnes :</strong> {personnes}</li>
                </ul>
            </div>
            
            <div style="background-color: #e9ecef; padding: 15px; border-radius: 10px; text-align: center;">
                <p style="margin: 0; color: #6c757d;">Nous vous remercions pour votre confiance et nous réjouissons de vous accueillir dans notre établissement.</p>
                <p style="margin: 10px 0 0 0; color: #6c757d;"><strong>Cordialement,<br>L'équipe du Restaurant Bouche à Oreille</strong></p>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        # Connexion au serveur SMTP et envoi avec retry
        print(f"Tentative d'envoi d'email à {email}...")
        
        # Configuration SMTP avec retry
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
                    print(f"Tentative {attempt + 1}/{max_retries} - Connexion au serveur SMTP...")
                    server.ehlo()
                    print("Démarrage du chiffrement TLS...")
                    server.starttls()
                    server.ehlo()
                    print("Authentification...")
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                    print("Envoi du message...")
                    server.send_message(msg)
                    print("✅ Email envoyé avec succès!")
                    return True
                    
            except smtplib.SMTPAuthenticationError as e:
                print(f"❌ Erreur d'authentification SMTP: {str(e)}")
                print("Vérifiez vos identifiants SMTP et assurez-vous que l'accès aux applications moins sécurisées est activé.")
                break  # Pas de retry pour les erreurs d'authentification
            except smtplib.SMTPException as e:
                print(f"⚠️ Erreur SMTP (tentative {attempt + 1}): {str(e)}")
                if attempt == max_retries - 1:
                    break
                continue
            except Exception as e:
                print(f"⚠️ Erreur inattendue (tentative {attempt + 1}): {str(e)}")
                if attempt == max_retries - 1:
                    break
                continue
        
        return False
            
    except Exception as e:
        print(f"❌ Erreur critique lors de la préparation de l'email: {str(e)}")
        return False

@reservation_bp.route('/creer_reservation', methods=['POST'])
def creer_reservation():
    if request.method == 'POST':
        nom = request.form['nom']
        email = request.form['email']
        telephone = request.form['telephone']
        date = request.form['date']
        heure = request.form['heure']
        personnes = int(request.form['personnes'])
        message = request.form.get('message', '')
        
        try:
            # Importer ici pour éviter l'importation circulaire
            from main import db, Reservation
            
            # Générer une référence unique
            import random
            import string
            chars = string.ascii_uppercase + string.digits
            reference = 'RES-' + ''.join(random.choices(chars, k=8))
            
            # Créer la réservation avec SQLAlchemy
            nouvelle_reservation = Reservation(
                reference=reference,
                nom=nom,
                email=email,
                telephone=telephone,
                date=date,
                heure=heure,
                personnes=personnes,
                message=message,
                statut='en_attente'
            )
            
            db.session.add(nouvelle_reservation)
            db.session.commit()
            
            # Envoyer l'email de confirmation
            try:
                envoyer_confirmation_email(nom, email, date, heure, personnes, reference)
                print("Email de confirmation envoyé avec succès")
            except Exception as email_error:
                print(f"Erreur lors de l'envoi de l'email: {email_error}")
                # Ne pas échouer la réservation si l'email ne s'envoie pas
            
            # Stocker la référence dans la session pour l'affichage
            session['derniere_reservation'] = reference
            
            flash(f'Votre réservation a été enregistrée avec succès ! Référence : {reference}', 'success')
            return redirect(url_for('confirmation', reference=reference))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Une erreur est survenue : {str(e)}', 'error')
            return redirect(url_for('reservation.reserver'))

@reservation_bp.route('/confirmation')
def confirmation():
    reference = session.get('derniere_reservation')
    if not reference:
        return redirect(url_for('reservation.reserver'))
    
    return render_template('confirmation.html', reference=reference)

# Ces routes sont déjà définies dans main.py, nous les supprimons pour éviter les doublons
