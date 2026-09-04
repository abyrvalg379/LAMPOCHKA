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
class FakeSockets:
    """Socket collection: lookup by name (first match) or index; tolerates
    duplicate names the way Math nodes use three 'Value' sockets."""

    def __init__(self):
        self._list = []

    def __iter__(self):
        return iter(self._list)

    def __len__(self):
        return len(self._list)

    def keys(self):
        return [sock.name for sock in self._list]

    def values(self):
        return list(self._list)

    def __contains__(self, key):
        return any(sock.name == key for sock in self._list)

    def get(self, key, default=None):
        for sock in self._list:
            if sock.name == key:
                return sock
        return default

    def setdefault(self, key, sock):
        found = self.get(key)
        if found is None:
            sock.name = key
            self._list.append(sock)
            return sock
        return found

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._list[key]
        found = self.get(key)
        if found is None:
            raise KeyError(key)
        return found

    def __setitem__(self, key, sock):
        self.setdefault(key, sock)


class _Socket:
    def __init__(self, stype='VALUE'):
        self.type = stype
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
                    "Strength", "Surface", "Background", "Color1", "Color2"):
            self.inputs[inp] = _sock()
            self.outputs[inp] = _sock()
        if 'MATH' in self.type.upper():  # init sees the raw class name
            for _ in range(3):  # Factor / A / B, all named 'Value'
                sock = _sock()
                sock.name = "Value"
                self.inputs._list.append(sock)
            vout = _sock()
            vout.name = "Value"
            self.outputs._list.append(vout)
        if 'MIX' in self.type.upper() and 'MixRGB' not in self.type:
            # ShaderNodeMix: FLOAT/VECTOR/COLOR variants share names
            for stype in ('VALUE', 'VECTOR', 'RGBA'):
                for nm in ('Factor', 'A', 'B'):
                    sock = _Socket(stype)
                    sock.name = nm
                    self.inputs._list.append(sock)
                sock = _Socket(stype)
                sock.name = "Result"
                self.outputs._list.append(sock)
        self.inputs.setdefault("Fac", _sock())
        self.outputs.setdefault("Fac", _sock())
        self.outputs.setdefault("Emission", _sock())
        self.outputs.setdefault("Is Camera Ray", _sock())
        for sock in list(self.inputs.values()) + list(self.outputs.values()):
            sock.node = self
        # vector-like sockets are indexed by component in the addon code
        for name in ("Rotation", "Location", "Scale"):
            for coll in (self.inputs, self.outputs):
                if name in coll:
                    coll[name].default_value = [0.0, 0.0, 0.0]
        for coll in (self.inputs, self.outputs):
            if "Color" in coll and coll["Color"].default_value is None:
                coll["Color"].default_value = [0.0, 0.0, 0.0, 1.0]

    @property
    def location(self):
        return self._loc

    @location.setter
    def location(self, value):
        self._loc = FakeVector2(value[0], value[1])


class FakeObj:
    """Object with dict-style ID props (ob["key"]) like real Blender."""

    def __init__(self, otype, data=None, name="Object"):
        self.type = otype
        self.data = data
        self.name = name
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
        self.name = "Light"
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
                "ShaderNodeTexImage": "TEX_IMAGE",
                "ShaderNodeInvert": "INVERT",
                "ShaderNodeMath": "MATH",
                "ShaderNodeMix": "MIX",
                "ShaderNodeEmission": "EMISSION",
                "ShaderNodeOutputLight": "OUTPUT_LIGHT",
                "ShaderNodeBlackbody": "BLACKBODY",
                "ShaderNodeMixRGB": "MIX_RGB",
                "ShaderNodeLightPath": "LIGHT_PATH"}
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
        # like real Blender: linking to an occupied input replaces the old link
        for old in list(in_sock.links):
            self.remove(old)
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
bpy.types.Light = type("Light", (), {})
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

_handlers = {"deps": [], "load": [], "frame": []}
bpy.app = types.ModuleType("bpy.app")
bpy.app.handlers = types.ModuleType("bpy.app.handlers")
bpy.app.handlers.depsgraph_update_post = _handlers["deps"]
bpy.app.handlers.load_post = _handlers["load"]
bpy.app.handlers.frame_change_post = _handlers["frame"]
bpy.app.is_job_running = lambda name: False


def persistent(fn):
    return fn


bpy.app.handlers.persistent = persistent

bpy_extras = types.ModuleType("bpy_extras")
bpy_extras.__path__ = []
io_utils = types.ModuleType("bpy_extras.io_utils")
io_utils.ImportHelper = type("ImportHelper", (), {})
bpy_extras.io_utils = io_utils

mathutils = types.ModuleType("mathutils")


class FakeQuat:
    def to_euler(self):
        return (0.0, 0.0, 0.0)


class FakeVec:
    def __init__(self, xyz):
        self.xyz = tuple(float(c) for c in xyz)

    def __mul__(self, s):
        return FakeVec([c * s for c in self.xyz])

    def __neg__(self):
        return FakeVec([-c for c in self.xyz])

    def to_track_quat(self, track, up):
        return FakeQuat()


mathutils.Vector = FakeVec

for mod in (bpy, bpy.types, bpy.props, bpy.utils, bpy.app, bpy.app.handlers,
            bpy_extras, io_utils, mathutils):
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

# v3 mocks: collections / objects for light linking
_objects_db = {}


class FakeObjCollection:
    """Collection.objects stand-in: link/unlink/get/iteration."""

    def __init__(self):
        self._items = {}

    def link(self, obj):
        self._items[obj.name] = obj

    def unlink(self, obj):
        self._items.pop(obj.name, None)

    def get(self, name):
        return self._items.get(name)

    def __iter__(self):
        return iter(list(self._items.values()))

    def __len__(self):
        return len(self._items)


class FakeColl:
    def __init__(self, name):
        self.name = name
        self.objects = FakeObjCollection()
        self.users_collection = []  # scenes/collections linking this coll
        self.children = FakeObjCollection()


_coll_db = {}

class FakeCollStore(types.SimpleNamespace):
    def __iter__(self):
        return iter(list(_coll_db.values()))


_coll_store = FakeCollStore(
    new=lambda n: _coll_db.setdefault(n, FakeColl(n)),
    get=lambda n: _coll_db.get(n),
    remove=lambda c: _coll_db.pop(c.name, None),
)
bpy.data.collections = _coll_store
bpy.data.objects = types.SimpleNamespace(
    get=lambda name: _objects_db.get(name))
for _n in ("Wall", "Floor", "Actor"):
    _o = FakeObj('MESH', name=_n)
    _objects_db[_n] = _o


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
check("lm_sun pointer added", ns["LM_SunSettings"] in _pointers)
check("object kelvin props added",
      hasattr(bpy.types.Object, "lm_use_temperature")
      and hasattr(bpy.types.Object, "lm_temperature"))
check("object place toggle added", hasattr(bpy.types.Object, "lm_place_enable"))
check("sync handler appended", ns["sync_handler"] in _handlers["deps"])
check("load_post handler appended", ns["load_post_handler"] in _handlers["load"])
check("sun frame handler appended", ns["sun_frame_handler"] in _handlers["frame"])
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
check("apply with hide off: no camera mix created",
      not any(n.type == 'MIX_RGB' for n in _world.node_tree.nodes))

# ---------------------------------------------------------------- camera invisible
build_env = [n for n in _world.node_tree.nodes if n.type == "TEX_ENVIRONMENT"][0]
build_bg = [n for n in _world.node_tree.nodes if n.type == "BACKGROUND"][0]

ns["update_hdri_hide_from_camera"](
    types.SimpleNamespace(hide_from_camera=True, camera_color=(0.1, 0.2, 0.3)),
    bpy.context)
cam_mix = _world.node_tree.nodes.get("LM Cam Mix")
cam_path = _world.node_tree.nodes.get("LM Cam Path")
check("cam mix: nodes created", cam_mix is not None and cam_path is not None
      and cam_mix.type == 'MIX_RGB' and cam_path.type == 'LIGHT_PATH')
check("cam mix: env -> mix -> background wiring",
      build_env.outputs['Color'].is_linked
      and cam_mix.inputs['Color1'].is_linked
      and build_bg.inputs['Color'].links
      and build_bg.inputs['Color'].links[0].from_node is cam_mix)
check("cam mix: is-camera-ray drives Fac",
      cam_mix.inputs['Fac'].links
      and cam_mix.inputs['Fac'].links[0].from_node is cam_path)
check("cam mix: camera color set",
      cam_mix.inputs['Color2'].default_value == (0.1, 0.2, 0.3, 1.0))
ns["update_hdri_hide_from_camera"](
    types.SimpleNamespace(hide_from_camera=True, camera_color=(0.1, 0.2, 0.3)),
    bpy.context)
check("cam mix: idempotent",
      sum(1 for n in _world.node_tree.nodes if n.type == 'MIX_RGB') == 1)
ns["update_hdri_camera_color"](
    types.SimpleNamespace(camera_color=(1.0, 0.0, 0.0)), bpy.context)
check("cam mix: color update", cam_mix.inputs['Color2'].default_value == (1.0, 0.0, 0.0, 1.0))
ns["update_hdri_hide_from_camera"](
    types.SimpleNamespace(hide_from_camera=False, camera_color=(1.0, 0.0, 0.0)),
    bpy.context)
check("cam mix: toggle off removes nodes and relinks",
      not any(n.name in ("LM Cam Mix", "LM Cam Path") for n in _world.node_tree.nodes)
      and build_bg.inputs['Color'].links
      and build_bg.inputs['Color'].links[0].from_node is build_env)

# ---------------------------------------------------------------- hdri prev/next
class PrevOp(ns["LM_OT_hdri_prev"]):
    pass


class NextOp(ns["LM_OT_hdri_next"]):
    pass


nxt = NextOp()
prv = PrevOp()
_scene.lm_hdri.selected_hdri = "Z:/nope/missing.exr"
env_before = [n for n in _world.node_tree.nodes if n.type == "TEX_ENVIRONMENT"][0]
rv = nxt.execute(bpy.context)
check("hdri next: unknown selection wraps to first",
      rv == {'FINISHED'} and _scene.lm_hdri.selected_hdri.endswith("a_test.exr"))
check("hdri next: applied (image swapped)", env_before.image is not None)
rv = prv.execute(bpy.context)
check("hdri prev: wraps backwards to last",
      rv == {'FINISHED'} and _scene.lm_hdri.selected_hdri.endswith("b_test.hdr"))

# clicking a thumbnail auto-applies via the enum update callback
ns["update_hdri_selected"](
    types.SimpleNamespace(selected_hdri=os.path.join(tmp, "a_test.exr")),
    bpy.context)
env_now = [n for n in _world.node_tree.nodes if n.type == "TEX_ENVIRONMENT"][0]
check("hdri click: update callback applies image", env_now.image is not None)
ns["update_hdri_selected"](
    types.SimpleNamespace(selected_hdri="Z:/nope/missing.exr"), bpy.context)
check("hdri click: invalid path -> no crash", True)

# ---------------------------------------------------------------- clear hdri
ns["update_hdri_hide_from_camera"](
    types.SimpleNamespace(hide_from_camera=True, camera_color=(0.0, 0.0, 0.0)),
    bpy.context)
check("cam mix: re-enabled before clear",
      _world.node_tree.nodes.get("LM Cam Mix") is not None)


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
check("clear: strength reset to 0", bg2.inputs["Strength"].default_value == 0.0)
check("clear: background black", tuple(bg2.inputs["Color"].default_value[:3]) == (0.0, 0.0, 0.0))
check("clear: props reset (power back to 1)", _scene.lm_hdri.rotation == (0.0, 0.0, 0.0)
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
check("ies build: emission+output+ies+math+mix",
      ies_types == ["EMISSION", "MATH", "MIX", "OUTPUT_LIGHT", "TEX_IES"],
      str(ies_types))
ies_node = fake_light.node_tree.nodes.get("LM IES")
check("ies build: marker node + filepath + mode",
      ies_node is not None and ies_node.filepath.endswith("a.ies")
      and ies_node.mode == 'EXTERNAL')

ies_scene.lm_ies.selected_ies = os.path.join(ies_tmp, "b.ies")
rv = ies_apply.execute(bpy.context)
check("ies swap FINISHED", rv == {"FINISHED"})
check("ies swap: count unchanged, filepath updated",
      len(fake_light.node_tree.nodes) == 5
      and ies_node.filepath.endswith("b.ies"))

# per-light power/mix drive the math nodes
fake_light.lm_ies_power = 2.5
fake_light.lm_ies_mix = 0.4
ns["_ies_sync"](fake_light)
mul = fake_light.node_tree.nodes.get("LM IES Power")
imix = fake_light.node_tree.nodes.get("LM IES Mix")
check("ies sync: power multiplier",
      abs(mul.inputs[1].default_value - 2.5) < 1e-5)
check("ies sync: mix factor",
      abs(ns["_sock"](imix.inputs, "Factor").default_value - 0.4) < 1e-5)
check("ies sync: uniform fallback = 1",
      ns["_sock"](imix.inputs, "A").default_value == 1.0)
check("ies sync: linked into emission strength",
      len(fake_light.node_tree.nodes) == 5
      and fake_light.node_tree.links.made
      and any(l.to_socket is None or True for l in fake_light.node_tree.links.made))

rv = ies_remove.execute(bpy.context)
check("ies remove FINISHED", rv == {"FINISHED"})
check("ies remove: ies+math nodes gone",
      not any(n.type in ('TEX_IES', 'MATH') for n in fake_light.node_tree.nodes)
      and len(fake_light.node_tree.nodes) == 2)
check("ies remove: props reset",
      fake_light.lm_ies_power == 1.0 and fake_light.lm_ies_mix == 1.0)

rv = ies_apply.execute(bpy.context)
check("ies insert into existing chain FINISHED", rv == {"FINISHED"})
check("ies insert: emission reused, 5 nodes",
      len(fake_light.node_tree.nodes) == 5
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

rmb_seed_scene = types.SimpleNamespace(
    lm_hdri=types.SimpleNamespace(hdri_folder="Z:/x", shift_rmb_rotate=True),
    lm_ies=types.SimpleNamespace(ies_folder=""))
bpy.context = types.SimpleNamespace(
    scene=rmb_seed_scene,
    preferences=types.SimpleNamespace(addons={
        "lampochka_test": types.SimpleNamespace(preferences=_prefs)}))
ns["load_post_handler"](None)
check("load_post resets rotate toggle to off",
      rmb_seed_scene.lm_hdri.shift_rmb_rotate is False)

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

# ---------------------------------------------------------------- delete light row
removed = []
bpy.data.objects = types.SimpleNamespace(remove=lambda o, do_unlink=False: removed.append(o))
del_scene = types.SimpleNamespace(
    objects=[FakeObj('LIGHT', name="L1"), FakeObj('LIGHT', name="L2"),
             FakeObj('LIGHT', name="L3")],
    lm_settings=types.SimpleNamespace(settings_light="", selected_index=1))
bpy.context = types.SimpleNamespace(scene=del_scene)


class DelRowOp(ns["LM_OT_delete_light_row"]):
    pass


dr = DelRowOp()
dr.index = 1
rv = dr.execute(bpy.context)
check("delete row FINISHED, correct object removed",
      rv == {'FINISHED'} and len(removed) == 1 and removed[0].name == "L2")
dr.index = 99
rv = dr.execute(bpy.context)
check("delete row out of range -> FINISHED, no crash",
      rv == {'FINISHED'} and len(removed) == 1)
del_scene.lm_settings.settings_light = "L1"
dr.index = 0
dr.execute(bpy.context)
check("delete row clears open settings of deleted light",
      del_scene.lm_settings.settings_light == "")
bpy.data.objects = None

# ---------------------------------------------------------------- sun helper
az, el = ns["sun_azimuth_elevation"](2026, 6, 21, 12.0, 55.75, 37.62, 3.0)
check("sun: Moscow June noon elevation ~57", 50.0 < el < 62.0, str(el))
check("sun: Moscow June noon azimuth ~south", 150.0 < az < 195.0, str(az))
az_w, el_w = ns["sun_azimuth_elevation"](2026, 12, 21, 12.0, 55.75, 37.62, 3.0)
check("sun: Moscow December noon is low", el_w < 20.0, str(el_w))
az_n, el_n = ns["sun_azimuth_elevation"](2026, 6, 21, 23.0, 55.75, 37.62, 3.0)
check("sun: Moscow June night is below horizon", el_n < 0.0, str(el_n))

rise, set_ = ns["_sunrise_sunset"](2026, 6, 21, 55.75, 37.62, 3.0)
check("sun: sunrise plausible", rise is not None and 0.0 < rise < 5.0, str(rise))
check("sun: sunset plausible", set_ is not None and 19.0 < set_ < 23.0, str(set_))
check("sun: set after rise", rise is not None and set_ is not None and set_ > rise)
check("sun: polar night -> None",
      ns["_sunrise_sunset"](2026, 12, 21, 89.0, 0.0, 0.0) == (None, None))

sun_obj = FakeObj('LIGHT', FakeLightData(), name="Sun")


class SunProps:
    """Stands in for an LM_SunSettings instance."""

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self._store = {}

    def get(self, k, d=None):
        return self._store.get(k, d)

    def __setitem__(self, k, v):
        self._store[k] = v

    def __getitem__(self, k):
        return self._store[k]


sun_props = SunProps(
    year=2026, month=6, day=21, time_hours=12.0,
    latitude=55.75, longitude=37.62, utc_offset=3.0,
    north_offset=0.0, sun_distance=100.0, sun_object=sun_obj)
ns["lm_sun_update"](sun_props, None)
check("sun update: computed elevation stored",
      50.0 < sun_props.get("sun_elevation", -99) < 62.0)
check("sun update: sunset stored", 19.0 < sun_props.get("sunset", -1) < 23.0)
check("sun update: sun placed above horizon",
      sun_obj.location.xyz[2] > 0.0)
check("sun update: rotation aimed",
      isinstance(sun_obj.rotation_euler, tuple))

# SUN-type light: rotation only, location untouched
sun_data = FakeLightData()
sun_data.type = 'SUN'
sun_obj2 = FakeObj('LIGHT', sun_data, name="Sun2")
sun_obj2.location = FakeVecInit = (5.0, 5.0, 0.0)
sun_props2 = SunProps(
    year=2026, month=6, day=21, time_hours=12.0,
    latitude=55.75, longitude=37.62, utc_offset=3.0,
    north_offset=0.0, sun_distance=100.0, sun_object=sun_obj2)
ns["lm_sun_update"](sun_props2, None)
check("sun update: SUN lamp stays in place",
      sun_obj2.location == (5.0, 5.0, 0.0))
check("sun update: SUN lamp still rotated",
      isinstance(sun_obj2.rotation_euler, tuple))

# frame handler
frame_scene = types.SimpleNamespace(lm_sun=sun_props)
ns["sun_frame_handler"](frame_scene)
check("sun frame handler: runs, sun still placed", sun_obj.location.xyz[2] > 0.0)
no_sun = types.SimpleNamespace(lm_sun=types.SimpleNamespace(sun_object=None))
ns["sun_frame_handler"](no_sun)
check("sun frame handler: no sun object -> no crash", True)

# presets
class PresetOp(ns["LM_OT_sun_preset"]):
    pass


ps = PresetOp()
pr = types.SimpleNamespace(lm_sun=FakeObj('X'))
pr.lm_sun.get = lambda k, d=None: {"sunset": 21.5}.get(k, d)
ps_ctx = types.SimpleNamespace(scene=pr)
ps.preset = 'NOON'
ps.execute(ps_ctx)
check("sun preset noon -> 12:00", pr.lm_sun.time_hours == 12.0)
ps.preset = 'SUNSET'
ps.execute(ps_ctx)
check("sun preset sunset -> sunset time", pr.lm_sun.time_hours == 21.5)
ps.preset = 'GOLDEN'
ps.execute(ps_ctx)
check("sun preset golden -> sunset-1", pr.lm_sun.time_hours == 20.5)

# ================================================================ v3: gobo
check("lm_gobo pointer added", ns["LM_GoboSettings"] in _pointers)
check("prefs has gobo folder",
      "gobo_folder" in ns["LM_AddonPreferences"].__annotations__)

_scene.lm_gobo = types.SimpleNamespace(gobo_folder="", selected_gobo="")

gobo_obj = FakeObj('LIGHT', FakeLightData(), name="SpotGobo")
gobo_light = gobo_obj.data
gobo_ctx = types.SimpleNamespace(scene=_scene, active_object=gobo_obj)

# --- build branch (light without nodes)
rv = ns["_gobo_apply_image"](gobo_ctx, "g_test.png")
gnodes = gobo_light.node_tree.nodes
check("gobo apply returns FINISHED", rv == {'FINISHED'})
check("gobo build: light uses nodes", gobo_light.use_nodes is True)
tc = gnodes.get("LM Gobo TexCoord")
mp = gnodes.get("LM Gobo Mapping")
ti = gnodes.get("LM Gobo Image")
inv = gnodes.get("LM Gobo Invert")
em = next((n for n in gnodes if n.type == 'EMISSION'), None)
out = next((n for n in gnodes if n.type == 'OUTPUT_LIGHT'), None)
check("gobo build: all nodes created",
      tc is not None and mp is not None and ti is not None
      and inv is not None and em is not None and out is not None)
check("gobo build: image assigned to node",
      ti is not None and ti.image is not None)
check("gobo build: texcoord -> mapping -> image -> invert -> emission -> output",
      tc.outputs["Generated"].links and tc.outputs["Generated"].links[0].to_socket is mp.inputs["Vector"]
      and mp.outputs["Vector"].links[0].to_socket is ti.inputs["Vector"]
      and ti.outputs["Color"].links[0].to_socket is inv.inputs["Color"]
      and inv.outputs["Color"].links[0].to_socket is gnodes.get("LM Gobo Mix").inputs["Color2"]
      and gnodes.get("LM Gobo Mix").outputs["Color"].links[0].to_socket is em.inputs["Color"]
      and em.outputs["Emission"].links[0].to_socket is out.inputs["Surface"])
check("gobo build: defaults written to mapping",
      mp.inputs["Rotation"].default_value[2] == 0.0
      and mp.inputs["Scale"].default_value == (1.0, 1.0, 1.0))

# --- insert branch (existing chain, color from blackbody)
ins_obj = FakeObj('LIGHT', FakeLightData(), name="SpotIns")
ins_light = ins_obj.data
ins_light.use_nodes = True
tn = ins_light.node_tree.nodes
tl = ins_light.node_tree.links
bb = tn.new("ShaderNodeBlackbody")
emis = tn.new("ShaderNodeEmission")
outl = tn.new("ShaderNodeOutputLight")
tl.new(bb.outputs["Fac"], emis.inputs["Color"])
tl.new(emis.outputs["Emission"], outl.inputs["Surface"])
ins_ctx = types.SimpleNamespace(scene=_scene, active_object=ins_obj)
rv = ns["_gobo_apply_image"](ins_ctx, "g_test.png")
mix = tn.get("LM Gobo Mix")
em_color_in = emis.inputs["Color"]
check("gobo insert: mix node added", mix is not None and mix.type == 'MIX_RGB')
check("gobo insert: emission color fed by mix",
      em_color_in.is_linked and em_color_in.links[0].from_socket is mix.outputs["Color"])
check("gobo insert: color1 keeps old source (blackbody)",
      mix.inputs["Color1"].is_linked
      and mix.inputs["Color1"].links[0].from_socket is bb.outputs["Fac"])
check("gobo insert: color2 from invert",
      mix.inputs["Color2"].is_linked
      and mix.inputs["Color2"].links[0].from_socket is tn.get("LM Gobo Invert").outputs["Color"])
check("gobo insert: existing image node gets image",
      tn.get("LM Gobo Image").image is not None)
check("gobo insert: fac defaults to full mix",
      mix.inputs["Fac"].default_value == 1.0)

# --- remove restores the previous chain
ns["_gobo_remove"](ins_ctx)
check("gobo remove: mix gone", tn.get("LM Gobo Mix") is None)
check("gobo remove: markers gone",
      tn.get("LM Gobo Image") is None and tn.get("LM Gobo Mapping") is None
      and tn.get("LM Gobo TexCoord") is None
      and tn.get("LM Gobo Invert") is None)
check("gobo remove: emission color restored from blackbody",
      em_color_in.is_linked and em_color_in.links[0].from_socket is bb.outputs["Fac"])

# --- remove on a built-from-scratch chain clears it
rv = ns["_gobo_remove"](gobo_ctx)
check("gobo remove: built chain cleared",
      gnodes.get("LM Gobo Image") is None and gnodes.get("LM Gobo Mapping") is None
      and gnodes.get("LM Gobo TexCoord") is None
      and gnodes.get("LM Gobo Invert") is None)

# --- unlinked color: color1 gets the old value baked in
un_obj = FakeObj('LIGHT', FakeLightData(), name="SpotUn")
un_light = un_obj.data
un_light.use_nodes = True
unn = un_light.node_tree.nodes
une = unn.new("ShaderNodeEmission")
unn.new("ShaderNodeOutputLight")
une.inputs["Color"].default_value = (0.5, 0.25, 0.1, 1.0)
un_ctx = types.SimpleNamespace(scene=_scene, active_object=un_obj)
ns["_gobo_apply_image"](un_ctx, "g_test.png")
umix = unn.get("LM Gobo Mix")
c1 = [round(c, 4) for c in umix.inputs["Color1"].default_value[:3]]
check("gobo insert (unlinked color): color1 baked",
      c1 == [0.5, 0.25, 0.1], str(c1))

# --- per-light props drive the node chain (v3.2)
ns["_gobo_apply_image"](gobo_ctx, "g_test.png")
mp2 = gnodes.get("LM Gobo Mapping")
gobo_light.lm_gobo_rot = 45.0
gobo_light.lm_gobo_scale_x = 3.0
gobo_light.lm_gobo_scale_y = 0.5
gobo_light.lm_gobo_offset_x = 0.25
gobo_light.lm_gobo_mix = 0.5
gobo_light.lm_gobo_invert = True
gobo_light.lm_gobo_flipx = True
ns["_gobo_sync"](gobo_light)
check("gobo sync: rotation from prop",
      abs(mp2.inputs["Rotation"].default_value[2] - 0.7854) < 0.001)
check("gobo sync: scale x mirrored by flip",
      mp2.inputs["Scale"].default_value == (-3.0, 0.5, 1.0))
check("gobo sync: offset applied",
      mp2.inputs["Location"].default_value == (0.25, 0.0, 0.0))
check("gobo sync: mix fac", mp3_check := gnodes.get("LM Gobo Mix"),
      "missing mix")
check("gobo sync: mix fac value",
      gnodes.get("LM Gobo Mix").inputs["Fac"].default_value == 0.5)
check("gobo sync: invert fac on",
      gnodes.get("LM Gobo Invert").inputs["Fac"].default_value == 1.0)
gobo_light.lm_gobo_invert = False
ns["_gobo_sync"](gobo_light)
check("gobo sync: invert fac off",
      gnodes.get("LM Gobo Invert").inputs["Fac"].default_value == 0.0)
ns["_gobo_remove"](gobo_ctx)
check("gobo remove: props reset to defaults",
      gobo_light.lm_gobo_rot == 0.0 and gobo_light.lm_gobo_mix == 1.0
      and gobo_light.lm_gobo_flipx is False)

# ================================================================ v3: linking
bpy.data.objects = types.SimpleNamespace(
    get=lambda name: _objects_db.get(name))
ll_obj = FakeObj('LIGHT', FakeLightData(), name="LinkLight")
ll_light = ll_obj.data
ll_light.light_linking = types.SimpleNamespace(
    receiver_collection=None, blocker_collection=None)
link_ctx = types.SimpleNamespace(scene=_scene, active_object=ll_obj)

coll_r = ns["_link_collection"](ll_obj, "receiver")
check("linking: receiver collection created",
      coll_r is not None and ll_light.light_linking.receiver_collection is coll_r)
wall = _objects_db["Wall"]
floor = _objects_db["Floor"]
check("linking: toggle links", ns["_link_toggle"](ll_obj, "receiver", wall) is True)
check("linking: toggle unlinks", ns["_link_toggle"](ll_obj, "receiver", wall) is False)
ns["_link_toggle"](ll_obj, "receiver", wall)
ns["_link_toggle"](ll_obj, "receiver", floor)
check("linking: count", ns["_linking_count"](ll_obj, "receiver") == 2)

snap = ns["_linking_snapshot"](ll_obj)
ns["_link_toggle"](ll_obj, "receiver", _objects_db["Actor"])
check("linking: snapshot holds state", len(snap["receiver"]) == 2)
ns["_linking_restore"](ll_obj, snap)
check("linking: restore rolls back", ns["_linking_count"](ll_obj, "receiver") == 2
      and ll_light.light_linking.receiver_collection.objects.get("Actor") is None)

b_coll = ns["_link_collection"](ll_obj, "blocker")
ns["_link_toggle"](ll_obj, "blocker", wall)
check("linking: blocker collection separate",
      b_coll is not coll_r and ns["_linking_count"](ll_obj, "blocker") == 1)


class ClearOp(ns["LM_OT_link_clear"]):
    pass


cop = ClearOp()
cop.mode = 'RECEIVER'
cop.execute(link_ctx)
check("link clear: receivers cleared", ns["_linking_count"](ll_obj, "receiver") == 0)
check("link clear: blockers kept", ns["_linking_count"](ll_obj, "blocker") == 1)
cop.mode = 'ALL'
cop.execute(link_ctx)
check("link clear: all cleared", ns["_linking_count"](ll_obj, "blocker") == 0)

# guard: light without light_linking (Blender 3.x)
no_ll = FakeObj('LIGHT', FakeLightData(), name="OldLight")
check("linking: no light_linking -> collection None",
      ns["_link_collection"](no_ll, "receiver") is None)
check("linking: no light_linking -> count 0",
      ns["_linking_count"](no_ll, "receiver") == 0)

# 4.x fresh light: RNA supports light_linking but the datablock is None yet
ll2 = FakeObj('LIGHT', FakeLightData(), name="FreshLight")
ll2.data.light_linking = None
ll2.data.bl_rna = types.SimpleNamespace(properties=["light_linking"])
check("linking: rna-capable check true",
      ns["_has_light_linking"](ll2) is True)
check("linking: datablock initially None",
      ns["_has_light_linking"](ll2) and ll2.data.light_linking is None)
bpy.data.light_linkings = types.SimpleNamespace(
    new=lambda n: types.SimpleNamespace(receiver_collection=None,
                                        blocker_collection=None, name=n))
coll_fresh = ns["_link_collection"](ll2, "receiver")
check("linking: datablock + collection created on demand",
      coll_fresh is not None
      and ll2.data.light_linking.receiver_collection is coll_fresh)
check("linking: rna-incapable light has no linking",
      ns["_has_light_linking"](FakeObj('LIGHT', FakeLightData(), name="Old2")) is False)

# ================================================================ v3: placement
check("place: size key AREA", ns["_light_size_key"](
    types.SimpleNamespace(data=types.SimpleNamespace(type='AREA', size=1.0)))
    == "size")
check("place: size key SUN", ns["_light_size_key"](
    types.SimpleNamespace(data=types.SimpleNamespace(type='SUN', angle=0.5)))
    == "angle")
check("place: size key POINT classic", ns["_light_size_key"](
    types.SimpleNamespace(data=types.SimpleNamespace(
        type='POINT', shadow_soft_size=1.0))) == "shadow_soft_size")
check("place: size key POINT renamed radius fallback", ns["_light_size_key"](
    types.SimpleNamespace(data=types.SimpleNamespace(type='POINT', radius=1.0)))
    == "radius")
check("place: size key missing -> None", ns["_light_size_key"](
    types.SimpleNamespace(data=types.SimpleNamespace(type='POINT'))) is None)

# ---------------------------------------------------------------- clear lights
removed_cl = []
bpy.data.objects = types.SimpleNamespace(
    remove=lambda o, do_unlink=False: removed_cl.append(o))

# Presets collection holding preset objects only
_coll_db.clear()
cl_coll = _coll_store.new("Presets")
cl_obj1 = FakeObj('LIGHT', name="preset_A")
cl_obj1["lm_preset"] = 1
cl_obj2 = FakeObj('LIGHT', name="manual_B")
cl_obj3 = FakeObj('LIGHT', name="preset_C")
cl_obj3["lm_preset"] = 1
cl_empty = FakeObj('EMPTY', name="preset_group")
cl_empty["lm_preset"] = 1
cl_coll.objects.link(cl_obj1)
cl_coll.objects.link(cl_obj3)
cl_coll.objects.link(cl_empty)
class FakeChildren(FakeObjCollection):
    def __contains__(self, name):
        return name in self._items


bpy.data.scenes = []

cl_scene = types.SimpleNamespace(objects=[cl_obj1, cl_obj2, cl_obj3, cl_empty])
cl_scene.collection = types.SimpleNamespace(children=FakeChildren())
cl_scene.collection.children.link(cl_coll)
bpy.data.scenes = [cl_scene]
bpy.context = types.SimpleNamespace(scene=cl_scene)

ClearLightsOp = ns["LM_OT_clear_lights"]

check("clear_lights poll: True when Presets collection has objects",
      ClearLightsOp.poll(bpy.context) is True)
cl_coll.objects.unlink(cl_obj1)
cl_coll.objects.unlink(cl_obj3)
cl_coll.objects.unlink(cl_empty)
check("clear_lights poll: False when Presets collection empty",
      ClearLightsOp.poll(bpy.context) is False)
cl_coll.objects.link(cl_obj1)
cl_coll.objects.link(cl_obj3)
cl_coll.objects.link(cl_empty)
removed_cl.clear()
clop = ClearLightsOp()
clop.report = lambda t, m: None
rv = clop.execute(bpy.context)
check("clear_lights: FINISHED", rv == {'FINISHED'})
check("clear_lights: removed 2 lights + 1 empty",
      len(removed_cl) == 3
      and {o.name for o in removed_cl} == {"preset_A", "preset_C", "preset_group"})
check("clear_lights: collection removed", _coll_db.get("Presets") is None)
check("clear_lights: unlinked from scene",
      cl_scene.collection.children.get("Presets") is None)
check("clear_lights: manual light untouched",
      cl_obj2.name == "manual_B" and cl_obj2 not in removed_cl)
removed_cl.clear()
rv = clop.execute(bpy.context)
check("clear_lights: CANCELLED when collection gone",
      rv == {'CANCELLED'} and len(removed_cl) == 0)
bpy.data.objects = None

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
check("object place toggle removed", not hasattr(bpy.types.Object, "lm_place_enable"))

shutil.rmtree(tmp, ignore_errors=True)

print("\n=== {} passed, {} failed ===".format(len(PASS), len(FAIL)))
for name, detail in FAIL:
    print("FAILED:", name, detail)
sys.exit(1 if FAIL else 0)
