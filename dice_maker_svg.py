"""Module pour gérer l'import et le traitement des fichiers SVG"""
import bpy
import os
import math
from mathutils import Vector, Euler


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


def _preprocess_imported_objects(context, new_objects, final_size, cube_size, depth, resolution):
    """
    Prétraite les objets importés jusqu'à la conversion en mesh : origine, position, redimensionnement, résolution, modificateur.
    
    Args:
        context: Le contexte Blender
        new_objects: Set des objets à traiter
        final_size: Taille finale pour le redimensionnement (cube_size * size_factor)
        cube_size: Taille du cube
        depth: Coefficient de profondeur
        resolution: Résolution pour l'objet (1 à 10)
    """
    # Calculer l'épaisseur : (cube_size / 2) * depth
    thickness = (cube_size / 2.0) * depth
    
    for obj in new_objects:
        # Sélectionner l'objet
        obj.select_set(True)
        context.view_layer.objects.active = obj
        
        # Remettre l'origine de la géométrie au centre médian
        bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME', center='BOUNDS')
        
        # Déplacer l'objet au centre du monde
        obj.location = (0.0, 0.0, 0.0)
        
        # Appliquer la résolution (doit être fait avant la conversion en mesh)
        if obj.data and hasattr(obj.data, 'resolution_u'):
            obj.data.resolution_u = resolution
        
        # Redimensionner l'objet pour correspondre à la taille finale
        _resize_object_to_cube_size(context, obj, final_size)
        
        # Ajouter le modificateur SOLIDIFY
        _add_solidify_modifier(obj, thickness)
        
        # S'assurer que l'objet est sélectionné et actif pour la conversion
        obj.select_set(True)
        context.view_layer.objects.active = obj
        
        # Convertir l'objet en mesh (applique automatiquement les modificateurs)
        bpy.ops.object.convert(target='MESH')
        
        # Désélectionner l'objet
        obj.select_set(False)


def _postprocess_imported_objects(context, new_objects, object_name, cube_size, face_number):
    """
    Post-traite les objets importés après conversion en mesh : translation, rotation, nom.
    
    Args:
        context: Le contexte Blender
        new_objects: Set des objets à traiter
        object_name: Nom de base pour les objets
        cube_size: Taille du cube
        face_number: Numéro de la face pour déterminer la rotation (1-6)
    """
    for obj in new_objects:
        # Sélectionner l'objet
        obj.select_set(True)
        context.view_layer.objects.active = obj
        
        # Calculer la translation vers le haut : (cube_size / 2) + (cube_size / 1000)
        translation_z = (cube_size / 2.0) + (cube_size / 500.0)
        
        # Passer en mode édition
        bpy.ops.object.mode_set(mode='EDIT')
        
        # Sélectionner tout
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Faire la translation vers le haut (axe Z)
        bpy.ops.transform.translate(value=(0.0, 0.0, translation_z))
        
        # Sortir du mode édition
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # Appliquer la rotation pour orienter l'objet sur la bonne face du cube
        rotation = _get_face_rotation(face_number)
        obj.rotation_euler = Euler(rotation, 'XYZ')
        
        # Désélectionner l'objet
        obj.select_set(False)
    
    # Renommer les objets
    for idx, obj in enumerate(new_objects):
        if len(new_objects) == 1:
            obj.name = object_name
        else:
            obj.name = f"{object_name}_{idx + 1}"


def import_svg(context, filepath, face_number, size_factor, cube_size, depth, resolution):
    """
    Importe un fichier SVG dans Blender.
    Si un SVG avec le même nom est déjà chargé, il sera supprimé avant l'import.
    
    Args:
        context: Le contexte Blender
        filepath: Le chemin vers le fichier SVG à importer
        face_number: Le numéro de la face (1-6) pour le nom de l'objet
        size_factor: Facteur de taille (0.2 à 0.8)
        cube_size: Taille du cube (sera multipliée par size_factor)
        depth: Coefficient de profondeur pour le modificateur SOLIDIFY
        resolution: Résolution pour l'objet (1 à 10)
    
    Returns:
        L'objet importé si succès, None sinon
    """
    if not filepath:
        return None
    
    # Convertir le chemin relatif en chemin absolu (Blender peut stocker des chemins relatifs)
    abs_filepath = bpy.path.abspath(filepath)
    
    if not os.path.exists(abs_filepath):
        return None
    
    # Nom de l'objet à créer
    object_name = f"dice_face_{face_number}"
    
    # Obtenir le nom du fichier avec extension pour identifier la collection
    filename_with_ext = os.path.basename(abs_filepath)
    
    # Nettoyer l'objet existant s'il existe
    _cleanup_existing_object(object_name)
    
    # Importer le fichier SVG
    try:
        # Sauvegarder les objets existants avant l'import
        objects_before_import = set(bpy.data.objects)
        
        # Importer le SVG
        bpy.ops.import_curve.svg(filepath=abs_filepath)
        
        # Récupérer les objets importés depuis la collection
        new_objects = _get_imported_objects_from_collection(
            context, filename_with_ext, objects_before_import
        )
        
        if not new_objects:
            return None
        
        # Calculer la taille finale : cube_size * size_factor
        final_size = cube_size * size_factor
        
        # Prétraiter les objets importés (jusqu'à la conversion en mesh)
        _preprocess_imported_objects(context, new_objects, final_size, cube_size, depth, resolution)
        
        # Retourner le premier objet créé
        return next(iter(new_objects))
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
        bbox_corners = [dice_obj.matrix_world @ Vector(corner) for corner in dice_obj.bound_box]
        x_coords = [corner.x for corner in bbox_corners]
        dice_width = max(x_coords) - min(x_coords)
        current_x = dice_width / 2.0 + spacing
        
        # Placer le dé au sol si demandé
        if place_on_ground:
            # Calculer le point le plus bas du dé
            z_coords = [corner.z for corner in bbox_corners]
            min_z = min(z_coords)
            # Ajuster la position Z pour que le point le plus bas soit à z=0
            dice_obj.location.z = -min_z
    
    # Placer les copies d'impression après le dé
    for copy_obj in print_copies:
        # Calculer la taille de la copie sur l'axe X
        bbox_corners = [copy_obj.matrix_world @ Vector(corner) for corner in copy_obj.bound_box]
        x_coords = [corner.x for corner in bbox_corners]
        copy_width = max(x_coords) - min(x_coords)
        
        # Positionner la copie : centre + moitié de sa largeur + espacement
        copy_obj.location.x = current_x + copy_width / 2.0
        
        # Placer la copie au sol si demandé
        if place_on_ground:
            # Calculer le point le plus bas de la copie
            z_coords = [corner.z for corner in bbox_corners]
            min_z = min(z_coords)
            # Ajuster la position Z pour que le point le plus bas soit à z=0
            copy_obj.location.z = -min_z
        
        # Mettre à jour la position X pour l'objet suivant
        current_x += copy_width + spacing


def finalize_imported_objects(context, imported_objects, cube_size):
    """
    Finalise les objets importés : translation, rotation, nom.
    
    Args:
        context: Le contexte Blender
        imported_objects: Liste des objets importés avec leurs informations (obj, face_number, object_name)
        cube_size: Taille du cube
    """
    for obj_info in imported_objects:
        obj = obj_info['object']
        face_number = obj_info['face_number']
        object_name = obj_info['object_name']
        new_objects = {obj}
        
        # Post-traiter les objets importés (translation, rotation, nom)
        _postprocess_imported_objects(context, new_objects, object_name, cube_size, face_number)


def import_all_svgs(context, svg_files, size_factors, cube_size, depth, resolutions):
    """
    Importe une liste de fichiers SVG.
    
    Args:
        context: Le contexte Blender
        svg_files: Liste des chemins vers les fichiers SVG
        size_factors: Liste des facteurs de taille pour chaque face (0.2 à 0.8)
        cube_size: Taille du cube (sera multipliée par chaque size_factor)
        depth: Coefficient de profondeur pour le modificateur SOLIDIFY
        resolutions: Liste des résolutions pour chaque face (1 à 10)
    
    Returns:
        Tuple (liste des dictionnaires avec les objets et leurs infos, liste des erreurs)
        Chaque dictionnaire contient: {'object': obj, 'face_number': i+1, 'object_name': object_name}
    """
    imported_objects = []
    errors = []
    
    for i, svg_file in enumerate(svg_files):
        if svg_file:
            try:
                # Récupérer le facteur de taille correspondant (par défaut 0.5 si non défini)
                size_factor = size_factors[i] if i < len(size_factors) else 0.5
                # Récupérer la résolution correspondante (par défaut 5 si non défini)
                resolution = resolutions[i] if i < len(resolutions) else 5
                obj = import_svg(context, svg_file, i + 1, size_factor, cube_size, depth, resolution)
                if obj:
                    object_name = f"dice_face_{i + 1}"
                    imported_objects.append({
                        'object': obj,
                        'face_number': i + 1,
                        'object_name': object_name
                    })
                else:
                    errors.append(f"Face {i + 1}: Le fichier n'a pas pu être importé (fichier introuvable ou invalide)")
            except Exception as e:
                errors.append(f"Face {i + 1}: {str(e)}")
    
    return imported_objects, errors

