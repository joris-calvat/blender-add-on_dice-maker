"""Rafraîchissement UI pendant les opérations longues."""
import bpy


def refresh_ui(status=None):
    """Force un redraw viewport/UI pour éviter « Blender ne répond pas ».

    Optionnellement met à jour le texte de statut de l'espace de travail.
    """
    try:
        if status is not None:
            ws = getattr(bpy.context, "workspace", None)
            if ws is not None:
                ws.status_text_set(str(status))
        # Laisse Blender traiter les events et redessiner une frame
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
    except Exception:
        # Pas de contexte fenêtre (script batch) : ignorer
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass


def clear_status():
    """Efface le texte de statut."""
    try:
        ws = getattr(bpy.context, "workspace", None)
        if ws is not None:
            ws.status_text_set(None)
    except Exception:
        pass


def progress_begin(total, status=None):
    try:
        bpy.context.window_manager.progress_begin(0, max(1, int(total)))
    except Exception:
        pass
    if status:
        refresh_ui(status)


def progress_update(value, status=None):
    try:
        bpy.context.window_manager.progress_update(int(value))
    except Exception:
        pass
    refresh_ui(status)


def progress_end():
    try:
        bpy.context.window_manager.progress_end()
    except Exception:
        pass
    clear_status()
