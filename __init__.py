bl_info = {
    "name": "Dice Maker",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Dice Maker",
    "description": "Créer des dés personnalisés avec des fichiers SVG (banc de test bevel inclus)",
    "category": "Mesh",
}

import bpy
import importlib
import sys

from . import dice_maker_panel
from . import dice_maker_operator
from . import dice_maker_svg
from . import dice_maker_bevel
from . import dice_maker_ui

_SUBMODULES = (
    "dice_maker_ui",
    "dice_maker_svg",
    "dice_maker_bevel",
    "dice_maker_panel",
    "dice_maker_operator",
)


def _refresh_submodules():
    """Reload submodules safely (hyphenated package + Reload Scripts)."""
    global dice_maker_ui, dice_maker_svg, dice_maker_bevel, dice_maker_panel, dice_maker_operator
    pkg = __name__
    refreshed = []
    for name in _SUBMODULES:
        full = f"{pkg}.{name}"
        try:
            if full in sys.modules:
                mod = importlib.reload(sys.modules[full])
            else:
                mod = importlib.import_module(full)
        except Exception:
            # Dernier recours : réimport forcé
            sys.modules.pop(full, None)
            mod = importlib.import_module(full)
        refreshed.append(mod)

    (
        dice_maker_ui,
        dice_maker_svg,
        dice_maker_bevel,
        dice_maker_panel,
        dice_maker_operator,
    ) = refreshed


def register():
    _refresh_submodules()

    # Bevel props AVANT le panneau (sinon draw plante si props absentes)
    dice_maker_bevel.register()
    dice_maker_panel.register()
    dice_maker_operator.register()


def unregister():
    dice_maker_panel.unregister()
    dice_maker_operator.unregister()
    dice_maker_bevel.unregister()


if __name__ == "__main__":
    register()
