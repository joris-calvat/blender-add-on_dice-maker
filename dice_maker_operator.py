import bpy
from bpy.types import Operator
from . import dice_maker_svg
from . import dice_maker_ui as ui


class DICE_MAKER_OT_create_dice(Operator):
    """Opérateur pour créer le dé"""
    bl_idname = "dice_maker.create_dice"
    bl_label = "Créer le dé"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # S'assurer qu'on n'est pas en mode édition
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        dice_name = "dice_maker_result"
        props = context.scene.dice_maker_props

        svg_files = [
            props.svg_file_1,
            props.svg_file_2,
            props.svg_file_3,
            props.svg_file_4,
            props.svg_file_5,
            props.svg_file_6,
        ]
        size_factors = [
            props.size_factor_1,
            props.size_factor_2,
            props.size_factor_3,
            props.size_factor_4,
            props.size_factor_5,
            props.size_factor_6,
        ]
        resolutions = [
            props.resolution_1,
            props.resolution_2,
            props.resolution_3,
            props.resolution_4,
            props.resolution_5,
            props.resolution_6,
        ]

        # Taille finale du dé dès le départ (pas de scale global ensuite)
        # → base_height / bevel_height restent exacts.
        cube_size = float(props.size)
        n_svg = sum(1 for f in svg_files if f)
        # Étapes approx : import×N + finalize + cube + bool×N + sphere + finish
        total_steps = max(1, n_svg * 2 + 4)
        step = 0
        ui.progress_begin(total_steps, "Dice Maker : démarrage…")

        try:
            ui.refresh_ui("Dice Maker : import SVG + bevel…")
            imported_objects_info, errors = dice_maker_svg.import_all_svgs(
                context,
                svg_files,
                size_factors,
                cube_size,
                resolutions,
                base_height=props.base_height,
                angle=float(props.bevel_angle),
                bevel_height=props.bevel_height,
            )
            step += n_svg
            ui.progress_update(step, "Dice Maker : SVG importés")

            if errors:
                for error in errors:
                    self.report({'WARNING'}, error)
            elif not any(svg_files):
                self.report({'INFO'}, "Aucun fichier SVG sélectionné")

            dice_maker_svg.cleanup_print_copies()
            ui.refresh_ui("Dice Maker : copies impression…")

            print_copies = []
            if props.print_drawings and imported_objects_info:
                print_copies = dice_maker_svg.create_print_copies(
                    context, imported_objects_info
                )
                dice_maker_svg.apply_height_percentage_to_print_copies(
                    context, print_copies, props.dice_face_height
                )

            if imported_objects_info:
                ui.refresh_ui("Dice Maker : placement des faces…")
                dice_maker_svg.finalize_imported_objects(
                    context, imported_objects_info, cube_size
                )
            step += 1
            ui.progress_update(step, "Dice Maker : faces placées")

            imported_objects = (
                [info['object'] for info in imported_objects_info]
                if imported_objects_info
                else []
            )

            if dice_name in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[dice_name], do_unlink=True)

            ui.refresh_ui("Dice Maker : création du cube…")
            bpy.ops.mesh.primitive_cube_add(size=cube_size, location=(0, 0, 0))
            cube = context.active_object
            cube.name = dice_name
            step += 1
            ui.progress_update(step, "Dice Maker : cube créé")

            for i, svg_obj in enumerate(imported_objects):
                ui.refresh_ui(
                    f"Dice Maker : boolean face {i + 1}/{len(imported_objects)}…"
                )
                cube.select_set(True)
                context.view_layer.objects.active = cube

                bool_mod = cube.modifiers.new(name="Boolean", type='BOOLEAN')
                bool_mod.operation = 'DIFFERENCE'
                bool_mod.object = svg_obj
                bpy.ops.object.modifier_apply(modifier="Boolean")
                bpy.data.objects.remove(svg_obj, do_unlink=True)
                step += 1
                ui.progress_update(
                    step,
                    f"Dice Maker : boolean {i + 1}/{len(imported_objects)}",
                )

            sphere_rounding_name = "sphere_rounding"
            if sphere_rounding_name in bpy.data.objects:
                bpy.data.objects.remove(
                    bpy.data.objects[sphere_rounding_name], do_unlink=True
                )

            ui.refresh_ui("Dice Maker : arrondi (sphère)…")
            bpy.ops.mesh.primitive_uv_sphere_add(
                segments=256,
                ring_count=128,
                enter_editmode=False,
                align='WORLD',
                location=(0, 0, 0),
                scale=(1, 1, 1),
            )
            sphere = context.active_object
            sphere.name = sphere_rounding_name
            sphere.select_set(True)
            # Facteur historique calé sur un demi-cube de 1 (cube size=2)
            sphere_scale = props.sphere_rounding_size * (cube_size / 2.0)
            sphere.scale = (sphere_scale, sphere_scale, sphere_scale)

            cube.select_set(True)
            context.view_layer.objects.active = cube
            bool_mod = cube.modifiers.new(name="Boolean", type='BOOLEAN')
            bool_mod.operation = 'INTERSECT'
            bool_mod.object = sphere
            bpy.ops.object.modifier_apply(modifier="Boolean")
            bpy.data.objects.remove(sphere, do_unlink=True)
            step += 1
            ui.progress_update(step, "Dice Maker : arrondi appliqué")

            ui.refresh_ui("Dice Maker : organisation…")
            dice_maker_svg.organize_objects_on_x_axis(
                context, cube, print_copies, place_on_ground=props.print_drawings
            )
            ui.progress_update(total_steps, "Dice Maker : terminé")

            self.report(
                {'INFO'},
                f"Dé créé: {dice_name} ({len(imported_objects)} SVG, "
                f"size={cube_size:.3f})",
            )
            return {'FINISHED'}
        finally:
            ui.progress_end()


def register():
    bpy.utils.register_class(DICE_MAKER_OT_create_dice)


def unregister():
    bpy.utils.unregister_class(DICE_MAKER_OT_create_dice)
