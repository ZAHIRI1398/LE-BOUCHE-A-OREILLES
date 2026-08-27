import sqlite3

def afficher_tables():
    try:
        with sqlite3.connect('C:/Users/adamy/OneDrive/Bureau/shared/reservations.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            print("Tables présentes dans la base de données :")
            for table in tables:
                print(table[0])
                
            # Optionnel : afficher le contenu de chaque table
            for table in [t[0] for t in tables]:
                print(f"\nContenu de la table {table} :")
                cursor.execute(f"SELECT * FROM {table};")
                rows = cursor.fetchall()
                for row in rows:
                    print(row)
    except sqlite3.Error as e:
        print(f"Erreur lors de l'accès à la base de données : {e}")

if __name__ == '__main__':
    afficher_tables()
