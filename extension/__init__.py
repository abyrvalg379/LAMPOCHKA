"""LAMPOCHKA — manage all lights in the scene."""

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Maksim Kovalev

import json
import math
import os

import bpy
from bpy.props import (
    StringProperty,
    IntProperty,
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    EnumProperty,
)
from bpy.types import AddonPreferences, PropertyGroup
from bpy.app.handlers import persistent
from bpy_extras.io_utils import ImportHelper


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
#  HDRI — environment browser
# ---------------------------------------------------------------------------

HDRI_EXTENSIONS = ('.exr', '.hdr')
_hdri_pcoll = None        # preview collection, created in register()
_hdri_enum_cache = []     # dynamic enum items must outlive the callback
_hdri_cache_folder = None
_hdri_km = None           # addon keymap for Shift+RMB rotation
_hdri_kmi = None


def hdri_enum_items(self, context):
    """Dynamic enum items (with thumbnails) for HDRI files in the folder."""
    global _hdri_cache_folder
    folder = self.hdri_folder

    if _hdri_cache_folder == folder and _hdri_enum_cache:
        return _hdri_enum_cache

    if _hdri_pcoll is not None and _hdri_cache_folder != folder:
        _hdri_pcoll.clear()

    _hdri_enum_cache.clear()
    _hdri_cache_folder = folder

    if not folder or not os.path.isdir(folder) or _hdri_pcoll is None:
        return _hdri_enum_cache

    try:
        files = sorted(f for f in os.listdir(folder)
                       if f.lower().endswith(HDRI_EXTENSIONS))
    except OSError:
        return _hdri_enum_cache

    for filename in files:
        filepath = os.path.join(folder, filename)
        name = os.path.splitext(filename)[0]
        try:
            thumb = _hdri_pcoll.load(filepath, filepath, 'IMAGE')
        except Exception:
            continue
        _hdri_enum_cache.append(
            (filepath, name, filepath, thumb.icon_id, len(_hdri_enum_cache)))

    return _hdri_enum_cache


def hdri_find_mapping_node(world):
    nodes = world.node_tree.nodes
    node = nodes.get('HDRI Mapping')
    if node and node.type == 'MAPPING':
        return node
    for node in nodes:
        if node.type == 'MAPPING':
            return node
    return None


def update_hdri_rotation(self, context):
    try:
        world = context.scene.world
        if world and world.use_nodes:
            node = hdri_find_mapping_node(world)
            if node:
                node.inputs['Rotation'].default_value = self.rotation
    except Exception:
        pass


def update_hdri_power(self, context):
    try:
        world = context.scene.world
        if world and world.use_nodes:
            for node in world.node_tree.nodes:
                if node.type == 'BACKGROUND':
                    node.inputs['Strength'].default_value = self.power
                    break
    except Exception:
        pass


def register_shift_rmb_keymap():
    """Register the Shift+RMB viewport keymap (operator poll gates the toggle)."""
    global _hdri_km, _hdri_kmi
    if _hdri_kmi is not None:
        return
    try:
        wm = getattr(bpy.context, "window_manager", None)
        kc = wm.keyconfigs.addon if wm is not None else None
        if kc is None:
            return
        km = kc.keymaps.new(name="3D View", space_type='VIEW_3D')
        _hdri_kmi = km.keymap_items.new(
            "light_manager.hdri_shift_rmb", 'RIGHTMOUSE', 'PRESS', shift=True)
        _hdri_km = km
    except Exception:
        pass


def unregister_shift_rmb_keymap():
    global _hdri_km, _hdri_kmi
    if _hdri_km is not None and _hdri_kmi is not None:
        try:
            _hdri_km.keymap_items.remove(_hdri_kmi)
        except Exception:
            pass
    _hdri_kmi = None
    _hdri_km = None


class LM_HDRISettings(PropertyGroup):
    hdri_folder: StringProperty(
        name="HDRI Folder",
        subtype='DIR_PATH',
        description="Folder containing .exr / .hdr files",
    )
    selected_hdri: EnumProperty(
        name="HDRI",
        items=hdri_enum_items,
        description="HDRI files found in the folder",
    )
    rotation: FloatVectorProperty(
        name="Rotation",
        subtype='EULER',
        size=3,
        default=(0.0, 0.0, 0.0),
        update=update_hdri_rotation,
        description="Rotation of the environment mapping",
    )
    power: FloatProperty(
        name="Strength",
        default=1.0,
        min=0.0,
        soft_max=10.0,
        update=update_hdri_power,
        description="Strength of the environment background",
    )
    shift_rmb_rotate: BoolProperty(
        name="Rotate with Shift+RMB",
        description="Drag with Shift+Right Mouse in the viewport to rotate the HDRI",
        default=False,
    )


def get_lm_prefs(context):
    """Add-on preferences (remembered HDRI/IES folders) or None."""
    try:
        return context.preferences.addons[__package__].preferences
    except KeyError:
        return None


class LM_AddonPreferences(AddonPreferences):
    bl_idname = __package__

    hdri_folder: StringProperty(
        name="Default HDRI Folder",
        subtype='DIR_PATH',
        description="Folder used when the current scene has no HDRI folder set",
    )
    ies_folder: StringProperty(
        name="Default IES Folder",
        subtype='DIR_PATH',
        description="Folder used when the current scene has no IES folder set",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "hdri_folder")
        layout.prop(self, "ies_folder")


@persistent
def load_post_handler(dummy):
    """Seed empty scene HDRI/IES folders from preferences."""
    try:
        context = bpy.context
        scene = getattr(context, "scene", None)
        if scene is None or not hasattr(scene, "lm_hdri"):
            return
        prefs = get_lm_prefs(context)
        if prefs is None:
            return
        if hasattr(scene, "lm_hdri") and not scene.lm_hdri.hdri_folder:
            if prefs.hdri_folder:
                scene.lm_hdri.hdri_folder = prefs.hdri_folder
        if hasattr(scene, "lm_ies") and not scene.lm_ies.ies_folder:
            if prefs.ies_folder:
                scene.lm_ies.ies_folder = prefs.ies_folder
    except Exception:
        pass


# ---------------------------------------------------------------------------
#  Light temperature (Kelvin)
# ---------------------------------------------------------------------------

def kelvin_to_rgb(kelvin):
    """Blackbody temperature -> linear RGB (Tanner Helland approximation)."""
    t = max(1000.0, min(kelvin, 40000.0)) / 100.0

    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)

    if t >= 66:
        b = 255.0
    elif t <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10) - 305.0447927307

    srgb = [max(0.0, min(c, 255.0)) / 255.0 for c in (r, g, b)]
    # sRGB -> linear, light.color expects linear values
    return tuple((c / 12.92) if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                 for c in srgb)


def get_obj_light(obj):
    return obj.data if obj.type == 'LIGHT' else None


LM_BB_NODE = 'LM Blackbody'


def _kelvin_targets(light):
    """Emission nodes whose Color input Kelvin may drive (unlinked only)."""
    if not light.use_nodes or light.node_tree is None:
        return []
    return [node for node in light.node_tree.nodes
            if node.type == 'EMISSION' and not node.inputs['Color'].is_linked]


def _lm_apply_kelvin(self, kelvin):
    """Write temperature to the light according to the mode stored on enable."""
    light = get_obj_light(self)
    if light is None:
        return
    if self.get("lm_kelvin_mode") == "nodes" and light.use_nodes and light.node_tree:
        for node in light.node_tree.nodes:
            if node.type == 'BLACKBODY':
                node.inputs[0].default_value = kelvin
    else:
        light.color = kelvin_to_rgb(kelvin)


def lm_temperature_get(self):
    return self.get("lm_temperature", 6500.0)


def lm_temperature_set(self, value):
    self["lm_temperature"] = value
    _lm_apply_kelvin(self, value)


def lm_use_temperature_update(self, context):
    light = get_obj_light(self)
    if light is None:
        return
    if self.lm_use_temperature:
        targets = _kelvin_targets(light)
        if targets:
            # Node light: remember emission colors, drive them via Blackbody
            self["lm_kelvin_mode"] = "nodes"
            saved = {node.name: list(node.inputs['Color'].default_value[:3])
                     for node in targets}
            self["lm_base_data"] = json.dumps({"emissions": saved})
            tree = light.node_tree
            bb = tree.nodes.get(LM_BB_NODE)
            if bb is None or bb.type != 'BLACKBODY':
                bb = tree.nodes.new('ShaderNodeBlackbody')
                bb.name = LM_BB_NODE
                bb.label = LM_BB_NODE
                first = targets[0]
                bb.location = (first.location.x - 200, first.location.y)
            for node in targets:
                tree.links.new(bb.outputs[0], node.inputs['Color'])
            bb.inputs[0].default_value = lm_temperature_get(self)
        else:
            # Plain light: remember light.color and write it directly
            self["lm_kelvin_mode"] = "color"
            if "lm_base_data" not in self:
                self["lm_base_data"] = json.dumps({"color": list(light.color)})
            light.color = kelvin_to_rgb(lm_temperature_get(self))
    else:
        raw = self.get("lm_base_data")
        saved = None
        if raw:
            try:
                saved = json.loads(raw)
            except Exception:
                saved = None
        if saved and "emissions" in saved and light.use_nodes and light.node_tree:
            for name, color in saved["emissions"].items():
                node = light.node_tree.nodes.get(name)
                if node is None:
                    continue
                inp = node.inputs['Color']
                for link in list(inp.links):
                    if link.from_node.type == 'BLACKBODY':
                        light.node_tree.links.remove(link)
                inp.default_value = color
            for node in list(light.node_tree.nodes):
                if node.type == 'BLACKBODY' and node.name == LM_BB_NODE:
                    light.node_tree.nodes.remove(node)
        elif saved and "color" in saved:
            light.color = saved["color"]
        for key in ("lm_base_data", "lm_kelvin_mode", "lm_temperature"):
            if key in self:
                del self[key]


# ---------------------------------------------------------------------------
#  IES — photometric profile browser
# ---------------------------------------------------------------------------

IES_EXTENSIONS = ('.ies',)
_ies_pcoll = None        # preview collection, created in register()
_ies_enum_cache = []     # dynamic enum items must outlive the callback
_ies_cache_folder = None


def ies_enum_items(self, context):
    """Dynamic enum items for IES files; thumbnails from thumbnails/ if present."""
    global _ies_cache_folder
    folder = self.ies_folder

    if _ies_cache_folder == folder and _ies_enum_cache:
        return _ies_enum_cache

    if _ies_pcoll is not None and _ies_cache_folder != folder:
        _ies_pcoll.clear()

    _ies_enum_cache.clear()
    _ies_cache_folder = folder

    if not folder or not os.path.isdir(folder) or _ies_pcoll is None:
        return _ies_enum_cache

    try:
        files = sorted(f for f in os.listdir(folder)
                       if f.lower().endswith(IES_EXTENSIONS))
    except OSError:
        return _ies_enum_cache

    for filename in files:
        filepath = os.path.join(folder, filename)
        name = os.path.splitext(filename)[0]
        icon = 'LIGHT'  # .ies are text files, thumbnails are optional
        thumb = _ies_thumbnail(folder, name)
        if thumb is not None:
            try:
                icon = _ies_pcoll.load(thumb, thumb, 'IMAGE').icon_id
            except Exception:
                icon = 'LIGHT'
        _ies_enum_cache.append(
            (filepath, name, filepath, icon, len(_ies_enum_cache)))

    return _ies_enum_cache


def _ies_thumbnail(folder, basename):
    """Lumio-style optional thumbnail: <folder>/thumbnails/<name>.jpg|png."""
    for ext in ('.jpg', '.jpeg', '.png'):
        candidate = os.path.join(folder, "thumbnails", basename + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


class LM_IESSettings(PropertyGroup):
    ies_folder: StringProperty(
        name="IES Folder",
        subtype='DIR_PATH',
        description="Folder containing .ies files",
    )
    selected_ies: EnumProperty(
        name="IES",
        items=ies_enum_items,
        description="IES files found in the folder",
    )


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
        col.prop(obj, "lm_use_temperature", text="Kelvin")
        if obj.lm_use_temperature:
            col.prop(obj, "lm_temperature", text="Temperature")

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


class LM_PT_HDRIPanel(bpy.types.Panel):
    bl_label = "HDRI"
    bl_idname = "LM_PT_hdri_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LAMPOCHKA"
    bl_parent_id = "LM_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        hdri = context.scene.lm_hdri

        row = layout.row(align=True)
        row.prop(hdri, "hdri_folder", text="")
        row.operator("light_manager.hdri_pick_folder", text="", icon='FILE_FOLDER')

        if not hdri.hdri_folder or not os.path.isdir(hdri.hdri_folder):
            layout.label(text="Pick a folder with .exr / .hdr", icon='INFO')
            return

        # Trigger enum rebuild if needed, then check what we have
        _ = hdri.selected_hdri
        if not _hdri_enum_cache:
            layout.label(text="No .exr / .hdr files in folder", icon='INFO')
            return

        layout.template_icon_view(hdri, "selected_hdri", show_labels=True, scale=4)

        if hdri.selected_hdri:
            name = os.path.splitext(os.path.basename(hdri.selected_hdri))[0]
            layout.label(text=name, icon='WORLD')

        col = layout.column(align=True)
        col.operator("light_manager.hdri_apply", icon='WORLD')
        col.operator("light_manager.hdri_clear", text="Clear HDRI", icon='X')
        col.separator()
        col.prop(hdri, "shift_rmb_rotate", text="Rotate: Shift+RMB", icon='GESTURE_ROTATE')
        col.separator()
        col.prop(hdri, "rotation")
        col.prop(hdri, "power")


class LM_PT_IESPanel(bpy.types.Panel):
    bl_label = "IES"
    bl_idname = "LM_PT_ies_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LAMPOCHKA"
    bl_parent_id = "LM_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        ies = context.scene.lm_ies

        row = layout.row(align=True)
        row.prop(ies, "ies_folder", text="")
        row.operator("light_manager.ies_pick_folder", text="", icon='FILE_FOLDER')

        if not ies.ies_folder or not os.path.isdir(ies.ies_folder):
            layout.label(text="Pick a folder with .ies", icon='INFO')
            return

        # Trigger enum rebuild if needed, then check what we have
        _ = ies.selected_ies
        if not _ies_enum_cache:
            layout.label(text="No .ies files in folder", icon='INFO')
            return

        if context.engine != 'CYCLES':
            layout.label(text="IES works in Cycles only", icon='ERROR')

        layout.template_icon_view(ies, "selected_ies", show_labels=True, scale=4)

        if ies.selected_ies:
            name = os.path.splitext(os.path.basename(ies.selected_ies))[0]
            layout.label(text=name, icon='LIGHT')

        col = layout.column(align=True)
        col.operator("light_manager.ies_apply", icon='LIGHT')
        col.operator("light_manager.ies_remove", text="Remove IES", icon='X')


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


class LM_OT_hdri_pick_folder(bpy.types.Operator, ImportHelper):
    """Pick a folder containing HDRI files."""
    bl_idname = "light_manager.hdri_pick_folder"
    bl_label = "Pick HDRI Folder"
    bl_options = {'REGISTER'}

    filename_ext = ""
    use_filter_folder = True

    def execute(self, context):
        folder = os.path.dirname(self.filepath)
        context.scene.lm_hdri.hdri_folder = folder
        prefs = get_lm_prefs(context)
        if prefs is not None:
            prefs.hdri_folder = folder
        return {'FINISHED'}


class LM_OT_hdri_apply(bpy.types.Operator):
    """Apply the selected HDRI to the world."""
    bl_idname = "light_manager.hdri_apply"
    bl_label = "Apply HDRI"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        hdri = context.scene.lm_hdri
        filepath = hdri.selected_hdri
        if not filepath or not os.path.isfile(filepath):
            self.report({'ERROR'}, "No valid HDRI selected")
            return {'CANCELLED'}

        world = context.scene.world
        if world is None:
            world = bpy.data.worlds.new("World")
            context.scene.world = world
        world.use_nodes = True
        nodes = world.node_tree.nodes
        links = world.node_tree.links

        image = bpy.data.images.load(filepath, check_existing=True)

        env = next((n for n in nodes if n.type == 'TEX_ENVIRONMENT'), None)
        background = next((n for n in nodes if n.type == 'BACKGROUND'), None)

        if env is not None and background is not None:
            # World already has an environment setup — swap the image only
            env.image = image
        else:
            # Plain world — build the HDRI node tree
            nodes.clear()
            node_texcoord = nodes.new('ShaderNodeTexCoord')
            node_mapping = nodes.new('ShaderNodeMapping')
            env = nodes.new('ShaderNodeTexEnvironment')
            background = nodes.new('ShaderNodeBackground')
            node_output = nodes.new('ShaderNodeOutputWorld')

            node_mapping.name = 'HDRI Mapping'
            node_mapping.label = 'HDRI Mapping'

            node_texcoord.location = (-800, 0)
            node_mapping.location = (-600, 0)
            env.location = (-400, 0)
            background.location = (-200, 0)
            node_output.location = (0, 0)

            env.image = image

            links.new(node_texcoord.outputs['Generated'], node_mapping.inputs['Vector'])
            links.new(node_mapping.outputs['Vector'], env.inputs['Vector'])
            links.new(env.outputs['Color'], background.inputs['Color'])
            links.new(background.outputs['Background'], node_output.inputs['Surface'])

        mapping = hdri_find_mapping_node(world)
        if mapping:
            mapping.inputs['Rotation'].default_value = hdri.rotation
        background.inputs['Strength'].default_value = hdri.power

        self.report({'INFO'}, "HDRI applied: " + image.name)
        return {'FINISHED'}


class LM_OT_hdri_shift_rmb(bpy.types.Operator):
    """Rotate the HDRI by dragging with Shift+RMB in the viewport."""
    bl_idname = "light_manager.hdri_shift_rmb"
    bl_label = "Rotate HDRI"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        hdri = getattr(context.scene, "lm_hdri", None)
        return hdri is not None and hdri.shift_rmb_rotate

    def invoke(self, context, event):
        hdri = context.scene.lm_hdri
        self._start_mouse = (event.mouse_x, event.mouse_y)
        self._start_rot = tuple(hdri.rotation)
        self._set_status(context, True)
        # Attach the modal handler explicitly — without it no events arrive
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        hdri = getattr(context.scene, "lm_hdri", None)
        if hdri is None:
            self._set_status(context, False)
            return {'CANCELLED'}
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            dx = event.mouse_x - self._start_mouse[0]
            hdri.rotation = (self._start_rot[0],
                             self._start_rot[1],
                             self._start_rot[2] + dx * 0.006)
            return {'RUNNING_MODAL'}
        if event.value == 'RELEASE' and event.type in {'RIGHTMOUSE', 'LEFTMOUSE'}:
            self._set_status(context, False)
            return {'FINISHED'}
        if event.type == 'ESC':
            hdri.rotation = self._start_rot
            self._set_status(context, False)
            return {'CANCELLED'}
        return {'PASS_THROUGH'}

    def _set_status(self, context, on):
        text = "LAMPOCHKA HDRI: drag — rotate  |  Ctrl+Z — undo" if on else None
        try:
            if on:
                context.window.cursor_modal_set('MOVE_X')
            else:
                context.window.cursor_modal_restore()
        except Exception:
            pass
        try:
            context.workspace.status_text_set(text)
        except Exception:
            pass
        try:
            context.area.header_text_set(text)
        except Exception:
            pass


class LM_OT_hdri_clear(bpy.types.Operator):
    """Remove the HDRI setup from the world."""
    bl_idname = "light_manager.hdri_clear"
    bl_label = "Clear HDRI"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        world = context.scene.world
        if world is None or not world.use_nodes:
            return {'FINISHED'}

        nodes = world.node_tree.nodes
        links = world.node_tree.links

        # Remove the environment chain (own mapping only, by marker name)
        for node in list(nodes):
            if node.type == 'TEX_ENVIRONMENT' or node.name == 'HDRI Mapping':
                nodes.remove(node)

        # Drop texture coordinate nodes left without links
        for node in list(nodes):
            if node.type == 'TEX_COORD' and not any(out.links for out in node.outputs):
                nodes.remove(node)

        # Make sure a plain background remains, linked to the output
        background = next((n for n in nodes if n.type == 'BACKGROUND'), None)
        output = next((n for n in nodes if n.type == 'OUTPUT_WORLD'), None)
        if background is None:
            background = nodes.new('ShaderNodeBackground')
            background.location = (-200, 0)
        if output is None:
            output = nodes.new('ShaderNodeOutputWorld')
            output.location = (0, 0)
        links.new(background.outputs['Background'], output.inputs['Surface'])
        background.inputs['Strength'].default_value = 1.0

        # Reset panel state
        hdri = context.scene.lm_hdri
        hdri.rotation = (0.0, 0.0, 0.0)
        hdri.power = 1.0

        self.report({'INFO'}, "HDRI cleared")
        return {'FINISHED'}


class LM_OT_ies_pick_folder(bpy.types.Operator, ImportHelper):
    """Pick a folder containing IES files."""
    bl_idname = "light_manager.ies_pick_folder"
    bl_label = "Pick IES Folder"
    bl_options = {'REGISTER'}

    filename_ext = ""
    use_filter_folder = True

    def execute(self, context):
        folder = os.path.dirname(self.filepath)
        context.scene.lm_ies.ies_folder = folder
        prefs = get_lm_prefs(context)
        if prefs is not None:
            prefs.ies_folder = folder
        return {'FINISHED'}


class LM_OT_ies_apply(bpy.types.Operator):
    """Apply the selected IES profile to the active light."""
    bl_idname = "light_manager.ies_apply"
    bl_label = "Apply IES"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.type == 'LIGHT'
                and obj.data.type in {'POINT', 'SPOT'})

    def execute(self, context):
        ies = context.scene.lm_ies
        filepath = ies.selected_ies
        if not filepath or not os.path.isfile(filepath):
            self.report({'ERROR'}, "No valid IES selected")
            return {'CANCELLED'}

        light = context.active_object.data
        light.use_nodes = True
        nodes = light.node_tree.nodes
        links = light.node_tree.links

        existing = nodes.get('LM IES')
        if existing is not None and existing.type == 'TEX_IES':
            # Light already has our IES setup — swap the file only
            existing.filepath = filepath
            self.report({'INFO'}, "IES swapped: " + os.path.basename(filepath))
            return {'FINISHED'}

        emission = next((n for n in nodes if n.type == 'EMISSION'), None)
        output = next((n for n in nodes if n.type == 'OUTPUT_LIGHT'), None)

        if emission is None or output is None:
            # No usable chain — build a clean IES setup
            nodes.clear()
            node_ies = nodes.new('ShaderNodeTexIES')
            emission = nodes.new('ShaderNodeEmission')
            output = nodes.new('ShaderNodeOutputLight')

            node_ies.name = 'LM IES'
            node_ies.label = 'LM IES'
            node_ies.mode = 'EXTERNAL'
            node_ies.filepath = filepath

            node_ies.location = (-200, 0)
            emission.location = (0, 0)
            output.location = (200, 0)

            links.new(node_ies.outputs['Fac'], emission.inputs['Strength'])
            links.new(emission.outputs['Emission'], output.inputs['Surface'])
        else:
            # Existing Emission chain — insert the IES node before Strength
            node_ies = nodes.new('ShaderNodeTexIES')
            node_ies.name = 'LM IES'
            node_ies.label = 'LM IES'
            node_ies.mode = 'EXTERNAL'
            node_ies.filepath = filepath
            node_ies.location = (emission.location.x - 200, emission.location.y)
            links.new(node_ies.outputs['Fac'], emission.inputs['Strength'])

        self.report({'INFO'}, "IES applied: " + os.path.basename(filepath))
        return {'FINISHED'}


class LM_OT_ies_remove(bpy.types.Operator):
    """Remove the IES node from the active light."""
    bl_idname = "light_manager.ies_remove"
    bl_label = "Remove IES"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'LIGHT'

    def execute(self, context):
        light = context.active_object.data
        if not light.use_nodes or light.node_tree is None:
            return {'FINISHED'}
        nodes = light.node_tree.nodes
        for node in list(nodes):
            if node.type == 'TEX_IES':
                nodes.remove(node)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
#  Registration
# ---------------------------------------------------------------------------

classes = (
    LM_SceneSettings,
    LM_HDRISettings,
    LM_IESSettings,
    LM_AddonPreferences,
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
    LM_OT_hdri_pick_folder,
    LM_OT_hdri_apply,
    LM_OT_hdri_clear,
    LM_OT_hdri_shift_rmb,
    LM_OT_ies_pick_folder,
    LM_OT_ies_apply,
    LM_OT_ies_remove,
    LM_PT_MainPanel,
    LM_PT_HDRIPanel,
    LM_PT_IESPanel,
)


def register():
    global _hdri_pcoll, _ies_pcoll
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lm_settings = bpy.props.PointerProperty(type=LM_SceneSettings)
    bpy.types.Scene.lm_hdri = bpy.props.PointerProperty(type=LM_HDRISettings)
    bpy.types.Scene.lm_ies = bpy.props.PointerProperty(type=LM_IESSettings)
    # Per-object Kelvin controls (stored as ID props on the light object)
    bpy.types.Object.lm_use_temperature = bpy.props.BoolProperty(
        name="Kelvin",
        description="Drive light color from blackbody temperature",
        default=False,
        update=lm_use_temperature_update,
    )
    bpy.types.Object.lm_temperature = bpy.props.FloatProperty(
        name="Temperature",
        description="Blackbody temperature in Kelvin",
        min=1500.0,
        max=12000.0,
        soft_min=2000.0,
        soft_max=10000.0,
        get=lm_temperature_get,
        set=lm_temperature_set,
    )
    # Register sync handler
    if sync_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sync_handler)
    # Register load handler (remembered HDRI/IES folders)
    if load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_post_handler)
    if _hdri_pcoll is None:
        _hdri_pcoll = bpy.utils.previews.new()
    if _ies_pcoll is None:
        _ies_pcoll = bpy.utils.previews.new()
    # Shift+RMB HDRI rotation keymap (always on, operator poll gates the toggle)
    register_shift_rmb_keymap()


def unregister():
    global _hdri_pcoll, _ies_pcoll
    # Remove the Shift+RMB keymap
    unregister_shift_rmb_keymap()
    # Remove sync handler
    if sync_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sync_handler)
    # Remove load handler
    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)
    if _hdri_pcoll is not None:
        bpy.utils.previews.remove(_hdri_pcoll)
        _hdri_pcoll = None
    if _ies_pcoll is not None:
        bpy.utils.previews.remove(_ies_pcoll)
        _ies_pcoll = None
    _hdri_enum_cache.clear()
    _ies_enum_cache.clear()
    global _hdri_cache_folder, _ies_cache_folder
    _hdri_cache_folder = None
    _ies_cache_folder = None
    try:
        del bpy.types.Scene.lm_hdri
    except Exception:
        pass
    try:
        del bpy.types.Scene.lm_ies
    except Exception:
        pass
    try:
        del bpy.types.Scene.lm_settings
    except Exception:
        pass
    try:
        del bpy.types.Object.lm_use_temperature
    except Exception:
        pass
    try:
        del bpy.types.Object.lm_temperature
    except Exception:
        pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
