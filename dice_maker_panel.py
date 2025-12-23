import bpy
from bpy.props import StringProperty, FloatProperty, IntProperty, BoolProperty
from bpy.types import Panel, PropertyGroup


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
    
    # Variable de profondeur (0.1 à 0.3, pas de 0.05)
    # Note: step est en pourcentage de la plage, donc pour 0.05 sur une plage de 0.2 = 25%
    depth: FloatProperty(
        name="Profondeur",
        description="Profondeur pour les objets SVG (0.1 à 0.3, pas de 0.05)",
        default=0.2,
        min=0.05,
        max=0.3,
        soft_min=0.05,
        soft_max=0.3,
        step=5,
        precision=2
    )
    
    # Option pour obtenir les dessins à imprimer
    print_drawings: BoolProperty(
        name="Print Drawings",
        description="Obtenir les dessins à imprimer",
        default=False
    )
    
    # Taille globale pour tous les objets (le cube par défaut vaut 2)
    size: FloatProperty(
        name="Size",
        description="Taille globale pour tous les objets (le cube par défaut vaut 2)",
        default=1.6,
        min=0.1,
        max=10.0,
        precision=2
    )
    
    # Taille de la sphère pour arrondir les coins du cube
    sphere_rounding_size: FloatProperty(
        name="Sphere Rounding Size",
        description="Taille de la sphère pour arrondir les coins du cube (1.3 à 1.5)",
        default=1.37,
        min=1.3,
        max=1.5,
        precision=2
    )
    
    # Pourcentage de hauteur à appliquer aux copies d'impression
    dice_face_height: IntProperty(
        name="Dice Face Height",
        description="Pourcentage de hauteur à appliquer aux copies d'impression (50 à 100)",
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
        max=10
    )
    resolution_2: IntProperty(
        name="Résolution Face 2",
        description="Résolution pour la face 2 (1 à 10)",
        default=5,
        min=1,
        max=10
    )
    resolution_3: IntProperty(
        name="Résolution Face 3",
        description="Résolution pour la face 3 (1 à 10)",
        default=5,
        min=1,
        max=10
    )
    resolution_4: IntProperty(
        name="Résolution Face 4",
        description="Résolution pour la face 4 (1 à 10)",
        default=5,
        min=1,
        max=10
    )
    resolution_5: IntProperty(
        name="Résolution Face 5",
        description="Résolution pour la face 5 (1 à 10)",
        default=5,
        min=1,
        max=10
    )
    resolution_6: IntProperty(
        name="Résolution Face 6",
        description="Résolution pour la face 6 (1 à 10)",
        default=5,
        min=1,
        max=10
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

        # Sélecteurs de fichiers SVG avec leurs tailles
        layout.label(text="Files")
        
        # Face front
        layout.prop(props, "svg_file_1", text="Front")
        row = layout.row()
        row.prop(props, "size_factor_1", text="Size")
        row.prop(props, "resolution_1", text="Resolution")
        
        # Face left
        layout.prop(props, "svg_file_2", text="Left")
        row = layout.row()
        row.prop(props, "size_factor_2", text="Size")
        row.prop(props, "resolution_2", text="Resolution")
        
        # Face right
        layout.prop(props, "svg_file_3", text="Right")
        row = layout.row()
        row.prop(props, "size_factor_3", text="Size")
        row.prop(props, "resolution_3", text="Resolution")
        
        # Face top
        layout.prop(props, "svg_file_4", text="Top")
        row = layout.row()
        row.prop(props, "size_factor_4", text="Size")
        row.prop(props, "resolution_4", text="Resolution")
        
        # Face bottom
        layout.prop(props, "svg_file_5", text="Bottom")
        row = layout.row()
        row.prop(props, "size_factor_5", text="Size")
        row.prop(props, "resolution_5", text="Resolution")
        
        # Face back
        layout.prop(props, "svg_file_6", text="Back")
        row = layout.row()
        row.prop(props, "size_factor_6", text="Size")
        row.prop(props, "resolution_6", text="Resolution")

        layout.separator()
        
        # Variable de profondeur
        layout.prop(props, "depth", text="Depth")
        
        layout.separator()
        
        # Taille globale
        layout.prop(props, "size", text="Size")
        
        layout.separator()
        
        # Taille de la sphère d'arrondi
        layout.prop(props, "sphere_rounding_size", text="Sphere Rounding Size")
        
        layout.separator()
        
        # Pourcentage de hauteur pour les copies d'impression
        layout.prop(props, "dice_face_height", text="Dice Face Height %")
        
        layout.separator()
        
        # Option pour les dessins à imprimer
        layout.prop(props, "print_drawings", text="Print Drawings")

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

