# 📸 Guide des Images du Restaurant

## 🏠 Page d'Accueil (accueil.html)
Images actuellement utilisées ✅ :
- `plat1.jpg` - Entrée du Chef
- `plat2.jpg` - Plat Signature  
- `dessert.jpg` - Dessert Maison
- `restaurant-interior.jpg` - Photo du restaurant

## 🍽️ Page du Menu (menu.html)
### Configuration actuelle (avec images existantes) :
- **Boissons** : utilise `plat0.jpg` 
- **Desserts** : utilise `dessert.jpg`
- **Plats principaux** : utilise `plat1.jpg`

### Pour utiliser des images spécifiques :
Ajoutez ces 3 images dans le dossier `static/images/` :
- `boisson.jpg` - Pour la catégorie Boissons
- `plat_principal.jpg` - Pour les plats principaux
- `dessert_menu.jpg` - Pour les desserts (différent de l'accueil)

## 📋 Étapes pour ajouter les nouvelles images :

1. **Préparez vos images** :
   - Format : JPG ou PNG
   - Taille recommandée : 800x600px minimum
   - Nommez-les exactement comme ci-dessus

2. **Placez-les dans le bon dossier** :
   ```
   static/
   └── images/
       ├── plat1.jpg ✅ (existe)
       ├── plat2.jpg ✅ (existe)
       ├── dessert.jpg ✅ (existe)
       ├── restaurant-interior.jpg ✅ (existe)
       ├── boisson.jpg 🆕 (à ajouter)
       ├── plat_principal.jpg 🆕 (à ajouter)
       └── dessert_menu.jpg 🆕 (à ajouter)
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
