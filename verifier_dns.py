#!/usr/bin/env python3
"""
Script pour vérifier la configuration DNS du sous-domaine
"""

import subprocess
import sys

def verifier_dns():
    """Vérifie si le sous-domaine pointe correctement vers Render"""
    domaine = "app.leboucheaoreille.com"
    cible_attendue = "le-bouche-a-oreilles-1.onrender.com"
    
    print(f"🔍 Vérification DNS pour {domaine}")
    print("=" * 50)
    
    try:
        # Sous Windows
        result = subprocess.run(['nslookup', domaine], 
                              capture_output=True, text=True, timeout=10)
        
        if cible_attendue in result.stdout:
            print(f"✅ {domaine} pointe correctement vers {cible_attendue}")
            print(f"🌐 Votre site sera accessible à : https://{domaine}")
            return True
        else:
            print(f"❌ {domaine} ne pointe pas vers {cible_attendue}")
            print("📋 Voici ce que j'ai trouvé :")
            print(result.stdout)
            return False
            
    except subprocess.TimeoutExpired:
        print("⏰ Timeout - La vérification DNS a pris trop de temps")
        return False
    except Exception as e:
        print(f"❌ Erreur lors de la vérification DNS : {e}")
        return False

if __name__ == "__main__":
    if verifier_dns():
        print("\n🎉 Configuration DNS réussie !")
        print("🚀 Votre sous-domaine est prêt à être utilisé")
    else:
        print("\n⏳ La configuration DNS n'est pas encore terminée")
        print("💡 Attendez encore quelques minutes et réessayez")
