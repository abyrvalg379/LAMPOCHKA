# Live headless smoke for the blend/zip preset engine (Blender 5.2).
# Verifies the fix that motivated the engine swap: applying a setup brings
# world transforms, emission colors and the empty hierarchy 1:1.
import os
import sys
import types
import tempfile
import traceback
import zipfile

EXT = r"D:\AI\ZCode\Project\LAMPOCHKA\work\extension\__init__.py"
PLS_ZIP = r"D:\AI\ZCode\Project\LAMPOCHKA\work\ref\Pro-Lighting Studio\assets_1.zip"


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
    # wipe the factory scene so object sets are deterministic
    for ob in list(scene.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    prefs = types.SimpleNamespace(hdri_folder="", ies_folder="",
                                  gobo_folder="", presets_folder="")
    m.get_lm_prefs = lambda ctx: prefs
    # background has no previews — stub the collection so enums build
    class _FakeThumb:
        icon_id = 1
    m._presets_pcoll = types.SimpleNamespace(
        load=lambda name, fp, t: _FakeThumb(), clear=lambda: None)

    fails = []

    def check(name, cond, detail=""):
        print(("  OK " if cond else "  FAIL ") + name
              + ((" -- " + str(detail)) if detail and not cond else ""))
        if not cond:
            fails.append(name)

    tmp = tempfile.mkdtemp(prefix="lm_live_presets_")
    lib = os.path.join(tmp, "packages")
    os.makedirs(lib)
    scene.lm_presets.preset_folder = lib

    # -- install a synthetic package from zip (PLS layout inside) ----------
    pkg_dir = os.path.join(tmp, "pkg_src")
    os.makedirs(pkg_dir)
    mini = os.path.join(pkg_dir, "Mini.blend")
    coll = bpy.data.collections.new("Test Setup")
    rig = bpy.data.objects.new("Rig", None)
    rig.location = (5.0, -2.0, 3.0)
    coll.objects.link(rig)
    lt = bpy.data.lights.new("Key", type='AREA')
    lt.energy = 500.0
    light_ob = bpy.data.objects.new("Key", lt)
    light_ob.parent = rig
    light_ob.location = (1.0, 2.0, -3.0)
    light_ob.rotation_euler = (0.3, 0.4, 0.5)
    coll.objects.link(light_ob)
    bpy.context.scene.collection.children.link(coll)
    bpy.ops.wm.save_as_mainfile(filepath=mini, copy=True)
    for ob in (rig, light_ob):
        bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.collections.remove(coll)
    colls = None
    # thumbs, so the enum picks up a preview path
    thumbs = os.path.join(pkg_dir, "thumbs")
    os.makedirs(thumbs)
    open(os.path.join(thumbs, "Test Setup.png"), "wb").close()
    zpath = os.path.join(tmp, "mini_package.zip")
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(mini, "library/Mini.blend")
        zf.write(os.path.join(thumbs, "Test Setup.png"),
                 "library/thumbs/Test Setup.png")
    m._extract_package(zpath, os.path.join(lib, "mini_package"))
    check("package installed",
          os.path.isfile(os.path.join(lib, "mini_package", "Mini.blend")))
    check("package thumbs flattened",
          os.path.isfile(os.path.join(lib, "mini_package", "thumbs",
                                      "Test Setup.png")))

    # -- reference pass: raw libraries.load, no LAMPOCHKA ------------------
    raw = m._load_collection_from_blend(
        os.path.join(lib, "mini_package", "Mini.blend"), "Test Setup")
    check("raw load works", raw is not None)
    ref = {}
    for ob in raw.all_objects:
        bpy.context.scene.collection.children.link(ob) if False else None
        ref[ob.name] = ob
    # place raw objects into the scene so matrices evaluate
    scene.collection.children.link(raw)
    bpy.context.view_layer.update()
    ref_world = {n: tuple(round(v, 5) for v in ob.matrix_world.translation)
                 for n, ob in ref.items()}
    ref_rot = {n: tuple(round(v, 5) for v in ob.rotation_euler)
               for n, ob in ref.items()}
    for ob in list(raw.all_objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.collections.remove(raw)

    def _refresh_enum():
        m._presets_cache_folder = None    # force rescan (GUI redraws do it)
        return m.preset_enum_items(scene.lm_presets, None)

    # -- apply via the operator --------------------------------------------
    _refresh_enum()
    check("catalog finds Test Setup",
          any(e["collection"] == "Test Setup" for e in m._presets_catalog))
    idx = next(i for i, e in enumerate(m._presets_catalog)
               if e["collection"] == "Test Setup")
    scene.lm_presets.selected_preset = str(idx)
    res = bpy.ops.light_manager.preset_apply()
    check("apply operator finished", res == {'FINISHED'}, res)

    presets_coll = bpy.data.collections.get("Presets")
    check("Presets collection exists", presets_coll is not None)
    applied = {ob.name: ob for ob in presets_coll.all_objects}
    check("apply brought 2 objects", len(applied) == 2, list(applied))
    check("setup collection datablock removed",
          bpy.data.collections.get("Test Setup") is None)

    bpy.context.view_layer.update()
    for n, ob in applied.items():
        if n not in ref_world:
            continue
        got = tuple(round(v, 5) for v in ob.matrix_world.translation)
        check("world location 1:1: " + n, got == ref_world[n],
              "%s != %s" % (got, ref_world[n]))
        got_rot = tuple(round(v, 5) for v in ob.rotation_euler)
        check("rotation 1:1: " + n, got_rot == ref_rot[n],
              "%s != %s" % (got_rot, ref_rot[n]))
    check("hierarchy kept (Key on Rig)",
          applied.get("Key") is not None
          and applied["Key"].parent is not None
          and applied["Key"].parent.name == "Rig")
    check("preset markers set",
          all(ob.get("lm_preset") == 1 for ob in applied.values()))

    # second apply replaces instead of stacking; with an active object the
    # setup roots must land on its pivot
    pivot = bpy.data.objects.new("PivotTarget", None)
    scene.collection.objects.link(pivot)
    pivot.location = (3.0, -4.0, 2.0)
    bpy.context.view_layer.objects.active = pivot
    bpy.ops.light_manager.preset_apply()
    presets_coll = bpy.data.collections.get("Presets")
    check("second apply replaces", len(presets_coll.all_objects) == 2)
    from mathutils import Vector
    roots = [ob for ob in presets_coll.all_objects if ob.parent is None]
    on_pivot = all(
        (ob.matrix_world.translation - Vector((3.0, -4.0, 2.0))).length < 1e-5
        for ob in roots)
    check("setup roots on active pivot", bool(roots) and on_pivot,
          [(ob.name, tuple(ob.matrix_world.translation)) for ob in roots])

    # -- clear lights -------------------------------------------------------
    res = bpy.ops.light_manager.clear_lights()
    check("clear finished", res == {'FINISHED'})
    check("presets gone", bpy.data.collections.get("Presets") is None)

    # -- save setup writes a package blend ----------------------------------
    rig2 = bpy.data.objects.new("MyRig", None)
    scene.collection.objects.link(rig2)
    lt2 = bpy.data.lights.new("MyKey", type='POINT')
    lt2.energy = 100.0
    lt2.color = (0.2, 0.9, 0.4)
    ob2 = bpy.data.objects.new("MyKey", lt2)
    ob2.parent = rig2
    ob2.location = (0.5, 0.0, 1.5)
    scene.collection.objects.link(ob2)
    scene.lm_presets.preset_name = "My Setup"
    res = bpy.ops.light_manager.preset_save()
    check("save finished", res == {'FINISHED'}, res)
    saved = os.path.join(lib, "My Setup.blend")
    check("saved blend exists", os.path.isfile(saved))

    _refresh_enum()
    check("catalog sees saved setup",
          any(e["collection"] == "My Setup" and e["blend"] == saved
              for e in m._presets_catalog))
    idx = next(i for i, e in enumerate(m._presets_catalog)
               if e["collection"] == "My Setup")
    scene.lm_presets.selected_preset = str(idx)
    res = bpy.ops.light_manager.preset_apply()
    check("apply of saved setup", res == {'FINISHED'})
    presets_coll = bpy.data.collections.get("Presets")
    roundtrip = {ob.name: ob for ob in presets_coll.all_objects}
    # originals are still in the scene, so appended names get .001 suffixes
    check("saved setup roundtrip objects",
          len(roundtrip) == 2
          and any(o.type == 'LIGHT' for o in roundtrip.values())
          and any(o.type == 'EMPTY' for o in roundtrip.values()),
          list(roundtrip))
    lights2 = [o for o in roundtrip.values() if o.type == 'LIGHT']
    if lights2:
        ob = lights2[0]
        check("saved setup color 1:1",
              tuple(round(c, 4) for c in ob.data.color) == (0.2, 0.9, 0.4),
              tuple(ob.data.color))
        check("saved setup parent kept", ob.parent is not None
              and ob.parent.type == 'EMPTY')

    # -- real PLS package ---------------------------------------------------
    pls_dir = os.path.join(lib, "PLS")
    m._extract_package(PLS_ZIP, pls_dir)
    check("PLS library flattened",
          os.path.isfile(os.path.join(pls_dir, "Movie_lighting_setups.blend")))
    _refresh_enum()
    kill = [e for e in m._presets_catalog if e["collection"] == "Kill Phil"]
    check("PLS Kill Phil found in catalog", len(kill) == 1, len(kill))
    check("PLS thumbnail resolved",
          m._preset_thumbnail(pls_dir, "Kill Phil") is not None)
    idx = m._presets_catalog.index(kill[0])

    # reference pass: raw load the same setup, remember per-light data
    # (BEFORE assigning selected_preset — the enum update applies it now)
    movie = os.path.join(pls_dir, "Movie_lighting_setups.blend")
    raw_kill = m._load_collection_from_blend(movie, "Kill Phil")
    scene.collection.children.link(raw_kill)
    bpy.context.view_layer.update()
    ref_data = {}
    for ob in raw_kill.all_objects:
        if ob.type == 'LIGHT':
            ref_data[ob.name] = (
                tuple(round(c, 5) for c in ob.data.color),
                round(ob.data.energy, 4))
    for ob in list(raw_kill.all_objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.collections.remove(raw_kill)

    scene.lm_presets.selected_preset = str(idx)   # enum update applies
    presets_coll = bpy.data.collections.get("Presets")
    objs = list(presets_coll.all_objects)
    lights = [ob for ob in objs if ob.type == 'LIGHT']
    empties = [ob for ob in objs if ob.type == 'EMPTY']
    check("PLS apply count", len(objs) == 6, len(objs))
    check("PLS lights nodal", lights and all(l.data.use_nodes for l in lights))
    check("PLS hierarchy present", bool(empties))
    parented = [l for l in lights if l.parent is not None]
    check("PLS lights parented to empties", parented == lights, len(parented))
    same = 0
    for l in lights:
        got = (tuple(round(c, 5) for c in l.data.color),
               round(l.data.energy, 4))
        if ref_data.get(l.name) == got:
            same += 1
    check("PLS color/energy 1:1 with source", same == len(ref_data)
          and len(ref_data) == 5, "%d/%d" % (same, len(ref_data)))

    # master intensity: x2 then back, against the raw references
    scene.lm_presets.preset_intensity = 2.0
    presets_coll = bpy.data.collections.get("Presets")
    lights_x2 = [ob for ob in presets_coll.all_objects if ob.type == 'LIGHT']
    scaled = all(abs(l.data.energy - ref_data[l.name][1] * 2.0) < 0.01
                 for l in lights_x2)
    check("master intensity x2", scaled,
          [(l.name, l.data.energy) for l in lights_x2])
    scene.lm_presets.preset_intensity = 1.0
    lights_bk = [ob for ob in presets_coll.all_objects if ob.type == 'LIGHT']
    check("master intensity back to authored",
          all(abs(l.data.energy - ref_data[l.name][1]) < 0.01
              for l in lights_bk))

    # rotation Z: spin the rig 90 deg around the root, height unchanged,
    # back to zero restores authored positions
    presets_coll = bpy.data.collections.get("Presets")
    probe = next(ob for ob in presets_coll.all_objects
                 if ob.type == 'LIGHT')
    import math as _math
    pos0 = tuple(bpy.context.view_layer.update() is None
                 and probe.matrix_world.translation)
    scene.lm_presets.preset_rotation_z = 1.5707963
    bpy.context.view_layer.update()
    pos90 = tuple(probe.matrix_world.translation)
    check("rotation Z keeps height", abs(pos0[2] - pos90[2]) < 1e-5,
          (pos0, pos90))
    check("rotation Z moved the rig in XY",
          abs(pos0[0] - pos90[0]) + abs(pos0[1] - pos90[1]) > 1e-4)
    scene.lm_presets.preset_rotation_z = 0.0
    bpy.context.view_layer.update()
    pos_back = tuple(probe.matrix_world.translation)
    check("rotation Z returns authored positions",
          all(abs(a - b) < 1e-4 for a, b in zip(pos0, pos_back)),
          (pos0, pos_back))
    res = bpy.ops.light_manager.clear_lights()
    check("PLS clear finished", res == {'FINISHED'})

    # -- carousel: prev/next apply instantly --------------------------------
    kill_idx = next(i for i, e in enumerate(m._presets_catalog)
                    if e["collection"] == "Kill Phil")
    scene.lm_presets.selected_preset = str(kill_idx)
    presets_coll = bpy.data.collections.get("Presets")
    before = {ob.name for ob in presets_coll.all_objects}
    res = bpy.ops.light_manager.preset_next()
    check("carousel next finished", res == {'FINISHED'})
    presets_coll = bpy.data.collections.get("Presets")
    after = {ob.name for ob in presets_coll.all_objects}
    check("carousel next applied a different setup",
          bool(after) and after != before, (before, after))
    res = bpy.ops.light_manager.preset_prev()
    check("carousel prev returns", res == {'FINISHED'})
    presets_coll = bpy.data.collections.get("Presets")
    back = {ob.name for ob in presets_coll.all_objects}
    check("carousel returned to Kill Phil", back == before, (before, back))

    # -- solo light ----------------------------------------------------------
    for nm, tp in (("SoloA", 'POINT'), ("SoloB", 'POINT'), ("SoloC", 'POINT')):
        lt = bpy.data.lights.new(nm + "_d", tp)
        ob = bpy.data.objects.new(nm, lt)
        scene.collection.objects.link(ob)
    bpy.ops.light_manager.solo_light(light_name="SoloA")
    def _sv(n):
        return bpy.data.objects[n].hide_viewport
    check("solo isolates A", not _sv("SoloA") and _sv("SoloB") and _sv("SoloC"))
    bpy.ops.light_manager.solo_light(light_name="SoloB")
    check("solo moves to B", _sv("SoloA") and not _sv("SoloB") and _sv("SoloC"))
    bpy.ops.light_manager.solo_light(light_name="SoloB")
    check("solo off restores", not _sv("SoloA") and not _sv("SoloB")
          and not _sv("SoloC"))
    for nm in ("SoloA", "SoloB", "SoloC"):
        bpy.data.objects.remove(bpy.data.objects[nm], do_unlink=True)

    # -- cycle select ---------------------------------------------------------
    lights_now = [o for o in scene.objects if o.type == 'LIGHT']
    first = lights_now[0]
    bpy.context.view_layer.objects.active = first
    bpy.ops.light_manager.cycle_select(direction=1)
    check("cycle selects another light",
          bpy.context.active_object is not None
          and bpy.context.active_object.type == 'LIGHT'
          and bpy.context.active_object is not first)
    nxt = bpy.context.active_object
    bpy.ops.light_manager.cycle_select(direction=-1)
    check("cycle returns back", bpy.context.active_object is first)

    # -- preset flip: mirror across root X, twice = original ------------------
    presets_coll = bpy.data.collections.get("Presets")
    probe = next(ob for ob in presets_coll.all_objects if ob.type == 'LIGHT')
    root = probe.parent
    bpy.context.view_layer.update()
    before = tuple(round(v, 5) for v in probe.matrix_world.translation)
    rx = root.matrix_world.translation.x
    res = bpy.ops.light_manager.preset_flip(direction='X')
    check("flip X finished", res == {'FINISHED'})
    bpy.context.view_layer.update()
    after = tuple(round(v, 5) for v in probe.matrix_world.translation)
    check("flip X mirrors x around root, keeps y/z",
          abs(after[0] - (2 * rx - before[0])) < 1e-4
          and abs(after[1] - before[1]) < 1e-4
          and abs(after[2] - before[2]) < 1e-4,
          (before, after, rx))
    bpy.ops.light_manager.preset_flip(direction='X')
    bpy.context.view_layer.update()
    back = tuple(round(v, 5) for v in probe.matrix_world.translation)
    check("double flip restores", back == before, (before, back))

    # -- package removal (Preferences operators) ---------------------------
    check("packages visible before removal",
          (os.path.isdir(os.path.join(lib, "mini_package")))
          and os.path.isdir(pls_dir))
    res = bpy.ops.light_manager.preset_package_remove(package="mini_package")
    check("package remove finished", res == {'FINISHED'})
    check("package folder gone",
          not os.path.isdir(os.path.join(lib, "mini_package")))
    try:
        bpy.ops.light_manager.preset_package_remove(package="no_such")
        check("package remove missing rejected", False, "no exception")
    except RuntimeError:
        check("package remove missing rejected", True)
    check("cache invalidated for rescan", m._presets_cache_folder is None)

    # -- fixed-height light list mirror -------------------------------------
    ltA = bpy.data.lights.new("MirrorLightA_data", type='POINT')
    obA = bpy.data.objects.new("MirrorLightA", ltA)
    scene.collection.objects.link(obA)
    ltB = bpy.data.lights.new("MirrorLightB_data", type='SUN')
    obB = bpy.data.objects.new("MirrorLightB", ltB)
    scene.collection.objects.link(obB)
    m._sync_light_slots(scene.lm_settings,
                        [o for o in scene.objects if o.type == 'LIGHT'])
    slot_names = [s.name for s in scene.lm_settings.lights_slots]
    check("light slots mirrored",
          "MirrorLightA" in slot_names and "MirrorLightB" in slot_names,
          slot_names)
    bpy.data.objects.remove(obB, do_unlink=True)
    m._sync_light_slots(scene.lm_settings,
                        [o for o in scene.objects if o.type == 'LIGHT'])
    slot_names = [s.name for s in scene.lm_settings.lights_slots]
    check("light slots resync after delete",
          "MirrorLightB" not in slot_names and "MirrorLightA" in slot_names,
          slot_names)
    check("UIList registered", hasattr(m, "LM_UL_Lights"))

    m.unregister()
    print("FAILS:", len(fails))
    _die(1 if fails else 0)
except Exception:
    traceback.print_exc()
    _die(2)
