# 📸 Guide des Images du Restaurant

## 🏠 Page d'Accueil (accueil.html)
Images actuellement utilisées ✅ :
- `plat1.jpg` - Entrée du Chef
- `plat2.jpg` - Plat Signature  
- `dessert.jpg` - Dessert Maison
- `restaurant-interior.jpg` - Photo du restaurant

## 🍽️ Page du menu (menu.html) :
### Configuration complète avec images dédiées :
- **Entrées** : utilise `entree.jpg` 🆕
- **Boissons** : utilise `boisson.jpg` 
- **Desserts** : utilise `dessert_menu.jpg`
- **Plats principaux** : utilise `plat_principal.jpg`
- **Autres** : utilise `default.jpg` (image par défaut)

### Détection intelligente par mots-clés :
- Contient "entree" ou "entrée" → `entree.jpg`
- Contient "boisson" → `boisson.jpg`
- Contient "dessert" → `dessert_menu.jpg`
- Contient "plat" → `plat_principal.jpg`
- Autres → `default.jpg`

## 📋 Étapes pour ajouter les nouvelles images :

1. **Préparez vos images** :
   - Format : JPG ou PNG
   - Taille recommandée : 800x600px minimum
   - Nommez-les exactement comme ci-dessus

2. **Placez-les dans le bon dossier** :
   ```
   static/
   └── images/
       ├── plat1.jpg ✅ (existe - accueil)
       ├── plat2.jpg ✅ (existe - accueil)
       ├── dessert.jpg ✅ (existe - accueil)
       ├── restaurant-interior.jpg ✅ (existe - accueil)
       ├── entree.jpg ✅ (existe - menu entrées)
       ├── boisson.jpg ✅ (existe - menu boissons)
       ├── plat_principal.jpg ✅ (existe - menu plats)
       ├── dessert_menu.jpg ✅ (existe - menu desserts)
       └── default.jpg ✅ (existe - image par défaut)
   ```

3. **Vérifiez avec le script** :
   ```bash
   python organiser_images.py
   ```

4. **Le code s'adaptera automatiquement** :
   - Si les nouvelles images existent → elles seront utilisées
   - Sinon → les images existantes seront utilisées comme secours

## 🎨 Conseils pour les images :

### Boissons :
- Photo de verres, bouteilles ou cocktails
- Fond clair pour meilleure visibilité
- Format horizontal

### Plats principaux :
- Photo appétissante d'un plat principal
- Bon éclairage
- Présentation soignée

### Desserts menu :
- Différent du dessert de l'accueil
- Créations sucrées originales
- Couleurs vives

## 🔄 Comment ça fonctionne dans le code :

```html
<!-- Dans menu.html -->
{% if categorie == "Boissons" %}
    <img src="{{ url_for('static', filename='images/boisson.jpg') }}">
{% elif categorie == "Desserts" %}
    <img src="{{ url_for('static', filename='images/dessert_menu.jpg') }}">
{% else %}
    <img src="{{ url_for('static', filename='images/plat_principal.jpg') }}">
{% endif %}
```

Le template utilisera automatiquement les nouvelles images quand vous les ajouterez !
