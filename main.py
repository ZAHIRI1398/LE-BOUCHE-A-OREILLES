import os
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import logging
from reservation_client import reservation_bp
from functools import wraps

app = Flask(__name__)
app.secret_key = 'votre_cle_secrète_plus_secrete_encore_123456'
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'reservations.db')

# Enregistrer le Blueprint de réservation
app.register_blueprint(reservation_bp, url_prefix='/reservation')

# Configuration de logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def creer_tables():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Créer les tables si elles n'existent pas
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS menu (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nom TEXT NOT NULL,
                    description TEXT,
                    prix REAL NOT NULL,
                    categorie TEXT
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reservations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reference TEXT UNIQUE,
                    nom TEXT NOT NULL,
                    email TEXT NOT NULL,
                    telephone TEXT,
                    date TEXT NOT NULL,
                    heure TEXT NOT NULL,
                    personnes INTEGER NOT NULL,
                    message TEXT,
                    statut TEXT DEFAULT 'en_attente',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reservations_plats (
                    reservation_id INTEGER NOT NULL,
                    plat_id INTEGER NOT NULL,
                    FOREIGN KEY (reservation_id) REFERENCES reservations(id),
                    FOREIGN KEY (plat_id) REFERENCES menu(id),
                    PRIMARY KEY (reservation_id, plat_id)
                )
            ''')

            conn.commit()
            app.logger.info("Tables créées avec succès.")
    except sqlite3.Error as e:
        app.logger.error(f"Erreur lors de la création des tables: {e}")
 # Configuration de l'admin
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"  # À changer en production

# Protection des routes admin
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# Route de connexion admin
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('afficher_toutes_reservations'))
        else:
            flash('Identifiants incorrects', 'danger')
    return render_template('admin_login.html')

# Route de déconnexion admin
@app.route('/admin/logout')
@login_required
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Vous avez été déconnecté avec succès.', 'success')
    return redirect(url_for('accueil'))    

# Exemple de route protégée
@app.route('/admin/reservations')
@login_required
def afficher_toutes_reservations():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT r.*, GROUP_CONCAT(m.nom, ', ') as plats
            FROM reservations r
            LEFT JOIN reservations_plats rp ON r.id = rp.reservation_id
            LEFT JOIN menu m ON rp.plat_id = m.id
            GROUP BY r.id
            ORDER BY r.date DESC, r.heure DESC
        ''')
        reservations = cursor.fetchall()
        
        # Convert to list of dicts for template
        reservations_list = []
        for row in reservations:
            res = dict(row)
            # Convert Row to dict and handle any necessary type conversions
            res['plats'] = res.get('plats', '').split(', ') if res.get('plats') else []
            reservations_list.append(res)
            
        return render_template('admin_reservations.html', 
                             reservations=reservations_list,
                             email=None)
    except sqlite3.Error as e:
        app.logger.error(f"Erreur lors de la récupération des réservations: {e}")
        flash("Une erreur est survenue lors de la récupération des réservations.", "error")
        return redirect(url_for('accueil'))
    finally:
        conn.close()

# Créer les tables au démarrage
with app.app_context():
    # Créer le dossier data s'il n'existe pas
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    creer_tables()

@app.route('/')
def accueil():
    return redirect(url_for('page_accueil'))

@app.route('/accueil')
def page_accueil():
    return render_template('accueil.html', today=datetime.date.today().isoformat())

@app.route('/ajouter_menu')
def ajouter_menu():
    return render_template('ajouter-menu.html')

@app.route('/admin/ajouter_plat')
@login_required
def ajouter_plat():
    return render_template('ajouter-menu.html')

@app.route('/admin/ajouter_plat_action', methods=['POST'])
@login_required
def admin_ajouter_plat_action():
    if request.method == 'POST':
        nom_plat = request.form.get('nom_plat')
        description = request.form.get('description')
        prix = request.form.get('prix')
        categorie = request.form.get('categorie', 'plat_principal')  # Valeur par défaut
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO menu (nom, description, prix, categorie) VALUES (?, ?, ?, ?)',
                (nom_plat, description, prix, categorie)
            )
            conn.commit()
            flash('Plat ajouté avec succès!', 'success')
            return redirect(url_for('menu'))
        except Exception as e:
            flash(f'Erreur lors de l\'ajout du plat: {str(e)}', 'error')
            return redirect(url_for('ajouter_plat'))
        finally:
            conn.close()
    return redirect(url_for('ajouter_plat'))

@app.route('/changer_statut/<int:id>', methods=['POST'])
def changer_statut(id):
    if 'nouveau_statut' not in request.form:
        flash('Statut non spécifié', 'error')
        return redirect(url_for('afficher_toutes_reservations'))
    
    nouveau_statut = request.form['nouveau_statut']
    if nouveau_statut not in ['en_attente', 'confirmee', 'annulee']:
        flash('Statut invalide', 'error')
        return redirect(url_for('afficher_toutes_reservations'))
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE reservations SET statut = ? WHERE id = ?',
            (nouveau_statut, id)
        )
        conn.commit()
        flash(f'Le statut de la réservation a été mis à jour avec succès.', 'success')
    except sqlite3.Error as e:
        app.logger.error(f"Erreur lors de la mise à jour du statut: {e}")
        flash('Une erreur est survenue lors de la mise à jour du statut.', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('afficher_toutes_reservations'))

@app.route('/menu')
@app.route('/carte')
def menu():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM menu ORDER BY categorie, nom')
        plats = cursor.fetchall()
        
        # Grouper les plats par catégorie
        menu_par_categorie = {}
        for plat in plats:
            categorie = plat['categorie'] or 'Autres'
            if categorie not in menu_par_categorie:
                menu_par_categorie[categorie] = []
            menu_par_categorie[categorie].append(dict(plat))
            
        # Si l'utilisateur est admin, on affiche la vue admin
        if session.get('admin_logged_in'):
            return render_template('admin_menu.html', 
                                menu_par_categorie=menu_par_categorie)
        # Sinon, on affiche la vue client
        return render_template('menu.html', 
                            menu_par_categorie=menu_par_categorie)
    except Exception as e:
        app.logger.error(f"Erreur dans la route menu: {str(e)}")
        flash('Une erreur est survenue lors du chargement du menu.', 'error')
        return redirect(url_for('accueil'))
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/admin/menu')
@login_required
def admin_menu():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM menu ORDER BY categorie, nom')
        plats = cursor.fetchall()
        
        # Grouper les plats par catégorie
        menu_par_categorie = {}
        for plat in plats:
            categorie = plat['categorie'] or 'Autres'
            if categorie not in menu_par_categorie:
                menu_par_categorie[categorie] = []
            menu_par_categorie[categorie].append(dict(plat))
            
        return render_template('admin_menu.html', 
                            menu_par_categorie=menu_par_categorie)
    except Exception as e:
        app.logger.error(f"Erreur dans la route menu admin: {str(e)}")
        flash('Une erreur est survenue lors du chargement du menu.', 'error')
        return redirect(url_for('accueil'))
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/supprimer_plat/<int:plat_id>', methods=['POST'])
def supprimer_plat(plat_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM menu WHERE id = ?', (plat_id,))
        conn.commit()
        flash('Plat supprimé avec succès!', 'success')
    except Exception as e:
        flash(f'Erreur lors de la suppression du plat: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('menu'))

@app.route('/admin/reservation/supprimer/<int:id>', methods=['POST'])
@login_required
def supprimer_reservation(id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Supprimer d'abord les entrées liées dans la table de liaison
            cursor.execute('DELETE FROM reservations_plats WHERE reservation_id = ?', (id,))
            # Puis supprimer la réservation
            cursor.execute('DELETE FROM reservations WHERE id = ?', (id,))
            conn.commit()
            flash('La réservation a été supprimée avec succès.', 'success')
    except Exception as e:
        flash(f'Une erreur est survenue lors de la suppression de la réservation : {str(e)}', 'error')
    
    return redirect(url_for('afficher_toutes_reservations'))

import random
import string

def generate_reference():
    """Generate a unique reference for reservations"""
    chars = string.ascii_uppercase + string.digits
    return 'RES-' + ''.join(random.choices(chars, k=8))

@app.route('/reserver', methods=['GET', 'POST'])
def reserver():
    if request.method == 'POST':
        try:
            # Get form data
            nom = request.form.get('nom')
            email = request.form.get('email')
            telephone = request.form.get('telephone')
            personnes = int(request.form.get('personnes', 1))
            date = request.form.get('date')
            heure = request.form.get('heure')
            message = request.form.get('message', '')
            
            # Generate a unique reference
            reference = generate_reference()
            
            # Save to database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO reservations 
                (reference, nom, email, telephone, date, heure, personnes, message, statut)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'en_attente')
                ''',
                (reference, nom, email, telephone, date, heure, personnes, message)
            )
            conn.commit()
            conn.close()
            
            flash('Votre réservation a été enregistrée avec succès!', 'success')
            return redirect(url_for('confirmation', reference=reference))
            
        except Exception as e:
            app.logger.error(f"Erreur lors de l'enregistrement de la réservation: {str(e)}")
            flash('Une erreur est survenue lors de l\'enregistrement de votre réservation.', 'error')
            return redirect(url_for('reserver'))
    
    # For GET request, show the reservation form
    return render_template('reservation_form.html', today=datetime.date.today().isoformat())

@app.route('/admin/reservation/modifier/<int:id>', methods=['GET', 'POST'])
@login_required
def modifier_reservation(id):
    conn = get_db_connection()
    try:
        if request.method == 'POST':
            # Récupérer les données du formulaire
            nom = request.form.get('nom')
            email = request.form.get('email')
            telephone = request.form.get('telephone')
            date = request.form.get('date')
            heure = request.form.get('heure')
            personnes = request.form.get('personnes')
            message = request.form.get('message', '')
            statut = request.form.get('statut')
            
            # Mettre à jour la réservation dans la base de données
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE reservations 
                SET nom = ?, email = ?, telephone = ?, date = ?, 
                    heure = ?, personnes = ?, message = ?, statut =?
                WHERE id =?
                ''',
                (nom, email, telephone, date, heure, personnes, message, statut, id)
            )
            conn.commit()
            
            flash('La réservation a été mise à jour avec succès.', 'success')
            return redirect(url_for('afficher_toutes_reservations'))
        
        # Pour les requêtes GET, afficher le formulaire de modification
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE id = ?', (id,))
        reservation = cursor.fetchone()
        
        if reservation is None:
            flash('Réservation non trouvée.', 'error')
            return redirect(url_for('afficher_toutes_reservations'))
            
        return render_template('modifier_reservation.html', reservation=dict(reservation))
        
    except Exception as e:
        app.logger.error(f"Erreur lors de la modification de la réservation: {str(e)}")
        flash('Une erreur est survenue lors de la modification de la réservation.', 'error')
        return redirect(url_for('afficher_toutes_reservations'))
    finally:
        conn.close()

@app.route('/confirmation/<reference>')
def confirmation(reference):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE reference = ?', (reference,))
        reservation = cursor.fetchone()
        
        if reservation is None:
            flash('Réservation non trouvée.', 'error')
            return redirect(url_for('accueil'))
            
        # Convert Row to dict for easier template access
        reservation = dict(reservation)
        
        # Format the date for display
        if 'date' in reservation and reservation['date']:
            try:
                date_obj = datetime.datetime.strptime(reservation['date'], '%Y-%m-%d')
                reservation['date'] = date_obj.strftime('%d/%m/%Y')
            except (ValueError, TypeError):
                pass
                
        return render_template('confirmation.html', reservation=reservation)
        
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération de la réservation: {str(e)}")
        flash('Une erreur est survenue lors de la récupération de votre réservation.', 'error')
        return redirect(url_for('accueil'))
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    app.run(debug=True,host='0.0.0.0',port=5000)