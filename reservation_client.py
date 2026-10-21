from flask import Blueprint, render_template, request, flash, redirect, url_for, session, jsonify, current_app
from itsdangerous import URLSafeSerializer, BadSignature
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
# Numero cliquable sur telephone (tel:+32...)
_chiffres_resto = re.sub(r'\D', '', RESTAURANT_TEL)
RESTAURANT_TEL_LIEN = '+32' + _chiffres_resto[1:] if _chiffres_resto.startswith('0') else '+' + _chiffres_resto
# Adresse publique du site, pour les liens envoyes par email.
SITE_URL = os.environ.get('SITE_URL', 'https://www.leboucheaoreilles.be').rstrip('/')

# Confirmation automatique : s'il reste de la place, la réservation est
# confirmée tout de suite (le client reçoit directement sa confirmation).
# Les groupes de plus de 10 personnes restent toujours à valider à la main.
# Mettre CONFIRMATION_AUTOMATIQUE=1 dans Railway pour l'activer.
CONFIRMATION_AUTOMATIQUE = os.environ.get('CONFIRMATION_AUTOMATIQUE', '0') == '1'

# Garde-fous du formulaire public
# Les habitues reservent parfois 15 ou 20 fois par mois : 40 dates d'un coup (environ 2 mois de service)
MAX_DATES_PAR_DEMANDE = int(os.environ.get('MAX_DATES_PAR_DEMANDE', '40'))
MAX_PERSONNES_EN_LIGNE = 10       # au-dela : demande de groupe, validee a la main
GROUPE_MAX = 60
HEURES_SERVICE = ('11:55',)
MOIS_MAX_AVANCE = 6               # meme valeur que dans le calendrier du formulaire
MAX_DEMANDES_PAR_HEURE_ET_IP = 5

EMAIL_SUBJECT = 'Confirmation de votre réservation - Restaurant Le Bouche à Oreilles'
EMAIL_SUBJECT_ANNULATION = 'Annulation de votre réservation - Restaurant Le Bouche à Oreilles'
EMAIL_SUBJECT_RECEPTION = 'Réception de votre demande de réservation - Restaurant Le Bouche à Oreilles'

TYPES_MAIL_CLIENT = ('reception', 'confirmation', 'annulation', 'modification', 'lien_modification')

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
        'lien_modif': lien_modification(r.groupe_reference),
    }


def jeton_modification(groupe_reference):
    """Jeton signe (impossible a deviner ou a fabriquer) qui donne acces
    a la page « Modifier ma reservation » d'un groupe de reservations."""
    return URLSafeSerializer(current_app.secret_key, salt='modifier-reservation').dumps(groupe_reference)


def lien_modification(groupe_reference):
    """Lien complet envoye au client dans ses emails."""
    if not groupe_reference:
        return ''
    return f"{SITE_URL}/reservation/modifier/{jeton_modification(groupe_reference)}"


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


def _gabarit(titre, couleur, intro_html, lignes, conclusion_html, bouton=None):
    """Mise en page commune des emails : grands caracteres (une bonne partie
    de nos clients sont ages), styles en ligne pour les messageries."""
    details = ''.join(
        f'<li style="margin: 10px 0;"><strong>{html.escape(libelle)} :</strong> {valeur}</li>'
        for libelle, valeur in lignes
    )
    bloc_bouton = ''
    if bouton:
        url, libelle_bouton = html.escape(bouton[0]), html.escape(bouton[1])
        bloc_bouton = f"""
        <div style="text-align: center; margin: 24px 0;">
            <a href="{url}" style="background-color: #cf7a3e; color: #ffffff; text-decoration: none; font-size: 20px; font-weight: bold; padding: 16px 28px; border-radius: 8px; display: inline-block;">{libelle_bouton}</a>
            <p style="font-size: 14px; color: #6c757d; margin: 12px 0 0 0;">Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur :<br>{url}</p>
        </div>"""
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; font-size: 18px; line-height: 1.5; max-width: 600px; margin: 0 auto; padding: 20px; color: #212529;">
        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 10px; border-left: 6px solid {couleur};">
            <h2 style="color: {couleur}; margin-top: 0; font-size: 26px;">{titre}</h2>
            {intro_html}
        </div>
        <div style="background-color: #ffffff; padding: 20px; border: 1px solid #dee2e6; border-radius: 10px; margin: 20px 0;">
            <ul style="list-style: none; padding: 0; margin: 0; font-size: 19px;">{details}</ul>
        </div>
        {bloc_bouton}
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


def _en_texte(valeur):
    """Valeur HTML d'une ligne -> texte simple (version texte des emails)."""
    return html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', ', ', valeur)))


def _texte_dates(resas):
    return [date_fr(r['date']) for r in resas]


def mail_client(type_mail, resas):
    """Email au client pour une ou plusieurs reservations du meme groupe :
    un seul email qui liste les dates. type_mail : reception, confirmation,
    annulation, modification ou lien_modification."""
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
    lien = premiere.get('lien_modif') or ''
    tel = html.escape(RESTAURANT_TEL)

    if type_mail in ('modification', 'lien_modification'):
        lignes = []
        for r in resas:
            etat = {'annulee': ' (annulée)', 'en_attente': ' (en attente de confirmation)'}.get(r['statut'], '')
            lignes.append((date_fr(r['date']), f"{r['personnes']} personne{'s' if r['personnes'] > 1 else ''}{etat}"))
        lignes.append(('Heure', html.escape(premiere['heure'])))
    else:
        lignes = [
            ('Date' + ('s' if plusieurs else ''), '<br>'.join(html.escape(d) for d in dates)),
            ('Heure', html.escape(premiere['heure'])),
            ('Nombre de personnes', str(premiere['personnes'])),
            ('Référence', html.escape(reference)),
        ]

    if type_mail == 'confirmation':
        sujet = EMAIL_SUBJECT
        titre, couleur = 'Votre réservation est confirmée', '#28a745'
        texte_intro = "Votre table est réservée. Nous vous attendons avec plaisir."
        conclusion = ("<p style=\"margin: 0;\">Un changement ou un empêchement ? Utilisez le bouton ci-dessus "
                      f"ou appelez-nous au {tel}.</p>")
    elif type_mail == 'annulation':
        sujet = EMAIL_SUBJECT_ANNULATION
        titre, couleur = 'Votre réservation est annulée', '#dc3545'
        texte_intro = "Nous sommes au regret de vous informer que votre réservation a été annulée."
        conclusion = ("<p style=\"margin: 0;\">Pour toute question ou pour réserver une autre date, "
                      "appelez-nous ou répondez à cet email.</p>")
    elif type_mail == 'modification':
        sujet = 'Modification de votre réservation - Restaurant Le Bouche à Oreilles'
        titre, couleur = 'Votre réservation est modifiée', '#cf7a3e'
        texte_intro = "Votre changement est bien enregistré. Voici votre réservation à jour."
        conclusion = f"<p style=\"margin: 0;\">Un autre changement ? Utilisez le bouton ci-dessus ou appelez-nous au {tel}.</p>"
    elif type_mail == 'lien_modification':
        sujet = 'Votre réservation - Restaurant Le Bouche à Oreilles'
        titre, couleur = 'Vous avez déjà une réservation', '#cf7a3e'
        texte_intro = ("Vous avez déjà une réservation chez nous. Pour changer le nombre de personnes "
                       "ou annuler, cliquez sur le bouton « Modifier ou annuler ma réservation ».")
        conclusion = f"<p style=\"margin: 0;\">Vous pouvez aussi nous appeler au {tel}.</p>"
    else:
        sujet = EMAIL_SUBJECT_RECEPTION
        titre, couleur = 'Nous avons bien reçu votre demande', '#17a2b8'
        texte_intro = ("Votre demande est bien arrivée. Elle n'est pas encore confirmée : "
                       "vous recevrez un second email dès que notre équipe l'aura validée.")
        conclusion = ("<p style=\"margin: 0;\">Sans nouvelles de notre part 2 jours avant votre venue, "
                      f"appelez-nous au {tel}.</p>")
    texte_intro_html = html.escape(texte_intro).replace("Elle n&#x27;est pas encore confirmée", "<strong>Elle n'est pas encore confirmée</strong>")
    intro = f"<p>Bonjour <strong>{nom}</strong>,</p><p>{texte_intro_html}</p>"

    bouton = (lien, 'Modifier ou annuler ma réservation') if lien and type_mail != 'annulation' else None
    html_content = _gabarit(titre, couleur, intro, lignes, conclusion, bouton)
    texte = "\n".join(
        [f"Bonjour {premiere['nom']},", "", texte_intro, ""]
        + [f"{libelle} : {_en_texte(valeur)}" for libelle, valeur in lignes]
        + ([f"", f"Modifier ou annuler ma réservation : {lien}"] if bouton else [])
        + ["", "L'équipe du Restaurant Le Bouche à Oreilles", f"Tél. {RESTAURANT_TEL}"]
    )

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

def _formulaire(valeurs=None, messages=(), code=200):
    """Affiche le formulaire. Apres une erreur, ce que le client a tape
    reste affiche : il corrige au lieu de tout recommencer."""
    for m in messages:
        flash(m, 'error')
    return render_template('reservation_form.html',
                           confirmation_automatique=CONFIRMATION_AUTOMATIQUE,
                           telephone_resto=RESTAURANT_TEL,
                           max_dates=MAX_DATES_PAR_DEMANDE,
                           valeurs=valeurs or {}), code


@reservation_bp.route('/reserver')
def reserver():
    return _formulaire()


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
        return _formulaire(request.form, erreurs, 400)

    # Limite par adresse IP (robots, doubles clics repetes...)
    if limite_atteinte(f'resa:{adresse_ip()}', MAX_DEMANDES_PAR_HEURE_ET_IP, 3600):
        return _formulaire(request.form, [f"Trop de demandes envoyées depuis votre connexion. Réessayez plus tard ou appelez-nous au {RESTAURANT_TEL}."], 429)

    # Deja une reservation ce jour-la (meme email ou meme telephone) ? On ne
    # cree pas de doublon (ex. une table de 8 qui repasse pour 10) : on
    # renvoie au client, a l'adresse deja connue, le lien pour la modifier.
    doublons = reservations_existantes(email, telephone, dates)
    if doublons:
        deja = doublons[0]
        groupe = (Reservation.query.filter_by(groupe_reference=deja.groupe_reference)
                  .order_by(Reservation.date).all() if deja.groupe_reference else [deja])
        if deja.email:
            en_arriere_plan(mail_client, 'lien_modification',
                            [donnees_reservation(r) for r in groupe if r.statut != 'annulee'])
            flash(f"Vous avez déjà une réservation le {date_fr(deja.date)}. Pour changer le nombre de personnes, "
                  "utilisez le bouton « Modifier ou annuler ma réservation » de votre email : nous venons de "
                  f"vous le renvoyer. Vous pouvez aussi nous appeler au {RESTAURANT_TEL}.", 'error')
        else:
            flash(f"Vous avez déjà une réservation le {date_fr(deja.date)}. Pour la modifier, appelez-nous au {RESTAURANT_TEL}.", 'error')
        return _formulaire(request.form, code=409)

    try:
        # Verifier qu'aucune date selectionnee n'est deja complete.
        # On compte les personnes des reservations non annulees.
        dates_completes = [d for d in dates
                           if places_occupees(d) + personnes > max_personnes_pour_date(d)]
        if dates_completes:
            liste = ', '.join(date_fr(d) for d in dates_completes)
            if len(dates_completes) == 1:
                message = f"Désolé, il ne reste plus assez de place le {liste}. Choisissez une autre date ou appelez-nous au {RESTAURANT_TEL}."
            else:
                message = f"Désolé, il ne reste plus assez de place à ces dates : {liste}. Choisissez d'autres dates ou appelez-nous au {RESTAURANT_TEL}."
            return _formulaire(request.form, [message], 409)

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
        url_admin = SITE_URL + url_for('afficher_toutes_reservations')
        en_arriere_plan(emails_nouvelle_demande, donnees, url_admin)

        session['derniere_reservation'] = groupe_reference
        return redirect(url_for('confirmation_groupe', groupe_reference=groupe_reference))

    except Exception:
        db.session.rollback()
        traceback.print_exc()
        return _formulaire(request.form, [f"Une erreur est survenue, votre demande n'a pas été enregistrée. Réessayez ou appelez-nous au {RESTAURANT_TEL}."], 500)


@reservation_bp.route('/confirmation')
def confirmation():
    reference = session.get('derniere_reservation')
    if not reference:
        return redirect(url_for('reservation.reserver'))
    return redirect(url_for('confirmation_groupe', groupe_reference=reference))


# ---------------------------------------------------------------------------
# Le client modifie ou annule lui-meme (lien personnel recu par email)
# ---------------------------------------------------------------------------

def _chiffres_tel(telephone):
    """9 derniers chiffres : 0470 12 34 56 et +32 470 12 34 56 se valent."""
    return re.sub(r'\D', '', telephone or '')[-9:]


def reservations_existantes(email, telephone, dates):
    """Reservations actives aux memes dates, avec le meme email ou le
    meme telephone."""
    from models import Reservation
    tel = _chiffres_tel(telephone)
    candidates = Reservation.query.filter(Reservation.date.in_(dates),
                                          Reservation.statut.in_(['en_attente', 'confirmee'])).all()
    return [r for r in candidates
            if (email and (r.email or '').strip().lower() == email.strip().lower())
            or (len(tel) >= 8 and _chiffres_tel(r.telephone) == tel)]


def mail_restaurant_modification(avant, apres):
    """Previent le restaurant quand un client modifie ou annule en ligne."""
    if not apres or not RESTAURANT_EMAIL:
        return
    anciens = {r['id']: r for r in avant}
    lignes = []
    for r in apres:
        a = anciens.get(r['id'])
        if not a:
            continue
        if r['statut'] == 'annulee' and a['statut'] != 'annulee':
            lignes.append((date_fr(r['date']), '<strong>annulée par le client</strong>'))
        elif r['personnes'] != a['personnes']:
            suite = ' (plus de 10 : à valider)' if r['statut'] == 'en_attente' and a['statut'] == 'confirmee' else ''
            lignes.append((date_fr(r['date']), f"de {a['personnes']} à {r['personnes']} personnes{suite}"))
    if not lignes:
        return
    premiere = apres[0]
    lignes += [('Nom', html.escape(premiere['nom'])),
               ('Téléphone', html.escape(premiere['telephone'] or '-')),
               ('Email', html.escape(premiere['email'] or '-'))]
    reference = premiere['groupe_reference'] or premiere['reference']
    lien = f'<p style="margin: 0;"><a href="{html.escape(SITE_URL)}/admin/reservations">Ouvrir la liste des réservations</a></p>'
    html_content = _gabarit('Réservation modifiée', '#cf7a3e',
                            '<p>Un client vient de modifier sa réservation sur le site.</p>', lignes, lien)
    texte = "\n".join(["Réservation modifiée par le client"] + [f"{l} : {_en_texte(v)}" for l, v in lignes])
    ok, canal, erreur = envoyer_email(RESTAURANT_EMAIL, f"Réservation modifiée par le client : {premiere['nom']}",
                                      html_content, texte, repondre_a=premiere['email'] or None)
    _journaliser('notification_resto', RESTAURANT_EMAIL, reference, ok, canal, erreur)


def emails_modification(avant, apres):
    mail_client('modification', apres)
    mail_restaurant_modification(avant, apres)


def _modifiable(r, aujourd_hui):
    """Modifiable en ligne jusqu'a la veille ; le jour meme, on telephone."""
    return r.statut != 'annulee' and r.date > aujourd_hui


@reservation_bp.route('/modifier/<jeton>', methods=['GET', 'POST'])
def modifier(jeton):
    from models import db, Reservation
    try:
        groupe_reference = URLSafeSerializer(current_app.secret_key, salt='modifier-reservation').loads(jeton)
    except BadSignature:
        groupe_reference = None
    resas = (Reservation.query.filter_by(groupe_reference=groupe_reference).order_by(Reservation.date).all()
             if groupe_reference else [])
    if not resas:
        return render_template('modifier_reservation_client.html', introuvable=True,
                               telephone_resto=RESTAURANT_TEL), 404
    aujourd_hui = date.today().isoformat()

    if request.method == 'POST':
        if limite_atteinte(f'modif:{adresse_ip()}', 20, 3600):
            flash(f"Trop de tentatives. Réessayez plus tard ou appelez-nous au {RESTAURANT_TEL}.", 'error')
            return redirect(url_for('reservation.modifier', jeton=jeton))
        avant = [donnees_reservation(r) for r in resas]
        erreurs, changements = [], 0
        tout_annuler = request.form.get('annuler_tout') == '1'
        for r in resas:
            if not _modifiable(r, aujourd_hui):
                continue
            if tout_annuler or request.form.get(f'annuler_{r.id}') == '1':
                r.statut = 'annulee'
                changements += 1
                continue
            try:
                nouveau = int(request.form.get(f'personnes_{r.id}', r.personnes))
            except ValueError:
                erreurs.append(f"{date_fr(r.date)} : le nombre de personnes n'est pas valide.")
                continue
            if nouveau == r.personnes:
                continue
            if not 1 <= nouveau <= GROUPE_MAX:
                erreurs.append(f"{date_fr(r.date)} : de 1 à {GROUPE_MAX} personnes. Au-delà, appelez-nous au {RESTAURANT_TEL}.")
                continue
            if nouveau > r.personnes:
                libres = max_personnes_pour_date(r.date) - places_occupees(r.date) + r.personnes
                if nouveau > libres:
                    erreurs.append(f"{date_fr(r.date)} : il ne reste pas assez de place (au maximum {max(libres, r.personnes)} "
                                   f"personnes pour votre table). Appelez-nous au {RESTAURANT_TEL}, on verra ce qui est possible.")
                    continue
            if nouveau > MAX_PERSONNES_EN_LIGNE >= r.personnes:
                r.statut = 'en_attente'   # devient un groupe : notre equipe valide
            r.personnes = nouveau
            changements += 1

        if erreurs:
            db.session.rollback()
            for e in erreurs:
                flash(e, 'error')
            return redirect(url_for('reservation.modifier', jeton=jeton))
        if not changements:
            flash("Aucun changement à enregistrer.", 'info')
            return redirect(url_for('reservation.modifier', jeton=jeton))
        db.session.commit()
        en_arriere_plan(emails_modification, avant, [donnees_reservation(r) for r in resas])
        flash("C'est enregistré. Vous allez recevoir un email avec votre réservation à jour.", 'success')
        return redirect(url_for('reservation.modifier', jeton=jeton))

    modifiables = [r for r in resas if _modifiable(r, aujourd_hui)]
    return render_template('modifier_reservation_client.html', introuvable=False, resas=resas,
                           aujourd_hui=aujourd_hui, telephone_resto=RESTAURANT_TEL,
                           nb_modifiables=len(modifiables),
                           personnes_defaut=modifiables[0].personnes if modifiables else 2,
                           max_en_ligne=MAX_PERSONNES_EN_LIGNE, groupe_max=GROUPE_MAX)
