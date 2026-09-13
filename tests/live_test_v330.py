# Live headless smoke for v3.3 folder auto-repair (Blender 5.2).
import os
import sys
import types
import tempfile
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
    # background mode has no addons[] entry for prefs — stub the accessor
    prefs = types.SimpleNamespace(hdri_folder="", ies_folder="",
                                  gobo_folder="", presets_folder="")
    m.get_lm_prefs = lambda ctx: prefs

    live = tempfile.mkdtemp(prefix="lm_live_hdri_")
    live2 = tempfile.mkdtemp(prefix="lm_live_hdri2_")

    fails = []

    def check(name, cond):
        print(("  OK " if cond else "  FAIL ") + name)
        if not cond:
            fails.append(name)

    # dead saved folder -> repaired from prefs
    prefs.hdri_folder = live
    scene.lm_hdri.hdri_folder = "Z:/dead/library"
    m.load_post_handler(None)
    check("repair dead from prefs", scene.lm_hdri.hdri_folder == live)

    # live saved folder wins over prefs
    scene.lm_hdri.hdri_folder = live2
    m.load_post_handler(None)
    check("live folder kept", scene.lm_hdri.hdri_folder == live2)

    # prefs edit in a live session repairs a dead scene folder
    scene.lm_hdri.hdri_folder = "Z:/dead/library"
    prefs.hdri_folder = live
    m._resolve_scene_folders()
    check("prefs update repairs dead folder", scene.lm_hdri.hdri_folder == live)

    # dead everywhere -> kept, no crash
    prefs.hdri_folder = "Z:/also/dead"
    scene.lm_hdri.hdri_folder = "Z:/dead/library"
    m.load_post_handler(None)
    check("dead kept when nothing live",
          scene.lm_hdri.hdri_folder == "Z:/dead/library")

    # ies chain intact: empty + live prefs
    ies_live = tempfile.mkdtemp(prefix="lm_live_ies_")
    scene.lm_ies.ies_folder = ""
    prefs.ies_folder = ies_live
    m.load_post_handler(None)
    check("ies seeded", scene.lm_ies.ies_folder == ies_live)

    # panel helper
    check("folder label", m._folder_label(os.path.join(live, "SP")) == "SP")

    # version bump shipped
    man = open(os.path.join(os.path.dirname(EXT), "blender_manifest.toml"),
               encoding="utf-8").read()
    check("manifest 3.3.0", 'version = "3.3.0"' in man)

    m.unregister()
    print("FAILS:", len(fails))
    _die(1 if fails else 0)
except Exception:
    traceback.print_exc()
    _die(2)
