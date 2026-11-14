"""Tests des correctifs : réservations, emails, sécurité de l'admin."""
from datetime import date, timedelta

import pytest


import reservation_client as rc
from models import db, Reservation, EmailEnvoi, JourFerme
from conftest import formulaire, jours_ouvrables, prochain_samedi, MOT_DE_PASSE_TEST


def reservations(app):
    with app.app_context():
        return Reservation.query.order_by(Reservation.date).all()


def journal(app):
    with app.app_context():
        return EmailEnvoi.query.order_by(EmailEnvoi.id).all()


# --- Réservation en ligne ----------------------------------------------------

def test_reservation_simple_previent_le_resto_et_le_client(app, client, mails):
    r = client.post('/reservation/creer_reservation', data=formulaire())
    assert r.status_code == 302 and '/confirmation-groupe/' in r.headers['Location']
    resas = reservations(app)
    assert len(resas) == 1 and resas[0].statut == 'en_attente' and resas[0].source == 'web'
    # 1 accusé de réception au client + 1 copie au restaurant
    assert len(mails.pour('jeanne@example.org')) == 1
    assert 'pas encore confirmée' in mails.pour('jeanne@example.org')[0]['html']
    assert len(mails.pour('resto@example.org')) == 1
    assert mails.pour('resto@example.org')[0]['repondre_a'] == 'jeanne@example.org'
    types = sorted((j.type_mail, j.statut) for j in journal(app))
    assert types == [('notification_resto', 'envoye'), ('reception', 'envoye')]


def test_plusieurs_dates_un_seul_email(app, client, mails):
    dates = jours_ouvrables(3)
    client.post('/reservation/creer_reservation', data=formulaire(dates=','.join(dates)))
    assert len(reservations(app)) == 3
    assert len(mails.pour('jeanne@example.org')) == 1      # avant : un email par date
    assert len(mails.pour('resto@example.org')) == 1


def test_confirmation_automatique(app, client, mails, monkeypatch):
    monkeypatch.setattr(rc, 'CONFIRMATION_AUTOMATIQUE', True)
    r = client.post('/reservation/creer_reservation', data=formulaire())
    assert reservations(app)[0].statut == 'confirmee'
    assert 'Votre réservation est confirmée' in mails.pour('jeanne@example.org')[0]['html']
    page = client.get(r.headers['Location'])
    assert 'Votre table est réservée' in page.get_data(as_text=True)


def test_groupe_de_plus_de_10_reste_a_valider_avec_le_vrai_nombre(app, client, mails, monkeypatch):
    monkeypatch.setattr(rc, 'CONFIRMATION_AUTOMATIQUE', True)
    client.post('/reservation/creer_reservation', data=formulaire(personnes='0', personnes_groupe='14'))
    resa = reservations(app)[0]
    assert resa.personnes == 14 and resa.statut == 'en_attente'


def test_groupe_sans_nombre_exact_refuse(app, client, mails):
    client.post('/reservation/creer_reservation', data=formulaire(personnes='0'))
    assert reservations(app) == []


def test_capacite_respectee(app, client, mails):
    jour = jours_ouvrables(1)[0]
    maximum = rc.max_personnes_pour_date(jour)
    with app.app_context():
        db.session.add(Reservation(reference=f'Table1-{jour}', nom='X', email='x@example.org', date=jour,
                                   heure='11:55', personnes=maximum - 1, statut='confirmee'))
        db.session.commit()
    client.post('/reservation/creer_reservation', data=formulaire(dates=jour, personnes='2'))
    assert len(reservations(app)) == 1   # refusée : plus assez de place


def test_dates_invalides_refusees(app, client, mails):
    hier = (date.today() - timedelta(days=1)).isoformat()
    for dates in (hier, prochain_samedi(), 'n-importe-quoi', ','.join(jours_ouvrables(rc.MAX_DATES_PAR_DEMANDE + 1)),
                  (date.today() + timedelta(days=400)).isoformat()):
        client.post('/reservation/creer_reservation', data=formulaire(dates=dates))
    assert reservations(app) == []
    assert mails.envoyes == []


def test_jour_ferme_refuse_et_signale_au_calendrier(app, client, admin, mails):
    jour = jours_ouvrables(1, depart=7)[0]
    admin.post('/admin/fermetures', data={'debut': jour, 'motif': 'Stages'})
    api = client.get('/reservation/api/occupation-dates').get_json()
    assert api['fermes'] == {jour: 'Stages'}
    client.post('/reservation/creer_reservation', data=formulaire(dates=jour))
    assert reservations(app) == []


def test_piege_a_robots(app, client, mails):
    client.post('/reservation/creer_reservation', data=formulaire(site_web='http://spam.example'))
    assert reservations(app) == [] and mails.envoyes == []


def test_limite_par_adresse_ip(app, client, mails):
    for i in range(7):
        client.post('/reservation/creer_reservation',
                    data=formulaire(dates=jours_ouvrables(7)[i], email=f'c{i}@example.org'))
    assert len(reservations(app)) == rc.MAX_DEMANDES_PAR_HEURE_ET_IP


def test_contenu_du_client_echappe_dans_les_emails(app, client, mails):
    client.post('/reservation/creer_reservation',
                data=formulaire(nom='<a href="http://spam.example">Gagnez</a>'))
    html = mails.pour('jeanne@example.org')[0]['html']
    assert '<a href="http://spam.example">' not in html and '&lt;a href=' in html


def test_page_de_confirmation_reservee_a_son_auteur(app, client, mails):
    r = client.post('/reservation/creer_reservation', data=formulaire())
    lien = r.headers['Location']
    assert client.get(lien).status_code == 200
    autre_visiteur = app.test_client()
    assert autre_visiteur.get(lien).status_code == 302


# --- Emails : échecs visibles -------------------------------------------------

def test_echec_email_visible_dans_l_admin_et_renvoi(app, client, admin, mails):
    mails.echouer = True
    client.post('/reservation/creer_reservation', data=formulaire())
    assert [j.statut for j in journal(app)] == ['echec', 'echec']
    page = admin.get('/admin/reservations').get_data(as_text=True)
    assert 'pas reçu leur dernier email' in page and 'non parti' in page

    # On confirme : l'email repart (le service remarche)
    mails.echouer = False
    resa_id = reservations(app)[0].id
    admin.post(f'/changer_statut/{resa_id}', data={'nouveau_statut': 'confirmee'})
    page = admin.get('/admin/reservations').get_data(as_text=True)
    assert 'pas reçu leur dernier email' not in page
    # Bouton « renvoyer »
    admin.post(f'/admin/reservation/{resa_id}/renvoyer')
    assert len(mails.pour('jeanne@example.org')) == 2


def test_alerte_demandes_en_attente_depuis_24h(app, admin, mails):
    jour = jours_ouvrables(1, depart=3)[0]
    with app.app_context():
        from datetime import datetime
        db.session.add(Reservation(reference=f'Table1-{jour}', nom='Ancienne', email='a@example.org', date=jour,
                                   heure='11:55', personnes=2, statut='en_attente',
                                   created_at=datetime.utcnow() - timedelta(hours=30)))
        db.session.commit()
    page = admin.get('/admin/reservations').get_data(as_text=True)
    assert 'attendent une validation depuis plus de 24 h' in page


def test_mode_test_signale(app, admin, mails, monkeypatch):
    monkeypatch.setattr(rc, 'TEST_EMAIL_REDIRECT', 'dev@example.org')
    page = admin.get('/admin/reservations').get_data(as_text=True)
    assert 'Mode test actif' in page


# --- Sécurité de l'admin ------------------------------------------------------

def test_changer_statut_exige_la_connexion(app, client, mails):
    client.post('/reservation/creer_reservation', data=formulaire())
    resa_id = reservations(app)[0].id
    r = app.test_client().post(f'/changer_statut/{resa_id}', data={'nouveau_statut': 'annulee'})
    assert r.status_code == 302 and '/admin/login' in r.headers['Location']
    assert reservations(app)[0].statut == 'en_attente'


def test_suppression_de_plat_exige_la_connexion(app, client):
    r = client.post('/supprimer_plat/1')
    assert r.status_code == 302 and '/admin/login' in r.headers['Location']


def test_mauvais_mot_de_passe_refuse(app, client):
    r = client.post('/admin/login', data={'username': 'admin', 'password': MOT_DE_PASSE_TEST + '-faux'})
    assert r.status_code == 200      # reste sur la page de connexion
    assert client.get('/admin/reservations').status_code == 302


def test_blocage_apres_5_essais(app, client):
    for _ in range(5):
        client.post('/admin/login', data={'username': 'admin', 'password': MOT_DE_PASSE_TEST + '-faux'})
    r = client.post('/admin/login', data={'username': 'admin', 'password': MOT_DE_PASSE_TEST})
    assert r.status_code == 429


def test_connexion_desactivee_sans_mot_de_passe(app, client, monkeypatch):
    import main
    monkeypatch.setattr(main, 'ADMIN_PASSWORD', '')
    r = client.post('/admin/login', data={'username': 'admin', 'password': ''})
    assert 'Connexion désactivée' in r.get_data(as_text=True)


# --- Saisie téléphonique, fermetures, fiche -------------------------------------

def test_reservation_par_telephone(app, client, admin, mails):
    jour = jours_ouvrables(1)[0]
    r = admin.post('/admin/reservations/ajouter', data={
        'nom': 'Mme Peeters', 'telephone': '02 660 00 00', 'email': '', 'date': jour,
        'personnes': '4', 'heure': '11:55', 'statut': 'confirmee', 'envoyer_email': '1'})
    assert r.status_code == 302
    resa = reservations(app)[0]
    assert resa.source == 'telephone' and resa.statut == 'confirmee' and resa.email == ''
    assert mails.envoyes == []      # pas d'email : rien n'est envoyé
    # Elle compte dans les places du jour
    assert client.get('/reservation/api/occupation-dates').get_json()['occupation'][jour] == 4
    page = admin.get('/admin/reservations').get_data(as_text=True)
    assert 'Mme Peeters' in page and 'bi-telephone' in page


def test_telephone_jour_complet_demande_de_forcer(app, admin, mails):
    jour = jours_ouvrables(1)[0]
    maximum = rc.max_personnes_pour_date(jour)
    donnees = {'nom': 'Groupe', 'date': jour, 'personnes': str(maximum + 1), 'statut': 'confirmee'}
    admin.post('/admin/reservations/ajouter', data=donnees)
    assert reservations(app) == []
    admin.post('/admin/reservations/ajouter', data=dict(donnees, forcer='1'))
    assert len(reservations(app)) == 1


def test_fermeture_sur_une_periode_ignore_les_week_ends(app, admin):
    debut = date.today() + timedelta(days=14)
    admin.post('/admin/fermetures', data={'debut': debut.isoformat(),
                                          'fin': (debut + timedelta(days=13)).isoformat(),
                                          'motif': "Congés d'hiver"})
    with app.app_context():
        jours = [j.date for j in JourFerme.query.all()]
    assert len(jours) == 10      # 2 semaines = 10 jours de semaine
    page = admin.get('/admin/fermetures').get_data(as_text=True)
    assert "Congés d&#39;hiver" in page or "Congés d'hiver" in page


def test_modifier_une_fiche_garde_11h55(app, client, admin, mails):
    client.post('/reservation/creer_reservation', data=formulaire())
    resa = reservations(app)[0]
    page = admin.get(f'/admin/reservation/modifier/{resa.id}').get_data(as_text=True)
    assert '<option value="11:55" selected>' in page


def test_pages_publiques_et_admin_s_affichent(app, client, admin):
    for url in ('/accueil', '/reservation/reserver', '/carte'):
        assert client.get(url).status_code == 200, url
    for url in ('/admin/reservations', '/admin/reservations/par-date', '/admin/reservations/ajouter',
                '/admin/fermetures', '/admin/menu'):
        assert admin.get(url).status_code == 200, url


# --- Le client modifie lui-même sa réservation ---------------------------------

import re  # noqa: E402


def chemin_modif(mails, adresse):
    """Chemin du lien « Modifier ou annuler ma réservation » du dernier email."""
    html = mails.pour(adresse)[-1]['html']
    return re.search(r'https?://[^/"]+(/reservation/modifier/[^"<\s]+)', html).group(1)


def test_lien_de_modification_dans_l_email(app, client, mails):
    client.post('/reservation/creer_reservation', data=formulaire())
    page = app.test_client().get(chemin_modif(mails, 'jeanne@example.org'))   # depuis un autre appareil
    assert page.status_code == 200 and 'Ma réservation' in page.get_data(as_text=True)


def test_lien_falsifie_refuse(app, client):
    assert client.get('/reservation/modifier/faux.jeton').status_code == 404


def test_client_passe_de_2_a_4_personnes(app, client, mails):
    client.post('/reservation/creer_reservation', data=formulaire())
    resa = reservations(app)[0]
    app.test_client().post(chemin_modif(mails, 'jeanne@example.org'), data={f'personnes_{resa.id}': '4'})
    assert reservations(app)[0].personnes == 4
    assert 'de 2 à 4 personnes' in mails.pour('resto@example.org')[-1]['html']
    assert 'Votre réservation est modifiée' in mails.pour('jeanne@example.org')[-1]['html']


def test_modification_refusee_sans_place(app, client, mails):
    jour = jours_ouvrables(1)[0]
    with app.app_context():
        db.session.add(Reservation(reference=f'Table1-{jour}', nom='X', email='x@example.org', date=jour,
                                   heure='11:55', personnes=rc.max_personnes_pour_date(jour) - 2, statut='confirmee'))
        db.session.commit()
    client.post('/reservation/creer_reservation', data=formulaire(dates=jour))
    resa = [r for r in reservations(app) if r.email == 'jeanne@example.org'][0]
    app.test_client().post(chemin_modif(mails, 'jeanne@example.org'), data={f'personnes_{resa.id}': '5'})
    assert [r for r in reservations(app) if r.email == 'jeanne@example.org'][0].personnes == 2


def test_client_annule_une_des_deux_dates(app, client, mails):
    client.post('/reservation/creer_reservation', data=formulaire(dates=','.join(jours_ouvrables(2))))
    premiere, seconde = reservations(app)
    app.test_client().post(chemin_modif(mails, 'jeanne@example.org'), data={f'annuler_{premiere.id}': '1'})
    premiere, seconde = reservations(app)
    assert premiere.statut == 'annulee' and seconde.statut == 'en_attente'
    assert 'annulée par le client' in mails.pour('resto@example.org')[-1]['html']


def test_passer_a_plus_de_10_remet_en_attente(app, client, mails, monkeypatch):
    monkeypatch.setattr(rc, 'CONFIRMATION_AUTOMATIQUE', True)
    client.post('/reservation/creer_reservation', data=formulaire(personnes='8'))
    resa = reservations(app)[0]
    assert resa.statut == 'confirmee'
    app.test_client().post(chemin_modif(mails, 'jeanne@example.org'), data={f'personnes_{resa.id}': '12'})
    resa = reservations(app)[0]
    assert resa.personnes == 12 and resa.statut == 'en_attente'


def test_le_jour_meme_on_telephone(app, client, mails):
    with app.app_context():
        db.session.add(Reservation(reference='Table1-auj', groupe_reference='Groupe-aujourdhui', nom='Y',
                                   email='y@example.org', date=date.today().isoformat(), heure='11:55',
                                   personnes=2, statut='confirmee'))
        db.session.commit()
        jeton = rc.jeton_modification('Groupe-aujourdhui')
        resa_id = Reservation.query.filter_by(reference='Table1-auj').first().id
    page = client.get(f'/reservation/modifier/{jeton}').get_data(as_text=True)
    assert 'appelez-nous' in page and 'Enregistrer le nombre de personnes' not in page
    client.post(f'/reservation/modifier/{jeton}', data={f'personnes_{resa_id}': '5'})
    assert reservations(app)[0].personnes == 2


def test_doublon_meme_email_renvoie_le_lien(app, client, mails):
    client.post('/reservation/creer_reservation', data=formulaire(personnes='8'))
    client.post('/reservation/creer_reservation', data=formulaire(personnes='10'))   # « la table de 8 passée à 10 »
    assert len(reservations(app)) == 1
    dernier = mails.pour('jeanne@example.org')[-1]['html']
    assert 'Vous avez déjà une réservation' in dernier and '/reservation/modifier/' in dernier


def test_doublon_meme_telephone_autre_email(app, client, mails):
    client.post('/reservation/creer_reservation', data=formulaire())
    client.post('/reservation/creer_reservation',
                data=formulaire(email='autre@example.org', telephone='+32 470 12 34 56'))
    assert len(reservations(app)) == 1
    assert mails.pour('autre@example.org') == []      # le lien part vers l'adresse déjà connue


def test_apres_une_erreur_la_saisie_reste_affichee(app, client, mails):
    r = client.post('/reservation/creer_reservation',
                    data=formulaire(nom='Marie Lambert', telephone='12', message='Anniversaire'))
    page = r.get_data(as_text=True)
    assert r.status_code == 400
    assert 'value="Marie Lambert"' in page and 'value="jeanne@example.org"' in page and 'Anniversaire</textarea>' in page
    assert 'tel:+32471243279' in page          # numero cliquable sur telephone


def test_un_habitue_reserve_20_jours_d_un_coup(app, client, mails):
    client.post('/reservation/creer_reservation', data=formulaire(dates=','.join(jours_ouvrables(20))))
    assert len(reservations(app)) == 20
    assert len(mails.pour('jeanne@example.org')) == 1 and len(mails.pour('resto@example.org')) == 1


def test_annuler_toutes_les_dates_d_un_coup(app, client, mails):
    client.post('/reservation/creer_reservation', data=formulaire(dates=','.join(jours_ouvrables(3))))
    app.test_client().post(chemin_modif(mails, 'jeanne@example.org'), data={'annuler_tout': '1'})
    assert [r.statut for r in reservations(app)] == ['annulee'] * 3


# --- Places par jour réglées dans l'admin ---------------------------------------

def test_places_par_defaut_puis_reglage_de_la_semaine(app, admin, client):
    lundi = next(j for j in jours_ouvrables(10) if date.fromisoformat(j).weekday() == 0)
    vendredi = next(j for j in jours_ouvrables(10) if date.fromisoformat(j).weekday() == 4)
    with app.app_context():
        assert rc.max_personnes_pour_date(lundi) == 30 and rc.max_personnes_pour_date(vendredi) == 32
    r = admin.post('/admin/places', data={'action': 'semaine', 'places_0': '34', 'places_1': '30',
                                           'places_2': '30', 'places_3': '30', 'places_4': '33'})
    assert r.status_code == 302
    with app.app_context():
        assert rc.max_personnes_pour_date(lundi) == 34 and rc.max_personnes_pour_date(vendredi) == 33
    donnees = client.get('/reservation/api/occupation-dates').get_json()
    assert donnees['places_semaine'] == [34, 30, 30, 30, 33]
    # Second enregistrement : la valeur est remplacée, pas dupliquée
    admin.post('/admin/places', data={'action': 'semaine', 'places_0': '28', 'places_1': '30',
                                       'places_2': '30', 'places_3': '30', 'places_4': '33'})
    with app.app_context():
        assert rc.max_personnes_pour_date(lundi) == 28


def test_places_refuse_un_nombre_farfelu(app, admin):
    admin.post('/admin/places', data={'action': 'semaine', 'places_0': '0', 'places_1': 'abc',
                                       'places_2': '30', 'places_3': '30', 'places_4': '500'})
    with app.app_context():
        assert rc.places_par_jour() == [30, 30, 30, 30, 32]


def test_places_pour_un_jour_precis(app, admin, client, mails):
    jour = jours_ouvrables(1)[0]
    with app.app_context():
        habituel = rc.max_personnes_pour_date(jour)
    admin.post('/admin/places', data={'action': 'jour', 'date': jour, 'maximum': '4', 'motif': 'Salle réduite'})
    with app.app_context():
        assert rc.max_personnes_pour_date(jour) == 4
    assert client.get('/reservation/api/occupation-dates').get_json()['places_exceptions'] == {jour: 4}
    # Le site refuse au-delà de 4 personnes ce jour-là, et accepte jusqu'à 4
    r = client.post('/reservation/creer_reservation', data=formulaire(dates=jour, personnes='5'))
    assert r.status_code == 409 and reservations(app) == []
    r = client.post('/reservation/creer_reservation', data=formulaire(dates=jour, personnes='4'))
    assert r.status_code == 302
    # Même date une seconde fois : le nombre est remplacé
    admin.post('/admin/places', data={'action': 'jour', 'date': jour, 'maximum': '36'})
    with app.app_context():
        assert rc.max_personnes_pour_date(jour) == 36
        from models import CapaciteJour
        exception = CapaciteJour.query.one()
    # Suppression : retour au nombre habituel
    admin.post(f'/admin/places/{exception.id}/supprimer')
    with app.app_context():
        assert rc.max_personnes_pour_date(jour) == habituel


def test_places_signale_les_jours_trop_remplis(app, admin, client, mails):
    jour = jours_ouvrables(1)[0]
    client.post('/reservation/creer_reservation', data=formulaire(dates=jour, personnes='6'))
    admin.post('/admin/places', data={'action': 'jour', 'date': jour, 'maximum': '4'})
    page = admin.get('/admin/places').get_data(as_text=True)
    assert "Plus d'inscrits que de places" in page or "Plus d&#39;inscrits que de places" in page
    assert '6 inscrits pour 4 places' in page
    assert '6 / 4 places' in admin.get('/admin/reservations/par-date').get_data(as_text=True)


def test_places_reservees_a_l_admin(app, client):
    assert client.get('/admin/places').status_code == 302
    assert client.post('/admin/places', data={'action': 'semaine'}).status_code == 302
    assert client.post('/admin/groupe/Groupe-abc/confirmer').status_code == 302
    with app.app_context():
        assert rc.places_par_jour() == [30, 30, 30, 30, 32]


# --- Confirmer toutes les dates d'une demande ----------------------------------

def test_confirmer_toutes_les_dates_envoie_un_seul_message(app, client, admin, mails):
    jours = jours_ouvrables(3)
    client.post('/reservation/creer_reservation', data=formulaire(dates=','.join(jours)))
    groupe = reservations(app)[0].groupe_reference
    page = admin.get('/admin/reservations').get_data(as_text=True)
    assert 'Confirmer ses 3 dates' in page
    mails.envoyes.clear()
    r = admin.post(f'/admin/groupe/{groupe}/confirmer')
    assert r.status_code == 302
    assert all(x.statut == 'confirmee' for x in reservations(app))
    recus = mails.pour('jeanne@example.org')
    assert len(recus) == 1 and 'confirmée' in recus[0]['html']
    for j in jours:
        assert rc.date_fr(j) in recus[0]['html']
    assert 'Confirmer ses' not in admin.get('/admin/reservations').get_data(as_text=True)


# --- SMS ------------------------------------------------------------------------

class FauxSms:
    def __init__(self):
        self.envoyes, self.echouer = [], False

    def __call__(self, numero, texte):
        if self.echouer:
            return False, 'HTTP 402 {"code":"not_enough_credits"}'
        self.envoyes.append((numero, texte))
        return True, None


@pytest.fixture
def sms(monkeypatch):
    faux = FauxSms()
    monkeypatch.setattr(rc, 'SMS_ACTIF', True)
    monkeypatch.setattr(rc, 'envoyer_sms', faux)
    return faux


def test_numero_gsm():
    assert rc.numero_gsm('0470 12 34 56') == '32470123456'
    assert rc.numero_gsm('+32 470/12.34.56') == '32470123456'
    assert rc.numero_gsm('0032470123456') == '32470123456'
    assert rc.numero_gsm('02 660 00 00') is None        # ligne fixe
    assert rc.numero_gsm('0470 12 34') is None          # incomplet
    assert rc.numero_gsm('+33 6 12 34 56 78') is None   # étranger
    assert rc.numero_gsm('') is None and rc.numero_gsm(None) is None


def test_textes_sms_tiennent_en_un_seul_sms(app):
    def resa(jour, personnes=10, statut='confirmee'):
        return {'date': jour, 'heure': '11:55', 'personnes': personnes, 'statut': statut,
                'reference': 'Table12-' + jour, 'groupe_reference': 'Groupe-abcdef12', 'telephone': '0470 12 34 56'}
    with app.app_context():
        for nombre_de_dates, avec_lien in [(n, l) for n in (1, 2, 4, 5, 40) for l in (False, True)]:
            resas = [resa(j) for j in jours_ouvrables(nombre_de_dates)]
            if avec_lien:
                resas[0]['lien_court'] = 'www.leboucheaoreilles.be/m/abcdefghjk'
            for type_mail in ('confirmation', 'annulation', 'modification', 'reception', 'lien_modification'):
                texte = rc.texte_sms(type_mail, resas)
                if avec_lien and type_mail in ('confirmation', 'modification', 'lien_modification'):
                    assert '/m/abcdefghjk' in texte, (type_mail, nombre_de_dates, texte)
                assert len(texte) <= 160, (type_mail, nombre_de_dates, len(texte), texte)
                assert texte.isascii(), texte           # pas d'accent : sinon le SMS compte double
                assert rc.RESTAURANT_TEL in texte or '/m/' in texte
        mixte = [resa(j, p) for j, p in zip(jours_ouvrables(3), (2, 4, 60))]
        assert len(rc.texte_sms('modification', mixte)) <= 160
        tout_annule = [resa(j, statut='annulee') for j in jours_ouvrables(2)]
        assert 'annulee' in rc.texte_sms('modification', tout_annule)


def test_pas_de_sms_tant_que_ce_n_est_pas_active(app, client, admin, mails, monkeypatch):
    appels = []
    monkeypatch.setattr(rc, 'envoyer_sms', lambda n, t: appels.append(n) or (True, None))
    client.post('/reservation/creer_reservation', data=formulaire())
    admin.post(f'/changer_statut/{reservations(app)[0].id}', data={'nouveau_statut': 'confirmee'})
    assert appels == []
    # Et sans SMS, l'email reste obligatoire
    r = client.post('/reservation/creer_reservation', data=formulaire(email='', dates=jours_ouvrables(2)[1]))
    assert r.status_code == 400 and len(reservations(app)) == 1


def test_sms_a_la_confirmation_un_seul_pour_plusieurs_dates(app, client, admin, mails, sms):
    jours = jours_ouvrables(3)
    client.post('/reservation/creer_reservation', data=formulaire(dates=','.join(jours), sms='1'))
    assert sms.envoyes == []                    # simple réception : pas de SMS (coût)
    admin.post(f'/admin/groupe/{reservations(app)[0].groupe_reference}/confirmer')
    assert len(sms.envoyes) == 1
    numero, texte = sms.envoyes[0]
    assert numero == '32470123456' and 'confirmee' in texte and '2 pers.' in texte
    assert len(mails.pour('jeanne@example.org')) == 2      # réception + confirmation, l'email part toujours
    with app.app_context():
        journal = EmailEnvoi.query.filter_by(canal='sms').one()
        assert journal.type_mail == 'sms_confirmation' and journal.statut == 'envoye'
    page = admin.get('/admin/reservations').get_data(as_text=True)
    assert 'bi-phone' in page and 'SMS envoyés ce mois-ci : 1 (environ 0,10 €)' in page
    assert 'Emails envoyés : 3 aujourd' in page          # réception + copie au resto + confirmation


def test_sms_a_l_annulation_et_a_la_confirmation_automatique(app, client, admin, mails, sms, monkeypatch):
    monkeypatch.setattr(rc, 'CONFIRMATION_AUTOMATIQUE', True)
    client.post('/reservation/creer_reservation', data=formulaire(sms='1'))
    assert len(sms.envoyes) == 1 and 'confirmee' in sms.envoyes[0][1]
    admin.post(f'/changer_statut/{reservations(app)[0].id}', data={'nouveau_statut': 'annulee'})
    assert len(sms.envoyes) == 2 and 'annulee' in sms.envoyes[1][1]


def test_sans_email_avec_gsm_quand_les_sms_sont_actifs(app, client, admin, mails, sms):
    r = client.post('/reservation/creer_reservation', data=formulaire(email=''))
    assert r.status_code == 302
    resa = reservations(app)[0]
    assert resa.email == ''
    assert mails.pour('resto@example.org')      # le restaurant est prévenu
    page = client.get(r.headers['Location']).get_data(as_text=True)
    assert 'par SMS' in page and 'courrier indésirable' not in page
    admin.post(f'/changer_statut/{resa.id}', data={'nouveau_statut': 'confirmee'})
    assert len(sms.envoyes) == 1
    # Sans email et avec une ligne fixe : on ne peut prévenir personne, donc refusé
    r = client.post('/reservation/creer_reservation',
                    data=formulaire(email='', telephone='02 660 00 00', dates=jours_ouvrables(2)[1]))
    assert r.status_code == 400 and 'GSM' in r.get_data(as_text=True)
    assert len(reservations(app)) == 1
    # Une adresse mal écrite reste refusée
    r = client.post('/reservation/creer_reservation', data=formulaire(email='pas-une-adresse', dates=jours_ouvrables(3)[2]))
    assert r.status_code == 400


def test_ligne_fixe_pas_de_sms_mais_email(app, client, admin, mails, sms):
    client.post('/reservation/creer_reservation', data=formulaire(telephone='02 660 00 00'))
    admin.post(f'/changer_statut/{reservations(app)[0].id}', data={'nouveau_statut': 'confirmee'})
    assert sms.envoyes == []
    assert len(mails.pour('jeanne@example.org')) == 2


def test_sms_en_echec_visible_dans_l_admin_et_email_quand_meme(app, client, admin, mails, sms):
    sms.echouer = True
    client.post('/reservation/creer_reservation', data=formulaire(sms='1'))
    admin.post(f'/changer_statut/{reservations(app)[0].id}', data={'nouveau_statut': 'confirmee'})
    assert len(mails.pour('jeanne@example.org')) == 2
    page = admin.get('/admin/reservations').get_data(as_text=True)
    assert 'SMS non parti' in page and 'crédits SMS' in page


def test_pas_de_sms_en_mode_test(app, client, admin, mails, sms, monkeypatch):
    monkeypatch.setattr(rc, 'TEST_EMAIL_REDIRECT', 'test@example.org')
    client.post('/reservation/creer_reservation', data=formulaire(sms='1'))
    admin.post(f'/changer_statut/{reservations(app)[0].id}', data={'nouveau_statut': 'confirmee'})
    assert sms.envoyes == []


def test_sms_quand_le_client_modifie(app, client, admin, mails, sms):
    jours = jours_ouvrables(2)
    client.post('/reservation/creer_reservation', data=formulaire(dates=','.join(jours), sms='1'))
    groupe = reservations(app)[0].groupe_reference
    admin.post(f'/admin/groupe/{groupe}/confirmer')
    with app.app_context():
        jeton = rc.jeton_modification(groupe)
    resas = reservations(app)
    sms.envoyes.clear()
    client.post(f'/reservation/modifier/{jeton}', data={f'personnes_{resas[0].id}': '4', f'personnes_{resas[1].id}': '4'})
    assert len(sms.envoyes) == 1 and '4 pers.' in sms.envoyes[0][1]


def test_saisie_telephone_avec_gsm_envoie_un_sms(app, admin, mails, sms):
    admin.post('/admin/reservations/ajouter', data={
        'nom': 'M. Janssens', 'telephone': '0478 11 22 33', 'email': '', 'date': jours_ouvrables(1)[0],
        'personnes': '2', 'heure': '11:55', 'statut': 'confirmee', 'envoyer_email': '1'})
    assert len(sms.envoyes) == 1 and sms.envoyes[0][0] == '32478112233'
    page = admin.get('/admin/reservations').get_data(as_text=True)
    assert 'Renvoyer le message' in page
    admin.post(f'/admin/reservation/{reservations(app)[0].id}/renvoyer')
    assert len(sms.envoyes) == 2


def test_envoi_sms_reel_appelle_brevo(app, monkeypatch):
    """L'appel à Brevo lui-même (réseau simulé) : adresse, clé et contenu."""
    recu = {}

    class Reponse:
        status = 201
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def faux_urlopen(requete, timeout=None):
        recu['url'] = requete.full_url
        recu['cle'] = requete.get_header('Api-key')
        recu['corps'] = __import__('json').loads(requete.data.decode())
        return Reponse()

    monkeypatch.setattr(rc.urllib.request, 'urlopen', faux_urlopen)
    ok, erreur = rc.envoyer_sms('32470123456', 'Bonjour')
    assert ok and erreur is None
    assert recu['url'] == 'https://api.brevo.com/v3/transactionalSMS/send'
    assert recu['cle'] == 'cle-factice'
    assert recu['corps'] == {'sender': 'LeBouche', 'recipient': '32470123456', 'content': 'Bonjour',
                             'type': 'transactional', 'tag': 'reservation'}


# --- Le client modifie ou annule sans email : lien court par SMS, page « Retrouver » ---

def test_lien_court_dans_le_sms_mene_a_ma_reservation(app, client, admin, mails, sms):
    client.post('/reservation/creer_reservation', data=formulaire(email=''))
    resa = reservations(app)[0]
    admin.post(f'/changer_statut/{resa.id}', data={'nouveau_statut': 'confirmee'})
    texte = sms.envoyes[0][1]
    assert 'Changer ou annuler : www.leboucheaoreilles.be/m/' in texte and len(texte) <= 160
    code = texte.split('/m/')[1].split()[0]
    autre = app.test_client()                       # un autre appareil, sans session
    r = autre.get(f'/m/{code}')
    assert r.status_code == 302 and '/reservation/modifier/' in r.headers['Location']
    page = autre.get(r.headers['Location']).get_data(as_text=True)
    assert 'Ma réservation' in page and 'Jeanne Dupont' in page
    # Le client annule depuis cette page, sans téléphoner
    autre.post(r.headers['Location'], data={f'annuler_{resa.id}': '1'})
    assert reservations(app)[0].statut == 'annulee'
    assert 'annulee' in sms.envoyes[-1][1]
    assert mails.pour('resto@example.org')[-1]['sujet'].startswith('Réservation modifiée par le client')
    # Le même groupe garde le même code ; un code inventé ne mène nulle part
    with app.app_context():
        assert rc.code_court(resa.groupe_reference) == code
    assert autre.get('/m/aaaaaaaaaa').status_code == 404


def test_retrouver_ma_reservation_par_gsm(app, client, admin, mails, sms):
    client.post('/reservation/creer_reservation', data=formulaire(email=''))
    admin.post(f'/changer_statut/{reservations(app)[0].id}', data={'nouveau_statut': 'confirmee'})
    sms.envoyes.clear()
    page = client.get('/reservation/retrouver').get_data(as_text=True)
    assert 'Recevoir mon lien' in page
    r = client.post('/reservation/retrouver', data={'contact': '+32 470 12 34 56'})
    assert r.status_code == 200 and "C'est envoyé" in r.get_data(as_text=True).replace('&#39;', "'")
    assert len(sms.envoyes) == 1 and '/m/' in sms.envoyes[0][1] and len(sms.envoyes[0][1]) <= 160
    # Numéro inconnu : même réponse à l'écran, mais rien ne part
    r = client.post('/reservation/retrouver', data={'contact': '0499 99 99 99'})
    assert "C'est envoyé" in r.get_data(as_text=True).replace('&#39;', "'")
    assert len(sms.envoyes) == 1


def test_retrouver_ma_reservation_par_email_et_limite(app, client, mails, sms):
    client.post('/reservation/creer_reservation', data=formulaire(telephone='02 660 00 00'))
    mails.envoyes.clear()
    client.post('/reservation/retrouver', data={'contact': 'Jeanne@Example.org'})
    recus = mails.pour('jeanne@example.org')
    assert len(recus) == 1 and '/reservation/modifier/' in recus[0]['html'] and sms.envoyes == []
    # Pas plus de 2 envois par jour pour le même contact (chaque envoi peut coûter un SMS)
    client.post('/reservation/retrouver', data={'contact': 'jeanne@example.org'})
    r = client.post('/reservation/retrouver', data={'contact': 'jeanne@example.org'}, follow_redirects=True)
    assert 'Trop de demandes' in r.get_data(as_text=True)
    assert len(mails.pour('jeanne@example.org')) == 2


def test_doublon_sans_email_recoit_le_lien_par_sms(app, client, admin, mails, sms):
    jour = jours_ouvrables(1)[0]
    client.post('/reservation/creer_reservation', data=formulaire(email='', dates=jour, personnes='3'))
    r = client.post('/reservation/creer_reservation', data=formulaire(email='', dates=jour, personnes='4'))
    assert r.status_code == 409 and len(reservations(app)) == 1
    assert 'par SMS' in r.get_data(as_text=True)
    assert len(sms.envoyes) == 1 and '/m/' in sms.envoyes[0][1]


def test_sms_seulement_si_demande_ou_sans_email(app, client, admin, mails, sms):
    """Avec une adresse email et sans cocher la case : pas de SMS, l'email suffit."""
    page = client.get('/reservation/reserver').get_data(as_text=True)
    assert 'name="sms"' in page
    client.post('/reservation/creer_reservation', data=formulaire())
    resa = reservations(app)[0]
    assert not resa.sms
    admin.post(f'/changer_statut/{resa.id}', data={'nouveau_statut': 'confirmee'})
    assert sms.envoyes == [] and len(mails.pour('jeanne@example.org')) == 2
    # Même numéro retrouvé par la page « Modifier ou annuler » : le lien part par email, pas par SMS
    client.post('/reservation/retrouver', data={'contact': '0470 12 34 56'})
    assert sms.envoyes == [] and len(mails.pour('jeanne@example.org')) == 3
    # La case cochée est bien enregistrée
    client.post('/reservation/creer_reservation',
                data=formulaire(nom='Paul Martin', email='paul@example.org', telephone='0478 11 22 33', sms='1'))
    assert [r.sms for r in reservations(app) if r.nom == 'Paul Martin'] == [True]


def test_case_sms_absente_quand_les_sms_sont_eteints(app, client):
    assert 'name="sms"' not in client.get('/reservation/reserver').get_data(as_text=True)


def test_suivi_des_emails_envoyes_dans_l_admin(app, client, admin, mails):
    client.post('/reservation/creer_reservation', data=formulaire())
    page = admin.get('/admin/reservations').get_data(as_text=True)
    assert 'Emails envoyés : 2 aujourd' in page and '2 ce mois-ci' in page and 'SMS envoyés' not in page


# --- Vue du jour pour les élèves, feuille de service du matin --------------------

def _service_aujourd_hui(app, monkeypatch):
    """Fige « maintenant » à 8h00 le prochain jour de service et y crée trois réservations."""
    import main
    from datetime import datetime as dt, time
    from zoneinfo import ZoneInfo
    jour = jours_ouvrables(1)[0]
    maintenant = dt.combine(date.fromisoformat(jour), time(8, 0), ZoneInfo('Europe/Brussels'))
    monkeypatch.setattr(main, 'maintenant_bruxelles', lambda: maintenant)
    monkeypatch.setattr(main, '_feuille_service_faite', None)
    with app.app_context():
        for i, (nom, personnes, statut, message) in enumerate([
                ('Zoé Martin', 2, 'confirmee', 'Sans gluten'), ('Albert Dubois', 4, 'en_attente', ''),
                ('Annulé Parti', 3, 'annulee', '')]):
            db.session.add(Reservation(reference=f'Table{i + 1}-{jour}', groupe_reference=f'Groupe-vue{i}', nom=nom,
                                       email=f'client{i}@example.org', telephone='0470 12 34 56', date=jour,
                                       heure='11:55', personnes=personnes, statut=statut, message=message))
        db.session.commit()
    return jour, maintenant


def test_vue_du_jour_pour_les_eleves(app, client, admin, monkeypatch):
    jour, _ = _service_aujourd_hui(app, monkeypatch)
    r = admin.get('/admin/vue-du-jour')
    assert r.status_code == 302 and '/salle/' in r.headers['Location']
    lien = r.headers['Location']
    page = client.get(lien)                      # sans être connecté : le lien suffit
    texte = page.get_data(as_text=True)
    assert page.status_code == 200 and page.headers['X-Robots-Tag'].startswith('noindex')
    assert 'Albert Dubois' in texte and 'Zoé Martin' in texte and 'Sans gluten' in texte
    assert texte.index('Albert Dubois') < texte.index('Zoé Martin')        # ordre alphabétique
    assert '6</strong> couverts' in texte and 'à confirmer' in texte
    assert 'Annulé Parti' not in texte                                     # annulée : pas affichée
    assert 'example.org' not in texte and '0470 12 34 56' not in texte     # ni email ni téléphone
    # Mauvais lien : rien. Lien changé dans l'admin : l'ancien ne marche plus.
    assert client.get('/salle/pas-la-bonne-cle').status_code == 404
    assert client.get('/admin/vue-du-jour').status_code == 302 and '/admin/login' in client.get('/admin/vue-du-jour').headers['Location']
    admin.post('/admin/vue-du-jour')
    assert client.get(lien).status_code == 404
    assert client.get(admin.get('/admin/vue-du-jour').headers['Location']).status_code == 200
    assert 'Vue du jour' in admin.get('/admin/reservations/par-date').get_data(as_text=True)


def test_vue_du_jour_ne_montre_pas_le_passe(app, client, admin, monkeypatch):
    jour, _ = _service_aujourd_hui(app, monkeypatch)
    lien = admin.get('/admin/vue-du-jour').headers['Location']
    hier = (date.fromisoformat(jour) - timedelta(days=7)).isoformat()
    texte = client.get(f'{lien}?date={hier}').get_data(as_text=True)
    assert rc.date_fr(jour) in texte and rc.date_fr(hier) not in texte


def test_feuille_de_service_envoyee_une_fois_le_matin(app, mails, monkeypatch):
    import main
    jour, maintenant = _service_aujourd_hui(app, monkeypatch)
    with app.test_request_context():
        assert main.feuille_de_service_si_besoin(maintenant.replace(hour=6, minute=0)) is False     # trop tôt
        assert mails.envoyes == []
        assert main.feuille_de_service_si_besoin(maintenant) is True
        assert main.feuille_de_service_si_besoin(maintenant.replace(hour=9)) is False                # déjà partie
        monkeypatch.setattr(main, '_feuille_service_faite', None)                                    # autre processus
        assert main.feuille_de_service_si_besoin(maintenant.replace(hour=9)) is False
    recus = mails.pour('resto@example.org')
    assert len(recus) == 1
    assert recus[0]['sujet'] == f"Service du {rc.date_fr(jour)} : 2 tables, 6 couverts"
    assert 'Albert Dubois' in recus[0]['html'] and 'en attente' in recus[0]['html'] and 'Sans gluten' in recus[0]['html']
    assert 'Annulé Parti' not in recus[0]['html'] and '/salle/' in recus[0]['html']
    with app.app_context():
        assert EmailEnvoi.query.filter_by(type_mail='feuille_service', statut='envoye').count() == 1


def test_feuille_de_service_pas_le_week_end_ni_un_jour_ferme_ni_trop_tard(app, mails, monkeypatch):
    import main
    jour, maintenant = _service_aujourd_hui(app, monkeypatch)
    samedi = maintenant + timedelta(days=(5 - maintenant.weekday()) % 7 or 7)
    with app.test_request_context():
        assert main.feuille_de_service_si_besoin(samedi) is False
        assert main.feuille_de_service_si_besoin(maintenant.replace(hour=11, minute=30)) is False
        with app.app_context():
            db.session.add(JourFerme(date=jour, motif='Stage'))
            db.session.commit()
        assert main.feuille_de_service_si_besoin(maintenant) is False
        monkeypatch.setattr(rc, 'FEUILLE_SERVICE_HEURE', '')
        monkeypatch.setattr(main, '_feuille_service_faite', None)
        assert main.feuille_de_service_si_besoin(maintenant) is False
    assert mails.envoyes == []


# --- Adresse de contact ------------------------------------------------------------

def test_adresse_de_contact_sur_le_site_et_en_reponse(app, client, admin, mails):
    for page in ('/', '/reservation/reserver'):
        texte = client.get(page, follow_redirects=True).get_data(as_text=True)
        assert rc.CONTACT_EMAIL in texte and 'stbernadette.restaurant@gmail.com' not in texte
    client.post('/reservation/creer_reservation', data=formulaire())
    recu = mails.pour('jeanne@example.org')[0]
    assert recu['repondre_a'] == rc.CONTACT_EMAIL
    # Les copies pour le restaurant partent toujours vers la boîte du resto
    assert mails.pour('resto@example.org')


def test_adresse_de_contact_reglable(app, client, monkeypatch):
    monkeypatch.setattr(rc, 'CONTACT_EMAIL', 'resto@ecole.example')
    assert 'resto@ecole.example' in client.get('/reservation/reserver').get_data(as_text=True)


# --- Retouches du 14/11/2026 --------------------------------------------------

def test_brevo_passe_avant_le_smtp(app, monkeypatch):
    """Railway bloque le SMTP : il ne doit plus être essayé avant Brevo."""
    appels = []
    monkeypatch.setattr(rc, 'SMTP_USER', 'quelquun')
    monkeypatch.setattr(rc, 'SMTP_PASSWORD', MOT_DE_PASSE_TEST)
    monkeypatch.setattr(rc, 'BREVO_API_KEY', 'cle-factice')
    monkeypatch.setattr(rc, 'RESEND_API_KEY', '')
    monkeypatch.setattr(rc, '_envoyer_brevo', lambda *a: appels.append('brevo'))
    monkeypatch.setattr(rc, '_envoyer_smtp', lambda *a: appels.append('smtp'))
    ok, canal, erreur = rc.envoyer_email('client@example.org', 'Sujet', '<p>Bonjour</p>')
    assert (ok, canal, erreur) == (True, 'brevo', None)
    assert appels == ['brevo']


def test_le_smtp_reste_en_secours_si_brevo_echoue(app, monkeypatch):
    appels = []

    def brevo_en_panne(*a):
        appels.append('brevo')
        raise RuntimeError('HTTP Error 401')

    monkeypatch.setattr(rc, 'SMTP_USER', 'quelquun')
    monkeypatch.setattr(rc, 'SMTP_PASSWORD', MOT_DE_PASSE_TEST)
    monkeypatch.setattr(rc, 'BREVO_API_KEY', 'cle-factice')
    monkeypatch.setattr(rc, 'RESEND_API_KEY', '')
    monkeypatch.setattr(rc, '_envoyer_brevo', brevo_en_panne)
    monkeypatch.setattr(rc, '_envoyer_smtp', lambda *a: appels.append('smtp'))
    ok, canal, erreur = rc.envoyer_email('client@example.org', 'Sujet', '<p>Bonjour</p>')
    assert ok and canal == 'smtp'
    assert appels == ['brevo', 'smtp']


def test_le_formulaire_passe_avant_le_mode_d_emploi(app, client):
    page = client.get('/reservation/reserver').get_data(as_text=True)
    assert page.index('id="form-reservation"') < page.index('Comment réserver une table')
    # Les deux raccourcis restent tout en haut, avant le formulaire.
    assert page.index('Vous préférez téléphoner') < page.index('id="form-reservation"')
    assert page.index('/reservation/retrouver') < page.index('id="form-reservation"')


def test_heure_d_impression_a_l_heure_de_bruxelles(app, admin, monkeypatch):
    import main
    from datetime import datetime
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(main, 'maintenant_bruxelles',
                        lambda: datetime(2026, 11, 14, 14, 23, tzinfo=ZoneInfo('Europe/Brussels')))
    page = admin.get('/admin/reservations').get_data(as_text=True)
    assert 'Imprimé le 14/11/2026 à 14:23' in page


def test_bouton_admin_discret_pour_les_clients(app, client, admin):
    page = client.get('/accueil').get_data(as_text=True)
    haut, pied = page.split('<footer', 1)
    assert '/admin/login' not in haut            # plus de bouton « Admin » dans le menu du haut
    assert '/admin/login' in pied and 'Espace équipe' in pied
    # Une fois connectée, l'équipe garde ses raccourcis en haut de page.
    page = admin.get('/accueil').get_data(as_text=True)
    haut = page.split('<footer', 1)[0]
    assert 'Déconnexion' in haut and '/admin/reservations' in haut


def test_bandeau_cookies_sur_une_ligne(app, client):
    page = client.get('/accueil').get_data(as_text=True)
    assert 'cookies techniques' in page
    assert 'rejectCookies()"' not in page        # un seul bouton : OK
