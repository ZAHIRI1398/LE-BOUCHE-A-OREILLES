#!/usr/bin/env python3
"""
Script de test pour diagnostiquer les problèmes d'envoi d'email
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# Configuration de l'email (même que dans reservation_client.py)
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_USERNAME = 'adamyamine1398@gmail.com'
SMTP_PASSWORD = 'baky mvuv lfpr giuv'
EMAIL_FROM = 'adamyamine1398@gmail.com'

def test_email_connection():
    """Test la connexion au serveur SMTP"""
    print("🧪 Test de connexion au serveur SMTP...")
    
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.set_debuglevel(1)
            
            print("🔗 Connexion à Gmail...")
            server.ehlo()
            
            print("🔐 Démarrage TLS...")
            server.starttls()
            server.ehlo()
            
            print("🔑 Test d'authentification...")
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            print("✅ Authentification réussie!")
            
            return True
            
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Erreur d'authentification: {e}")
        print("\n💡 Solutions possibles:")
        print("1. Allez dans votre compte Gmail")
        print("2. Paramètres > Sécurité")
        print("3. Activez 'Accès aux applications moins sécurisées'")
        print("4. Ou créez un mot de passe d'application:")
        print("   - Compte Google > Sécurité > Mot de passe des applications")
        print("   - Générez un nouveau mot de passe pour cette application")
        return False
        
    except Exception as e:
        print(f"❌ Erreur de connexion: {e}")
        return False

def test_email_sending():
    """Test l'envoi d'un email à vous-même"""
    print("\n🧪 Test d'envoi d'email...")
    
    try:
        # Créer un email de test
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_FROM  # Envoyer à vous-même pour tester
        msg['Subject'] = f"🧪 Test Email - {datetime.now().strftime('%H:%M:%S')}"
        
        body = """
        <html>
        <body>
            <h2>🧪 Email de test</h2>
            <p>Ceci est un email de test pour vérifier que l'envoi fonctionne.</p>
            <p>Si vous recevez cet email, la configuration SMTP est correcte!</p>
            <p>Envoyé le: {}</p>
        </body>
        </html>
        """.format(datetime.now().strftime('%d/%m/%Y %H:%M:%S'))
        
        msg.attach(MIMEText(body, 'html'))
        
        # Envoyer l'email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.set_debuglevel(1)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            
            print("📤 Envoi de l'email de test...")
            server.send_message(msg)
            print("✅ Email de test envoyé avec succès!")
            print(f"📧 Vérifiez votre boîte de réception: {EMAIL_FROM}")
            
            return True
            
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("=" * 60)
    print("🔧 DIAGNOSTIC DU SYSTÈME D'EMAIL")
    print("=" * 60)
    
    # Test 1: Connexion SMTP
    if not test_email_connection():
        print("\n❌ Le test de connexion a échoué. Corrigez les problèmes d'authentification avant de continuer.")
        return
    
    # Test 2: Envoi d'email
    if not test_email_sending():
        print("\n❌ Le test d'envoi a échoué.")
        return
    
    print("\n🎉 Tous les tests ont réussi!")
    print("✅ Le système d'email est configuré correctement.")
    print("✅ Les emails de réservation devraient maintenant fonctionner.")

if __name__ == "__main__":
    main()
