from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from flask_login import login_required
import resend
from datetime import datetime
import os

# Création d'un Blueprint pour les routes de réservation
reservation_bp = Blueprint('reservation', __name__)

# Configuration de Resend
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'contact@leboucheaoreilles.be')
EMAIL_SUBJECT = 'Confirmation de votre réservation - Restaurant Le Bouche à Oreilles'
EMAIL_SUBJECT_ANNULATION = 'Annulation de votre réservation - Restaurant Le Bouche à Oreilles'
EMAIL_SUBJECT_RECEPTION = 'Réception de votre demande de réservation - Restaurant Le Bouche à Oreilles'

# Pour les tests avec Resend gratuit, rediriger tous les emails vers votre adresse
TEST_EMAIL_REDIRECT = os.environ.get('TEST_EMAIL_REDIRECT', '')

@reservation_bp.route('/reserver')
def reserver():
    return render_template('reservation_form.html')

def envoyer_confirmation_email(nom, email, date, heure, personnes, reference):
    print(f"🚀 Début de l'envoi d'email à {email} pour la réservation {reference}")
    
    # Vérifier que la clé API est configurée
    if not RESEND_API_KEY:
        print("⚠️  RESEND_API_KEY non configurée - email non envoyé")
        print("📝 Pour configurer Resend:")
        print("   1. Allez sur https://resend.com")
        print("   2. Créez une clé API")
        print("   3. Ajoutez RESEND_API_KEY dans les variables d'environnement Railway")
        return False
    
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
        
        # Pour les tests Resend gratuit, rediriger vers votre email
        recipient_email = TEST_EMAIL_REDIRECT if TEST_EMAIL_REDIRECT else email
        
        # Envoyer l'email via Resend
        params = {
            "from": EMAIL_FROM,
            "to": [recipient_email],
            "subject": EMAIL_SUBJECT,
            "html": html_content
        }
        
        print(f"📧 Envoi via Resend API...")
        r = resend.Emails.send(params)
        print(f"✅ Email envoyé avec succès! ID: {r['id']}")
        return True
            
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi de l'email: {str(e)}")
        import traceback
        print("📋 Traceback complet:")
        traceback.print_exc()
        return False
def envoyer_annulation_email(nom, email, date, heure, personnes, reference):
    print(f"🚀 Début de l'envoi de l'email d'annulation à {email} pour la réservation {reference}")

    # Vérifier que la clé API est configurée
    if not RESEND_API_KEY:
        print("⚠️  RESEND_API_KEY non configurée - email non envoyé")
        return False

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
            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 10px; border-left: 4px solid #dc3545;">
                <h2 style="color: #dc3545; margin-top: 0;">❌ Annulation de réservation</h2>
                <p>Bonjour <strong>{nom}</strong>,</p>
                <p>Nous sommes au regret de vous informer que votre réservation a été annulée.</p>
            </div>

            <div style="background-color: #ffffff; padding: 20px; border: 1px solid #dee2e6; border-radius: 10px; margin: 20px 0;">
                <h3 style="color: #495057; border-bottom: 2px solid #dc3545; padding-bottom: 10px;">Détails de la réservation annulée</h3>
                <ul style="list-style: none; padding: 0;">
                    <li style="margin: 10px 0;"><strong>📋 Référence :</strong> {reference}</li>
                    <li style="margin: 10px 0;"><strong>📅 Date :</strong> {date_formatee}</li>
                    <li style="margin: 10px 0;"><strong>🕐 Heure :</strong> {heure}</li>
                    <li style="margin: 10px 0;"><strong>👥 Nombre de personnes :</strong> {personnes}</li>
                </ul>
            </div>

            <div style="background-color: #e9ecef; padding: 15px; border-radius: 10px; text-align: center;">
                <p style="margin: 0; color: #6c757d;">Pour toute question ou pour effectuer une nouvelle réservation, n'hésitez pas à nous contacter.</p>
                <p style="margin: 10px 0 0 0; color: #6c757d;"><strong>Cordialement,<br>L'équipe du Restaurant Le Bouche à Oreilles</strong></p>
            </div>
        </body>
        </html>
        """

        # Pour les tests Resend gratuit, rediriger vers votre email
        recipient_email = TEST_EMAIL_REDIRECT if TEST_EMAIL_REDIRECT else email

        # Envoyer l'email via Resend
        params = {
            "from": EMAIL_FROM,
            "to": [recipient_email],
            "subject": EMAIL_SUBJECT_ANNULATION,
            "html": html_content
        }

        print(f"📧 Envoi via Resend API...")
        r = resend.Emails.send(params)
        print(f"✅ Email d'annulation envoyé avec succès! ID: {r['id']}")
        return True

    except Exception as e:
        print(f"❌ Erreur lors de l'envoi de l'email d'annulation: {str(e)}")
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
        heure = request.form['heure']
        personnes = int(request.form['personnes'])
        message = request.form.get('message', '')

        # Plusieurs dates peuvent être choisies en une seule réservation
        dates_brutes = request.form.get('dates', '')
        dates = sorted(set(d.strip() for d in dates_brutes.split(',') if d.strip()))

        if not dates:
            flash('Veuillez sélectionner au moins une date.', 'error')
            return redirect(url_for('reservation.reserver'))

        try:
            # Importer depuis models pour éviter l'importation circulaire
            from models import db, Reservation

            import random
            import string
            chars = string.ascii_uppercase + string.digits
            groupe_reference = 'GRP-' + ''.join(random.choices(chars, k=8))

            reservations_creees = []

            for date in dates:
                reference = 'RES-' + ''.join(random.choices(chars, k=8))
                nouvelle_reservation = Reservation(
                    reference=reference,
                    groupe_reference=groupe_reference,
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
                reservations_creees.append(nouvelle_reservation)

            db.session.commit()

            # Envoyer immédiatement un email de confirmation de réception au
            # client pour chaque date réservée, sans attendre la validation
            # de l'administrateur. L'admin recevra toujours un email dédié
            # lorsqu'il confirme ou annule chaque date individuellement.
            # envoyer_confirmation_email() gère elle-même le cas où Resend
            # n'est pas configuré (log d'un avertissement, pas d'exception).
           for reservation in reservations_creees:
                try:
                    envoyer_reception_email(
                        reservation.nom,
                        reservation.email,
                        reservation.date,
                        reservation.heure,
                        reservation.personnes,
                        reservation.reference
                    )
                except Exception as email_error:
                    # Ne pas ffor reservation in reservations_creees:aire échouer la création de la réservation
                    # si l'envoi de l'email de réception échoue.
                    print(f"⚠️  Erreur lors de l'envoi de l'email de réception au client: {email_error}")

            session['derniere_reservation'] = groupe_reference

            if len(dates) == 1:
                flash('Votre réservation a été enregistrée avec succès !', 'success')
            else:
                flash(f'Votre réservation a été enregistrée avec succès pour {len(dates)} dates !', 'success')
            return redirect(url_for('confirmation_groupe', groupe_reference=groupe_reference))

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
        from models import Reservation
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

