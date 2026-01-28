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
###Où les images sont utilisées :
Page d'accueil (accueil.html) : affiche plat1.jpg, plat2.jpg, dessert.jpg et restaurant-interior.jpg
Page du menu (menu.html) : utilise les images plat0.jpg à plat3.jpg en boucle
Page d'administration du menu (admin_menu.html) : utilise également les images plat0.jpg à plat3.jpg
1-git add static/images/*
2-git status
3-rm -Force .git/index.lock
git push origin main