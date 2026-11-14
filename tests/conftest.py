"""Configuration des tests : base SQLite temporaire, emails simulés.

Lancer avec :  pip install pytest  puis  python -m pytest tests
"""
import os
import secrets
import sys
import tempfile
from datetime import date, timedelta

import pytest

_DOSSIER = tempfile.mkdtemp(prefix='resto-tests-')
os.environ['DATABASE_URL'] = os.environ.get('TEST_DATABASE_URL') or f"sqlite:///{os.path.join(_DOSSIER, 'tests.db')}"
os.environ['SECRET_KEY'] = 'cle-de-test'
os.environ['ADMIN_USERNAME'] = 'admin'
MOT_DE_PASSE_TEST = secrets.token_urlsafe(16)   # tiré au hasard à chaque lancement des tests
os.environ['ADMIN_PASSWORD'] = MOT_DE_PASSE_TEST
os.environ['RESTAURANT_EMAIL'] = 'resto@example.org'
os.environ.pop('TEST_EMAIL_REDIRECT', None)
os.environ['BREVO_API_KEY'] = 'cle-factice'      # un canal "configuré" (remplacé par le faux envoi)
os.environ.pop('RESEND_API_KEY', None)
os.environ.pop('SMTP_USER', None)
os.environ.pop('CONFIRMATION_AUTOMATIQUE', None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
import reservation_client as rc  # noqa: E402
from models import db, Reservation, EmailEnvoi, JourFerme  # noqa: E402


class FauxEnvoi:
    """Remplace l'envoi réel : garde les emails en mémoire."""

    def __init__(self):
        self.envoyes = []
        self.echouer = False

    def __call__(self, destinataire, sujet, html_content, texte='', repondre_a=None):
        if self.echouer:
            return False, None, 'brevo : HTTP Error 401: Unauthorized'
        self.envoyes.append({'a': destinataire, 'sujet': sujet, 'html': html_content,
                             'texte': texte, 'repondre_a': repondre_a})
        return True, 'test', None

    def pour(self, adresse):
        return [m for m in self.envoyes if m['a'] == adresse]


@pytest.fixture
def app(monkeypatch):
    application = main.app
    application.config.update(TESTING=True, EMAILS_SYNCHRONES=True)
    with application.app_context():
        db.drop_all()
        db.create_all()
    rc._compteurs.clear()
    monkeypatch.setattr(rc, 'CONFIRMATION_AUTOMATIQUE', False)
    yield application


@pytest.fixture
def mails(monkeypatch):
    faux = FauxEnvoi()
    monkeypatch.setattr(rc, 'envoyer_email', faux)
    return faux


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(app):
    c = app.test_client()
    r = c.post('/admin/login', data={'username': 'admin', 'password': MOT_DE_PASSE_TEST})
    assert r.status_code == 302
    return c


def jours_ouvrables(n, depart=1):
    """n prochains jours de semaine, à partir de demain (ou depart jours)."""
    jours, d = [], date.today() + timedelta(days=depart)
    while len(jours) < n:
        if d.weekday() < 5:
            jours.append(d.isoformat())
        d += timedelta(days=1)
    return jours


def prochain_samedi():
    d = date.today() + timedelta(days=1)
    while d.weekday() != 5:
        d += timedelta(days=1)
    return d.isoformat()


def formulaire(**valeurs):
    donnees = {'nom': 'Jeanne Dupont', 'email': 'jeanne@example.org', 'telephone': '0470 12 34 56',
               'heure': '11:55', 'personnes': '2', 'dates': jours_ouvrables(1)[0], 'message': ''}
    donnees.update(valeurs)
    return donnees
