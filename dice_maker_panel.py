import bpy
from bpy.props import (
    StringProperty,
    FloatProperty,
    IntProperty,
    BoolProperty,
    EnumProperty,
)
from bpy.types import Panel, PropertyGroup

_FACE_ROTATION_ITEMS = (
    ("-180", "-180°", "Rotation -180°"),
    ("-135", "-135°", "Rotation -135°"),
    ("-90", "-90°", "Rotation -90°"),
    ("-45", "-45°", "Rotation -45°"),
    ("0", "0°", "Pas de rotation"),
    ("45", "45°", "Rotation 45°"),
    ("90", "90°", "Rotation 90°"),
    ("135", "135°", "Rotation 135°"),
    ("180", "180°", "Rotation 180°"),
)


class DiceMakerProperties(PropertyGroup):
    """Propriétés pour stocker les chemins des fichiers SVG"""
    svg_file_1: StringProperty(
        name="Face 1",
        description="Sélectionner le fichier SVG pour la face 1",
        default="",
        maxlen=1024,
        subtype='FILE_PATH'
    )
    svg_file_2: StringProperty(
        name="Face 2",
        description="Sélectionner le fichier SVG pour la face 2",
        default="",
        maxlen=1024,
        subtype='FILE_PATH'
    )
    svg_file_3: StringProperty(
        name="Face 3",
        description="Sélectionner le fichier SVG pour la face 3",
        default="",
        maxlen=1024,
        subtype='FILE_PATH'
    )
    svg_file_4: StringProperty(
        name="Face 4",
        description="Sélectionner le fichier SVG pour la face 4",
        default="",
        maxlen=1024,
        subtype='FILE_PATH'
    )
    svg_file_5: StringProperty(
        name="Face 5",
        description="Sélectionner le fichier SVG pour la face 5",
        default="",
        maxlen=1024,
        subtype='FILE_PATH'
    )
    svg_file_6: StringProperty(
        name="Face 6",
        description="Sélectionner le fichier SVG pour la face 6",
        default="",
        maxlen=1024,
        subtype='FILE_PATH'
    )
    
    # Variables de taille pour chaque face (0.2 à 0.8, pas de 0.05)
    # Note: step est en pourcentage de la plage, donc pour 0.05 sur une plage de 0.6 = 8.33%
    size_factor_1: FloatProperty(
        name="Taille Face 1",
        description="Facteur de taille pour la face 1 (0.2 à 0.8, pas de 0.05)",
        default=0.5,
        min=0.2,
        max=0.8,
        soft_min=0.2,
        soft_max=0.8,
        step=5,
        precision=2
    )
    size_factor_2: FloatProperty(
        name="Taille Face 2",
        description="Facteur de taille pour la face 2 (0.2 à 0.8, pas de 0.05)",
        default=0.5,
        min=0.2,
        max=0.8,
        soft_min=0.2,
        soft_max=0.8,
        step=5,
        precision=2
    )
    size_factor_3: FloatProperty(
        name="Taille Face 3",
        description="Facteur de taille pour la face 3 (0.2 à 0.8, pas de 0.05)",
        default=0.5,
        min=0.2,
        max=0.8,
        soft_min=0.2,
        soft_max=0.8,
        step=5,
        precision=2
    )
    size_factor_4: FloatProperty(
        name="Taille Face 4",
        description="Facteur de taille pour la face 4 (0.2 à 0.8, pas de 0.05)",
        default=0.5,
        min=0.2,
        max=0.8,
        soft_min=0.2,
        soft_max=0.8,
        step=5,
        precision=2
    )
    size_factor_5: FloatProperty(
        name="Taille Face 5",
        description="Facteur de taille pour la face 5 (0.2 à 0.8, pas de 0.05)",
        default=0.5,
        min=0.2,
        max=0.8,
        soft_min=0.2,
        soft_max=0.8,
        step=5,
        precision=2
    )
    size_factor_6: FloatProperty(
        name="Taille Face 6",
        description="Facteur de taille pour la face 6 (0.2 à 0.8, pas de 0.05)",
        default=0.5,
        min=0.2,
        max=0.8,
        soft_min=0.2,
        soft_max=0.8,
        step=5,
        precision=2
    )
    
    # Bevel volume (gravure SVG)
    base_height: FloatProperty(
        name="Base Height",
        description="Hauteur du corps sans bevel, en unités du dé final (0 = biseau dès le bas)",
        default=0.05,
        min=0.0,
        max=2.0,
        soft_min=0.0,
        soft_max=0.5,
        precision=3,
        subtype="DISTANCE",
    )
    bevel_angle: FloatProperty(
        name="Bevel Angle",
        description="Angle du bevel depuis l'horizontale (1°≈plat, 45°=chanfrein)",
        default=45.0,
        min=1.0,
        max=89.0,
        soft_min=15.0,
        soft_max=75.0,
    )
    bevel_height: FloatProperty(
        name="Bevel Height",
        description="Hauteur verticale du biseau, en unités du dé final (0 = prisme sans bevel)",
        default=0.15,
        min=0.0,
        max=2.0,
        soft_min=0.0,
        soft_max=0.5,
        precision=3,
        subtype="DISTANCE",
    )
    
    # Option pour obtenir les dessins à imprimer
    print_drawings: BoolProperty(
        name="Print Drawings",
        description="Obtenir les dessins à imprimer",
        default=False
    )

    # Orientation coin pour impression résine
    resin_orient: BoolProperty(
        name="Resin Print Orient",
        description=(
            "Pose le dé sur un coin (diagonale d'espace alignée sur Z) : "
            "les 3 faces du bas ont le même angle (~54.7°) par rapport au plateau"
        ),
        default=False,
    )
    
    # Taille globale du dé (arête) — toute la géométrie est construite à cette échelle
    size: FloatProperty(
        name="Size",
        description="Taille du dé (longueur d'arête). Base/Bevel height sont absolus par rapport à cette taille.",
        default=1.6,
        min=0.1,
        max=10.0,
        precision=2
    )
    
    # Facteur d'arrondi (calé historiquement sur un demi-cube de 1) ; mis à l'échelle avec Size
    sphere_rounding_size: FloatProperty(
        name="Sphere Rounding Size",
        description="Facteur d'arrondi des coins (relatif ; mis à l'échelle avec Size)",
        default=1.37,
        min=1.3,
        max=1.5,
        precision=2
    )
    
    # Pourcentage de hauteur à appliquer aux copies d'impression
    dice_face_height: IntProperty(
        name="Face Height %",
        description="Hauteur des copies Print Drawings (50–100 %). Sans effet sur le dé.",
        default=85,
        min=50,
        max=100
    )
    
    # Variables de résolution pour chaque face (1 à 10, défaut 5)
    resolution_1: IntProperty(
        name="Résolution Face 1",
        description="Résolution pour la face 1 (1 à 10)",
        default=5,
        min=1,
        max=30
    )
    resolution_2: IntProperty(
        name="Résolution Face 2",
        description="Résolution pour la face 2 (1 à 10)",
        default=5,
        min=1,
        max=30
    )
    resolution_3: IntProperty(
        name="Résolution Face 3",
        description="Résolution pour la face 3 (1 à 10)",
        default=5,
        min=1,
        max=30
    )
    resolution_4: IntProperty(
        name="Résolution Face 4",
        description="Résolution pour la face 4 (1 à 10)",
        default=5,
        min=1,
        max=30
    )
    resolution_5: IntProperty(
        name="Résolution Face 5",
        description="Résolution pour la face 5 (1 à 10)",
        default=5,
        min=1,
        max=30
    )
    resolution_6: IntProperty(
        name="Résolution Face 6",
        description="Résolution pour la face 6 (1 à 10)",
        default=5,
        min=1,
        max=30
    )

    # Flatten Top par face (plateau forcé à Base+Bevel, ou Z suit la pente)
    flatten_top_1: BoolProperty(
        name="Flatten Top Face 1",
        description="Plateau plat à Base+Bevel height (sinon le Z suit la pente)",
        default=True,
    )
    flatten_top_2: BoolProperty(
        name="Flatten Top Face 2",
        description="Plateau plat à Base+Bevel height (sinon le Z suit la pente)",
        default=True,
    )
    flatten_top_3: BoolProperty(
        name="Flatten Top Face 3",
        description="Plateau plat à Base+Bevel height (sinon le Z suit la pente)",
        default=True,
    )
    flatten_top_4: BoolProperty(
        name="Flatten Top Face 4",
        description="Plateau plat à Base+Bevel height (sinon le Z suit la pente)",
        default=True,
    )
    flatten_top_5: BoolProperty(
        name="Flatten Top Face 5",
        description="Plateau plat à Base+Bevel height (sinon le Z suit la pente)",
        default=True,
    )
    flatten_top_6: BoolProperty(
        name="Flatten Top Face 6",
        description="Plateau plat à Base+Bevel height (sinon le Z suit la pente)",
        default=True,
    )

    # Rotation in-plane du dessin (avant projection sur le dé)
    rotation_1: EnumProperty(
        name="Rotation Face 1",
        description="Rotation du dessin dans le plan de la face (avant projection)",
        items=_FACE_ROTATION_ITEMS,
        default="0",
    )
    rotation_2: EnumProperty(
        name="Rotation Face 2",
        description="Rotation du dessin dans le plan de la face (avant projection)",
        items=_FACE_ROTATION_ITEMS,
        default="0",
    )
    rotation_3: EnumProperty(
        name="Rotation Face 3",
        description="Rotation du dessin dans le plan de la face (avant projection)",
        items=_FACE_ROTATION_ITEMS,
        default="0",
    )
    rotation_4: EnumProperty(
        name="Rotation Face 4",
        description="Rotation du dessin dans le plan de la face (avant projection)",
        items=_FACE_ROTATION_ITEMS,
        default="0",
    )
    rotation_5: EnumProperty(
        name="Rotation Face 5",
        description="Rotation du dessin dans le plan de la face (avant projection)",
        items=_FACE_ROTATION_ITEMS,
        default="0",
    )
    rotation_6: EnumProperty(
        name="Rotation Face 6",
        description="Rotation du dessin dans le plan de la face (avant projection)",
        items=_FACE_ROTATION_ITEMS,
        default="0",
    )


class DICE_MAKER_PT_panel(Panel):
    """Panel principal pour Dice Maker"""
    bl_label = "Dice Maker"
    bl_idname = "DICE_MAKER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Dice Maker"

    def draw(self, context):
        layout = self.layout
        props = context.scene.dice_maker_props

        # Sélecteurs de fichiers SVG avec leurs options par face
        layout.label(text="Faces")

        faces = (
            (
                "Front",
                "svg_file_1",
                "size_factor_1",
                "resolution_1",
                "flatten_top_1",
                "rotation_1",
            ),
            (
                "Left",
                "svg_file_2",
                "size_factor_2",
                "resolution_2",
                "flatten_top_2",
                "rotation_2",
            ),
            (
                "Right",
                "svg_file_3",
                "size_factor_3",
                "resolution_3",
                "flatten_top_3",
                "rotation_3",
            ),
            (
                "Top",
                "svg_file_4",
                "size_factor_4",
                "resolution_4",
                "flatten_top_4",
                "rotation_4",
            ),
            (
                "Bottom",
                "svg_file_5",
                "size_factor_5",
                "resolution_5",
                "flatten_top_5",
                "rotation_5",
            ),
            (
                "Back",
                "svg_file_6",
                "size_factor_6",
                "resolution_6",
                "flatten_top_6",
                "rotation_6",
            ),
        )
        for label, svg_attr, size_attr, res_attr, flat_attr, rot_attr in faces:
            box = layout.box()
            box.prop(props, svg_attr, text=label)
            row = box.row(align=True)
            row.prop(props, size_attr, text="Size")
            row.prop(props, res_attr, text="Resolution")
            row = box.row(align=True)
            row.prop(props, rot_attr, text="Rot")
            row.prop(props, flat_attr, text="Flatten Top")

        layout.separator()
        layout.label(text="Bevel")
        layout.prop(props, "base_height", text="Base Height")
        layout.prop(props, "bevel_angle", text="Angle")
        layout.prop(props, "bevel_height", text="Bevel Height")

        layout.separator()

        # Taille globale
        layout.prop(props, "size", text="Size")
        
        layout.separator()
        
        # Taille de la sphère d'arrondi
        layout.prop(props, "sphere_rounding_size", text="Sphere Rounding Size")
        
        layout.separator()

        # Impression des faces (hauteur liée uniquement à cette option)
        box = layout.box()
        box.prop(props, "print_drawings", text="Print Drawings")
        sub = box.column()
        sub.enabled = props.print_drawings
        sub.prop(props, "dice_face_height", text="Face Height %")

        layout.separator()
        layout.prop(props, "resin_orient", text="Resin Print Orient")

        layout.separator()

        # Bouton pour créer le dé
        layout.operator("dice_maker.create_dice", text="Apply")


def register():
    bpy.utils.register_class(DiceMakerProperties)
    bpy.utils.register_class(DICE_MAKER_PT_panel)
    bpy.types.Scene.dice_maker_props = bpy.props.PointerProperty(type=DiceMakerProperties)


def unregister():
    bpy.utils.unregister_class(DICE_MAKER_PT_panel)
    bpy.utils.unregister_class(DiceMakerProperties)
    del bpy.types.Scene.dice_maker_props

