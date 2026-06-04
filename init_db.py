import os
from pathlib import Path
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from models import db, Plat, Reservation

# Configuration de la base de données
basedir = Path(__file__).parent
DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{basedir}/data/restaurant.db')

# Utiliser psycopg2 comme driver PostgreSQL pour une meilleure stabilité SSL
if DATABASE_URL and DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg2://')

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300
}

db.init_app(app)

with app.app_context():
    try:
        print(f"🔗 Tentative de connexion à la base de données...")
        print(f"📍 DATABASE_URL: {DATABASE_URL[:50]}..." if len(DATABASE_URL) > 50 else f"📍 DATABASE_URL: {DATABASE_URL}")
        
        # Tester la connexion
        db.engine.connect()
        print("✅ Connexion à la base de données réussie!")
        
        # Créer les tables
        print("📋 Création des tables...")
        db.create_all()
        print("✅ Tables créées avec succès!")
        
        # Vérifier les tables
        print("\n📊 Vérification des tables:")
        inspector = db.inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"Tables existantes: {tables}")
        
        # Vérifier le nombre de réservations
        reservations_count = Reservation.query.count()
        print(f"📝 Nombre de réservations: {reservations_count}")
        
        # Vérifier le nombre de plats
        plats_count = Plat.query.count()
        print(f"🍽️ Nombre de plats: {plats_count}")
        
        print("\n✅ Initialisation de la base de données terminée avec succès!")
        
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation: {e}")
        import traceback
        traceback.print_exc()
