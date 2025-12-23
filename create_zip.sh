#!/bin/bash
# Script pour créer un fichier ZIP installable pour l'add-on Blender

# Nom du fichier ZIP de sortie
ZIP_NAME="dice-maker.zip"

# Supprimer l'ancien ZIP s'il existe
if [ -f "$ZIP_NAME" ]; then
    rm "$ZIP_NAME"
    echo "Ancien fichier ZIP supprimé"
fi

# Créer le ZIP avec les fichiers à la racine (structure requise par Blender)
# On ajoute les fichiers individuellement pour s'assurer qu'ils sont à la racine
zip "$ZIP_NAME" __init__.py dice_maker_panel.py dice_maker_operator.py dice_maker_svg.py LICENSE 2>/dev/null

# Vérifier que le ZIP a été créé
if [ -f "$ZIP_NAME" ]; then
    echo "✓ Fichier ZIP créé : $ZIP_NAME"
    echo "✓ Vous pouvez maintenant installer cet add-on dans Blender via Edit > Preferences > Add-ons > Install..."
else
    echo "✗ Erreur : Impossible de créer le fichier ZIP"
    echo "Assurez-vous d'être dans le bon répertoire et que tous les fichiers Python sont présents."
    exit 1
fi

