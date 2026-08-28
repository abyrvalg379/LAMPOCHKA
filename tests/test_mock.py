# Mock-based smoke test for LAMPOCHKA 2.1 (no Blender needed).
# Validates: module exec (NameErrors), register/unregister flow, enum
# caching logic, node-tree build/swap logic in apply operator.
import os
import sys
import json
import types
import tempfile
import shutil
import traceback

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(("  OK " if cond else "FAIL ") + name + ((" -- " + detail) if detail and not cond else ""))


# ---------------------------------------------------------------- mocks
class FakeSockets(dict):
    """Dict by socket name, but iterates like real bpy sockets collection."""

    def __iter__(self):
        return iter(self.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _Socket:
    def __init__(self):
        self.default_value = None
        self.links = []
        self.node = None

    @property
    def is_linked(self):
        return bool(self.links)


class FakeVector2:
    def __init__(self, x=0.0, y=0.0):
        self.x = x
        self.y = y


class FakeNode:
    def __init__(self, ntype, name=None):
        self.type = ntype
        self.name = name or ntype
        self.label = ""
        self._loc = FakeVector2()
        self.image = None
        self.filepath = ""
        self.mode = ""
        self.inputs = FakeSockets()
        self.outputs = FakeSockets()
        for inp in ("Vector", "Generated", "Color", "Rotation", "Location", "Scale",
                    "Strength", "Surface", "Background"):
            self.inputs[inp] = _sock()
            self.outputs[inp] = _sock()
        self.inputs.setdefault("Fac", _sock())
        self.outputs.setdefault("Fac", _sock())
        self.outputs.setdefault("Emission", _sock())
        for sock in list(self.inputs.values()) + list(self.outputs.values()):
            sock.node = self

    @property
    def location(self):
        return self._loc

    @location.setter
    def location(self, value):
        self._loc = FakeVector2(value[0], value[1])


class FakeObj:
    """Object with dict-style ID props (ob["key"]) like real Blender."""

    def __init__(self, otype, data=None):
        self.type = otype
        self.data = data
        self._props = {}

    def get(self, key, default=None):
        return self._props.get(key, default)

    def __contains__(self, key):
        return key in self._props

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value

    def __delitem__(self, key):
        del self._props[key]


class FakeLightData:
    def __init__(self):
        self.type = 'SPOT'
        self.use_nodes = False
        self.node_tree = FakeTree()
        self.color = [1.0, 1.0, 1.0]


class FakeNodes(list):
    _links = None

    def get(self, name):
        for n in self:
            if n.name == name:
                return n
        return None

    def new(self, ntype):
        n = FakeNode(ntype)
        # normalize like real blender: 'ShaderNodeTexEnvironment' -> 'TEX_ENVIRONMENT'
        tmap = {"ShaderNodeTexEnvironment": "TEX_ENVIRONMENT",
                "ShaderNodeBackground": "BACKGROUND",
                "ShaderNodeMapping": "MAPPING",
                "ShaderNodeTexCoord": "TEX_COORD",
                "ShaderNodeOutputWorld": "OUTPUT_WORLD",
                "ShaderNodeTexIES": "TEX_IES",
                "ShaderNodeEmission": "EMISSION",
                "ShaderNodeOutputLight": "OUTPUT_LIGHT",
                "ShaderNodeBlackbody": "BLACKBODY"}
        n.type = tmap.get(ntype, ntype)
        self.append(n)
        return n

    def remove(self, node):
        # like real Blender: removing a node removes its links too
        if self._links is not None:
            for sock in list(node.inputs.values()) + list(node.outputs.values()):
                for link in list(sock.links):
                    self._links.remove(link)
        list.remove(self, node)

    def clear(self):
        self[:] = []


def _sock():
    return _Socket()


class FakeLinks:
    def __init__(self, nodes):
        self.nodes = nodes
        self.made = []

    def new(self, out_sock, in_sock):
        link = types.SimpleNamespace(from_socket=out_sock, to_socket=in_sock,
                                     from_node=getattr(out_sock, "node", None),
                                     to_node=getattr(in_sock, "node", None))
        self.made.append(link)
        out_sock.links.append(link)
        in_sock.links.append(link)
        return link

    def remove(self, link):
        self.made.remove(link)
        link.from_socket.links.remove(link)
        link.to_socket.links.remove(link)


class FakeTree:
    def __init__(self):
        self.nodes = FakeNodes()
        self.links = FakeLinks(self.nodes)
        self.nodes._links = self.links


class FakeWorld:
    def __init__(self):
        self.name = "World"
        self.use_nodes = False
        self.node_tree = FakeTree()


class FakeEnumThumb:
    icon_id = 42


class FakePColl:
    def __init__(self):
        self.loaded = []
        self.cleared = 0

    def load(self, name, filepath, ftype):
        self.loaded.append(filepath)
        return FakeEnumThumb()

    def clear(self):
        self.cleared += 1
        self.loaded.clear()


bpy = types.ModuleType("bpy")
bpy.__path__ = []  # package-style so "from bpy.props import ..." resolves
bpy.types = types.ModuleType("bpy.types")
bpy.types.PropertyGroup = type("PropertyGroup", (), {})
bpy.types.Panel = type("Panel", (), {})
bpy.types.Operator = type("Operator", (), {})
bpy.types.Scene = type("Scene", (), {})
bpy.types.Object = type("Object", (), {})
bpy.types.AddonPreferences = type("AddonPreferences", (), {})

bpy.props = types.ModuleType("bpy.props")
bpy.props.StringProperty = lambda **kw: None
bpy.props.IntProperty = lambda **kw: None
bpy.props.BoolProperty = lambda **kw: kw
bpy.props.FloatProperty = lambda **kw: None
bpy.props.FloatVectorProperty = lambda **kw: None
bpy.props.EnumProperty = lambda **kw: kw          # keep kwargs for callback test
bpy.props.PointerProperty = lambda **kw: None

_registered = []
bpy.utils = types.ModuleType("bpy.utils")
bpy.utils.register_class = lambda cls: _registered.append(cls.__name__)
bpy.utils.unregister_class = lambda cls: _registered.remove(cls.__name__)
_pcoll_holder = [None]
bpy.utils.previews = types.SimpleNamespace(
    new=lambda: _pcoll_holder[0],
    remove=lambda p: None,
)

_handlers = {"deps": [], "load": []}
bpy.app = types.ModuleType("bpy.app")
bpy.app.handlers = types.ModuleType("bpy.app.handlers")
bpy.app.handlers.depsgraph_update_post = _handlers["deps"]
bpy.app.handlers.load_post = _handlers["load"]


def persistent(fn):
    return fn


bpy.app.handlers.persistent = persistent

bpy_extras = types.ModuleType("bpy_extras")
bpy_extras.__path__ = []
io_utils = types.ModuleType("bpy_extras.io_utils")
io_utils.ImportHelper = type("ImportHelper", (), {})
bpy_extras.io_utils = io_utils

for mod in (bpy, bpy.types, bpy.props, bpy.utils, bpy.app, bpy.app.handlers,
            bpy_extras, io_utils):
    sys.modules[mod.__name__] = mod

# ---------------------------------------------------------------- exec module
path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "extension", "__init__.py")
src = open(path, encoding="utf-8").read()
ns = {"__name__": "lampochka_test", "__file__": path, "__package__": "lampochka_test"}
try:
    exec(compile(src, path, "exec"), ns)
    check("module exec without NameError", True)
except Exception:
    check("module exec without NameError", False, traceback.format_exc())
    sys.exit(1)

LM_HDRISettings = ns["LM_HDRISettings"]
hdri_enum_items = ns["hdri_enum_items"]

# enum callback wired as items= (py3.14: __annotations__ is lazy via
# __annotate__, py3.11/Blender: eager in __dict__ — __annotations__ covers both)
_anns = LM_HDRISettings.__annotations__
_sel = _anns.get("selected_hdri")
check("enum callback wired into EnumProperty",
      isinstance(_sel, dict) and _sel.get("items") is hdri_enum_items,
      repr(_sel)[:200])

# ---------------------------------------------------------------- register
pcoll = FakePColl()
_pcoll_holder[0] = pcoll
_world = FakeWorld()
_prefs = types.SimpleNamespace(hdri_folder="")
bpy.context = types.SimpleNamespace(
    scene=types.SimpleNamespace(world=_world),
    preferences=types.SimpleNamespace(addons={
        "lampochka_test": types.SimpleNamespace(preferences=_prefs)}),
)
bpy.data = types.SimpleNamespace(
    worlds=types.SimpleNamespace(new=lambda n: FakeWorld()),
    images=types.SimpleNamespace(load=lambda fp, check_existing=False: FakeNode("IMAGE")),
)
_scene = bpy.context.scene


def _pointer(type):
    _pointers.append(type)
    return None


_pointers = []
bpy.props.PointerProperty = _pointer

try:
    ns["register"]()
    check("register() runs", True)
except Exception:
    check("register() runs", False, traceback.format_exc())
    sys.exit(1)

check("all classes registered", len(_registered) == len(ns["classes"]),
      f"{_registered} vs {len(ns['classes'])} classes")
check("lm_settings pointer added", ns["LM_SceneSettings"] in _pointers)
check("lm_hdri pointer added", ns["LM_HDRISettings"] in _pointers)
check("lm_ies pointer added", ns["LM_IESSettings"] in _pointers)
check("object kelvin props added",
      hasattr(bpy.types.Object, "lm_use_temperature")
      and hasattr(bpy.types.Object, "lm_temperature"))
check("sync handler appended", ns["sync_handler"] in _handlers["deps"])
check("load_post handler appended", ns["load_post_handler"] in _handlers["load"])
check("prefs class registered", "LM_AddonPreferences" in _registered)
check("preview collection created", pcoll is _pcoll_holder[0])

# ---------------------------------------------------------------- enum callback
class FakeHdriProps:
    hdri_folder = ""


props = FakeHdriProps()
check("enum callback: empty folder -> []", hdri_enum_items(props, None) == [])

tmp = tempfile.mkdtemp(prefix="lampochka_hdri_")
for fname in ("b_test.hdr", "a_test.exr", "ignore.png"):
    open(os.path.join(tmp, fname), "wb").close()

props.hdri_folder = tmp
items = hdri_enum_items(props, None)
check("enum: 2 hdri files found", len(items) == 2, str(items))
check("enum: sorted, exr first",
      items and items[0][1] == "a_test" and items[1][1] == "b_test", str(items))
check("enum: identifier is filepath", items and items[0][0].endswith("a_test.exr"))
check("enum: 5-tuple with icon_id", items and len(items[0]) == 5 and items[0][3] == 42)
cleared_before = pcoll.cleared
check("enum: cache returned (no rebuild)",
      hdri_enum_items(props, None) is items and pcoll.cleared == cleared_before)
props.hdri_folder = ""
hdri_enum_items(props, None)
check("enum: folder change clears pcoll", pcoll.cleared == cleared_before + 1)
props.hdri_folder = tmp
items2 = hdri_enum_items(props, None)
check("enum: rebuild after clear", len(items2) == 2 and pcoll.loaded)

# ---------------------------------------------------------------- update callbacks
mapping_node = FakeNode("MAPPING", "HDRI Mapping")
bg_node = FakeNode("BACKGROUND")
_world.use_nodes = True
_world.node_tree.nodes.extend([mapping_node, bg_node])

ns["update_hdri_rotation"](types.SimpleNamespace(rotation=(0, 0, 1.57)), bpy.context)
check("rotation update hits Mapping node",
      mapping_node.inputs["Rotation"].default_value == (0, 0, 1.57))
ns["update_hdri_power"](types.SimpleNamespace(power=2.5), bpy.context)
check("power update hits Background node", bg_node.inputs["Strength"].default_value == 2.5)

# ---------------------------------------------------------------- apply operator
bpy.ops = types.SimpleNamespace()  # operator classes use bl_options only


class Op(ns["LM_OT_hdri_apply"]):
    pass


op = Op()
op.report = lambda t, m: print("    report:", t, m)

# --- build branch (empty world tree)
_scene.lm_hdri = types.SimpleNamespace(
    selected_hdri=os.path.join(tmp, "a_test.exr"),
    rotation=(0.1, 0.2, 0.3),
    power=3.0,
)
_world.node_tree.nodes.clear()
_world.node_tree.links.made.clear()
rv = op.execute(bpy.context)
check("apply build branch FINISHED", rv == {"FINISHED"})
types_ = [n.type for n in _world.node_tree.nodes]
check("build: 5 nodes created", len(types_) == 5, str(types_))
check("build: has env+mapping+bg+output",
      {"TEX_ENVIRONMENT", "MAPPING", "BACKGROUND", "OUTPUT_WORLD"} <= set(types_))
check("build: 4 links", len(_world.node_tree.links.made) == 4)
build_env = [n for n in _world.node_tree.nodes if n.type == "TEX_ENVIRONMENT"][0]
check("build: image assigned to env node", build_env.image is not None)
mapping = _world.node_tree.nodes.get("HDRI Mapping")
check("build: mapping named + rotation set", mapping is not None
      and mapping.inputs["Rotation"].default_value == (0.1, 0.2, 0.3))
bg = [n for n in _world.node_tree.nodes if n.type == "BACKGROUND"][0]
check("build: strength set", bg.inputs["Strength"].default_value == 3.0)

# --- swap branch (env+bg exist)
n_before = len(_world.node_tree.nodes)
scene_image = FakeNode("IMAGE")
bpy.data.images.load = lambda fp, check_existing=False: scene_image
rv = op.execute(bpy.context)
check("apply swap branch FINISHED", rv == {"FINISHED"})
check("swap: node count unchanged", len(_world.node_tree.nodes) == n_before)
env = [n for n in _world.node_tree.nodes if n.type == "TEX_ENVIRONMENT"][0]
check("swap: image swapped", env.image is scene_image)

# --- invalid selection
_scene.lm_hdri.selected_hdri = "Z:/nope/missing.exr"
rv = op.execute(bpy.context)
check("apply invalid -> CANCELLED", rv == {"CANCELLED"})

# ---------------------------------------------------------------- clear hdri
class ClearOp(ns["LM_OT_hdri_clear"]):
    pass


clear = ClearOp()
clear.report = lambda t, m: print("    report:", t, m)
rv = clear.execute(bpy.context)
check("clear FINISHED", rv == {"FINISHED"})
types_after = sorted(n.type for n in _world.node_tree.nodes)
check("clear: env/mapping/texcoord removed",
      types_after == ["BACKGROUND", "OUTPUT_WORLD"], str(types_after))
bg2 = [n for n in _world.node_tree.nodes if n.type == "BACKGROUND"][0]
check("clear: strength reset", bg2.inputs["Strength"].default_value == 1.0)
check("clear: props reset", _scene.lm_hdri.rotation == (0.0, 0.0, 0.0)
      and _scene.lm_hdri.power == 1.0)
n_before = len(_world.node_tree.nodes)
rv = clear.execute(bpy.context)
check("clear idempotent", rv == {"FINISHED"}
      and len(_world.node_tree.nodes) == n_before)

# ---------------------------------------------------------------- kelvin
rgb_warm = ns["kelvin_to_rgb"](2000)
rgb_noon = ns["kelvin_to_rgb"](6500)
rgb_cold = ns["kelvin_to_rgb"](10000)
check("kelvin: channels in 0..1",
      all(0.0 <= c <= 1.0 for rgb in (rgb_warm, rgb_noon, rgb_cold) for c in rgb))
check("kelvin: 2000K is warm (r >> b)", rgb_warm[0] > rgb_warm[2] + 0.3,
      str(rgb_warm))
check("kelvin: 10000K is cold (b > r)", rgb_cold[2] > rgb_cold[0], str(rgb_cold))
check("kelvin: 6500K near white", all(c > 0.7 for c in rgb_noon), str(rgb_noon))

kobj = FakeObj('LIGHT', FakeLightData())
kobj.data.color = [0.5, 0.3, 0.2]
kobj.lm_use_temperature = True
ns["lm_use_temperature_update"](kobj, None)
check("kelvin: mode=color on node-less light",
      kobj.get("lm_kelvin_mode") == "color")
base_raw = kobj.get("lm_base_data")
check("kelvin: base color stored on enable",
      base_raw is not None and json.loads(base_raw)["color"] == [0.5, 0.3, 0.2])
check("kelvin: color set to ~6500K", all(c > 0.7 for c in kobj.data.color))
ns["lm_temperature_set"](kobj, 2500.0)
check("kelvin: value stored", kobj["lm_temperature"] == 2500.0)
check("kelvin: 2500K color is warm", kobj.data.color[0] > kobj.data.color[2],
      str(kobj.data.color))
kobj.lm_use_temperature = False
ns["lm_use_temperature_update"](kobj, None)
check("kelvin: original color restored on disable",
      kobj.data.color == [0.5, 0.3, 0.2])
check("kelvin: temp keys removed on disable",
      "lm_base_data" not in kobj and "lm_temperature" not in kobj
      and "lm_kelvin_mode" not in kobj)

# --- node light: Blackbody mode
nobj = FakeObj('LIGHT', FakeLightData())
nobj.data.use_nodes = True
em_node = FakeNode('EMISSION')
em_node.inputs['Color'].default_value = [0.1, 0.2, 0.3, 1.0]
nobj.data.node_tree.nodes.append(em_node)

nobj.lm_use_temperature = True
ns["lm_use_temperature_update"](nobj, None)
check("kelvin nodes: mode=nodes", nobj.get("lm_kelvin_mode") == "nodes")
bb_nodes = [n for n in nobj.data.node_tree.nodes if n.type == 'BLACKBODY']
check("kelvin nodes: blackbody created", len(bb_nodes) == 1)
check("kelvin nodes: linked into Emission color",
      em_node.inputs['Color'].is_linked
      and em_node.inputs['Color'].links[0].from_node.type == 'BLACKBODY')
check("kelvin nodes: default temp applied",
      bb_nodes[0].inputs[0].default_value == 6500.0)
ns["lm_temperature_set"](nobj, 3000.0)
check("kelvin nodes: slider updates blackbody",
      bb_nodes[0].inputs[0].default_value == 3000.0)
check("kelvin nodes: light.color untouched",
      nobj.data.color == [1.0, 1.0, 1.0])
nobj.lm_use_temperature = False
ns["lm_use_temperature_update"](nobj, None)
check("kelvin nodes: blackbody removed",
      not any(n.type == 'BLACKBODY' for n in nobj.data.node_tree.nodes))
check("kelvin nodes: emission color restored",
      list(em_node.inputs['Color'].default_value[:3]) == [0.1, 0.2, 0.3]
      and not em_node.inputs['Color'].is_linked)

# ---------------------------------------------------------------- ies browser
class FakeIesProps:
    ies_folder = ""


ies_props = FakeIesProps()
check("ies enum: empty folder -> []", ns["ies_enum_items"](ies_props, None) == [])

ies_tmp = tempfile.mkdtemp(prefix="lampochka_ies_")
os.makedirs(os.path.join(ies_tmp, "thumbnails"))
open(os.path.join(ies_tmp, "a.ies"), "wb").close()
open(os.path.join(ies_tmp, "b.ies"), "wb").close()
open(os.path.join(ies_tmp, "thumbnails", "a.jpg"), "wb").close()
open(os.path.join(ies_tmp, "ignore.txt"), "wb").close()

ies_props.ies_folder = ies_tmp
ies_items = ns["ies_enum_items"](ies_props, None)
check("ies enum: 2 files found", len(ies_items) == 2, str(ies_items))
check("ies enum: thumbnail icon for a", ies_items and ies_items[0][3] == 42)
check("ies enum: icon name fallback for b", ies_items and ies_items[1][3] == 'LIGHT')

# ---------------------------------------------------------------- ies apply
ies_scene = types.SimpleNamespace(
    lm_ies=types.SimpleNamespace(selected_ies=os.path.join(ies_tmp, "a.ies")))
fake_light = FakeLightData()
ies_obj = FakeObj('LIGHT', fake_light)
bpy.context = types.SimpleNamespace(scene=ies_scene, active_object=ies_obj)


class IesApplyOp(ns["LM_OT_ies_apply"]):
    pass


class IesRemoveOp(ns["LM_OT_ies_remove"]):
    pass


ies_apply = IesApplyOp()
ies_apply.report = lambda t, m: print("    report:", t, m)
ies_remove = IesRemoveOp()
ies_remove.report = lambda t, m: print("    report:", t, m)

check("ies apply poll: light ok", IesApplyOp.poll(bpy.context))
rv = ies_apply.execute(bpy.context)
check("ies apply build FINISHED", rv == {"FINISHED"})
ies_types = sorted(n.type for n in fake_light.node_tree.nodes)
check("ies build: emission+output+ies",
      ies_types == ["EMISSION", "OUTPUT_LIGHT", "TEX_IES"], str(ies_types))
ies_node = fake_light.node_tree.nodes.get("LM IES")
check("ies build: marker node + filepath + mode",
      ies_node is not None and ies_node.filepath.endswith("a.ies")
      and ies_node.mode == 'EXTERNAL')

ies_scene.lm_ies.selected_ies = os.path.join(ies_tmp, "b.ies")
rv = ies_apply.execute(bpy.context)
check("ies swap FINISHED", rv == {"FINISHED"})
check("ies swap: count unchanged, filepath updated",
      len(fake_light.node_tree.nodes) == 3
      and ies_node.filepath.endswith("b.ies"))

rv = ies_remove.execute(bpy.context)
check("ies remove FINISHED", rv == {"FINISHED"})
check("ies remove: node gone",
      not any(n.type == 'TEX_IES' for n in fake_light.node_tree.nodes)
      and len(fake_light.node_tree.nodes) == 2)

rv = ies_apply.execute(bpy.context)
check("ies insert into existing chain FINISHED", rv == {"FINISHED"})
check("ies insert: emission reused, 3 nodes",
      len(fake_light.node_tree.nodes) == 3
      and any(n.type == 'EMISSION' for n in fake_light.node_tree.nodes))

ies_scene.lm_ies.selected_ies = "Z:/nope/missing.ies"
rv = ies_apply.execute(bpy.context)
check("ies apply invalid -> CANCELLED", rv == {"CANCELLED"})

# ---------------------------------------------------------------- ies prefs seed
_prefs.ies_folder = "Z:/ies_lib"
seed_scene = types.SimpleNamespace(
    lm_hdri=types.SimpleNamespace(hdri_folder=""),
    lm_ies=types.SimpleNamespace(ies_folder=""))
bpy.context = types.SimpleNamespace(
    scene=seed_scene,
    preferences=types.SimpleNamespace(addons={
        "lampochka_test": types.SimpleNamespace(preferences=_prefs)}))
ns["load_post_handler"](None)
check("load_post seeds empty ies folder from prefs",
      seed_scene.lm_ies.ies_folder == "Z:/ies_lib")

# ---------------------------------------------------------------- folder persistence
# picker writes to context.scene — point context back at the main test scene
bpy.context = types.SimpleNamespace(
    scene=_scene,
    preferences=types.SimpleNamespace(addons={
        "lampochka_test": types.SimpleNamespace(preferences=_prefs)}))


class PickOp(ns["LM_OT_hdri_pick_folder"]):
    pass


pick = PickOp()
pick.filepath = os.path.join(tmp, "hdris")
rv = pick.execute(bpy.context)
check("picker FINISHED", rv == {"FINISHED"})
expected = os.path.dirname(pick.filepath)
check("picker sets scene folder", _scene.lm_hdri.hdri_folder == expected)
check("picker remembers folder in prefs", _prefs.hdri_folder == expected)

# load_post_handler reads bpy.context (as in real Blender) — point it at fakes
fake_scene = types.SimpleNamespace(lm_hdri=types.SimpleNamespace(hdri_folder=""))
bpy.context = types.SimpleNamespace(
    scene=fake_scene,
    preferences=types.SimpleNamespace(addons={
        "lampochka_test": types.SimpleNamespace(preferences=_prefs)}))
ns["load_post_handler"](None)
check("load_post seeds empty scene from prefs",
      fake_scene.lm_hdri.hdri_folder == expected)
fake_scene.lm_hdri.hdri_folder = "Z:/keep/me"
ns["load_post_handler"](None)
check("load_post keeps non-empty scene folder",
      fake_scene.lm_hdri.hdri_folder == "Z:/keep/me")
bpy.context = types.SimpleNamespace(
    scene=types.SimpleNamespace(lm_hdri=types.SimpleNamespace(hdri_folder="")),
    preferences=types.SimpleNamespace(addons={}))
ns["load_post_handler"](None)
check("load_post without prefs -> no crash", True)
bpy.context = types.SimpleNamespace(
    scene=types.SimpleNamespace(), preferences=bpy.context.preferences)
ns["load_post_handler"](None)
check("load_post without lm_hdri -> no crash", True)

# ---------------------------------------------------------------- shift+rmb rotate
class FakeKMI:
    def __init__(self, idname, ktype, value, shift):
        self.idname = idname
        self.type = ktype
        self.value = value
        self.shift = shift


class FakeKeyMapItems:
    def __init__(self):
        self.items = []

    def new(self, idname, ktype, value, **kw):
        kmi = FakeKMI(idname, ktype, value, kw.get("shift", False))
        self.items.append(kmi)
        return kmi

    def remove(self, kmi):
        self.items.remove(kmi)


class FakeKeyMap:
    def __init__(self):
        self.keymap_items = FakeKeyMapItems()


class FakeKeyMaps:
    def __init__(self):
        self._maps = {}

    def new(self, name, space_type=None):
        if name not in self._maps:
            self._maps[name] = FakeKeyMap()
        return self._maps[name]

    def get(self, name):
        return self._maps.get(name)


addon_kc = types.SimpleNamespace(keymaps=FakeKeyMaps())
fake_window = types.SimpleNamespace(
    cursor_modal_set=lambda c: None,
    cursor_modal_restore=lambda: None,
)

_anns_h = ns["LM_HDRISettings"].__annotations__
check("shift_rmb prop present",
      isinstance(_anns_h.get("shift_rmb_rotate"), dict))

# keymap registered explicitly (register() skips when no window_manager)
bpy.context = types.SimpleNamespace(
    window_manager=types.SimpleNamespace(keyconfigs=types.SimpleNamespace(addon=addon_kc)))
ns["register_shift_rmb_keymap"]()
km3d = addon_kc.keymaps.get("3D View")
check("shift_rmb: keymap item added",
      km3d is not None and len(km3d.keymap_items.items) == 1
      and km3d.keymap_items.items[0].idname == "light_manager.hdri_shift_rmb"
      and km3d.keymap_items.items[0].type == 'RIGHTMOUSE'
      and km3d.keymap_items.items[0].shift is True)
ns["register_shift_rmb_keymap"]()
check("shift_rmb: no duplicate on re-register", len(km3d.keymap_items.items) == 1)

rmb_scene = types.SimpleNamespace(
    lm_hdri=types.SimpleNamespace(rotation=(0.2, 0.1, 0.5), shift_rmb_rotate=True))
status_texts = []
header_texts = []
modal_added = []
fake_wm = types.SimpleNamespace(modal_handler_add=lambda op: modal_added.append(op))
fake_area = types.SimpleNamespace(header_text_set=lambda t: header_texts.append(t))
bpy.context = types.SimpleNamespace(
    scene=rmb_scene,
    window=fake_window,
    window_manager=fake_wm,
    area=fake_area,
    workspace=types.SimpleNamespace(status_text_set=lambda t: status_texts.append(t)))


class RmbOp(ns["LM_OT_hdri_shift_rmb"]):
    pass


check("shift_rmb poll: on when toggled", RmbOp.poll(bpy.context) is True)
rmb_scene.lm_hdri.shift_rmb_rotate = False
check("shift_rmb poll: off when untoggled", RmbOp.poll(bpy.context) is False)
rmb_scene.lm_hdri.shift_rmb_rotate = True


def _ev(t, v='NONE', x=0, y=0):
    return types.SimpleNamespace(type=t, value=v, mouse_x=x, mouse_y=y)


rmb = RmbOp()
rv = rmb.invoke(bpy.context, _ev('RIGHTMOUSE', 'PRESS', 500, 400))
check("shift_rmb modal: invoke RUNNING + handler attached + status set",
      rv == {'RUNNING_MODAL'} and modal_added == [rmb] and len(status_texts) == 1)
rv = rmb.modal(bpy.context, _ev('INBETWEEN_MOUSEMOVE', x=600, y=350))
check("shift_rmb modal: inbetween moves handled", rv == {'RUNNING_MODAL'})
check("shift_rmb modal: Z rotation from dx, X/Y untouched",
      abs(rmb_scene.lm_hdri.rotation[2] - (0.5 + 100 * 0.006)) < 1e-6
      and rmb_scene.lm_hdri.rotation[0] == 0.2
      and rmb_scene.lm_hdri.rotation[1] == 0.1)
rv = rmb.modal(bpy.context, _ev('RIGHTMOUSE', 'RELEASE'))
check("shift_rmb modal: FINISHED on release", rv == {'FINISHED'})

rmb_scene.lm_hdri.rotation = (0.0, 0.0, 0.5)
rmb2 = RmbOp()
rmb2.invoke(bpy.context, _ev('RIGHTMOUSE', 'PRESS', 100, 100))
rv = rmb2.modal(bpy.context, _ev('ESC'))
check("shift_rmb modal: ESC restores + CANCELLED",
      rv == {'CANCELLED'} and rmb_scene.lm_hdri.rotation == (0.0, 0.0, 0.5))

ns["unregister_shift_rmb_keymap"]()
check("shift_rmb: keymap removed on unregister",
      len(km3d.keymap_items.items) == 0)
bpy.context = types.SimpleNamespace()  # no window_manager
ns["unregister_shift_rmb_keymap"]()
check("shift_rmb: no keyconfig -> no crash", True)

# ---------------------------------------------------------------- unregister
try:
    ns["unregister"]()
    check("unregister() runs", True)
except Exception:
    check("unregister() runs", False, traceback.format_exc())
check("classes unregistered", _registered == [])
check("sync handler removed", ns["sync_handler"] not in _handlers["deps"])
check("load_post handler removed", ns["load_post_handler"] not in _handlers["load"])
_pointers.remove(ns["LM_SceneSettings"])
_pointers.remove(ns["LM_HDRISettings"])
_pointers.remove(ns["LM_IESSettings"])
check("object kelvin props removed",
      not hasattr(bpy.types.Object, "lm_use_temperature")
      and not hasattr(bpy.types.Object, "lm_temperature"))

shutil.rmtree(tmp, ignore_errors=True)

print("\n=== {} passed, {} failed ===".format(len(PASS), len(FAIL)))
for name, detail in FAIL:
    print("FAILED:", name, detail)
sys.exit(1 if FAIL else 0)
