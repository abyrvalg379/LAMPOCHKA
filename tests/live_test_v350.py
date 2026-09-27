# Live headless smoke for v3.5 (Blender 5.2): sun sky sync, kelvin from
# elevation, collapse toggle, update_checker wiring.
import os
import sys
import types
import math
import traceback

EXT = r"D:\AI\ZCode\Project\LAMPOCHKA\work\extension\__init__.py"


def _die(code):
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # blender 5.2 -b hangs on regular exit in this setup


try:
    import bpy
    import importlib.util

    spec = importlib.util.spec_from_file_location("lampochka", EXT)
    m = importlib.util.module_from_spec(spec)
    sys.modules["lampochka"] = m
    spec.loader.exec_module(m)

    m.register()

    scene = bpy.context.scene
    prefs = types.SimpleNamespace(hdri_folder="", ies_folder="",
                                  gobo_folder="", presets_folder="",
                                  update_auto_check=True, update_checking=False,
                                  update_result="", update_url="")
    m.get_lm_prefs = lambda ctx: prefs
    # update_checker resolves prefs through preferences.addons — absent in
    # background; stub its accessor to the same namespace
    try:
        import lampochka
        uc = lampochka.update_checker
        uc._prefs = lambda: prefs
        uc._local_version_tuple = lambda: (3, 5, 0)
    except Exception as e:
        print("update_checker stub failed:", e)

    fails = []

    def check(name, cond, detail=""):
        print(("  OK " if cond else "  FAIL ") + name
              + ("" if cond else "  [" + str(detail) + "]"))
        if not cond:
            fails.append(name)

    # --- version + registration
    check("version 3.5.0 in manifest", m._ADDON_VERSION == "3.5.0")
    check("toggle_lights registered",
          hasattr(bpy.ops.light_manager, "toggle_lights"))
    check("check_updates registered",
          hasattr(bpy.ops.light_manager, "check_updates"))
    check("open_releases registered",
          hasattr(bpy.ops.light_manager, "open_releases"))
    check("lights_open prop exists",
          hasattr(scene.lm_settings, "lights_open")
          and scene.lm_settings.lights_open is True)
    check("sun props exist",
          hasattr(scene.lm_sun, "use_sky_sync")
          and hasattr(scene.lm_sun, "kelvin_from_elevation"))

    # --- collapse toggle operator
    scene.lm_settings.lights_open = True
    bpy.ops.light_manager.toggle_lights()
    check("toggle collapses", scene.lm_settings.lights_open is False)
    bpy.ops.light_manager.toggle_lights()
    check("toggle expands", scene.lm_settings.lights_open is True)

    # --- sun: kelvin from elevation (fresh 5.2 lights are ALWAYS nodal,
    # so the blackbody branch is the one a real user exercises; the plain
    # light.color branch is covered by the mock test for old files)
    light_data = bpy.data.lights.new("Sun", type='SUN')
    sun_obj = bpy.data.objects.new("Sun", light_data)
    scene.collection.objects.link(sun_obj)
    scene.lm_sun.sun_object = sun_obj
    scene.lm_sun.latitude = 55.75
    scene.lm_sun.longitude = 37.62
    scene.lm_sun.utc_offset = 3.0
    scene.lm_sun.day = 21
    scene.lm_sun.month = 6
    scene.lm_sun.year = 2026
    scene.lm_sun.time_hours = 5.0   # low sun
    m.lm_sun_update(scene.lm_sun, None)
    tree = light_data.node_tree
    author = list(next(n for n in tree.nodes
                       if n.type == 'EMISSION').inputs['Color'].default_value)
    scene.lm_sun.kelvin_from_elevation = True
    m.lm_sun_update(scene.lm_sun, None)
    bb = next((n for n in tree.nodes
               if n.type == 'BLACKBODY' and n.name == "LM Sun Blackbody"), None)
    em = next(n for n in tree.nodes if n.type == 'EMISSION')
    check("kelvin: blackbody created and linked", bb is not None
          and em.inputs['Color'].is_linked
          and em.inputs['Color'].links[0].from_node == bb)
    check("kelvin: low sun is warm",
          bb.inputs[0].default_value < 4000.0, str(bb.inputs[0].default_value))
    color_before = list(light_data.color)
    scene.lm_sun.time_hours = 12.0
    m.lm_sun_update(scene.lm_sun, None)
    check("kelvin: noon is neutral",
          bb.inputs[0].default_value > 6000.0, str(bb.inputs[0].default_value))
    check("kelvin: nodal branch never touches light.color",
          list(light_data.color) == color_before)
    scene.lm_sun.kelvin_from_elevation = False
    em = next(n for n in tree.nodes if n.type == 'EMISSION')
    check("kelvin off: unlinks and restores author color",
          not em.inputs['Color'].is_linked
          and all(abs(a - b) < 1e-6
                  for a, b in zip(em.inputs['Color'].default_value, author)))
    check("kelvin off: blackbody removed",
          not any(n.type == 'BLACKBODY' for n in tree.nodes))

    # --- sun: sky texture sync
    world = bpy.data.worlds.new("LMTestWorld")
    world.use_nodes = True
    scene.world = world
    nt = world.node_tree
    scene.lm_sun.use_sky_sync = True
    m.lm_sun_update(scene.lm_sun, None)
    skies = [n for n in nt.nodes if n.type == 'TEX_SKY']
    check("sky node created", len(skies) == 1 and skies[0].name == "LM Sky",
          str([n.name for n in nt.nodes]))
    sky = skies[0]
    el = scene.lm_sun["sun_elevation"]
    az = scene.lm_sun["sun_azimuth"]
    check("sky elevation driven",
          abs(sky.sun_elevation - math.radians(el)) < 1e-4,
          "%.5f vs %.5f" % (sky.sun_elevation, math.radians(el)))
    check("sky rotation driven",
          abs(sky.sun_rotation - math.radians(az)) % (2 * math.pi) < 1e-4,
          "%.5f vs %.5f" % (sky.sun_rotation, math.radians(az)))
    check("sky sun_disc off (sun lamp drives light)", sky.sun_disc is False)
    bg = next(n for n in nt.nodes if n.type == 'BACKGROUND')
    check("sky wired into Background",
          bg.inputs['Color'].is_linked
          and bg.inputs['Color'].links[0].from_node == sky)
    # move time: sky follows
    scene.lm_sun.time_hours = 18.0
    m.lm_sun_update(scene.lm_sun, None)
    el2 = scene.lm_sun["sun_elevation"]
    check("sky follows time change",
          abs(sky.sun_elevation - math.radians(el2)) < 1e-4)
    scene.lm_sun.use_sky_sync = False

    # existing (foreign) sky node is adopted instead of creating a second one
    scene.lm_sun.use_sky_sync = True
    nt.nodes.remove(skies[0])  # drop our LM Sky: sync must adopt the user's node
    foreign = nt.nodes.new('ShaderNodeTexSky')
    foreign.name = "UserSky"
    m.lm_sun_update(scene.lm_sun, None)
    skies = [n for n in nt.nodes if n.type == 'TEX_SKY']
    check("foreign sky adopted, no duplicate",
          len(skies) == 1 and skies[0].name == "UserSky"
          and abs(foreign.sun_elevation
                  - math.radians(scene.lm_sun["sun_elevation"])) < 1e-4)
    scene.lm_sun.use_sky_sync = False

    # --- update_checker sanity
    import lampochka as pkg
    uc = pkg.update_checker
    check("uc parse tag", uc._parse_tag("v3.6.0") == (3, 6, 0))
    prefs.update_result = "Update available: v9.9.9"
    check("uc valid for newer", uc.result_is_valid() is True)
    prefs.update_result = "Up to date (v3.5.0)"
    check("uc invalid for same", uc.result_is_valid() is False)
    prefs.update_result = ""

    # --- nodal sun light: blackbody branch
    nd = bpy.data.lights.new("SunN", type='SUN')
    nd.use_nodes = True
    em = next(n for n in nd.node_tree.nodes if n.type == 'EMISSION')
    author_c = list(em.inputs['Color'].default_value)
    scene.lm_sun.sun_object = bpy.data.objects["SunN"] \
        if "SunN" in bpy.data.objects else None
    sun_n = bpy.data.objects.new("SunN", nd)
    scene.collection.objects.link(sun_n)
    scene.lm_sun.sun_object = sun_n
    scene.lm_sun.kelvin_from_elevation = True
    m.lm_sun_update(scene.lm_sun, None)
    check("nodal: blackbody node created and linked",
          any(n.name == "LM Sun Blackbody" for n in nd.node_tree.nodes)
          and em.inputs['Color'].is_linked)
    scene.lm_sun.kelvin_from_elevation = False
    check("nodal: restore unlinks and restores color",
          not em.inputs['Color'].is_linked
          and all(abs(a - b) < 1e-6
                  for a, b in zip(em.inputs['Color'].default_value, author_c)))

    m.unregister()
    check("unregister clean", True)

    print("\n=== %d fails ===" % len(fails))
    _die(1 if fails else 0)
except Exception:
    traceback.print_exc()
    _die(1)
_die(1)
