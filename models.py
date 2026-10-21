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

class MenuDocument(db.Model):
    __tablename__ = 'menu_documents'

    id = db.Column(db.Integer, primary_key=True)
    nom_fichier = db.Column(db.String(200), nullable=False)
    contenu = db.Column(db.LargeBinary, nullable=False)
    date_upload = db.Column(db.DateTime, default=datetime.utcnow)
    pages = db.relationship(
        'MenuDocumentPage', backref='document', cascade='all, delete-orphan',
        order_by='MenuDocumentPage.numero',
    )

class MenuDocumentPage(db.Model):
    __tablename__ = 'menu_document_pages'

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('menu_documents.id'), nullable=False)
    numero = db.Column(db.Integer, nullable=False)
    image = db.Column(db.LargeBinary, nullable=False)

class Reservation(db.Model):
    __tablename__ = 'reservations'
    
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(30), unique=True, nullable=False)
    groupe_reference = db.Column(db.String(20))
    nom = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    telephone = db.Column(db.String(20))
    date = db.Column(db.String(20), nullable=False)
    heure = db.Column(db.String(10), nullable=False)
    personnes = db.Column(db.Integer, nullable=False)
    message = db.Column(db.Text)
    statut = db.Column(db.String(20), default='en_attente')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # 'web' (formulaire du site) ou 'telephone' (saisie par l'equipe)
    source = db.Column(db.String(20), default='web')

class EmailEnvoi(db.Model):
    """Journal des emails : chaque tentative d'envoi est notee ici, pour
    que l'equipe voie dans l'admin si un client a bien recu son email
    (et le rappelle par telephone si ce n'est pas le cas)."""
    __tablename__ = 'email_envois'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    type_mail = db.Column(db.String(30), nullable=False)   # reception, confirmation, annulation, notification_resto
    destinataire = db.Column(db.String(120))
    reference = db.Column(db.String(30), index=True)       # reference de la reservation ou du groupe
    statut = db.Column(db.String(10), nullable=False)      # envoye / echec
    canal = db.Column(db.String(20))                       # smtp, brevo, resend
    erreur = db.Column(db.Text)

class JourFerme(db.Model):
    """Jours ou le restaurant ne prend pas de reservation (conges,
    stages, journees pedagogiques...)."""
    __tablename__ = 'jours_fermes'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), unique=True, nullable=False)  # AAAA-MM-JJ
    motif = db.Column(db.String(120))
