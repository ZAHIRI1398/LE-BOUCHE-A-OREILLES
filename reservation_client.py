from flask import Blueprint, render_template, request, flash, redirect, url_for, session
import sqlite3
import os
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

def get_db_connection():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'reservations.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Créer la table avec la structure mise à jour
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reference TEXT UNIQUE,
        nom TEXT NOT NULL,
        email TEXT NOT NULL,
        telephone TEXT NOT NULL,
        date TEXT NOT NULL,
        heure TEXT NOT NULL,
        personnes INTEGER NOT NULL,
        message TEXT,
        statut TEXT DEFAULT 'en_attente',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Vérifier si la colonne 'reference' existe
    cursor.execute("PRAGMA table_info(reservations)")
    columns = [column[1] for column in cursor.fetchall()]
    
    # Si la colonne reference n'existe pas, on l'ajoute
    if 'reference' not in columns:
        try:
            # Ajouter la colonne reference
            cursor.execute('ALTER TABLE reservations ADD COLUMN reference TEXT UNIQUE')
            
            # Mettre à jour les références existantes
            cursor.execute("SELECT id FROM reservations")
            reservations = cursor.fetchall()
            for res in reservations:
                reference = f"RES-{res[0]:04d}"
                cursor.execute(
                    "UPDATE reservations SET reference = ? WHERE id = ?",
                    (reference, res[0])
                )
            
            conn.commit()
            print("Colonne 'reference' ajoutée avec succès.")
            
        except sqlite3.Error as e:
            print(f"Erreur lors de l'ajout de la colonne 'reference': {e}")
    
    conn.commit()
    conn.close()

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
        
        # Corps du message
        body = f"""
        <h2>Confirmation de réservation</h2>
        <p>Bonjour {nom},</p>
        <p>Nous avons bien reçu votre réservation pour le {date_formatee} à {heure}.</p>
        
        <h3>Détails de votre réservation :</h3>
        <ul>
            <li><strong>Référence :</strong> {reference}</li>
            <li><strong>Date :</strong> {date_formatee}</li>
            <li><strong>Heure :</strong> {heure}</li>
            <li><strong>Nombre de personnes :</strong> {personnes}</li>
        </ul>
        
        <p>Nous vous remercions pour votre confiance et nous réjouissons de vous accueillir dans notre établissement.</p>
        <p>Cordialement,<br>L'équipe du Restaurant Bouche à Oreille</p>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        # Connexion au serveur SMTP et envoi avec plus de logs
        print(f"Tentative d'envoi d'email à {email}...")
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            print("Connexion au serveur SMTP...")
            server.ehlo()
            print("Démarrage du chiffrement TLS...")
            server.starttls()
            server.ehlo()
            print("Authentification...")
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            print("Envoi du message...")
            server.send_message(msg)
            print("Email envoyé avec succès!")
            return True
            
    except smtplib.SMTPAuthenticationError as e:
        print(f"Erreur d'authentification SMTP: {str(e)}")
        print("Vérifiez vos identifiants SMTP et assurez-vous que l'accès aux applications moins sécurisées est activé.")
    except smtplib.SMTPException as e:
        print(f"Erreur SMTP: {str(e)}")
    except Exception as e:
        print(f"Erreur inattendue lors de l'envoi de l'email: {str(e)}")
    
    return False

@reservation_bp.route('/creer_reservation', methods=['POST'])
def creer_reservation():
    if request.method == 'POST':
        nom = request.form['nom']
        email = request.form['email']
        telephone = request.form['telephone']
        date = request.form['date']
        heure = request.form['heure']
        personnes = request.form['personnes']
        message = request.form.get('message', '')
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Insérer la réservation
            cursor.execute('''
                INSERT INTO reservations (nom, email, telephone, date, heure, personnes, message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (nom, email, telephone, date, heure, personnes, message))
            
            # Récupérer l'ID de la réservation pour la référence
            reservation_id = cursor.lastrowid
            reference = f"RES-{reservation_id:04d}"
            
            # Mettre à jour la référence de la réservation
            cursor.execute('''
                UPDATE reservations SET reference = ? WHERE id = ?
            ''', (reference, reservation_id))
            
            conn.commit()
            conn.close()
            
            # Envoyer l'email de confirmation
            envoyer_confirmation_email(nom, email, date, heure, personnes, reference)
            
            # Stocker la référence dans la session pour l'affichage
            session['derniere_reservation'] = reference
            
            flash(f'Votre réservation a été enregistrée avec succès ! Référence : {reference}', 'success')
            return redirect(url_for('reservation.confirmation'))
            
        except Exception as e:
            flash(f'Une erreur est survenue : {str(e)}', 'error')
            return redirect(url_for('reservation.reserver'))

@reservation_bp.route('/confirmation')
def confirmation():
    reference = session.get('derniere_reservation')
    if not reference:
        return redirect(url_for('reservation.reserver'))
    
    return render_template('confirmation.html', reference=reference)

@reservation_bp.route('/admin/reservations')
def admin_reservations():
    # Vérifier si l'utilisateur est admin (à implémenter selon votre système d'authentification)
    # if not current_user.is_authenticated or not current_user.is_admin:
    #     return redirect(url_for('main.accueil'))
    
    statut = request.args.get('statut')
    
    conn = get_db_connection()
    
    if statut:
        reservations = conn.execute(
            'SELECT * FROM reservations WHERE statut = ? ORDER BY date DESC, heure DESC',
            (statut,)
        ).fetchall()
    else:
        reservations = conn.execute(
            'SELECT * FROM reservations ORDER BY date DESC, heure DESC'
        ).fetchall()
    
    conn.close()
    
    return render_template('admin_reservations.html', reservations=reservations)

@reservation_bp.route('/admin/reservations/<int:id>/changer_statut', methods=['POST'])
def changer_statut(id):
    # Vérifier si l'utilisateur est admin (à implémenter selon votre système d'authentification)
    # if not current_user.is_authenticated or not current_user.is_admin:
    #     return redirect(url_for('main.accueil'))
    
    nouveau_statut = request.form.get('nouveau_statut')
    
    if nouveau_statut not in ['en_attente', 'confirmee', 'annulee']:
        flash('Statut invalide', 'error')
        return redirect(url_for('reservation.admin_reservations'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Vérifier que la réservation existe
        cursor.execute('SELECT id FROM reservations WHERE id = ?', (id,))
        if not cursor.fetchone():
            flash('Réservation introuvable', 'error')
            return redirect(url_for('reservation.admin_reservations'))
        
        # Mettre à jour le statut
        cursor.execute(
            'UPDATE reservations SET statut = ? WHERE id = ?',
            (nouveau_statut, id)
        )
        
        conn.commit()
        conn.close()
        
        flash(f'Le statut de la réservation a été mis à jour avec succès.', 'success')
        
    except Exception as e:
        flash(f'Une erreur est survenue lors de la mise à jour du statut : {str(e)}', 'error')
    
    return redirect(url_for('reservation.admin_reservations'))

# Initialisation de la base de données
init_db()
