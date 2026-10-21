"""Tests des correctifs : réservations, emails, sécurité de l'admin."""
from datetime import date, timedelta

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
