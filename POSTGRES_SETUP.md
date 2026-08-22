# Configuration PostgreSQL sur Railway

## ✅ Configuration actuelle

Votre application Flask est **déjà configurée** pour utiliser PostgreSQL sur Railway.

### Variables d'environnement disponibles

Lorsque PostgreSQL est déployé sur Railway, ces variables sont automatiquement disponibles pour votre service `web`:

```
DATABASE_URL          → URL de connexion complète PostgreSQL
PGHOST               → Hôte (ex: railway.internal)
PGPORT               → Port (ex: 5432)
PGUSER               → Nom d'utilisateur PostgreSQL
PGPASSWORD           → Mot de passe généré automatiquement
PGDATABASE           → Nom de la base de données
```

### Code déjà en place dans `main.py`

```python
# Votre application détecte automatiquement PostgreSQL
DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{basedir}/data/restaurant.db')

# Configuration automatique du driver psycopg2
if DATABASE_URL and DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg2://', 1)

# Configuration optimisée
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,      # Vérifier les connexions
    'pool_recycle': 300         # Recycler les connexions tous les 5 min
}
```

## 🚀 Prochaines étapes

### 1. Appliquer les changements sur Railway
- ✅ PostgreSQL est déployé
- ✅ Variables de connexion ajoutées au service `web`
- Cliquez sur "Apply" dans l'interface Railway

### 2. Les tables se créent automatiquement au démarrage
Votre `main.py` exécute `creer_tables()` au démarrage :
```python
with app.app_context():
    creer_tables()
```

### 3. Vérifier la connexion
Après le déploiement, consultez les logs pour confirmer :
```
✅ Tables créées avec succès.
```

## 🔧 Dépannage

### Test local avec PostgreSQL
Si vous voulez tester avec PostgreSQL localement :

```bash
# Installer PostgreSQL localement
# Créer une base de données
createdb restaurant

# Exporter la variable (Linux/Mac)
export DATABASE_URL="postgresql://user:password@localhost:5432/restaurant"

# Ou sur Windows (PowerShell)
$env:DATABASE_URL = "postgresql://user:password@localhost:5432/restaurant"

# Lancer l'initialisation
python init_postgres.py
```

### Vérifier l'état sur Railway
```bash
# Voir les logs
railway logs web     # Logs de votre app
railway logs Postgres # Logs de la base de données
```

## 📝 Notes importantes

1. **Persistance des données** ✅
   - PostgreSQL sur Railway persiste les données automatiquement
   - Les migrations de schéma se font via `db.create_all()`

2. **Pool de connexions** ✅
   - Configuré pour éviter les fuites de connexions
   - Recycle automatique toutes les 5 minutes

3. **SSL/TLS** ✅
   - PostgreSQL sur Railway utilise SSL par défaut
   - psycopg2 gère automatiquement la validation

4. **Admin credentials** ⚠️
   - Changez `ADMIN_PASSWORD` en production (actuellement: `password123`)
   - Utilisez une variable d'environnement sécurisée

## 📚 Ressources

- [Flask-SQLAlchemy Documentation](https://flask-sqlalchemy.palletsprojects.com/)
- [Railway PostgreSQL](https://docs.railway.app/)
- [psycopg2 Documentation](https://www.psycopg.org/)

