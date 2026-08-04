"""Module pour gérer l'import et le traitement des fichiers SVG"""
import bpy
import os
import math
from mathutils import Vector, Euler

from . import dice_maker_bevel
from . import dice_maker_ui as ui


def _cleanup_existing_object(object_name):
    """Supprime l'objet existant avec le nom donné s'il existe"""
    if object_name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[object_name], do_unlink=True)


def _get_imported_objects_from_collection(context, collection_name, objects_before):
    """
    Récupère les objets importés depuis la collection créée par Blender.
    
    Args:
        context: Le contexte Blender
        collection_name: Le nom de la collection créée par l'import
        objects_before: Set des objets existants avant l'import
    
    Returns:
        Set des objets importés, ou None si aucun objet trouvé
    """
    main_collection = context.scene.collection
    
    if collection_name in bpy.data.collections:
        collection = bpy.data.collections[collection_name]
        new_objects = set(collection.objects)
        
        # Déplacer tous les objets vers la collection principale
        for obj in list(collection.objects):
            # Retirer de toutes les collections
            for col in list(obj.users_collection):
                col.objects.unlink(obj)
            # Ajouter à la collection principale
            main_collection.objects.link(obj)
        
        # Supprimer la collection vide
        bpy.data.collections.remove(collection)
        return new_objects
    else:
        # Fallback : utiliser l'objet actif
        if context.active_object and context.active_object not in objects_before:
            obj = context.active_object
            # S'assurer qu'il est dans la collection principale
            for col in list(obj.users_collection):
                if col != main_collection:
                    col.objects.unlink(obj)
            if main_collection not in obj.users_collection:
                main_collection.objects.link(obj)
            return {obj}
    return None


def _join_imported_objects_into_one(context, new_objects):
    """
    Fusionne plusieurs objets issus d'un meme import SVG (path, path.001, etc.)
    en un seul objet, avant conversion / mise a l'echelle.
    Sinon le code ne suivait que le premier objet : les autres restaient dans la scene.
    """
    objs = [o for o in new_objects if o and o.name in bpy.data.objects]
    if not objs:
        return None
    if len(objs) == 1:
        objs[0].select_set(False)
        return objs[0]

    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    bpy.ops.object.select_all(action='DESELECT')
    for obj in objs:
        obj.select_set(True)
    context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    merged = context.view_layer.objects.active
    merged.select_set(False)
    return merged


def _resize_object_to_cube_size(context, obj, cube_size=2.0):
    """
    Redimensionne un objet pour que sa dimension maximale (largeur ou hauteur) 
    corresponde à la taille du cube, puis applique l'échelle à la géométrie.
    
    Args:
        context: Le contexte Blender
        obj: L'objet à redimensionner
        cube_size: La taille du cube (par défaut 2.0)
    """
    # S'assurer que l'objet est actif pour calculer les dimensions
    context.view_layer.objects.active = obj
    obj.select_set(True)
    
    # Calculer les dimensions de l'objet (bounding box)
    # Pour les courbes SVG, on utilise bound_box
    bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    
    # Calculer les dimensions
    x_coords = [corner.x for corner in bbox_corners]
    y_coords = [corner.y for corner in bbox_corners]
    
    width = max(x_coords) - min(x_coords)
    height = max(y_coords) - min(y_coords)
    
    # Trouver la dimension maximale (largeur ou hauteur)
    max_dimension = max(width, height)
    
    if max_dimension > 0:
        # Calculer le facteur d'échelle
        scale_factor = cube_size / max_dimension
        
        # Appliquer l'échelle uniformément
        obj.scale = (scale_factor, scale_factor, scale_factor)
        
        # Appliquer l'échelle à la géométrie
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    
    obj.select_set(False)


def _add_solidify_modifier(obj, thickness):
    """
    Ajoute un modificateur SOLIDIFY à l'objet avec l'épaisseur spécifiée.
    
    Args:
        obj: L'objet auquel ajouter le modificateur
        thickness: L'épaisseur du modificateur
    """
    # Supprimer le modificateur SOLIDIFY existant s'il existe
    if "Solidify" in obj.modifiers:
        obj.modifiers.remove(obj.modifiers["Solidify"])
    
    # Ajouter le modificateur SOLIDIFY
    solidify_mod = obj.modifiers.new(name="Solidify", type='SOLIDIFY')
    solidify_mod.thickness = thickness


def _get_face_rotation(face_number):
    """
    Retourne la rotation en radians pour orienter l'objet sur la bonne face du cube.
    Les SVG sont importés dans le plan XY (horizontal), regardant vers +Z (haut).
    
    Args:
        face_number: Numéro de la face (1=front, 2=left, 3=right, 4=top, 5=bottom, 6=back)
    
    Returns:
        Tuple (rotation_x, rotation_y, rotation_z) en radians
    """
    rotations = {
        1: (math.pi/2, 0, 0),    # Front
        2: (math.pi/2, 0, -math.pi/2),     # Left
        3: (math.pi/2, 0, math.pi/2),    # Right
        4: (0, 0, 0),             # Top
        5: (math.pi, 0.0, 0.0),         # Bottom
        6: (-math.pi / 2, 0.0, 0.0),     # Back
    }
    return rotations.get(face_number, (0.0, 0.0, 0.0))


def _face_resolution_to_contour(resolution):
    """Mappe la résolution UI (1–30) vers un budget de points de contour."""
    return max(48, min(1024, int(resolution) * 32))


def _preprocess_imported_curve(context, obj, final_size, resolution):
    """Prépare la CURVE SVG (origine, taille, résolution) sans la convertir en mesh."""
    obj.select_set(True)
    context.view_layer.objects.active = obj

    bpy.ops.object.origin_set(type="ORIGIN_CENTER_OF_VOLUME", center="BOUNDS")
    obj.location = (0.0, 0.0, 0.0)

    if obj.data and hasattr(obj.data, "resolution_u"):
        obj.data.resolution_u = resolution
    if obj.data and hasattr(obj.data, "dimensions"):
        obj.data.dimensions = "2D"
    if obj.data and hasattr(obj.data, "fill_mode"):
        obj.data.fill_mode = "BOTH"
    if obj.data and hasattr(obj.data, "bevel_depth"):
        obj.data.bevel_depth = 0.0

    _resize_object_to_cube_size(context, obj, final_size)
    obj.select_set(False)


def _curve_to_beveled_cutter(
    context,
    curve_obj,
    *,
    name,
    base_height,
    angle,
    bevel_height,
    contour_resolution,
    flatten_top=True,
):
    """Construit le volume bevel à partir de la CURVE et remplace celle-ci."""
    curve_obj.select_set(True)
    context.view_layer.objects.active = curve_obj

    volume, info = dice_maker_bevel.build_beveled_volume(
        curve_obj,
        base_height=base_height,
        angle=angle,
        bevel_height=bevel_height,
        resolution=contour_resolution,
        flatten_top=flatten_top,
    )

    # Supprimer la courbe source (le cutter est le mesh bevel)
    curve_data = curve_obj.data
    bpy.data.objects.remove(curve_obj, do_unlink=True)
    if curve_data is not None and curve_data.users == 0:
        bpy.data.curves.remove(curve_data)

    # volume s'appelle encore "{curve}-beveled-volume"
    src_base = (
        volume.name[: -len(dice_maker_bevel._SUFFIX_VOLUME)]
        if volume.name.endswith(dice_maker_bevel._SUFFIX_VOLUME)
        else volume.name
    )
    cross_name = dice_maker_bevel.bevel_output_names(src_base)["crossings"]
    cross_obj = bpy.data.objects.get(cross_name)
    if cross_obj is not None:
        data = cross_obj.data
        bpy.data.objects.remove(cross_obj, do_unlink=True)
        if data is not None and data.users == 0 and isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)

    volume.name = name
    volume.select_set(False)
    print(
        f"[dice_maker svg] cutter={volume.name} mode={info.get('mode')} "
        f"verts={info.get('nverts')} crossings={info.get('crossings_before', 0)}→{info.get('crossings', 0)}"
    )
    return volume


def _postprocess_imported_objects(context, new_objects, object_name, cube_size, face_number):
    """Place le volume bevel sur la face : large à la surface, biseau vers l'intérieur.

    Comme avant : la translation vers la face est cuite dans le mesh local (Z+),
    puis seule la rotation d'objet oriente sur la bonne face. Sinon, avec
    location=(0,0,face) + rotation, tout reste collé sur +Z.
    """
    for obj in new_objects:
        obj.select_set(True)
        context.view_layer.objects.active = obj

        # Volume bevel : z=0 large, z=+H étroit → inverser (large en surface, tip vers -Z)
        for v in obj.data.vertices:
            v.co.z = -v.co.z
        # Aligner la face large (max z) sur z=0 local
        max_z = max(v.co.z for v in obj.data.vertices)
        for v in obj.data.vertices:
            v.co.z -= max_z

        # Décaler vers la face +Z en espace local (avant rotation)
        translation_z = (cube_size / 2.0) + (cube_size / 500.0)
        for v in obj.data.vertices:
            v.co.z += translation_z
        obj.data.update()

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")

        obj.location = (0.0, 0.0, 0.0)
        obj.rotation_euler = Euler(_get_face_rotation(face_number), "XYZ")
        obj.select_set(False)

    for idx, obj in enumerate(new_objects):
        if len(new_objects) == 1:
            obj.name = object_name
        else:
            obj.name = f"{object_name}_{idx + 1}"


def import_svg(
    context,
    filepath,
    face_number,
    size_factor,
    cube_size,
    resolution,
    *,
    base_height,
    angle,
    bevel_height,
    flatten_top=True,
):
    """
    Importe un SVG, construit le volume bevel, retourne le cutter MESH.

    Returns:
        L'objet mesh bevel si succès, None sinon
    """
    if not filepath:
        return None

    abs_filepath = bpy.path.abspath(filepath)
    if not os.path.exists(abs_filepath):
        return None

    object_name = f"dice_face_{face_number}"
    filename_with_ext = os.path.basename(abs_filepath)
    _cleanup_existing_object(object_name)
    # Nettoyer un éventuel volume bevel orphelin du même nom logique
    _cleanup_existing_object(f"{object_name}-beveled-volume")

    try:
        objects_before_import = set(bpy.data.objects)
        bpy.ops.import_curve.svg(filepath=abs_filepath)

        new_objects = _get_imported_objects_from_collection(
            context, filename_with_ext, objects_before_import
        )
        if not new_objects:
            return None

        final_size = cube_size * size_factor
        merged_obj = _join_imported_objects_into_one(context, new_objects)
        if not merged_obj:
            return None

        _preprocess_imported_curve(context, merged_obj, final_size, resolution)
        contour_res = _face_resolution_to_contour(resolution)
        volume = _curve_to_beveled_cutter(
            context,
            merged_obj,
            name=object_name,
            base_height=base_height,
            angle=angle,
            bevel_height=bevel_height,
            contour_resolution=contour_res,
            flatten_top=flatten_top,
        )
        return volume
    except Exception as e:
        raise Exception(f"Erreur lors de l'import de {abs_filepath}: {str(e)}")


def cleanup_print_copies():
    """
    Supprime les copies d'impression précédentes si elles existent.
    """
    # Chercher tous les objets avec le préfixe dice_maker_face_
    objects_to_remove = [obj for obj in bpy.data.objects if obj.name.startswith("dice_maker_face_")]
    for obj in objects_to_remove:
        bpy.data.objects.remove(obj, do_unlink=True)


def create_print_copies(context, imported_objects_info):
    """
    Crée des copies des objets SVG pour l'impression si demandé.
    
    Args:
        context: Le contexte Blender
        imported_objects_info: Liste des objets importés avec leurs informations
    
    Returns:
        Liste des copies créées
    """
    
    copies = []
    
    for obj_info in imported_objects_info:
        obj = obj_info['object']
        face_number = obj_info['face_number']
        
        # Dupliquer l'objet
        obj_copy = obj.copy()
        obj_copy.data = obj.data.copy()
        
        # Renommer la copie
        obj_copy.name = f"dice_maker_face_{face_number}"
        
        # Lier la copie à la scène
        context.scene.collection.objects.link(obj_copy)
        
        copies.append(obj_copy)
    
    return copies


def apply_height_percentage_to_print_copies(context, print_copies, height_percentage):
    """
    Applique un pourcentage de hauteur aux copies d'impression (sur l'axe Z uniquement).
    
    Args:
        context: Le contexte Blender
        print_copies: Liste des copies d'impression
        height_percentage: Pourcentage de hauteur (50 à 100)
    """
    if not print_copies:
        return
    
    # Convertir le pourcentage en facteur (80% = 0.8)
    height_factor = height_percentage / 100.0
    
    for copy_obj in print_copies:
        copy_obj.select_set(True)
        context.view_layer.objects.active = copy_obj
        
        # Appliquer le scale uniquement sur l'axe Z (hauteur)
        copy_obj.scale = (1.0, 1.0, height_factor)
        
        # Appliquer l'échelle à la géométrie
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        copy_obj.select_set(False)


def apply_size_factor_to_objects(context, dice_obj, print_copies, size_factor):
    """
    Applique un facteur de taille à tous les objets (dé et copies d'impression).
    
    Args:
        context: Le contexte Blender
        dice_obj: L'objet dé
        print_copies: Liste des copies d'impression
        size_factor: Facteur de taille à appliquer
    """
    # Appliquer au dé
    if dice_obj:
        dice_obj.select_set(True)
        context.view_layer.objects.active = dice_obj
        # Appliquer l'échelle
        dice_obj.scale = (size_factor, size_factor, size_factor)
        # Appliquer l'échelle à la géométrie
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        dice_obj.select_set(False)
    
    # Appliquer aux copies d'impression
    for copy_obj in print_copies:
        copy_obj.select_set(True)
        context.view_layer.objects.active = copy_obj
        # Appliquer l'échelle
        copy_obj.scale = (size_factor, size_factor, size_factor)
        # Appliquer l'échelle à la géométrie
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        copy_obj.select_set(False)


def _mesh_min_z_local(obj):
    """Z local minimal du mesh (après apply, rotation = 0)."""
    if obj.type != "MESH" or not obj.data.vertices:
        return 0.0
    return min(v.co.z for v in obj.data.vertices)


def _place_object_on_ground(obj):
    """Pose l'objet pour que le point le plus bas du mesh soit à z=0 monde."""
    obj.location.z = -_mesh_min_z_local(obj)


def orient_for_resin_print(context, dice_obj):
    """Pose le dé sur un coin, faces également inclinées, prêt pour la résine.

    Aligne la diagonale d'espace du cube sur -Z (sommet vers le plateau).
    Les 3 faces adjacentes ont alors le même angle avec le plateau
    (arccos(1/√3) ≈ 54.74°), contrairement à un simple 45°/45°.
    """
    if dice_obj is None:
        return

    dice_obj.select_set(True)
    context.view_layer.objects.active = dice_obj

    # Coin (-X,-Y,-Z) → bas ; le twist autour de Z est fixé par rotation_difference
    corner = Vector((-1.0, -1.0, -1.0))
    quat = corner.normalized().rotation_difference(Vector((0.0, 0.0, -1.0)))
    dice_obj.rotation_euler = quat.to_euler("XYZ")
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    _place_object_on_ground(dice_obj)
    dice_obj.select_set(False)


def organize_objects_on_x_axis(context, dice_obj, print_copies, spacing=0.1, place_on_ground=False):
    """
    Organise les objets sur l'axe X : le dé d'abord, puis les copies d'impression avec espacement.
    Optionnellement, place tous les objets à z=0 comme s'ils étaient sur le sol.
    
    Args:
        context: Le contexte Blender
        dice_obj: L'objet dé
        print_copies: Liste des copies d'impression
        spacing: Espacement supplémentaire entre les objets (par défaut 0.1)
        place_on_ground: Si True, place tous les objets à z=0 (par défaut False)
    """
    current_x = 0.0
    
    # Placer le dé à l'origine X
    if dice_obj:
        dice_obj.location.x = current_x
        # Calculer la taille du dé sur l'axe X (bounding box)
        context.view_layer.update()
        bbox_corners = [dice_obj.matrix_world @ Vector(corner) for corner in dice_obj.bound_box]
        x_coords = [corner.x for corner in bbox_corners]
        dice_width = max(x_coords) - min(x_coords)
        current_x = dice_width / 2.0 + spacing
        
        if place_on_ground:
            _place_object_on_ground(dice_obj)

    # Placer les copies d'impression après le dé
    for copy_obj in print_copies:
        context.view_layer.update()
        bbox_corners = [copy_obj.matrix_world @ Vector(corner) for corner in copy_obj.bound_box]
        x_coords = [corner.x for corner in bbox_corners]
        copy_width = max(x_coords) - min(x_coords)

        # Positionner la copie : centre + moitié de sa largeur + espacement
        copy_obj.location.x = current_x + copy_width / 2.0

        if place_on_ground:
            _place_object_on_ground(copy_obj)

        # Mettre à jour la position X pour l'objet suivant
        current_x += copy_width + spacing


def finalize_imported_objects(context, imported_objects, cube_size):
    """Finalise les cutters bevel : placement sur la face + rotation."""
    n = len(imported_objects)
    for i, obj_info in enumerate(imported_objects):
        ui.refresh_ui(
            f"Dice Maker : placement face {obj_info['face_number']} ({i + 1}/{n})…"
        )
        obj = obj_info["object"]
        face_number = obj_info["face_number"]
        object_name = obj_info["object_name"]
        _postprocess_imported_objects(
            context, {obj}, object_name, cube_size, face_number
        )


def import_all_svgs(
    context,
    svg_files,
    size_factors,
    cube_size,
    resolutions,
    flatten_tops=None,
    *,
    base_height,
    angle,
    bevel_height,
):
    """
    Importe une liste de fichiers SVG et construit les volumes bevel.

    Returns:
        Tuple (liste des dicts {object, face_number, object_name}, liste des erreurs)
    """
    imported_objects = []
    errors = []
    if flatten_tops is None:
        flatten_tops = [True] * len(svg_files)

    for i, svg_file in enumerate(svg_files):
        if svg_file:
            try:
                ui.refresh_ui(f"Dice Maker : face {i + 1}/6 — import + bevel…")
                size_factor = size_factors[i] if i < len(size_factors) else 0.5
                resolution = resolutions[i] if i < len(resolutions) else 5
                flatten_top = flatten_tops[i] if i < len(flatten_tops) else True
                obj = import_svg(
                    context,
                    svg_file,
                    i + 1,
                    size_factor,
                    cube_size,
                    resolution,
                    base_height=base_height,
                    angle=angle,
                    bevel_height=bevel_height,
                    flatten_top=flatten_top,
                )
                if obj:
                    object_name = f"dice_face_{i + 1}"
                    imported_objects.append(
                        {
                            "object": obj,
                            "face_number": i + 1,
                            "object_name": object_name,
                        }
                    )
                    ui.refresh_ui(
                        f"Dice Maker : face {i + 1}/6 — OK "
                        f"(flatten={flatten_top})"
                    )
                else:
                    errors.append(
                        f"Face {i + 1}: Le fichier n'a pas pu être importé "
                        f"(fichier introuvable ou invalide)"
                    )
            except Exception as e:
                errors.append(f"Face {i + 1}: {str(e)}")
                ui.refresh_ui(f"Dice Maker : face {i + 1}/6 — erreur")

    return imported_objects, errors

