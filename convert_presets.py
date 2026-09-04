#!/usr/bin/env python
"""Convert LAMPOCHKA preset .blend files into JSON.

Reads every .blend in a folder, serializes only LIGHT objects in the
exact format produced by _collect_lights_json() inside the addon, and
writes <name>.json beside each source file.

Output format — LAMPOCHKA v3.1 compatible:

{
  "name": ...,
  "version": 1,
  "app": "LAMPOCHKA 3.1+",
  "author": ...,
  "created": ...,
  "lights": [ {LAMPOCHKA-serialized LIGHT}, ... ]
}

Usage: "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" \
       --background --factory-startup --python-exit-code 1 \
       --python convert_presets.py -- <folder>
"""

import bpy

import getpass
import json
import math
import os
import sys
import datetime

BLEND_EXT = ".blend"
JSON_EXT = ".json"


def _ser_light(ob):
    """Serialize one LIGHT object in exact _collect_lights_json format."""
    data = ob.data
    entry = {
        "name": ob.name,
        "type": data.type,
        "energy": data.energy,
        "color": [round(c, 5) for c in data.color],
        "use_shadow": data.use_shadow,
        "location": [round(v, 5) for v in ob.location],
        "rotation": [round(v, 5) for v in ob.rotation_euler],
    }
    for key in ("diffuse_factor", "specular_factor", "volume_factor"):
        value = getattr(data, key, None)
        if value is not None:
            entry[key] = round(float(value), 5)
    if data.type == 'POINT':
        entry["shadow_soft_size"] = data.shadow_soft_size
    elif data.type == 'SPOT':
        entry["spot_size"] = round(math.degrees(data.spot_size), 3)
        entry["spot_blend"] = data.spot_blend
        entry["shadow_soft_size"] = data.shadow_soft_size
    elif data.type == 'AREA':
        entry["shape"] = data.shape
        entry["size"] = data.size
        if data.shape in {'RECTANGLE', 'ELLIPSE'}:
            entry["size_y"] = data.size_y
    elif data.type == 'SUN':
        entry["angle"] = round(math.degrees(data.angle), 3)
    try:
        if ob.lm_use_temperature:
            entry["kelvin"] = ob.lm_temperature
    except Exception:
        pass
    if data.use_nodes and data.node_tree is not None:
        ies = data.node_tree.nodes.get('LM IES')
        if ies is not None and ies.type == 'TEX_IES' and ies.filepath:
            entry["ies_path"] = bpy.path.abspath(ies.filepath)
        gobo = data.node_tree.nodes.get('LM Gobo Image')
        if (gobo is not None and gobo.type == 'TEX_IMAGE'
                and gobo.image is not None and gobo.image.filepath):
            entry["gobo_path"] = bpy.path.abspath(gobo.image.filepath)
    return entry


def _tree_contains_light(coll, cache):
    """True if the collection directly or indirectly holds a light."""
    if coll.name in cache:
        return cache[coll.name]
    cache[coll.name] = (any(ob.type == 'LIGHT' for ob in coll.objects)
                        or any(_tree_contains_light(ch, cache)
                               for ch in coll.children))
    return cache[coll.name]


def convert_one(path):
    """Convert one .blend into a list of JSON dicts (one per setup).

    PLS-style libraries keep every named setup in its own collection,
    often NOT linked to the scene — so the whole file is scanned and
    setups are split by the top-most collections that contain lights.
    Loose lights (outside such collections) go to a file-level preset.
    """
    bpy.ops.wm.open_mainfile(filepath=path)
    try:
        author = getpass.getuser()
    except Exception:
        author = ""
    base = os.path.splitext(os.path.basename(path))[0]
    created = datetime.datetime.now().isoformat(timespec="seconds")

    cache = {}
    containers = {c.name for c in bpy.data.collections
                  if _tree_contains_light(c, cache)}
    # top-most containers only: children belong to the parent's setup
    child_names = {ch.name for c in bpy.data.collections
                   if c.name in containers
                   for ch in c.children}
    roots = {c.name: c for c in bpy.data.collections
             if c.name in containers and c.name not in child_names}

    # child collection -> parent collections (no parent pointers in API)
    parents = {}
    for c in bpy.data.collections:
        for ch in c.children:
            parents.setdefault(ch.name, []).append(c.name)

    assigned = {name: [] for name in roots}
    loose = []
    for ob in bpy.data.objects:
        if ob.type != 'LIGHT':
            continue
        seen = set()
        queue = list(ob.users_collection)
        root = None
        while queue:
            cur = queue.pop()
            if cur.name in seen:
                continue
            seen.add(cur.name)
            if cur.name in roots and root is None:
                root = cur.name
            queue.extend(parents.get(cur.name, []))
        if root is not None:
            assigned[root].append(_ser_light(ob))
        else:
            loose.append(_ser_light(ob))

    def make_json(name, lights):
        return {
            "name": name,
            "version": 1,
            "app": "LAMPOCHKA 3.1+",
            "author": author,
            "created": created,
            "lights": lights,
        }

    out = []
    for name in sorted(assigned):
        if assigned[name]:
            out.append(make_json(name, assigned[name]))
    if loose:
        out.append(make_json(base + " (loose)", loose))
    return out


def main():
    folder = sys.argv[-1]
    if not os.path.isdir(folder):
        sys.exit(f"not a folder: {folder}")
    used = set()
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith(BLEND_EXT):
            continue
        path = os.path.join(folder, fn)
        for manifest in convert_one(path):
            safe = manifest["name"].replace(" ", "_")
            if safe.lower() in used:
                # generic collection names repeat across library files
                safe = os.path.splitext(fn)[0][:12] + "__" + safe
                if safe.lower() in used:
                    continue
            used.add(safe.lower())
            out = os.path.join(folder, safe + JSON_EXT)
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2)
            print(f"{fn} -> {os.path.basename(out)} "
                  f"({len(manifest['lights'])} lights)")


if __name__ == "__main__":
    main()
