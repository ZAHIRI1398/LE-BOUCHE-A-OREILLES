import sqlite3
import os

# Chemin vers la base de données
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'reservations.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM menu ORDER BY categorie, nom')
    plats = cursor.fetchall()
    
    print("=== PLATS DANS LA BASE DE DONNÉES ===")
    for plat in plats:
        print(f"- {plat['nom']} (ID: {plat['id']}, Catégorie: {plat['categorie']})")
    
    print("\n=== IMAGES DISPONIBLES ===")
    images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'images')
    for img in os.listdir(images_dir):
        if img.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
            print(f"- {img}")
    
except Exception as e:
    print(f"Erreur: {e}")
finally:
    if 'conn' in locals():
        conn.close()
