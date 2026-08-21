"""LAMPOCHKA — manage all lights in the scene."""

import bpy
from bpy.props import StringProperty, IntProperty, BoolProperty
from bpy.types import PropertyGroup
from bpy.app.handlers import persistent


# ---------------------------------------------------------------------------
#  Sync handler — viewport → panel
# ---------------------------------------------------------------------------

_last_active_light = None
_settings_were_open = False


@persistent
def sync_handler(scene):
    """Auto-sync selected light from viewport."""
    global _last_active_light, _settings_were_open
    try:
        context = bpy.context
        if not hasattr(context, 'scene') or context.scene is None:
            return
        settings = context.scene.lm_settings
        active = context.active_object

        if active and active.type == 'LIGHT':
            lights = [o for o in context.scene.objects if o.type == 'LIGHT']
            if active in lights:
                idx = lights.index(active)
                if settings.selected_index != idx:
                    # Check if settings were open BEFORE changing index
                    settings_open = bool(settings.settings_light)
                    _settings_were_open = settings_open

                    settings.selected_index = idx

                    # Transfer settings state to new light
                    if _settings_were_open:
                        settings.settings_light = active.name
                    else:
                        settings.settings_light = ""

                _last_active_light = active.name
    except Exception:
        pass


# ---------------------------------------------------------------------------
#  Properties
# ---------------------------------------------------------------------------

class LM_SceneSettings(PropertyGroup):
    selected_index: IntProperty(name="Selected Index", default=-1)
    filter_name: StringProperty(name="Filter", default="", description="Filter lights by name")
    settings_light: StringProperty(name="Settings Light", default="", description="Name of light with open settings")
    transform_open: BoolProperty(name="Transform Open", default=False)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def get_scene_lights(context):
    return [o for o in context.scene.objects if o.type == 'LIGHT']


def get_filtered_lights(context):
    lights = get_scene_lights(context)
    filter_text = context.scene.lm_settings.filter_name.lower()
    if filter_text:
        return [o for o in lights if filter_text in o.name.lower()]
    return lights


LIGHT_TYPE_ICONS = {
    'POINT': 'LIGHT_POINT',
    'SUN': 'LIGHT_SUN',
    'SPOT': 'LIGHT_SPOT',
    'AREA': 'LIGHT_AREA',
}


def get_light_icon(light):
    if light and light.type in LIGHT_TYPE_ICONS:
        return LIGHT_TYPE_ICONS[light.type]
    return 'LIGHT'


# ---------------------------------------------------------------------------
#  Panel
# ---------------------------------------------------------------------------

class LM_PT_MainPanel(bpy.types.Panel):
    bl_label = "LAMPOCHKA"
    bl_idname = "LM_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LAMPOCHKA"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lm_settings

        # --- Header ---
        row = layout.row(align=True)
        row.prop(settings, "filter_name", text="", icon='VIEWZOOM')
        row.separator()
        row.operator("light_manager.toggle_all_visibility", text="", icon='HIDE_OFF')
        row.operator("light_manager.toggle_all_render", text="", icon='RESTRICT_RENDER_OFF')
        row.separator()
        row.operator_menu_enum("light_manager.add_light", "light_type", text="", icon='ADD')

        # --- Light list ---
        lights = get_filtered_lights(context)
        if not lights:
            layout.label(text="No lights", icon='INFO')
            return

        for obj in lights:
            self._draw_light_row(context, layout, obj)

    def _draw_light_row(self, context, layout, obj):
        settings = context.scene.lm_settings
        all_lights = get_scene_lights(context)
        full_idx = all_lights.index(obj) if obj in all_lights else -1
        is_selected = (full_idx == settings.selected_index)
        settings_open = settings.settings_light == obj.name
        light = obj.data
        icon = get_light_icon(light)

        row = layout.row(align=True)

        # Name (click to select)
        sub = row.row(align=True)
        sub.active = is_selected
        op = sub.operator("light_manager.select_light", text=obj.name, icon=icon)
        op.index = full_idx

        # Gear (click to open settings)
        op = row.operator("light_manager.toggle_settings", text="", icon='PREFERENCES',
                          depress=settings_open)
        op.light_name = obj.name

        # Visibility icons (operators)
        op = row.operator("light_manager.toggle_visibility", text="",
                          icon='HIDE_OFF' if not obj.hide_viewport else 'HIDE_ON')
        op.index = full_idx
        op = row.operator("light_manager.toggle_render", text="",
                          icon='RESTRICT_RENDER_OFF' if not obj.hide_render else 'RESTRICT_RENDER_ON')
        op.index = full_idx

        # Settings (only if gear clicked)
        if settings_open:
            self._draw_settings(context, layout, obj)

    def _draw_settings(self, context, layout, obj):
        light = obj.data
        if not light:
            return

        layout.separator(factor=0.3)
        box = layout.box()

        # Action buttons
        row = box.row(align=True)
        row.operator("light_manager.duplicate_light", text="", icon='DUPLICATE')
        row.operator("light_manager.delete_light", text="", icon='TRASH')
        row.separator()
        row.operator("light_manager.move_light", text="", icon='TRIA_UP').direction = 'UP'
        row.operator("light_manager.move_light", text="", icon='TRIA_DOWN').direction = 'DOWN'

        # Settings
        col = box.column(align=True)
        col.prop(light, "type", text="Type")
        col.prop(light, "color", text="Color")
        col.prop(light, "energy", text="Power")

        col.separator()
        col.prop(light, "use_shadow", text="Shadow")
        if light.use_shadow:
            col.prop(light, "shadow_soft_size", text="Shadow Size")

        # Type-specific
        if light.type == 'POINT':
            col.separator()
            col.prop(light, "shadow_soft_size", text="Radius")
        elif light.type == 'SUN':
            col.separator()
            col.prop(light, "angle", text="Angle")
        elif light.type == 'SPOT':
            col.separator()
            col.prop(light, "spot_size", text="Spot Size")
            col.prop(light, "spot_blend", text="Blend")
            col.prop(light, "show_cone", text="Show Cone")
        elif light.type == 'AREA':
            col.separator()
            col.prop(light, "shape", text="Shape")
            if light.shape in {'SQUARE', 'DISK'}:
                col.prop(light, "size", text="Size")
            else:
                col.prop(light, "size_x", text="Size X")
                col.prop(light, "size_y", text="Size Y")

        # Cycles
        if context.engine == 'CYCLES':
            col.separator()
            col.prop(light, "use_nodes", text="Use Nodes")
            if light.use_nodes and light.node_tree:
                for node in light.node_tree.nodes:
                    if node.type == 'EMISSION':
                        col.prop(node.inputs[1], "default_value", text="Emission Strength")

        # Contact shadow
        if hasattr(light, 'use_contact_shadow'):
            col.separator()
            col.prop(light, "use_contact_shadow", text="Contact Shadow")
            if light.use_contact_shadow:
                col.prop(light, "contact_shadow_distance", text="Distance")
                col.prop(light, "contact_shadow_bias", text="Bias")
                col.prop(light, "contact_shadow_thickness", text="Thickness")

        # Volume
        if hasattr(light, 'volume_factor'):
            col.separator()
            col.prop(light, "volume_factor", text="Volume")

        # Transform (collapsed)
        settings = context.scene.lm_settings
        transform_open = settings.transform_open

        row = box.row(align=True)
        toggle_icon = 'TRIA_DOWN' if transform_open else 'TRIA_RIGHT'
        op = row.operator("light_manager.toggle_transform", text="", icon=toggle_icon, emboss=False)
        row.label(text="Transform", icon='OBJECT_ORIGIN')

        if transform_open:
            col = box.column(align=True)
            col.prop(obj, "location", text="Loc")
            col.prop(obj, "rotation_euler", text="Rot")
            col.prop(obj, "scale", text="Scl")

        layout.separator(factor=0.3)


# ---------------------------------------------------------------------------
#  Operators
# ---------------------------------------------------------------------------

class LM_OT_select_light(bpy.types.Operator):
    """Select a light in the scene."""
    bl_idname = "light_manager.select_light"
    bl_label = "Select Light"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        lights = get_scene_lights(context)
        if 0 <= self.index < len(lights):
            obj = lights[self.index]
            settings = context.scene.lm_settings
            # Remember if settings were open
            had_settings_open = bool(settings.settings_light)
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            settings.selected_index = self.index
            # Transfer settings state to new light
            if had_settings_open:
                settings.settings_light = obj.name
            else:
                settings.settings_light = ""
        return {'FINISHED'}


class LM_OT_toggle_visibility(bpy.types.Operator):
    """Toggle viewport visibility."""
    bl_idname = "light_manager.toggle_visibility"
    bl_label = "Toggle Visibility"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        lights = get_scene_lights(context)
        if 0 <= self.index < len(lights):
            lights[self.index].hide_viewport = not lights[self.index].hide_viewport
        return {'FINISHED'}


class LM_OT_toggle_render(bpy.types.Operator):
    """Toggle render visibility."""
    bl_idname = "light_manager.toggle_render"
    bl_label = "Toggle Render"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        lights = get_scene_lights(context)
        if 0 <= self.index < len(lights):
            lights[self.index].hide_render = not lights[self.index].hide_render
        return {'FINISHED'}


class LM_OT_toggle_all_visibility(bpy.types.Operator):
    """Toggle all lights viewport visibility."""
    bl_idname = "light_manager.toggle_all_visibility"
    bl_label = "Toggle All"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        lights = get_scene_lights(context)
        if not lights:
            return {'CANCELLED'}
        any_visible = any(not l.hide_viewport for l in lights)
        for l in lights:
            l.hide_viewport = any_visible
        return {'FINISHED'}


class LM_OT_toggle_all_render(bpy.types.Operator):
    """Toggle all lights render visibility."""
    bl_idname = "light_manager.toggle_all_render"
    bl_label = "Toggle All Render"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        lights = get_scene_lights(context)
        if not lights:
            return {'CANCELLED'}
        any_visible = any(not l.hide_render for l in lights)
        for l in lights:
            l.hide_render = any_visible
        return {'FINISHED'}


class LM_OT_add_light(bpy.types.Operator):
    """Add a new light."""
    bl_idname = "light_manager.add_light"
    bl_label = "Add Light"
    bl_options = {'REGISTER', 'UNDO'}

    light_type: bpy.props.EnumProperty(
        name="Type",
        items=[
            ('POINT', "Point", "Point light"),
            ('SUN', "Sun", "Sun light"),
            ('SPOT', "Spot", "Spot light"),
            ('AREA', "Area", "Area light"),
        ],
        default='POINT',
    )

    def execute(self, context):
        light_data = bpy.data.lights.new(name=self.light_type + "_Light", type=self.light_type)
        obj = bpy.data.objects.new(name=light_data.name, object_data=light_data)
        context.collection.objects.link(obj)
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class LM_OT_delete_light(bpy.types.Operator):
    """Delete selected light."""
    bl_idname = "light_manager.delete_light"
    bl_label = "Delete Light"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'LIGHT':
            bpy.data.objects.remove(obj, do_unlink=True)
        return {'FINISHED'}


class LM_OT_duplicate_light(bpy.types.Operator):
    """Duplicate selected light."""
    bl_idname = "light_manager.duplicate_light"
    bl_label = "Duplicate Light"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'LIGHT':
            return {'CANCELLED'}
        new_obj = obj.copy()
        if obj.data:
            new_obj.data = obj.data.copy()
        new_obj.name = obj.name + "_copy"
        context.collection.objects.link(new_obj)
        bpy.ops.object.select_all(action='DESELECT')
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj
        return {'FINISHED'}


class LM_OT_move_light(bpy.types.Operator):
    """Move light up or down."""
    bl_idname = "light_manager.move_light"
    bl_label = "Move Light"
    bl_options = {'REGISTER', 'UNDO'}

    direction: bpy.props.EnumProperty(
        items=[('UP', "Up", "Move up"), ('DOWN', "Down", "Move down")],
        default='UP',
    )

    def execute(self, context):
        lights = get_scene_lights(context)
        idx = context.scene.lm_settings.selected_index
        if self.direction == 'UP' and idx > 0:
            lights[idx].name, lights[idx - 1].name = lights[idx - 1].name, lights[idx].name
            context.scene.lm_settings.selected_index -= 1
        elif self.direction == 'DOWN' and idx < len(lights) - 1:
            lights[idx].name, lights[idx + 1].name = lights[idx + 1].name, lights[idx].name
            context.scene.lm_settings.selected_index += 1
        return {'FINISHED'}


class LM_OT_toggle_settings(bpy.types.Operator):
    """Toggle settings for a light."""
    bl_idname = "light_manager.toggle_settings"
    bl_label = "Toggle Settings"
    bl_options = {'REGISTER'}

    light_name: bpy.props.StringProperty()

    def execute(self, context):
        settings = context.scene.lm_settings
        if settings.settings_light == self.light_name:
            settings.settings_light = ""
        else:
            settings.settings_light = self.light_name
        return {'FINISHED'}


class LM_OT_toggle_transform(bpy.types.Operator):
    """Toggle transform section."""
    bl_idname = "light_manager.toggle_transform"
    bl_label = "Toggle Transform"
    bl_options = {'REGISTER'}

    def execute(self, context):
        context.scene.lm_settings.transform_open = not context.scene.lm_settings.transform_open
        return {'FINISHED'}


# ---------------------------------------------------------------------------
#  Registration
# ---------------------------------------------------------------------------

classes = (
    LM_SceneSettings,
    LM_OT_select_light,
    LM_OT_toggle_visibility,
    LM_OT_toggle_render,
    LM_OT_toggle_all_visibility,
    LM_OT_toggle_all_render,
    LM_OT_add_light,
    LM_OT_delete_light,
    LM_OT_duplicate_light,
    LM_OT_move_light,
    LM_OT_toggle_settings,
    LM_OT_toggle_transform,
    LM_PT_MainPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lm_settings = bpy.props.PointerProperty(type=LM_SceneSettings)
    # Register sync handler
    if sync_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sync_handler)


def unregister():
    # Remove sync handler
    if sync_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sync_handler)
    try:
        del bpy.types.Scene.lm_settings
    except Exception:
        pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
