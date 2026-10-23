"""Jarvis's Blender benchmark: everyday requests, said the way people say them, run against a real headless Blender
(tests/real_blender.py) through the same path the app uses for a request said while Blender is open
(app.run_blender_directly: blender_commands first; with --ai, the free-form BlenderComputerTask for the rest, on
the local AI). Each task passes only when objective checks on Blender's real scene afterwards hold — never because
a command ran without an error or a reply sounded right.

    python tests/blender_bench.py [--ai] [--only name,name] [--out results.json]

The scene state is read by this file's own snippet, not by the code under test, so a broken inspection in Jarvis
can't make a task look passed.
"""
import argparse
import json
import math
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# What Jarvis writes while the benchmark runs (the AI task's scene checkpoints) goes to a temp folder, never into
# the project folder or the real user data folder (as tests/conftest.py does for the tests).
os.environ.setdefault("JARVIS_DATA_DIR", tempfile.mkdtemp(prefix="jarvis-bench-data-"))
from real_blender import ROOT, RealBlender   # noqa: E402

sys.path.insert(0, ROOT)
import blender_bridge    # noqa: E402
import blender_commands  # noqa: E402
import blender_control   # noqa: E402
import computer_use      # noqa: E402

# Everything the checks look at, read straight from Blender.
STATE = r'''
import json, os, mathutils
scene = bpy.context.scene
def principled(mat):
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None
    n = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if not n:
        return None
    out = next((o for o in mat.node_tree.nodes if o.type == 'OUTPUT_MATERIAL' and o.is_active_output), None)
    linked = bool(out and out.inputs['Surface'].links and out.inputs['Surface'].links[0].from_node == n)
    def val(name):
        s = n.inputs.get(name)
        if s is None:
            return None
        v = s.default_value
        return list(v) if hasattr(v, '__len__') else float(v)
    return {"base": val('Base Color'), "metallic": val('Metallic'), "roughness": val('Roughness'),
            "transmission": val('Transmission Weight') if n.inputs.get('Transmission Weight') else val('Transmission'),
            "emission": val('Emission Color'), "emission_strength": val('Emission Strength'),
            "alpha": val('Alpha'), "linked": linked}
dg = bpy.context.evaluated_depsgraph_get()
objs = {}
for o in scene.objects:
    corners = [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
    e = {"type": o.type, "location": list(o.location), "rotation": list(o.rotation_euler), "scale": list(o.scale),
         "dimensions": list(o.dimensions), "min": [min(c[i] for c in corners) for i in range(3)],
         "max": [max(c[i] for c in corners) for i in range(3)], "hidden": o.hide_get() or o.hide_render,
         "materials": [], "modifiers": [{"type": m.type, "name": m.name,
                                          **({"width": m.width, "segments": m.segments} if m.type == 'BEVEL' else {}),
                                          **({"levels": m.levels, "render_levels": m.render_levels}
                                             if m.type == 'SUBSURF' else {}),
                                          **({"count": m.count} if m.type == 'ARRAY' else {})}
                                         for m in o.modifiers],
         "forward": list((o.matrix_world.to_quaternion() @ mathutils.Vector((0, 0, -1))))}
    if o.type == 'MESH':
        e["materials"] = [{"name": s.material.name, **(principled(s.material) or {}),
                           "viewport": list(s.material.diffuse_color)} if s.material else None
                          for s in o.material_slots]
        e["smooth"] = (sum(p.use_smooth for p in o.data.polygons) / len(o.data.polygons)) if o.data.polygons else 0
        e["verts"] = len(o.data.vertices)
        e["evaluated_verts"] = len(o.evaluated_get(dg).to_mesh().vertices)
        o.evaluated_get(dg).to_mesh_clear()
    if o.type == 'LIGHT':
        e["light"] = {"type": o.data.type, "energy": o.data.energy}
    if o.type == 'CAMERA':
        e["lens"] = o.data.lens
    objs[o.name] = e
RESULT = json.dumps({"objects": objs, "camera": scene.camera.name if scene.camera else None,
                     "filepath": bpy.data.filepath, "engine": scene.render.engine,
                     "resolution": [scene.render.resolution_x, scene.render.resolution_y]})
'''

# Runs in Blender: is every point given in front of the scene camera, inside its frame?
IN_VIEW = r'''
import json
from bpy_extras.object_utils import world_to_camera_view
scene = bpy.context.scene
cam = scene.camera
pts = json.loads(POINTS)
seen = []
for p in pts:
    v = world_to_camera_view(scene, cam, mathutils.Vector(p))
    seen.append(bool(0.0 <= v.x <= 1.0 and 0.0 <= v.y <= 1.0 and v.z > 0))
RESULT = json.dumps(seen)
'''


# Runs in Blender: is the stairwell above each stair flight open? A ray goes up from over the middle of the flight,
# just under where the next floor starts; it must not meet the floor slab (or anything) for 1.5 m.
STAIRWELLS = r'''
import json, mathutils
scene = bpy.context.scene
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
out = {}
for o in scene.objects:
    if o.type == 'MESH' and 'stairs' in o.name.lower():
        corners = [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
        lo = mathutils.Vector([min(c[i] for c in corners) for i in range(3)])
        hi = mathutils.Vector([max(c[i] for c in corners) for i in range(3)])
        start = mathutils.Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z - 0.4))
        out[o.name] = not scene.ray_cast(dg, start, mathutils.Vector((0, 0, 1)), distance=1.5)[0]
RESULT = json.dumps(out)
'''


class NoScreen(computer_use.Environment):
    """The free-form task's screen: nothing (the benchmark Blender has no window), so the AI can't click anything
    and never sees or touches the real desktop."""
    name = "benchmark"

    def available(self):
        return True, ""

    def observe(self):
        return computer_use.Observation(app="Blender", window="Blender (benchmark, no window)")

    def switch_window(self, title):
        return ""   # Blender is the window in front, as it would be in the app


def state(bridge) -> dict:
    response = bridge.run(STATE, timeout=30)
    if not response.get("ok"):
        raise RuntimeError("couldn't read the scene: " + (response.get("error") or "")[-300:])
    return json.loads(response["output"])


def in_view(bridge, points) -> list:
    response = bridge.run(f"POINTS = {json.dumps(json.dumps(points))}\n" + IN_VIEW, timeout=15)
    return json.loads(response["output"]) if response.get("ok") else [False] * len(points)


def corners(o):
    lo, hi = o["min"], o["max"]
    return [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


def new_objects(before: dict, after: dict, kind="MESH"):
    return [n for n, o in after["objects"].items() if n not in before["objects"] and o["type"] == kind]


def close(a, b, tolerance=0.02):
    return abs(a - b) <= tolerance


def mat(o, i=0):
    ms = o.get("materials") or []
    return ms[i] if len(ms) > i and ms[i] else {}


def reddish(c):
    return bool(c) and c[0] > 0.4 and c[1] < 0.2 and c[2] < 0.2


# ---------- the tasks ----------
# Each: name, what it tests, setup code (run in Blender first), the requests said in order, and check(ctx) -> list
# of failed criteria ([] = passed). ctx has before/after scene state, the replies, the bridge and the folder.

def _check_describe(c):
    reply = " ".join(c["replies"]).lower()
    return [f"the reply doesn't name {n}" for n in ("cube", "camera", "light") if n not in reply]


def _check_create_cylinder(c):
    made = new_objects(c["before"], c["after"])
    if len(made) != 1:
        return [f"expected one new mesh, found {made}"]
    o = c["after"]["objects"][made[0]]
    problems = [] if o["verts"] == 64 else [f"not a cylinder ({o['verts']} vertices)"]
    cube = c["after"]["objects"].get("Cube")
    if cube:
        overlap = all(o["min"][i] < cube["max"][i] and o["max"][i] > cube["min"][i] for i in range(3))
        if overlap:
            problems.append("it was put inside the existing cube")
    return problems


def _check_move_up(c):
    cube = c["after"]["objects"].get("Cube")
    return [] if cube and close(cube["location"][2], 3.0) else [f"cube z is {cube and cube['location'][2]}, not 3"]


def _check_width(c):
    cube = c["after"]["objects"].get("Cube")
    return [] if cube and close(cube["dimensions"][0], 4.0) else [f"cube is {cube and cube['dimensions'][0]} m wide"]


def _check_red(c):
    m = mat(c["after"]["objects"]["Cube"])
    out = [] if reddish(m.get("base")) else [f"base color is {m.get('base')}"]
    if not m.get("linked"):
        out.append("the Principled BSDF isn't what the material output shows")
    if not reddish(m.get("viewport")):
        out.append("the solid-view color isn't red")
    return out


def _check_metal(c):
    m = mat(c["after"]["objects"]["Cube"])
    out = []
    if (m.get("metallic") or 0) < 0.9:
        out.append(f"metallic is {m.get('metallic')}")
    if (m.get("roughness") if m.get("roughness") is not None else 1) > 0.35:
        out.append(f"roughness is {m.get('roughness')}")
    return out


def _check_glass(c):
    m = mat(c["after"]["objects"]["Cube"])
    out = [] if (m.get("transmission") or 0) >= 0.9 else [f"transmission is {m.get('transmission')}"]
    if (m.get("roughness") if m.get("roughness") is not None else 1) > 0.15:
        out.append(f"roughness is {m.get('roughness')} (frosted, not clear glass)")
    return out


def _check_glow(c):
    m = mat(c["after"]["objects"]["Cube"])
    out = [] if (m.get("emission_strength") or 0) > 0.5 else [f"emission strength is {m.get('emission_strength')}"]
    e = m.get("emission") or [0, 0, 0]
    if not (e[2] > 0.4 and e[0] < 0.3):
        out.append(f"emission color is {e}, not blue")
    return out


def _check_bevel(c):
    cube = c["after"]["objects"]["Cube"]
    bevels = [m for m in cube["modifiers"] if m["type"] == "BEVEL"]
    out = [] if bevels and bevels[0]["width"] > 0 else ["no bevel modifier with a width"]
    if cube["evaluated_verts"] <= 8:
        out.append("the evaluated mesh still has 8 vertices: nothing was bevelled")
    return out


def _check_smooth(c):
    made = new_objects(c["before"], c["after"])
    o = c["after"]["objects"][made[0]] if made else None
    return [] if o and o["smooth"] == 1 else [f"smooth faces: {o and o['smooth']}"]


def _check_subsurf(c):
    cube = c["after"]["objects"]["Cube"]
    s = [m for m in cube["modifiers"] if m["type"] == "SUBSURF"]
    return [] if s and s[0]["levels"] >= 1 and cube["evaluated_verts"] > 8 else ["no working subdivision surface"]


def _check_sun(c):
    suns = [n for n, o in c["after"]["objects"].items() if o.get("light", {}).get("type") == "SUN"
            and n not in c["before"]["objects"]]
    return [] if suns and c["after"]["objects"][suns[0]]["light"]["energy"] > 0 else ["no new sun light"]


def _check_camera_aim(c):
    cube = c["after"]["objects"]["Cube"]
    seen = in_view(c["bridge"], corners(cube))
    return [] if all(seen) else [f"{seen.count(False)} of the cube's 8 corners are outside the camera's view"]


def _check_render(c):
    pngs = [os.path.join(dp, f) for dp, _, fs in os.walk(c["folder"]) for f in fs if f.lower().endswith(".png")
            and os.path.getmtime(os.path.join(dp, f)) >= c["started"]]
    if not pngs:
        return ["no new image file was rendered"]
    reply = " ".join(c["replies"])
    out = []
    if not any(os.path.basename(p) in reply for p in pngs):
        out.append("the reply doesn't say where the render is")
    try:
        from PIL import Image, ImageStat
        image = Image.open(pngs[0]).convert("L")
        if max(ImageStat.Stat(image).stddev) < 2:
            out.append("the render is a flat, empty image")
    except ImportError:
        pass
    return out


def _check_delete_keeps_rest(c):
    after = c["after"]["objects"]
    cone_left = any(o["type"] == "MESH" and n.startswith("Cone") for n, o in after.items())
    out = ["cone still there"] if cone_left else []
    out += [f"{n} was lost" for n in ("Cube", "Camera", "Light", "Ball") if n not in after]
    return out


def _check_rename(c):
    return [] if "Crate" in c["after"]["objects"] and "Cube" not in c["after"]["objects"] else ["no object named Crate"]


def _check_save_safely(c):
    sentinel = os.path.join(c["home"], "Documents", "jarvis_scene.blend")
    out = []
    with open(sentinel, "rb") as f:
        if f.read() != b"an older project":
            out.append("an existing jarvis_scene.blend was overwritten")
    path = c["after"]["filepath"]
    if not path or not os.path.exists(path):
        out.append("the scene wasn't saved anywhere")
    return out


def _check_chain(c):
    made = new_objects(c["before"], c["after"])
    if len(made) != 1:
        return [f"expected one new mesh, found {made}"]
    o = c["after"]["objects"][made[0]]
    out = [] if reddish(mat(o).get("base")) else ["it isn't red"]
    if o["location"][2] < 1.5:
        out.append(f"it wasn't moved up (z={o['location'][2]:.2f})")
    return out


def _check_on_floor(c):
    ball = c["after"]["objects"]["Ball"]
    return [] if close(ball["min"][2], 0.0, 0.01) else [f"the ball's bottom is at z={ball['min'][2]:.2f}"]


def _check_frame_all(c):
    meshes = [o for o in c["after"]["objects"].values() if o["type"] == "MESH"]
    points = [p for o in meshes for p in corners(o)]
    seen = in_view(c["bridge"], points)
    return [] if all(seen) else [f"{seen.count(False)} of {len(seen)} object corners are outside the camera's view"]


def _check_dims_exact(c):
    cube = c["after"]["objects"]["Cube"]
    return [] if close(cube["dimensions"][2], 3.0) else [f"the cube is {cube['dimensions'][2]:.2f} m tall"]


def _check_ai_table(c):
    made = [c["after"]["objects"][n] for n in new_objects(c["before"], c["after"])]
    if len(made) < 5:
        return [f"only {len(made)} new parts"]
    top = max(made, key=lambda o: o["max"][2])
    legs = [o for o in made if o is not top and o["max"][2] <= top["min"][2] + 0.05]
    out = [] if len(legs) >= 4 else [f"{len(legs)} parts stand under the top"]
    if legs and any(o["min"][2] > 0.05 + min(l["min"][2] for l in legs) for o in legs):
        out.append("the legs don't all reach the same floor")
    return out


def _check_ai_snowman(c):
    made = [c["after"]["objects"][n] for n in new_objects(c["before"], c["after"])]
    balls = sorted((o for o in made if o["verts"] > 100), key=lambda o: o["location"][2])
    if len(balls) < 3:
        return [f"{len(balls)} round parts"]
    out = []
    sizes = [b["dimensions"][2] for b in balls[:3]]
    if not sizes[0] > sizes[1] > sizes[2]:
        out.append(f"the balls don't get smaller going up ({[round(s, 2) for s in sizes]})")
    for low, high in zip(balls, balls[1:3]):
        gap = high["min"][2] - low["max"][2]
        if gap > 0.05:
            out.append(f"a ball floats {gap:.2f} m above the one under it")
    return out


def _check_ai_on_top(c):
    made = [c["after"]["objects"][n] for n in new_objects(c["before"], c["after"])]
    cube = c["after"]["objects"]["Cube"]
    ball = next((o for o in made if o["verts"] > 100), None)
    if not ball:
        return ["no sphere was made"]
    out = [] if abs(ball["min"][2] - cube["max"][2]) < 0.05 else [
        f"the sphere's bottom is {ball['min'][2] - cube['max'][2]:+.2f} m from the cube's top"]
    if not reddish(mat(ball).get("base")):
        out.append("the sphere isn't red")
    if (mat(ball).get("metallic") or 0) < 0.8:
        out.append("the sphere isn't metal")
    return out


def _villa_parts(c):
    made = {n: c["after"]["objects"][n] for n in new_objects(c["before"], c["after"])}
    building = {n: o for n, o in made.items() if not any(w in n.lower() for w in ("ground", "path", "driveway",
                                                                                   "tree", "hedge"))}
    return made, building


def _check_villa(c):
    """A villa, measured from Blender's own data: many parts of the kinds a building has, two storeys of walls with a
    roof on top, real glass, a door at the entrance, standing on the ground, lit by a sun, framed by the camera, and
    a preview picture that isn't empty. A cube (or a few boxes) fails nearly all of it."""
    made, building = _villa_parts(c)
    out = []
    if len(made) < 40:
        out.append(f"only {len(made)} new parts")
    words = {k: [n for n in building if k in n.lower()] for k in ("wall", "roof", "glass", "door", "floor")}
    out += [f"no {k} parts" for k, names in words.items() if not names]
    if building:
        lo = [min(o["min"][i] for o in building.values()) for i in range(3)]
        hi = [max(o["max"][i] for o in building.values()) for i in range(3)]
        if hi[2] - lo[2] < 6.0:
            out.append(f"only {hi[2] - lo[2]:.1f} m tall (two storeys need 6+)")
        if (hi[0] - lo[0]) * (hi[1] - lo[1]) < 150:
            out.append(f"footprint only {(hi[0] - lo[0]) * (hi[1] - lo[1]):.0f} m2")
        if abs(lo[2]) > 0.01:
            out.append(f"the building's bottom is at z={lo[2]:.2f}, not on the ground")
        walls_top = max((building[n]["max"][2] for n in words["wall"]), default=0)
        roofs = [building[n] for n in words["roof"] if "canopy" not in n]
        if roofs and min(r["min"][2] for r in roofs) < walls_top - 3.5:
            out.append("a roof sits below the top storey")
        if not any(r["max"][2] >= walls_top for r in roofs):
            out.append("no roof over the top of the walls")
        seen = in_view(c["bridge"], [p for n in building for p in corners(building[n])])
        if not all(seen):
            out.append(f"{seen.count(False)} building corners are outside the camera's view")
    glass = [n for n in words["glass"] if (mat(building[n]).get("transmission") or 0) >= 0.9]
    if len(glass) < 10:
        out.append(f"{len(glass)} clear glass panes")
    unlinked = [n for n, o in made.items() if o["type"] == "MESH" and not mat(o).get("linked")]
    if unlinked:
        out.append(f"{len(unlinked)} parts without a working material ({unlinked[:3]})")
    if not any(o.get("light", {}).get("type") == "SUN" and o["light"]["energy"] > 0
               for o in c["after"]["objects"].values()):
        out.append("no sun")
    # Two storeys must be reachable: stairs, under an open stairwell.
    response = c["bridge"].run(STAIRWELLS, timeout=30)
    wells = json.loads(response["output"]) if response.get("ok") else {}
    if not wells:
        out.append("no stairs to the upper floor")
    out += [f"{n} leads into a closed ceiling" for n, is_open in wells.items() if not is_open]
    # No lamp left standing inside the building (Blender's startup lamp sits where an upper floor goes).
    if building:
        for n, o in c["after"]["objects"].items():
            if o["type"] == "LIGHT" and o["light"]["type"] != "SUN" and all(
                    lo[i] < o["location"][i] < hi[i] for i in range(3)):
                out.append(f"the lamp {n} is inside the building")
    out += _check_preview(c)
    return out


def _check_preview(c):
    reply = " ".join(c["replies"])
    # Blender saves the preview under its own home folder (Documents\Jarvis renders), which may sit outside c["folder"].
    pngs = sorted({os.path.normcase(os.path.abspath(os.path.join(dp, f))) for root in {c["folder"], c["home"]}
                   for dp, _, fs in os.walk(root) for f in fs   # (the home folder may sit inside c["folder"])
                   if f.lower().endswith(".png") and os.path.getmtime(os.path.join(dp, f)) >= c["started"]
                   and os.path.basename(f) in reply})
    if not pngs:
        return ["no preview picture named in the reply"]
    c.setdefault("evidence", []).extend(pngs)
    try:
        from PIL import Image, ImageStat
        if max(ImageStat.Stat(Image.open(pngs[0]).convert("L")).stddev) < 2:
            return ["the preview is a flat, empty image"]
    except ImportError:
        pass
    return []


def _check_villa_features(c):
    made, building = _villa_parts(c)
    out = _check_villa(c)
    water = [n for n in made if "water" in n.lower() and (mat(made[n]).get("transmission") or 0) > 0.5]
    crowns = [n for n in made if "crown" in n.lower()]
    garage = [n for n in made if "garage" in n.lower() and "panel" in n.lower()]
    out += [] if water else ["no pool water"]
    out += [] if len(crowns) >= 4 else [f"{len(crowns)} trees"]
    out += [] if garage else ["no garage door"]
    return out


TASKS = [
    ("describe", "inspection", "", ["what's in the scene"], _check_describe),
    ("create", "creation", "", ["create a cylinder"], _check_create_cylinder),
    ("move-up", "transforms", "", ["move the cube up 3 meters"], _check_move_up),
    ("width", "dimensions", "", ["make the cube 4 meters wide"], _check_width),
    ("height", "dimensions", "", ["make the cube 3 meters tall"], _check_dims_exact),
    ("red", "materials", "", ["make the cube red"], _check_red),
    ("metal", "materials", "", ["make the cube shiny metal"], _check_metal),
    ("glass", "materials", "", ["make the cube glass"], _check_glass),
    ("glow", "materials", "", ["make the cube glow blue"], _check_glow),
    ("bevel", "modifiers", "", ["bevel the cube"], _check_bevel),
    ("smooth", "modifiers", "", ["create a sphere", "shade it smooth"], _check_smooth),
    ("subsurf", "modifiers", "", ["add a subdivision surface to the cube"], _check_subsurf),
    ("sun", "lighting", "", ["add a sun light"], _check_sun),
    ("aim-camera", "camera", "bpy.data.objects['Cube'].location = (6, 4, 1)",
     ["point the camera at the cube"], _check_camera_aim),
    ("render", "rendering", "", ["render the scene"], _check_render),
    ("delete-one", "non-destructive edit",
     "bpy.ops.mesh.primitive_uv_sphere_add(location=(4, 0, 0)); bpy.context.object.name = 'Ball'\n"
     "bpy.ops.mesh.primitive_cone_add(location=(-4, 0, 0))", ["delete the cone"], _check_delete_keeps_rest),
    ("rename", "editing", "", ["rename the cube to Crate"], _check_rename),
    ("save-safely", "persistence", "SENTINEL", ["save"], _check_save_safely),
    ("chain", "multi-step", "", ["create a sphere, make it red and move it up"], _check_chain),
    ("on-floor", "repair", "bpy.ops.mesh.primitive_uv_sphere_add(location=(3, 0, 5)); bpy.context.object.name = 'Ball'",
     ["put the ball on the floor"], _check_on_floor),
    ("frame-all", "repair",
     "bpy.data.objects['Camera'].rotation_euler = (0, 0, 0)\n"
     "bpy.ops.mesh.primitive_uv_sphere_add(location=(5, 3, 0)); bpy.ops.mesh.primitive_cone_add(location=(-4, -2, 0))",
     ["make the camera show everything"], _check_frame_all),
    ("villa", "building", "", ["create a villa"], _check_villa),
    ("villa-features", "building", "", ["build a modern villa with a pool, a garden and a garage"],
     _check_villa_features),
    ("ai-villa", "ai: building", "", ["create a villa"], _check_villa),
    ("ai-table", "ai: modeling", "bpy.data.objects.remove(bpy.data.objects['Cube'])",
     ["build a simple table with four legs"], _check_ai_table),
    ("ai-snowman", "ai: modeling", "bpy.data.objects.remove(bpy.data.objects['Cube'])",
     ["build a snowman out of three spheres"], _check_ai_snowman),
    ("ai-on-top", "ai: placement", "", ["put a red metal sphere on top of the cube"], _check_ai_on_top),
]

RESET = ("bpy.ops.wm.read_factory_settings(use_empty=False)\n"
         "RESULT = ', '.join(o.name for o in bpy.data.objects)")


def _ask_local_ai(messages, tools):
    import local_llm
    return local_llm.chat(messages=messages, tools=tools, tool_choice="required")


def run_request(text, session, bridge, use_ai, max_steps, ai_only=False, trace=None):
    """What the app does with `text` said while Blender is open (app.run_blender_directly, then
    start_computer_task's Blender branch) -> (reply, how it was handled). `ai_only` skips the deterministic
    commands, to measure the free-form AI task on its own; `trace` (a list) collects the AI's steps."""
    steps = None if ai_only else blender_commands.steps_for(text, session, bridge)
    if steps:
        results = []
        for _, action in steps:
            try:
                results.append(action())
            except Exception as e:
                results.append(str(e))
                break
        return " ".join(r for r in results if r), "deterministic"
    if not blender_commands.looks_concrete(text):
        return blender_commands.clarification_for(text), "clarified"
    if not use_ai:
        return "", "needs the AI (not run)"
    task = computer_use.BlenderComputerTask(text, NoScreen(), _ask_local_ai, bridge, session=session,
                                            max_steps=max_steps, log=lambda *a: None)
    reply = task.run()
    if trace is not None:
        trace.extend(f"{did[:200]} -> {happened[:300]}" for did, happened in task.history)
    return reply, f"ai ({task.step} steps, {task.state})"


def run(names=None, use_ai=False, max_steps=12, folder=None, verbose=True, ai_only=False):
    folder = folder or tempfile.mkdtemp(prefix="jarvis-blender-bench-")
    results = []
    with RealBlender(folder) as bridge:
        version = bridge.run("RESULT = bpy.app.version_string").get("output")
        home = os.path.join(folder, "home")
        for name, area, setup, requests, check in TASKS:
            if names and name not in names:
                continue
            if name.startswith("ai-") and not (use_ai or ai_only) and not names:
                continue
            reset = bridge.run(RESET, timeout=30)
            sentinel = os.path.join(home, "Documents", "jarvis_scene.blend")
            if os.path.exists(sentinel):
                os.remove(sentinel)
            if setup == "SENTINEL":
                with open(sentinel, "wb") as f:
                    f.write(b"an older project")
            elif setup:
                done = bridge.run(setup, timeout=30)
                if not done.get("ok"):
                    raise RuntimeError(f"{name}: setup failed: {done.get('error')}")
            session = computer_use.ControlSession(env=None)
            session.blender = bridge
            ctx = {"bridge": bridge, "folder": folder, "home": home, "replies": [], "handled": [],
                   "before": state(bridge), "started": time.time()}
            started = time.time()
            errors = 0
            trace = []
            for text in requests:
                try:
                    reply, how = run_request(text, session, bridge, use_ai or ai_only, max_steps, ai_only, trace)
                except Exception as e:
                    reply, how = f"crashed: {type(e).__name__}: {e}", "crashed"
                    errors += 1
                ctx["replies"].append(reply)
                ctx["handled"].append(how)
            seconds = time.time() - started
            ctx["after"] = state(bridge)
            try:
                failed = check(ctx)
            except Exception as e:
                failed = [f"check crashed: {type(e).__name__}: {e}"]
            results.append({"task": name, "area": area, "passed": not failed, "failed": failed,
                            "handled": ctx["handled"], "seconds": round(seconds, 2), "replies": ctx["replies"],
                            "errors": errors, "reset": reset.get("ok"), "ai_steps": trace,
                            "evidence": ctx.get("evidence", [])})
            if verbose:
                mark = "PASS" if not failed else "FAIL"
                print(f"{mark} {name:12} {seconds:6.2f}s  {', '.join(ctx['handled'])}  {'; '.join(failed)[:150]}",
                      flush=True)
    passed = sum(r["passed"] for r in results)
    summary = {"blender": version, "ai": use_ai, "passed": passed, "total": len(results), "tasks": results}
    if verbose:
        print(f"\n{passed}/{len(results)} passed on Blender {version}")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai", action="store_true", help="also run requests the deterministic commands don't know "
                                                          "through the free-form AI task (local AI)")
    parser.add_argument("--ai-only", action="store_true", help="send every request to the free-form AI task, "
                                                               "skipping the deterministic commands")
    parser.add_argument("--only", default="", help="comma-separated task names")
    parser.add_argument("--steps", type=int, default=12, help="the AI task's step limit")
    parser.add_argument("--out", default="", help="write the results here as JSON")
    args = parser.parse_args()
    summary = run(names=[n for n in args.only.split(",") if n] or None, use_ai=args.ai, max_steps=args.steps,
                  ai_only=args.ai_only)
    if args.out:
        import shutil
        folder = os.path.join(os.path.dirname(os.path.abspath(args.out)), "bench-evidence")
        for task in summary["tasks"]:   # the pictures the checks looked at, kept next to the results
            for i, path in enumerate(task["evidence"]):
                os.makedirs(folder, exist_ok=True)
                kept = os.path.join(folder, f"{task['task']}-{i + 1}.png")
                shutil.copyfile(path, kept)
                task["evidence"][i] = kept
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1)


if __name__ == "__main__":
    main()
