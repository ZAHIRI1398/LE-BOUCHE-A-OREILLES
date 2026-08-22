#!/usr/bin/env python3
"""
Script d'initialisation PostgreSQL pour Railway
Crée les tables et vérifie la connexion à la base de données
"""

import os
import sys
from pathlib import Path

# Ajouter le répertoire courant au chemin
sys.path.insert(0, str(Path(__file__).parent))

from main import app, db, Plat, Reservation

def initialize_database():
    """Initialiser la base de données PostgreSQL"""
    with app.app_context():
        try:
            print("🔗 Tentative de connexion à PostgreSQL...")
            
            # Afficher la configuration (masquée)
            db_url = os.environ.get('DATABASE_URL', 'SQLite (local)')
            if isinstance(db_url, str) and db_url.startswith('postgresql'):
                print(f"📍 PostgreSQL: {db_url.split('@')[1] if '@' in db_url else 'Railway'}")
            else:
                print(f"📍 Base de données: {db_url[:30]}...")
            
            # Tester la connexion
            print("⏳ Test de connexion...")
            with app.app.engine.connect() as connection:
                connection.execute("SELECT 1")
            print("✅ Connexion réussie!")
            
            # Créer les tables
            print("\n📋 Création des tables...")
            db.create_all()
            print("✅ Tables créées/mises à jour!")
            
            # Afficher les statistiques
            print("\n📊 Statistiques de la base de données:")
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            print(f"   • Tables: {', '.join(tables)}")
            
            plats_count = Plat.query.count()
            reservations_count = Reservation.query.count()
            print(f"   • Plats: {plats_count}")
            print(f"   • Réservations: {reservations_count}")
            
            print("\n✅ Initialisation PostgreSQL terminée avec succès!")
            return True
            
        except Exception as e:
            print(f"\n❌ Erreur lors de l'initialisation:")
            print(f"   {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == '__main__':
    success = initialize_database()
    sys.exit(0 if success else 1)

