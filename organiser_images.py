#!/usr/bin/env python3
"""
Script pour organiser et vérifier les images du restaurant
"""

import os
from pathlib import Path

def verifier_images():
    """Vérifie quelles images sont disponibles"""
    images_dir = Path("static/images")
    
    print("🖼️  Vérification des images disponibles...")
    print("=" * 50)
    
    if not images_dir.exists():
        print("❌ Le dossier static/images n'existe pas")
        return
    
    images = list(images_dir.glob("*.jpg")) + list(images_dir.glob("*.png")) + list(images_dir.glob("*.jpeg"))
    
    if not images:
        print("❌ Aucune image trouvée dans static/images")
        return
    
    print(f"✅ {len(images)} images trouvées :")
    for img in sorted(images):
        print(f"   📸 {img.name}")
    
    print("\n" + "=" * 50)
    print("📋 Images requises pour chaque page :")
    print("\n🏠 Page d'accueil (accueil.html) :")
    print("   ✅ plat1.jpg")
    print("   ✅ plat2.jpg") 
    print("   ✅ dessert.jpg")
    print("   ✅ restaurant-interior.jpg")
    
    print("\n🍽️  Page du menu (menu.html) :")
    print("   ✅ boisson.jpg")
    print("   ✅ plat_principal.jpg")
    print("   ✅ dessert_menu.jpg")
    
    print("\n" + "=" * 50)
    print("🔍 Vérification des images manquantes...")
    
    # Images requises
    requises_accueil = ["plat1.jpg", "plat2.jpg", "dessert.jpg", "restaurant-interior.jpg"]
    requises_menu = ["boisson.jpg", "plat_principal.jpg", "dessert_menu.jpg"]
    toutes_requises = requises_accueil + requises_menu
    
    images_disponibles = [img.name for img in images]
    manquantes = []
    
    for req in toutes_requises:
        if req not in images_disponibles:
            manquantes.append(req)
    
    if manquantes:
        print(f"❌ Images manquantes ({len(manquantes)}) :")
        for manq in manquantes:
            print(f"   📷 {manq}")
    else:
        print("✅ Toutes les images requises sont disponibles !")
    
    print("\n💡 Conseils :")
    print("   - Utilisez des images de bonne qualité (800x600px minimum)")
    print("   - Nommez les images exactement comme indiqué ci-dessus")
    print("   - Placez-les dans le dossier static/images/")

if __name__ == "__main__":
    verifier_images()
