"""LAMPOCHKA — manage all lights in the scene."""

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Maksim Kovalev

import json
import math
import os

import bpy
from mathutils import Vector
from bpy.props import (
    StringProperty,
    IntProperty,
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    EnumProperty,
    PointerProperty,
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


LM_CAM_MIX = 'LM Cam Mix'
LM_CAM_PATH = 'LM Cam Path'


def _find_node(nodes, ntype):
    return next((n for n in nodes if n.type == ntype), None)


def update_hdri_hide_from_camera(self, context):
    _hdri_ensure_camera_mix(context.scene.world, self.hide_from_camera,
                            self.camera_color)


def update_hdri_camera_color(self, context):
    _hdri_ensure_camera_mix(context.scene.world, True, self.camera_color)


def _hdri_ensure_camera_mix(world, enabled, color):
    """Insert/remove the Is Camera Ray mix between env and background."""
    if world is None or not world.use_nodes or world.node_tree is None:
        return
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    env = _find_node(nodes, 'TEX_ENVIRONMENT')
    background = _find_node(nodes, 'BACKGROUND')
    mix = nodes.get(LM_CAM_MIX)

    if not enabled:
        if mix is not None and env is not None and background is not None:
            links.new(env.outputs['Color'], background.inputs['Color'])
        for marker in (LM_CAM_MIX, LM_CAM_PATH):
            node = nodes.get(marker)
            if node is not None:
                nodes.remove(node)
        return

    if env is None or background is None:
        return

    if mix is None or mix.type != 'MIX_RGB':
        if mix is not None:
            nodes.remove(mix)
        mix = nodes.new('ShaderNodeMixRGB')
        mix.name = LM_CAM_MIX
        mix.label = LM_CAM_MIX
        mix.blend_type = 'MIX'
        mix.location = (env.location.x + 200, env.location.y - 200)
        path = nodes.new('ShaderNodeLightPath')
        path.name = LM_CAM_PATH
        path.label = LM_CAM_PATH
        path.location = (mix.location.x - 200, mix.location.y - 200)
        links.new(env.outputs['Color'], mix.inputs['Color1'])
        links.new(mix.outputs['Color'], background.inputs['Color'])
        links.new(path.outputs['Is Camera Ray'], mix.inputs['Fac'])
    mix.inputs['Color2'].default_value = (color[0], color[1], color[2], 1.0)


def _hdri_apply_image(context, filepath):
    """Build or update the world HDRI node chain with the given image."""
    world = context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        context.scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links

    image = bpy.data.images.load(filepath, check_existing=True)

    env = _find_node(nodes, 'TEX_ENVIRONMENT')
    background = _find_node(nodes, 'BACKGROUND')

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

    hdri = context.scene.lm_hdri
    mapping = hdri_find_mapping_node(world)
    if mapping:
        mapping.inputs['Rotation'].default_value = hdri.rotation
    background.inputs['Strength'].default_value = hdri.power

    _hdri_ensure_camera_mix(world, getattr(hdri, "hide_from_camera", False),
                            getattr(hdri, "camera_color", (0.0, 0.0, 0.0)))
    return {'FINISHED'}


def update_hdri_selected(self, context):
    """Auto-apply when a thumbnail is clicked in the browser grid."""
    filepath = self.selected_hdri
    if filepath and os.path.isfile(filepath):
        try:
            _hdri_apply_image(context, filepath)
        except Exception:
            pass


def _hdri_cycle(context, step):
    """Move the HDRI selection by step entries (update applies it)."""
    hdri = context.scene.lm_hdri
    if not _hdri_enum_cache:
        return {'CANCELLED'}
    ids = [item[0] for item in _hdri_enum_cache]
    try:
        idx = ids.index(hdri.selected_hdri)
    except ValueError:
        # Unknown selection: next starts from the first, prev from the last
        hdri.selected_hdri = ids[0] if step > 0 else ids[-1]
        return {'FINISHED'}
    hdri.selected_hdri = ids[(idx + step) % len(ids)]
    return {'FINISHED'}


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
        update=update_hdri_selected,
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
    hide_from_camera: BoolProperty(
        name="Hide from Camera",
        description="Show a flat color to the camera instead of the HDRI "
                    "(lighting and reflections keep the HDRI)",
        default=False,
        update=update_hdri_hide_from_camera,
    )
    camera_color: FloatVectorProperty(
        name="Camera Color",
        subtype='COLOR',
        size=3,
        min=0.0,
        max=1.0,
        default=(0.0, 0.0, 0.0),
        update=update_hdri_camera_color,
        description="Color visible to the camera when the HDRI is hidden",
    )


def get_lm_prefs(context):
    """Add-on preferences (remembered HDRI/IES folders) or None."""
    try:
        return context.preferences.addons[__package__].preferences
    except KeyError:
        return None


def _seed_scene_folder(scene_group, folder_attr):
    """Live pickup: changing a default folder in preferences immediately
    fills the still-empty folder of the current scene. Scenes that keep
    their own folder are never overridden."""
    try:
        scene = getattr(bpy.context, "scene", None)
        if scene is None:
            return
        scene_props = getattr(scene, scene_group, None)
        prefs = get_lm_prefs(bpy.context)
        if scene_props is None or prefs is None:
            return
        if not getattr(scene_props, folder_attr, "") and getattr(prefs, folder_attr, ""):
            setattr(scene_props, folder_attr, getattr(prefs, folder_attr))
    except Exception:
        pass


def _on_pref_hdri(self, context):
    _seed_scene_folder("lm_hdri", "hdri_folder")


def _on_pref_ies(self, context):
    _seed_scene_folder("lm_ies", "ies_folder")


def _on_pref_gobo(self, context):
    _seed_scene_folder("lm_gobo", "gobo_folder")


class LM_AddonPreferences(AddonPreferences):
    bl_idname = __package__

    hdri_folder: StringProperty(
        name="Default HDRI Folder",
        subtype='DIR_PATH',
        update=_on_pref_hdri,
        description="Folder used when the current scene has no HDRI folder set",
    )
    ies_folder: StringProperty(
        name="Default IES Folder",
        subtype='DIR_PATH',
        update=_on_pref_ies,
        description="Folder used when the current scene has no IES folder set",
    )
    gobo_folder: StringProperty(
        name="Default Gobo Folder",
        subtype='DIR_PATH',
        update=_on_pref_gobo,
        description="Folder used when the current scene has no gobo folder set",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "hdri_folder")
        layout.prop(self, "ies_folder")
        layout.prop(self, "gobo_folder")


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
        if hasattr(scene, "lm_gobo") and not scene.lm_gobo.gobo_folder:
            if prefs.gobo_folder:
                scene.lm_gobo.gobo_folder = prefs.gobo_folder
        # Rotate toggle is always off in a fresh session — otherwise users
        # forget Shift+RMB is hijacked and blame the default navigation
        if hasattr(scene, "lm_hdri"):
            scene.lm_hdri.shift_rmb_rotate = False
        # same for the G placement arming — never hijack G unexpectedly
        try:
            for ob in context.scene.objects:
                if getattr(ob, "lm_place_enable", False):
                    ob.lm_place_enable = False
        except Exception:
            pass
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
#  Sun helper — aim a sun light by time & location (NOAA algorithm, public domain)
# ---------------------------------------------------------------------------

def _julian_day(year, month, day, hour_utc):
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    jdn = day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    return jdn + (hour_utc - 12.0) / 24.0


def sun_azimuth_elevation(year, month, day, hour_local, latitude, longitude, utc_offset):
    """Solar position (NOAA, public domain). hour_local = local clock time.
    Returns (azimuth_deg, elevation_deg); azimuth measured from north, clockwise."""
    jd = _julian_day(year, month, day, hour_local - utc_offset)
    n = jd - 2451545.0

    mean_lon = (280.460 + 0.9856474 * n) % 360.0
    mean_anom = math.radians((357.528 + 0.9856003 * n) % 360.0)
    ecl_lon = math.radians(mean_lon + 1.915 * math.sin(mean_anom)
                           + 0.020 * math.sin(2.0 * mean_anom))
    obliq = math.radians(23.439 - 0.0000004 * n)

    alpha = math.atan2(math.cos(obliq) * math.sin(ecl_lon), math.cos(ecl_lon))
    decl = math.asin(math.sin(obliq) * math.sin(ecl_lon))

    gmst = (280.46061837 + 360.98564736629 * n) % 360.0
    ha = math.radians(((gmst + longitude - math.degrees(alpha) + 180.0) % 360.0) - 180.0)

    lat = math.radians(latitude)
    cos_zen = (math.sin(lat) * math.sin(decl)
               + math.cos(lat) * math.cos(decl) * math.cos(ha))
    cos_zen = max(-1.0, min(1.0, cos_zen))
    elevation = 90.0 - math.degrees(math.acos(cos_zen))

    az = math.atan2(math.sin(ha),
                    math.cos(ha) * math.sin(lat) - math.tan(decl) * math.cos(lat))
    azimuth = (math.degrees(az) + 180.0) % 360.0
    return azimuth, elevation


def _day_declination(year, month, day):
    """Sun declination at local noon (radians) + equation of time (minutes)."""
    jd = _julian_day(year, month, day, 12.0)
    n = jd - 2451545.0
    mean_lon = (280.460 + 0.9856474 * n) % 360.0
    mean_anom = math.radians((357.528 + 0.9856003 * n) % 360.0)
    ecl_lon = math.radians(mean_lon + 1.915 * math.sin(mean_anom)
                           + 0.020 * math.sin(2.0 * mean_anom))
    obliq = math.radians(23.439 - 0.0000004 * n)
    alpha = math.degrees(math.atan2(math.cos(obliq) * math.sin(ecl_lon),
                                    math.cos(ecl_lon)))
    decl = math.asin(math.sin(obliq) * math.sin(ecl_lon))
    eq_time_min = 4.0 * ((mean_lon - alpha + 180.0) % 360.0 - 180.0)
    return decl, eq_time_min


def _sunrise_sunset(year, month, day, latitude, longitude, utc_offset):
    """Return (sunrise_hours, sunset_hours) in local clock time, or (None, None)."""
    decl, eq_time_min = _day_declination(year, month, day)
    lat = math.radians(latitude)
    cos_ha0 = ((math.cos(math.radians(90.833)) - math.sin(lat) * math.sin(decl))
               / (math.cos(lat) * math.cos(decl)))
    if not -1.0 <= cos_ha0 <= 1.0:
        return None, None  # polar day/night
    ha0_min = 4.0 * math.degrees(math.acos(cos_ha0))
    solar_noon_utc = 720.0 - 4.0 * longitude - eq_time_min
    rise = (solar_noon_utc - ha0_min) / 60.0 + utc_offset
    set_ = (solar_noon_utc + ha0_min) / 60.0 + utc_offset
    return rise % 24.0, set_ % 24.0


def _format_hours(hours):
    if hours is None or hours < 0:
        return "—"
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h, m = h + 1, 0
    return "%02d:%02d" % (h % 24, m)


def lm_sun_update(self, context):
    """Recompute position data and aim the sun object."""
    az, el, az_rad, el_rad = _lm_sun_dir(self)

    rise, set_ = _sunrise_sunset(self.year, self.month, self.day,
                                 self.latitude, self.longitude, self.utc_offset)
    self["sun_elevation"] = el
    self["sun_azimuth"] = az
    self["sunrise"] = rise if rise is not None else -1.0
    self["sunset"] = set_ if set_ is not None else -1.0

    obj = self.sun_object
    if obj is None or obj.type != 'LIGHT':
        return
    direction = Vector((math.sin(az_rad) * math.cos(el_rad),
                        math.cos(az_rad) * math.cos(el_rad),
                        math.sin(el_rad)))
    rot = (-direction).to_track_quat('-Z', 'Y').to_euler()
    if obj.data is not None and obj.data.type == 'SUN':
        # Sun light is directional — placement doesn't affect anything,
        # moving it would only confuse the user
        obj.rotation_euler = rot
    else:
        obj.location = direction * self.sun_distance
        obj.rotation_euler = rot


def _lm_sun_dir(props):
    az, el = sun_azimuth_elevation(
        props.year, props.month, props.day, props.time_hours,
        props.latitude, props.longitude, props.utc_offset)
    az = (az + props.north_offset) % 360.0
    return az, el, math.radians(az), math.radians(el)


def _sun_elev_get(self):
    return self.get("sun_elevation", 0.0)


class LM_SunSettings(PropertyGroup):
    sun_object: PointerProperty(
        name="Sun",
        type=bpy.types.Object,
        description="Sun light to aim",
    )
    time_hours: FloatProperty(
        name="Time", min=0.0, max=24.0, default=12.0, subtype='TIME',
        update=lm_sun_update,
        description="Local time of day — keyframe it to animate the day")
    day: IntProperty(name="Day", min=1, max=31, default=21, update=lm_sun_update)
    month: IntProperty(name="Month", min=1, max=12, default=6, update=lm_sun_update)
    year: IntProperty(name="Year", min=1900, max=2100, default=2026,
                      update=lm_sun_update)
    latitude: FloatProperty(name="Latitude", min=-90.0, max=90.0, default=55.75,
                            update=lm_sun_update,
                            description="Degrees; positive is north")
    longitude: FloatProperty(name="Longitude", min=-180.0, max=180.0, default=37.62,
                             update=lm_sun_update,
                             description="Degrees; positive is east")
    utc_offset: FloatProperty(name="UTC Offset", min=-12.0, max=14.0, default=3.0,
                              update=lm_sun_update,
                              description="Time zone offset from UTC in hours")
    north_offset: FloatProperty(
        name="North Offset", min=0.0, max=360.0, default=0.0, subtype='ANGLE',
        update=lm_sun_update,
        description="Rotate the whole setup: where north is in the scene")
    sun_distance: FloatProperty(
        name="Distance", min=0.1, default=100.0, unit='LENGTH',
        update=lm_sun_update,
        description="Placement of non-sun lights; sun lamps only rotate")
    # read-only computed values (written by lm_sun_update)
    sun_elevation: FloatProperty(get=_sun_elev_get)
    sun_azimuth: FloatProperty(get=lambda self: self.get("sun_azimuth", 0.0))
    sunrise: FloatProperty(get=lambda self: self.get("sunrise", -1.0))
    sunset: FloatProperty(get=lambda self: self.get("sunset", -1.0))


@persistent
def sun_frame_handler(scene):
    """Re-aim the sun on frame changes — animates the day when Time is keyed."""
    try:
        if bpy.app.is_job_running("RENDER") or bpy.app.is_job_running("OBJECT_BAKE"):
            return
        props = scene.lm_sun
        if props.sun_object is not None:
            lm_sun_update(props, None)
    except Exception:
        pass


class LM_OT_sun_preset(bpy.types.Operator):
    """Set the time to a classic lighting moment."""
    bl_idname = "light_manager.sun_preset"
    bl_label = "Sun Preset"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(
        name="Preset",
        items=[
            ('NOON', "Noon", "Solar noon — 12:00"),
            ('GOLDEN', "Golden Hour", "One hour before sunset"),
            ('SUNSET', "Sunset", "The sunset moment"),
        ],
        default='NOON',
    )

    def execute(self, context):
        props = context.scene.lm_sun
        if self.preset == 'NOON':
            props.time_hours = 12.0
        else:
            sunset = props.get("sunset", -1.0)
            if sunset < 0:
                self.report({'WARNING'}, "No sunset for this date/location")
                return {'CANCELLED'}
            props.time_hours = sunset if self.preset == 'SUNSET' else (sunset - 1.0) % 24.0
        return {'FINISHED'}


class LM_PT_SunPanel(bpy.types.Panel):
    bl_label = "Sun"
    bl_idname = "LM_PT_sun_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LAMPOCHKA"
    bl_parent_id = "LM_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        sun = context.scene.lm_sun

        col = layout.column(align=True)
        col.prop(sun, "sun_object")

        col = layout.column(align=True)
        col.prop(sun, "time_hours", text="Time")
        row = col.row(align=True)
        row.prop(sun, "day")
        row.prop(sun, "month")
        row.prop(sun, "year")
        row = col.row(align=True)
        row.prop(sun, "latitude")
        row.prop(sun, "longitude")
        row = col.row(align=True)
        row.prop(sun, "utc_offset")
        row.prop(sun, "north_offset")
        col.prop(sun, "sun_distance")

        row = layout.row(align=True)
        row.operator("light_manager.sun_preset", text="Noon").preset = 'NOON'
        row.operator("light_manager.sun_preset", text="Golden").preset = 'GOLDEN'
        row.operator("light_manager.sun_preset", text="Sunset").preset = 'SUNSET'

        col = layout.column(align=True)
        col.label(text="Elevation: %.1f°   Azimuth: %.1f°"
                  % (sun.sun_elevation, sun.sun_azimuth))
        col.label(text="Sunrise %s   Sunset %s"
                  % (_format_hours(sun.sunrise), _format_hours(sun.sunset)))

        box = layout.box()
        col = box.column(align=True)
        col.label(text="Animate: keyframe Time —", icon='ANIM')
        col.label(text="the sun follows every frame")


# ---------------------------------------------------------------------------
#  Gobo — texture projection for spot lights
# ---------------------------------------------------------------------------

GOBO_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp')
_gobo_pcoll = None        # preview collection, created in register()
_gobo_enum_cache = []     # dynamic enum items must outlive the callback
_gobo_cache_folder = None

LM_GOBO_TEXCOORD = 'LM Gobo TexCoord'
LM_GOBO_MAPPING = 'LM Gobo Mapping'
LM_GOBO_IMAGE = 'LM Gobo'
LM_GOBO_MIX = 'LM Gobo Mix'


def gobo_enum_items(self, context):
    """Dynamic enum items (with thumbnails) for gobo images in the folder."""
    global _gobo_cache_folder
    folder = self.gobo_folder

    if _gobo_cache_folder == folder and _gobo_enum_cache:
        return _gobo_enum_cache

    if _gobo_pcoll is not None and _gobo_cache_folder != folder:
        _gobo_pcoll.clear()

    _gobo_enum_cache.clear()
    _gobo_cache_folder = folder

    if not folder or not os.path.isdir(folder) or _gobo_pcoll is None:
        return _gobo_enum_cache

    try:
        files = sorted(f for f in os.listdir(folder)
                       if f.lower().endswith(GOBO_EXTENSIONS))
    except OSError:
        return _gobo_enum_cache

    for filename in files:
        filepath = os.path.join(folder, filename)
        name = os.path.splitext(filename)[0]
        try:
            thumb = _gobo_pcoll.load(filepath, filepath, 'IMAGE').icon_id
        except Exception:
            thumb = 'TEXTURE'
        _gobo_enum_cache.append(
            (filepath, name, filepath, thumb, len(_gobo_enum_cache)))

    return _gobo_enum_cache


def update_gobo_transform(self, context):
    """Write rotation/scale of the panel into the active light's gobo mapping."""
    try:
        obj = getattr(context, "active_object", None)
        light = get_obj_light(obj) if obj is not None else None
        if light is None or not light.use_nodes or light.node_tree is None:
            return
        node = light.node_tree.nodes.get(LM_GOBO_MAPPING)
        if node is None or node.type != 'MAPPING':
            return
        node.inputs['Rotation'].default_value[2] = math.radians(self.rotation)
        s = max(0.01, self.scale)
        node.inputs['Scale'].default_value = (s, s, s)
    except Exception:
        pass


class LM_GoboSettings(PropertyGroup):
    gobo_folder: StringProperty(
        name="Gobo Folder",
        subtype='DIR_PATH',
        description="Folder containing gobo textures",
    )
    selected_gobo: EnumProperty(
        name="Gobo",
        items=gobo_enum_items,
        description="Gobo textures found in the folder",
    )
    rotation: FloatProperty(
        name="Rotation", min=0.0, max=360.0, default=0.0,
        update=update_gobo_transform,
        description="Rotation of the projected texture (degrees)",
    )
    scale: FloatProperty(
        name="Scale", min=0.05, max=20.0, default=1.0,
        update=update_gobo_transform,
        description="Scale of the projected texture",
    )


def _gobo_light_nodes(light):
    """(nodes, links, emission, output) for a node light, or (None, ...)."""
    if not light.use_nodes or light.node_tree is None:
        return None, None, None, None
    nodes = light.node_tree.nodes
    links = light.node_tree.links
    emission = next((n for n in nodes if n.type == 'EMISSION'), None)
    output = next((n for n in nodes if n.type == 'OUTPUT_LIGHT'), None)
    return nodes, links, emission, output


def _gobo_cleanup_orphans(nodes):
    """Drop gobo texture-coordinate chains left without links."""
    for node in list(nodes):
        if (node.type == 'TEX_COORD'
                and not any(out.links for out in node.outputs)
                and node.name == LM_GOBO_TEXCOORD):
            nodes.remove(node)


def _gobo_apply_image(context, filepath):
    """Build or update the gobo projection chain on the active spot light."""
    obj = context.active_object
    light = get_obj_light(obj)
    if light is None:
        return {'CANCELLED'}

    image = bpy.data.images.load(filepath, check_existing=True)
    nodes, links, emission, output = _gobo_light_nodes(light)

    if emission is None or output is None:
        # No usable light chain — build a clean gobo setup
        light.use_nodes = True
        nodes = light.node_tree.nodes
        links = light.node_tree.links
        nodes.clear()
        texcoord = nodes.new('ShaderNodeTexCoord')
        texcoord.name = LM_GOBO_TEXCOORD
        texcoord.label = LM_GOBO_TEXCOORD
        mapping = nodes.new('ShaderNodeMapping')
        mapping.name = LM_GOBO_MAPPING
        mapping.label = LM_GOBO_MAPPING
        tex_image = nodes.new('ShaderNodeTexImage')
        tex_image.name = LM_GOBO_IMAGE
        tex_image.label = LM_GOBO_IMAGE
        tex_image.image = image
        emission = nodes.new('ShaderNodeEmission')
        output = nodes.new('ShaderNodeOutputLight')

        texcoord.location = (-600, 0)
        mapping.location = (-400, 0)
        tex_image.location = (-200, 0)
        emission.location = (0, 0)
        output.location = (200, 0)

        links.new(texcoord.outputs['Generated'], mapping.inputs['Vector'])
        links.new(mapping.outputs['Vector'], tex_image.inputs['Vector'])
        links.new(tex_image.outputs['Color'], emission.inputs['Color'])
        links.new(emission.outputs['Emission'], output.inputs['Surface'])
    else:
        # Existing chain — insert (or update) the multiply mix before Emission Color
        tex_image = nodes.get(LM_GOBO_IMAGE)
        if tex_image is None or tex_image.type != 'TEX_IMAGE':
            texcoord = nodes.new('ShaderNodeTexCoord')
            texcoord.name = LM_GOBO_TEXCOORD
            texcoord.label = LM_GOBO_TEXCOORD
            mapping = nodes.new('ShaderNodeMapping')
            mapping.name = LM_GOBO_MAPPING
            mapping.label = LM_GOBO_MAPPING
            tex_image = nodes.new('ShaderNodeTexImage')
            tex_image.name = LM_GOBO_IMAGE
            tex_image.label = LM_GOBO_IMAGE
            texcoord.location = (-600, emission.location.y)
            mapping.location = (-400, emission.location.y)
            tex_image.location = (-200, emission.location.y)
            links.new(texcoord.outputs['Generated'], mapping.inputs['Vector'])
            links.new(mapping.outputs['Vector'], tex_image.inputs['Vector'])
        tex_image.image = image

        mix = nodes.get(LM_GOBO_MIX)
        color_in = emission.inputs['Color']
        if mix is None or mix.type != 'MIX_RGB':
            if mix is not None:
                nodes.remove(mix)
            mix = nodes.new('ShaderNodeMixRGB')
            mix.name = LM_GOBO_MIX
            mix.label = LM_GOBO_MIX
            mix.blend_type = 'MULTIPLY'
            mix.location = (color_in.links[0].from_node.location.x + 100,
                            emission.location.y - 200) if color_in.is_linked \
                else (emission.location.x - 100, emission.location.y - 200)
            if color_in.is_linked:
                src = color_in.links[0].from_socket
            else:
                src = None
                mix.inputs['Color1'].default_value = tuple(
                    color_in.default_value[:3]) + (1.0,)
            links.new(tex_image.outputs['Color'], mix.inputs['Color2'])
            links.new(mix.outputs['Color'], color_in)
            if src is not None:
                links.new(src, mix.inputs['Color1'])
            mix.inputs['Fac'].default_value = 1.0

    gobo = context.scene.lm_gobo
    mapping = nodes.get(LM_GOBO_MAPPING)
    if mapping is not None and mapping.type == 'MAPPING':
        mapping.inputs['Rotation'].default_value[2] = math.radians(gobo.rotation)
        s = max(0.01, gobo.scale)
        mapping.inputs['Scale'].default_value = (s, s, s)
    return {'FINISHED'}


def _gobo_remove(context):
    obj = context.active_object
    light = get_obj_light(obj)
    if light is None or not light.use_nodes or light.node_tree is None:
        return {'FINISHED'}
    nodes = light.node_tree.nodes
    links = light.node_tree.links

    # Restore what fed the mix before removing it
    mix = nodes.get(LM_GOBO_MIX)
    src = None
    mix_color = None
    if mix is not None and mix.type == 'MIX_RGB':
        color1 = mix.inputs['Color1']
        if color1.is_linked:
            src = color1.links[0].from_socket
        else:
            mix_color = tuple(color1.default_value[:3])
        emission = next((n for n in nodes if n.type == 'EMISSION'), None)
        nodes.remove(mix)
        if emission is not None:
            if src is not None:
                links.new(src, emission.inputs['Color'])
            else:
                emission.inputs['Color'].default_value = tuple(mix_color) + (1.0,)

    for node in list(nodes):
        if node.name in (LM_GOBO_IMAGE, LM_GOBO_MAPPING, LM_GOBO_TEXCOORD):
            nodes.remove(node)
    _gobo_cleanup_orphans(nodes)
    return {'FINISHED'}


class LM_OT_gobo_pick_folder(bpy.types.Operator, ImportHelper):
    """Pick a folder containing gobo textures."""
    bl_idname = "light_manager.gobo_pick_folder"
    bl_label = "Pick Gobo Folder"
    bl_options = {'REGISTER'}

    filename_ext = ""
    use_filter_folder = True

    def execute(self, context):
        folder = os.path.dirname(self.filepath)
        context.scene.lm_gobo.gobo_folder = folder
        prefs = get_lm_prefs(context)
        if prefs is not None:
            prefs.gobo_folder = folder
        return {'FINISHED'}


class LM_OT_gobo_apply(bpy.types.Operator):
    """Project the selected gobo texture from the active spot light."""
    bl_idname = "light_manager.gobo_apply"
    bl_label = "Apply Gobo"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.type == 'LIGHT'
                and obj.data.type == 'SPOT')

    def execute(self, context):
        gobo = context.scene.lm_gobo
        filepath = gobo.selected_gobo
        if not filepath or not os.path.isfile(filepath):
            self.report({'ERROR'}, "No valid gobo texture selected")
            return {'CANCELLED'}
        rv = _gobo_apply_image(context, filepath)
        if rv == {'FINISHED'}:
            self.report({'INFO'},
                        "Gobo applied: " + os.path.basename(filepath))
        return rv


class LM_OT_gobo_remove(bpy.types.Operator):
    """Remove the gobo setup from the active light."""
    bl_idname = "light_manager.gobo_remove"
    bl_label = "Remove Gobo"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'LIGHT'

    def execute(self, context):
        return _gobo_remove(context)


class LM_PT_GoboPanel(bpy.types.Panel):
    bl_label = "Gobo"
    bl_idname = "LM_PT_gobo_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LAMPOCHKA"
    bl_parent_id = "LM_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        gobo = context.scene.lm_gobo

        row = layout.row(align=True)
        row.prop(gobo, "gobo_folder", text="")
        row.operator("light_manager.gobo_pick_folder", text="", icon='FILE_FOLDER')

        if not gobo.gobo_folder or not os.path.isdir(gobo.gobo_folder):
            layout.label(text="Pick a folder with gobo textures", icon='INFO')
            return

        # Trigger enum rebuild if needed, then check what we have
        _ = gobo.selected_gobo
        if not _gobo_enum_cache:
            layout.label(text="No textures in folder", icon='INFO')
            return

        if context.engine != 'CYCLES':
            layout.label(text="Gobo works best in Cycles", icon='ERROR')

        obj = context.active_object
        light = get_obj_light(obj) if obj is not None else None
        if light is None or light.type != 'SPOT':
            layout.label(text="Pick a spot light (gobo needs a cone)", icon='INFO')

        layout.template_icon_view(gobo, "selected_gobo", show_labels=True, scale=4)

        if gobo.selected_gobo:
            name = os.path.splitext(os.path.basename(gobo.selected_gobo))[0]
            layout.label(text=name, icon='TEXTURE')

        col = layout.column(align=True)
        col.operator("light_manager.gobo_apply", icon='TEXTURE')
        col.operator("light_manager.gobo_remove", text="Remove Gobo", icon='X')
        col.separator()
        col.prop(gobo, "rotation")
        col.prop(gobo, "scale")


# ---------------------------------------------------------------------------
#  Light / shadow linking — pick receivers & blockers by clicking
# ---------------------------------------------------------------------------

def _viewport_ray(context, coord):
    """Cast a ray from the viewport through the mouse; returns
    (location, normal, object) or None."""
    from bpy_extras import view3d_utils
    region = getattr(context, "region", None)
    rv3d = getattr(context, "region_data", None)
    if region is None or rv3d is None:
        return None
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    # context.depsgraph only exists in some handler contexts — ask for the
    # evaluated one explicitly (works from operators and modals)
    depsgraph = context.evaluated_depsgraph_get()
    result = context.scene.ray_cast(depsgraph, origin, direction)
    if not result[0]:
        return None
    return result[1], result[2], result[4]


def _has_light_linking(obj):
    """Capability check across Blender versions: 5.x keeps the collections
    on the object, 4.x on the light data (as a lazily-created pointer)."""
    try:
        if 'light_linking' in obj.bl_rna.properties:
            return True
    except Exception:
        pass
    try:
        return (obj.data is not None
                and 'light_linking' in obj.data.bl_rna.properties)
    except Exception:
        return False


def _linking_holder(obj):
    """Whatever holds receiver/blocker collections: Object.light_linking
    (5.x) or light data light_linking (4.x), or None."""
    holder = getattr(obj, "light_linking", None)
    if holder is not None and hasattr(holder, "receiver_collection"):
        return holder
    data = obj.data
    if data is not None:
        holder = getattr(data, "light_linking", None)
        if holder is not None and hasattr(holder, "receiver_collection"):
            return holder
    return None


def _link_collection(obj, which):
    """The receiver/blocker collection of the light object, creating the
    linking datablock and the collection itself if needed."""
    holder = _linking_holder(obj)
    if holder is None:
        if not _has_light_linking(obj):
            return None
        new_ll = getattr(bpy.data, "light_linkings", None)
        if new_ll is None:
            return None
        holder = new_ll.new("LM Linking " + obj.name)
        obj.data.light_linking = holder
    coll = getattr(holder, which + "_collection", None)
    if coll is None:
        coll = bpy.data.collections.new(
            "LM %s %s" % (which.capitalize(), obj.name))
        setattr(holder, which + "_collection", coll)
    return coll


def _link_toggle(obj, which, target):
    """Link/unlink an object as receiver or blocker of the light."""
    coll = _link_collection(obj, which)
    if coll is None:
        return False
    if coll.objects.get(target.name) is not None:
        coll.objects.unlink(target)
        return False
    coll.objects.link(target)
    return True


def _linking_snapshot(obj):
    snap = {}
    for which in ("receiver", "blocker"):
        holder = _linking_holder(obj)
        coll = getattr(holder, which + "_collection", None) if holder else None
        snap[which] = [ob.name for ob in coll.objects] if coll is not None else []
    return snap


def _linking_restore(obj, snap):
    for which in ("receiver", "blocker"):
        holder = _linking_holder(obj)
        coll = getattr(holder, which + "_collection", None) if holder else None
        if coll is None:
            continue
        for ob in list(coll.objects):
            coll.objects.unlink(ob)
        for name in snap[which]:
            ob = bpy.data.objects.get(name)
            if ob is not None:
                coll.objects.link(ob)


def _linking_count(obj, which):
    holder = _linking_holder(obj)
    coll = getattr(holder, which + "_collection", None) if holder else None
    return len(coll.objects) if coll is not None else 0


class LM_OT_link_pick(bpy.types.Operator):
    """Click objects in the viewport to link/unlink them as receivers or blockers."""
    bl_idname = "light_manager.link_pick"
    bl_label = "Pick Linking Targets"
    bl_options = {'REGISTER'}

    mode: EnumProperty(
        name="Mode",
        items=[
            ('RECEIVER', "Receivers", "Objects lit by this light"),
            ('BLOCKER', "Blockers", "Objects casting shadows from this light"),
        ],
        default='RECEIVER',
    )
    light_name: StringProperty()

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'LIGHT':
            return False
        return _has_light_linking(obj)

    def invoke(self, context, event):
        obj = bpy.data.objects.get(self.light_name) or context.active_object
        self._light = obj
        self._which = "receiver" if self.mode == 'RECEIVER' else "blocker"
        self._snapshot = _linking_snapshot(obj)
        self._set_status(context, "click objects to link / unlink")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        light = self._light
        if (light is None or light.name not in context.scene.objects):
            self._set_status(context, None)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            ray = _viewport_ray(context, (event.mouse_region_x, event.mouse_region_y))
            if ray is None:
                return {'RUNNING_MODAL'}
            target = ray[2]
            if target is None or target.type == 'LIGHT' or target == light:
                return {'RUNNING_MODAL'}
            linked = _link_toggle(light, self._which, target)
            word = "linked" if linked else "unlinked"
            self._set_status(context, "%s %s" % (target.name, word))
            return {'RUNNING_MODAL'}
        if event.type == 'RET' and event.value == 'PRESS':
            self._set_status(context, None)
            return {'FINISHED'}
        if ((event.type == 'RIGHTMOUSE' and event.value == 'PRESS')
                or event.type == 'ESC'):
            _linking_restore(light, self._snapshot)
            self._set_status(context, None)
            return {'CANCELLED'}
        if event.type in {'G', 'R', 'S'} and event.value == 'PRESS':
            # keep the picked links and let the transform tools through
            self._set_status(context, None)
            return {'FINISHED'}
        if event.type in {'MIDDLEMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}  # picking: swallow so the scene stays still

    def _set_status(self, context, extra):
        if extra is None:
            text = None
        else:
            text = ("LAMPOCHKA %s: %s  |  Enter — done, Esc/RMB — cancel"
                    % (self.mode.capitalize(), extra))
        try:
            context.workspace.status_text_set(text)
        except Exception:
            pass
        try:
            context.area.header_text_set(text)
        except Exception:
            pass


class LM_OT_link_clear(bpy.types.Operator):
    """Unlink all receivers/blockers from the active light."""
    bl_idname = "light_manager.link_clear"
    bl_label = "Clear Linking"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=[
            ('RECEIVER', "Receivers", "Clear light linking"),
            ('BLOCKER', "Blockers", "Clear shadow linking"),
            ('ALL', "All", "Clear both"),
        ],
        default='ALL',
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.type == 'LIGHT'
                and _has_light_linking(obj))

    def execute(self, context):
        obj = context.active_object
        whiches = ("receiver", "blocker") if self.mode == 'ALL' else (
            "receiver",) if self.mode == 'RECEIVER' else ("blocker",)
        for which in whiches:
            holder = _linking_holder(obj)
            coll = getattr(holder, which + "_collection", None) if holder else None
            if coll is None:
                continue
            for ob in list(coll.objects):
                coll.objects.unlink(ob)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
#  Interactive placement — move a light by clicking surfaces
# ---------------------------------------------------------------------------

def _light_size_key(light):
    """Name of the light data property holding the light's size/radius.
    Several candidates per type — the name changed across Blender versions."""
    ldata = light.data
    candidates = {
        'AREA': ("size",),
        'POINT': ("shadow_soft_size", "radius"),
        'SPOT': ("shadow_soft_size", "radius"),
        'SUN': ("angle",),
    }.get(ldata.type, ())
    for key in candidates:
        if hasattr(ldata, key):
            return key
    return None


class LM_OT_place_toggle(bpy.types.Operator):
    """Switch placement mode for this light: pressed — the light follows
    the cursor in the viewport; released — nothing runs."""
    bl_idname = "light_manager.place_toggle"
    bl_label = "Placement Mode"
    bl_options = {'REGISTER', 'UNDO'}

    light_name: StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.light_name)
        if obj is None or obj.type != 'LIGHT':
            return {'CANCELLED'}
        if obj.lm_place_enable:
            # button released — the running session sees the flag and stops
            obj.lm_place_enable = False
            return {'FINISHED'}
        obj.lm_place_enable = True
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.light_manager.place_light('INVOKE_DEFAULT')
        return {'FINISHED'}


class LM_OT_place_light(bpy.types.Operator):
    """Placement mode: while the cursor button is pressed the light follows
    the cursor freely (Alt — snap to surfaces). G applies / restarts like a
    transform operator. LMB/Enter applies, RMB/Esc resets the run."""
    bl_idname = "light_manager.place_light"
    bl_label = "Place Light"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        self._obj = context.active_object
        self._following = True
        self._remember_run()
        self._free_dist = self._initial_free_dist(context)
        self._set_status(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _remember_run(self):
        """Snapshot the transform at the start of every follow run."""
        self._run_location = tuple(self._obj.location)
        self._run_energy = self._obj.data.energy
        size_key = _light_size_key(self._obj)
        self._run_size = getattr(self._obj.data, size_key) if size_key else None

    def _initial_free_dist(self, context):
        from bpy_extras import view3d_utils
        region = getattr(context, "region", None)
        rv3d = getattr(context, "region_data", None)
        if region is None or rv3d is None:
            return 10.0
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (0, 0))
        return max(1.0, (self._obj.location - origin).length)

    def _move_to_ray(self, context, coord, snap=False, depth_factor=1.0):
        """Free flight along the view ray at the remembered depth.
        With snap=True (Alt held) the light sticks to the surface."""
        from bpy_extras import view3d_utils
        region = getattr(context, "region", None)
        rv3d = getattr(context, "region_data", None)
        if region is None or rv3d is None:
            return
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        if snap:
            hit = context.scene.ray_cast(
                context.evaluated_depsgraph_get(), origin, direction)
            if hit[0]:
                location, normal = hit[1], hit[2]
                self._free_dist = max(0.1, (location - origin).length)
                self._obj.location = location + normal * 0.001
                return
        self._free_dist = max(0.1, self._free_dist * depth_factor)
        self._obj.location = origin + direction * self._free_dist

    def modal(self, context, event):
        obj = self._obj
        if obj is None or obj.name not in context.scene.objects:
            self._set_status(context, False)
            return {'CANCELLED'}
        if obj.lm_place_enable is not True:
            # the cursor button is the only off switch — it was released
            self._set_status(context, False)
            return {'FINISHED'}

        if not self._following:
            # armed idle: only G restarts a run — every other event (UI
            # clicks, wheel zoom) passes through, nothing feels frozen
            if event.type == 'G' and event.value == 'PRESS':
                self._remember_run()
                self._following = True
                self._set_status(context)
                # consume the G: letting it through would also start the
                # native Grab on top of the follow run
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if self._following and event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._move_to_ray(context, (event.mouse_region_x, event.mouse_region_y),
                              snap=event.alt)
            return {'RUNNING_MODAL'}

        wheel_up = event.type in {'WHEELUPMOUSE', 'WHEELINMOUSE'}
        wheel_down = event.type in {'WHEELDOWNMOUSE', 'WHEELOUTMOUSE'}
        if self._following and (wheel_up or wheel_down):
            factor = 1.25 if wheel_up else 1.0 / 1.25
            if event.ctrl:
                self._move_to_ray(context, (event.mouse_region_x,
                                            event.mouse_region_y),
                                  depth_factor=factor)
            elif event.shift:
                size_key = _light_size_key(obj)
                if size_key:
                    value = getattr(obj.data, size_key) * factor
                    if value < 1e-4:
                        # a zero size would stay zero forever — start it off
                        value = 0.01 if factor > 1.0 else 0.0
                    if obj.data.type == 'SUN':
                        value = max(0.0, min(value, math.pi))
                    else:
                        value = max(0.0, value)
                    setattr(obj.data, size_key, value)
            else:
                obj.data.energy = max(0.0, obj.data.energy * factor)
            self._set_status(context)
            return {'RUNNING_MODAL'}

        if self._following and ((event.type == 'LEFTMOUSE' and event.value == 'PRESS')
                or (event.type == 'RET' and event.value == 'PRESS')):
            self._set_status(context, False)
            self._following = False
            return {'RUNNING_MODAL'}

        if self._following and ((event.type == 'RIGHTMOUSE' and event.value == 'PRESS')
                or event.type == 'ESC'):
            obj.location = self._run_location
            obj.data.energy = self._run_energy
            size_key = _light_size_key(obj)
            if size_key and self._run_size is not None:
                setattr(obj.data, size_key, self._run_size)
            self._set_status(context, False)
            self._following = False
            return {'RUNNING_MODAL'}

        if event.type in {'MIDDLEMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}  # following: swallow so UI doesn't react

    def _set_status(self, context, on=True):
        if not on:
            text = None
        else:
            size_key = _light_size_key(self._obj)
            size_val = getattr(self._obj.data, size_key, None) if size_key else None
            size_txt = (" (%.2f)" % size_val) if size_val is not None else " — n/a"
            if self._following:
                text = ("LAMPOCHKA place: LMB/G — apply  |  RMB/Esc — reset  |  "
                        "Alt — snap to surface  |  Wheel — power (%.0f)  |  "
                        "Shift+Wheel — size%s  |  Ctrl+Wheel — depth (%.1f m)"
                        % (self._obj.data.energy, size_txt, self._free_dist))
            else:
                text = "LAMPOCHKA place [armed]: G — place the light again"
        try:
            context.window.cursor_modal_set(
                'PAINT_BRUSH' if on else 'DEFAULT')
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

        # Placement mode: pressed — the light follows the cursor
        op = row.operator("light_manager.place_toggle", text="", icon='CURSOR',
                          depress=bool(getattr(obj, "lm_place_enable", False)))
        op.light_name = obj.name

        # Visibility icons (operators)
        op = row.operator("light_manager.toggle_visibility", text="",
                          icon='HIDE_OFF' if not obj.hide_viewport else 'HIDE_ON')
        op.index = full_idx
        op = row.operator("light_manager.toggle_render", text="",
                          icon='RESTRICT_RENDER_OFF' if not obj.hide_render else 'RESTRICT_RENDER_ON')
        op.index = full_idx
        # Delete this light (same trash button as in the settings)
        op = row.operator("light_manager.delete_light_row", text="", icon='TRASH')
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

        # Light / shadow linking (Blender 4.x)
        if _has_light_linking(obj):
            col.separator()
            op = col.operator("light_manager.link_pick", text="Light Linking: Pick",
                              icon='EYEDROPPER')
            op.mode = 'RECEIVER'
            op.light_name = obj.name
            op = col.operator("light_manager.link_pick", text="Shadow Linking: Pick",
                              icon='EYEDROPPER')
            op.mode = 'BLOCKER'
            op.light_name = obj.name
            row = col.row(align=True)
            op = row.operator("light_manager.link_clear", text="Clear Receivers")
            op.mode = 'RECEIVER'
            op = row.operator("light_manager.link_clear", text="Clear Blockers")
            op.mode = 'BLOCKER'

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

        # Carousel: one row of three cards — previous / active / next.
        # The active card's button is drawn pressed; arrows below step through.
        selected = hdri.selected_hdri
        cache = _hdri_enum_cache
        try:
            active = [item[0] for item in cache].index(selected)
        except ValueError:
            active = 0
        total = len(cache)
        row = layout.row(align=True)
        for offset in (-1, 0, 1):
            item = cache[(active + offset) % total]
            filepath, name, _desc, icon = item[0], item[1], item[2], item[3]
            col = row.column(align=True)
            if isinstance(icon, int):
                try:
                    col.template_icon(icon_value=icon, scale=4.5)
                except Exception:
                    pass
            short = name if len(name) <= 12 else name[:11] + "…"
            op = col.operator("light_manager.hdri_pick", text=short,
                              depress=(offset == 0))
            op.index = cache.index(item)

        row = layout.row(align=True)
        row.operator("light_manager.hdri_prev", text="", icon='TRIA_LEFT')
        if hdri.selected_hdri:
            name = os.path.splitext(os.path.basename(hdri.selected_hdri))[0]
            row.label(text=name, icon='WORLD')
        else:
            row.label(text="—")
        row.operator("light_manager.hdri_next", text="", icon='TRIA_RIGHT')

        col = layout.column(align=True)
        col.operator("light_manager.hdri_apply", icon='WORLD')
        col.operator("light_manager.hdri_clear", text="Clear HDRI", icon='X')
        col.separator()
        col.prop(hdri, "hide_from_camera", text="Hide from Camera", icon='HIDE_ON')
        if hdri.hide_from_camera:
            col.prop(hdri, "camera_color", text="Camera Color")
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


class LM_OT_delete_light_row(bpy.types.Operator):
    """Delete this light."""
    bl_idname = "light_manager.delete_light_row"
    bl_label = "Delete Light"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        lights = get_scene_lights(context)
        if 0 <= self.index < len(lights):
            obj = lights[self.index]
            settings = context.scene.lm_settings
            if settings.settings_light == obj.name:
                settings.settings_light = ""
            if settings.selected_index >= len(lights) - 1:
                settings.selected_index = -1
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
        rv = _hdri_apply_image(context, filepath)
        if rv == {'FINISHED'}:
            self.report({'INFO'},
                        "HDRI applied: " + os.path.basename(filepath))
        return rv


class LM_OT_hdri_pick(bpy.types.Operator):
    """Apply this HDRI to the world."""
    bl_idname = "light_manager.hdri_pick"
    bl_label = "Pick HDRI"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)

    def execute(self, context):
        if 0 <= self.index < len(_hdri_enum_cache):
            # the enum update callback applies the image
            context.scene.lm_hdri.selected_hdri = _hdri_enum_cache[self.index][0]
        return {'FINISHED'}


class LM_OT_hdri_prev(bpy.types.Operator):
    """Apply the previous HDRI from the folder."""
    bl_idname = "light_manager.hdri_prev"
    bl_label = "Previous HDRI"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return _hdri_cycle(context, -1)


class LM_OT_hdri_next(bpy.types.Operator):
    """Apply the next HDRI from the folder."""
    bl_idname = "light_manager.hdri_next"
    bl_label = "Next HDRI"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return _hdri_cycle(context, 1)


def _place_armed(context):
    """True while the Place Light cursor button is pressed on the active
    light — placement owns the viewport input then."""
    obj = getattr(context, "active_object", None)
    return (obj is not None and obj.type == 'LIGHT'
            and getattr(obj, "lm_place_enable", False) is True)


class LM_OT_hdri_shift_rmb(bpy.types.Operator):
    """Rotate the HDRI by dragging with Shift+RMB in the viewport."""
    bl_idname = "light_manager.hdri_shift_rmb"
    bl_label = "Rotate HDRI"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if _place_armed(context):
            return False  # placement mode owns the input while armed
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
            if (node.type == 'TEX_ENVIRONMENT'
                    or node.name in ('HDRI Mapping', LM_CAM_MIX, LM_CAM_PATH)):
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
        # "no environment": pitch black, zero strength
        background.inputs['Color'].default_value = (0.0, 0.0, 0.0, 1.0)
        background.inputs['Strength'].default_value = 0.0

        # Panel: strength back to its default, so the next Apply HDRI
        # comes in at full strength (the world itself stays black/0)
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
    LM_GoboSettings,
    LM_SunSettings,
    LM_AddonPreferences,
    LM_OT_select_light,
    LM_OT_toggle_visibility,
    LM_OT_toggle_render,
    LM_OT_toggle_all_visibility,
    LM_OT_toggle_all_render,
    LM_OT_add_light,
    LM_OT_delete_light,
    LM_OT_delete_light_row,
    LM_OT_duplicate_light,
    LM_OT_move_light,
    LM_OT_toggle_settings,
    LM_OT_toggle_transform,
    LM_OT_hdri_pick_folder,
    LM_OT_hdri_pick,
    LM_OT_hdri_apply,
    LM_OT_hdri_prev,
    LM_OT_hdri_next,
    LM_OT_hdri_clear,
    LM_OT_hdri_shift_rmb,
    LM_OT_ies_pick_folder,
    LM_OT_ies_apply,
    LM_OT_ies_remove,
    LM_OT_gobo_pick_folder,
    LM_OT_gobo_apply,
    LM_OT_gobo_remove,
    LM_OT_link_pick,
    LM_OT_link_clear,
    LM_OT_place_toggle,
    LM_OT_place_light,
    LM_OT_sun_preset,
    LM_PT_MainPanel,
    LM_PT_HDRIPanel,
    LM_PT_IESPanel,
    LM_PT_GoboPanel,
    LM_PT_SunPanel,
)


def register():
    global _hdri_pcoll, _ies_pcoll, _gobo_pcoll
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lm_settings = bpy.props.PointerProperty(type=LM_SceneSettings)
    bpy.types.Scene.lm_hdri = bpy.props.PointerProperty(type=LM_HDRISettings)
    bpy.types.Scene.lm_ies = bpy.props.PointerProperty(type=LM_IESSettings)
    bpy.types.Scene.lm_gobo = bpy.props.PointerProperty(type=LM_GoboSettings)
    bpy.types.Scene.lm_sun = bpy.props.PointerProperty(type=LM_SunSettings)
    # Per-object Kelvin controls (stored as ID props on the light object)
    bpy.types.Object.lm_use_temperature = bpy.props.BoolProperty(
        name="Kelvin",
        description="Drive light color from blackbody temperature",
        default=False,
        update=lm_use_temperature_update,
    )
    # Per-light "Place with G" arming toggle (keymap is always registered)
    bpy.types.Object.lm_place_enable = bpy.props.BoolProperty(
        name="Place with G",
        description="Placement mode master switch (manual only). ON: the "
                    "light follows the cursor freely, Alt snaps it to "
                    "surfaces, G applies/restarts like a transform operator, "
                    "wheel — power, Shift+wheel — size, Ctrl+wheel — depth. "
                    "OFF: nothing runs, G is the native Grab again",
        default=False,
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
    # Sun animation: re-aim on frame changes
    if sun_frame_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(sun_frame_handler)
    previews = getattr(bpy.utils, "previews", None)  # absent in background mode
    if previews is not None:
        if _hdri_pcoll is None:
            _hdri_pcoll = previews.new()
        if _ies_pcoll is None:
            _ies_pcoll = previews.new()
        if _gobo_pcoll is None:
            _gobo_pcoll = previews.new()
    # Shift+RMB HDRI rotation keymap (always on, operator poll gates the toggle)
    register_shift_rmb_keymap()


def unregister():
    global _hdri_pcoll, _ies_pcoll, _gobo_pcoll
    # Remove the Shift+RMB keymap
    unregister_shift_rmb_keymap()
    # Remove sync handler
    if sync_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sync_handler)
    # Remove load handler
    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)
    # Remove sun frame handler
    if sun_frame_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(sun_frame_handler)
    previews = getattr(bpy.utils, "previews", None)
    for name in ("_hdri_pcoll", "_ies_pcoll", "_gobo_pcoll"):
        pcoll = globals()[name]
        if pcoll is not None and previews is not None:
            try:
                previews.remove(pcoll)
            except Exception:
                pass
        globals()[name] = None
    _hdri_enum_cache.clear()
    _ies_enum_cache.clear()
    _gobo_enum_cache.clear()
    global _hdri_cache_folder, _ies_cache_folder, _gobo_cache_folder
    _hdri_cache_folder = None
    _ies_cache_folder = None
    _gobo_cache_folder = None
    try:
        del bpy.types.Scene.lm_gobo
    except Exception:
        pass
    try:
        del bpy.types.Scene.lm_hdri
    except Exception:
        pass
    try:
        del bpy.types.Scene.lm_ies
    except Exception:
        pass
    try:
        del bpy.types.Scene.lm_sun
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
    try:
        del bpy.types.Object.lm_place_enable
    except Exception:
        pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
