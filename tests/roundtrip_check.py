"""Apply KARUSELKA/LAMPOCHKA preset JSONs back into Blender and verify
they round-trip: compared against the original .blend (object count,
light fields, mesh geometry, parent hierarchy).
Usage: blender --background --factory-startup --python-exit-code 1 \
               --python tests/roundtrip_check.py -- <folder>

Fails (exit 1) if any preset's re-applied scene differs materially.
"""

import bpy
import json
import math
import os
import sys
import mathutils

BLEND_EXT = ".blend"
JSON_EXT = ".json"


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def make_mesh(name, mesh_data):
    data = bpy.data.meshes.new(name + "_data")
    verts = [mathutils.Vector(v) for v in mesh_data.get("verts", [])]
    data.vertices.add(len(verts))
    for i, v in enumerate(verts):
        data.vertices[i].co = v
    for (a, b) in mesh_data.get("edges", []):
        data.edges.new(a, b)
    for poly in mesh_data.get("polygons", []):
        f = data.polygons.new()
        f.vertices = list(poly.get("vertices", []))
        f.loop_start = poly.get("loop_start", 0)
        f.loop_total = poly.get("loop_total", 0)
    return data


def set_parent(obj, parent_name, by_name):
    parent = by_name.get(parent_name)
    if parent is not None:
        obj.parent = parent


def create_obj(entry, scene, by_name):
    name = entry["name"]
    otype = entry["type"]
    if otype == 'LIGHT':
        d = entry["data"]
        data = bpy.data.lights.new(name=name, type=d.get("type", 'POINT'))
        data.energy = float(d.get("energy", 100.0))
        color = d.get("color")
        if color and len(color) >= 3:
            data.color = color[:3]
        data.use_shadow = bool(d.get("use_shadow", True))
        for k in ("diffuse_factor", "specular_factor", "volume_factor"):
            if k in d and hasattr(data, k):
                setattr(data, k, float(d[k]))
        if data.type == 'POINT':
            data.shadow_soft_size = float(d.get("shadow_soft_size", 0.1))
        elif data.type == 'SPOT':
            data.spot_size = math.radians(float(d.get("spot_size", 45.0)))
            data.spot_blend = float(d.get("spot_blend", 0.15))
            data.shadow_soft_size = float(d.get("shadow_soft_size", 0.1))
        elif data.type == 'AREA':
            shape = d.get("shape", 'SQUARE')
            try:
                data.shape = shape
            except Exception:
                pass
            data.size = float(d.get("size", 0.5))
            if shape in {'RECTANGLE', 'ELLIPSE'}:
                data.size_y = float(d.get("size_y", data.size))
        elif data.type == 'SUN':
            data.angle = math.radians(float(d.get("angle", 0.526)))
        obj = bpy.data.objects.new(name=name, object_data=data)
    elif otype == 'MESH':
        data = make_mesh(name, entry["data"])
        obj = bpy.data.objects.new(name=name, object_data=data)
    elif otype == 'EMPTY':
        obj = bpy.data.objects.new(name=name, object_data=None)
        empty_disp = entry.get("data", {}).get("empty_display_type")
        if empty_disp:
            obj.empty_display_type = empty_disp
    elif otype == 'CAMERA':
        data = bpy.data.cameras.new(name)
        dobj = entry.get("data", {})
        data.lens = float(dobj.get("lens", 50.0))
        data.dof.use_dof = bool(dobj.get("use_dof", False))
        data.clip_start = float(dobj.get("clip_start", 0.1))
        data.clip_end = float(dobj.get("clip_end", 100.0))
        obj = bpy.data.objects.new(name=name, object_data=data)
    else:
        return None
    scene.collection.objects.link(obj)
    loc = entry.get("location")
    if loc and len(loc) >= 3:
        obj.location = loc[:3]
    rot = entry.get("rotation_euler")
    if rot and len(rot) >= 3:
        obj.rotation_euler = rot[:3]
    scale = entry.get("scale")
    if scale and len(scale) >= 3:
        obj.scale = scale[:3]
    by_name[name] = obj
    return obj


def apply_manifest(manifest, scene):
    by_name = {}
    for entry in manifest.get("objects", []):
        create_obj(entry, scene, by_name)
    # parents second pass (all objects exist now)
    for name, parent in manifest.get("parents", {}).items():
        obj = by_name.get(name)
        if obj is not None:
            set_parent(obj, parent, by_name)
    return by_name


def diff(a, b):
    return abs(a - b)


def check(name, cond, detail=""):
    print("  OK " if cond else "FAIL " + name + ((" -- " + str(detail)) if detail and not cond else ""))
    return cond


def compare(manifest, scene):
    """Compare the applied scene against the manifest. Returns number of fails."""
    fails = 0
    by_name = {o.name: o for o in scene.objects}
    if len(by_name) != len(manifest["objects"]):
        check("object count", False,
              f"applied {len(by_name)} vs manifest {len(manifest['objects'])}")
        fails += 1
    else:
        check("object count", True, f"{len(by_name)}")
    for entry in manifest["objects"]:
        name = entry["name"]
        obj = by_name.get(name)
        if obj is None:
            check(f"exists {name}", False)
            fails += 1
            continue
        # light fields
        if obj.type == 'LIGHT' and 'lights' in manifest:
            light_entry = next((l for l in manifest["lights"] if l["name"] == name), None)
            if light_entry:
                d = obj.data
                if abs(d.energy - light_entry["energy"]) > 1e-4:
                    check(f"light energy {name}", False, (d.energy, light_entry["energy"])); fails += 1
                if d.type != light_entry["type"]:
                    check(f"light type {name}", False, (d.type, light_entry["type"])); fails += 1
                if d.type == 'AREA' and abs(d.size - light_entry.get("size", 0)) > 1e-4:
                    check(f"area size {name}", False, (d.size, light_entry.get("size"))); fails += 1
        # location / rotation / scale
        loc = entry.get("location")
        if loc and len(loc) >= 3 and any(diff(obj.location[i], loc[i]) > 1e-4 for i in range(3)):
            check(f"loc {name}", False, (tuple(obj.location), loc)); fails += 1
        rot = entry.get("rotation_euler")
        if rot and len(rot) >= 3:
            for i in range(3):
                # normalize shortest arc
                ra, rb = obj.rotation_euler[i], rot[i]
                if diff(min((ra - rb) % math.tau, (rb - ra) % math.tau), 0) > 1e-3:
                    check(f"rot {name}", False, (ra, rb)); fails += 1
                    break
        # parent
        exp_parent = entry.get("parent")
        got_parent = obj.parent.name if obj.parent else None
        if exp_parent != got_parent:
            check(f"parent {name}", False, (got_parent, exp_parent)); fails += 1
        # mesh verts count
        if obj.type == 'MESH':
            exp_v = len(entry.get("data", {}).get("verts", []))
            if len(obj.data.vertices) != exp_v:
                check(f"mesh verts {name}", False, (len(obj.data.vertices), exp_v)); fails += 1
    return fails


def main():
    folder = sys.argv[-1]
    if not os.path.isdir(folder):
        sys.exit(f"not a folder: {folder}")
    total = 0
    for fn in sorted(os.listdir(folder)):
        name_root = os.path.splitext(fn)[0]
        blend = os.path.join(folder, name_root + BLEND_EXT)
        jpath = os.path.join(folder, name_root + JSON_EXT)
        if fn.lower().endswith(BLEND_EXT) and os.path.isfile(jpath):
            with open(jpath, encoding="utf-8") as fh:
                manifest = json.load(fh)
            scene = fresh_scene()
            try:
                apply_manifest(manifest, scene)
            except Exception as ex:
                print(f"{name_root}: APPLY ERROR -- {ex}")
                total += 1
                continue
            fails = compare(manifest, scene)
            print(f"{name_root}: {fails} fail(s)")
            total += fails
    print(f"\n=== {total} total fail(s) ===")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()