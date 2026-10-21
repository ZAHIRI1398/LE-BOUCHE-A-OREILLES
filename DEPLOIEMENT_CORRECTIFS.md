# Correctifs réservations : ce qui change et comment déployer

Branche `correctifs-reservations`, trois commits :

1. **Sécurité** : mot de passe admin et clé de session sortis du code, routes admin protégées, fichiers contenant des secrets supprimés.
2. **Réservations** : le restaurant est prévenu à chaque demande, chaque email est noté et visible dans l'admin, confirmation automatique possible, protection contre les robots, saisie des réservations prises par téléphone, jours fermés.
3. **Tests** : 25 tests automatiques (SQLite et PostgreSQL) et ce document.

Le premier commit peut partir seul et tout de suite. Les deux autres touchent au fonctionnement du restaurant et demandent l'avis de l'équipe (voir « Décisions »).

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
| `RESTAURANT_EMAIL` | adresse qui reçoit chaque nouvelle réservation | Par défaut `stbernadette.restaurant@gmail.com` (l'adresse affichée sur le site). Les clients qui répondent à un email tombent aussi dessus. |
| `RESTAURANT_TEL` | `0471 24 32 79` par défaut | Affiché dans les emails et les messages d'erreur. |
| `CONFIRMATION_AUTOMATIQUE` | `1` pour l'activer | Désactivée par défaut (comportement actuel). Voir « Décisions ». |
| `TEST_EMAIL_REDIRECT` | **vide ou supprimée** | Si elle est remplie, aucun client ne reçoit ses emails. L'admin affiche maintenant un bandeau rouge dans ce cas. |
| `SMTP_USER` / `SMTP_PASSWORD` | à supprimer sur l'offre Hobby | Railway bloque le SMTP sur les offres Free, Trial et Hobby : chaque email perd 15 secondes avant de passer au canal suivant. |
| `BREVO_API_KEY` / `BREVO_FROM` | clé Brevo + expéditeur validé | Offre gratuite : 300 emails par jour, largement assez. Authentifier le domaine `leboucheaoreilles.be` dans Brevo (SPF, DKIM, DMARC) pour que les emails n'arrivent pas en indésirables. |
| `RESEND_API_KEY` | facultatif, en secours | L'offre gratuite (3 000 par mois, 100 par jour) suffit aussi. Une offre payante n'est pas nécessaire au volume du restaurant. |

## Base de données

Rien à lancer à la main. Au démarrage, `db.create_all()` crée les tables `email_envois` (journal des emails) et `jours_fermes`, et `migrer_colonnes_manquantes()` ajoute la colonne `reservations.source` (`web` ou `telephone`, `web` pour les lignes existantes). Testé sur PostgreSQL 16 avec une base créée par l'ancienne version, et sur SQLite.

L'instruction `ALTER COLUMN ... TYPE VARCHAR(30)` ne tourne plus que sur PostgreSQL (elle plantait le démarrage en local sous SQLite).

## Ce qui change pour l'équipe

- **Un email au restaurant pour chaque nouvelle demande**, avec toutes les dates, le téléphone et le message du client. Avant, personne n'était prévenu : une demande pouvait rester « en attente » indéfiniment.
- **Colonne « Statut / email » dans la liste** : on voit si l'email du client est parti ou non (survol = détail de l'erreur). Bandeaux en haut de la liste quand un email n'est pas parti, quand des demandes attendent depuis plus de 24 h, quand aucun service d'envoi n'est configuré ou quand le mode test est actif. Bouton ✉ pour renvoyer une confirmation.
- **Un seul email par demande**, même avec plusieurs dates (avant : un email par date).
- **« Ajouter (téléphone) »** : les réservations prises au téléphone entrent dans la même liste et comptent dans les places du jour. Email facultatif. Lien direct depuis chaque jour de la page « Par date ».
- **« Jours fermés »** : congés, stages, jours fériés. Ces jours sont hachurés dans le calendrier du site et refusés par le serveur. La page signale les réservations déjà prises sur un jour devenu fermé.
- **Groupes de plus de 10 personnes** : l'option « Plus de 10 » enregistrait 0 personne, donc le groupe ne comptait pas dans les places. Le client doit maintenant donner le nombre exact, et un groupe reste toujours à valider à la main.
- **Fiche « Modifier »** : enregistrer une fiche remplaçait 11:55 par 12:00 (option absente de la liste). Corrigé.

## Protection du formulaire

- Champ piège invisible pour les robots.
- 5 demandes maximum par heure et par adresse IP, 10 dates maximum par demande.
- Contrôle serveur des dates (pas de date passée, pas de week-end, pas plus de 6 mois à l'avance, pas de jour fermé), du nombre de personnes, de l'email et du téléphone.
- Le nom et le message du client sont échappés dans les emails : impossible d'y glisser un lien ou du HTML (sinon le formulaire peut servir à envoyer du spam au nom du restaurant).
- Le bouton « Réserver » se désactive après le clic (doubles envois).

## Décisions à prendre avec l'équipe

1. **Confirmation automatique** (`CONFIRMATION_AUTOMATIQUE=1`) : s'il reste de la place et que le jour n'est pas fermé, la table est réservée tout de suite et le client reçoit directement sa confirmation. L'équipe garde la main pour annuler. C'est ce qui supprime le plus sûrement les réservations « jamais confirmées », à condition que les jours fermés soient encodés.
2. **Adresse qui reçoit les nouvelles réservations** (`RESTAURANT_EMAIL`) et qui la consulte chaque jour.

## Après la mise en ligne

1. Se connecter à l'admin avec le nouveau mot de passe.
2. Faire une réservation de test avec sa propre adresse : la colonne « Statut / email » doit afficher « reception » en vert, et le restaurant doit recevoir sa copie.
3. Encoder les jours fermés. Officiel (calendrier scolaire FWB 2026-2027) : vacances d'hiver du 21/12/2026 au 3/01/2027, vacances de détente du 22/02 au 7/03/2027, vacances de printemps du 26/04 au 9/05/2027, fin des cours le 2/07/2027. Jours fériés : 11/11/2026, 29/03/2027 (lundi de Pâques), 17/05/2027 (lundi de Pentecôte). Le 6/05/2027 (Ascension) tombe déjà dans les vacances de printemps. À compléter par l'équipe : semaines de stage, journées pédagogiques, examens.
4. Vérifier les demandes de groupe déjà enregistrées avec 0 personne (ancienne option « Plus de 10 ») : le vrai nombre est peut-être dans le message, sinon rappeler le client.

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
