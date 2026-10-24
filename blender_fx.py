"""Blender's side of what moves and how it's seen (runs inside Blender with the kit; private names start with _fx_).

  animate_motion(task)       a thing travelling (fly / drive / sail / move / orbit / spin / hover / bounce) along
                             a route found through the scene's real free space, relative to what was named ("between
                             the skyscrapers", "around the castle", "along the street", "over the desert")
  set_weather(tasks)         rain and snow as Geometry Nodes driven by time (the same on every frame, no
                             simulation cache), fog, storm lightning, wind, wet surfaces
  set_lighting(task)         time of day: sun, sky, exposure; at night windows and lamps light up
  set_camera(task)           follow / orbit / establishing / closeup / static / cinematic (a cut sequence), keyed
                             per frame from where the subject really is, keeping a clear line of sight to it
  render_frames / render_video_chunk / encode_video          stills, a video in chunks, one MP4
  inspect_motion_paths / inspect_camera / subject_coverage / rain_visible                    measured checks
"""
import json
import math
import os
import random

try:
    import bmesh
    import bpy
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree
except ImportError:   # imported outside Blender (packaging checks only)
    bmesh = bpy = Matrix = Vector = BVHTree = None

import anim_library
import world_library

FX_FPS = anim_library.FPS


def _fx_scene():
    return bpy.context.scene


def _fx_objects_of(task_id):
    return [o for o in _fx_scene().objects if o.get("jarvis_scene") == task_id and o.type in ('MESH', 'ARMATURE')]


def _fx_meta(o):
    try:
        return json.loads(o.get("jarvis_meta", "{}"))
    except ValueError:
        return {}


def _fx_bvh(objs):
    deps = bpy.context.evaluated_depsgraph_get()
    verts, polys = [], []
    for o in objs:
        if o.type != 'MESH':
            continue
        ev = o.evaluated_get(deps)
        try:
            me = ev.to_mesh()
        except RuntimeError:
            continue
        m = o.matrix_world
        base = len(verts)
        verts += [m @ v.co for v in me.vertices]
        polys += [[base + i for i in p.vertices] for p in me.polygons]
        ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys) if polys else None


def _fx_obstacles(exclude=()):
    out = []
    for o in _fx_scene().objects:
        if o.type != 'MESH' or not o.visible_get() or o.name in exclude:
            continue
        role = o.get("jarvis_scene_role") or o.get("jarvis_role") or ""
        if role in ("ground", "floor", "water", "sidewalk", "road", "path", "weather", "ceiling") or \
                o.get("jarvis_fx") or "ground" in o.name.lower():
            continue
        if _fx_meta(o).get("flat"):
            continue
        out.append(o)
    return out


def _fx_ground(x, y, z_top=200.0):
    deps = bpy.context.evaluated_depsgraph_get()
    origin = Vector((x, y, z_top))
    for _ in range(8):
        hit, loc, n, i, obj, m = _fx_scene().ray_cast(deps, origin, Vector((0, 0, -1)), distance=z_top + 50)
        if not hit:
            return 0.0
        role = obj.get("jarvis_scene_role") or obj.get("jarvis_role") or ""
        if role in ("ground", "floor", "sidewalk", "road", "path", "water", "slab", "steps") or \
                "ground" in obj.name.lower() or _fx_meta(obj).get("flat"):
            return loc.z
        origin = loc - Vector((0, 0, 0.02))
    return 0.0


# ---------- routes ----------

def _fx_targets(target):
    """The objects a step's target names."""
    if not target:
        return []
    scene = _fx_scene()
    if target.get("task"):
        objs = [o for o in scene.objects if (o.get("jarvis_scene") == target["task"] or o.get("jarvis_for") ==
                                             target["task"]) and o.type in ('MESH', 'ARMATURE')]
        if not objs:   # a build (the villa) is a task of the plan made by blender_build
            build = next((o.get("jarvis_build") for o in scene.objects if o.get("jarvis_plan_task") == target["task"]),
                         None)
            objs = [o for o in scene.objects if build and o.get("jarvis_build") == build and o.type == 'MESH']
        if target.get("items"):
            want = target["items"]
            objs = [o for o in objs if (o.get("jarvis_scene_role") or "") == want] or objs
        return [o for o in objs if (o.get("jarvis_scene_role") or "") not in ("ground", "sidewalk", "water")] or objs
    if target.get("asset"):
        return [o for o in scene.objects if o.get("jarvis_asset") == target["asset"]]
    return []


def _fx_env():
    root = bpy.data.objects.get("Jarvis Scene")
    envs = json.loads(root.get("jarvis_envs", "{}")) if root else {}
    return next(iter(envs.values()), None)


def _fx_catmull(points, samples=8):
    if len(points) < 3:
        out = []
        for a, b in zip(points, points[1:]):
            for k in range(samples):
                t = k / samples
                out.append(a.lerp(b, t))
        out.append(points[-1])
        return out
    pts = [points[0]] + list(points) + [points[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for k in range(samples):
            t = k / samples
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
                              (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(points[-1])
    return out


def _fx_route_points(subject, step, start, clearance, altitude):
    """[(x, y)] for one travel step: through free space at `altitude` (an obstacle within `clearance` blocks)."""
    obstacles = [o for o in _fx_obstacles(exclude={s.name for s in subject})]
    tree = _fx_bvh(obstacles)
    env = _fx_env()

    def free(x, y):
        if tree is None:
            return True
        z = altitude(x, y)
        return tree.find_nearest(Vector((x, y, z)), clearance)[0] is None

    rel = step.get("rel") or ""
    targets = _fx_targets(step.get("target"))
    centres = []
    for o in targets:
        lo, hi = box(o)
        centres.append(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo, hi))
    bounds = env["bounds"] if env else None
    if bounds is None and centres:
        bounds = [min(c[2].x for c in centres) - 20, min(c[2].y for c in centres) - 20,
                  max(c[3].x for c in centres) + 20, max(c[3].y for c in centres) + 20]
    if bounds is None:
        bounds = [start.x - 25, start.y - 25, start.x + 25, start.y + 25]
    grid_bounds = (bounds[0] - 15, bounds[1] - 15, bounds[2] + 15, bounds[3] + 15)
    cell = max(1.0, min(4.0, (grid_bounds[2] - grid_bounds[0]) / 80))
    waypoints = []
    if rel in ("between", "among", "amongst", "through") and len(centres) >= 2:
        gaps = world_library.gaps_between([(c[0], c[1]) for c in centres])
        gaps = [g for g in gaps if free(*g)]
        random.Random(3).shuffle(gaps)
        waypoints = world_library.tour((start.x, start.y), gaps[:6])
    elif rel in ("around", "round") or step["do"] == "orbit":
        if centres:
            cx = sum(c[0] for c in centres) / len(centres)
            cy = sum(c[1] for c in centres) / len(centres)
            r = max(max(c[3].x - c[2].x, c[3].y - c[2].y) for c in centres) / 2 + clearance + 3
        else:
            cx, cy, r = start.x, start.y, 12.0
        a0 = math.atan2(start.y - cy, start.x - cx)
        waypoints = [(cx + r * math.cos(a0 + k * math.tau / 16), cy + r * math.sin(a0 + k * math.tau / 16))
                     for k in range(1, 17)]
        return [(start.x, start.y)] + waypoints
    elif rel == "along" and env and (env.get("streets") or env.get("river")):
        lines = env.get("streets") or [env["river"]]
        best = min(lines, key=lambda ln: min(math.hypot(p[0] - start.x, p[1] - start.y) for p in ln))
        a, b = best[0], best[-1]
        if math.hypot(a[0] - start.x, a[1] - start.y) > math.hypot(b[0] - start.x, b[1] - start.y):
            best = list(reversed(best))
        waypoints = [tuple(p) for p in best]
    elif rel in ("to", "toward", "towards", "into", "up to", "onto", "at", "near", "past") and centres:
        c = centres[0]
        # stop beside it, on the side facing where we come from
        dx, dy = start.x - c[0], start.y - c[1]
        d = math.hypot(dx, dy) or 1.0
        half = max(c[3].x - c[2].x, c[3].y - c[2].y) / 2
        waypoints = [(c[0] + dx / d * (half + clearance + 1.0), c[1] + dy / d * (half + clearance + 1.0))]
    elif rel in ("over", "above", "across") or not centres:
        # across the place from one side to the other (over its middle)
        cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        far = (2 * cx - start.x, 2 * cy - start.y)
        waypoints = [(cx, cy), far]
    else:
        waypoints = [(centres[0][0], centres[0][1])]
    route = [(start.x, start.y)]
    for wp in waypoints:
        seg = world_library.route(free, route[-1], wp, cell, grid_bounds)
        if seg is None:
            continue
        route += seg[1:]
    return route


def animate_motion(task, start_frame=1, clearance=None, lift=0.0):
    """Key `task`'s subject travelling as its steps say. Returns {"frames": [first, last], "length", "path": [...]}"""
    if isinstance(task, str):
        task = json.loads(task)
    scene = _fx_scene()
    subjects = [o for o in _fx_objects_of(task["subject"]) if o.type == 'MESH']
    if not subjects:
        raise RuntimeError("the thing to animate isn't in the scene")
    lead = subjects[0]
    meta = _fx_meta(lead)
    moves = meta.get("moves") or "move"
    size = meta.get("size") or [1, 1, 1]
    radius = max(size[0], size[1]) / 2
    clearance = clearance if clearance is not None else radius + 1.0
    speed = (meta.get("speed") or 3.0) * float(task.get("speed") or 1.0)
    for o in subjects:
        o.animation_data_clear()
    home = json.loads(lead.get("jarvis_home", "null") or "null")
    start = Vector(home) if home else lead.location.copy()
    for o in subjects:
        h = json.loads(o.get("jarvis_home", "null") or "null")
        if h:
            o.location = Vector(h)
    frame = start_frame
    path_all = []
    for step in task["steps"]:
        verb = step["do"]
        if verb == "move":
            verb = {"fly": "fly", "drive": "drive", "sail": "sail"}.get(moves, "move")
        if verb in ("spin", "hover", "bounce") and not step.get("target"):
            frame = _fx_in_place(subjects, verb, frame, speed)
            continue
        flying = verb in ("fly",) or moves == "fly"
        targets = _fx_targets(step.get("target"))
        heights = sorted(box(o)[1].z for o in targets) if targets else []
        if flying:
            if step.get("rel") in ("over", "above") and targets:
                alt = max(heights) + 6 + radius
            elif heights and step.get("rel") in ("between", "among", "through", "around", None):
                alt = max(6.0, min(heights[len(heights) // 2] * 0.45, heights[0] - 4.0 if heights[0] > 12 else 8.0))
            else:
                alt = 8.0
            alt += lift
            altitude = (lambda x, y, a=alt: a)
        else:
            altitude = (lambda x, y: _fx_ground(x, y) + size[2] / 2)
        pts = _fx_route_points(subjects, step, start, clearance, altitude)
        if len(pts) < 2 and step.get("rel") not in ("around", "round"):
            pts = _fx_route_points(subjects, dict(step, rel="around"), start, clearance, altitude)
        if len(pts) < 2 and flying:
            top = max(heights) if heights else 10.0
            altitude = (lambda x, y, a=top + 6 + radius: a)
            pts = _fx_route_points(subjects, dict(step, rel="over"), start, clearance, altitude)
        if len(pts) < 2:
            continue
        # a flier is already flying when the shot starts (a take-off from beside a tower would put the follow camera
        # inside it); whatever drives or walks keeps to the ground
        pts3 = [Vector((x, y, altitude(x, y) if flying else _fx_ground(x, y))) for x, y in pts]
        if path_all:
            pts3[0] = start.copy()
        dense = _fx_catmull(pts3, 10)
        if not flying:
            for p in dense:
                p.z = _fx_ground(p.x, p.y)
        # a journey is a shot, not a tour of everything: about `max_seconds` of it (the request can ask for longer)
        budget = speed * float(task.get("seconds") or 14.0) - sum(
            (Vector(path_all[i + 1]) - Vector(path_all[i])).length for i in range(len(path_all) - 1))
        run, kept = 0.0, [dense[0]]
        for a, b in zip(dense, dense[1:]):
            run += (b - a).length
            kept.append(b)
            if run >= budget:
                break
        dense = kept
        if len(dense) < 2:
            break
        frame = _fx_key_path(subjects, dense, frame, speed, flying, loop=False)
        path_all += [list(p) for p in dense]
        start = dense[-1].copy()
    scene.frame_start = 1
    scene.frame_end = max(scene.frame_end, frame + int(FX_FPS * 0.5))
    lead["jarvis_motion"] = json.dumps({"frames": [start_frame, frame], "speed": speed})
    return {"frames": [start_frame, frame], "length": round(sum((Vector(path_all[i + 1]) - Vector(path_all[i])).length
                                                                for i in range(len(path_all) - 1)), 1) if path_all
            else 0.0, "points": len(path_all), "subject": lead.name}


def _fx_key_path(subjects, dense, frame, speed, flying, loop):
    """Keys along `dense` points at `speed` m/s, easing in and out; facing along the way, banking into turns
    when it flies."""
    lengths = [0.0]
    for a, b in zip(dense, dense[1:]):
        lengths.append(lengths[-1] + (b - a).length)
    total = lengths[-1]
    if total < 0.1:
        return frame
    ramp = min(2.0, total / speed / 3)
    duration = total / speed + ramp
    n = max(2, int(duration * FX_FPS))

    def s_at(t):   # distance covered at time t, accelerating over `ramp` and slowing over the last `ramp`
        if t < ramp:
            return 0.5 * speed / ramp * t * t
        if t > duration - ramp:
            r = duration - t
            return total - 0.5 * speed / ramp * r * r
        return 0.5 * speed * ramp + speed * (t - ramp)

    def point_at(s):
        s = max(0.0, min(total, s))
        lo_, hi_ = 0, len(lengths) - 1
        while hi_ - lo_ > 1:
            mid = (lo_ + hi_) // 2
            if lengths[mid] <= s:
                lo_ = mid
            else:
                hi_ = mid
        seg = max(lengths[hi_] - lengths[lo_], 1e-9)
        return dense[lo_].lerp(dense[hi_], (s - lengths[lo_]) / seg)

    prev_yaw = None
    offsets = [Vector((0, 0, 0))] + [Vector(((i % 3 - 1) * 4.0, -(i // 1) * 6.0, (i % 2) * 2.0))
                                     for i in range(1, len(subjects))]
    for o, off in zip(subjects, offsets):
        o.rotation_mode = 'XYZ'
        action = bpy.data.actions.new(f"{o.name} journey")
        curves = [action.fcurves.new("location", index=i, action_group="Journey") for i in range(3)] + \
                 [action.fcurves.new("rotation_euler", index=i, action_group="Journey") for i in range(3)]
        keys = [[] for _ in range(6)]
        prev_yaw = None
        for k in range(n + 1):
            t = duration * k / n
            s = s_at(t)
            p = point_at(s)
            ahead = point_at(s + 1.5)
            behind = point_at(s - 1.5)
            d = ahead - behind
            yaw = math.atan2(d.x, -d.y) if d.length > 1e-3 else (prev_yaw or o.rotation_euler.z)
            if prev_yaw is not None:
                yaw = prev_yaw + math.atan2(math.sin(yaw - prev_yaw), math.cos(yaw - prev_yaw))
            turn = 0.0 if prev_yaw is None else (yaw - prev_yaw) * FX_FPS
            prev_yaw = yaw
            bank = max(-0.45, min(0.45, -turn * 0.35)) if flying else 0.0
            pitch = math.atan2(d.z, math.hypot(d.x, d.y)) if flying and d.length > 1e-3 else 0.0
            rot_off = Matrix.Rotation(yaw, 3, 'Z') @ off
            loc = p + rot_off
            f = frame + k
            for i in range(3):
                keys[i].append((f, loc[i]))
            for i, v in enumerate((pitch * 0.6, bank, yaw)):
                keys[3 + i].append((f, v))
        # turns of the yaw curve are smoothed a little (no shiver from the path's corners)
        for i in range(6):
            vals = [v for _, v in keys[i]]
            if i >= 3:
                sm = []
                for j in range(len(vals)):
                    w = vals[max(0, j - 3):j + 4]
                    sm.append(sum(w) / len(w))
                vals = sm
            curves[i].keyframe_points.add(len(vals))
            curves[i].keyframe_points.foreach_set("co", [c for (f, _), v in zip(keys[i], vals) for c in (f, v)])
            curves[i].update()
        _fx_bind(o, action)
    return frame + n


def _fx_bind(obj, action):
    obj.animation_data_create()
    obj.animation_data.action = action
    ad = obj.animation_data
    if hasattr(ad, "action_slot") and ad.action_slot is None and len(action.slots):
        ad.action_slot = action.slots[0]


def _fx_in_place(subjects, verb, frame, speed):
    n = int(6 * FX_FPS)
    for o in subjects:
        base = o.location.copy()
        yaw0 = o.rotation_euler.z
        action = bpy.data.actions.new(f"{o.name} {verb}")
        loc = [action.fcurves.new("location", index=i, action_group=verb) for i in range(3)]
        rot = action.fcurves.new("rotation_euler", index=2, action_group=verb)
        pts = {i: [] for i in range(3)}
        rs = []
        for k in range(n + 1):
            t = k / FX_FPS
            p = base.copy()
            yaw = yaw0
            if verb == "spin":
                yaw = yaw0 + t * math.tau * 0.25 * max(0.5, speed / 3)
            elif verb == "hover":
                p.z = base.z + 1.5 + 0.25 * math.sin(t * 2.2)
                yaw = yaw0 + 0.15 * math.sin(t * 0.7)
            elif verb == "bounce":
                ph = (t * 1.6) % 1.0
                p.z = base.z + 1.2 * 4 * ph * (1 - ph) * (0.85 ** int(t * 1.6))
            for i in range(3):
                pts[i].append((frame + k, p[i]))
            rs.append((frame + k, yaw))
        for i in range(3):
            loc[i].keyframe_points.add(len(pts[i]))
            loc[i].keyframe_points.foreach_set("co", [c for f, v in pts[i] for c in (f, v)])
            loc[i].update()
        rot.keyframe_points.add(len(rs))
        rot.keyframe_points.foreach_set("co", [c for f, v in rs for c in (f, v)])
        rot.update()
        _fx_bind(o, action)
    _fx_scene().frame_end = max(_fx_scene().frame_end, frame + n)
    return frame + n


def inspect_motion_paths(task_ids, step=2):
    """For each travelling thing: does it pass through anything (its body within its own radius of a solid), how
    fast, how far, the largest change of speed between frames, and whether it moved at all."""
    if isinstance(task_ids, str):
        task_ids = json.loads(task_ids)
    scene = _fx_scene()
    keep = scene.frame_current
    out = {}
    for tid, subject_id in task_ids.items():
        subjects = [o for o in _fx_objects_of(subject_id) if o.type == 'MESH']
        if not subjects:
            out[tid] = {"error": "missing"}
            continue
        o = subjects[0]
        meta = _fx_meta(o)
        size = meta.get("size") or [1, 1, 1]
        r = max(size[0], size[1], size[2]) / 2 * 0.6
        tree = _fx_bvh(_fx_obstacles(exclude={s.name for s in subjects}))
        m = json.loads(o.get("jarvis_motion", "null") or "null") or {"frames": [scene.frame_start, scene.frame_end]}
        hits, positions = [], []
        for f in range(m["frames"][0], m["frames"][1] + 1, step):
            scene.frame_set(f)
            c = o.matrix_world @ Vector((0, 0, size[2] / 2 / max(o.scale.z, 1e-6)))
            positions.append(c.copy())
            if tree is not None:
                h = tree.find_nearest(c, r)
                if h[0] is not None and len(hits) < 20:
                    hits.append([f, round(r - h[3], 2)])
        speeds = [(b - a).length * FX_FPS / step for a, b in zip(positions, positions[1:])]
        jumps = [abs(b - a) for a, b in zip(speeds, speeds[1:])]
        out[tid] = {"subject": o.name, "frames": m["frames"], "hits": hits,
                    "travelled": round(sum((b - a).length for a, b in zip(positions, positions[1:])), 1),
                    "top_speed": round(max(speeds), 1) if speeds else 0.0,
                    "speed_jump": round(max(jumps), 2) if jumps else 0.0,
                    "lowest": round(min(p.z for p in positions), 2) if positions else 0.0}
    scene.frame_set(keep)
    return out


# ---------- weather ----------

def _fx_clear(role):
    for o in [o for o in _fx_scene().objects if o.get("jarvis_fx") == role]:
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)


def _fx_region():
    """Where weather must fall: around what the camera will see (the subjects and the environment's middle)."""
    env = _fx_env()
    if env:
        b = env["bounds"]
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        half = min(70.0, max(b[2] - b[0], b[3] - b[1]) / 2 + 10)
    else:
        cx = cy = 0.0
        half = 30.0
    moving = [o for o in _fx_scene().objects if o.get("jarvis_scene") and (o.animation_data or o.type == 'ARMATURE')]
    if moving:
        xs = [o.matrix_world.translation.x for o in moving]
        ys = [o.matrix_world.translation.y for o in moving]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        half = max(25.0, min(70.0, max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 25))
    return cx, cy, half


def _fx_sock(node, name, kind=None):
    for s in node.inputs:
        if s.name == name and s.enabled and (kind is None or s.type == kind):
            return s
    for s in node.inputs:
        if s.name == name:
            return s
    raise KeyError(f"{node.bl_idname} has no input {name}")


def _fx_out(node, name, kind=None):
    for s in node.outputs:
        if s.name == name and s.enabled and (kind is None or s.type == kind):
            return s
    return next(s for s in node.outputs if s.name == name)


def _fx_falling(name, count, region, top, speed, drop_mesh, wind=(0.0, 0.0), sway=0.0, seed=1):
    """`count` drops (or flakes) in `region`, each falling from `top` to the ground at `speed` m/s and starting
    over: their height is fract(time * speed / top + its own phase) — computed from the frame, so every frame
    shows the same rain whether it is rendered in order or alone."""
    cx, cy, half = region
    rng = random.Random(seed)
    me = bpy.data.meshes.new(name + " points")
    me.from_pydata([(cx + rng.uniform(-half, half), cy + rng.uniform(-half, half), top) for _ in range(count)], [], [])
    pts = bpy.data.objects.new(name, me)
    _fx_scene().collection.objects.link(pts)
    pts["jarvis_fx"] = "weather"
    drop = bpy.data.objects.new(name + " drop", drop_mesh)
    _fx_scene().collection.objects.link(drop)
    drop["jarvis_fx"] = "weather"
    drop.hide_render = True
    drop.hide_viewport = True
    drop.location = (0, 0, -1000)
    tree = bpy.data.node_groups.new(name + " fall", 'GeometryNodeTree')
    tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    N = tree.nodes
    L = tree.links
    gin, gout = N.new('NodeGroupInput'), N.new('NodeGroupOutput')
    time = N.new('GeometryNodeInputSceneTime')
    rnd = N.new('FunctionNodeRandomValue')
    rnd.data_type = 'FLOAT'
    idx = N.new('GeometryNodeInputID')
    L.new(idx.outputs['ID'], _fx_sock(rnd, "ID"))
    _fx_sock(rnd, "Min", 'VALUE').default_value = 0.0
    _fx_sock(rnd, "Max", 'VALUE').default_value = 1.0
    m1 = N.new('ShaderNodeMath')
    m1.operation = 'MULTIPLY'
    L.new(time.outputs['Seconds'], m1.inputs[0])
    m1.inputs[1].default_value = speed / top
    a1 = N.new('ShaderNodeMath')
    a1.operation = 'ADD'
    L.new(m1.outputs[0], a1.inputs[0])
    L.new(_fx_out(rnd, "Value", 'VALUE'), a1.inputs[1])
    fr = N.new('ShaderNodeMath')
    fr.operation = 'FRACT'
    L.new(a1.outputs[0], fr.inputs[0])
    fall = N.new('ShaderNodeMath')
    fall.operation = 'MULTIPLY'
    L.new(fr.outputs[0], fall.inputs[0])
    fall.inputs[1].default_value = top
    # offset = (wind_x * fall + sway, wind_y * fall, -fall)
    ox = N.new('ShaderNodeMath')
    ox.operation = 'MULTIPLY'
    L.new(fall.outputs[0], ox.inputs[0])
    ox.inputs[1].default_value = wind[0]
    oy = N.new('ShaderNodeMath')
    oy.operation = 'MULTIPLY'
    L.new(fall.outputs[0], oy.inputs[0])
    oy.inputs[1].default_value = wind[1]
    oz = N.new('ShaderNodeMath')
    oz.operation = 'MULTIPLY'
    L.new(fall.outputs[0], oz.inputs[0])
    oz.inputs[1].default_value = -1.0
    if sway:
        sw = N.new('ShaderNodeMath')
        sw.operation = 'SINE'
        sm = N.new('ShaderNodeMath')
        sm.operation = 'MULTIPLY_ADD'
        L.new(time.outputs['Seconds'], sm.inputs[0])
        sm.inputs[1].default_value = 1.3
        L.new(_fx_out(rnd, "Value", 'VALUE'), sm.inputs[2])
        L.new(sm.outputs[0], sw.inputs[0])
        sa = N.new('ShaderNodeMath')
        sa.operation = 'MULTIPLY_ADD'
        L.new(sw.outputs[0], sa.inputs[0])
        sa.inputs[1].default_value = sway
        L.new(ox.outputs[0], sa.inputs[2])
        ox = sa
    comb = N.new('ShaderNodeCombineXYZ')
    L.new(ox.outputs[0], comb.inputs[0])
    L.new(oy.outputs[0], comb.inputs[1])
    L.new(oz.outputs[0], comb.inputs[2])
    setp = N.new('GeometryNodeSetPosition')
    L.new(gin.outputs[0], _fx_sock(setp, "Geometry"))
    L.new(comb.outputs[0], _fx_sock(setp, "Offset"))
    info = N.new('GeometryNodeObjectInfo')
    info.inputs['Object'].default_value = drop
    inst = N.new('GeometryNodeInstanceOnPoints')
    L.new(_fx_out(setp, "Geometry"), _fx_sock(inst, "Points"))
    L.new(_fx_out(info, "Geometry"), _fx_sock(inst, "Instance"))
    L.new(_fx_out(inst, "Instances"), gout.inputs[0])
    mod = pts.modifiers.new("Fall", 'NODES')
    mod.node_group = tree
    return pts, drop


def _fx_streak_mesh(name, length, radius, tilt=(0.0, 0.0), color=(0.8, 0.85, 0.95), strength=0.4):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=5, radius1=radius, radius2=radius * 0.3, depth=length)
    lean = Matrix.Rotation(math.atan(tilt[0]), 4, 'Y') @ Matrix.Rotation(-math.atan(tilt[1]), 4, 'X')
    bmesh.ops.transform(bm, matrix=lean, verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material(f"{name} material", color=color, roughness=0.05, transmission=0.6,
                                 emission=color, emission_strength=strength))
    return me


def _fx_flake_mesh(name, radius):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=radius)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material(f"{name} material", color=(0.95, 0.96, 1.0), roughness=0.6, emission=(0.9, 0.92, 1.0),
                                 emission_strength=1.5))
    return me


_FX_WET_KEYS = ("asphalt", "concrete", "paving", "stone", "ground", "grass", "sand", "deck", "walkway", "steps",
                "coping", "roof", "wood")


def _fx_wet(on):
    """Wet look: paving and ground darker and glossier (originals kept to undo it)."""
    root = bpy.data.objects.get("Jarvis Scene") or bpy.data.objects.new("Jarvis Scene", None)
    saved = json.loads(root.get("jarvis_dry", "{}"))
    for mat in bpy.data.materials:
        if not mat.use_nodes or not any(k in mat.name.lower() for k in _FX_WET_KEYS):
            continue
        node = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if node is None:
            continue
        col, rough = node.inputs['Base Color'], node.inputs['Roughness']
        if on:
            if mat.name not in saved:
                saved[mat.name] = [list(col.default_value), rough.default_value]
                c = col.default_value
                col.default_value = (c[0] * 0.6, c[1] * 0.6, c[2] * 0.62, c[3])
                rough.default_value = min(rough.default_value, 0.12 if "grass" not in mat.name.lower() else 0.35)
        elif mat.name in saved:
            col.default_value, rough.default_value = saved[mat.name][0], saved[mat.name][1]
            saved.pop(mat.name)
    root["jarvis_dry"] = json.dumps(saved)


def set_weather(tasks):
    """Replace whatever weather the scene has with `tasks` ([{"type", "intensity"}]; [] clears it)."""
    if isinstance(tasks, str):
        tasks = json.loads(tasks)
    _fx_clear("weather")
    _fx_clear("lightning")
    world = _fx_scene().world
    if world and world.use_nodes:
        for n in [n for n in world.node_tree.nodes if n.get("jarvis_fog")]:
            world.node_tree.nodes.remove(n)
    types = {t["type"]: t for t in tasks}
    wind = 0.25 if "wind" in types or "storm" in types else 0.06
    made = []
    region = _fx_region()
    wet = False
    for kind, t in types.items():
        heavy = t.get("intensity") == "heavy" or kind == "storm"
        if kind in ("rain", "storm"):
            preset = anim_library.RAIN["heavy" if heavy else "light" if t.get("intensity") == "light" else "rain"]
            area = (2 * region[2]) ** 2 / 3600.0
            count = int(min(90000, preset["drops"] * max(0.5, area)))
            mesh = _fx_streak_mesh("Rain streak", preset["length"], preset["radius"] * 1.6, (wind, wind * 0.3))
            pts, _ = _fx_falling("Rain", count, region, 30.0, preset["speed"] * 1.3, mesh, (wind, wind * 0.3))
            made.append(pts.name)
            wet = True
        if kind == "snow":
            area = (2 * region[2]) ** 2 / 3600.0
            mesh = _fx_flake_mesh("Snowflake", 0.055)
            pts, _ = _fx_falling("Snow", int(min(70000, 20000 * max(0.5, area) * (1.6 if heavy else 1.0))), region,
                                 25.0, 1.2, mesh, (wind * 0.5, 0.0), sway=0.35)
            made.append(pts.name)
            for mat in bpy.data.materials:
                if "grass" in mat.name.lower() and mat.use_nodes:
                    n = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                    if n is not None:
                        n.inputs['Base Color'].default_value = (0.75, 0.78, 0.8, 1.0)
        if kind == "fog" or kind == "storm":
            _fx_fog(0.02 if kind == "fog" else 0.008)
            made.append("fog")
        if kind == "storm":
            made.append(_fx_lightning())
        if kind == "wet":
            wet = True
        if kind == "wind" or kind == "storm":
            made += _fx_sway()
    _fx_wet(wet)
    return {"made": made, "region": [round(v, 1) for v in region], "wet": wet}


def _fx_fog(density):
    scene = _fx_scene()
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_WORLD')
    vol = nt.nodes.new('ShaderNodeVolumePrincipled')
    vol["jarvis_fog"] = True
    vol.inputs['Density'].default_value = density
    vol.inputs['Color'].default_value = (0.75, 0.78, 0.82, 1.0)
    nt.links.new(vol.outputs[0], out.inputs['Volume'])


def _fx_lightning():
    data = bpy.data.lights.new("Lightning", 'SUN')
    data.color = (0.8, 0.85, 1.0)
    o = bpy.data.objects.new("Lightning", data)
    _fx_scene().collection.objects.link(o)
    o["jarvis_fx"] = "lightning"
    o.rotation_euler = (math.radians(30), 0, math.radians(40))
    data.animation_data_create()
    action = bpy.data.actions.new("Lightning flashes")
    fc = action.fcurves.new("energy")
    rng = random.Random(5)
    end = max(_fx_scene().frame_end, 120)
    keys = [(1, 0.0)]
    f = rng.randint(30, 60)
    while f < end:
        keys += [(f - 1, 0.0), (f, 25.0), (f + 2, 4.0), (f + 3, 18.0), (f + 6, 0.0)]
        f += rng.randint(70, 140)
    fc.keyframe_points.add(len(keys))
    fc.keyframe_points.foreach_set("co", [c for k in keys for c in k])
    for kp in fc.keyframe_points:
        kp.interpolation = 'LINEAR'
    fc.update()
    _fx_bind(data, action)
    return o.name


def _fx_sway():
    """Things that sway in wind (trees, palms) get a gentle noisy rock about their base."""
    done = []
    for o in _fx_scene().objects:
        if not _fx_meta(o).get("sways"):
            continue
        o.animation_data_create()
        if o.animation_data.action is None:
            action = bpy.data.actions.new(f"{o.name} sway")
            for i in (0, 1):
                fc = action.fcurves.new("rotation_euler", index=i)
                fc.keyframe_points.add(1)
                fc.keyframe_points.foreach_set("co", [1, o.rotation_euler[i]])
                noise = fc.modifiers.new('NOISE')
                noise.strength = 0.08
                noise.scale = 18 + 4 * i
                noise.phase = hash(o.name) % 100
            _fx_bind(o, action)
            done.append(o.name)
    return done


# ---------- lighting ----------

def set_lighting(task, weather=()):
    """The time of day (and how rain changes it): one sun, the sky, exposure; at night the windows and lamps light
    up and real lights stand at the lamps nearest the action."""
    if isinstance(task, str):
        task = json.loads(task)
    if isinstance(weather, str):
        weather = json.loads(weather)
    scene = _fx_scene()
    time = task.get("time") or ("overcast" if weather else "day")
    rainy = any(w in ("rain", "storm", "snow") for w in weather)
    preset = dict(anim_library.LIGHTING["rain" if rainy and time in ("day", "overcast", None) else
                                         "night" if time == "night" else "sunset" if time in ("sunset", "sunrise") else
                                         "day"])
    if time == "overcast":
        preset.update(sun=1.2, sky=(0.45, 0.5, 0.55), sky_strength=0.6, exposure=0.3)
    if rainy and time == "night":
        preset["exposure"] = 1.2
    _fx_clear("lighting")
    for o in scene.objects:   # the builds' own suns give way to the scene's
        if o.type == 'LIGHT' and o.data.type == 'SUN' and not o.get("jarvis_fx"):
            o.data.energy = 0.0
    sun_data = bpy.data.lights.new("Jarvis sun", 'SUN')
    sun_data.energy = preset["sun"]
    sun_data.color = preset["sun_color"]
    sun_data.angle = math.radians(3.0 if not rainy else 12.0)
    sun = bpy.data.objects.new("Jarvis sun", sun_data)
    scene.collection.objects.link(sun)
    sun["jarvis_fx"] = "lighting"
    sun.rotation_euler = (math.radians(90 - preset["sun_elevation"]), 0.0,
                          math.radians(-35 if time != "sunrise" else 145))
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None)
    if bg is not None:
        bg.inputs['Color'].default_value = tuple(preset["sky"]) + (1.0,)
        bg.inputs['Strength'].default_value = preset["sky_strength"]
    night = time == "night" or (rainy and time in ("sunset",))
    for mat in bpy.data.materials:
        if mat.get("jarvis_windows") and mat.use_nodes:
            g = mat.node_tree.nodes.get("glow")
            if g is not None:
                g.outputs[0].default_value = 3.0 if night else (0.6 if rainy else 0.0)
    lamps = 0
    if night or rainy:
        focus = _fx_region()
        posts = sorted([o for o in scene.objects if o.get("jarvis_asset") in ("streetlight", "lamp")],
                       key=lambda o: math.hypot(o.location.x - focus[0], o.location.y - focus[1]))[:12]
        for o in posts:
            h = box(o)[1].z
            ld = bpy.data.lights.new(f"{o.name} light", 'POINT')
            ld.energy = 900.0 if o.get("jarvis_asset") == "streetlight" else 120.0
            ld.color = preset["warm"] if o.get("jarvis_asset") == "lamp" else (0.75, 0.9, 1.0) if "futur" in str(
                o.get("jarvis_meta")) else preset["warm"]
            ld.shadow_soft_size = 0.4
            lo = bpy.data.objects.new(f"{o.name} light", ld)
            scene.collection.objects.link(lo)
            lo["jarvis_fx"] = "lighting"
            lo.location = (o.location.x, o.location.y, h - 0.5)
            lamps += 1
    try:
        scene.view_settings.view_transform = 'AgX'
    except TypeError:
        pass
    scene.view_settings.exposure = preset.get("exposure", 0.0)
    scene.render.engine = next((e for e in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE") if e in {
        i.identifier for i in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}), "CYCLES")
    if hasattr(scene.eevee, "use_raytracing"):
        scene.eevee.use_raytracing = True
    return {"time": time, "sun": preset["sun"], "lamps": lamps, "night": night, "exposure": scene.view_settings.exposure}


# ---------- cameras ----------

def _fx_track(subject_id, step=2):
    """Where the subject is over the animation: [(frame, centre)]. An armature's hips; an object's middle."""
    scene = _fx_scene()
    objs = _fx_objects_of(subject_id)
    keep = scene.frame_current
    if not objs:
        return []
    o = next((x for x in objs if x.type == 'ARMATURE'), objs[0])
    out = []
    for f in range(scene.frame_start, scene.frame_end + 1, step):
        scene.frame_set(f)
        if o.type == 'ARMATURE':
            c = o.matrix_world @ o.pose.bones["hips"].head + Vector((0, 0, 0.35))
        else:
            lo, hi = box(o)
            c = (lo + hi) / 2
        out.append((f, c.copy()))
    scene.frame_set(keep)
    return out


def _fx_look(cam_pos, target):
    return (target - cam_pos).to_track_quat('-Z', 'Y').to_euler()


def _fx_smooth_vectors(vs, k=6):
    out = []
    for i in range(len(vs)):
        w = vs[max(0, i - k):i + k + 1]
        s = Vector((0, 0, 0))
        for v in w:
            s += v
        out.append(s / len(w))
    return out


def set_camera(task, attempt=0):
    """The camera `task` asks for (shot, subject), keyed per frame; attempt>0 tries other angles (a repair after
    the subject was found hidden)."""
    if isinstance(task, str):
        task = json.loads(task)
    scene = _fx_scene()
    _fx_clear("camera")
    shot = task.get("shot") or "follow"
    track = _fx_track(task["subject"]) if task.get("subject") else []
    subj_objs = _fx_objects_of(task["subject"]) if task.get("subject") else []
    size = 2.0
    if subj_objs:
        if any(o.type == 'ARMATURE' for o in subj_objs):   # a person: framed as a person (about 1.2 m across)
            size = 1.2
        else:
            lo, hi = box(subj_objs[0])
            size = max(1.6, (hi - lo).length)
    env = _fx_env()
    if not track:   # nothing moves: frame the place
        if env:
            b = env["bounds"]
            c = Vector(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, 2.0))
            span = max(b[2] - b[0], b[3] - b[1])
        else:
            objs = [o for o in scene.objects if o.get("jarvis_scene") and o.type == 'MESH']
            if objs:
                los = [box(o)[0] for o in objs]
                his = [box(o)[1] for o in objs]
                lo = Vector([min(v[i] for v in los) for i in range(3)])
                hi = Vector([max(v[i] for v in his) for i in range(3)])
                c, span = (lo + hi) / 2, max((hi - lo).x, (hi - lo).y, 4.0)
            else:
                c, span = Vector((0, 0, 1)), 10.0
        track = [(f, c) for f in range(scene.frame_start, max(scene.frame_end, scene.frame_start + 96) + 1, 4)]
        if shot == "follow":
            shot = "establishing"
        size = span / 3
    cam_data = bpy.data.cameras.new("Jarvis camera")
    cam = bpy.data.objects.new("Jarvis camera", cam_data)
    scene.collection.objects.link(cam)
    cam["jarvis_fx"] = "camera"
    cam.rotation_mode = 'XYZ'
    obstacles = _fx_bvh([o for o in _fx_obstacles(exclude={o.name for o in subj_objs}) if o.type == 'MESH'])
    room = env.get("room") if env else None
    if room and not task.get("subject"):
        # a room is seen the way a person standing in it sees it: from a corner by the door, at eye height,
        # with a wide lens, looking across to the far corner — then fitted so everything in it shows
        w, d = room["width"] / 2, room["depth"] / 2
        corner = [(-1, -1), (1, -1), (-1, 1), (1, 1)][attempt % 4]
        cam.location = Vector((corner[0] * (w - 0.35), corner[1] * (d - 0.35), 1.65))
        aim = Vector((-corner[0] * w * 0.35, -corner[1] * d * 0.35, 0.75))
        cam.rotation_euler = _fx_look(cam.location, aim)
        cam_data.lens = 16
        scene.camera = cam
        return {"camera": cam.name, "shot": "room", "frames": None}
    if not task.get("subject") and shot in ("establishing", "static", "follow", "cinematic"):
        # nothing moves: a three-quarter view from above that fits what the plan made (not its whole lawn), with
        # blender_scene.frame() — the environment's ground and the sky stay out of the sum
        things = [o.name for o in _fx_still_things()]
        if things:
            a = math.radians(35 + 50 * attempt)
            los = [box(bpy.data.objects[n])[0] for n in things]
            his = [box(bpy.data.objects[n])[1] for n in things]
            lo = Vector([min(v[i] for v in los) for i in range(3)])
            hi = Vector([max(v[i] for v in his) for i in range(3)])
            c = (lo + hi) / 2
            span = max((hi - lo).x, (hi - lo).y, 2.0)
            cam.location = c + Vector((math.cos(a) * span, -math.sin(a) * span, span * 0.6))
            cam_data.lens = 28
            cam_data.clip_end = 2000
            scene.camera = cam
            frame(things, camera=cam.name, margin=0.1)
            return {"camera": cam.name, "shot": "fitted", "frames": None}
    frames = [f for f, _ in track]
    pts = [p for _, p in track]
    vel = []
    for i in range(len(pts)):
        a, b = pts[max(0, i - 3)], pts[min(len(pts) - 1, i + 3)]
        d = b - a
        d.z = 0.0   # which way it goes, over the ground: bending down isn't "going down" for a camera behind it
        # only travelling changes "behind it": turning on the spot or reaching over a table keeps the camera put
        vel.append(d.normalized() if d.length > 0.25 else (vel[-1] if vel else (d.normalized() if d.length > 1e-4
                                                                                  else Vector((0, 1, 0)))))
    vel = [v.normalized() if v.length > 1e-6 else Vector((0, 1, 0)) for v in _fx_smooth_vectors(vel, 10)]
    rng = random.Random(attempt)
    az = rng.uniform(-0.5, 0.5) * attempt
    positions, aims, lens = [], [], []
    shots = [shot] * len(pts)
    if shot == "cinematic":   # establishing, then following, then close: cut between them
        n = len(pts)
        shots = ["establishing" if i < n * 0.25 else "follow" if i < n * 0.75 else "closeup" for i in range(n)]
    dist = {"follow": 3.5, "track": 3.2, "closeup": 1.6, "orbit": 4.0, "establishing": 9.0, "static": 6.0}
    for i, (p, v) in enumerate(zip(pts, vel)):
        s = shots[i]
        D = size * dist.get(s, 3.5) / (1 + 0.6 * attempt) if s != "establishing" else size * dist[s]
        if room:
            D = min(D, 3.2)
        side = Vector((-v.y, v.x, 0)).normalized() if v.length else Vector((1, 0, 0))
        if s == "follow":
            pos = p - v * D + side * D * (0.25 + az) + Vector((0, 0, size * 0.6 + 0.5))
            aim = p + v * size * 0.8
            ln = 35
        elif s == "track":   # beside and ahead of it, three-quarters on: a person's face and hands show
            pos = p + v * D * 0.55 + side * D * (0.85 + az) + Vector((0, 0, size * 0.35 + 0.35))
            aim = p + Vector((0, 0, size * 0.1))
            ln = 35
        elif s == "closeup":
            pos = p + v * D * 0.8 + side * D * 0.6 + Vector((0, 0, size * 0.25))
            aim = p + Vector((0, 0, size * 0.15))
            ln = 50
        elif s == "orbit":
            a = math.tau * i / max(1, len(pts)) + az
            pos = p + Vector((math.cos(a), math.sin(a), 0)) * D + Vector((0, 0, size * 0.5 + 0.5))
            aim = p
            ln = 32
        elif s == "establishing":
            a = math.radians(35) + az
            c0 = pts[len(pts) // 2]
            push = 1.0 - 0.25 * i / max(1, len(pts))
            pos = c0 + Vector((math.cos(a), -math.sin(a), 0)) * D * push + Vector((0, 0, D * 0.45))
            aim = p.lerp(c0, 0.6)
            ln = 24
        else:   # static: one place that sees the whole journey
            c0 = pts[len(pts) // 2]
            spread = max((q - c0).length for q in pts) + size * 2
            pos = c0 + Vector((spread * 0.8, -spread * 0.9, spread * 0.5))
            aim = p.lerp(c0, 0.5)
            ln = 28
        if room:   # inside a room the camera stays inside its walls
            w, d_, h = room["width"] / 2 - 0.35, room["depth"] / 2 - 0.35, room["height"] - 0.3
            pos = Vector((max(-w, min(w, pos.x)), max(-d_, min(d_, pos.y)), max(0.6, min(h, pos.z))))
        positions.append(pos)
        aims.append(aim)
        lens.append(ln)
    # never under the ground (the ground isn't an obstacle, so nothing else would catch it)
    # (the floor under the camera itself: from 200 m up, a house's upper floor would count and lift it into the slab)
    positions = [Vector((p_.x, p_.y, max(p_.z, _fx_ground(p_.x, p_.y, p_.z + 0.5) + 0.4))) for p_ in positions]
    if shot != "cinematic":   # smooth first: a smoothing after the repair below would pull it back into walls
        positions = _fx_smooth_vectors(positions, 8)
        aims = _fx_smooth_vectors(aims, 5)

    def blocked(i):
        if obstacles is None:
            return False
        d = aims[i] - positions[i]
        hit = obstacles.ray_cast(positions[i], d.normalized(), max(0.0, d.length - size * 0.5))
        return hit[0] is not None or obstacles.find_nearest(positions[i], 0.6)[0] is not None or \
            _fx_inside(obstacles, positions[i])
    # a clear line to the subject: when something stands between, the camera comes closer and rises; the frames
    # around a repaired one are eased toward it so the move stays smooth
    def indoors(i):   # a roof or ceiling over the subject: rising would only put the camera into it
        if obstacles is None:
            return False
        return obstacles.ray_cast(pts[i] + Vector((0, 0, 0.3)), Vector((0, 0, 1)), 8.0)[0] is not None
    for _ in range(3):
        fixed = []
        for i in range(len(positions)):
            inside_room = indoors(i)
            for _ in range(10):
                if not blocked(i):
                    break
                if inside_room:   # come closer at head height, into the room the subject is in
                    p_ = positions[i].lerp(pts[i], 0.25)
                    positions[i] = Vector((p_.x, p_.y, pts[i].z + 0.45))
                else:
                    positions[i] = positions[i].lerp(pts[i], 0.2) + Vector((0, 0, size * 0.35))
                if i not in fixed:
                    fixed.append(i)
        if not fixed:
            break
        eased = list(positions)
        for i in fixed:
            for j in range(max(0, i - 8), min(len(positions), i + 9)):
                if j not in fixed:
                    w = 1.0 - abs(j - i) / 9.0
                    eased[j] = positions[j].lerp(positions[i], w * 0.5)
        positions = eased
    action = bpy.data.actions.new("Jarvis camera move")
    loc = [action.fcurves.new("location", index=k, action_group="Camera") for k in range(3)]
    rot = [action.fcurves.new("rotation_euler", index=k, action_group="Camera") for k in range(3)]
    lens_fc = None
    prev = None
    rows_l = [[] for _ in range(3)]
    rows_r = [[] for _ in range(3)]
    for f, pos, aim in zip(frames, positions, aims):
        e = _fx_look(pos, aim)
        if prev is not None:   # keep the angles continuous (no 360 degree spin between keys)
            e = Vector([prev[k] + math.atan2(math.sin(e[k] - prev[k]), math.cos(e[k] - prev[k])) for k in range(3)])
        prev = Vector(e)
        for k in range(3):
            rows_l[k].append((f, pos[k]))
            rows_r[k].append((f, prev[k]))
    for k in range(3):
        loc[k].keyframe_points.add(len(rows_l[k]))
        loc[k].keyframe_points.foreach_set("co", [c for r in rows_l[k] for c in r])
        rot[k].keyframe_points.add(len(rows_r[k]))
        rot[k].keyframe_points.foreach_set("co", [c for r in rows_r[k] for c in r])
        if shot == "cinematic":   # a cut is a cut: no blend between shots
            for kp in list(loc[k].keyframe_points) + list(rot[k].keyframe_points):
                kp.interpolation = 'LINEAR'
        loc[k].update()
        rot[k].update()
    _fx_bind(cam, action)
    cam_data.lens = lens[0] if lens else 35
    cam_data.clip_end = 2000
    if shot == "cinematic":
        cam_data.animation_data_create()
        la = bpy.data.actions.new("Jarvis camera lens")
        fc = la.fcurves.new("lens")
        fc.keyframe_points.add(len(frames))
        fc.keyframe_points.foreach_set("co", [c for f, ln in zip(frames, lens) for c in (f, ln)])
        for kp in fc.keyframe_points:
            kp.interpolation = 'CONSTANT'
        fc.update()
        _fx_bind(cam_data, la)
    scene.camera = cam
    return {"camera": cam.name, "shot": shot, "frames": [frames[0], frames[-1]] if frames else None}


def inspect_camera(subject_id=None, step=4):
    """For sampled frames: is the subject in the picture (inside its middle 90%), with nothing solid between, and
    is the camera itself out of every solid."""
    from bpy_extras.object_utils import world_to_camera_view
    scene = _fx_scene()
    cam = scene.camera
    if cam is None:
        return {"error": "no camera"}
    keep = scene.frame_current
    subj = _fx_objects_of(subject_id) if subject_id else []
    tree = _fx_bvh([o for o in _fx_obstacles(exclude={o.name for o in subj}) if o.type == 'MESH'])
    out = {"frames": 0, "outside": [], "hidden": [], "camera_inside": []}
    track = dict(_fx_track(subject_id, step)) if subject_id else {}
    if not subject_id:   # nothing moves: everything the plan made must be in the picture, on its first frame
        scene.frame_set(scene.frame_start)
        things = _fx_still_things()
        out["things"] = len(things)
        for o in things:
            lo, hi = box(o)
            v = world_to_camera_view(scene, cam, (lo + hi) / 2)
            if not (0.02 < v.x < 0.98 and 0.02 < v.y < 0.98 and v.z > 0):
                out["outside"].append(o.name)
        out["frames"] = max(1, len(things))
        out["still"] = True
        # and big enough to see: the share of the picture the box around them all takes
        if things:
            pts_ = [world_to_camera_view(scene, cam, c) for o in things for c in _corners(box(o))]
            xs = [min(1, max(0, p.x)) for p in pts_ if p.z > 0]
            ys = [min(1, max(0, p.y)) for p in pts_ if p.z > 0]
            out["fill"] = round((max(xs) - min(xs)) * (max(ys) - min(ys)), 3) if xs else 0.0
        cpos = cam.matrix_world.translation
        if tree is not None and _fx_inside(tree, cpos):
            out["camera_inside"].append(scene.frame_start)
        scene.frame_set(keep)
        return out
    for f in range(scene.frame_start, scene.frame_end + 1, step):
        scene.frame_set(f)
        out["frames"] += 1
        cpos = cam.matrix_world.translation
        if tree is not None and _fx_inside(tree, cpos):
            out["camera_inside"].append(f)
        if cpos.z < _fx_ground(cpos.x, cpos.y, cpos.z + 0.5) + 0.2:
            out["camera_inside"].append(f)   # under the ground counts as inside something
        if f in track:
            p = track[f]
            v = world_to_camera_view(scene, cam, p)
            if not (0.05 < v.x < 0.95 and 0.05 < v.y < 0.95 and v.z > 0):
                out["outside"].append(f)
            elif tree is not None:
                d = p - cpos
                hit = tree.ray_cast(cpos, d.normalized(), max(0.0, d.length - 0.6))
                if hit[0] is not None:
                    out["hidden"].append(f)
    scene.frame_set(keep)
    for k in ("outside", "hidden", "camera_inside"):
        out[k] = out[k][:30]
    return out


def _fx_still_things():
    """What a still picture is of: the objects the plan made, not the ground, walls, sky or a layout's filler."""
    made = [o for o in _fx_scene().objects if o.type == 'MESH' and o.get("jarvis_scene") and
            (o.get("jarvis_scene_role") or "") not in ("ground", "floor", "wall", "ceiling", "sidewalk", "water",
                                                       "glass", "light")]
    asked = [o for o in made if o.get("jarvis_for") or o.get("jarvis_scene_role") == "object"]
    return asked or made   # what was asked for; with nothing named, the place's own things


def _fx_inside(tree, p):
    """A point inside a closed solid: the first surface a ray meets faces away from it."""
    hit = tree.ray_cast(p, Vector((0.31, 0.27, 0.91)), 500)
    return hit[0] is not None and hit[1].dot(Vector((0.31, 0.27, 0.91))) > 0


# ---------- rendering ----------

def _fx_quality(q):
    scene = _fx_scene()
    r = anim_library.RENDER.get(q, anim_library.RENDER["preview"])
    scene.render.resolution_x, scene.render.resolution_y = r["width"], r["height"]
    scene.render.resolution_percentage = 100
    if hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = r["samples"]
    if hasattr(scene.render, "use_motion_blur"):
        scene.render.use_motion_blur = r["motion_blur"]
    scene.render.fps = FX_FPS


def render_frames(folder, frames, quality="preview"):
    """Stills of `frames` (EEVEE, the real look), with their pixel facts."""
    if isinstance(frames, str):
        frames = json.loads(frames)
    scene = _fx_scene()
    _fx_quality(quality)
    os.makedirs(folder, exist_ok=True)
    keep = scene.frame_current
    out = []
    scene.render.image_settings.file_format = 'PNG'
    for f in frames:
        scene.frame_set(int(f))
        path = os.path.join(folder, f"frame {int(f):04d}.png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        out.append({"frame": int(f), "path": path, **picture_facts(path)})
    scene.frame_set(keep)
    return out


def render_video_chunk(folder, start, end, quality="preview"):
    """Frames start..end as PNGs in `folder` (existing ones kept: a stopped render resumes)."""
    scene = _fx_scene()
    _fx_quality(quality)
    os.makedirs(folder, exist_ok=True)
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = os.path.join(folder, "f")
    scene.render.use_overwrite = False
    keep = (scene.frame_start, scene.frame_end)
    scene.frame_start, scene.frame_end = int(start), int(end)
    try:
        bpy.ops.render.render(animation=True)
    finally:
        scene.frame_start, scene.frame_end = keep
    done = len([n for n in os.listdir(folder) if n.startswith("f") and n.endswith(".png")])
    return {"frames_on_disk": done}


def encode_video(folder, out_path, fps=None):
    """The PNG frames in `folder` as one MP4 (H.264), through Blender's own video editor in a scene of its own."""
    files = sorted(n for n in os.listdir(folder) if n.startswith("f") and n.endswith(".png"))
    if not files:
        raise RuntimeError("there are no rendered frames to make a video of")
    main = _fx_scene()
    tmp = bpy.data.scenes.new("Jarvis video encode")
    try:
        tmp.sequence_editor_create()
        strips = tmp.sequence_editor.strips if hasattr(tmp.sequence_editor, "strips") else \
            tmp.sequence_editor.sequences
        strip = strips.new_image("frames", os.path.join(folder, files[0]), 1, 1)
        for n in files[1:]:
            strip.elements.append(n)
        tmp.frame_start, tmp.frame_end = 1, len(files)
        tmp.render.fps = fps or FX_FPS
        tmp.render.resolution_x, tmp.render.resolution_y = main.render.resolution_x, main.render.resolution_y
        tmp.render.resolution_percentage = 100
        tmp.render.image_settings.file_format = 'FFMPEG'
        tmp.render.ffmpeg.format = 'MPEG4'
        tmp.render.ffmpeg.codec = 'H264'
        tmp.render.ffmpeg.constant_rate_factor = 'HIGH'
        tmp.render.filepath = out_path
        tmp.render.use_file_extension = False
        bpy.ops.render.render(animation=True, scene=tmp.name)
    finally:
        bpy.data.scenes.remove(tmp)
    return {"path": out_path, "frames": len(files), "bytes": os.path.getsize(out_path) if os.path.exists(out_path)
            else 0, "seconds": round(len(files) / (fps or FX_FPS), 2)}


def subject_coverage(subject_id, frame, path):
    """How much of the picture the subject fills at `frame` (and whether it's there at all): a flat render where
    only the subject is white."""
    scene = _fx_scene()
    keep = (scene.render.engine, scene.display.shading.light, scene.display.shading.color_type,
            scene.display.shading.show_shadows, scene.render.filepath, scene.frame_current,
            scene.display.shading.background_type if hasattr(scene.display.shading, "background_type") else None)
    colors = {}
    subj = {o.name for o in _fx_objects_of(subject_id)}
    subj |= {c.name for o in _fx_objects_of(subject_id) for c in o.children}
    try:
        scene.render.engine = 'BLENDER_WORKBENCH'
        scene.display.shading.light = 'FLAT'
        scene.display.shading.color_type = 'OBJECT'
        scene.display.shading.show_shadows = False
        for o in scene.objects:
            colors[o.name] = tuple(o.color)
            o.color = (1, 1, 1, 1) if o.name in subj else (0, 0, 0, 1)
        world = scene.world
        bgc = None
        if world is not None:
            bgc = tuple(world.color)
            world.color = (0, 0, 0)
        scene.frame_set(int(frame))
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
    finally:
        for name, c in colors.items():
            if name in bpy.data.objects:
                bpy.data.objects[name].color = c
        if scene.world is not None and bgc is not None:
            scene.world.color = bgc
        (scene.render.engine, scene.display.shading.light, scene.display.shading.color_type,
         scene.display.shading.show_shadows, scene.render.filepath) = keep[:5]
        scene.frame_set(keep[5])
    import numpy
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        px = numpy.empty(w * h * 4, dtype=numpy.float32)
        img.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(img)
    lum = px.reshape(h, w, 4)[:, :, :3].mean(axis=2)
    return {"frame": int(frame), "coverage": round(float((lum > 0.5).mean()), 4)}


def rain_visible(frame, folder):
    """Whether the weather shows in the picture: the same frame with and without it, compared pixel by pixel."""
    import numpy
    scene = _fx_scene()
    weather = [o for o in scene.objects if o.get("jarvis_fx") == "weather" and o.modifiers]
    if not weather:
        return {"weather": False}
    _fx_quality("preview")
    scene.render.resolution_percentage = 50
    os.makedirs(folder, exist_ok=True)
    paths = []
    keep = scene.frame_current
    scene.frame_set(int(frame))
    try:
        for on in (True, False):
            for o in weather:
                o.hide_render = not on
            p = os.path.join(folder, f"weather {'on' if on else 'off'} {int(frame)}.png")
            scene.render.filepath = p
            bpy.ops.render.render(write_still=True)
            paths.append(p)
    finally:
        for o in weather:
            o.hide_render = False
        scene.render.resolution_percentage = 100
        scene.frame_set(keep)
    imgs = []
    for p in paths:
        img = bpy.data.images.load(p, check_existing=False)
        w, h = img.size
        px = numpy.empty(w * h * 4, dtype=numpy.float32)
        img.pixels.foreach_get(px)
        bpy.data.images.remove(img)
        imgs.append(px.reshape(h, w, 4)[:, :, :3])
    diff = numpy.abs(imgs[0] - imgs[1]).max(axis=2)
    return {"weather": True, "changed": round(float((diff > 0.04).mean()), 4), "paths": paths}
