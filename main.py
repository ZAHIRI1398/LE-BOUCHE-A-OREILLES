import os
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import logging
from reservation_client import reservation_bp

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

# Créer les tables au démarrage
with app.app_context():
    # Créer le dossier data s'il n'existe pas
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    creer_tables()

@app.route('/')
def accueil():
    return render_template('accueil.html', today=datetime.date.today().isoformat())

@app.route('/afficher_reservations')
def afficher_toutes_reservations():
    conn = get_db_connection()
    try:
        # Récupérer toutes les réservations avec les colonnes nommées
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM reservations 
            ORDER BY date DESC, heure DESC
        ''')
        reservations = [dict(row) for row in cursor.fetchall()]
        
        # Récupérer les plats pour chaque réservation
        for reservation in reservations:
            cursor.execute('''
                SELECT m.nom, m.description, m.prix 
                FROM reservations_plats rp
                JOIN menu m ON rp.plat_id = m.id
                WHERE rp.reservation_id = ?
            ''', (reservation['id'],))
            plats = [dict(row) for row in cursor.fetchall()]
            reservation['plats'] = plats
            
    except sqlite3.Error as e:
        app.logger.error(f"Erreur lors de la récupération des réservations: {e}")
        flash("Une erreur est survenue lors de la récupération des réservations.", "error")
        return redirect(url_for('accueil'))
    finally:
        conn.close()
    
    return render_template('afficher_reservations.html', 
                         reservations=reservations,
                         email=None)

@app.route('/ajouter_menu')
def ajouter_menu():
    return render_template('ajouter-menu.html')

@app.route('/ajouter_plat', methods=['POST'])
def ajouter_plat():
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
            return redirect(url_for('afficher_menu'))
        except Exception as e:
            flash(f'Erreur lors de l\'ajout du plat: {str(e)}', 'error')
            return redirect(url_for('ajouter_menu'))
        finally:
            conn.close()
    return redirect(url_for('ajouter_menu'))

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
def afficher_menu():
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
            menu_par_categorie[categorie].append(plat)
            
        return render_template('menu.html', menu_par_categorie=menu_par_categorie)
    except Exception as e:
        flash(f'Erreur lors de la récupération du menu: {str(e)}', 'error')
        return redirect(url_for('accueil'))
    finally:
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
    return redirect(url_for('afficher_menu'))

if __name__ == '__main__':
    app.run(debug=True,host='0.0.0.0',port=5000)