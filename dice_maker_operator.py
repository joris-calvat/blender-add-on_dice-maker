import bpy
from bpy.types import Operator
from . import dice_maker_svg


class DICE_MAKER_OT_create_dice(Operator):
    """Opérateur pour créer le dé"""
    bl_idname = "dice_maker.create_dice"
    bl_label = "Créer le dé"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # S'assurer qu'on n'est pas en mode édition
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        
        # Nom de l'objet à créer
        dice_name = "dice_maker_result"
        
        # Récupérer les propriétés
        props = context.scene.dice_maker_props
        
        # Liste des fichiers SVG
        svg_files = [
            props.svg_file_1,
            props.svg_file_2,
            props.svg_file_3,
            props.svg_file_4,
            props.svg_file_5,
            props.svg_file_6,
        ]
        
        # Liste des facteurs de taille
        size_factors = [
            props.size_factor_1,
            props.size_factor_2,
            props.size_factor_3,
            props.size_factor_4,
            props.size_factor_5,
            props.size_factor_6,
        ]
        
        # Liste des résolutions
        resolutions = [
            props.resolution_1,
            props.resolution_2,
            props.resolution_3,
            props.resolution_4,
            props.resolution_5,
            props.resolution_6,
        ]
        
        # Taille du cube (sera utilisée plus tard)
        cube_size = 2.0
        
        # Récupérer la profondeur
        depth = props.depth
        extrusion_scale = props.extrusion_scale
        
        # Importer tous les fichiers SVG
        imported_objects_info, errors = dice_maker_svg.import_all_svgs(
            context, svg_files, size_factors, cube_size, depth, resolutions, extrusion_scale
        )
        
        # Afficher les erreurs s'il y en a
        if errors:
            for error in errors:
                self.report({'WARNING'}, error)
        elif not any(svg_files):
            self.report({'INFO'}, "Aucun fichier SVG sélectionné")
        
        # Supprimer les copies précédentes
        dice_maker_svg.cleanup_print_copies()

        # Créer des copies pour l'impression si demandé
        print_copies = []
        if props.print_drawings and imported_objects_info:
            print_copies = dice_maker_svg.create_print_copies(context, imported_objects_info)
            # Appliquer le pourcentage de hauteur aux copies d'impression
            dice_maker_svg.apply_height_percentage_to_print_copies(context, print_copies, props.dice_face_height)
        
        # Finaliser les objets importés (translation, rotation, nom)
        if imported_objects_info:
            dice_maker_svg.finalize_imported_objects(
                context, imported_objects_info, cube_size, depth, extrusion_scale
            )
        
        # Extraire la liste des objets pour les modificateurs booléens
        imported_objects = [info['object'] for info in imported_objects_info] if imported_objects_info else []

        # Supprimer l'objet dé s'il existe déjà
        if dice_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[dice_name], do_unlink=True)

        # Créer un nouveau cube
        bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
        
        # Renommer le cube créé
        cube = context.active_object
        cube.name = dice_name
        
        # Appliquer chaque objet SVG comme modificateur booléen DIFFERENCE
        for svg_obj in imported_objects:
            # S'assurer que le cube est sélectionné et actif
            cube.select_set(True)
            context.view_layer.objects.active = cube
            
            # Ajouter un modificateur booléen DIFFERENCE
            bool_mod = cube.modifiers.new(name="Boolean", type='BOOLEAN')
            bool_mod.operation = 'DIFFERENCE'
            bool_mod.object = svg_obj
            
            # Appliquer le modificateur
            bpy.ops.object.modifier_apply(modifier="Boolean")
            
            # Supprimer l'objet SVG
            bpy.data.objects.remove(svg_obj, do_unlink=True)


        sphere_rounding_name = "sphere_rounding"
        if sphere_rounding_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[sphere_rounding_name], do_unlink=True)

        # Ajouter une sphere pour arrondir les coins
        bpy.ops.mesh.primitive_uv_sphere_add(segments=256, ring_count=128, enter_editmode=False, align='WORLD', location=(0, 0, 0), scale=(1, 1, 1))
        sphere = context.active_object
        sphere.name = sphere_rounding_name
        sphere.select_set(True)
        # Redimensionner la sphere avec la valeur du panel
        sphere_scale = props.sphere_rounding_size
        sphere.scale = (sphere_scale, sphere_scale, sphere_scale)

        # sélectionner le cube
        cube.select_set(True)
        context.view_layer.objects.active = cube

        # appliquer un modificateur boolean pour les coins
        bool_mod = cube.modifiers.new(name="Boolean", type='BOOLEAN')
        bool_mod.operation = 'INTERSECT'
        bool_mod.object = sphere
        # appliquer le modificateur
        bpy.ops.object.modifier_apply(modifier="Boolean")

        # supprimer la sphere
        bpy.data.objects.remove(sphere, do_unlink=True)
        
        # Calculer le facteur de taille à partir de la taille souhaitée (cube par défaut = 2)
        size_factor = props.size / 2.0
        
        # Appliquer le facteur de taille global aux objets
        if size_factor != 1.0:
            dice_maker_svg.apply_size_factor_to_objects(context, cube, print_copies, size_factor)
        
        # Organiser les objets sur l'axe X
        # Si print_drawings est activé, placer tous les éléments à z=0
        dice_maker_svg.organize_objects_on_x_axis(context, cube, print_copies, place_on_ground=props.print_drawings)

        self.report({'INFO'}, f"Dé créé: {dice_name} ({len(imported_objects)} SVG appliqués)")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(DICE_MAKER_OT_create_dice)


def unregister():
    bpy.utils.unregister_class(DICE_MAKER_OT_create_dice)


