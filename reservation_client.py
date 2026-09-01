from flask import Blueprint, render_template, request, flash, redirect, url_for, session, jsonify
from flask_login import login_required
import resend
from datetime import datetime
import os
from sqlalchemy import func

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

# Nombre maximum de personnes par date. Au-dela, la date
# est consideree comme complete et n'est plus reservable.
MAX_PERSONNES_PAR_DATE = 26

@reservation_bp.route('/api/occupation-dates')
def api_occupation_dates():
    """Retourne le nombre de personnes par date (reservations non annulees)."""
    try:
        from models import db, Reservation
        # On compte les personnes des reservations en_attente et confirmees
        # (les annulees ne comptent plus).
        resultats = db.session.query(
            Reservation.date,
            func.sum(Reservation.personnes).label('total')
        ).filter(
            Reservation.statut.in_(['en_attente', 'confirmee'])
        ).group_by(Reservation.date).all()

        occupation = {}
        for date, total in resultats:
            occupation[date] = int(total or 0)

        return jsonify({
            'occupation': occupation,
            'max_personnes': MAX_PERSONNES_PAR_DATE
        })
    except Exception as e:
        return jsonify({'erreur': str(e)}), 500

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

def envoyer_reception_email(nom, email, date, heure, personnes, reference):
    """Email envoyé au client dès la création de la demande, pour accuser
    réception. Il ne s'agit PAS d'une confirmation : la confirmation (ou
    annulation) sera envoyée par l'administrateur ultérieurement."""
    print(f"🚀 Début de l'envoi de l'email de réception à {email} pour la réservation {reference}")

    if not RESEND_API_KEY:
        print("⚠️  RESEND_API_KEY non configurée - email non envoyé")
        return False

    try:
        resend.api_key = RESEND_API_KEY

        date_obj = datetime.strptime(date, '%Y-%m-%d')
        date_formatee = date_obj.strftime('%d/%m/%Y')

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 10px; border-left: 4px solid #17a2b8;">
                <h2 style="color: #17a2b8; margin-top: 0;">📨 Réception de votre demande</h2>
                <p>Bonjour <strong>{nom}</strong>,</p>
                <p>Nous avons bien reçu votre demande de réservation. Elle est actuellement <strong>en attente de validation</strong> par notre équipe.</p>
            </div>

            <div style="background-color: #ffffff; padding: 20px; border: 1px solid #dee2e6; border-radius: 10px; margin: 20px 0;">
                <h3 style="color: #495057; border-bottom: 2px solid #17a2b8; padding-bottom: 10px;">Détails de votre demande</h3>
                <ul style="list-style: none; padding: 0;">
                    <li style="margin: 10px 0;"><strong>📋 Référence :</strong> {reference}</li>
                    <li style="margin: 10px 0;"><strong>📅 Date :</strong> {date_formatee}</li>
                    <li style="margin: 10px 0;"><strong>🕐 Heure :</strong> {heure}</li>
                    <li style="margin: 10px 0;"><strong>👥 Nombre de personnes :</strong> {personnes}</li>
                </ul>
            </div>

            <div style="background-color: #e9ecef; padding: 15px; border-radius: 10px; text-align: center;">
                <p style="margin: 0; color: #6c757d;">Nous reviendrons vers vous très prochainement pour confirmer votre réservation.</p>
                <p style="margin: 10px 0 0 0; color: #6c757d;"><strong>Cordialement,<br>L'équipe du Restaurant Le Bouche à Oreilles</strong></p>
            </div>
        </body>
        </html>
        """

        recipient_email = TEST_EMAIL_REDIRECT if TEST_EMAIL_REDIRECT else email

        params = {
            "from": EMAIL_FROM,
            "to": [recipient_email],
            "subject": EMAIL_SUBJECT_RECEPTION,
            "html": html_content
        }

        print(f"📧 Envoi via Resend API...")
        r = resend.Emails.send(params)
        print(f"✅ Email de réception envoyé avec succès! ID: {r['id']}")
        return True

    except Exception as e:
        print(f"❌ Erreur lors de l'envoi de l'email de réception: {str(e)}")
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
            from sqlalchemy import func

            # Verifier qu'aucune date selectionnee n'est deja complete.
            # On compte les personnes des reservations non annulees.
            dates_completes = []
            for date in dates:
                total = db.session.query(func.sum(Reservation.personnes)).filter(
                    Reservation.date == date,
                    Reservation.statut.in_(['en_attente', 'confirmee'])
                ).scalar() or 0
                if total + personnes > MAX_PERSONNES_PAR_DATE:
                    dates_completes.append(date)

            if dates_completes:
                if len(dates_completes) == 1:
                    flash(f"Désolé, cette date ({dates_completes[0]}) est déjà complète. Veuillez choisir une autre date ou nous contacter 0471 24 32 79.", 'error')
                else:
                    flash(f"Désolé, ces dates sont déjà complètes : {', '.join(dates_completes)}. Veuillez choisir d'autres dates.", 'error')
                return redirect(url_for('reservation.reserver'))

            # Reference sequentielle par date : Table1, Table2, etc.
            # Le compteur se reinitialise pour chaque date.
            groupe_count = Reservation.query.count()
            groupe_reference = f'Groupe{groupe_count + 1}'

            reservations_creees = []

            for date in dates:
                # Trouver le numero de table le plus eleve pour cette date
                # pour eviter les collisions (en cas de suppression ou de
                # reservations simultanees).
                import re
                tables_existantes = Reservation.query.filter_by(date=date).all()
                numeros = []
                for r in tables_existantes:
                    match = re.match(r'Table(\d+)-', r.reference)
                    if match:
                        numeros.append(int(match.group(1)))
                prochain_num = (max(numeros) + 1) if numeros else 1

                # Generer une reference unique. Si elle existe deja (cas
                # rare de concurrence), on incremente jusqu'a en trouver une
                # de libre.
                while True:
                    reference = f'Table{prochain_num}-{date}'
                    existe = Reservation.query.filter_by(reference=reference).first()
                    if not existe:
                        break
                    prochain_num += 1

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
            # envoyer_reception_email() gère elle-même le cas où Resend
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
                    # Ne pas faire échouer la création de la réservation
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

