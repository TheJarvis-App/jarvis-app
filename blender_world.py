"""Blender's side of scene building (runs *inside* Blender with the rest of the kit; private names start with _w_).

  instantiate(asset, ...)    any world_library recipe (or an AI-described composite) as one object: its parts
                             merged into a single mesh, each with its material, tagged with the task it serves
  build_environment(task)    a layout from world_library made real: ground (flat, dunes, mountains, water,
                             a river), sidewalks, a room's walls with a door gap and a window, and every item
  place_objects(task)        `count` copies of an asset where the request said ("on the table", "in the room",
                             "near the fountain") or wherever is free, each standing on what's under it
  remove_task(id)            what a task made, gone (a re-run replaces only its own objects)
  scene_facts()              what the director needs: each task's objects with their bounds, functional points
                             (seats, surfaces), the walkable ground, streets
"""
import json
import math
import random

try:
    import bmesh
    import bpy
    from mathutils import Matrix, Vector
except ImportError:   # imported outside Blender (packaging checks only)
    bmesh = bpy = Matrix = Vector = None

import world_library

SCENE_ROOT = "Jarvis Scene"


def _w_root():
    root = bpy.data.objects.get(SCENE_ROOT)
    if root is None:
        root = bpy.data.objects.new(SCENE_ROOT, None)
        bpy.context.scene.collection.objects.link(root)
        root["jarvis_scene"] = "root"
        root.hide_render = True
        root.empty_display_size = 0.5
    return root


def scene_plan_get():
    root = bpy.data.objects.get(SCENE_ROOT)
    return json.loads(root["jarvis_plan"]) if root is not None and root.get("jarvis_plan") else None


def scene_plan_set(plan):
    _w_root()["jarvis_plan"] = json.dumps(plan)
    return True


def _w_tag(o, task_id, role, asset=None):
    o["jarvis_scene"] = task_id
    o["jarvis_scene_role"] = role
    if asset:
        o["jarvis_asset"] = asset
    return o


def _w_windows_material(name, night=False):
    """A facade of windows: a grid (brick texture in object space) of panes, some lit, over dark glass; how bright
    the lit ones glow is the material's "glow" input, which lighting changes for night."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = material(name, color=(0.1, 0.11, 0.13), roughness=0.15, metallic=0.4)
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    coord = nt.nodes.new('ShaderNodeTexCoord')
    mapping = nt.nodes.new('ShaderNodeMapping')
    nt.links.new(coord.outputs['Object'], mapping.inputs['Vector'])
    brick = nt.nodes.new('ShaderNodeTexBrick')
    brick.offset = 0.0
    brick.inputs['Scale'].default_value = 1.0
    brick.inputs['Mortar Size'].default_value = 0.25
    brick.inputs['Brick Width'].default_value = 3.0
    brick.inputs['Row Height'].default_value = 3.6
    brick.inputs['Color1'].default_value = (1.0, 0.82, 0.55, 1.0)
    brick.inputs['Color2'].default_value = (0.05, 0.05, 0.06, 1.0)
    brick.inputs['Mortar'].default_value = (0.0, 0.0, 0.0, 1.0)
    nt.links.new(mapping.outputs['Vector'], brick.inputs['Vector'])
    glow = nt.nodes.new('ShaderNodeValue')
    glow.name = glow.label = "glow"
    glow.outputs[0].default_value = 2.5 if night else 0.0
    mult = nt.nodes.new('ShaderNodeMath')
    mult.operation = 'MULTIPLY'
    nt.links.new(brick.outputs['Fac'], mult.inputs[0])
    nt.links.new(glow.outputs[0], mult.inputs[1])
    em_color = next(s for s in bsdf.inputs if s.name in ("Emission Color", "Emission"))
    em_strength = bsdf.inputs.get("Emission Strength")
    nt.links.new(brick.outputs['Color'], em_color)
    if em_strength is not None:
        nt.links.new(mult.outputs[0], em_strength)
    mat["jarvis_windows"] = True
    return mat


def _w_material(key, color=None, style=None):
    if key == "windows":
        return _w_windows_material("Jarvis windows" + (" futuristic" if style == "futuristic" else ""))
    look = dict(world_library.MATERIALS.get(key, world_library.MATERIALS["plastic"]))
    name = f"Jarvis {key}"
    if color is not None:
        look["color"] = color
        name += " " + "-".join(f"{c:.2f}" for c in color)
    return material(name, **look)


def _w_part_geom(bm, part):
    """Add one recipe part to `bm`; returns its faces."""
    shape = part["shape"]
    sx, sy, sz = part["size"]
    before = set(bm.faces)
    if shape == "box":
        geom = bmesh.ops.create_cube(bm, size=1.0)
        verts = geom["verts"]
        for v in verts:
            v.co = Vector((v.co.x * sx, v.co.y * sy, (v.co.z + 0.5) * sz))
    elif shape == "cyl":
        top = part.get("top")
        r1 = sx / 2
        r2 = (top / 2) if top is not None else r1
        geom = bmesh.ops.create_cone(bm, cap_ends=True, segments=part.get("segments", 24), radius1=r1,
                                     radius2=max(r2, 0.0005), depth=sz)
        verts = geom["verts"]
        for v in verts:
            v.co = Vector((v.co.x * (sx / max(sx, 1e-9)), v.co.y * (sy / max(sx, 1e-9)), v.co.z + sz / 2))
    else:
        geom = bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.5)
        verts = geom["verts"]
        for v in verts:
            v.co = Vector((v.co.x * sx, v.co.y * sy, v.co.z * sz))
    rot = part.get("rot")
    m = Matrix.Translation(Vector(part["at"]))
    if rot:
        m = m @ (Matrix.Rotation(math.radians(rot[2]), 4, 'Z') @ Matrix.Rotation(math.radians(rot[1]), 4, 'Y') @
                 Matrix.Rotation(math.radians(rot[0]), 4, 'X'))
    bmesh.ops.transform(bm, matrix=m, verts=verts)
    return [f for f in bm.faces if f not in before]


def instantiate(asset, name=None, at=(0, 0, 0), yaw=0.0, scale=1.0, params=None, color=None, task_id="", role="object",
                recipe=None):
    """One object made from a recipe (world_library.recipe(asset, params), or `recipe` itself for a composite):
    every part merged into a single mesh with its own material, its origin at the centre of its bottom."""
    params = dict(params or {})
    if color is not None and isinstance(color, str):
        color = world_library.COLORS.get(color)
    r = recipe or world_library.recipe(asset, params)
    bm = bmesh.new()
    keys = []
    for part in r["parts"]:
        faces = _w_part_geom(bm, part)
        key = part.get("mat", "plastic")
        if key not in keys:
            keys.append(key)
        for f in faces:
            f.material_index = keys.index(key)
            f.smooth = part["shape"] != "box"
    me = bpy.data.meshes.new(name or asset)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name or asset.replace("_", " ").title(), me)
    bpy.context.scene.collection.objects.link(o)
    paint_main = color is not None
    for key in keys:
        # the request's colour goes on the main body (painted parts and the first material), not on tyres or glass
        tinted = paint_main and key in ("paint", "plastic", "chrome", "fabric", "wood", "ceramic", "red", "metal",
                                        "cardboard") and key == keys[0]
        me.materials.append(_w_material(key, color if tinted else None, params.get("style")))
    o.location = Vector(at)
    o.rotation_euler = (0.0, 0.0, math.radians(yaw))
    o.scale = (scale, scale, scale)
    _w_tag(o, task_id, role, asset)
    meta = {k: r[k] for k in ("seat", "surface", "moves", "speed", "glows", "sways", "spins", "solid", "flat", "prop",
                              "category") if k in r}
    meta["size"] = [v * scale for v in r["size"]]
    o["jarvis_meta"] = json.dumps(meta)
    if any(p.get("bevel") for p in r["parts"]):
        m = o.modifiers.new("Rounded", 'BEVEL')
        m.width = max(p.get("bevel") or 0 for p in r["parts"])
        m.segments = 2
        m.limit_method = 'ANGLE'
    return o


def remove_task(task_id):
    """Every object a task made (and its now unused data), removed."""
    gone = [o for o in bpy.data.objects if o.get("jarvis_scene") == task_id]
    for o in gone:
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if data is not None and getattr(data, "users", 1) == 0:
            try:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Light):
                    bpy.data.lights.remove(data)
                elif isinstance(data, bpy.types.Camera):
                    bpy.data.cameras.remove(data)
            except (ReferenceError, RuntimeError):
                pass
    return len(gone)


def _w_ground(task_id, g, kind):
    """The ground an environment stands on: a plane (subdivided and displaced into dunes or mountains when the
    layout asks), water, a river."""
    w, d = g["size"]
    made = []
    bm = bmesh.new()
    cuts = 90 if (g.get("dunes") or g.get("mountains")) else 1
    bmesh.ops.create_grid(bm, x_segments=cuts + 1, y_segments=cuts + 1, size=0.5)
    for v in bm.verts:
        v.co.x *= w
        v.co.y *= d
    rng = random.Random(7)
    if g.get("dunes") or g.get("mountains"):
        amp = 2.5 if g.get("dunes") else 14.0
        waves = [(rng.uniform(0.02, 0.06), rng.uniform(0.02, 0.06), rng.uniform(0, 6.28), rng.uniform(0.4, 1.0))
                 for _ in range(6)]
        for v in bm.verts:
            x, y = v.co.x, v.co.y
            h = sum(a * math.sin(x * fx + ph) * math.cos(y * fy - ph) for fx, fy, ph, a in waves) / 3
            r = math.hypot(x, y)
            if g.get("mountains"):   # flat in the middle (where things stand), rising toward the edges
                h = max(0.0, h + 0.6) * min(1.0, max(0.0, (r - 30) / 40)) * amp
            else:
                h = (h + 0.5) * amp * min(1.0, r / 25)
            v.co.z = max(0.0, h)
    me = bpy.data.meshes.new(f"{task_id} ground")
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(f"{kind.title()} ground", me)
    bpy.context.scene.collection.objects.link(o)
    me.materials.append(_w_material(g.get("material", "grass")))
    if g.get("mountains"):
        me.materials.append(_w_material("snow"))
        for p in me.polygons:
            if p.center.z > 9.0:
                p.material_index = 1
    _w_tag(o, task_id, "ground")
    made.append(o)
    if g.get("water"):
        y0 = g["water"]["from_y"]
        wat = instantiate("road", f"{kind.title()} water", (0, y0 + d / 4, -0.15), params={"width": w, "length": d / 2},
                          task_id=task_id, role="water")
        wat.data.materials.clear()
        wat.data.materials.append(_w_material("water"))
        made.append(wat)
    return made


def _w_river(task_id, bounds):
    """A river across an environment: a band of water sunk a little into the ground, curving gently."""
    x0, y0, x1, y1 = bounds
    pts = []
    n = 40
    for i in range(n + 1):
        t = i / n
        x = x0 - 20 + (x1 - x0 + 40) * t
        pts.append((x, (y0 + y1) / 2 * 0.3 + 6.0 * math.sin(t * 5.0)))
    bm = bmesh.new()
    width = 5.0
    left_, right_ = [], []
    for i, (x, y) in enumerate(pts):
        a = pts[max(0, i - 1)]
        b = pts[min(n, i + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        left_.append(bm.verts.new((x + nx * width / 2, y + ny * width / 2, 0.04)))
        right_.append(bm.verts.new((x - nx * width / 2, y - ny * width / 2, 0.04)))
    for i in range(n):
        bm.faces.new((left_[i], right_[i], right_[i + 1], left_[i + 1]))
    me = bpy.data.meshes.new(f"{task_id} river")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("River", me)
    bpy.context.scene.collection.objects.link(o)
    me.materials.append(_w_material("water"))
    _w_tag(o, task_id, "water")
    o["jarvis_path"] = json.dumps(pts)
    return o, pts


def _w_room(task_id, room):
    """Floor, four walls (a door gap in the front, a window in the left), a ceiling and a light under it."""
    w, d, h = room["width"], room["depth"], room["height"]
    t = 0.15
    door, window = room["door"], room["window"]
    boxes = {"floor": [((-w / 2, -d / 2, -0.1), (w / 2, d / 2, 0.0))],
             "ceiling": [((-w / 2 - t, -d / 2 - t, h), (w / 2 + t, d / 2 + t, h + 0.12))]}
    walls = [((-w / 2 - t, d / 2, 0), (w / 2 + t, d / 2 + t, h)),                       # back
             ((w / 2, -d / 2 - t, 0), (w / 2 + t, d / 2 + t, h))]                       # right
    dw = door["width"] / 2
    walls += [((-w / 2 - t, -d / 2 - t, 0), (-dw, -d / 2, h)), ((dw, -d / 2 - t, 0), (w / 2 + t, -d / 2, h)),
              ((-dw, -d / 2 - t, door["height"]), (dw, -d / 2, h))]                     # front, with the doorway
    ww, wy = window["width"] / 2, 0.0
    s0, s1 = window["sill"], window["sill"] + window["height"]
    walls += [((-w / 2 - t, -d / 2 - t, 0), (-w / 2, wy - ww, h)), ((-w / 2 - t, wy + ww, 0), (-w / 2, d / 2 + t, h)),
              ((-w / 2 - t, wy - ww, 0), (-w / 2, wy + ww, s0)), ((-w / 2 - t, wy - ww, s1), (-w / 2, wy + ww, h))]
    boxes["wall"] = walls
    made = []
    for role, bs in boxes.items():
        o = _boxes_mesh(f"Room {role}", bs)
        o.data.materials.append(_w_material({"floor": "wood", "ceiling": "plaster", "wall": "plaster"}[role]))
        _w_tag(o, task_id, "floor" if role == "floor" else "wall" if role == "wall" else "ceiling")
        made.append(o)
    glass = _boxes_mesh("Room window", [((-w / 2 - t / 2 - 0.01, wy - ww, s0), (-w / 2 - t / 2 + 0.01, wy + ww, s1))])
    glass.data.materials.append(_w_material("glass"))
    _w_tag(glass, task_id, "glass")
    made.append(glass)
    light = bpy.data.lights.new("Room light", 'AREA')
    light.energy = 180.0
    light.size = 1.2
    light.color = (1.0, 0.9, 0.78)
    lo = bpy.data.objects.new("Room light", light)
    bpy.context.scene.collection.objects.link(lo)
    lo.location = (0.0, 0.0, h - 0.05)
    _w_tag(lo, task_id, "light")
    made.append(lo)
    return made


def build_environment(task):
    """The environment `task` asks for, built (replacing what an earlier run of it made). Returns its facts."""
    if isinstance(task, str):
        task = json.loads(task)
    tid = task["id"]
    remove_task(tid)
    kind = task.get("type", "ground")
    if kind == "ground":   # just somewhere to stand
        g = {"size": [80, 80], "material": "grass"}
        _w_ground(tid, g, "ground")
        return {"task": tid, "kind": "ground", "objects": 1, "bounds": [-40, -40, 40, 40]}
    params = {k: task.get(k) for k in ("style", "size", "density", "seed", "room", "furniture", "furniture_for")
              if task.get(k)}
    if kind == "room" and task.get("furniture") is None:
        params["furniture"] = task.get("furniture_default") or world_library.ROOM_FURNITURE.get(
            task.get("room") or "room", world_library.ROOM_FURNITURE["room"])
    lay = world_library.layout(kind, params)
    made = []
    g = lay["ground"]
    if g.get("room"):
        made += _w_room(tid, g["room"])
    else:
        made += _w_ground(tid, g, kind)
    if g.get("sidewalks"):
        bs = [((x + 0.5, y + 0.5, 0.0), (x + blk - 0.5, y + blk - 0.5, 0.18)) for x, y, blk in g["sidewalks"]["blocks"]]
        side = _boxes_mesh(f"{kind.title()} sidewalks", bs)
        side.data.materials.append(_w_material("concrete"))
        _w_tag(side, tid, "sidewalk")
        made.append(side)
    for i, item in enumerate(lay["items"]):
        z = 0.18 if g.get("sidewalks") and item["asset"] in ("skyscraper",) else 0.0
        if g.get("sidewalks") and item["asset"] == "streetlight":
            z = 0.18
        o = instantiate(item["asset"], f"{item['asset'].replace('_', ' ').title()} {i + 1}", (item["at"][0], item["at"][1], z),
                        item.get("yaw", 0), item.get("scale", 1.0), item.get("params"), task_id=tid,
                        role=item.get("role", "item"))
        if item.get("for"):
            o["jarvis_for"] = item["for"]
        made.append(o)
    if "river" in (task.get("features") or []) and kind != "room":
        river, pts = _w_river(tid, lay["bounds"])
        made.append(river)
        # nothing stands in the river
        for o in list(made):
            if o.get("jarvis_scene_role") in ("nature", "item") and o.type == 'MESH':
                if any(math.hypot(o.location.x - x, o.location.y - y) < 4.5 for x, y in pts):
                    bpy.data.objects.remove(o, do_unlink=True)
                    made.remove(o)
        lay["river"] = pts
    root = _w_root()
    envs = json.loads(root.get("jarvis_envs", "{}"))
    envs[tid] = {"kind": kind, "bounds": lay["bounds"], "streets": lay.get("streets", []),
                 "street_width": lay.get("street_width", 0.0), "room": g.get("room"), "river": lay.get("river")}
    root["jarvis_envs"] = json.dumps(envs)
    _sync()
    return {"task": tid, "kind": kind, "objects": len(made), "bounds": lay["bounds"],
            "items": len(lay["items"]), "streets": len(lay.get("streets", []))}


# ---------- placing things ----------

def _w_meta(o):
    try:
        return json.loads(o.get("jarvis_meta", "{}"))
    except ValueError:
        return {}


def _w_bounds2(o):
    lo, hi = box(o)
    return (lo.x, lo.y, hi.x, hi.y), lo, hi


def _w_task_objects(task_id):
    return [o for o in bpy.context.scene.objects if o.get("jarvis_scene") == task_id and o.type == 'MESH']


def _w_obstacles(exclude=()):
    out = []
    for o in bpy.context.scene.objects:
        if o.type != 'MESH' or not o.visible_get() or o.name in exclude:
            continue
        role = o.get("jarvis_scene_role") or o.get("jarvis_role") or ""
        if role in ("ground", "floor", "water", "sidewalk", "road", "path", "ceiling") or "ground" in o.name.lower():
            continue
        if _w_meta(o).get("flat"):
            continue
        if o.get("jarvis_anim"):
            continue
        out.append(o)
    return out


def _w_floor_z(x, y, start=None, exclude=()):
    """Height of the walkable floor under (x, y) — the ground, a room's floor, a sidewalk — not a roof or a tree
    crown above it."""
    deps = bpy.context.evaluated_depsgraph_get()
    z0 = 3.0 if start is None else start
    origin = Vector((x, y, z0))
    for _ in range(6):
        hit, loc, normal, index, obj, mat = bpy.context.scene.ray_cast(deps, origin, Vector((0, 0, -1)), distance=200)
        if not hit:
            return 0.0
        role = obj.get("jarvis_scene_role") or obj.get("jarvis_role") or ""
        if role in ("ground", "floor", "sidewalk", "road", "path", "slab", "steps", "foundation", "deck") or \
                "ground" in obj.name.lower() or obj.name in exclude:
            if obj.name not in exclude:
                return loc.z
        origin = loc - Vector((0, 0, 0.01))
    return 0.0


def _w_footprints(exclude=()):
    fps = []
    for o in _w_obstacles(exclude):
        (x0, y0, x1, y1), lo, hi = _w_bounds2(o)
        fps.append((x0, y0, x1, y1))
    return fps


def _w_free_spot(size, area, taken, rng, gap=0.4, tries=200):
    w, d = size[0], size[1]
    for _ in range(tries):
        x = rng.uniform(area[0] + w / 2, area[2] - w / 2)
        y = rng.uniform(area[1] + d / 2, area[3] - d / 2)
        fp = (x - w / 2, y - d / 2, x + w / 2, y + d / 2)
        if not any(world_library.overlaps(fp, t, gap) for t in taken):
            taken.append(fp)
            return x, y
    return None


def place_objects(task, near=None):
    """`task`'s objects placed: on a surface ("on the table": its top), near another thing, inside the room or
    environment that's there, clear of everything; each set down on what's beneath it."""
    if isinstance(task, str):
        task = json.loads(task)
    if isinstance(near, str):
        near = json.loads(near) if near else None
    tid = task["id"]
    remove_task(tid)
    asset = task["asset"]
    rng = random.Random(hash(tid) % 1000 + 3)
    r = world_library.recipe(asset, {"style": task.get("style")}) if asset != "composite" else {
        "parts": task["parts"], "size": _w_composite_size(task["parts"]), "category": "object"}
    if asset == "composite":
        r["asset"] = "composite"
    size = r["size"]
    count = int(task.get("count") or 1)
    scale = {"small": 0.7, "large": 1.4, "huge": 2.0}.get(task.get("size"), 1.0)
    envs = json.loads(_w_root().get("jarvis_envs", "{}"))
    area = None
    room = next((e for e in envs.values() if e.get("room")), None)
    if room:
        rr = room["room"]
        area = (-rr["width"] / 2 + 0.3, -rr["depth"] / 2 + 1.3, rr["width"] / 2 - 0.3, rr["depth"] / 2 - 0.3)
    elif envs:
        b = next(iter(envs.values()))["bounds"]
        area = tuple(b)
    else:
        area = (-12, -12, 12, 12)
    taken = _w_footprints()
    made = []
    surface = None
    if near and near.get("surface") is not None:
        surface = near
    for i in range(count):
        name = (task.get("name") or asset.replace("_", " ")).title() + (f" {i + 1}" if count > 1 else "")
        if surface is not None:   # on the table: spread over its top, clear of its edges
            sx0, sy0, sx1, sy1 = surface["rect"]
            x = sx0 + (sx1 - sx0) * (i + 1) / (count + 1)
            y = sy0   # near the edge people come to it from, within reach
            z = surface["surface"]
        else:
            if near and near.get("at"):
                nx, ny = near["at"][:2]
                local = (nx - 4, ny - 4, nx + 4, ny + 4)
                spot = _w_free_spot((size[0] * scale, size[1] * scale), local, taken, rng)
            else:
                spot = None
            streets = [ln for e in envs.values() for ln in (e.get("streets") or [])]
            if spot is None and r.get("moves") in ("fly", "drive") and streets:
                # something that travels starts out in the open: on a street, not against a building
                ln = streets[(len(streets) // 2 + i) % len(streets)]
                t_ = 0.3 + 0.1 * i
                spot = (ln[0][0] + (ln[-1][0] - ln[0][0]) * t_, ln[0][1] + (ln[-1][1] - ln[0][1]) * t_)
            if spot is None:
                spot = _w_free_spot((size[0] * scale, size[1] * scale), area, taken, rng)
            if spot is None:
                spot = (area[0] + rng.uniform(0, 1) * (area[2] - area[0]), area[1] + rng.uniform(0, 1) * (area[3] - area[1]))
            x, y = spot
            z = _w_floor_z(x, y, 3.0 if room else 60.0)
        moves = r.get("moves")
        if moves == "fly" and surface is None:
            z += 0.0
        o = instantiate(asset, name, (x, y, z), rng.choice((0, 90, 180, 270)) if asset not in ("table", "sofa", "bed")
                        else 0, scale, {"style": task.get("style")}, task.get("color"), tid, "object",
                        recipe=r if asset == "composite" else None)
        o["jarvis_home"] = json.dumps([round(v, 4) for v in o.location])   # where its journeys start
        made.append(o.name)
    _sync()
    return {"task": tid, "made": made, "size": size}


def _w_composite_size(parts):
    lo = [min(p["at"][i] - (p["size"][i] / 2 if i < 2 else 0) for p in parts) for i in range(3)]
    hi = [max(p["at"][i] + (p["size"][i] / 2 if i < 2 else p["size"][2]) for p in parts) for i in range(3)]
    return [hi[i] - lo[i] for i in range(3)]


def scene_facts():
    """Each task's objects (name, bounds, centre, functional points), the environments' extra facts, and builds."""
    _sync()
    tasks = {}
    for o in bpy.context.scene.objects:
        tid = o.get("jarvis_scene")
        if not tid or tid == "root":
            continue
        entry = tasks.setdefault(tid, [])
        if o.get("jarvis_for"):   # made by a room for an object task: that task's too
            entry = tasks.setdefault(o["jarvis_for"], [])
        if o.type == 'MESH':
            lo, hi = box(o)
            meta = _w_meta(o)
            e = {"name": o.name, "role": o.get("jarvis_scene_role"), "asset": o.get("jarvis_asset"),
                 "lo": [round(v, 3) for v in lo], "hi": [round(v, 3) for v in hi],
                 "at": [round(v, 3) for v in o.location], "yaw": round(math.degrees(o.rotation_euler.z), 1)}
            if meta.get("seat"):
                e["seat"] = meta["seat"]
            if meta.get("surface"):
                e["surface"] = round(lo.z + meta["surface"] * o.scale.z, 3)
            if meta.get("moves"):
                e["moves"] = meta["moves"]
                e["speed"] = meta.get("speed")
            entry.append(e)
        else:
            entry.append({"name": o.name, "role": o.get("jarvis_scene_role"), "type": o.type,
                          "at": [round(v, 3) for v in o.matrix_world.translation]})
    root = bpy.data.objects.get(SCENE_ROOT)
    builds = sorted({o.get("jarvis_build") for o in bpy.context.scene.objects if o.get("jarvis_build")})
    return {"tasks": tasks, "envs": json.loads(root.get("jarvis_envs", "{}")) if root else {}, "builds": builds,
            "frames": [bpy.context.scene.frame_start, bpy.context.scene.frame_end]}


def inspect_scene(task_ids=None):
    """Measured facts about what the plan made: every task has its objects, nothing floats above what's under it
    or sinks into it, no two solid things of different tasks stand inside each other, every material works."""
    if isinstance(task_ids, str):
        task_ids = json.loads(task_ids)
    _sync()
    objs = [o for o in bpy.context.scene.objects if o.get("jarvis_scene") and o.get("jarvis_scene") != "root"
            and o.type == 'MESH' and (task_ids is None or o.get("jarvis_scene") in task_ids)]
    by_task = {}
    for o in objs:
        by_task.setdefault(o["jarvis_scene"], []).append(o)
    floating, sunk, clashes, no_mat = [], [], [], []
    trees = _w_world_trees()
    ground_roles = ("ground", "floor", "water", "sidewalk", "road", "ceiling", "wall", "glass", "light")
    solids = []
    for o in objs:
        role = o.get("jarvis_scene_role")
        if role in ground_roles:
            continue
        lo, hi = box(o)
        meta = _w_meta(o)
        if meta.get("moves") in ("fly",) and lo.z > 1.0:
            continue
        support = _w_support_z(o, lo, trees)
        gap = lo.z - support
        if gap > 0.05:
            floating.append([o.name, round(gap, 3)])
        if gap < -0.25 and role not in ("nature",):
            sunk.append([o.name, round(-gap, 3)])
        if not meta.get("flat") and meta.get("category") not in ("prop",):
            solids.append((o, lo, hi))
        if not [s for s in o.material_slots if s.material]:
            no_mat.append(o.name)
    for i, (a, alo, ahi) in enumerate(solids):
        for b, blo, bhi in solids[i + 1:]:
            ox = min(ahi.x, bhi.x) - max(alo.x, blo.x)
            oy = min(ahi.y, bhi.y) - max(alo.y, blo.y)
            oz = min(ahi.z, bhi.z) - max(alo.z, blo.z)
            if ox > 0.08 and oy > 0.08 and oz > 0.08:
                # a prop on a table is "on", not inside: only volumes that really cross
                if _w_really_overlap(a, b):
                    clashes.append([a.name, b.name])
    return {"objects": len(objs), "tasks": {t: len(v) for t, v in by_task.items()}, "floating": floating[:12],
            "sunk": sunk[:12], "clashes": clashes[:12], "no_material": no_mat[:12]}


def _w_world_trees():
    """A BVH of each visible mesh, in world space: what something stands on is looked for among the others only
    (a ray cast through the scene meets the object's own underside first)."""
    from mathutils.bvhtree import BVHTree
    deps = bpy.context.evaluated_depsgraph_get()
    trees = {}
    for o in bpy.context.scene.objects:
        if o.type != 'MESH' or not o.visible_get() or o.get("jarvis_fx"):
            continue
        ev = o.evaluated_get(deps)
        try:
            me = ev.to_mesh()
        except RuntimeError:
            continue
        m = o.matrix_world
        verts = [m @ v.co for v in me.vertices]
        polys = [list(p.vertices) for p in me.polygons]
        ev.to_mesh_clear()
        if polys:
            trees[o.name] = BVHTree.FromPolygons(verts, polys)
    return trees


def _w_support_z(o, lo, trees):
    """What `o` stands on: the highest surface of any other object under its footprint, or the ground (0)."""
    (x0, y0, x1, y1), _, _ = _w_bounds2(o)
    best = None
    for fx, fy in ((0.5, 0.5), (0.25, 0.25), (0.75, 0.75), (0.25, 0.75), (0.75, 0.25)):
        p = Vector((x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fy, lo.z + 0.03))
        for name, tree in trees.items():
            if name == o.name:
                continue
            hit = tree.ray_cast(p, Vector((0, 0, -1)), 100.0)
            if hit[0] is not None:
                best = hit[0].z if best is None else max(best, hit[0].z)
    return best if best is not None else 0.0


def _w_really_overlap(a, b):
    """Whether two objects' meshes really intersect (their boxes overlapping isn't enough: a chair under a table)."""
    from mathutils.bvhtree import BVHTree
    deps = bpy.context.evaluated_depsgraph_get()
    ta = BVHTree.FromObject(a, deps)
    tb = BVHTree.FromObject(b, deps)
    if ta is None or tb is None:
        return False
    # FromObject is in object space: bring b into a's space
    mat = a.matrix_world.inverted() @ b.matrix_world
    verts = [mat @ v.co for v in b.evaluated_get(deps).data.vertices] if b.type == 'MESH' else []
    polys = [list(p.vertices) for p in b.data.polygons]
    if not verts:
        return False
    tb2 = BVHTree.FromPolygons(verts, polys)
    return bool(ta.overlap(tb2))
