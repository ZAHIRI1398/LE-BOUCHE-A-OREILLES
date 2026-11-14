# Correctifs réservations : ce qui change et comment déployer

Branche `correctifs-reservations`, cinq commits :

1. **Sécurité** : mot de passe admin et clé de session sortis du code, routes admin protégées, fichiers contenant des secrets supprimés.
2. **Réservations** : le restaurant est prévenu à chaque demande, chaque email est noté et visible dans l'admin, confirmation automatique possible, protection contre les robots, saisie des réservations prises par téléphone, jours fermés.
3. **Tests** : tests automatiques (SQLite et PostgreSQL) et ce document.
4. **Côté client** : le client modifie ou annule lui-même sa réservation, les doublons sont évités, les pages et les emails sont plus faciles à lire et à utiliser (une bonne partie de la clientèle est âgée).

5. **Places, SMS, confirmation groupée** (ajout du 11/11/2026) : l'équipe règle elle-même le nombre de places par jour, le client peut recevoir sa confirmation par SMS, et une demande de plusieurs dates se confirme en un clic avec un seul message.

Le premier commit peut partir seul et tout de suite. Les autres touchent au fonctionnement du restaurant et demandent l'avis de l'équipe (voir « Décisions »).

## À faire tout de suite, même sans déployer

Ces secrets ont été publiés dans le dépôt public et restent lisibles dans l'historique git. Les supprimer du code ne suffit pas, il faut les **révoquer** :

- le mot de passe d'application Gmail qui était dans `test_email.py` (compte Google → Sécurité → Mots de passe des applications → supprimer) ;
- les clés Resend écrites dans `reservation_client.py` en juin et en août 2026 (Resend → API Keys → supprimer, puis en créer une nouvelle si Resend reste utilisé) ;
- le mot de passe admin du site (il apparaît aussi dans un message de commit).

Ensuite, passer le dépôt en **privé** (GitHub → Settings → General → Danger Zone → Change visibility). Railway continue de déployer tant que son application GitHub a accès au dépôt.

## Variables Railway à régler avant le déploiement

| Variable | Valeur | Remarque |
|---|---|---|
| `ADMIN_PASSWORD` | un nouveau mot de passe long | **Obligatoire.** Sans elle, la connexion admin est désactivée. |
| `ADMIN_USERNAME` | `admin` par défaut | Facultatif. |
| `SECRET_KEY` | longue chaîne aléatoire | Générer avec `python -c "import secrets; print(secrets.token_hex(32))"`. Sans elle, les sessions admin sautent à chaque redémarrage. |
| `RESTAURANT_EMAIL` | adresse qui reçoit chaque nouvelle réservation | Par défaut `stbernadette.restaurant@gmail.com`. Reçoit aussi les changements faits par les clients et la feuille de service du matin. |
| `CONTACT_EMAIL` | adresse de contact montrée aux clients | Par défaut `frederic.cuvelier@sainte-bernadette-secondaire.be` (choix de Fred, 13/11/2026). Affichée sur l'accueil, en pied de page et pour les données personnelles ; c'est aussi l'adresse de réponse des emails envoyés aux clients. Pour en changer (adresse de fonction, par exemple), il suffit de modifier cette variable. |
| `RESTAURANT_TEL` | `0471 24 32 79` par défaut | Affiché dans les emails et les messages d'erreur, et cliquable sur téléphone. |
| `SITE_URL` | `https://www.leboucheaoreilles.be` par défaut | Adresse utilisée dans les liens des emails. |
| `MAX_DATES_PAR_DEMANDE` | `40` par défaut | Nombre de dates qu'on peut cocher en une demande. |
| `CONFIRMATION_AUTOMATIQUE` | `1` pour l'activer | Désactivée par défaut (comportement actuel). Voir « Décisions ». |
| `FEUILLE_SERVICE_HEURE` | `07:30` par défaut | Heure (de Bruxelles) à partir de laquelle la feuille de service du jour part vers `RESTAURANT_EMAIL`. Mettre `non` pour ne pas l'envoyer. |
| `RAPPEL_VEILLE_HEURE` | `10:00` par défaut | Heure (de Bruxelles) à partir de laquelle part, la veille d'un jour de service, l'email de rappel aux clients dont la table est confirmée pour le lendemain (ajout du 14/11/2026). Jamais de SMS. Pas de rappel pour une réservation prise le jour même, ni pour une adresse qui sert à plusieurs clients différents ce jour-là (réservations encodées par l'équipe). Mettre `non` pour ne pas l'envoyer. |
| `SMS_ACTIF` | `1` pour activer les SMS | Désactivés par défaut. Voir « SMS » plus bas : il faut d'abord acheter des crédits SMS dans Brevo. |
| `SMS_EXPEDITEUR` | `LeBouche` par défaut | Nom affiché comme expéditeur du SMS : 11 caractères maximum, lettres et chiffres uniquement. |
| `SMS_TYPES` | `confirmation,annulation,modification` par défaut | Les cas où un SMS part. Ajouter `reception` pour un SMS dès la demande (un SMS de plus par demande). |
| `SMS_PRIX_UNITAIRE` | `0.095` par défaut | Prix d'un SMS, pour l'estimation affichée dans l'admin. À ajuster selon le tarif du compte. |
| `TEST_EMAIL_REDIRECT` | **vide ou supprimée** | Si elle est remplie, aucun client ne reçoit ses emails. L'admin affiche maintenant un bandeau rouge dans ce cas. |
| `SMTP_USER` / `SMTP_PASSWORD` | facultatif, dernier recours | Railway bloque le SMTP sur les offres Free, Trial et Hobby. Depuis le 14/11/2026, ce canal n'est essayé qu'après Brevo et Resend : il ne ralentit plus rien et peut être retiré. |
| `BREVO_API_KEY` / `BREVO_FROM` | clé Brevo + expéditeur validé | Offre gratuite : 300 emails par jour, largement assez. Authentifier le domaine `leboucheaoreilles.be` dans Brevo (SPF, DKIM, DMARC) pour que les emails n'arrivent pas en indésirables. |
| `RESEND_API_KEY` | facultatif, en secours | L'offre gratuite (3 000 par mois, 100 par jour) suffit aussi. Une offre payante n'est pas nécessaire au volume du restaurant. |

## Base de données

Rien à lancer à la main. Au démarrage, `db.create_all()` crée les tables `email_envois` (journal des emails et des SMS), `jours_fermes`, `reglages` et `capacites_jour` (places par jour), `liens_courts` (liens des SMS), et `migrer_colonnes_manquantes()` ajoute les colonnes `reservations.source` (`web` ou `telephone`, `web` pour les lignes existantes) et `reservations.sms` (case « par SMS », décochée pour les lignes existantes). Testé sur PostgreSQL 16 avec une base créée par l'ancienne version, et sur SQLite.

L'instruction `ALTER COLUMN ... TYPE VARCHAR(30)` ne tourne plus que sur PostgreSQL (elle plantait le démarrage en local sous SQLite).

## Ce qui change pour l'équipe

- **Un email au restaurant pour chaque nouvelle demande**, avec toutes les dates, le téléphone et le message du client. Avant, personne n'était prévenu : une demande pouvait rester « en attente » indéfiniment.
- **Colonne « Statut / email » dans la liste** : on voit si l'email du client est parti ou non (survol = détail de l'erreur). Bandeaux en haut de la liste quand un email n'est pas parti, quand des demandes attendent depuis plus de 24 h, quand aucun service d'envoi n'est configuré ou quand le mode test est actif. Bouton ✉ pour renvoyer une confirmation.
- **Un seul email par demande**, même avec plusieurs dates (avant : un email par date).
- **« Ajouter (téléphone) »** : les réservations prises au téléphone entrent dans la même liste et comptent dans les places du jour. Email facultatif. Lien direct depuis chaque jour de la page « Par date ».
- **« Jours fermés »** : congés, stages, jours fériés. Ces jours sont hachurés dans le calendrier du site et refusés par le serveur. La page signale les réservations déjà prises sur un jour devenu fermé.
- **Groupes de plus de 10 personnes** : l'option « Plus de 10 » enregistrait 0 personne, donc le groupe ne comptait pas dans les places. Le client doit maintenant donner le nombre exact, et un groupe reste toujours à valider à la main.
- **Fiche « Modifier »** : enregistrer une fiche remplaçait 11:55 par 12:00 (option absente de la liste). Corrigé.

- **Le client modifie ou annule lui-même** : chaque email client contient un gros bouton « Modifier ou annuler ma réservation » (lien personnel, signé avec `SECRET_KEY`, impossible à deviner). Il change le nombre de personnes avec des boutons − et + (les places sont contrôlées) ou annule un jour, jusqu'à la veille. Le jour même, il téléphone. Le restaurant reçoit un email à chaque changement, et une table qui passe au-delà de 10 personnes repasse « en attente ». Si `SECRET_KEY` change, les anciens liens ne marchent plus.
- **Plus de doublons** : une table de 8 qui repasse pour 10 créait une deuxième réservation. Maintenant, si quelqu'un réserve le même jour avec le même email ou le même téléphone, rien n'est créé : le lien de modification est renvoyé à l'adresse déjà connue.
- **Plus facile à lire et à utiliser** : textes, champs et boutons plus grands sur les pages client et dans les emails ; après une erreur, ce que le client a tapé reste affiché ; bouton pour appeler le restaurant directement depuis un téléphone ; légende des couleurs sous le calendrier ; pour les habitués, un clic sur la lettre d'un jour (L, M, M, J, V) coche tous ces jours-là du mois, et un bouton coche tous les jours libres du mois ; sur la page « Ma réservation », un réglage « même nombre pour toutes les dates » et un bouton « Annuler toutes mes dates » ; remplissage automatique du nom, de l'email et du téléphone par le navigateur.

## Emails : rester dans le gratuit (commit 5)

Le site envoyait un email par date, à la réception puis à la confirmation : un habitué qui réserve 15 dates recevait 30 emails. Avec ces correctifs, c'est un email par demande (commits 2 et 5, bouton « Confirmer ses N dates »), soit deux ou trois emails par demande en comptant la copie au restaurant.

À ce rythme, l'offre gratuite de Brevo (300 emails par jour) suffit largement, et celle de Resend (3 000 par mois, 100 par jour) peut rester en secours. Aucune offre payante n'est nécessaire : si un abonnement Resend ou Brevo court encore, il peut être arrêté une fois ces correctifs en ligne. Le compteur en haut de la liste des réservations (« Emails envoyés : N aujourd'hui, N ce mois-ci ») permet de le vérifier.

Ordre des canaux : Brevo, puis Resend, puis SMTP en dernier recours.

## Vue du jour pour les élèves (commit 5)

Bouton « Vue du jour (élèves) » sur la page « Par date ». Il ouvre une page à part (`/salle/<clé>`) avec les tables du jour par ordre alphabétique : nom, couverts, remarques, et une case « Arrivé » à cocher. **Ni email ni téléphone** : la page est faite pour être confiée aux élèves à l'accueil, sur une tablette ou imprimée. Elle ne montre que le jour même et les trois semaines à venir.

L'adresse contient une clé tirée au hasard : pas de mot de passe à donner aux élèves. Si l'adresse a circulé, le bouton « Nouveau lien » la remplace et l'ancienne ne fonctionne plus. Les cases « Arrivé » restent sur l'appareil, rien n'est enregistré sur le site.

## Feuille de service du matin (commit 5)

Chaque jour de service (lundi à vendredi, hors jours fermés), à partir de 7h30, le restaurant reçoit un email « Service du mardi 17/11/2026 : 14 tables, 32 couverts » avec la liste des tables, les couverts, les téléphones et les remarques, plus le lien vers la vue du jour. Un seul email par jour, même avec plusieurs processus gunicorn (la table `reglages` sert d'arbitre). L'envoi se fait à la première visite du site après 7h30, et sinon par un fil d'exécution qui regarde l'heure toutes les cinq minutes ; plus rien ne part après 11h. Si Railway met l'application en veille (option « App Sleeping »), la feuille partira au premier réveil de la matinée.

## Places par jour (commit 5)

- **Page « Places » dans l'admin** : un nombre de places pour chaque jour de la semaine, et au besoin un nombre différent pour un jour précis (banquet, classe en stage, salle réduite). Le calendrier du site et les contrôles du serveur en tiennent compte tout de suite. Plus besoin de toucher au code pour passer de 30 à 34.
- Tant que rien n'est réglé dans l'admin, les valeurs en vigueur depuis novembre restent appliquées : 30 du lundi au jeudi, 32 le vendredi. Les anciennes constantes (`MAX_PERSONNES_PAR_DATE`, `NOV_DEBUT`…) ont disparu du code.
- Baisser le nombre de places n'annule rien : la page signale les jours où il y a déjà plus d'inscrits que de places, et la page « Par date » affiche « inscrits / places » avec un raccourci pour régler ce jour-là.

## Confirmer toutes les dates d'une demande (commit 5)

Un habitué qui réserve 15 dates demandait 15 clics, et recevait 15 emails. Le bouton « Confirmer ses N dates » (liste des réservations) confirme toute la demande : le client reçoit **un seul** email, et un seul SMS, qui reprend toutes les dates. C'est aussi ce qui fait baisser le plus le nombre d'emails envoyés.

## SMS (commit 5)

- **Envoi par Brevo**, avec la même clé `BREVO_API_KEY` que les emails (API `POST /v3/transactionalSMS/send`). Aucun abonnement : on achète des crédits SMS dans le compte Brevo (lots de 100 crédits, sans date d'expiration). Vers la Belgique, un SMS coûte environ 9,5 crédits, soit à peu près 0,095 € (tarif relevé début novembre 2026 : à vérifier dans le compte, Mon offre → crédits SMS).
- **Pour qui** : seulement les clients qui cochent « Envoyez-moi ma confirmation par SMS » sur le formulaire, et ceux qui n'ont pas donné d'adresse email. Les autres reçoivent leurs emails comme avant. C'est ce qui garde la facture SMS à quelques euros par mois. Pour une réservation saisie par l'équipe (« Ajouter (téléphone) »), cocher « Envoyer la confirmation » vaut demande de SMS.
- **Quand** : à la confirmation, à l'annulation par le restaurant, et quand le client modifie. Pas à la simple réception de la demande (réglable avec `SMS_TYPES`).
- **Un seul SMS par demande**, même avec plusieurs dates. Le texte est écrit sans accent et tient en moins de 160 caractères : il compte toujours pour un seul SMS. Exemple : « Le Bouche a Oreilles : table confirmee, 4 pers. le mar. 17/11 a 11h55. Changer ou annuler : www.leboucheaoreilles.be/m/k7mq2xw9pa ou tel. 0471 24 32 79 ».
- **Le SMS contient un lien court** (`/m/<code>`, code tiré au hasard, table `liens_courts`) vers la page « Ma réservation » : le client change le nombre de personnes ou annule depuis son GSM, sans email et sans téléphoner.
- **Seulement vers les GSM belges** (04…). Une ligne fixe ou un numéro étranger ne reçoit pas de SMS : l'email part comme avant.
- **L'email continue de partir** en plus du SMS quand le client a donné une adresse. Quand les SMS sont actifs, l'adresse email devient facultative sur le site pour qui donne un numéro de GSM : une personne sans email peut enfin réserver en ligne. Elle modifie ou annule par le lien de son SMS.
- **Suivi dans l'admin** : pastille « SMS » à côté du statut, bandeau rouge si le dernier SMS n'est pas parti (crédits épuisés, par exemple), et, en haut de la liste, le nombre d'emails partis aujourd'hui et ce mois-ci, et le nombre de SMS du mois avec le coût estimé. Si les SMS tombent en panne, le site et les emails continuent de fonctionner.
- En mode test (`TEST_EMAIL_REDIRECT`), aucun SMS ne part.

Pour activer : acheter des crédits SMS dans Brevo, mettre `SMS_ACTIF=1` dans Railway, faire une réservation de test avec son propre GSM et la confirmer.

## « Modifier ou annuler » sans retrouver son message (commit 5)

Nouvelle page `/reservation/retrouver`, liée depuis le menu du site et depuis le formulaire : le client tape le numéro de GSM ou l'adresse email donnés à la réservation et reçoit le lien vers sa réservation (par SMS si les SMS sont actifs et que c'est un GSM, sinon par email). La page répond la même chose qu'une réservation existe ou non. Limites : 5 demandes par heure et par connexion, 2 par jour pour un même numéro ou une même adresse (chaque envoi peut coûter un SMS).

Une réservation en double avec le même GSM et sans email reçoit maintenant ce lien par SMS au lieu d'un « appelez-nous ».

**À savoir pour l'équipe** : le site refuse une deuxième réservation le même jour avec le même email ou le même téléphone. Les réservations prises au téléphone ne doivent donc plus être encodées par le formulaire public avec les coordonnées d'un professeur : elles passent par « Ajouter (téléphone) » dans l'admin, avec le numéro du client (c'est lui qui reçoit le SMS).

## Protection du formulaire

- Champ piège invisible pour les robots.
- 5 demandes maximum par heure et par adresse IP, 40 dates maximum par demande (les habitués réservent parfois 15 ou 20 fois par mois ; réglable avec `MAX_DATES_PAR_DEMANDE`).
- Contrôle serveur des dates (pas de date passée, pas de week-end, pas plus de 6 mois à l'avance, pas de jour fermé), du nombre de personnes, de l'email et du téléphone.
- Le nom et le message du client sont échappés dans les emails : impossible d'y glisser un lien ou du HTML (sinon le formulaire peut servir à envoyer du spam au nom du restaurant).
- Le bouton « Réserver » se désactive après le clic (doubles envois).

## Décisions à prendre avec l'équipe

1. **Confirmation automatique** (`CONFIRMATION_AUTOMATIQUE=1`) : s'il reste de la place et que le jour n'est pas fermé, la table est réservée tout de suite et le client reçoit directement sa confirmation. L'équipe garde la main pour annuler. C'est ce qui supprime le plus sûrement les réservations « jamais confirmées », à condition que les jours fermés soient encodés.
2. **Adresse qui reçoit les nouvelles réservations** (`RESTAURANT_EMAIL`) et qui la consulte chaque jour.
3. **SMS** : les activer ou non, et qui achète les crédits (voir « SMS »). Avec la confirmation automatique, chaque demande en ligne coûte un SMS.

## Après la mise en ligne

1. Se connecter à l'admin avec le nouveau mot de passe.
2. Faire une réservation de test avec sa propre adresse : la colonne « Statut / email » doit afficher « reception » en vert, et le restaurant doit recevoir sa copie.
3. Vérifier la page « Places » et y mettre les nombres voulus.
4. Encoder les jours fermés. Officiel (calendrier scolaire FWB 2026-2027) : vacances d'hiver du 21/12/2026 au 3/01/2027, vacances de détente du 22/02 au 7/03/2027, vacances de printemps du 26/04 au 9/05/2027, fin des cours le 2/07/2027. Jours fériés : 11/11/2026, 29/03/2027 (lundi de Pâques), 17/05/2027 (lundi de Pentecôte). Le 6/05/2027 (Ascension) tombe déjà dans les vacances de printemps. À compléter par l'équipe : semaines de stage, journées pédagogiques, examens.
5. Vérifier les demandes de groupe déjà enregistrées avec 0 personne (ancienne option « Plus de 10 ») : le vrai nombre est peut-être dans le message, sinon rappeler le client.

## Tests

```
pip install pytest
python -m pytest tests                     # SQLite
TEST_DATABASE_URL=postgresql://... python -m pytest tests   # PostgreSQL
```

Les emails sont simulés pendant les tests (aucun envoi réel).

## Pas traité ici

- Pas de jeton CSRF sur les formulaires admin (le cookie `SameSite=Lax` bloque déjà les envois depuis un autre site).
- Les compteurs anti-robots sont en mémoire : ils repartent à zéro à chaque redémarrage, ce qui suffit pour ce site.
- `postgres-backup/node_modules` est toujours suivi par git, et `generate_reference()` dans `main.py` n'est plus utilisé.
