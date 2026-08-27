import sqlite3

# Vérifier que sqlite3 est bien disponible et essayer de se connecter à une base de données
try:
    # Connexion à une base de données SQLite (un fichier en local)
    conn = sqlite3.connect('C:/Users/adamy/OneDrive/Bureau/shared/reservations.db')
 # Base de données en mémoire pour tester
    cursor = conn.cursor()

    # Exécuter une simple commande SQL
    cursor.execute('SELECT sqlite_version()')
    sqlite_version = cursor.fetchone()[0]

    print(f"sqlite3 est disponible et chargé avec succès. Version SQLite : {sqlite_version}")

    # Fermer la connexion
    conn.close()

except sqlite3.Error as e:
    print(f"Erreur avec sqlite3 : {e}")
