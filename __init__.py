bl_info = {
    "name": "Dice Maker",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Dice Maker",
    "description": "Créer des dés personnalisés avec des fichiers SVG",
    "category": "Mesh",
}

import bpy
import importlib

# Importer les modules
from . import dice_maker_panel
from . import dice_maker_operator
from . import dice_maker_svg

def register():
    # Recharger les modules pour le développement (permet de recharger le code modifié sans redémarrer Blender)
    importlib.reload(dice_maker_svg)
    importlib.reload(dice_maker_panel)
    importlib.reload(dice_maker_operator)
    
    dice_maker_panel.register()
    dice_maker_operator.register()

def unregister():
    dice_maker_panel.unregister()
    dice_maker_operator.unregister()

if __name__ == "__main__":
    register()

