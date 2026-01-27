# Système de Réservation et Gestion de Menu

Ce projet contient deux applications :
1. **Application de Réservation** - Pour gérer les réservations des clients
2. **Application de Cuisine** - Pour gérer le menu du jour

## Installation

1. Clonez le repository
```bash
git clone [URL_DU_REPO]
```

2. Installez les dépendances
```bash
pip install -r requirements.txt
```

3. Lancez l'application
```bash
python run.py
```

## Fonctionnalités

### Application de Réservation
- Gestion des réservations clients
- Système de calendrier
- Confirmation par email

### Application de Cuisine
- Gestion du menu du jour
- Interface pour la cuisine
- Mise à jour en temps réel

## Technologies Utilisées
- Python
- Flask
- SQLite
- HTML/CSS/JavaScript
###git
git status
git add main.py templates/reservation_form.html
git commit -m "Correction du formulaire de réservation et de la page de confirmation"
rm -Force .git/index.lock
git push origin main