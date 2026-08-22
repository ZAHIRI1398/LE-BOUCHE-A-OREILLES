# Configuration Resend API

## 🚀 Étapes pour mettre en place Resend

### 1️⃣ Créer un compte Resend

1. Allez sur **[resend.com](https://resend.com)**
2. Cliquez sur **"Sign Up"** (s'inscrire)
3. Entrez votre email et créez un mot de passe
4. Vérifiez votre email (lien de confirmation)

### 2️⃣ Générer une clé API

1. Connectez-vous à [resend.com/api-keys](https://resend.com/api-keys)
2. Cliquez sur **"Create API Key"**
3. Donnez-lui un nom (ex: `Restaurant Le Bouche à Oreilles`)
4. Sélectionnez **"Default Server"** (ou la région appropriée)
5. Cliquez **"Create API Key"**
6. **Copiez la clé** (elle commence par `re_...`)

⚠️ **IMPORTANT** : Vous ne pourrez voir cette clé qu'une fois ! Sauvegardez-la immédiatement.

### 3️⃣ Ajouter la clé API à Railway

#### Méthode 1 : Via le Dashboard Railway (recommandé)

1. Allez sur [railway.com](https://railway.com)
2. Ouvrez votre projet **ingenious-appreciation**
3. Sélectionnez l'environnement **production**
4. Cliquez sur le service **web**
5. Allez dans l'onglet **Variables**
6. Cliquez sur **"Add Variable"**
7. Remplissez :
   - **Name** : `RESEND_API_KEY`
   - **Value** : collez votre clé API (ex: `re_VxpPtEic...`)
8. Cliquez sur **"Save"** ✅

#### Méthode 2 : Via Railway CLI

```bash
# Si vous avez Railway CLI installé
railway env RESEND_API_KEY=re_VxpPtEic...
railway up
```

### 4️⃣ Configuration du domaine email

#### Option A : Domaine Railway (gratuit, pour tests)
- Résend crée un domaine de test automatiquement
- Les emails sont envoyés depuis `onboarding@resend.dev` (par défaut)
- **Limitation** : max 100 emails/jour en développement

#### Option B : Domaine personnalisé (recommandé pour production)

1. Allez dans **[resend.com/domains](https://resend.com/domains)**
2. Cliquez sur **"Add Domain"**
3. Entrez votre domaine (ex: `mail.leboucheaoreilles.be`)
4. Suivez les étapes pour configurer les DNS records
5. Une fois vérifié, mettez à jour la variable `EMAIL_FROM` :

```
EMAIL_FROM=contact@leboucheaoreilles.be
```

### 5️⃣ Redéployer votre app

```bash
railway deploy web
```

Ou via le Dashboard :
- Allez dans **Deployments**
- Cliquez sur **"Deploy"**

## ✅ Vérifier que ça fonctionne

Après le déploiement :

1. Allez sur votre site de réservation
2. Créez une réservation de test
3. Vérifiez les logs Railway :
   ```
   ✅ Email envoyé avec succès! ID: ...
   ```
4. Vérifiez que l'email a été reçu

### Logs de succès

Vous devriez voir dans les logs Railway :
```
🚀 Début de l'envoi d'email à client@example.com pour la réservation RES-XXXXX
📅 Date formatée: 28/08/2026
📧 Envoi via Resend API...
✅ Email envoyé avec succès! ID: 12345-abcde-67890
```

### Logs d'erreur

Si vous voyez :
```
⚠️  RESEND_API_KEY non configurée - email non envoyé
```

Cela signifie que :
- La variable `RESEND_API_KEY` n'est pas définie sur Railway
- Répétez l'étape 3 ci-dessus

## 📝 Variables d'environnement

| Variable | Description | Exemple |
|----------|-------------|---------|
| `RESEND_API_KEY` | Clé API Resend | `re_VxpPtEic...` |
| `EMAIL_FROM` | Adresse email d'envoi | `contact@leboucheaoreilles.be` |
| `TEST_EMAIL_REDIRECT` | (Optionnel) Rediriger les emails vers une adresse de test | `admin@test.com` |

## 🔒 Sécurité

✅ **Bonnes pratiques** :
- ✅ Clé API stockée en variable d'environnement (pas en dur dans le code)
- ✅ La clé API est masquée dans le Dashboard Railway
- ✅ Les logs ne contiennent pas la clé complète

## 🆘 Dépannage

### "API key is invalid"
```
❌ Erreur lors de l'envoi de l'email: API key is invalid
```

**Solutions** :
1. Vérifiez que la clé API a été copiée entièrement
2. Assurez-vous qu'elle commence par `re_`
3. Vérifiez qu'elle n'a pas d'espaces avant/après
4. Régénérez une nouvelle clé sur resend.com

### "Invalid from address"
```
❌ Erreur: Invalid from address
```

**Solution** :
- Le domaine email doit être vérifié sur Resend
- Utilisez `onboarding@resend.dev` pour les tests

### Emails non reçus
**Vérifications** :
1. Vérifiez le dossier Spam/Courrier indésirable
2. Cherchez les emails du domaine Resend dans les logs
3. Testez avec `TEST_EMAIL_REDIRECT=your@email.com` pour rediriger les emails

## 📚 Ressources

- [Resend Documentation](https://resend.com/docs)
- [Resend API Reference](https://resend.com/docs/api-reference/emails/send)
- [Railway Documentation](https://docs.railway.app)

## 🎯 Prochaines étapes

1. ✅ Clé API Resend configurée
2. ✅ Variable `RESEND_API_KEY` ajoutée sur Railway
3. ✅ Service `web` redéployé
4. 📧 Testez une réservation
5. 🎉 Les emails de confirmation sont maintenant envoyés automatiquement !

