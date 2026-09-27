# -*- coding:utf-8 -*-
"""LAMPOCHKA headless smoke test - runs INSIDE Blender (-b).

Builds a synthetic lighting scene (all four lamp types), then exercises the
addon end-to-end through the same entry points the UI uses: light list
mirror, select/settings/visibility/delete, Kelvin, Sun helper (sky sync +
kelvin-from-elevation), HDRI / IES / Gobo browsers on generated asset files,
preset package install -> apply -> intensity -> clear, solo/cycle/batch,
list collapse and the update checker. Nothing here may depend on network,
GUI or the host machine's libraries.

Prerequisite: the lampochka extension is installed into a user resources
dir pointed to by BLENDER_USER_RESOURCES (see tests/run_smoke.py).

Exit code: 0 = all steps passed, 1 = at least one step failed.
Never returns through normal interpreter teardown: Blender -b can hang on
exit on some setups, os._exit is safe everywhere.
"""

import bpy
import os
import sys
import tempfile
import traceback

MOD = "bl_ext.user_default.lampochka"

RESULTS = []


def step(name, fn):
    try:
        info = fn() or ""
        RESULTS.append((name, True, info))
        print(f"[SMOKE] PASS {name} {info}")
    except Exception as e:
        RESULTS.append((name, False, str(e)))
        print(f"[SMOKE] FAIL {name}: {e}")
        traceback.print_exc()


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ── Enable the extension ─────────────────────────────────────────────────────
import addon_utils

enable_info = addon_utils.enable(MOD, default_set=True, persistent=True)
if MOD not in sys.modules:
    raise SystemExit(f"cannot enable {MOD}: {enable_info!r}")

m = sys.modules[MOD]

scene = bpy.context.scene


def scene_lights():
    return [o for o in scene.objects if o.type == 'LIGHT']


def make_light(name, ltype, energy=100.0):
    data = bpy.data.lights.new(name, type=ltype)
    data.energy = energy
    ob = bpy.data.objects.new(name, data)
    scene.collection.objects.link(ob)
    return ob


def save_image(path, fmt):
    img = bpy.data.images.new(os.path.basename(path), 8, 8,
                              float_buffer=(fmt == 'OPEN_EXR'))
    img.filepath_raw = path
    img.file_format = fmt
    img.save()
    return path


MINIMAL_IES = """IESNA:LM-63-2002
[LAMPOCHKA smoke] 1 1 1 0 0 1
1 1 100
0 0 0
0 0 0
0 90
0
1 1
0
"""


# ── Steps ────────────────────────────────────────────────────────────────────

def st_clean_scene():
    for ob in list(scene.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    expect(not scene_lights(), "factory scene still has lights")
    return "empty scene"


def st_add_lights():
    for i, ltype in enumerate(('POINT', 'SUN', 'SPOT', 'AREA')):
        bpy.ops.light_manager.add_light(light_type=ltype)
    expect(len(scene_lights()) == 4,
           f"expected 4 lights, got {len(scene_lights())}")
    return "4 lamps added via operator"


def st_light_list_mirror():
    lights = scene_lights()
    m._sync_light_slots(scene.lm_settings, lights)
    expect(len(scene.lm_settings.lights_slots) == 4,
           f"mirror has {len(scene.lm_settings.lights_slots)} slots")
    return "4 slots mirrored"


def st_select_and_settings():
    bpy.ops.light_manager.select_light(index=0)
    expect(scene.lm_settings.selected_index == 0, "index not stored")
    expect(bpy.context.view_layer.objects.active is not None,
           "no active object after select")
    name = bpy.context.view_layer.objects.active.name
    bpy.ops.light_manager.toggle_settings(light_name=name)
    expect(scene.lm_settings.settings_light == name, "settings not opened")
    return f"active={name}"


def st_visibility():
    ob = scene_lights()[0]
    bpy.ops.light_manager.toggle_visibility(index=0)
    expect(ob.hide_viewport is True, "hide_viewport not toggled")
    bpy.ops.light_manager.toggle_visibility(index=0)
    bpy.ops.light_manager.toggle_render(index=0)
    expect(ob.hide_render is True, "hide_render not toggled")
    bpy.ops.light_manager.toggle_render(index=0)
    bpy.ops.light_manager.toggle_all_visibility()
    hidden = all(o.hide_viewport for o in scene_lights())
    bpy.ops.light_manager.toggle_all_visibility()
    expect(hidden, "toggle_all did not hide everything")
    return "viewport + render + all-toggles"


def st_duplicate_delete():
    before = len(scene_lights())
    bpy.ops.light_manager.duplicate_light()
    expect(len(scene_lights()) == before + 1, "duplicate did not add a lamp")
    bpy.ops.light_manager.delete_light_row(index=len(scene_lights()) - 1)
    expect(len(scene_lights()) == before, "row delete did not remove")
    return "duplicate + row delete"


def st_kelvin():
    ob = scene_lights()[0]
    ob.data.use_nodes = True  # fresh 5.2 lights are nodal anyway
    em = next(n for n in ob.data.node_tree.nodes if n.type == 'EMISSION')
    author = list(em.inputs['Color'].default_value)
    ob.lm_use_temperature = True
    driven = em.inputs['Color'].default_value[:]
    expect(em.inputs['Color'].is_linked
           or list(driven) != author, "kelvin did not change the light")
    ob.lm_use_temperature = False
    expect(all(abs(a - b) < 1e-6 for a, b in
               zip(em.inputs['Color'].default_value, author)),
           "kelvin off did not restore the author color")
    return "on/off restores color"


def st_sun_helper():
    sun = make_light("SmokeSun", 'SUN')
    sun.data.use_nodes = True  # 4.x lamps are not nodal by default, 5.x are
    world = bpy.data.worlds.new("SmokeWorld")
    world.use_nodes = True
    scene.world = world
    s = scene.lm_sun
    s.sun_object = sun
    s.latitude, s.longitude, s.utc_offset = 55.75, 37.62, 3.0
    s.day, s.month, s.year = 21, 6, 2026
    s.time_hours = 12.0
    expect(s["sun_elevation"] > 30.0, f"June noon too low: {s['sun_elevation']}")

    s.use_sky_sync = True
    skies = [n for n in world.node_tree.nodes if n.type == 'TEX_SKY']
    expect(len(skies) == 1, f"expected 1 sky node, got {len(skies)}")
    import math
    expect(abs(skies[0].sun_elevation - math.radians(s["sun_elevation"])) < 1e-4,
           "sky elevation not driven")

    s.kelvin_from_elevation = True
    tree = sun.data.node_tree
    bb = [n for n in tree.nodes
          if n.type == 'BLACKBODY' and n.name == "LM Sun Blackbody"]
    expect(len(bb) == 1, "blackbody not created")
    s.kelvin_from_elevation = False
    expect(not any(n.type == 'BLACKBODY' for n in tree.nodes),
           "blackbody not removed on toggle off")

    bpy.ops.light_manager.sun_preset(preset='NOON')
    expect(s.time_hours == 12.0, "noon preset wrong")
    s.use_sky_sync = False
    return f"elev={s['sun_elevation']:.1f} deg, sky synced"


def st_hdri_browser():
    folder = tempfile.mkdtemp(prefix="lm_smoke_hdri_")
    exr = save_image(os.path.join(folder, "smoke_env.exr"), 'OPEN_EXR')
    # dynamic enums are empty in background mode (no previews) — exercise the
    # scan + apply internals the operator delegates to
    items = m.hdri_enum_items(scene.lm_hdri, bpy.context)
    expect(not m._hdri_enum_cache or items, "enum cache inconsistent")
    world = scene.world
    rv = m._hdri_apply_image(bpy.context, exr)
    expect(rv == {'FINISHED'}, f"apply failed: {rv}")
    env = [n for n in world.node_tree.nodes if n.type == 'TEX_ENVIRONMENT']
    expect(env and env[0].image is not None, "env node without image")
    scene.lm_hdri.hide_from_camera = True
    scene.lm_hdri.hide_from_camera = False
    bpy.ops.light_manager.hdri_clear()
    # after apply+clear there may be more than one Background node; the one
    # that matters is the one wired to the world output
    bg = next(n for n in world.node_tree.nodes
              if n.type == 'BACKGROUND' and n.outputs['Background'].is_linked)
    expect(bg.inputs['Strength'].default_value == 0.0,
           "clear did not black out the world")
    scene.lm_hdri.hdri_folder = ""
    return "apply / hide-from-camera / clear"


def st_ies_browser():
    folder = tempfile.mkdtemp(prefix="lm_smoke_ies_")
    ies_path = os.path.join(folder, "smoke.ies")
    with open(ies_path, "w") as fh:
        fh.write(MINIMAL_IES)
    scene.lm_ies.ies_folder = folder
    spot = next(ob for ob in scene_lights() if ob.data.type == 'SPOT')
    bpy.context.view_layer.objects.active = spot
    m._lm_apply_ies(spot.data, ies_path)
    nodes = spot.data.node_tree.nodes
    expect(any(n.type == 'TEX_IES' for n in nodes), "no TEX_IES node")
    bpy.ops.light_manager.ies_remove()
    expect(not any(n.type == 'TEX_IES' for n in nodes), "IES not removed")
    scene.lm_ies.ies_folder = ""
    return "apply + remove on spot"


def st_gobo_browser():
    folder = tempfile.mkdtemp(prefix="lm_smoke_gobo_")
    png = save_image(os.path.join(folder, "smoke_gobo.png"), 'PNG')
    scene.lm_gobo.gobo_folder = folder
    spot = next(ob for ob in scene_lights() if ob.data.type == 'SPOT')
    bpy.context.view_layer.objects.active = spot
    m._lm_apply_gobo(spot, png)
    nodes = spot.data.node_tree.nodes
    img = nodes.get("LM Gobo Image")
    expect(img is not None and img.image is not None, "gobo image node missing")
    spot.data.lm_gobo_mix = 0.5
    spot.data.lm_gobo_scale_x = 1.5
    bpy.ops.light_manager.gobo_remove()
    expect(not any(n.name == "LM Gobo Image" for n in nodes),
           "gobo not removed")
    return "apply + per-light knobs + remove"


def st_presets():
    base = tempfile.mkdtemp(prefix="lm_smoke_presets_")
    pkg = os.path.join(base, "SmokePkg")
    os.makedirs(pkg)

    coll = bpy.data.collections.new("Smoke Setup")
    scene.collection.children.link(coll)
    empty = bpy.data.objects.new("SmokePivot", None)
    empty.location = (2.0, 0.0, 0.0)  # off-origin so a Z rotation is visible
    coll.objects.link(empty)
    key = make_light("SmokeKey", 'AREA', energy=500.0)
    key.parent = empty
    coll.objects.link(key)

    # 4.x+ signature: a plain set of datablocks
    bpy.data.libraries.write(os.path.join(pkg, "setup.blend"), {coll})
    for ob in (key, empty):
        bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.collections.remove(coll)

    scene.lm_presets.preset_folder = base
    # dynamic preset enums are empty in background mode (no previews) —
    # stub the preview collection so the enum machinery fills the catalog
    class _FakePColl:
        def clear(self):
            pass

        def load(self, name, path, _type):
            return 0

    m._presets_pcoll = _FakePColl()
    m._invalidate_preset_cache()
    m.preset_enum_items(scene.lm_presets, bpy.context)
    items = [i[0] for i in m._presets_enum_cache]
    expect(items, f"catalog empty: {items}")
    scene.lm_presets.selected_preset = items[0]  # update applies it
    presets_coll = bpy.data.collections.get("Presets")
    expect(presets_coll is not None, "Presets collection missing")
    applied = [o for o in presets_coll.objects if o.type == 'LIGHT']
    expect(applied, "preset apply produced no lights")
    energy0 = applied[0].data.energy

    scene.lm_presets.preset_intensity = 2.0
    expect(abs(applied[0].data.energy - energy0 * 2.0) < 1e-4,
           f"intensity x2 wrong: {applied[0].data.energy} vs {energy0 * 2}")
    scene.lm_presets.preset_intensity = 1.0
    expect(abs(applied[0].data.energy - energy0) < 1e-4,
           "intensity restore wrong")

    scene.lm_presets.preset_rotation_z = 1.5707963  # 90 deg
    roots = [o for o in presets_coll.objects if o.parent is None]
    pivot = next(o for o in roots if o.name.startswith("SmokePivot"))
    x0, y0 = pivot.matrix_world.translation.x, pivot.matrix_world.translation.y
    expect(abs(pivot.matrix_world.translation.x - (-y0)) < 1e-3
           and abs(pivot.matrix_world.translation.y - x0) < 1e-3,
           f"90 deg rotation wrong: {(x0, y0)} -> "
           f"{tuple(pivot.matrix_world.translation)}")
    scene.lm_presets.preset_rotation_z = 0.0
    expect(abs(pivot.matrix_world.translation.x - x0) < 1e-3
           and abs(pivot.matrix_world.translation.y - y0) < 1e-3,
           "rotation reset wrong")

    bpy.ops.light_manager.clear_lights('EXEC_DEFAULT')
    gone = bpy.data.collections.get("Presets")
    expect(gone is None or not [o for o in gone.objects if o.type == 'LIGHT'],
           "clear lights left preset lamps")
    scene.lm_presets.preset_folder = ""
    return f"package '{items[0]}' apply/intensity/rotation/clear"


def st_solo_cycle_batch():
    lights = scene_lights()
    expect(len(lights) >= 2, "need >= 2 lights")
    a, b = lights[0], lights[1]
    bpy.ops.light_manager.solo_light(light_name=a.name)
    expect(a.hide_viewport is False and b.hide_viewport is True,
           "solo did not isolate")
    bpy.ops.light_manager.solo_light(light_name=a.name)
    expect(b.hide_viewport is False, "solo off did not restore")

    idx = scene_lights().index(a)
    scene.lm_settings.selected_index = idx
    bpy.ops.light_manager.cycle_select(direction=1)
    expect(scene.lm_settings.selected_index != idx
           or len(scene_lights()) == 1, "cycle did not move")

    settings = scene.lm_settings
    settings.batch_mode = True
    base_a = a.data.energy
    base_b = b.data.energy
    bpy.ops.light_manager.batch_toggle(light_name=a.name)
    bpy.ops.light_manager.batch_toggle(light_name=b.name)
    settings.batch_power = 2.0
    expect(abs(a.data.energy - base_a * 2.0) < 1e-4,
           f"batch power wrong: {a.data.energy} vs {base_a * 2}")
    bpy.ops.light_manager.batch_clear()
    expect(abs(a.data.energy - base_a * 2.0) < 1e-4,
           "batch clear must keep tuned energies")
    settings.batch_power = 1.0
    settings.batch_mode = False
    return "solo / cycle / batch power + clear"


def st_collapse():
    bpy.ops.light_manager.toggle_lights()
    expect(scene.lm_settings.lights_open is False, "did not collapse")
    bpy.ops.light_manager.toggle_lights()
    expect(scene.lm_settings.lights_open is True, "did not expand")
    return "collapse + expand"


def st_update_checker():
    uc = m.update_checker
    expect(uc._parse_tag("v3.5.0") == (3, 5, 0), "tag parse broken")
    ver = uc._local_version_tuple()
    expect(ver != (0, 0, 0), f"local version not resolved: {ver}")
    # no network calls here - the silent timer is disarmed by disabling the
    # daily toggle for the duration of the smoke
    return f"local version {ver}"


def st_reload_cycle():
    addon_utils.disable(MOD, default_set=True)
    for name in list(sys.modules):
        if "lampochka" in name:
            del sys.modules[name]
    addon_utils.enable(MOD, default_set=True, persistent=True)
    expect(MOD in sys.modules, "re-enable failed")
    expect(hasattr(bpy.ops.light_manager, "toggle_lights"),
           "operators missing after reload")
    return "disable/enable clean"


def main():
    print("=" * 60)
    print("[SMOKE] LAMPOCHKA headless smoke test")
    print("=" * 60)

    step("clean_scene", st_clean_scene)
    step("add_lights", st_add_lights)
    step("light_list_mirror", st_light_list_mirror)
    step("select_and_settings", st_select_and_settings)
    step("visibility", st_visibility)
    step("duplicate_delete", st_duplicate_delete)
    step("kelvin", st_kelvin)
    step("sun_helper", st_sun_helper)
    step("hdri_browser", st_hdri_browser)
    step("ies_browser", st_ies_browser)
    step("gobo_browser", st_gobo_browser)
    step("presets", st_presets)
    step("solo_cycle_batch", st_solo_cycle_batch)
    step("collapse", st_collapse)
    step("update_checker", st_update_checker)
    step("reload_cycle", st_reload_cycle)

    failed = [r for r in RESULTS if not r[1]]
    print("=" * 60)
    for name, ok, info in RESULTS:
        if not ok:
            print(f"[SMOKE] FAILED STEP: {name}: {info}")
    verdict = "PASS" if not failed else "FAIL"
    print(f"SMOKE_RESULT: {verdict} ({len(RESULTS) - len(failed)}/{len(RESULTS)} steps)")
    print("=" * 60)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if not failed else 1)


main()
