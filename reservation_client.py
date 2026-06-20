from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from flask_login import login_required
import resend
from datetime import datetime
import os

# Création d'un Blueprint pour les routes de réservation
reservation_bp = Blueprint('reservation', __name__)

# Configuration de Resend
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', 're_hctYz5TC_CLWPnyiNbUHhGZn4iRZz1MVp')
EMAIL_FROM = 'onboarding@resend.dev'  # Email par défaut de Resend (à personnaliser)
EMAIL_SUBJECT = 'Confirmation de votre réservation - Restaurant Le Bouche à Oreilles'

# Plus besoin de ces fonctions - nous utilisons SQLAlchemy

@reservation_bp.route('/reserver')
def reserver():
    return render_template('reservation_form.html')

def envoyer_confirmation_email(nom, email, date, heure, personnes, reference):
    print(f"🚀 Début de l'envoi d'email à {email} pour la réservation {reference}")
    
    try:
        # Initialiser Resend
        resend.api_key = RESEND_API_KEY
        
        # Formatage de la date
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        date_formatee = date_obj.strftime('%d/%m/%Y')
        
        print(f"📅 Date formatée: {date_formatee}")
        
        # Corps du message en HTML
        html_content = f"""
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
                <p style="margin: 10px 0 0 0; color: #6c757d;"><strong>Cordialement,<br>L'équipe du Restaurant Le Bouche à Oreilles</strong></p>
            </div>
        </body>
        </html>
        """
        
        # Envoyer l'email via Resend
        params = {
            "from": EMAIL_FROM,
            "to": [email],
            "subject": EMAIL_SUBJECT,
            "html": html_content
        }
        
        print(f"� Envoi via Resend API...")
        r = resend.Emails.send(params)
        print(f"✅ Email envoyé avec succès! ID: {r['id']}")
        return True
            
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi de l'email: {str(e)}")
        import traceback
        print("📋 Traceback complet:")
        traceback.print_exc()
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
            # Importer depuis models pour éviter l'importation circulaire
            from models import db, Reservation
            
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
            
            # Envoyer l'email de confirmation via Resend
            try:
                envoyer_confirmation_email(nom, email, date, heure, personnes, reference)
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
    
    # Récupérer les détails de la réservation
    try:
        reservation = Reservation.query.filter_by(reference=reference).first()
        if reservation:
            return render_template('reservation_success.html', 
                                 reference=reservation.reference,
                                 nom=reservation.nom,
                                 date=reservation.date,
                                 heure=reservation.heure,
                                 personnes=reservation.personnes)
        else:
            return redirect(url_for('reservation.reserver'))
    except Exception as e:
        print(f"Erreur lors de la récupération de la réservation: {e}")
        return redirect(url_for('reservation.reserver'))

# Ces routes sont déjà définies dans main.py, nous les supprimons pour éviter les doublons
