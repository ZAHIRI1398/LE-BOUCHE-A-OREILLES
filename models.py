from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Initialisation de SQLAlchemy
db = SQLAlchemy()

# Modèles de données
class Plat(db.Model):
    __tablename__ = 'menu'
    
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    prix = db.Column(db.Float, nullable=False)
    categorie = db.Column(db.String(50), nullable=False)
    image = db.Column(db.String(200))

class Reservation(db.Model):
    __tablename__ = 'reservations'
    
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(20), unique=True, nullable=False)
    nom = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    telephone = db.Column(db.String(20))
    date = db.Column(db.String(20), nullable=False)
    heure = db.Column(db.String(10), nullable=False)
    personnes = db.Column(db.Integer, nullable=False)
    message = db.Column(db.Text)
    statut = db.Column(db.String(20), default='en_attente')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
