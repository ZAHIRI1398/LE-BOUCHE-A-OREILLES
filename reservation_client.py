from flask import Blueprint, render_template, request, flash, redirect, url_for, session, jsonify, current_app
from flask_login import login_required
import resend
import smtplib
import threading
import traceback
import json
import re
import html
import time
import secrets
import urllib.request
from collections import defaultdict, deque
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, date, timedelta
import os
from sqlalchemy import func

# Création d'un Blueprint pour les routes de réservation
reservation_bp = Blueprint('reservation', __name__)

# ---------------------------------------------------------------------------
# Réglages (variables d'environnement Railway)
# ---------------------------------------------------------------------------

# Configuration de Resend
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'contact@leboucheaoreilles.be')

# Pour les tests uniquement : redirige TOUS les emails vers une seule adresse.
# Si cette variable reste remplie en production, aucun client ne reçoit ses
# emails : l'admin affiche donc un bandeau rouge tant qu'elle est active.
TEST_EMAIL_REDIRECT = os.environ.get('TEST_EMAIL_REDIRECT', '')

# Envoi via le SMTP de l'email de l'ecole (gratuit). Si SMTP_USER et
# SMTP_PASSWORD sont definis, les emails partent par ce canal ; sinon
# on retombe sur Brevo puis Resend.
# Attention : Railway bloque le SMTP sur les offres Free/Trial/Hobby.
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
# Expediteur SMTP : le compte Gmail par defaut (Gmail reecrit le From de
# toute facon). EMAIL_FROM reste reserve a Resend et doit utiliser un
# domaine verifie (ex: contact@leboucheaoreilles.be).
SMTP_FROM = os.environ.get('SMTP_FROM', '')

# Envoi via l'API HTTPS de Brevo (300 emails/jour gratuits). Fonctionne
# la ou le SMTP est bloque (ex: Railway Hobby bloque les ports SMTP).
# L'expediteur doit etre un expéditeur/domaine valide dans Brevo.
BREVO_API_KEY = os.environ.get('BREVO_API_KEY', '')
BREVO_FROM = os.environ.get('BREVO_FROM', '')
BREVO_FROM_NAME = os.environ.get('BREVO_FROM_NAME', 'Restaurant Le Bouche à Oreilles')

# Adresse du restaurant : elle reçoit une copie de chaque nouvelle
# réservation, et les clients qui répondent à un email tombent dessus.
RESTAURANT_EMAIL = os.environ.get('RESTAURANT_EMAIL', 'stbernadette.restaurant@gmail.com')
RESTAURANT_TEL = os.environ.get('RESTAURANT_TEL', '0471 24 32 79')

# Confirmation automatique : s'il reste de la place, la réservation est
# confirmée tout de suite (le client reçoit directement sa confirmation).
# Les groupes de plus de 10 personnes restent toujours à valider à la main.
# Mettre CONFIRMATION_AUTOMATIQUE=1 dans Railway pour l'activer.
CONFIRMATION_AUTOMATIQUE = os.environ.get('CONFIRMATION_AUTOMATIQUE', '0') == '1'

# Garde-fous du formulaire public
MAX_DATES_PAR_DEMANDE = 10
MAX_PERSONNES_EN_LIGNE = 10       # au-dela : demande de groupe, validee a la main
GROUPE_MAX = 60
HEURES_SERVICE = ('11:55',)
MOIS_MAX_AVANCE = 6               # meme valeur que dans le calendrier du formulaire
MAX_DEMANDES_PAR_HEURE_ET_IP = 5

EMAIL_SUBJECT = 'Confirmation de votre réservation - Restaurant Le Bouche à Oreilles'
EMAIL_SUBJECT_ANNULATION = 'Annulation de votre réservation - Restaurant Le Bouche à Oreilles'
EMAIL_SUBJECT_RECEPTION = 'Réception de votre demande de réservation - Restaurant Le Bouche à Oreilles'

TYPES_MAIL_CLIENT = ('reception', 'confirmation', 'annulation')

if TEST_EMAIL_REDIRECT:
    print(f"⚠️  TEST_EMAIL_REDIRECT est actif : tous les emails partent vers {TEST_EMAIL_REDIRECT} et AUCUN client ne les reçoit.")


# ---------------------------------------------------------------------------
# Petits outils
# ---------------------------------------------------------------------------

JOURS_FR = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def date_fr(iso, avec_jour=True):
    """'2026-10-23' -> 'jeudi 23/10/2026'."""
    try:
        d = datetime.strptime(iso, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return str(iso)
    texte = d.strftime('%d/%m/%Y')
    return f"{JOURS_FR[d.weekday()]} {texte}" if avec_jour else texte


def adresse_ip():
    """IP du visiteur (le site passe par Cloudflare puis Railway)."""
    return (request.headers.get('CF-Connecting-IP')
            or request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
            or request.remote_addr or 'inconnue')


_compteurs = defaultdict(deque)
_verrou_compteurs = threading.Lock()


def limite_atteinte(cle, maximum, fenetre_secondes, enregistrer=True):
    """Compteur en memoire : True si `cle` a deja ete vue `maximum` fois
    pendant la fenetre. Suffisant contre les robots du formulaire et les
    essais de mot de passe (remis a zero a chaque redemarrage)."""
    maintenant = time.time()
    with _verrou_compteurs:
        file = _compteurs[cle]
        while file and maintenant - file[0] > fenetre_secondes:
            file.popleft()
        if len(file) >= maximum:
            return True
        if enregistrer:
            file.append(maintenant)
        return False


def en_arriere_plan(fonction, *args):
    """Lance fonction(*args) dans un thread, avec le contexte de
    l'application (necessaire pour ecrire le journal des emails).
    Un service email lent ne bloque ainsi jamais la page du client."""
    app = current_app._get_current_object()

    def cible():
        with app.app_context():
            try:
                fonction(*args)
            except Exception:
                traceback.print_exc()

    if app.config.get('EMAILS_SYNCHRONES'):   # utilise par les tests
        cible()
        return
    threading.Thread(target=cible, daemon=True).start()


def donnees_reservation(r):
    """Copie simple d'une reservation (les objets SQLAlchemy ne doivent
    pas etre utilises dans un autre thread)."""
    return {
        'id': r.id,
        'nom': r.nom,
        'email': r.email or '',
        'telephone': r.telephone or '',
        'date': r.date,
        'heure': r.heure,
        'personnes': r.personnes,
        'reference': r.reference,
        'groupe_reference': r.groupe_reference,
        'message': r.message or '',
        'statut': r.statut,
    }


# ---------------------------------------------------------------------------
# Envoi des emails
# ---------------------------------------------------------------------------

def _envoyer_smtp(destinataire, sujet, html_content, texte, repondre_a):
    msg = MIMEMultipart('alternative')
    msg['From'] = SMTP_FROM or SMTP_USER
    msg['To'] = destinataire
    msg['Subject'] = sujet
    if repondre_a:
        msg['Reply-To'] = repondre_a
    msg.attach(MIMEText(texte, 'plain'))
    msg.attach(MIMEText(html_content, 'html'))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as serveur:
        serveur.starttls()
        serveur.login(SMTP_USER, SMTP_PASSWORD)
        serveur.send_message(msg)


def _envoyer_brevo(destinataire, sujet, html_content, texte, repondre_a):
    payload = {
        'sender': {'email': BREVO_FROM or EMAIL_FROM, 'name': BREVO_FROM_NAME},
        'to': [{'email': destinataire}],
        'subject': sujet,
        'htmlContent': html_content,
        'textContent': texte,
    }
    if repondre_a:
        payload['replyTo'] = {'email': repondre_a}
    requete = urllib.request.Request(
        'https://api.brevo.com/v3/smtp/email',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'api-key': BREVO_API_KEY,
            'Content-Type': 'application/json',
            'accept': 'application/json',
        },
        method='POST',
    )
    with urllib.request.urlopen(requete, timeout=15) as reponse:
        if reponse.status >= 300:
            raise RuntimeError(f'Brevo HTTP {reponse.status}')


def _envoyer_resend(destinataire, sujet, html_content, texte, repondre_a):
    resend.api_key = RESEND_API_KEY
    parametres = {
        "from": EMAIL_FROM,
        "to": [destinataire],
        "subject": sujet,
        "html": html_content,
        "text": texte,
    }
    if repondre_a:
        parametres["reply_to"] = repondre_a
    resend.Emails.send(parametres)


def envoyer_email(destinataire, sujet, html_content, texte='', repondre_a=None):
    """Envoie un email par le premier canal configure qui fonctionne
    (SMTP, puis Brevo, puis Resend). Retourne (ok, canal, erreur)."""
    erreurs = []
    canaux = []
    if SMTP_USER and SMTP_PASSWORD:
        canaux.append(('smtp', _envoyer_smtp))
    if BREVO_API_KEY:
        canaux.append(('brevo', _envoyer_brevo))
    if RESEND_API_KEY:
        canaux.append(('resend', _envoyer_resend))

    for nom_canal, fonction in canaux:
        try:
            fonction(destinataire, sujet, html_content, texte, repondre_a)
            print(f"✅ Email envoyé via {nom_canal} à {destinataire}")
            return True, nom_canal, None
        except Exception as erreur:
            print(f"⚠️  Échec de l'envoi via {nom_canal} ({erreur}) - tentative suivante")
            erreurs.append(f'{nom_canal} : {erreur}')

    if not canaux:
        erreurs.append('aucun service email configuré (SMTP_*, BREVO_API_KEY ou RESEND_API_KEY)')
    print(f"❌ Email non envoyé à {destinataire} : {' | '.join(erreurs)}")
    return False, None, ' | '.join(erreurs)


def _journaliser(type_mail, destinataire, reference, ok, canal, erreur):
    """Note l'envoi dans la table email_envois (visible dans l'admin)."""
    from models import db, EmailEnvoi
    try:
        db.session.add(EmailEnvoi(
            type_mail=type_mail,
            destinataire=(destinataire or '')[:120],
            reference=(reference or '')[:30],
            statut='envoye' if ok else 'echec',
            canal=canal,
            erreur=(erreur or None) and erreur[:2000],
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"⚠️  Impossible d'écrire le journal des emails : {e}")


def _gabarit(titre, couleur, intro_html, lignes, conclusion_html):
    """Mise en page commune des emails (styles en ligne pour les
    messageries)."""
    details = ''.join(
        f'<li style="margin: 8px 0;"><strong>{html.escape(libelle)} :</strong> {valeur}</li>'
        for libelle, valeur in lignes
    )
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #212529;">
        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 10px; border-left: 4px solid {couleur};">
            <h2 style="color: {couleur}; margin-top: 0;">{titre}</h2>
            {intro_html}
        </div>
        <div style="background-color: #ffffff; padding: 20px; border: 1px solid #dee2e6; border-radius: 10px; margin: 20px 0;">
            <ul style="list-style: none; padding: 0; margin: 0; font-size: 16px;">{details}</ul>
        </div>
        <div style="background-color: #e9ecef; padding: 15px; border-radius: 10px; text-align: center; color: #495057;">
            {conclusion_html}
            <p style="margin: 10px 0 0 0;"><strong>L'équipe du Restaurant Le Bouche à Oreilles</strong><br>
            Restaurant didactique de l'École Sainte-Bernadette<br>
            Square du Sacré-Cœur 2/A, 1160 Auderghem<br>
            Tél. {html.escape(RESTAURANT_TEL)}</p>
        </div>
    </body>
    </html>
    """


def _texte_dates(resas):
    return [date_fr(r['date']) for r in resas]


def mail_client(type_mail, resas):
    """Email au client pour une ou plusieurs reservations (meme client,
    memes infos, dates differentes) : un seul email qui liste les dates.
    type_mail : 'reception', 'confirmation' ou 'annulation'."""
    if not resas:
        return
    premiere = resas[0]
    destinataire = (premiere.get('email') or '').strip()
    reference = premiere['groupe_reference'] if len(resas) > 1 and premiere.get('groupe_reference') else premiere['reference']
    if not destinataire:
        # Reservation prise par telephone sans adresse email : rien a envoyer.
        return

    nom = html.escape(premiere['nom'])
    dates = _texte_dates(resas)
    plusieurs = len(dates) > 1
    lignes = [
        ('Date' + ('s' if plusieurs else ''), '<br>'.join(html.escape(d) for d in dates)),
        ('Heure', html.escape(premiere['heure'])),
        ('Nombre de personnes', str(premiere['personnes'])),
        ('Référence', html.escape(reference)),
    ]

    if type_mail == 'confirmation':
        sujet = EMAIL_SUBJECT
        titre, couleur = 'Votre réservation est confirmée', '#28a745'
        intro = (f"<p>Bonjour <strong>{nom}</strong>,</p>"
                 f"<p>Votre table est réservée. Nous vous attendons avec plaisir.</p>")
        conclusion = ("<p style=\"margin: 0;\">Un empêchement ? Merci de nous prévenir par téléphone "
                      "ou en répondant simplement à cet email.</p>")
        texte_intro = "Votre table est réservée. Nous vous attendons avec plaisir."
    elif type_mail == 'annulation':
        sujet = EMAIL_SUBJECT_ANNULATION
        titre, couleur = 'Votre réservation est annulée', '#dc3545'
        intro = (f"<p>Bonjour <strong>{nom}</strong>,</p>"
                 f"<p>Nous sommes au regret de vous informer que votre réservation a été annulée.</p>")
        conclusion = ("<p style=\"margin: 0;\">Pour toute question ou pour réserver une autre date, "
                      "appelez-nous ou répondez à cet email.</p>")
        texte_intro = "Nous sommes au regret de vous informer que votre réservation a été annulée."
    else:
        sujet = EMAIL_SUBJECT_RECEPTION
        titre, couleur = 'Nous avons bien reçu votre demande', '#17a2b8'
        intro = (f"<p>Bonjour <strong>{nom}</strong>,</p>"
                 f"<p>Votre demande est bien arrivée. <strong>Elle n'est pas encore confirmée</strong> : "
                 f"vous recevrez un second email dès que notre équipe l'aura validée.</p>")
        conclusion = ("<p style=\"margin: 0;\">Sans nouvelles de notre part 2 jours avant votre venue, "
                      f"appelez-nous au {html.escape(RESTAURANT_TEL)}.</p>")
        texte_intro = ("Votre demande est bien arrivée. Elle n'est pas encore confirmée : "
                       "vous recevrez un second email dès que notre équipe l'aura validée.")

    html_content = _gabarit(titre, couleur, intro, lignes, conclusion)
    texte = "\n".join([
        f"Bonjour {premiere['nom']},", "", texte_intro, "",
        ("Dates : " if plusieurs else "Date : ") + ", ".join(dates),
        f"Heure : {premiere['heure']}",
        f"Nombre de personnes : {premiere['personnes']}",
        f"Référence : {reference}", "",
        "L'équipe du Restaurant Le Bouche à Oreilles",
        f"Tél. {RESTAURANT_TEL}",
    ])

    envoi_reel = TEST_EMAIL_REDIRECT or destinataire
    ok, canal, erreur = envoyer_email(envoi_reel, sujet, html_content, texte,
                                      repondre_a=RESTAURANT_EMAIL or None)
    _journaliser(type_mail, envoi_reel, reference, ok, canal, erreur)


def mail_restaurant(resas, url_admin=''):
    """Previent le restaurant a chaque nouvelle demande (un email par
    demande, toutes dates comprises)."""
    if not resas or not RESTAURANT_EMAIL:
        return
    premiere = resas[0]
    reference = premiere['groupe_reference'] or premiere['reference']
    dates = _texte_dates(resas)
    confirmee = premiere['statut'] == 'confirmee'
    statut = 'CONFIRMÉE automatiquement' if confirmee else 'À VALIDER dans l\'admin'
    sujet = (f"Nouvelle réservation ({'confirmée' if confirmee else 'à valider'}) : {premiere['nom']}, "
             f"{premiere['personnes']} pers., " + (dates[0] if len(dates) == 1 else f"{len(dates)} dates"))

    lignes = [
        ('Statut', f'<strong>{statut}</strong>'),
        ('Nom', html.escape(premiere['nom'])),
        ('Téléphone', html.escape(premiere['telephone'] or '-')),
        ('Email', html.escape(premiere['email'] or '-')),
        ('Date' + ('s' if len(dates) > 1 else ''), '<br>'.join(html.escape(d) for d in dates)),
        ('Personnes', str(premiere['personnes'])),
        ('Message', html.escape(premiere['message'] or '-')),
    ]
    lien = (f'<p style="margin: 0;"><a href="{html.escape(url_admin)}">Ouvrir la liste des réservations</a></p>'
            if url_admin else '')
    html_content = _gabarit('Nouvelle réservation', '#cf7a3e',
                            '<p>Une nouvelle demande vient d\'arriver par le site.</p>', lignes, lien)
    texte = "\n".join([
        "Nouvelle réservation par le site", f"Statut : {statut}",
        f"Nom : {premiere['nom']}", f"Téléphone : {premiere['telephone'] or '-'}",
        f"Email : {premiere['email'] or '-'}", "Dates : " + ", ".join(dates),
        f"Personnes : {premiere['personnes']}", f"Message : {premiere['message'] or '-'}",
        url_admin,
    ])
    ok, canal, erreur = envoyer_email(RESTAURANT_EMAIL, sujet, html_content, texte,
                                      repondre_a=premiere['email'] or None)
    _journaliser('notification_resto', RESTAURANT_EMAIL, reference, ok, canal, erreur)


def emails_nouvelle_demande(resas, url_admin=''):
    """Apres une reservation en ligne : email au client (accuse de
    reception, ou confirmation directe) + copie au restaurant."""
    type_mail = 'confirmation' if all(r['statut'] == 'confirmee' for r in resas) else 'reception'
    mail_client(type_mail, resas)
    mail_restaurant(resas, url_admin)


# Anciennes fonctions gardees pour compatibilite (une seule date).
def envoyer_confirmation_email(nom, email, date, heure, personnes, reference):
    mail_client('confirmation', [{'nom': nom, 'email': email, 'date': date, 'heure': heure,
                                  'personnes': personnes, 'reference': reference,
                                  'groupe_reference': None}])


def envoyer_annulation_email(nom, email, date, heure, personnes, reference):
    mail_client('annulation', [{'nom': nom, 'email': email, 'date': date, 'heure': heure,
                                'personnes': personnes, 'reference': reference,
                                'groupe_reference': None}])


# ---------------------------------------------------------------------------
# Capacite, jours fermes, references
# ---------------------------------------------------------------------------

# Nombre maximum de personnes par date. Au-dela, la date
# est consideree comme complete et n'est plus reservable.
MAX_PERSONNES_PAR_DATE = 26
# Exception : le mardi, le maximum est de 30 personnes.
MAX_PERSONNES_MARDI = 30

# A partir du 1er novembre 2026 : 30 personnes du lundi au jeudi,
# 32 le vendredi. (Le weekend n'est pas reservable dans le calendrier.)
NOV_DEBUT = date(2026, 11, 1)
MAX_PERSONNES_SEMAINE_NOV = 30
MAX_PERSONNES_VENDREDI_NOV = 32

def max_personnes_pour_date(date_str):
    """Retourne le maximum de personnes autorise pour une date.

    Avant le 1er novembre 2026 : 26 personnes, 30 le mardi.
    A partir du 1er novembre 2026 : 30 du lundi au jeudi, 32 le vendredi.
    """
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return MAX_PERSONNES_PAR_DATE
    jour_semaine = date_obj.weekday()  # lundi=0 ... vendredi=4 ... dimanche=6
    if date_obj >= NOV_DEBUT:
        return MAX_PERSONNES_VENDREDI_NOV if jour_semaine == 4 else MAX_PERSONNES_SEMAINE_NOV
    return MAX_PERSONNES_MARDI if jour_semaine == 1 else MAX_PERSONNES_PAR_DATE


def places_occupees(date_iso):
    """Personnes deja inscrites (en attente + confirmees) pour une date."""
    from models import db, Reservation
    return db.session.query(func.sum(Reservation.personnes)).filter(
        Reservation.date == date_iso,
        Reservation.statut.in_(['en_attente', 'confirmee'])
    ).scalar() or 0


def jours_fermes():
    """{ 'AAAA-MM-JJ': motif } pour les jours sans service."""
    from models import JourFerme
    try:
        return {j.date: (j.motif or 'Fermé') for j in JourFerme.query.all()}
    except Exception:
        return {}


def prochaine_reference(date_iso):
    """Reference sequentielle par date : Table1-2026-08-28, Table2-..."""
    from models import Reservation
    numeros = []
    for r in Reservation.query.filter_by(date=date_iso).all():
        match = re.match(r'Table(\d+)-', r.reference or '')
        if match:
            numeros.append(int(match.group(1)))
    prochain_num = (max(numeros) + 1) if numeros else 1
    # Si la reference existe deja (cas rare de concurrence), on incremente.
    while Reservation.query.filter_by(reference=f'Table{prochain_num}-{date_iso}').first():
        prochain_num += 1
    return f'Table{prochain_num}-{date_iso}'


def nouvelle_reference_groupe():
    """Reference de groupe unique et non devinable."""
    from models import Reservation
    while True:
        groupe_reference = f'Groupe-{secrets.token_hex(4)}'
        if not Reservation.query.filter_by(groupe_reference=groupe_reference).first():
            return groupe_reference


def verifier_dates(dates, fermes, aujourd_hui=None):
    """Controle serveur des dates choisies (le calendrier fait deja ce
    tri, mais un robot peut envoyer n'importe quoi). Retourne une liste
    de messages d'erreur (vide si tout va bien)."""
    aujourd_hui = aujourd_hui or date.today()
    mois = aujourd_hui.month - 1 + MOIS_MAX_AVANCE + 1
    limite = date(aujourd_hui.year + mois // 12, mois % 12 + 1, 1)  # 1er jour apres le dernier mois affiche
    erreurs = []
    for d in dates:
        try:
            jour = datetime.strptime(d, '%Y-%m-%d').date()
        except ValueError:
            erreurs.append("Une des dates envoyées n'est pas valide.")
            continue
        if jour < aujourd_hui:
            erreurs.append(f"Le {date_fr(d)} est déjà passé.")
        elif jour.weekday() >= 5:
            erreurs.append(f"Le restaurant est fermé le week-end ({date_fr(d)}).")
        elif jour >= limite:
            erreurs.append(f"Le {date_fr(d)} est trop loin : on ne prend les réservations que {MOIS_MAX_AVANCE} mois à l'avance.")
        elif d in fermes:
            erreurs.append(f"Le restaurant est fermé le {date_fr(d)} ({fermes[d]}).")
    return erreurs


# ---------------------------------------------------------------------------
# Routes publiques
# ---------------------------------------------------------------------------

@reservation_bp.route('/reserver')
def reserver():
    return render_template('reservation_form.html',
                           confirmation_automatique=CONFIRMATION_AUTOMATIQUE,
                           telephone_resto=RESTAURANT_TEL,
                           max_dates=MAX_DATES_PAR_DEMANDE)


@reservation_bp.route('/api/occupation-dates')
def api_occupation_dates():
    """Retourne le nombre de personnes par date (reservations non annulees)
    et les jours fermes."""
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
        for jour, total in resultats:
            occupation[jour] = int(total or 0)

        return jsonify({
            'occupation': occupation,
            'fermes': jours_fermes(),
            'max_personnes': MAX_PERSONNES_PAR_DATE,
            'max_personnes_mardi': MAX_PERSONNES_MARDI,
            'nov_debut': NOV_DEBUT.isoformat(),
            'nov_semaine': MAX_PERSONNES_SEMAINE_NOV,
            'nov_vendredi': MAX_PERSONNES_VENDREDI_NOV
        })
    except Exception as e:
        return jsonify({'erreur': str(e)}), 500


@reservation_bp.route('/creer_reservation', methods=['POST'])
def creer_reservation():
    from models import db, Reservation

    # Piege a robots : ce champ est invisible pour les humains.
    if request.form.get('site_web', '').strip():
        print(f"🤖 Demande ignorée (champ piège rempli) depuis {adresse_ip()}")
        return redirect(url_for('accueil'))

    nom = request.form.get('nom', '').strip()
    email = request.form.get('email', '').strip()
    telephone = request.form.get('telephone', '').strip()
    heure = request.form.get('heure', '').strip()
    message = request.form.get('message', '').strip()

    erreurs = []
    if not 2 <= len(nom) <= 100:
        erreurs.append("Merci d'indiquer votre nom.")
    if len(email) > 120 or not EMAIL_RE.match(email):
        erreurs.append("L'adresse email ne semble pas correcte.")
    if not 6 <= len(re.sub(r'\D', '', telephone)) <= 15 or len(telephone) > 20:
        erreurs.append("Le numéro de téléphone ne semble pas correct.")
    if heure not in HEURES_SERVICE:
        erreurs.append("L'heure choisie n'est pas disponible.")
    if len(message) > 1000:
        erreurs.append("Le message est trop long (1000 caractères maximum).")

    # Nombre de personnes : 1 a 10 en ligne ; « Plus de 10 » (valeur 0)
    # demande le nombre exact et la reservation reste a valider.
    try:
        personnes = int(request.form.get('personnes', ''))
    except ValueError:
        personnes = -1
    groupe = personnes == 0
    if groupe:
        try:
            personnes = int(request.form.get('personnes_groupe', ''))
        except ValueError:
            personnes = -1
        if not MAX_PERSONNES_EN_LIGNE < personnes <= GROUPE_MAX:
            erreurs.append(f"Pour un groupe, indiquez le nombre exact de personnes (de 11 à {GROUPE_MAX}). "
                           f"Au-delà, appelez-nous au {RESTAURANT_TEL}.")
    elif not 1 <= personnes <= MAX_PERSONNES_EN_LIGNE:
        erreurs.append("Le nombre de personnes n'est pas valide.")

    # Plusieurs dates peuvent être choisies en une seule réservation
    dates_brutes = request.form.get('dates', '')
    dates = sorted(set(d.strip() for d in dates_brutes.split(',') if d.strip()))
    if not dates:
        erreurs.append('Veuillez sélectionner au moins une date.')
    elif len(dates) > MAX_DATES_PAR_DEMANDE:
        erreurs.append(f"Vous pouvez choisir au maximum {MAX_DATES_PAR_DEMANDE} dates par demande.")
    else:
        erreurs.extend(verifier_dates(dates, jours_fermes()))

    if erreurs:
        for e in erreurs:
            flash(e, 'error')
        return redirect(url_for('reservation.reserver'))

    # Limite par adresse IP (robots, doubles clics repetes...)
    if limite_atteinte(f'resa:{adresse_ip()}', MAX_DEMANDES_PAR_HEURE_ET_IP, 3600):
        flash(f"Trop de demandes envoyées depuis votre connexion. Réessayez plus tard ou appelez-nous au {RESTAURANT_TEL}.", 'error')
        return redirect(url_for('reservation.reserver'))

    try:
        # Verifier qu'aucune date selectionnee n'est deja complete.
        # On compte les personnes des reservations non annulees.
        dates_completes = [d for d in dates
                           if places_occupees(d) + personnes > max_personnes_pour_date(d)]
        if dates_completes:
            liste = ', '.join(date_fr(d) for d in dates_completes)
            if len(dates_completes) == 1:
                flash(f"Désolé, il ne reste plus assez de place le {liste}. Choisissez une autre date ou appelez-nous au {RESTAURANT_TEL}.", 'error')
            else:
                flash(f"Désolé, il ne reste plus assez de place à ces dates : {liste}. Choisissez d'autres dates ou appelez-nous au {RESTAURANT_TEL}.", 'error')
            return redirect(url_for('reservation.reserver'))

        # Reference de groupe unique et non devinable (voir d783664).
        groupe_reference = nouvelle_reference_groupe()
        statut = 'confirmee' if (CONFIRMATION_AUTOMATIQUE and not groupe) else 'en_attente'

        reservations_creees = []
        for jour in dates:
            nouvelle_reservation = Reservation(
                reference=prochaine_reference(jour),
                groupe_reference=groupe_reference,
                nom=nom,
                email=email,
                telephone=telephone,
                date=jour,
                heure=heure,
                personnes=personnes,
                message=message,
                statut=statut,
                source='web',
            )
            db.session.add(nouvelle_reservation)
            db.session.flush()   # reference visible pour la date suivante
            reservations_creees.append(nouvelle_reservation)

        db.session.commit()

        # Emails dans un thread : un service email lent ou injoignable ne
        # doit jamais bloquer la reponse. Chaque envoi est note dans le
        # journal des emails, visible dans l'admin.
        donnees = [donnees_reservation(r) for r in reservations_creees]
        url_admin = url_for('afficher_toutes_reservations', _external=True)
        en_arriere_plan(emails_nouvelle_demande, donnees, url_admin)

        session['derniere_reservation'] = groupe_reference
        return redirect(url_for('confirmation_groupe', groupe_reference=groupe_reference))

    except Exception:
        db.session.rollback()
        traceback.print_exc()
        flash(f"Une erreur est survenue, votre demande n'a pas été enregistrée. Réessayez ou appelez-nous au {RESTAURANT_TEL}.", 'error')
        return redirect(url_for('reservation.reserver'))


@reservation_bp.route('/confirmation')
def confirmation():
    reference = session.get('derniere_reservation')
    if not reference:
        return redirect(url_for('reservation.reserver'))
    return redirect(url_for('confirmation_groupe', groupe_reference=reference))
