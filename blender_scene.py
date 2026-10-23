"""Helpers that run *inside* Blender, in the bridge's namespace (see blender_bridge.py): reading the scene as facts,
checking it for defects that can be measured, and the operations everyday requests need done the same, correct way
every time — materials, modifiers, lights, camera aim and framing, putting things on the floor, rendering.

Jarvis never imports this file: blender_control.with_kit() sends its source along with any request that uses it,
and it is exec'd into the bridge's namespace once per Blender session (again only when this file changes). So
blender_commands.py's verified commands and the AI's own run_python code (BlenderComputerTask) share one tested
implementation instead of each writing raw bpy from scratch.

Everything here works with plain bpy data (no bpy.ops that need a 3D View under the mouse), which is what makes it
work from the bridge's timer and from a headless `blender -b` alike. Checked on Blender 4.5; the Principled BSDF
input names that changed in 4.0 are looked up by either name.
"""
import json
import math
import os
import re
import time

import bpy
import mathutils
from mathutils import Vector

def _scene():
    return bpy.context.scene


def _sync():
    """Blender recomputes world matrices and dimensions only on a view-layer update: without one, a location or
    rotation set earlier in the same script still reads as the old one."""
    bpy.context.view_layer.update()


def find(name):
    """The object called `name` (exact, then case-insensitive, then by prefix: "cube" finds "Cube.001")."""
    if not isinstance(name, str):
        return name
    objects = _scene().objects
    o = objects.get(name)
    if o:
        return o
    low = name.lower()
    o = next((o for o in objects if o.name.lower() == low), None) or \
        next((o for o in objects if o.name.lower().startswith(low)), None)
    if o is None:
        raise ValueError(f"there's no object called {name!r}; the scene has: " +
                         ", ".join(o.name for o in objects)[:300])
    return o


def box(o):
    """(min, max) corners of `o` in world space, modifiers included — for a group (an empty with parts), of all
    its parts."""
    parts = [o]
    if o.children:   # a group: the bounds of its parts (an empty's own box is just a point)
        parts = [p for p in [o, *o.children_recursive] if p.type != 'EMPTY'] or [o]
    corners = [p.matrix_world @ Vector(c) for p in parts for c in p.bound_box]
    return (Vector([min(c[i] for c in corners) for i in range(3)]),
            Vector([max(c[i] for c in corners) for i in range(3)]))


def _visible_meshes(exclude=()):
    return [o for o in _scene().objects if o.type == 'MESH' and o.visible_get() and o not in exclude]


def _overlap(a, b, pad=0.0):
    (alo, ahi), (blo, bhi) = a, b
    return all(alo[i] < bhi[i] - pad and ahi[i] > blo[i] + pad for i in range(3))


# ---------- reading the scene ----------

_INPUTS = {"color": ("Base Color",), "metallic": ("Metallic",), "roughness": ("Roughness",),
           "transmission": ("Transmission Weight", "Transmission"), "emission": ("Emission Color", "Emission"),
           "emission_strength": ("Emission Strength",), "alpha": ("Alpha",), "ior": ("IOR",),
           "coat": ("Coat Weight", "Clearcoat")}


def _socket(node, key):
    return next((node.inputs[n] for n in _INPUTS[key] if n in node.inputs), None)


def _principled(mat):
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)


def _material_line(mat):
    if mat is None:
        return "no material"
    node = _principled(mat)
    if node is None:
        return f"{mat.name} (no Principled BSDF)"
    def val(key):
        s = _socket(node, key)
        return None if s is None or s.is_linked else s.default_value
    parts = []
    color = val("color")
    if color is not None:
        parts.append("color " + "/".join(f"{c:.2f}" for c in color[:3]))
    elif _socket(node, "color").is_linked:
        parts.append("textured color")
    for key in ("metallic", "roughness", "transmission"):
        v = val(key)
        if v is not None and (key == "roughness" or v > 0):
            parts.append(f"{key} {v:.2f}")
    strength = val("emission_strength")
    if strength:
        parts.append(f"glows {strength:.1f}")
    if not _connected(mat, node):
        parts.append("NOT connected to the output")
    return f"{mat.name} ({', '.join(parts)})"


def _connected(mat, node):
    out = next((n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
    if out is None:
        out = next((n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)
    return bool(out and out.inputs['Surface'].is_linked and out.inputs['Surface'].links[0].from_node == node)


def _r(v, digits=2):
    return "(" + ", ".join(f"{round(x, digits) + 0.0:g}" for x in v) + ")"


def report(names=None, limit=40):
    """The scene as compact facts, one line per object: what it is, where, how big, its rotation, materials,
    modifiers, light and camera settings — what a person checking the work would look at."""
    _sync()
    scene = _scene()
    objects = [find(n) for n in names] if names else list(scene.objects)
    lines = [f"Blender {bpy.app.version_string}; scene '{scene.name}', render engine {scene.render.engine}, "
             f"camera {scene.camera.name if scene.camera else 'none'}, "
             f"{len(scene.objects)} objects" + (f", file {os.path.basename(bpy.data.filepath)}"
                                                if bpy.data.filepath else ", not saved yet")]
    active = bpy.context.view_layer.objects.active
    for o in objects[:limit]:
        line = f"- {o.name} [{o.type.lower()}] at {_r(o.location)}"
        if any(abs(a) > 1e-4 for a in o.rotation_euler):
            line += f", rotated {_r([math.degrees(a) for a in o.rotation_euler], 0)} deg"
        if o.type == 'MESH':
            lo, hi = box(o)
            line += f", size {_r(o.dimensions)} m, spans z {lo.z:.2f}..{hi.z:.2f}"
            mats = [s.material for s in o.material_slots] or [None]
            line += "; material " + "; ".join(_material_line(m) for m in mats[:3])
            if o.modifiers:
                line += "; modifiers " + ", ".join(f"{m.type.lower()}" + (f" w={m.width:.3f}" if m.type == 'BEVEL'
                                                                          else f" lv={m.levels}" if m.type == 'SUBSURF'
                                                                          else "") for m in o.modifiers)
            if o.data.polygons and o.data.polygons[0].use_smooth:
                line += "; smooth shaded"
        elif o.type == 'LIGHT':
            line += f", {o.data.type.lower()} light {o.data.energy:g} W"
        elif o.type == 'CAMERA':
            line += f", lens {o.data.lens:g} mm"
        if o.parent:
            line += f", child of {o.parent.name}"
        if not o.visible_get():
            line += ", hidden"
        if o == active:
            line += " (active)"
        lines.append(line)
    if len(objects) > limit:
        lines.append(f"(+{len(objects) - limit} more objects)")
    return "\n".join(lines)


def digest():
    """Each object's facts as short strings ({name: {"type", "at", "size", ...}}), to compare before and after a
    script: what really changed is then measured, not assumed from the script running without an error."""
    _sync()
    out = {}
    for o in _scene().objects:
        d = {"type": o.type.lower(), "at": _r(o.location)}
        if any(abs(a) > 1e-4 for a in o.rotation_euler):
            d["rotated"] = _r([math.degrees(a) for a in o.rotation_euler], 0)
        if o.type == 'MESH' or o.children:
            d["size"] = _r(size_of(o))
            lo, hi = box(o)
            d["spans z"] = f"{lo.z:.2f}..{hi.z:.2f}"   # where its bottom really is, not just its origin
        if o.type == 'MESH':
            d["material"] = "; ".join(_material_line(s.material) for s in o.material_slots) or "none"
            d["modifiers"] = ", ".join(m.type.lower() for m in o.modifiers) or "none"
            d["shading"] = "smooth" if o.data.polygons and o.data.polygons[0].use_smooth else "flat"
        if o.type == 'LIGHT':
            d["light"] = f"{o.data.type.lower()} {o.data.energy:g} W"
        if o.parent:
            d["parent"] = o.parent.name
        if not o.visible_get():
            d["hidden"] = "yes"
        out[o.name] = d
    return out


_KIND_WORDS = {'MESH': "object", 'LIGHT': "light", 'CAMERA': "camera", 'EMPTY': "empty", 'CURVE': "curve",
               'FONT': "text", 'ARMATURE': "armature"}


def describe():
    """The scene in a sentence or two, for saying out loud: the top-level things (a group's parts are counted,
    not listed one by one)."""
    _sync()
    objects = [o for o in _scene().objects if o.parent is None]
    if not objects:
        return "The scene is empty."
    parts = []
    for o in objects[:12]:
        kind = o.data.type.lower() + " light" if o.type == 'LIGHT' else _KIND_WORDS.get(o.type, o.type.lower())
        if o.type == 'MESH' or o.children:
            size = " by ".join(f"{round(d, 1) + 0.0:g}" for d in size_of(o))
            mat = o.active_material
            named = f", {mat.name}" if mat and not mat.name.startswith("Material") else ""
            made_of = f", a group of {len(o.children_recursive)} parts" if o.children else ""
            parts.append(f"{o.name}{made_of}, {size} metres{named}")
        else:
            parts.append(f"{o.name}, a {kind}" if kind.split()[0] not in o.name.lower() else o.name)
    more = f", and {len(objects) - 12} more" if len(objects) > 12 else ""
    noun = "thing" if len(objects) == 1 else "things"
    return f"The scene has {len(objects)} {noun}: " + "; ".join(parts) + more + "."


def check(names=None):
    """Defects that can be measured, worst first: [{"object", "problem", "severity"}]. "error" means broken
    (a material that shows nothing, a camera that sees none of it, an object squashed to nothing); "warning" is
    probably unintended (floating, inside another object, no material, nothing lighting the scene) — the AI or
    the user may know better, so warnings never block anything."""
    _sync()
    scene = _scene()
    problems = []
    def add(o, problem, severity="warning"):
        problems.append({"object": o.name if o else "", "problem": problem, "severity": severity})
    meshes = _visible_meshes()
    targets = [find(n) for n in names] if names else meshes
    boxes = {o.name: box(o) for o in meshes}
    for o in targets:
        if o.type != 'MESH':
            continue
        lo, hi = boxes.get(o.name) or box(o)
        if any(math.isnan(v) for v in tuple(o.location) + tuple(o.scale)):
            add(o, "has an invalid location or scale (NaN)", "error")
            continue
        if min(o.dimensions) < 1e-5 and len(o.data.polygons) > 1 and min(abs(s) for s in o.scale) < 1e-5:
            add(o, "is squashed flat (a scale of 0)", "error")
        for slot in o.material_slots:
            node = _principled(slot.material)
            if slot.material and node and not _connected(slot.material, node):
                add(o, f"material {slot.material.name}'s shader isn't connected to its output, so it renders "
                       "black or empty", "error")
        if not o.material_slots or not any(s.material for s in o.material_slots):
            add(o, "has no material")
        if not o.parent:
            _floating(o, (lo, hi), boxes, add)
        for n, other in boxes.items():
            if n == o.name or o.parent and o.parent.name == n:
                continue
            olo, ohi = other
            inter = [max(0.0, min(hi[i], ohi[i]) - max(lo[i], olo[i])) for i in range(3)]
            vol = inter[0] * inter[1] * inter[2]
            smaller = min(_vol(lo, hi), _vol(olo, ohi))
            if smaller > 1e-6 and vol > 0.5 * smaller:
                add(o, f"is mostly inside {n}")
    for root in scene.objects:   # a group (an empty with parts) floats or stands as one thing
        if root.type == 'EMPTY' and root.parent is None and root.children and (not names or root in targets):
            _floating(root, box(root), boxes, add)
    cam = scene.camera
    if cam is None:
        add(None, "the scene has no camera, so it can't be rendered", "error")
    elif meshes:
        unseen = [o.name for o in meshes if not any(_in_view(cam, c) for c in _corners(boxes[o.name]))]
        if len(unseen) == len(meshes):
            add(cam, "the camera doesn't see any object", "error")
        elif unseen:
            add(cam, "the camera doesn't see " + ", ".join(unseen[:6]))
    lights = [o for o in scene.objects if o.type == 'LIGHT' and o.visible_get() and o.data.energy > 0]
    world = scene.world
    world_strength = 0.0
    if world and world.use_nodes:
        bg = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None)
        if bg:
            world_strength = bg.inputs['Strength'].default_value * max(bg.inputs['Color'].default_value[:3])
    glowing = any(_glows(s.material) for o in meshes for s in o.material_slots)
    if meshes and not lights and world_strength < 0.05 and not glowing:
        add(None, "nothing lights the scene (no lights, a dark world), so a render will be black", "error")
    order = {"error": 0, "warning": 1}
    return sorted(problems, key=lambda p: order[p["severity"]])


def _floating(o, bounds, boxes, add):
    """Warn when `o` (an object or a whole group) hangs in the air: its bottom above the ground with nothing
    right under it."""
    lo, hi = bounds
    if lo.z <= 0.02:
        return
    own = {o.name} | {c.name for c in o.children_recursive}
    below = [n for n, (blo, bhi) in boxes.items() if n not in own and bhi.z <= lo.z + 0.02
             and blo.x < hi.x and bhi.x > lo.x and blo.y < hi.y and bhi.y > lo.y]
    top = max(boxes[n][1].z for n in below) if below else 0.0
    if lo.z - top > 0.02:
        add(o, f"floats {lo.z - top:.2f} m above {'what is under it' if below else 'the ground'}")


def _glows(mat):
    node = _principled(mat)
    strength, color = (_socket(node, "emission_strength"), _socket(node, "emission")) if node else (None, None)
    return bool(strength and color and strength.default_value > 0 and max(color.default_value[:3]) > 0)


def _vol(lo, hi):
    return max(0.0, hi.x - lo.x) * max(0.0, hi.y - lo.y) * max(0.0, hi.z - lo.z)


def _corners(b):
    lo, hi = b
    return [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]


def sees(cam=None, objects=None):
    """Whether every corner of `objects` (default: every visible object) is in `cam`'s picture."""
    cam = find(cam) if cam else _scene().camera
    if cam is None:
        return False
    _sync()
    targets = [find(n) for n in objects] if objects else _visible_meshes()
    return all(_in_view(cam, c) for t in targets for c in _corners(box(t)))


def shader_values(o):
    """The values `o`'s material really has: {"color", "metallic", ...} (only inputs that aren't textured)."""
    mat = find(o).active_material
    node = _principled(mat)
    if node is None:
        return {}
    out = {}
    for key in _INPUTS:
        sock = _socket(node, key)
        if sock is not None and not sock.is_linked:
            v = sock.default_value
            out[key] = list(v)[:3] if hasattr(v, "__len__") else float(v)
    out["connected"] = _connected(mat, node)
    return out


def matches(o, expected, tolerance=0.02):
    """(True, "") when `o`'s material really has the `expected` values and feeds the output, else (False, what's
    different) — for checking a change took, from Blender's data rather than from what was meant to be set."""
    have = shader_values(o)
    if not have:
        return False, f"{find(o).name} has no Principled material"
    if not have.get("connected"):
        return False, "its shader isn't connected to the material output"
    for key, want in expected.items():
        got = have.get(key)
        if got is None:
            return False, f"its material has no {key} setting"
        pairs = zip(got, want) if isinstance(want, (list, tuple)) else [(got, want)]
        if any(abs(g - w) > tolerance for g, w in pairs):
            return False, f"its {key} is {got}, not {want}"
    return True, ""


def _in_view(cam, point, margin=0.0):
    from bpy_extras.object_utils import world_to_camera_view
    v = world_to_camera_view(_scene(), cam, point)
    return v.z > 0 and margin <= v.x <= 1 - margin and margin <= v.y <= 1 - margin


# ---------- materials ----------

def material(name, color=None, metallic=None, roughness=None, transmission=None, emission=None,
             emission_strength=None, alpha=None, ior=None, coat=None):
    """The material called `name` (made if missing) with a Principled BSDF that really feeds the output, and the
    given values set on it — RGB colors 0..1. Also sets the solid-view color, so it looks right in the viewport."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    node = _principled(mat) or nodes.new('ShaderNodeBsdfPrincipled')
    out = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None) or \
        next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None) or nodes.new('ShaderNodeOutputMaterial')
    if not _connected(mat, node):
        for link in list(out.inputs['Surface'].links):
            links.remove(link)
        links.new(node.outputs['BSDF'], out.inputs['Surface'])
    values = {"metallic": metallic, "roughness": roughness, "transmission": transmission,
              "emission_strength": emission_strength, "alpha": alpha, "ior": ior, "coat": coat}
    if color is not None:
        rgba = tuple(color[:3]) + (1.0,)
        _socket(node, "color").default_value = rgba
        mat.diffuse_color = rgba[:3] + (mat.diffuse_color[3],)
    if emission is not None:
        _socket(node, "emission").default_value = tuple(emission[:3]) + (1.0,)
        if emission_strength is None and _socket(node, "emission_strength").default_value == 0:
            values["emission_strength"] = 5.0
    for key, value in values.items():
        s = _socket(node, key)
        if value is not None and s is not None:
            s.default_value = float(value)
    if metallic is not None:
        mat.metallic = float(metallic)
    if roughness is not None:
        mat.roughness = float(roughness)
    if alpha is not None or transmission is not None:
        faded = alpha is not None and alpha < 1
        if hasattr(mat, "surface_render_method"):   # Blender 4.2+
            mat.surface_render_method = 'BLENDED' if faded else 'DITHERED'
        else:
            mat.blend_method = 'BLEND' if faded else ('HASHED' if transmission else 'OPAQUE')
        # The solid view can't show glass: a see-through tint there; back to opaque when it stops being glass.
        viewport_alpha = alpha if faded else (0.35 if transmission else 1.0)
        mat.diffuse_color = tuple(mat.diffuse_color[:3]) + (viewport_alpha,)
    return mat


def paint(o, **values):
    """Change `o`'s own material (see material()): one shared with other objects is copied first, so painting one
    object never changes the others. Returns the material."""
    o = find(o)
    current = o.active_material
    if current is None:
        mat = material(f"{o.name} material", **values)
    else:
        mat = current
        if current.users > 1 + (1 if current.use_fake_user else 0):
            mat = current.copy()
            mat.name = f"{o.name} material"
        mat = material(mat.name, **values)
    if o.data is not None and hasattr(o.data, "materials"):
        if o.material_slots:
            for slot in o.material_slots:
                if slot.material in (None, current):
                    slot.material = mat
        else:
            o.data.materials.append(mat)
    return mat


# ---------- geometry and modifiers ----------

def bevel(o, width=None, segments=3):
    """Rounded edges, as a Bevel modifier (non-destructive). The default width scales with the object (3% of its
    smallest side), so a 2 m cube and a 10 cm cup both look right."""
    o = find(o)
    if width is None:
        width = max(0.002, 0.03 * min(d for d in o.dimensions if d > 1e-6))
    mod = next((m for m in o.modifiers if m.type == 'BEVEL'), None) or o.modifiers.new("Bevel", 'BEVEL')
    mod.width = width
    mod.segments = segments
    mod.limit_method = 'ANGLE'
    if hasattr(mod, "harden_normals"):
        mod.harden_normals = True
    _sync()
    return mod


def subdivide(o, levels=2):
    o = find(o)
    mod = next((m for m in o.modifiers if m.type == 'SUBSURF'), None) or o.modifiers.new("Subdivision", 'SUBSURF')
    mod.levels = levels
    mod.render_levels = max(levels, mod.render_levels)
    _sync()
    return mod


def smooth(o, on=True):
    """Smooth (or flat) shading on every face."""
    o = find(o)
    if o.type != 'MESH':
        raise ValueError(f"{o.name} is a {o.type.lower()}, which has no faces to shade")
    o.data.polygons.foreach_set("use_smooth", [bool(on)] * len(o.data.polygons))
    o.data.update()
    return o


def evaluated_vertex_count(o):
    """How many vertices the mesh that renders has (modifiers applied), without changing the object."""
    o = find(o)
    evaluated = o.evaluated_get(bpy.context.evaluated_depsgraph_get())
    try:
        return len(evaluated.to_mesh().vertices)
    finally:
        evaluated.to_mesh_clear()


def size_of(o):
    """(x, y, z) size in metres: an object's own dimensions, or a group's overall extent."""
    o = find(o)
    _sync()
    if o.children and o.type == 'EMPTY':
        lo, hi = box(o)
        return tuple(hi - lo)
    return tuple(o.dimensions)


def set_size(o, axis, metres):
    """Scale `o` so its size along x, y or z is exactly `metres` (the other sides keep theirs) — or, with axis
    "max", so its biggest side is, keeping its proportions. A group scales as a whole."""
    o = find(o)
    size = size_of(o)
    if axis == "max":
        current = max(size)
        if current < 1e-6:
            raise ValueError(f"{o.name} has no size to scale")
        o.scale = [v * metres / current for v in o.scale]
        _sync()
        return o
    i = "xyz".index(axis)
    if size[i] < 1e-6:
        raise ValueError(f"{o.name} has no size along {axis} to scale")
    s = list(o.scale)
    s[i] *= metres / size[i]
    o.scale = s
    _sync()
    return o


# ---------- building ----------
# Every builder takes real sizes in metres and `at` = the centre of the object's BOTTOM face, with the object's
# origin there too: a leg 0.7 m tall at z=0 stands on the floor and reaches 0.7, a top at z=0.7 sits on it — no
# half-height arithmetic to get wrong. Built from bmesh, so no 3D View or selection is needed.

def _build(name, fill, at, color, smooth_it):
    import bmesh
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    try:
        fill(bm)
        lowest = min(v.co.z for v in bm.verts)
        for v in bm.verts:
            v.co.z -= lowest   # origin at the bottom
        bm.to_mesh(mesh)
    finally:
        bm.free()
    o = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(o)
    o.location = Vector(at)
    if smooth_it:
        smooth(o)
    if color is not None:
        paint(o, color=color)
    _make_active(o)
    _sync()
    return o


def _make_active(o):
    """Selected and active, as Blender's own add operators leave a new object: code that goes on with
    bpy.context.object then means this one, not whatever was active before."""
    layer = bpy.context.view_layer
    for other in layer.objects:
        if other is not None:   # an object removed earlier in the session can linger here as None until an update
            other.select_set(False)
    o.select_set(True)
    layer.objects.active = o


def add_box(name, size=(1, 1, 1), at=(0, 0, 0), color=None):
    """A box `size` = (width x, depth y, height z) metres."""
    import bmesh
    w, d, h = size
    return _build(name, lambda bm: bmesh.ops.create_cube(bm, size=1.0, matrix=mathutils.Matrix.Diagonal((w, d, h, 1))),
                  at, color, False)


def add_cylinder(name, radius=0.5, height=1.0, at=(0, 0, 0), color=None, segments=32):
    import bmesh
    return _build(name, lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius,
                                                         radius2=radius, depth=height), at, color, True)


def add_cone(name, radius=0.5, height=1.0, at=(0, 0, 0), color=None, top_radius=0.0, segments=32):
    import bmesh
    return _build(name, lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius,
                                                         radius2=top_radius, depth=height), at, color, True)


def add_sphere(name, radius=0.5, at=(0, 0, 0), color=None):
    import bmesh
    return _build(name, lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=radius),
                  at, color, True)


def add_ground(name="Ground", color=(0.35, 0.35, 0.33), roughness=0.8):
    """A floor under everything: a flat square three times the scene's width, at the lowest object's bottom
    (or z=0), so nothing renders floating in a void. Returns it."""
    _sync()
    meshes = _visible_meshes()
    center, radius = _scene_bounds(meshes)
    lowest = min((box(m)[0].z for m in meshes), default=0.0)
    half = max(radius * 3, 5.0)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-half, -half, 0), (half, -half, 0), (half, half, 0), (-half, half, 0)], [], [(0, 1, 2, 3)])
    o = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(o)
    o.location = (center.x, center.y, min(lowest, 0.0))
    paint(o, color=color, roughness=roughness, metallic=0.0)
    _sync()
    return o


def group(name, parts):
    """Make `parts` one thing: parented to an empty called `name` at the centre of their bottom, so "move the
    table" moves every part and nothing jumps. Returns the empty."""
    parts = [find(p) for p in parts]
    _sync()
    lows, highs = zip(*(box(p) for p in parts))
    lo = Vector([min(v[i] for v in lows) for i in range(3)])
    hi = Vector([max(v[i] for v in highs) for i in range(3)])
    root = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(root)
    root.location = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)
    _sync()
    for p in parts:
        world = p.matrix_world.copy()
        p.parent = root
        p.matrix_parent_inverse = root.matrix_world.inverted()   # assigning a parent resets this: keep it in place
        p.matrix_world = world
    _make_active(root)
    _sync()
    return root


# ---------- placement ----------

def drop_to_floor(o, floor=None):
    """Lower (or raise) `o` until it rests on what's under it — another object's top, or the ground (z=0) — or on
    the height `floor`. Returns the height it now stands on."""
    o = find(o)
    _sync()
    lo, hi = box(o)
    if floor is None:
        tops = [box(m)[1].z for m in _visible_meshes(exclude=(o,) + tuple(o.children_recursive))
                if _xy_overlap(box(m), (lo, hi)) and box(m)[1].z <= lo.z + 1e-4]
        floor = max(tops) if tops else 0.0
    o.location.z += floor - lo.z
    _sync()
    return floor


def _xy_overlap(a, b):
    return a[0].x < b[1].x and a[1].x > b[0].x and a[0].y < b[1].y and a[1].y > b[0].y


def row_of_copies(o, count, gap=None):
    """`count` copies of `o` in a row along +x after it, each a full copy (its own mesh and material slots), so
    each can be changed on its own. Returns the copies."""
    o = find(o)
    _sync()
    lo, hi = box(o)
    step = (hi.x - lo.x) + (gap if gap is not None else max(0.2, 0.25 * (hi.x - lo.x)))
    made = []
    for i in range(1, int(count) + 1):
        c = o.copy()
        if o.data is not None:
            c.data = o.data.copy()
        (o.users_collection[0] if o.users_collection else _scene().collection).objects.link(c)
        c.location.x += step * i
        made.append(c)
    _sync()
    return made


def place_on(o, target):
    """Stand `o` centred on top of `target`."""
    o, target = find(o), find(target)
    bpy.context.view_layer.update()
    tlo, thi = box(target)
    lo, hi = box(o)
    o.location.x += (tlo.x + thi.x) / 2 - (lo.x + hi.x) / 2
    o.location.y += (tlo.y + thi.y) / 2 - (lo.y + hi.y) / 2
    o.location.z += thi.z - lo.z
    _sync()
    return o


def free_spot(o, gap=0.5):
    """Slide `o` along +x until it no longer sits inside another object (a new object would otherwise appear
    inside whatever is already at the origin)."""
    o = find(o)
    bpy.context.view_layer.update()
    for _ in range(200):
        b = box(o)
        hits = [box(m) for m in _visible_meshes(exclude=(o,)) if _overlap(b, box(m), pad=1e-4)]
        if not hits:
            return o
        o.location.x += max(h[1].x for h in hits) - b[0].x + gap
        bpy.context.view_layer.update()
    return o


# ---------- lights and camera ----------

def look_at(o, target):
    """Turn `o` (a camera or light) to face `target`: an object, its name, or a point."""
    o = find(o)
    if not isinstance(target, (Vector, tuple, list)):
        t = find(target)
        lo, hi = box(t) if t.type == 'MESH' else (t.location, t.location)
        target = (Vector(lo) + Vector(hi)) / 2
    direction = Vector(target) - o.matrix_world.translation
    if direction.length < 1e-6:
        return o
    o.rotation_mode = 'XYZ'
    o.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    _sync()
    return o


def add_light(kind="SUN", energy=None, at=None, name=None, aim=None):
    """A light that suits its kind, aimed at the scene (or `aim`): a sun at 45 degrees, point/spot/area lamps up
    and to the side, with a strength that lights a few metres. Returns the object."""
    kind = kind.upper()
    defaults = {"SUN": 3.0, "POINT": 1000.0, "SPOT": 1500.0, "AREA": 400.0}
    data = bpy.data.lights.new(name or f"{kind.title()} light", kind)
    data.energy = defaults.get(kind, 1000.0) if energy is None else energy
    if kind == "AREA":
        data.size = 3.0
    o = bpy.data.objects.new(name or data.name, data)
    bpy.context.collection.objects.link(o)
    center, radius = _scene_bounds()
    o.location = Vector(at) if at else center + Vector((radius + 3, -(radius + 3), radius + 5))
    look_at(o, aim if aim is not None else center)
    return o


def _scene_bounds(objects=None):
    meshes = objects or _visible_meshes()
    if not meshes:
        return Vector((0, 0, 0)), 1.0
    los, his = zip(*(box(m) for m in meshes))
    lo = Vector([min(v[i] for v in los) for i in range(3)])
    hi = Vector([max(v[i] for v in his) for i in range(3)])
    return (lo + hi) / 2, max((hi - lo).length / 2, 0.5)


def frame(objects=None, camera=None, margin=0.08):
    """Aim the camera at `objects` (default: every visible object) and move it along its line of sight until
    all of them fit in the picture with a margin — staying on the side it's on. Makes a camera if there's none.
    Returns the camera."""
    scene = _scene()
    cam = find(camera) if camera else scene.camera
    if cam is None:
        cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
        bpy.context.collection.objects.link(cam)
        cam.location = (7.4, -6.5, 5.3)
        scene.camera = cam
    targets = [find(n) for n in objects] if objects else _visible_meshes()
    if not targets:
        return cam
    center, radius = _scene_bounds(targets)
    points = [c for t in targets for c in _corners(box(t))]
    away = cam.matrix_world.translation - center
    if away.length < 1e-3:
        away = Vector((1, -1, 0.7))
    away.normalize()
    def fits(distance):
        cam.location = center + away * distance
        look_at(cam, center)
        return all(_in_view(cam, p, margin) for p in points)
    near, far = 0.0, max(radius * 4, 2.0)
    while not fits(far):
        far *= 2
        if far > 1e5:
            break
    for _ in range(30):
        mid = (near + far) / 2
        if fits(mid):
            far = mid
        else:
            near = mid
    fits(far)
    if cam.data.clip_end < far + radius * 2:
        cam.data.clip_end = far + radius * 4
    return cam


# ---------- undo ----------

_MOD_SETTINGS = {'BEVEL': ("width", "segments", "limit_method"), 'SUBSURF': ("levels", "render_levels")}


def snapshot(o):
    """What restore() needs to put `o` back exactly: transform, name, materials and their shader values,
    modifiers, shading, and light/camera settings. JSON-safe."""
    o = find(o)
    snap = {"name": o.name, "matrix": [list(r) for r in o.matrix_basis], "rotation_mode": o.rotation_mode,
            "hidden": [o.hide_get(), o.hide_viewport, o.hide_render],
            "slots": [s.material.name if s.material else None for s in o.material_slots], "materials": {},
            "modifiers": [{"name": m.name, "type": m.type, **{k: getattr(m, k) for k in _MOD_SETTINGS.get(m.type, ())}}
                          for m in o.modifiers]}
    for name in filter(None, set(snap["slots"])):
        mat = bpy.data.materials[name]
        node = _principled(mat)
        snap["materials"][name] = {
            "diffuse": list(mat.diffuse_color), "metallic": mat.metallic, "roughness": mat.roughness,
            "render_method": getattr(mat, "surface_render_method", None), "blend": getattr(mat, "blend_method", None),
            "inputs": {k: (list(s.default_value) if hasattr(s.default_value, "__len__") else s.default_value)
                       for k in _INPUTS if node and (s := _socket(node, k)) is not None}}
    if o.type == 'MESH' and len(o.data.polygons) <= 100000:   # (a flag per face: kept off huge meshes)
        flags = [False] * len(o.data.polygons)
        o.data.polygons.foreach_get("use_smooth", flags)
        snap["smooth"] = flags
    if o.type == 'LIGHT':
        snap["energy"] = o.data.energy
    if o.type == 'CAMERA':
        snap["lens"], snap["clip_end"] = o.data.lens, o.data.clip_end
    return snap


def restore(snap, current_name=None):
    """Put an object back as snapshot() saw it (modifiers added since are removed, materials and their values
    reset, the old name given back)."""
    o = bpy.data.objects[current_name or snap["name"]]
    o.name = snap["name"]
    if "hidden" in snap:
        o.hide_set(snap["hidden"][0])
        o.hide_viewport, o.hide_render = snap["hidden"][1], snap["hidden"][2]
    o.rotation_mode = snap["rotation_mode"]
    o.matrix_basis = mathutils.Matrix(snap["matrix"])
    for name, saved in snap["materials"].items():
        mat = bpy.data.materials.get(name)
        if mat is None:
            continue
        mat.diffuse_color, mat.metallic, mat.roughness = saved["diffuse"], saved["metallic"], saved["roughness"]
        if saved["render_method"] is not None:
            mat.surface_render_method = saved["render_method"]
        if saved["blend"] is not None:
            mat.blend_method = saved["blend"]
        node = _principled(mat)
        for key, value in saved["inputs"].items():
            if node and _socket(node, key) is not None:
                _socket(node, key).default_value = value
    if o.data is not None and hasattr(o.data, "materials"):
        while len(o.material_slots) > len(snap["slots"]):
            o.data.materials.pop()
        for i, name in enumerate(snap["slots"]):
            mat = bpy.data.materials.get(name) if name else None
            if i < len(o.material_slots):
                o.material_slots[i].material = mat
            else:
                o.data.materials.append(mat)
    kept = {m["name"] for m in snap["modifiers"]}
    for m in list(o.modifiers):
        if m.name not in kept:
            o.modifiers.remove(m)
    for saved in snap["modifiers"]:
        m = o.modifiers.get(saved["name"])
        if m is None and saved["type"] in _MOD_SETTINGS:   # removed since: put it back (others can't be rebuilt)
            m = o.modifiers.new(saved["name"], saved["type"])
        for key in _MOD_SETTINGS.get(saved["type"], ()):
            if m is not None:
                setattr(m, key, saved[key])
    if "smooth" in snap and len(snap["smooth"]) == len(o.data.polygons):
        o.data.polygons.foreach_set("use_smooth", snap["smooth"])
        o.data.update()
    if "energy" in snap:
        o.data.energy = snap["energy"]
    if "lens" in snap:
        o.data.lens, o.data.clip_end = snap["lens"], snap["clip_end"]
    _sync()
    return o.name


# ---------- rendering ----------

def render(path, resolution_percent=None, samples=None):
    """Render the scene camera's view to `path` (a PNG) with the scene's own engine and settings. Returns facts
    about the picture that was really written: {"path", "width", "height", "seconds", "flat", "brightness"} —
    "flat" means one even color all over (an empty or black render), measured from the file's pixels."""
    scene = _scene()
    if scene.camera is None:
        raise ValueError("the scene has no camera to render from")
    old = (scene.render.filepath, scene.render.resolution_percentage, scene.render.image_settings.file_format)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        scene.render.filepath = path
        scene.render.image_settings.file_format = 'PNG'
        if resolution_percent:
            scene.render.resolution_percentage = int(resolution_percent)
        if samples and scene.render.engine == 'CYCLES':
            scene.cycles.samples = int(samples)
        started = time.time()
        bpy.ops.render.render(write_still=True)
        seconds = time.time() - started
    finally:
        scene.render.filepath, scene.render.resolution_percentage, scene.render.image_settings.file_format = old
    if not os.path.exists(path):
        raise RuntimeError("Blender finished rendering but no image file was written")
    image = bpy.data.images.load(path, check_existing=False)
    try:
        width, height = image.size
        import numpy
        pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
        image.pixels.foreach_get(pixels)
        rgb = pixels.reshape(-1, 4)[::7, :3]
        luminance = rgb @ numpy.array([0.2126, 0.7152, 0.0722], dtype=numpy.float32)
        flat = float(luminance.std()) < 0.004
        brightness = float(luminance.mean())
    finally:
        bpy.data.images.remove(image)
    return {"path": path, "width": width, "height": height, "seconds": round(seconds, 1), "flat": flat,
            "brightness": round(brightness, 3)}


# ---------- architecture: staged builds (blender_build.py plans them; these build, inspect and preview them) ----------
# Every part a build makes carries custom properties: jarvis_build (the build's name), jarvis_stage and jarvis_role
# (wall, glass, door, roof...). That is what lets one stage be re-run without duplicating anything (it first removes
# only its own parts) and what inspect_build() measures — the user's own objects are never touched or counted.

_PALETTES = {
    "modern": {"wall": dict(color=(0.86, 0.85, 0.82), roughness=0.85), "base": dict(color=(0.3, 0.29, 0.28), roughness=0.9),
               "roof": dict(color=(0.15, 0.15, 0.16), roughness=0.7), "accent": dict(color=(0.42, 0.26, 0.14), roughness=0.55),
               "slab": dict(color=(0.7, 0.69, 0.66), roughness=0.8)},
    "classic": {"wall": dict(color=(0.9, 0.82, 0.66), roughness=0.9), "base": dict(color=(0.42, 0.38, 0.33), roughness=0.9),
                "roof": dict(color=(0.55, 0.2, 0.1), roughness=0.75), "accent": dict(color=(0.35, 0.2, 0.1), roughness=0.6),
                "slab": dict(color=(0.75, 0.7, 0.62), roughness=0.85)},
}
_COMMON = {"glass": dict(color=(0.75, 0.88, 0.95), transmission=1.0, roughness=0.03, ior=1.45, metallic=0.0),
           "frame": dict(color=(0.05, 0.05, 0.055), metallic=0.6, roughness=0.35),
           "door": dict(color=(0.3, 0.17, 0.08), roughness=0.5), "ground": dict(color=(0.16, 0.32, 0.1), roughness=0.95),
           "paving": dict(color=(0.62, 0.6, 0.56), roughness=0.85), "water": dict(color=(0.1, 0.45, 0.62),
                                                                                 transmission=0.85, roughness=0.02),
           "foliage": dict(color=(0.1, 0.3, 0.08), roughness=0.9), "trunk": dict(color=(0.25, 0.15, 0.08), roughness=0.9),
           "metal": dict(color=(0.55, 0.56, 0.57), metallic=1.0, roughness=0.3),
           # the pool's own surfaces, so improving the pool never repaints the floors or the entrance path
           "coping": dict(color=(0.7, 0.69, 0.66), roughness=0.8), "pool_tile": dict(color=(0.7, 0.69, 0.66), roughness=0.8),
           "deck": dict(color=(0.62, 0.6, 0.56), roughness=0.85), "walkway": dict(color=(0.62, 0.6, 0.56), roughness=0.85),
           "edging": dict(color=(0.2, 0.2, 0.21), roughness=0.8), "cushion": dict(color=(0.92, 0.9, 0.85), roughness=0.85),
           "lamp_glow": dict(color=(1.0, 0.86, 0.62), emission=(1.0, 0.8, 0.55), emission_strength=4.0),
           "flowers": dict(color=(0.75, 0.2, 0.35), roughness=0.8), "soil": dict(color=(0.16, 0.1, 0.06), roughness=0.95)}
_STRUCTURAL = ("foundation", "slab", "wall", "interior_wall", "roof", "gable")


def _build_mat(plan, key):
    """The build's material for `key`, as its style has it — or as an edit changed it (plan["materials"]), so a stage
    re-run after "make the pool better" keeps the better pool."""
    palette = _PALETTES.get(plan.get("style"), _PALETTES["modern"])
    look = dict(palette.get(key) or _COMMON[key])
    look.update(plan.get("materials", {}).get(key, {}))
    return material(f"{plan['build']} {key}", **look)


def _build_root(plan):
    """The empty the build's parts hang from (so "move the villa" moves all of it), made once."""
    name = plan["build"]
    root = bpy.data.objects.get(name)
    if root is None or root.get("jarvis_build") != name:
        root = bpy.data.objects.new(name, None)
        bpy.context.collection.objects.link(root)
        root.location = (plan["origin"][0], plan["origin"][1], 0.0)
        root["jarvis_build"], root["jarvis_role"] = name, "root"
    root["jarvis_plan"] = json.dumps(plan)
    return root


def _part(plan, stage, role, o, mat_key=None, attach=True):
    root = _build_root(plan)
    o["jarvis_build"], o["jarvis_stage"], o["jarvis_role"] = plan["build"], stage, role
    if attach:
        o.parent = root
        # Plan coordinates are relative to where the root first stood: a moved build gets re-run stages in place.
        o.matrix_parent_inverse = mathutils.Matrix.Translation((plan["origin"][0], plan["origin"][1], 0.0)).inverted()
    if mat_key and o.type == 'MESH':
        o.data.materials.append(_build_mat(plan, mat_key))
        o["jarvis_mat"] = mat_key
        if plan.get("bevels", {}).get(mat_key):   # rounded edges an earlier "make it better" asked for
            bevel(o, plan["bevels"][mat_key], 2)
    return o


def _boxes_mesh(name, boxes):
    """One object from axis-aligned boxes [((x0, y0, z0), (x1, y1, z1)), ...] (plan coordinates), its origin at the
    centre of its bottom. None when every box is empty."""
    import bmesh
    boxes = [(a, b) for a, b in boxes if min(b[i] - a[i] for i in range(3)) > 1e-4]
    if not boxes:
        return None
    lo = [min(a[i] for a, _ in boxes) for i in range(3)]
    hi = [max(b[i] for _, b in boxes) for i in range(3)]
    origin = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]))
    bm = bmesh.new()
    for a, b in boxes:
        centre = Vector([(a[i] + b[i]) / 2 for i in range(3)]) - origin
        size = [b[i] - a[i] for i in range(3)]
        bmesh.ops.create_cube(bm, size=1.0, matrix=mathutils.Matrix.Translation(centre) @
                              mathutils.Matrix.Diagonal((size[0], size[1], size[2], 1.0)))
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    o = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(o)
    o.location = origin
    return o


def _poly_mesh(name, verts, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.validate()
    mesh.update()
    o = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(o)
    return o


def _clear_stage(build, stage):
    """Remove what an earlier run of this stage of this build made — nothing else."""
    gone = [o for o in bpy.data.objects if o.get("jarvis_build") == build and o.get("jarvis_stage") == stage]
    for o in gone:
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if data is not None and data.users == 0 and isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)
    return len(gone)


def _levels(plan, vol):
    """(floor slab bottom, wall bottom, wall top) per storey of a volume."""
    h, plinth, slab = plan["storey_height"], plan["plinth"], plan["slab"]
    return [(plinth + k * h, plinth + k * h + slab, plinth + (k + 1) * h) for k in range(vol["storeys"])]


def _wall_frame(vol, side, t):
    """For one side of a volume: (along-axis 0 or 1, wall start, wall end, offset base, (thickness from, to))."""
    (x0, y0), (w, d) = vol["min"], vol["size"]
    x1, y1 = x0 + w, y0 + d
    if side == "front":
        return 0, x0, x1, x0, (y0, y0 + t)
    if side == "back":
        return 0, x0, x1, x0, (y1 - t, y1)
    if side == "left":
        return 1, y0 + t, y1 - t, y0, (x0, x0 + t)
    return 1, y0 + t, y1 - t, y0, (x1 - t, x1)


def _box3(axis, u0, u1, across, z0, z1):
    a0, a1 = across
    return ((u0, a0, z0), (u1, a1, z1)) if axis == 0 else ((a0, u0, z0), (a1, u1, z1))


def _openings(plan, vol, side, storey):
    """This wall's openings as (kind, u0, u1, z bottom, z top) in plan coordinates, sorted along the wall."""
    axis, start, end, base, across = _wall_frame(vol, side, plan["wall"])
    floor = _levels(plan, vol)[storey][1]
    out = []
    for o in vol.get("openings", []):
        if o["side"] != side or o["storey"] != storey:
            continue
        u0 = max(start + 0.15, base + o["at"] - o["width"] / 2)
        u1 = min(end - 0.15, base + o["at"] + o["width"] / 2)
        if u1 - u0 > 0.2:
            out.append((o["kind"], u0, u1, floor + o.get("sill", 0.0), floor + o.get("sill", 0.0) + o["height"]))
    return sorted(out, key=lambda o: o[1])


def _inner_wall(plan, vol):
    """(x, doorway centre y, doorway width) of the inner wall that divides a volume into rooms, or None when the
    volume is too small for two rooms. Shared by the builder and inspect_build, so both mean the same doorway."""
    return tuple(vol["inner_wall"]) if vol.get("inner_wall") else None


def _stair_run(stairs):
    """(along-axis start, end) of a stair flight."""
    return stairs["start"], stairs["start"] + stairs["going"] * stairs["risers"]


def _stair_lane(stairs, k):
    """Where flight `k` runs across the stairwell: flights alternate between two lanes side by side, so one never
    stands on top of the one below it (you'd climb into its underside)."""
    a0, a1 = stairs["across"]
    shift = (k % 2) * (a1 - a0) * stairs.get("inward", 0)
    return a0 + shift, a1 + shift


def _stair_boxes(stairs, floor, rise, k=0):
    """Flight `k` as solid steps, from the floor at `floor` up `rise` metres."""
    a0, a1 = _stair_lane(stairs, k)
    step = rise / stairs["risers"]
    return [_box3(stairs["axis"], stairs["start"] + i * stairs["going"], stairs["start"] + (i + 1) * stairs["going"],
                  (a0, a1), floor, floor + (i + 1) * step) for i in range(stairs["risers"])]


def _doorways(plan):
    """Every doorway that should join two rooms: (label, point in front of it, direction through it), in plan
    coordinates at hip height on the ground storey — inner walls on every storey, and passages between volumes."""
    t, out = plan["wall"], []
    for vol in plan["volumes"]:
        levels = _levels(plan, vol)
        inner = _inner_wall(plan, vol)
        stairs = vol.get("stairs")
        for k, (_, floor, _) in enumerate(levels):
            if inner:
                cx, mid, _ = inner
                out.append((f"{vol['name']} inner doorway {k + 1}", (cx - 0.6, mid, floor + 1.2), (1, 0, 0)))
            if stairs and k + 1 < len(levels):   # up from three quarters of the way along the flight: the
                s0, s1 = _stair_run(stairs)       # stairwell above must be open, or the stairs lead into a ceiling
                u = s0 + 0.75 * (s1 - s0)
                a = sum(_stair_lane(stairs, k)) / 2
                z = floor + 0.8 * (levels[k + 1][1] - floor) + 0.05
                at = (u, a, z) if stairs["axis"] == 0 else (a, u, z)
                out.append((f"{vol['name']} stairs {k + 1}", at, (0, 0, 1)))
        for o in vol.get("openings", []):
            if o["kind"] != "passage":
                continue
            (x0, y0), (w, _) = vol["min"], vol["size"]
            floor = levels[o["storey"]][1]
            inside = x0 + w - t - 0.6 if o["side"] == "right" else x0 + t + 0.6
            out.append((f"{vol['name']} passage {o['side']}", (inside, y0 + o["at"], floor + 1.2),
                        (1 if o["side"] == "right" else -1, 0, 0)))
    return out


def arch_structure(plan):
    """Foundations, floor slabs and the outer walls (with real gaps for every window and door) of each volume, plus
    one inner wall per storey with a doorway, so the plan has rooms."""
    build, t = plan["build"], plan["wall"]
    _clear_stage(build, "structure")
    made = 0
    for vol in plan["volumes"]:
        (x0, y0), (w, d) = vol["min"], vol["size"]
        name = f"{build} {vol['name']}"
        found = _boxes_mesh(f"{name} foundation", [((x0, y0, 0.0), (x0 + w, y0 + d, plan["plinth"]))])
        _part(plan, "structure", "foundation", found, "base")
        made += 1
        stairs = vol.get("stairs")
        levels = _levels(plan, vol)
        for k, (slab_z, wall_z, top_z) in enumerate(levels):
            slab_boxes = [((x0, y0, slab_z), (x0 + w, y0 + d, wall_z))]
            if stairs and k > 0:   # the stairwell: the floor above a flight is open over it
                s0, s1 = _stair_run(stairs)
                a0, a1 = _stair_lane(stairs, k - 1)   # over the flight coming up from the storey below
                if stairs["axis"] == 0:
                    slab_boxes = [((x0, y0, slab_z), (s0, y0 + d, wall_z)), ((s1, y0, slab_z), (x0 + w, y0 + d, wall_z)),
                                  ((s0, y0, slab_z), (s1, a0, wall_z)), ((s0, a1, slab_z), (s1, y0 + d, wall_z))]
                else:
                    slab_boxes = [((x0, y0, slab_z), (x0 + w, s0, wall_z)), ((x0, s1, slab_z), (x0 + w, y0 + d, wall_z)),
                                  ((x0, s0, slab_z), (a0, s1, wall_z)), ((a1, s0, slab_z), (x0 + w, s1, wall_z))]
            slab = _boxes_mesh(f"{name} floor {k + 1}", slab_boxes)
            _part(plan, "structure", "slab", slab, "slab")
            made += 1
            if stairs and k + 1 < len(levels):   # a flight up to the next storey's floor
                flight = _boxes_mesh(f"{name} stairs {k + 1}",
                                     _stair_boxes(stairs, wall_z, levels[k + 1][1] - wall_z, k))
                _part(plan, "structure", "stairs", flight, "slab")
                made += 1
            for side in ("front", "back", "left", "right"):
                if side in vol.get("open_sides", []) and k < vol.get("open_storeys", 99):
                    continue   # shared with the volume next to it: one wall there, not two
                axis, start, end, _, across = _wall_frame(vol, side, t)
                boxes, cursor = [], start
                for _, u0, u1, zb, zt in _openings(plan, vol, side, k):
                    boxes.append(_box3(axis, cursor, u0, across, wall_z, top_z))
                    boxes.append(_box3(axis, u0, u1, across, wall_z, zb))
                    boxes.append(_box3(axis, u0, u1, across, min(zt, top_z), top_z))
                    cursor = u1
                boxes.append(_box3(axis, cursor, end, across, wall_z, top_z))
                wall = _boxes_mesh(f"{name} wall {side} {k + 1}", boxes)
                if wall:
                    # The cladding accent goes on one storey of one side: a whole facade of it reads as a box.
                    accent = vol.get("accent") == side and k == vol["storeys"] - 1 and vol["storeys"] > 1
                    _part(plan, "structure", "wall", wall, "accent" if accent else "wall")
                    made += 1
            inner_wall = _inner_wall(plan, vol)
            if inner_wall:   # rooms: one inner wall across the volume, with a doorway in the middle
                cx, mid, door = inner_wall
                inner = _boxes_mesh(f"{name} inner wall {k + 1}", [
                    ((cx - 0.06, y0 + t, wall_z), (cx + 0.06, mid - door / 2, top_z)),
                    ((cx - 0.06, mid + door / 2, wall_z), (cx + 0.06, y0 + d - t, top_z)),
                    ((cx - 0.06, mid - door / 2, wall_z + 2.15), (cx + 0.06, mid + door / 2, top_z))])
                _part(plan, "structure", "interior_wall", inner, "wall")
                made += 1
    _sync()
    return {"stage": "structure", "parts": made}


def arch_openings(plan):
    """Glass, frames and doors in every opening the walls left, and a canopy over the entrance."""
    build, t = plan["build"], plan["wall"]
    _clear_stage(build, "openings")
    made = 0
    for vol in plan["volumes"]:
        name = f"{build} {vol['name']}"
        for k in range(vol["storeys"]):
            for side in ("front", "back", "left", "right"):
                axis, _, _, _, (a0, a1) = _wall_frame(vol, side, t)
                mid = (a0 + a1) / 2
                for i, (kind, u0, u1, zb, zt) in enumerate(_openings(plan, vol, side, k)):
                    label = f"{name} {kind} {side} {k + 1}.{i + 1}"
                    f = 0.06
                    bars = [_box3(axis, u0, u0 + f, (a0, a1), zb, zt), _box3(axis, u1 - f, u1, (a0, a1), zb, zt),
                            _box3(axis, u0, u1, (a0, a1), zt - f, zt)]
                    if kind not in ("door", "garage", "passage"):   # nothing to trip over in a doorway
                        bars.append(_box3(axis, u0, u1, (a0, a1), zb, zb + f))
                    if kind in ("window", "glass_door") and u1 - u0 > 1.8:   # a mullion on wide glass
                        c = (u0 + u1) / 2
                        bars.append(_box3(axis, c - f / 2, c + f / 2, (a0, a1), zb, zt))
                    _part(plan, "openings", "frame", _boxes_mesh(f"{label} frame", bars), "frame")
                    inner = (u0 + f, u1 - f)
                    if kind in ("window", "glass_door"):
                        pane = _boxes_mesh(f"{label} glass", [_box3(axis, *inner, (mid - 0.015, mid + 0.015),
                                                                    zb + (f if kind == "window" else 0), zt - f)])
                        _part(plan, "openings", "glass", pane, "glass")
                    elif kind == "door":
                        leaf = _boxes_mesh(f"{label} leaf", [_box3(axis, *inner, (mid - 0.03, mid + 0.03), zb, zt - f)])
                        _part(plan, "openings", "door", leaf, "door")
                    elif kind == "garage":
                        leaf = _boxes_mesh(f"{label} panel", [_box3(axis, *inner, (mid - 0.03, mid + 0.03), zb, zt - f)])
                        _part(plan, "openings", "garage_door", leaf, "metal")
                    made += 2
    entrance = plan.get("entrance")
    if entrance and entrance.get("canopy", True):
        (u0, u1, zt, y_face) = entrance["span"][0], entrance["span"][1], entrance["top"], entrance["face_y"]
        canopy = _boxes_mesh(f"{build} entrance canopy", [((u0 - 0.6, y_face - 1.4, zt + 0.25),
                                                            (u1 + 0.6, y_face, zt + 0.42))])
        _part(plan, "openings", "canopy", canopy, "roof")
        made += 1
    _sync()
    return {"stage": "openings", "parts": made}


def arch_roof(plan):
    """A roof on every volume: flat with an overhang (modern), or gable/hip with gable walls closing the ends."""
    build = plan["build"]
    _clear_stage(build, "roof")
    made = 0
    for vol in plan["volumes"]:
        (x0, y0), (w, d) = vol["min"], vol["size"]
        top = _levels(plan, vol)[-1][2]
        name = f"{build} {vol['name']}"
        kind, o = vol.get("roof", "flat"), plan.get("overhang", 0.4)
        if kind == "flat":
            roof = _boxes_mesh(f"{name} roof", [((x0 - o, y0 - o, top), (x0 + w + o, y0 + d + o, top + 0.3))])
            _part(plan, "roof", "roof", roof, "roof")
            made += 1
            continue
        along_x = w >= d
        span = d if along_x else w
        rise = span / 2 * math.tan(math.radians(plan.get("pitch", 30)))
        ax0, ax1, bx0, bx1 = (x0 - o, x0 + w + o, y0 - o, y0 + d + o) if along_x else (y0 - o, y0 + d + o, x0 - o, x0 + w + o)
        inset = span / 2 + o if kind == "hip" else 0.0
        bmid = (bx0 + bx1) / 2
        def p(a, b, z):
            return (a, b, z) if along_x else (b, a, z)
        eave = top - o * math.tan(math.radians(plan.get("pitch", 30)))
        verts = [p(ax0, bx0, eave), p(ax1, bx0, eave), p(ax1, bx1, eave), p(ax0, bx1, eave),
                 p(ax0 + inset, bmid, top + rise), p(ax1 - inset, bmid, top + rise)]
        # A gable roof is just its two slopes (given thickness below): closed ends would hide the gable walls.
        faces = [(0, 1, 5, 4), (2, 3, 4, 5)] + ([(1, 2, 5), (3, 0, 4), (3, 2, 1, 0)] if kind == "hip" else [])
        if not along_x:
            faces = [tuple(reversed(f)) for f in faces]
        roof = _poly_mesh(f"{name} roof", verts, faces)
        if kind == "gable":
            shell = roof.modifiers.new("Thickness", 'SOLIDIFY')
            shell.thickness, shell.offset = 0.18, 1.0
        _part(plan, "roof", "roof", roof, "roof")
        made += 1
        if kind == "gable":   # close the triangles between the walls and the roof at both ends
            t = plan["wall"]
            for end, (a0, a1) in (("start", (ax0 + o, ax0 + o + t)), ("end", (ax1 - o - t, ax1 - o))):
                g = [p(a0, bx0 + o, top), p(a0, bx1 - o, top), p(a0, bmid, top + rise - 0.05),
                     p(a1, bx0 + o, top), p(a1, bx1 - o, top), p(a1, bmid, top + rise - 0.05)]
                gf = [(0, 1, 2), (5, 4, 3), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)]
                _part(plan, "roof", "gable", _poly_mesh(f"{name} gable {end}", g, gf), "wall")
                made += 1
    _sync()
    return {"stage": "roof", "parts": made}


def arch_site(plan):
    """The ground the build stands on, steps up to the entrance, and the paved path from the street to them."""
    build = plan["build"]
    _clear_stage(build, "site")
    (sx, sy), (sw, sd) = plan["site"]["min"], plan["site"]["size"]
    m = 40.0   # the lawn runs well past the site, so no camera angle shows its edge and the void behind it
    ground = _poly_mesh(f"{build} ground", [(sx - m, sy - m, 0), (sx + sw + m, sy - m, 0), (sx + sw + m, sy + sd + m, 0),
                                            (sx - m, sy + sd + m, 0)], [(0, 1, 2, 3)])
    _part(plan, "site", "ground", ground, "ground")
    made = 1
    entrance = plan.get("entrance")
    if entrance:
        u0, u1, face = entrance["span"][0] - 0.5, entrance["span"][1] + 0.5, entrance["face_y"]
        steps, n = [], 2
        rise = plan["plinth"] / n
        for i in range(n):   # the lower step reaches further out
            steps.append(((u0, face - 0.4 * (n - i), 0.0), (u1, face, rise * (i + 1))))
        _part(plan, "site", "steps", _boxes_mesh(f"{build} entrance steps", steps), "paving")
        start = face - 0.4 * n
        path = _boxes_mesh(f"{build} path", [(((u0 + u1) / 2 - 0.8, sy + 0.2, 0.0), ((u0 + u1) / 2 + 0.8, start, 0.04))])
        _part(plan, "site", "path", path, "paving")
        made += 2
        if entrance.get("planters"):   # what "make the house better" added
            made += _planters(plan)
    for drive in plan.get("driveways", []):
        (x0, x1), y_face = drive["span"], drive["face_y"]
        _part(plan, "site", "path", _boxes_mesh(f"{build} driveway", [((x0, sy + 0.2, 0.0), (x1, y_face, 0.04))]),
              "paving")
        made += 1
    _sync()
    return {"stage": "site", "parts": made}


def arch_extras(plan):
    """What was asked for around the building: a pool, a garden, a terrace, a balcony."""
    build = plan["build"]
    _clear_stage(build, "extras")
    made = 0
    extras = plan.get("extras", {})
    pool = extras.get("pool")
    if pool:
        (x0, y0), (w, d) = pool["min"], pool["size"]
        _part(plan, "extras", "pool_deck", _boxes_mesh(f"{build} pool deck", _deck_boxes(pool)), "deck")
        c, h = 0.3, POOL_TOP
        rim = [((x0 - c, y0 - c, 0.12), (x0 + w + c, y0, h)), ((x0 - c, y0 + d, 0.12), (x0 + w + c, y0 + d + c, h)),
               ((x0 - c, y0, 0.12), (x0, y0 + d, h)), ((x0 + w, y0, 0.12), (x0 + w + c, y0 + d, h))]
        _part(plan, "extras", "pool", _boxes_mesh(f"{build} pool", rim), "coping")
        # Its own role: the rim is a ring, so the rim's box always holds the basin — that isn't a clash.
        _part(plan, "extras", "pool_floor", _boxes_mesh(f"{build} pool basin", [((x0, y0, 0.12),
                                                                                (x0 + w, y0 + d, 0.2))]), "pool_tile")
        _part(plan, "extras", "water", _boxes_mesh(f"{build} pool water", [((x0, y0, 0.2), (x0 + w, y0 + d, h - 0.08))]),
              "water")
        made += 4
        for level in range(1, plan.get("quality", {}).get("pool", 0) + 1):   # what "make the pool better" added
            _pool_level(plan, level)
    terrace = extras.get("terrace")
    if terrace:
        (x0, y0), (w, d) = terrace["min"], terrace["size"]
        _part(plan, "extras", "terrace", _boxes_mesh(f"{build} terrace", [((x0, y0, 0.0), (x0 + w, y0 + d,
                                                                                            plan["plinth"]))]), "paving")
        made += 1
    balcony = extras.get("balcony")
    if balcony:
        (x0, x1), (y_face, depth), z = balcony["span"], (balcony["face_y"], balcony["depth"]), balcony["z"]
        y_out = y_face - depth if balcony.get("side", "front") == "front" else y_face + depth
        ya, yb = min(y_face, y_out), max(y_face, y_out)
        _part(plan, "extras", "balcony", _boxes_mesh(f"{build} balcony", [((x0, ya, z - 0.2), (x1, yb, z))]), "slab")
        rail_y = (y_out, y_out + 0.04) if y_out < y_face else (y_out - 0.04, y_out)
        rails = [((x0, rail_y[0], z), (x1, rail_y[1], z + 1.0)), ((x0, ya, z), (x0 + 0.04, yb, z + 1.0)),
                 ((x1 - 0.04, ya, z), (x1, yb, z + 1.0))]
        _part(plan, "extras", "railing", _boxes_mesh(f"{build} balcony railing", rails), "glass")
        made += 2
    garden = extras.get("garden")
    if garden:
        for i, (x, y, r) in enumerate(garden.get("trees", [])):
            trunk = _part(plan, "extras", "tree", add_cylinder(f"{build} tree {i + 1} trunk", 0.15 * r, 2.2 * r,
                                                                (x, y, 0.0)), "trunk")
            crown = _part(plan, "extras", "tree", add_sphere(f"{build} tree {i + 1} crown", 1.3 * r,
                                                              (x, y, 2.0 * r)), "foliage")
            made += 2
        for i, ((x0, y0), (x1, y1)) in enumerate(garden.get("hedges", [])):
            _part(plan, "extras", "hedge", _boxes_mesh(f"{build} hedge {i + 1}", [((x0, y0, 0.0), (x1, y1, 0.9))]),
                  "foliage")
            made += 1
        made += _garden_extras(plan, garden)
    _sync()
    return {"stage": "extras", "parts": made}


POOL_TOP = 0.55


def _planters(plan):
    """Planters with shrubs either side of the entrance steps."""
    build, entrance = plan["build"], plan["entrance"]
    u0, u1, face = entrance["span"][0] - 0.5, entrance["span"][1] + 0.5, entrance["face_y"]
    for o in [o for o in _scene().objects if o.get("jarvis_build") == build and o.get("jarvis_role") == "planter"]:
        bpy.data.objects.remove(o, do_unlink=True)
    for i, x in enumerate((u0 - 0.75, u1 + 0.75)):
        _part(plan, "site", "planter", _boxes_mesh(f"{build} planter {i + 1}", [
            ((x - 0.4, face - 1.0, 0.0), (x + 0.4, face - 0.2, 0.55))]), "base")
        _part(plan, "site", "planter", add_sphere(f"{build} planter {i + 1} shrub", 0.42, (x, face - 0.6, 0.45)),
              "foliage")
    return 4


def _deck_boxes(pool):
    """The deck around a pool (plan coordinates): 1.2 m all round, wider on one side once improved."""
    (x0, y0), (w, d) = pool["min"], pool["size"]
    extra = pool.get("deck_extra", 0.0)   # + widens the far (+y) side, - the near one
    return [((x0 - 1.2, y0 - 1.2 - max(0.0, -extra), 0.0), (x0 + w + 1.2, y0 + d + 1.2 + max(0.0, extra), 0.12))]


def _garden_extras(plan, garden):
    """Shrubs, flower beds and extra trees that "make the garden better" placed (positions are in the plan)."""
    build, made = plan["build"], 0
    for i, (x, y, r) in enumerate(garden.get("shrubs", [])):
        _part(plan, "extras", "shrub", add_sphere(f"{build} shrub {i + 1}", r, (x, y, 0.0)), "foliage")
        made += 1
    for i, ((x0, y0), (x1, y1)) in enumerate(garden.get("beds", [])):
        _part(plan, "extras", "flower_bed", _boxes_mesh(f"{build} flower bed {i + 1}",
                                                         [((x0, y0, 0.0), (x1, y1, 0.18))]), "soil")
        _part(plan, "extras", "flower_bed", _boxes_mesh(f"{build} flowers {i + 1}",
                                                         [((x0 + 0.1, y0 + 0.1, 0.18), (x1 - 0.1, y1 - 0.1, 0.32))]),
              "flowers")
        made += 2
    for i, (x, y, r) in enumerate(garden.get("more_trees", [])):
        _part(plan, "extras", "tree", add_cylinder(f"{build} tree {i + 101} trunk", 0.15 * r, 2.2 * r, (x, y, 0.0)),
              "trunk")
        _part(plan, "extras", "tree", add_sphere(f"{build} tree {i + 101} crown", 1.3 * r, (x, y, 2.0 * r)), "foliage")
        made += 2
    return made


# ---------- features and edits: working on what is already in the scene ----------
# "Move the pool", "add a path from the villa to the pool", "make the pool better" name *features*: the pool is its
# rim, water, basin, deck and steps together; the villa is all of its walls, floors, roof and openings. A build's
# parts say which feature they are through their jarvis_role (so scenes built before this existed work too); any
# other object is a feature of its own, with its children, called by its name. An edit of a build is also written
# into the build's plan (the root's jarvis_plan), so a stage re-run later rebuilds the edited version, never the
# original one. Every edit measures its result in the scene; none of them trusts that its code ran as meant.

_FEATURE_WORDS = {
    "house": ("house", "villa", "home", "building", "mansion", "cottage", "cabin", "bungalow", "main house", "walls"),
    "pool": ("pool", "swimming pool", "pool deck", "water"),
    "garden": ("garden", "trees", "tree", "hedges", "hedge", "plants", "landscaping", "yard", "greenery", "shrubs",
               "flowers"),
    "entrance": ("entrance", "entrance path", "front path", "front steps", "steps", "entry", "front door"),
    "driveway": ("driveway", "drive"),
    "terrace": ("terrace", "patio"),
    "balcony": ("balcony",),
    "ground": ("ground", "lawn", "grass"),
    "path": ("path", "walkway", "pathway", "footpath", "walk", "trail", "paving"),
    "sun": ("sun", "sunlight"),
    "camera": ("camera",),
    "light": ("light", "lamp"),
}
_NOT_SOLID = ("ground", "path", "entrance", "driveway", "sun", "camera", "light")
PATH_HEIGHT = 0.05   # just above the entrance path (0.04), so where they cross neither flickers through the other
ON_GROUND = 0.5      # a part starting below this stands on the ground (a wall above a plinth, a tree trunk)


def _feature_key(o):
    """Which feature of its build a part belongs to: "house", "pool", "garden", "path:house-pool"..."""
    if o.get("jarvis_feature"):
        return o["jarvis_feature"]
    role, name = o.get("jarvis_role"), o.name.lower()
    if role in ("pool", "pool_floor", "water", "pool_deck", "pool_steps", "lounger") or \
            (role == "terrace" and name.endswith(" pool deck")):
        return "pool"
    if role in ("tree", "hedge", "shrub", "flower_bed"):
        return "garden"
    if role in ("terrace", "balcony", "ground", "sun", "camera"):
        return role
    if role == "railing":
        return "balcony"
    if role in ("steps", "planter") or (role == "path" and name.endswith(" path")):
        return "entrance"
    if role == "path":
        return "driveway" if "driveway" in name else "path"
    return "house"


def _plan_of(build):
    root = bpy.data.objects.get(build) if build else None
    if root is None or not root.get("jarvis_plan"):
        return None, None
    return root, json.loads(root["jarvis_plan"])


def _save_plan(root, plan):
    root["jarvis_plan"] = json.dumps(plan)


def _flat(lo, hi):
    return (lo[0], lo[1], hi[0], hi[1])


def _clash2(a, b, tol=0.0):
    """Whether two (x0, y0, x1, y1) rectangles overlap by more than `tol` (a negative tol: come closer than that)."""
    return a[0] < b[2] - tol and a[2] > b[0] + tol and a[1] < b[3] - tol and a[3] > b[1] + tol


def _gap2(a, b):
    dx = max(0.0, b[0] - a[2], a[0] - b[2])
    dy = max(0.0, b[1] - a[3], a[1] - b[3])
    return math.hypot(dx, dy)


def features():
    """Every feature in the scene, oldest first: {"id", "kind", "name", "build", "objects", "lo", "hi", "connects",
    "uids"}. lo/hi are the world corners of its meshes (or of its objects' places, for a light or a camera); uids are
    Blender's own ids of its objects, which change only when an object is made anew."""
    _sync()
    found, order = {}, []
    for o in _scene().objects:
        build = o.get("jarvis_build")
        if build and o.get("jarvis_role") == "root":
            continue
        if build:
            key = _feature_key(o)
            fid, kind = f"{build}/{key}", key.split(":")[0]
        elif o.get("jarvis_feature"):   # a path Jarvis laid between two of the user's own objects, with its edging
            fid, kind = o["jarvis_feature"], o["jarvis_feature"].split(":")[0]
        else:
            top = o
            while top.parent is not None and not top.parent.get("jarvis_build"):
                top = top.parent
            fid = top.name
            kind = {'CAMERA': "camera", 'LIGHT': "light"}.get(top.type, "object")
        if fid not in found:
            found[fid] = {"id": fid, "kind": kind, "build": build, "objects": []}
            order.append(fid)
        found[fid]["objects"].append(o.name)
    out = []
    for fid in order:
        f = found[fid]
        objs = [bpy.data.objects[n] for n in f["objects"]]
        meshes = [o for o in objs if o.type == 'MESH']
        if meshes:
            boxes = [box(o) for o in meshes]
            lo = [min(b[0][i] for b in boxes) for i in range(3)]
            hi = [max(b[1][i] for b in boxes) for i in range(3)]
        else:
            points = [o.matrix_world.translation for o in objs]
            lo = [min(p[i] for p in points) for i in range(3)]
            hi = [max(p[i] for p in points) for i in range(3)]
        f["lo"], f["hi"] = [round(v, 3) for v in lo], [round(v, 3) for v in hi]
        meta = next((o for o in objs if o.get("jarvis_connects")), None)
        f["connects"] = json.loads(meta["jarvis_connects"]) if meta else None
        f["uids"] = {o.name: getattr(o, "session_uid", 0) for o in objs}
        f["name"] = _feature_name(f)
        out.append(f)
    return out


def _feature_name(f):
    if f["build"] is None:
        if f["kind"] == "path" and f["connects"]:
            return f"path between the {f['connects'][0]} and the {f['connects'][1]}"
        return f["id"]
    key = f["id"].split("/", 1)[1]
    if f["kind"] == "house":
        return f["build"].lower() if f["build"].split()[0].lower() in _FEATURE_WORDS["house"] else f"{f['build']} building"
    if f["kind"] == "path" and f["connects"]:
        a, b = (_end_name(e, f["build"]) for e in f["connects"])
        return f"path between the {a} and the {b}"
    return key


def _end_name(end, build):
    """A path end ("house", "pool", or another feature's id) as the user calls it."""
    if end == "house" and build:
        return build.lower().split()[0]
    return end.split("/", 1)[-1]


def _words(f):
    if f["build"] is None:
        name = f["id"].lower()
        base = re.sub(r"[._ ]\d+$", "", name)
        return (name, base) + (_FEATURE_WORDS[f["kind"]] if f["kind"] in ("camera", "light") else ())
    words = _FEATURE_WORDS.get(f["kind"], ())
    if f["kind"] == "house":
        words = words + (f["build"].lower(),)
    return words


def feature(query, exclude=None):
    """The feature `query` names — "the pool", "villa", "the path to the pool", an id like "Villa/pool", or an
    object's name — or None. On a tie the newer feature wins (the newest build, the newest path)."""
    fs = features()
    if isinstance(query, dict):
        query = query["id"]
    if not query:
        return None
    for f in fs:
        if query == f["id"] and f["id"] != exclude:
            return f
    if "/" in query:
        return None   # an id ("Villa/path:house-pool") means exactly that feature, never a look-alike
    q = " ".join(re.sub(r"[^a-z0-9 ]", " ", query.lower()).split())
    q = re.sub(r"^(?:the|my|this|that|a|an|our)\s+", "", q)
    best, best_score = None, 0.0
    for f in fs:
        if f["id"] == exclude:
            continue
        score = 0.0
        for w in _words(f):
            if q == w:
                score = max(score, 3 + len(w) / 100)
            elif re.search(rf"\b{re.escape(w)}\b", q):
                score = max(score, 2 + len(w) / 100)
        if f["kind"] == "entrance" and re.search(r"\bpath\b", q):
            score = max(score, 1.5)   # "the path" is the entrance path only while no other path is there
        if f["kind"] == "path" and score and f["connects"]:
            for end in f["connects"]:
                kind = end.split("/", 1)[-1].split(":")[0]
                if re.search(rf"\b{re.escape(_end_name(end, f['build']))}\b", q) or \
                        any(re.search(rf"\b{w}\b", q) for w in _FEATURE_WORDS.get(kind, ())):
                    score += 0.5
        if any(n.lower() == q for n in f["objects"]):
            score = max(score, 4.0)
        if score and score >= best_score:
            best, best_score = f, score
    return best


def _need(query, exclude=None):
    f = feature(query, exclude)
    if f is None:
        names = ", ".join(sorted({x["name"] for x in features() if x["kind"] not in ("ground",)}))[:300]
        raise ValueError(f"there's nothing in the scene I can match to {query!r} (it has: {names or 'nothing'})")
    return f


def _center2(f):
    return Vector(((f["lo"][0] + f["hi"][0]) / 2, (f["lo"][1] + f["hi"][1]) / 2))


def _main_building(exclude=None, fs=None):
    return next((f for f in reversed(fs or features()) if f["kind"] == "house" and f["id"] != exclude), None)


def _ground_rects(f, solid_only=True):
    """The xy rectangles of a feature's parts that stand on the ground (overhead parts — a roof's eave, a tree's
    crown — and flat ones a path may cross are left out)."""
    base = f["lo"][2]
    out = []
    for n in f["objects"]:
        o = bpy.data.objects.get(n)
        if o is None or o.type != 'MESH' or not o.visible_get():
            continue
        lo, hi = box(o)
        if lo.z > base + ON_GROUND or (solid_only and hi.z < base + 0.06):
            continue
        out.append((n, _flat(lo, hi)))
    return out


def _solid_rects(exclude_ids=(), fs=None):
    """(feature id, object, rectangle) of everything standing on the ground that a path or a moved feature must keep
    clear of."""
    out = []
    for f in fs or features():
        if f["kind"] in _NOT_SOLID or f["id"] in exclude_ids:
            continue
        out.extend((f["id"], n, r) for n, r in _ground_rects(f))
    return out


def _clashes(rects, others, gap=0.0):
    return sorted({n for r in rects for (_, n, o) in others if _clash2(r, o, -gap)})


# ----- paths between features -----

def _door_anchors(f, width):
    """Where a path can leave a building: just past whatever stands outside each ground-floor door (the entrance
    steps, a terrace, the foundation), as (point, outward direction, door)."""
    objs = [bpy.data.objects[n] for n in f["objects"]]
    base = f["lo"][2]
    near = []
    for o in _scene().objects:
        if o.get("jarvis_build") == f["build"] and o.type == 'MESH' and o.get("jarvis_role") not in ("ground", "path"):
            lo, hi = box(o)
            if lo.z < base + ON_GROUND and hi.z > base + 0.02:
                near.append(_flat(lo, hi))
    center = _center2(f)
    out = []
    for door in objs:
        role = door.get("jarvis_role")
        if door.type != 'MESH' or not (role == "door" or (role == "glass" and "glass_door" in door.name)):
            continue
        lo, hi = box(door)
        if lo.z - base > 1.5:
            continue   # an upper floor's balcony door
        c = (lo + hi) / 2
        axis = 0 if hi.x - lo.x < hi.y - lo.y else 1   # a door is thin across its wall
        lat = 1 - axis
        sign = 1 if c[axis] >= center[axis] else -1
        reach, moved = c[axis], True
        while moved:   # walk out through everything that touches the way out within the path's width
            moved = False
            for r in near:
                rlo, rhi = (r[0], r[1]), (r[2], r[3])
                if rhi[lat] < c[lat] - width / 2 or rlo[lat] > c[lat] + width / 2:
                    continue
                inner, outer = (rlo[axis], rhi[axis]) if sign > 0 else (rhi[axis], rlo[axis])
                if (inner - reach) * sign <= 0.05 and (outer - reach) * sign > 1e-4:
                    reach, moved = outer, True
        p = Vector((c.x, c.y))
        p[axis] = reach + sign * 0.02
        n = Vector((0.0, 0.0))
        n[axis] = sign
        out.append((p, n, door.name))
    return out


def _edge_anchor(f, toward, width):
    """The middle of the side that faces `toward` of the feature's part nearest to it (a garden is its trees and
    hedges, not the whole plot they stand on), as (point, outward direction, None)."""
    parts = [r for _, r in _ground_rects(f, solid_only=False)] or [_flat(f["lo"], f["hi"])]
    x0, y0, x1, y1 = min(parts, key=lambda r: _gap2(r, (toward.x, toward.y, toward.x, toward.y)))
    if f["kind"] in ("pool", "terrace", "object"):   # one thing: its whole outline
        x0, y0, x1, y1 = f["lo"][0], f["lo"][1], f["hi"][0], f["hi"][1]
    c = Vector(((x0 + x1) / 2, (y0 + y1) / 2))
    d = toward - c
    def along(v, a, b):
        return (a + b) / 2 if b - a < width + 0.2 else min(max(v, a + width / 2 + 0.1), b - width / 2 - 0.1)
    if abs(d.x) / max(x1 - x0, 1e-3) >= abs(d.y) / max(y1 - y0, 1e-3):
        n = Vector((1.0 if d.x > 0 else -1.0, 0.0))
        p = Vector((x1 + 0.0 if d.x > 0 else x0, along(toward.y, y0, y1)))
    else:
        n = Vector((0.0, 1.0 if d.y > 0 else -1.0))
        p = Vector((along(toward.x, x0, x1), y1 if d.y > 0 else y0))
    return p, n, None


def _anchors(f, toward, width):
    if f["kind"] == "house":
        doors = _door_anchors(f, width)
        if doors:
            return doors
    return [_edge_anchor(f, toward, width)]


def _segment_rects(points, width):
    """Axis-aligned strips along a path's centre line; inner corners overlap so the path has no gaps."""
    rects, h = [], width / 2
    last = len(points) - 2
    for i, (p, q) in enumerate(zip(points, points[1:])):
        e0 = 0.0 if i == 0 else h
        e1 = 0.0 if i == last else h
        if abs(p.x - q.x) > abs(p.y - q.y):
            a, b = (p.x, q.x) if p.x < q.x else (q.x, p.x)
            ea, eb = (e0, e1) if p.x < q.x else (e1, e0)
            rects.append((a - ea, p.y - h, b + eb, p.y + h))
        else:
            a, b = (p.y, q.y) if p.y < q.y else (q.y, p.y)
            ea, eb = (e0, e1) if p.y < q.y else (e1, e0)
            rects.append((p.x - h, a - ea, p.x + h, b + eb))
    return rects


def _simplify(points):
    out = []
    for p in points:
        if out and (p - out[-1]).length < 1e-3:
            continue
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            if abs((b - a).normalized().dot((p - b).normalized())) > 0.999:
                out[-1] = p   # straight on: one segment
                continue
        out.append(p)
    return out


def _route(fa, fb, width, obstacles):
    """The shortest path from a door (or side) of `fa` to a side of `fb` that runs through nothing: out from the
    first, at most two turns, straight in to the second. (points, door) or None."""
    best = None
    for pa, na, door in _anchors(fa, _center2(fb), width):
        for pb, nb, _ in _anchors(fb, pa, width):
            for s in (1.0, 2.5, 4.0, 6.0, 9.0, 13.0):
                for t in (0.0, 1.0, 3.0, 6.0):
                    a1, b1 = pa + na * s, pb + nb * t
                    for corner in (Vector((b1.x, a1.y)), Vector((a1.x, b1.y))):
                        points = _simplify([pa.copy(), a1, corner, b1, pb.copy()])
                        if len(points) < 2:
                            continue
                        segments = [(q - p) for p, q in zip(points, points[1:])]
                        if any(u.normalized().dot(v.normalized()) < -0.5 for u, v in zip(segments, segments[1:])):
                            continue   # doubles back on itself
                        if any(min(abs(v.x), abs(v.y)) > 1e-3 for v in segments):
                            continue
                        rects = _segment_rects(points, width)
                        if any(_clash2(r, o, 0.03) for r in rects for (_, _, o) in obstacles):
                            continue
                        score = sum(v.length for v in segments) + 2.0 * (len(points) - 2)
                        if best is None or score < best[0]:
                            best = (score, points, door)
    return (best[1], best[2]) if best else None


def _path_ends(f):
    """(a, b) features a path joins, from what it stored."""
    ends = []
    for end in f["connects"]:
        fid = f"{f['build']}/{end}" if f["build"] and "/" not in end else end
        ends.append(feature(fid))
    return ends


def _replace_object(name, made):
    """Put `made`'s mesh and place into the existing object called `name` (so it stays the same object — an edit,
    not a new one), or keep `made` under that name when there is none. Returns the object kept."""
    old = bpy.data.objects.get(name)
    if old is None or old.type != 'MESH':
        made.name = name
        return made
    made.matrix_world = made.matrix_basis.copy()   # a new object's matrix_world is stale until the next update
    _swap_mesh(old, made)
    return old


def _swap_mesh(old, made):
    """Give `old` the shape and place of the new, unparented object `made` (which goes): the same object, with its
    name, parent, properties and materials (materials live on the mesh, so they move across with it)."""
    mesh = old.data
    for m in mesh.materials:
        made.data.materials.append(m)
    old.data = made.data
    old.matrix_world = made.matrix_world.copy()
    bpy.data.objects.remove(made, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _lay_path(fa, fb, width=1.2, quality=0, build=None, plan=None, root=None):
    """Lay (or re-lay) the path between two features; returns (path object, door it starts at)."""
    if build:
        ka, kb = (f["id"].split("/", 1)[1] for f in (fa, fb))
    else:
        ka, kb = fa["id"], fb["id"]
    key = "path:" + "-".join(sorted([ka, kb]))
    obstacles = [o for o in _solid_rects() if not (o[0] == f"{build}/{key}" or o[0] == key)]
    backwards = fb["kind"] == "house" and fa["kind"] != "house"
    found = _route(fb, fa, width, obstacles) if backwards else _route(fa, fb, width, obstacles)
    if found and backwards:
        found = (list(reversed(found[0])), found[1])
    if found is None:
        in_way = sorted({n for (_, n, _) in obstacles if _gap2(_flat(fa["lo"], fa["hi"]), _flat(fb["lo"], fb["hi"])) > 0})
        raise ValueError(f"I couldn't find a way from the {fa['name']} to the {fb['name']} that doesn't go through "
                         f"something ({', '.join(in_way[:3]) or 'they overlap'})")
    points, door = found
    z0 = min(fa["lo"][2], fb["lo"][2])
    rects = _segment_rects(points, width)
    name = f"{build} path {_end_name(ka, build)} to {_end_name(kb, build)}" if build else f"Path {ka} to {kb}"
    made = _boxes_mesh(name + " new", [((r[0], r[1], z0), (r[2], r[3], z0 + PATH_HEIGHT)) for r in rects])
    o = _replace_object(name, made)
    if not o.material_slots:
        o.data.materials.append(_build_mat(plan, "walkway") if plan else material("Path paving", **_COMMON["walkway"]))
    elif plan:
        o.material_slots[0].material = _build_mat(plan, "walkway")
    o["jarvis_feature"], o["jarvis_role"] = key, "path"
    o["jarvis_connects"] = json.dumps([ka, kb])
    o["jarvis_points"] = json.dumps([[round(p.x, 3), round(p.y, 3)] for p in points])
    o["jarvis_width"], o["jarvis_z"], o["jarvis_quality"] = width, z0, quality
    if build:
        o["jarvis_build"], o["jarvis_stage"] = build, "connections"
        if o.parent != root:
            world = o.matrix_basis.copy() if o.parent is None else o.matrix_world.copy()
            o.parent = root
            o.matrix_world = world
    _path_dressing(o, rects, z0, quality, plan, build, key, root)
    _sync()
    return o, door


def _path_dressing(path, rects, z0, quality, plan, build, key, root):
    """Edging along a path (quality 1) and low lamps beside it (quality 2) — what "make the path better" adds."""
    for o in [o for o in _scene().objects if o.get("jarvis_feature") == key and o is not path]:
        bpy.data.objects.remove(o, do_unlink=True)
    def mat(k):
        return _build_mat(plan, k) if plan else material(f"Path {k}", **_COMMON[k])
    def keep(o, role, k):
        o.data.materials.append(mat(k))
        o["jarvis_feature"], o["jarvis_role"] = key, role
        if build:
            o["jarvis_build"], o["jarvis_stage"] = build, "connections"
            world = o.matrix_basis.copy()   # new and unparented: its basis is where it is
            o.parent = root
            o.matrix_world = world
    points = [Vector(p) for p in json.loads(path["jarvis_points"])]
    width = path["jarvis_width"]
    if quality >= 1:
        rects = _segment_rects(points, width)
        strips = []
        last = len(points) - 2
        for i, (p, q) in enumerate(zip(points, points[1:])):
            along = 0 if abs(p.x - q.x) > abs(p.y - q.y) else 1
            lo, hi = sorted((p[along], q[along]))
            # past a turn the outer strip carries on round the corner; at the path's two ends it stops there
            grow_lo = 0.0 if (i == 0 and p[along] == lo) or (i == last and q[along] == lo) else width / 2 + 0.1
            grow_hi = 0.0 if (i == 0 and p[along] == hi) or (i == last and q[along] == hi) else width / 2 + 0.1
            for side in (-1, 1):
                at = p[1 - along] + side * (width / 2 + 0.05)
                pieces = [(lo - grow_lo, hi + grow_hi)]
                for r in rects:   # never across a walkway: each stretch is cut out of the strip
                    r_lo, r_hi = (r[0], r[2]) if along == 0 else (r[1], r[3])
                    c_lo, c_hi = (r[1], r[3]) if along == 0 else (r[0], r[2])
                    if not (c_lo < at + 0.05 - 1e-6 and c_hi > at - 0.05 + 1e-6):
                        continue
                    pieces = [part for a, b in pieces
                              for part in ((a, min(b, r_lo)), (max(a, r_hi), b)) if part[1] - part[0] > 1e-6]
                for a, b in pieces:
                    if b - a < 0.05:
                        continue
                    if along == 0:
                        strips.append(((a, at - 0.05, z0), (b, at + 0.05, z0 + 0.08)))
                    else:
                        strips.append(((at - 0.05, a, z0), (at + 0.05, b, z0 + 0.08)))
        keep(_boxes_mesh(f"{path.name} edging", strips), "path_edge", "edging")
    if quality >= 2:
        n, side = 0, 1
        for (p, q) in zip(points, points[1:]):
            seg = q - p
            k = 1
            while 3.5 * k < seg.length:
                at = p + seg.normalized() * (3.5 * k)
                off = Vector((-seg.y, seg.x)).normalized() * (width / 2 + 0.3) * side
                x, y = at.x + off.x, at.y + off.y
                n += 1
                keep(_boxes_mesh(f"{path.name} lamp {n}", [((x - 0.05, y - 0.05, z0), (x + 0.05, y + 0.05, z0 + 0.55))]),
                     "path_lamp", "edging")
                keep(_boxes_mesh(f"{path.name} lamp {n} light", [((x - 0.08, y - 0.08, z0 + 0.55),
                                                                  (x + 0.08, y + 0.08, z0 + 0.65))]), "path_lamp",
                     "lamp_glow")
                side, k = -side, k + 1


def connect(a=None, b=None, width=1.2):
    """A real path between two features ("house" and "pool", or any objects): from a door of a building (or the
    side of anything else) facing the other, around whatever stands in between, ending against the other's edge.
    With `a` left out it starts at the main building; with `b` left out it goes to the newest thing that has no path
    yet. Returns {"path", "feature", "between", "door", "length", "turns", "width"}."""
    fs = features()
    fa = _need(a) if a else _main_building(fs=fs)
    if fa is None:
        raise ValueError("there's no building in the scene to lay a path from — say where it should start")
    if b:
        fb = _need(b, exclude=fa["id"])
    else:
        joined = {e for f in fs if f["kind"] == "path" and f["connects"] for e in f["connects"]}
        candidates = [f for f in fs if f["id"] != fa["id"] and f["kind"] not in _NOT_SOLID + ("house",)]
        fb = next((f for f in reversed(candidates) if f["id"].split("/", 1)[-1] not in joined and f["id"] not in joined),
                  candidates[-1] if candidates else None)
        if fb is None:
            raise ValueError("there's nothing in the scene for a path to lead to — say where it should go")
    if fa["kind"] in _NOT_SOLID or fb["kind"] in _NOT_SOLID:
        raise ValueError(f"a path can't lead to the {fa['name'] if fa['kind'] in _NOT_SOLID else fb['name']}")
    build = fa["build"] if fa["build"] and fa["build"] == fb["build"] else None
    root, plan = _plan_of(build)
    if build and plan is None:
        build = None
    ends = sorted([f["id"].split("/", 1)[1] for f in (fa, fb)]) if build else None
    quality = 0
    if build:
        conns = plan.setdefault("connections", [])
        entry = next((c for c in conns if sorted(c["between"]) == ends), None)
        if entry is None:
            entry = {"between": [fa["id"].split("/", 1)[1], fb["id"].split("/", 1)[1]], "width": width, "quality": 0}
            conns.append(entry)
        entry["width"] = width
        quality = entry.get("quality", 0)
    existed = any(f["kind"] == "path" and f["connects"] and sorted(f["connects"]) == sorted(
        [x["id"].split("/", 1)[1] if build else x["id"] for x in (fa, fb)]) for f in fs)
    o, door = _lay_path(fa, fb, width, quality, build, plan, root)
    if build:
        _save_plan(root, plan)
    points = [Vector(p) for p in json.loads(o["jarvis_points"])]
    return {"path": o.name, "feature": f"{build}/{o['jarvis_feature']}" if build else o["jarvis_feature"],
            "between": [fa["name"], fb["name"]], "door": door, "width": width, "replaced": existed,
            "door_end": 0 if fa["kind"] == "house" else 1,
            "length": round(sum((q - p).length for p, q in zip(points, points[1:])), 2), "turns": len(points) - 2}


def arch_connections(plan):
    """The paths a plan asks for between its parts ("a path from the villa to the pool"), laid between the parts as
    they stand now."""
    build = plan["build"]
    _clear_stage(build, "connections")
    root = _build_root(plan)
    made = 0
    for c in plan.get("connections", []):
        fa, fb = feature(f"{build}/{c['between'][0]}"), feature(f"{build}/{c['between'][1]}")
        if fa is None or fb is None:
            continue   # what it led to isn't built (yet): inspect_build reports the path as missing
        _lay_path(fa, fb, c.get("width", 1.2), c.get("quality", 0), build, plan, root)
        made += 1
    _sync()
    return {"stage": "connections", "parts": made}


def check_path(target):
    """Whether a path really is there and joins what it is meant to, measured: a ray straight down every 0.4 m along
    its middle must land on the path itself (it exists, has no gap, nothing covers it); each end must touch its
    feature (for a building: the building, its steps or terrace); and no part of it may run through anything.
    {"ok", "problems", "path", "between", "length", "continuous", "reaches", "clear", "width"}"""
    f = _need(target)
    path = next((bpy.data.objects[n] for n in f["objects"] if bpy.data.objects[n].get("jarvis_points")), None)
    if path is None:
        raise ValueError(f"{f['name']} isn't a path I laid, so I can't tell what it should join")
    ends = _path_ends(f)
    problems = []
    if not path.visible_get() or path.hide_render:
        problems.append("it is hidden")
    if not any(s.material for s in path.material_slots):
        problems.append("it has no material")
    points = [Vector(p) for p in json.loads(path["jarvis_points"])]
    width, z0 = path["jarvis_width"], path["jarvis_z"]
    scene, depsgraph = _scene(), bpy.context.evaluated_depsgraph_get()
    samples = misses = 0
    covered = set()
    last = len(points) - 2
    for k, (p, q) in enumerate(zip(points, points[1:])):
        seg = q - p
        n = max(1, int(seg.length / 0.4))
        for i in range(n + 1):
            x = p + seg * (i / n)
            if (k == 0 and i == 0) or (k == last and i == n):   # the very ends sit on the path's edge
                x = x + seg.normalized() * (0.1 if i == 0 else -0.1)
            hit, _, _, _, obj, _ = scene.ray_cast(depsgraph, Vector((x.x, x.y, z0 + PATH_HEIGHT + 0.25)),
                                                  Vector((0, 0, -1)), distance=0.5)
            samples += 1
            if not hit or obj.name != path.name:
                misses += 1
                if hit:
                    covered.add(obj.name)
    if misses:
        problems.append(f"{misses} of {samples} points along it have no path under them" +
                        (f" (covered by {', '.join(sorted(covered)[:3])})" if covered else ""))
    rects = _segment_rects(points, width)
    reaches = []
    for end_rect, fe, label in ((rects[0], ends[0], "start"), (rects[-1], ends[1], "end")):
        if fe is None:
            problems.append(f"what its {label} should reach isn't in the scene any more")
            reaches.append(None)
            continue
        targets = [r for _, r in _ground_rects(fe, solid_only=False)]
        if fe["kind"] == "house" and fe["build"]:
            for kind in ("entrance", "terrace"):
                g = feature(f"{fe['build']}/{kind}")
                if g:
                    targets += [r for _, r in _ground_rects(g, solid_only=False)]
        gap = min((_gap2(end_rect, r) for r in targets), default=99.0)
        reaches.append(round(gap, 3))
        if gap > 0.15:
            problems.append(f"it stops {gap:.1f} m short of the {fe['name']}")
    through = _clashes(rects, _solid_rects(exclude_ids=(f["id"],)), gap=-0.03)
    if through:
        problems.append("it runs through " + ", ".join(through[:3]))
    return {"ok": not problems, "problems": problems, "path": path.name, "between": [e["name"] if e else None
                                                                                      for e in ends],
            "length": round(sum((q - p).length for p, q in zip(points, points[1:])), 2), "continuous": not misses,
            "samples": samples, "reaches": reaches, "clear": not through, "width": width}


def _reroute(moved_ids, fs=None):
    """Re-lay every path that leads to something that just moved, so it still joins it. Returns their names."""
    names = []
    for f in fs or features():
        if f["kind"] != "path" or not f["connects"]:
            continue
        ends = [f"{f['build']}/{e}" if f["build"] and "/" not in e else e for e in f["connects"]]
        if not set(ends) & set(moved_ids):
            continue
        fa, fb = (feature(e) for e in ends)
        if fa is None or fb is None:
            continue
        path = next(bpy.data.objects[n] for n in f["objects"] if bpy.data.objects[n].get("jarvis_points"))
        root, plan = _plan_of(f["build"])
        _lay_path(fa, fb, path["jarvis_width"], path.get("jarvis_quality", 0), f["build"] if plan else None, plan, root)
        names.append(path.name)
    return names


# ----- moving, resizing, removing -----

def _movers(f):
    """What to move for a feature: a whole build moves by its root (its parts follow); otherwise the feature's
    top-level objects (children follow their parents)."""
    if f["kind"] == "house" and f["build"] and bpy.data.objects.get(f["build"]):
        return [bpy.data.objects[f["build"]]]
    objs = [bpy.data.objects[n] for n in f["objects"]]
    return [o for o in objs if o.parent not in objs]


def _shift(objs, delta):
    for o in objs:
        m = o.matrix_world.copy()
        m.translation += Vector((delta.x, delta.y, 0.0))
        o.matrix_world = m
    _sync()


def _own_ids(f, fs):
    return {g["id"] for g in fs if g["build"] == f["build"]} if (f["kind"] == "house" and f["build"]) else {f["id"]}


def _feature_rects(ids, fs):
    return [r for g in fs if g["id"] in ids and g["kind"] not in _NOT_SOLID for _, r in _ground_rects(g)]


_WAYS = {"left": (-1, 0), "right": (1, 0), "forward": (0, 1), "forwards": (0, 1), "back": (0, -1),
         "backward": (0, -1), "backwards": (0, -1), "behind": (0, 1), "front": (0, -1)}


def _direction(f, how, ref):
    if how in _WAYS:
        return Vector(_WAYS[how])
    away = (_center2(f) - _center2(ref)) if ref else Vector((1.0, 0.0))
    if away.length < 1e-3:
        away = Vector((1.0, 0.0))
    if how == "side":
        return Vector((1.0 if away.x >= 0 else -1.0, 0.0))
    if how in ("closer", "toward", "towards", "nearer"):
        return -away.normalized()
    return away.normalized()   # "away", "further"


def _plan_shift(f, delta):
    """Write a move into the build's plan, so re-running the stage that made it puts it where it now is."""
    root, plan = _plan_of(f["build"])
    if plan is None or f["kind"] == "house":
        return
    key = f["id"].split("/", 1)[1]
    extra = plan.get("extras", {}).get(key)
    if extra and "min" in extra:
        extra["min"] = [round(extra["min"][0] + delta.x, 3), round(extra["min"][1] + delta.y, 3)]
    elif extra and key == "garden":
        extra["trees"] = [[x + delta.x, y + delta.y, r] for x, y, r in extra.get("trees", [])]
        extra["hedges"] = [[[a[0] + delta.x, a[1] + delta.y], [b[0] + delta.x, b[1] + delta.y]]
                           for a, b in extra.get("hedges", [])]
        for k in ("shrubs", "more_trees"):
            extra[k] = [[x + delta.x, y + delta.y, r] for x, y, r in extra.get(k, [])]
        extra["beds"] = [[[a[0] + delta.x, a[1] + delta.y], [b[0] + delta.x, b[1] + delta.y]]
                         for a, b in extra.get("beds", [])]
    _save_plan(root, plan)


def move_feature(target, how="side", distance=None, ref=None):
    """Move a whole feature ("the pool") `how`: left/right/forward/back/behind/front, "side" (sideways, away from
    the building), "away"/"further" or "closer" (from/to `ref`, the main building by default), `distance` metres
    (default 4, or 2 closer). It never ends up inside anything: it carries on the same way until it is clear (or
    stops short, moving closer), and if no clear place is found it stays where it was. Paths that lead to it are
    re-laid so they still join it. Returns {"feature", "name", "moved", "distance", "pushed", "rerouted", "gap",
    "ref"}."""
    fs = features()
    f = _need(target)
    if f["kind"] in ("ground", "sun", "camera"):
        raise ValueError(f"the {f['name']} isn't something I can move like that")
    ref_f = _need(ref, exclude=f["id"]) if ref else _main_building(exclude=f["id"], fs=fs)
    v = _direction(f, how, ref_f)
    movers = _movers(f)
    own = _own_ids(f, fs)
    others = _solid_rects(exclude_ids=own, fs=fs)
    start = {o.name: o.matrix_world.copy() for o in movers}
    closer = how in ("closer", "toward", "towards", "nearer")
    d = float(distance) if distance else (2.0 if closer else 4.0)
    _shift(movers, v * d)
    pushed = 0.0
    def hits():
        return _clashes(_feature_rects(own, features()), others, gap=0.3)
    # Asked for an exact distance, it may go only a little further to stand clear; told just "to the side", further.
    limit = 3.0 if distance else 12.0
    while hits() and pushed < limit:
        step = v * (-0.5 if closer else 1.0)
        _shift(movers, step)
        pushed += 0.5 if closer else 1.0
        if closer and pushed >= d:
            break
    in_way = hits()
    delta = movers[0].matrix_world.translation - start[movers[0].name].translation
    if in_way or delta.length < 0.01:
        for o in movers:
            o.matrix_world = start[o.name]
        _sync()
        if in_way:
            raise ValueError(f"there's no clear place for the {f['name']} that way ({', '.join(in_way[:3])} is in "
                             "the way), so I left it where it was")
        raise ValueError(f"the {f['name']} is already as close as it can be without touching the {ref_f['name']}")
    _plan_shift(f, delta)
    rerouted = _reroute(own)
    after = feature(f["id"])
    gap = None
    if ref_f is not None and f["kind"] != "house":
        gap = round(min((_gap2(a, b) for a in _feature_rects({f["id"]}, features())
                         for b in _feature_rects({ref_f["id"]}, features())), default=0.0), 2)
    return {"feature": f["id"], "name": f["name"], "moved": [round(delta.x, 2), round(delta.y, 2)],
            "distance": round(delta.length, 2), "pushed": round(pushed, 2), "rerouted": rerouted, "gap": gap,
            "ref": ref_f["name"] if ref_f else None, "center": [round(v, 2) for v in _center2(after)]}


def clashes_of(target):
    """What a feature (a whole build, for a building) stands in or touches, measured on the ground plan."""
    fs = features()
    f = _need(target)
    own = _own_ids(f, fs)
    return _clashes(_feature_rects(own, fs), _solid_rects(exclude_ids=own, fs=fs), gap=0.0)


def shift_feature(target, dx, dy):
    """Move a feature by exactly (dx, dy) metres, no checks (what "undo" uses to put a moved feature back)."""
    fs = features()
    f = _need(target)
    _shift(_movers(f), Vector((dx, dy)))
    _plan_shift(f, Vector((dx, dy)))
    return {"feature": f["id"], "rerouted": _reroute(_own_ids(f, fs))}


def resize_feature(target, factor, axes="xy"):
    """Scale a feature about its middle (`axes` among x, y, z). A path is re-laid wider or narrower instead, so it
    still joins both ends; a whole building can't be stretched (its doors and stairs would be too). If the bigger
    feature would stand in something, it moves away from the main building until clear."""
    fs = features()
    f = _need(target)
    if f["kind"] == "house":
        raise ValueError("stretching a whole building would stretch its doors and stairs too; ask for a larger "
                         "building instead (\"create a large villa\")")
    if f["kind"] == "path":
        path = next(bpy.data.objects[n] for n in f["objects"] if bpy.data.objects[n].get("jarvis_points"))
        old = path["jarvis_width"]
        width = round(min(4.0, max(0.6, old * factor)), 2)
        fa, fb = _path_ends(f)
        root, plan = _plan_of(f["build"])
        if plan:
            for c in plan.get("connections", []):
                if sorted(c["between"]) == sorted(json.loads(path["jarvis_connects"])):
                    c["width"] = width
            _save_plan(root, plan)
        _lay_path(fa, fb, width, path.get("jarvis_quality", 0), f["build"] if plan else None, plan, root)
        return {"feature": f["id"], "name": f["name"], "before": [old], "after": [width], "moved": None}
    c = Vector(((f["lo"][0] + f["hi"][0]) / 2, (f["lo"][1] + f["hi"][1]) / 2, f["lo"][2]))
    s = mathutils.Matrix.Diagonal([factor if a in axes else 1.0 for a in "xyz"] + [1.0])
    pivot = mathutils.Matrix.Translation(c) @ s.to_4x4() @ mathutils.Matrix.Translation(-c)
    before = [round(f["hi"][i] - f["lo"][i], 2) for i in range(3)]
    for o in _movers(f):
        o.matrix_world = pivot @ o.matrix_world
    _sync()
    root, plan = _plan_of(f["build"])
    key = f["id"].split("/", 1)[-1]
    extra = plan.get("extras", {}).get(key) if plan else None
    if extra and "min" in extra and "size" in extra:   # about the same middle, in plan coordinates
        (x0, y0), (w, d) = extra["min"], extra["size"]
        fx, fy = (factor if "x" in axes else 1.0), (factor if "y" in axes else 1.0)
        extra["size"] = [round(w * fx, 3), round(d * fy, 3)]
        extra["min"] = [round(x0 + w / 2 - w * fx / 2, 3), round(y0 + d / 2 - d * fy / 2, 3)]
        _save_plan(root, plan)
    moved = None
    others = _solid_rects(exclude_ids={f["id"]}, fs=fs)
    if _clashes(_feature_rects({f["id"]}, features()), others, gap=0.3):
        moved = move_feature(f["id"], "away", 0.5)
    rerouted = _reroute({f["id"]})
    after = feature(f["id"])
    return {"feature": f["id"], "name": f["name"], "before": before,
            "after": [round(after["hi"][i] - after["lo"][i], 2) for i in range(3)],
            "moved": moved, "rerouted": rerouted}


def remove_feature(target):
    """Take a feature out of the scene — a whole building with everything it has, or one part of it (the pool, a
    path) — plus any path that led only to it. The objects are kept out of sight (a fake user) so undo can bring
    them back; the build's plan forgets it, so a stage re-run doesn't either. Returns {"removed", "homes",
    "plan_before", "still"}."""
    fs = features()
    f = _need(target)
    root, plan = _plan_of(f["build"])
    if f["kind"] == "house" and f["build"]:
        names = [o.name for o in bpy.data.objects if o.get("jarvis_build") == f["build"]]
    else:
        names = list(f["objects"])
        mine = f["id"].split("/", 1)[-1] if f["build"] else f["id"]
        for g in fs:   # a path to nowhere goes with it
            if g["kind"] == "path" and g["connects"] and mine in g["connects"] and g["id"] != f["id"]:
                names += g["objects"]
    before = root["jarvis_plan"] if root is not None else None
    homes = {}
    for n in names:
        o = bpy.data.objects.get(n)
        if o is None:
            continue
        homes[n] = [c.name for c in o.users_collection]
        for c in list(o.users_collection):
            c.objects.unlink(o)
        o.use_fake_user = True
    if plan is not None and f["kind"] != "house":
        key = f["id"].split("/", 1)[1]
        plan.get("extras", {}).pop(key, None)
        plan["connections"] = [c for c in plan.get("connections", [])
                               if key not in c["between"] and "path:" + "-".join(sorted(c["between"])) != key]
        _save_plan(root, plan)
    _sync()
    return {"removed": names, "homes": homes, "plan_before": before, "build": f["build"],
            "still": [n for n in names if n in _scene().objects]}


def bring_back(homes, build=None, plan=None):
    """Undo remove_feature: the kept objects back where they were, and the plan as it was."""
    for n, collections in homes.items():
        o = bpy.data.objects.get(n)
        if o is None:
            continue
        for c in collections:
            home = bpy.data.collections.get(c) or (_scene().collection if c == _scene().collection.name else None)
            (home or _scene().collection).objects.link(o)
        if not o.users_collection:
            _scene().collection.objects.link(o)
        o.use_fake_user = False
    if build and plan and bpy.data.objects.get(build):
        bpy.data.objects[build]["jarvis_plan"] = plan
    _sync()
    return [n for n in homes if n in _scene().objects]


def clear_scene():
    """Delete every object in the scene. Returns {"removed", "left"} as measured afterwards."""
    scene = _scene()
    names = [o.name for o in scene.objects]
    for o in list(scene.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    _sync()
    return {"removed": len(names), "left": [o.name for o in scene.objects]}


def paint_feature(target, **values):
    """Change the look of a feature's main surfaces (a building's walls, a pool's water...) — see material()."""
    f = _need(target)
    main = {"house": ("wall",), "pool": ("water",), "path": ("path",), "garden": ("tree", "hedge", "shrub"),
            "terrace": ("terrace",), "entrance": ("path", "steps")}.get(f["kind"])
    objs = [bpy.data.objects[n] for n in f["objects"] if bpy.data.objects[n].type == 'MESH']
    picked = [o for o in objs if not main or o.get("jarvis_role") in main] or objs
    if f["kind"] == "garden":
        picked = [o for o in picked if "trunk" not in o.name]
    root, plan = _plan_of(f["build"])
    keys = sorted({o.get("jarvis_mat") or (o.active_material.name[len(f["build"]) + 1:] if o.active_material and
                                           f["build"] and o.active_material.name.startswith(f["build"] + " ") else "")
                   for o in picked} - {""}) if plan else []
    if plan and keys:   # the build's shared material: every part of that kind changes, and stays so on a re-run
        for k in keys:
            plan.setdefault("materials", {}).setdefault(k, {}).update(
                {key: (list(v) if isinstance(v, tuple) else v) for key, v in values.items()})
            _build_mat(plan, k)
        _save_plan(root, plan)
    else:
        for o in picked:
            paint(o, **values)
    return {"feature": f["id"], "name": f["name"], "objects": [o.name for o in picked],
            "values": {o.name: shader_values(o) for o in picked[:3]}}


# ----- making things better -----
# Each feature kind has levels of improvement, kept in the build's plan ("quality"), so asking again goes further
# instead of repeating itself, and a re-run of the stage rebuilds the improved version. Nothing is regenerated: the
# existing objects get the new materials and shapes, and new parts are added beside them.

_POOL_LOOK = {"water": dict(color=(0.03, 0.3, 0.42), transmission=0.9, roughness=0.02, ior=1.33),
              "pool_tile": dict(color=(0.5, 0.76, 0.8), roughness=0.25),
              "coping": dict(color=(0.84, 0.82, 0.77), roughness=0.55),
              "deck": dict(color=(0.42, 0.27, 0.15), roughness=0.6)}
_HOUSE_LOOK = {"wall": dict(color=(0.93, 0.91, 0.87), roughness=0.75), "base": dict(color=(0.28, 0.27, 0.26), roughness=0.85),
               "roof": dict(color=(0.13, 0.13, 0.14), roughness=0.6), "accent": dict(color=(0.47, 0.3, 0.16), roughness=0.5),
               "frame": dict(color=(0.12, 0.1, 0.08), metallic=0.7, roughness=0.35),
               "door": dict(color=(0.22, 0.13, 0.07), roughness=0.45)}


def _restyle(plan, looks):
    mats = plan.setdefault("materials", {})
    for key, look in looks.items():
        mats[key] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in look.items()}
        _build_mat(plan, key)


def _parts_with(build, roles):
    return [o for o in _scene().objects if o.get("jarvis_build") == build and o.get("jarvis_role") in roles]


def _pool_level(plan, level):
    """One level of a better pool, on the pool that's there. Returns what changed, in words."""
    build, pool = plan["build"], plan["extras"]["pool"]
    (x0, y0), (w, d) = pool["min"], pool["size"]
    root = _build_root(plan)
    if level == 1:
        _restyle(plan, _POOL_LOOK)
        for o in _parts_with(build, ("pool",)):
            bevel(o, 0.03, 3)
        for o in _parts_with(build, ("pool_deck",)) + [o for o in _parts_with(build, ("terrace",))
                                                       if o.name.endswith(" pool deck")]:
            bevel(o, 0.02, 2)
        n, sw = 3, min(1.8, d * 0.5)
        cy = y0 + d / 2
        top = POOL_TOP - 0.08
        steps = [((x0, cy - sw / 2, 0.2), (x0 + 0.35 * (n - i), cy + sw / 2, 0.2 + (top - 0.2) * (i + 1) / n - 0.06))
                 for i in range(n)]
        old = bpy.data.objects.get(f"{build} pool steps")
        if old is not None:
            bpy.data.objects.remove(old, do_unlink=True)
        _part(plan, "extras", "pool_steps", _boxes_mesh(f"{build} pool steps", steps), "coping")
        return ["clearer, deeper-blue water", "light aqua tiles in the basin", "pale stone coping with rounded edges",
                "a warm wooden deck", "steps down into the water"]
    if level == 2:
        if "deck_extra" not in pool:   # widen the deck on the side away from the house, where there's room
            house = [v for v in plan["volumes"]]
            hy = sum(v["min"][1] + v["size"][1] / 2 for v in house) / len(house)
            pool["deck_extra"] = 2.6 if (y0 + d / 2) >= hy else -2.6
        extra = pool["deck_extra"]
        deck = next(iter(_parts_with(build, ("pool_deck",))), None) or next(
            (o for o in _parts_with(build, ("terrace",)) if o.name.endswith(" pool deck")), None)
        made = _boxes_mesh(f"{build} pool deck new", _deck_boxes(pool))
        world_shift = root.matrix_world.translation - Vector((plan["origin"][0], plan["origin"][1], 0.0))
        made.matrix_world = mathutils.Matrix.Translation(world_shift) @ made.matrix_basis
        if deck is not None:
            _swap_mesh(deck, made)
        else:
            made.name = f"{build} pool deck"
            _part(plan, "extras", "pool_deck", made, "deck")
        for o in [o for o in _parts_with(build, ("lounger",))]:
            bpy.data.objects.remove(o, do_unlink=True)
        far = (y0 + d + 1.2 + 0.3) if extra > 0 else (y0 - 1.2 - abs(extra) + 0.3)
        for i, x in enumerate((x0 + w * 0.3, x0 + w * 0.62)):
            seat = [((x - 0.35, far, 0.12), (x + 0.35, far + 1.9, 0.42))]
            back = [((x - 0.35, far + (1.45 if extra > 0 else 0.0), 0.42),
                     (x + 0.35, far + (1.9 if extra > 0 else 0.45), 0.85))]
            _part(plan, "extras", "lounger", _boxes_mesh(f"{build} sun lounger {i + 1}", seat + back), "cushion")
        return ["a wider deck on the side away from the house", "two sun loungers on it"]
    return []


def _improve_pool(f):
    root, plan = _plan_of(f["build"])
    if plan is None or "pool" not in plan.get("extras", {}):
        return _improve_objects(f)
    quality = plan.setdefault("quality", {})
    level = quality.get("pool", 0) + 1
    changes = _pool_level(plan, level)
    if changes:
        quality["pool"] = level
    _save_plan(root, plan)
    return changes, quality.get("pool", 0)


def _improve_path(f):
    path = next((bpy.data.objects[n] for n in f["objects"] if bpy.data.objects[n].get("jarvis_points")), None)
    if path is None:
        return _improve_objects(f)
    level = path.get("jarvis_quality", 0) + 1
    if level > 2:
        return [], level - 1
    root, plan = _plan_of(f["build"])
    if plan:
        for c in plan.get("connections", []):
            if sorted(c["between"]) == sorted(json.loads(path["jarvis_connects"])):
                c["quality"] = level
        if level == 1:
            _restyle(plan, {"walkway": dict(color=(0.78, 0.74, 0.66), roughness=0.7)})
        _save_plan(root, plan)
    elif level == 1:
        material("Path walkway", color=(0.78, 0.74, 0.66), roughness=0.7)
        path.material_slots[0].material = bpy.data.materials["Path walkway"]
    fa, fb = _path_ends(f)
    _lay_path(fa, fb, path["jarvis_width"], level, f["build"] if plan else None, plan, root)
    return (["warm stone paving", "dark edging along both sides"] if level == 1 else
            ["low lamps along it, on alternate sides"]), level


def _improve_house(f):
    root, plan = _plan_of(f["build"])
    if plan is None:
        return _improve_objects(f)
    quality = plan.setdefault("quality", {})
    level = quality.get("house", 0) + 1
    changes = []
    if level == 1:
        _restyle(plan, _HOUSE_LOOK)
        bevels = plan.setdefault("bevels", {})
        bevels.update({"wall": 0.012, "base": 0.02, "roof": 0.02, "accent": 0.012})
        for o in _scene().objects:
            key = o.get("jarvis_mat") or (o.active_material.name[len(f["build"]) + 1:] if o.active_material and
                                           o.active_material.name.startswith(f["build"] + " ") else "")
            if o.get("jarvis_build") == f["build"] and o.type == 'MESH' and key in bevels:
                bevel(o, bevels[key], 2)
        changes = ["warm white plaster walls", "a dark stone plinth", "warm wood cladding on the accent wall",
                   "dark bronze window frames", "softly rounded edges on the walls and roof"]
    elif level == 2 and plan.get("entrance"):
        plan["entrance"]["planters"] = True
        _planters(plan)
        changes = ["planters with shrubs either side of the entrance steps"]
    if changes:
        quality["house"] = level
    _save_plan(root, plan)
    return changes, quality.get("house", 0)


def _free_spots(candidates, radius, fs):
    """Of `candidates` [(x, y)], those where something `radius` wide stands clear of everything (paths too)."""
    taken = [r for (_, _, r) in _solid_rects(fs=fs)]
    for f in fs:
        if f["kind"] in ("path", "entrance", "driveway"):
            taken += [r for _, r in _ground_rects(f, solid_only=False)]
    out = []
    for x, y in candidates:
        r = (x - radius, y - radius, x + radius, y + radius)
        if not any(_clash2(r, t, -0.2) for t in taken):
            out.append((x, y))
            taken.append(r)
    return out


def _improve_garden(f):
    root, plan = _plan_of(f["build"])
    if plan is None or "garden" not in plan.get("extras", {}):
        return _improve_objects(f)
    garden = plan["extras"]["garden"]
    quality = plan.setdefault("quality", {})
    level = quality.get("garden", 0) + 1
    shift = root.matrix_world.translation - Vector((plan["origin"][0], plan["origin"][1], 0.0))
    fs = features()
    changes = []
    if level == 1:
        face = min(v["min"][1] for v in plan["volumes"])
        lo_x = min(v["min"][0] for v in plan["volumes"])
        hi_x = max(v["min"][0] + v["size"][0] for v in plan["volumes"])
        spots = [(x + shift.x, face - 1.1 + shift.y) for x in [lo_x + 1.0 + 2.2 * i for i in range(int((hi_x - lo_x) / 2.2))]]
        shrubs = _free_spots(spots, 0.6, fs)
        garden["shrubs"] = [[x - shift.x, y - shift.y, 0.55] for x, y in shrubs]
        beds = _free_spots([(lo_x - 2.0 + shift.x, face - 3.5 + shift.y), (hi_x + 2.0 + shift.x, face - 3.5 + shift.y)],
                           1.3, fs)
        garden["beds"] = [[[x - 1.2 - shift.x, y - 0.6 - shift.y], [x + 1.2 - shift.x, y + 0.6 - shift.y]] for x, y in beds]
        changes = ([f"{len(shrubs)} shrub{'s' if len(shrubs) != 1 else ''} along the front of the house"]
                   if shrubs else []) + ([f"{len(beds)} flower bed{'s' if len(beds) != 1 else ''}"] if beds else [])
    elif level == 2:
        sx, sy = plan["site"]["min"]
        sw, sd = plan["site"]["size"]
        ring = [(sx + 1.5 + i * 4.0, sy + sd - 1.5) for i in range(int(sw / 4))] + \
               [(sx + 1.5, sy + 3 + j * 4.0) for j in range(int(sd / 4))] + \
               [(sx + sw - 1.5, sy + 3 + j * 4.0) for j in range(int(sd / 4))]
        trees = _free_spots([(x + shift.x, y + shift.y) for x, y in ring], 1.4, fs)[:8]
        garden["more_trees"] = [[x - shift.x, y - shift.y, 0.8 + 0.1 * (i % 3)] for i, (x, y) in enumerate(trees)]
        if trees:
            changes = [f"{len(trees)} more trees around the edge of the plot"]
    if changes:
        quality["garden"] = level
        _save_plan(root, plan)
        for o in [o for o in _scene().objects if o.get("jarvis_build") == f["build"] and (
                o.get("jarvis_role") in ("shrub", "flower_bed") or
                int((re.search(r" tree (\d+) (?:trunk|crown)$", o.name) or [0, 0])[1]) > 100)]:
            bpy.data.objects.remove(o, do_unlink=True)
        _garden_extras(plan, garden)
    _save_plan(root, plan)
    return changes, quality.get("garden", 0)


def _improve_objects(f):
    """Any object, or one this doesn't know as a part of a building: rounded edges on hard-edged shapes, smooth
    shading on curved ones, a real material where there's none, and a light clear coat the second time."""
    objs = [bpy.data.objects[n] for n in f["objects"] if bpy.data.objects[n].type == 'MESH']
    if not objs:
        return [], 0
    level = max(o.get("jarvis_quality", 0) for o in objs) + 1
    changes = []
    for o in objs:
        if level == 1:
            if not any(s.material for s in o.material_slots):
                paint(o, color=(0.7, 0.7, 0.72), roughness=0.45)
                changes.append(f"a material on {o.name}")
            faces = len(o.data.polygons)
            if faces <= 24 and not any(m.type == 'BEVEL' for m in o.modifiers):
                bevel(o)
                changes.append(f"rounded edges on {o.name}")
            elif faces > 24 and not all(p.use_smooth for p in o.data.polygons):
                smooth(o)
                changes.append(f"smooth shading on {o.name}")
        elif level == 2 and o.active_material is not None:
            paint(o, coat=0.25, roughness=max(0.2, (shader_values(o).get("roughness") or 0.5) - 0.15))
            changes.append(f"a subtle clear coat on {o.name}")
        if level <= 2:
            o["jarvis_quality"] = level
    return changes, level if changes else level - 1


def improve_feature(target):
    """Make a feature better, the next step up from where it is: the pool, a path, the building, the garden (each
    has its own levels), or any other object. Returns {"feature", "name", "level", "changes", "kept"} — "changes"
    empty when there is nothing more this knows how to add."""
    f = _need(target)
    before = set(f["objects"])
    how = {"pool": _improve_pool, "path": _improve_path, "house": _improve_house, "garden": _improve_garden}
    changes, level = ((how.get(f["kind"]) if f["build"] else None) or _improve_objects)(f)
    _sync()
    after = feature(f["id"])
    return {"feature": f["id"], "name": f["name"], "level": level, "changes": changes,
            "kept": sorted(before & set(after["objects"] if after else [])), "lost": sorted(before - set(after["objects"]
                                                                                                    if after else []))}


def scene_manifest(limit=30):
    """The scene as features, for the AI and for "what's in the scene": one line each."""
    fs = [f for f in features() if f["kind"] not in ("sun", "camera")]
    house = _main_building(fs=fs)
    lines = []
    for f in fs[:limit]:
        size = [round(f["hi"][i] - f["lo"][i], 1) for i in range(3)]
        c = _center2(f)
        line = f"- {f['name']} [{f['id']}] {size[0]} x {size[1]} m, {size[2]} m tall, centre ({c.x:.1f}, {c.y:.1f})"
        if house and f is not house and f["kind"] not in ("ground",):
            gap = min((_gap2(a, b) for a in [r for _, r in _ground_rects(f, False)] or [_flat(f["lo"], f["hi"])]
                       for b in [r for _, r in _ground_rects(house)] or [_flat(house["lo"], house["hi"])]), default=0)
            line += f", {gap:.1f} m from the {house['name']}"
        lines.append(line)
    return "Features (what the user calls things):\n" + "\n".join(lines) if lines else "The scene is empty."


def _eevee_engine():
    items = {i.identifier for i in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}
    return next((e for e in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE") if e in items), "CYCLES")


def _building_parts(build):
    return [o for o in _scene().objects if o.get("jarvis_build") == build and o.type == 'MESH'
            and o.get("jarvis_role") not in ("ground", "path", "tree", "hedge", "path_edge", "path_lamp")]


def arch_lighting(plan):
    """A sun from the front left, a sky, a camera of its own looking at the entrance side three-quarters on, and
    render settings that suit an exterior."""
    build = plan["build"]
    _clear_stage(build, "lighting")
    scene = _scene()
    _sync()
    parts = _building_parts(build)
    center, radius = _scene_bounds(parts)
    sun_plan = plan.get("sun") or {}
    sun_data = bpy.data.lights.new(f"{build} sun", 'SUN')
    sun_data.energy = sun_plan.get("energy", 3.5)
    sun_data.angle = math.radians(2.0)
    if sun_plan.get("elevation", 50) < 30:   # low, warm late-afternoon light
        sun_data.color = (1.0, 0.82, 0.62)
    sun = bpy.data.objects.new(f"{build} sun", sun_data)
    scene.collection.objects.link(sun)
    # A sun shines along its -Z: tilted (90 - elevation) degrees from straight down, from the front left.
    sun.rotation_euler = (math.radians(90 - sun_plan.get("elevation", 50)), 0.0, math.radians(-35))
    _part(plan, "lighting", "sun", sun, attach=False)
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None)
    if bg is not None:
        bg.inputs['Color'].default_value = (0.55, 0.7, 0.92, 1.0)
        # A dimmer sky than the sun: at 0.9 the sky's fill washed out every shadow and the facade read flat.
        bg.inputs['Strength'].default_value = 0.45
    world.color = (0.55, 0.7, 0.92)
    cam = bpy.data.objects.new(f"{build} camera", bpy.data.cameras.new(f"{build} camera"))
    scene.collection.objects.link(cam)
    cam.data.lens = 32
    cam.location = center + Vector((-0.7, -1.0, 0.38)).normalized() * radius * 3
    _part(plan, "lighting", "camera", cam, attach=False)
    _sync()
    scene.camera = cam
    frame([p.name for p in parts], camera=cam, margin=0.06)
    scene.render.engine = _eevee_engine()
    scene.render.resolution_x, scene.render.resolution_y = 1280, 800
    try:
        scene.view_settings.view_transform = 'AgX'
    except TypeError:
        scene.view_settings.view_transform = 'Filmic'
    looks = {i.identifier for i in scene.view_settings.bl_rna.properties['look'].enum_items}
    for look in ("AgX - Medium High Contrast", "Medium High Contrast"):   # the name differs between versions
        if look in looks:
            scene.view_settings.look = look
            break
    _sync()
    return {"stage": "lighting", "parts": 2}


def _part_box(o):
    lo, hi = box(o)
    return lo, hi


def inspect_build(build):
    """Measured facts about a build, for blender_build.py's acceptance checks: what parts it has (by role), whether
    it stands on the ground with nothing floating, whether every window and door sits in a wall's gap, whether each
    volume has a roof over it, materials, the sun, and what the camera sees."""
    _sync()
    scene = _scene()
    parts = [o for o in scene.objects if o.get("jarvis_build") == build]
    meshes = [o for o in parts if o.type == 'MESH']
    roles = {}
    for o in parts:
        roles[o.get("jarvis_role", "?")] = roles.get(o.get("jarvis_role", "?"), 0) + 1
    boxes = {o.name: _part_box(o) for o in meshes}
    ground = [o for o in meshes if o.get("jarvis_role") == "ground"]
    ground_z = max((boxes[g.name][1].z for g in ground), default=0.0)
    # Nothing floats: every part touches a chain of parts that reaches the ground.
    near = 0.03
    def touch(a, b):
        return all(a[0][i] <= b[1][i] + near and b[0][i] <= a[1][i] + near for i in range(3))
    supported = {n for n, (lo, hi) in boxes.items() if lo.z <= ground_z + near}
    frontier = list(supported)
    while frontier:
        n = frontier.pop()
        for m, b in boxes.items():
            if m not in supported and touch(boxes[n], b):
                supported.add(m)
                frontier.append(m)
    floating = sorted(set(boxes) - supported)
    building = [o for o in meshes if o.get("jarvis_role") not in ("ground", "path", "tree", "hedge", "path_edge",
                                                                  "path_lamp")]
    lowest = min((boxes[o.name][0].z for o in building), default=0.0)
    plan = {}
    root = bpy.data.objects.get(build)
    if root is not None and root.get("jarvis_plan"):
        plan = json.loads(root["jarvis_plan"])
    walls = [o for o in meshes if o.get("jarvis_role") == "wall"]
    in_walls = 0
    filled = [o for o in meshes if o.get("jarvis_role") in ("glass", "door", "garage_door")]
    for o in filled:
        lo, hi = boxes[o.name]
        c = (lo + hi) / 2
        if any(boxes[w.name][0].x - 0.05 <= c.x <= boxes[w.name][1].x + 0.05 and
               boxes[w.name][0].y - 0.05 <= c.y <= boxes[w.name][1].y + 0.05 and
               boxes[w.name][0].z - 0.05 <= c.z <= boxes[w.name][1].z + 0.05 for w in walls):
            in_walls += 1
    roofs = [o for o in meshes if o.get("jarvis_role") == "roof" and "canopy" not in o.name]
    volumes = []
    for vol in plan.get("volumes", []):
        (x0, y0), (w, d) = vol["min"], vol["size"]
        ox, oy = root.matrix_world.translation.x - plan["origin"][0], root.matrix_world.translation.y - plan["origin"][1]
        top = max((boxes[o.name][1].z for o in walls if o.name.startswith(f"{build} {vol['name']} ")), default=0.0)
        covered = any(boxes[r.name][0].x <= x0 + ox + 0.05 and boxes[r.name][1].x >= x0 + ox + w - 0.05 and
                      boxes[r.name][0].y <= y0 + oy + 0.05 and boxes[r.name][1].y >= y0 + oy + d - 0.05 and
                      boxes[r.name][0].z >= top - 1.0 for r in roofs if r.name.startswith(f"{build} {vol['name']} "))
        volumes.append({"name": vol["name"], "storeys": vol["storeys"], "footprint": [w, d], "wall_top": round(top, 2),
                        "roofed": covered})
    # Volumes that overlap one another, or a pool/tree standing inside the house: real intersections.
    solids = [(o.name, boxes[o.name]) for o in meshes if o.get("jarvis_role") in ("foundation", "pool", "tree")
              and not o.name.endswith("crown")]
    clashes = []
    for i, (a, ba) in enumerate(solids):
        for b, bb in solids[i + 1:]:
            ox_ = min(ba[1].x, bb[1].x) - max(ba[0].x, bb[0].x)
            oy_ = min(ba[1].y, bb[1].y) - max(ba[0].y, bb[0].y)
            if ox_ > 0.05 and oy_ > 0.05:
                clashes.append(f"{a} / {b}")
    no_material, unconnected = [], []
    for o in meshes:
        mats = [s.material for s in o.material_slots if s.material]
        if not mats:
            no_material.append(o.name)
        for m in mats:
            node = _principled(m)
            if node is None or not _connected(m, node):
                unconnected.append(o.name)
    glass = [o for o in meshes if o.get("jarvis_role") == "glass"]
    clear = all((shader_values(o).get("transmission") or 0) > 0.5 for o in glass) if glass else False
    lights = [o for o in scene.objects if o.type == 'LIGHT' and o.visible_get() and o.data.energy > 0]
    cam = scene.camera
    sees, coverage = False, 0.0
    if cam is not None and building:
        from bpy_extras.object_utils import world_to_camera_view
        lo = Vector([min(boxes[o.name][0][i] for o in building) for i in range(3)])
        hi = Vector([max(boxes[o.name][1][i] for o in building) for i in range(3)])
        pts = [world_to_camera_view(scene, cam, c) for c in _corners((lo, hi))]
        # Every corner of every part, as frame() fits them: the corners of the building's overall box can lie
        # where nothing is (a gable's ridge height at the front edge) and fall outside a picture that shows it all.
        sees = all(_in_view(cam, c, -0.001) for o in building for c in _corners(boxes[o.name]))
        xs = [min(1, max(0, p.x)) for p in pts]
        ys = [min(1, max(0, p.y)) for p in pts]
        coverage = round((max(xs) - min(xs)) * (max(ys) - min(ys)), 3)
    # Rooms that connect: a ray through each doorway (inner walls, passages between volumes) must meet nothing for
    # 1.2 m — measured on the real geometry, so a wall built across a doorway is caught.
    doorways = []
    if root is not None and plan:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        shift = root.matrix_world.translation - Vector((plan["origin"][0], plan["origin"][1], 0.0))
        for label, at, way in _doorways(plan):
            hit = scene.ray_cast(depsgraph, Vector(at) + shift, Vector(way), distance=1.2)[0]
            doorways.append({"doorway": label, "open": not hit})
    entrance = plan.get("entrance") or {}
    door_front = any(o.get("jarvis_role") == "door" and " door front " in o.name for o in meshes)
    path = next((boxes[o.name] for o in meshes if o.get("jarvis_role") == "path" and o.name.endswith(" path")), None)
    # The paths the plan asks for between its parts, each checked where it lies.
    connections = []
    for c in plan.get("connections", []):
        found = feature(f"{build}/path:" + "-".join(sorted(c["between"])))
        connections.append({**(check_path(found["id"]) if found else {"ok": False, "problems": ["it isn't there"]}),
                            "between": c["between"]})   # the plan's ends, not check_path's names for them
    steps = next((boxes[o.name] for o in meshes if o.get("jarvis_role") == "steps"), None)
    reaches = bool(path and steps and touch(path, steps))
    size = ([round(hi_ - lo_, 2) for lo_, hi_ in zip(
        [min(boxes[o.name][0][i] for o in building) for i in range(3)],
        [max(boxes[o.name][1][i] for o in building) for i in range(3)])] if building else [0, 0, 0])
    return {"build": build, "exists": bool(parts), "parts": len(parts), "roles": roles, "volumes": volumes,
            "size": size, "ground_gap": round(lowest - ground_z, 3) if ground else None, "floating": floating[:12],
            "openings_filled": len(filled), "openings_in_walls": in_walls, "door_on_front": door_front,
            "path_reaches_entrance": reaches, "has_entrance": bool(entrance), "clashes": clashes[:8],
            "doorways": doorways, "connections": connections,
            "no_material": no_material[:8], "unconnected": unconnected[:8], "glass_clear": clear,
            "lights": len(lights), "sun": any(o.data.type == 'SUN' for o in lights),
            "camera": cam.name if cam else None, "camera_sees": sees, "coverage": coverage,
            "engine": scene.render.engine}


def preview(path, width=960, height=600):
    """A quick Workbench picture from the scene camera (material colours, shadows) — seconds, where EEVEE's first
    render takes a minute — with facts about its pixels: {"path", "brightness", "contrast", "flat", "subject"}.
    "subject" is the share of the picture that isn't the empty sky colour: near 0 means the camera shows nothing."""
    scene = _scene()
    if scene.camera is None:
        raise ValueError("the scene has no camera to preview from")
    shading = scene.display.shading
    old = (scene.render.engine, scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage,
           shading.color_type, shading.light, shading.show_shadows, shading.show_cavity, scene.render.filepath)
    try:
        scene.render.engine = 'BLENDER_WORKBENCH'
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = width, height, 100
        shading.color_type, shading.light = 'MATERIAL', 'STUDIO'
        shading.show_shadows, shading.show_cavity = True, True
        scene.render.filepath = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        bpy.ops.render.render(write_still=True)
    finally:
        (scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
         scene.render.resolution_percentage, shading.color_type, shading.light, shading.show_shadows,
         shading.show_cavity, scene.render.filepath) = old
    return {"path": path, **picture_facts(path)}


def picture_facts(path):
    """Brightness, contrast and how much of the picture differs from its top corners' colour (the sky)."""
    import numpy
    image = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = image.size
        px = numpy.empty(w * h * 4, dtype=numpy.float32)
        image.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(image)
    rgb = px.reshape(h, w, 4)[:, :, :3]
    lum = rgb @ numpy.array([0.2126, 0.7152, 0.0722], dtype=numpy.float32)
    sky = numpy.concatenate([rgb[-3:, :3].reshape(-1, 3), rgb[-3:, -3:].reshape(-1, 3)]).mean(axis=0)   # top rows
    subject = float((numpy.abs(rgb - sky).max(axis=2) > 0.08).mean())
    return {"width": w, "height": h, "brightness": round(float(lum.mean()), 3), "contrast": round(float(lum.std()), 3),
            "flat": float(lum.std()) < 0.004, "subject": round(subject, 3)}


JARVIS_KIT_HELP = """Helpers already loaded (use them instead of raw bpy where they fit — they are tested):
find(name) -> object; report() -> scene facts text; check() -> [{object, problem, severity}] measured defects;
material(name, color=(r,g,b), metallic=, roughness=, transmission=, emission=(r,g,b), emission_strength=, alpha=);
paint(obj, color=..., metallic=..., ...) changes that object's own material; bevel(obj, width=None, segments=3);
subdivide(obj, levels=2); smooth(obj, on=True); set_size(obj, 'x'|'y'|'z'|'max', metres); size_of(obj);
BUILD with real metres, at = centre of the BOTTOM face (so z=0 stands on the floor; a part on top of a 0.7 m tall
leg goes at z=0.7): add_box(name, size=(w, d, h), at=(x, y, z), color=None); add_cylinder(name, radius, height, at);
add_cone(name, radius, height, at, top_radius=0); add_sphere(name, radius, at); group(name, [parts]) -> one thing;
add_ground() -> a floor under everything;
drop_to_floor(obj); place_on(obj, target); free_spot(obj); row_of_copies(obj, n); look_at(obj, target);
add_light('SUN'|'POINT'|'SPOT'|'AREA', energy=None, at=None); frame(objects=None) aims+fits the camera;
sees(cam, objects) -> bool;
render(path) -> {path, width, height, seconds, flat, brightness}. obj may be an object or its name.
EDIT what's there by feature ("pool", "villa", "path to the pool", an object's name): features() -> [{id, kind, name,
objects, lo, hi}]; feature(words); move_feature(target, 'left'|'right'|'forward'|'back'|'behind'|'front'|'side'|
'away'|'closer', distance=None, ref=None) keeps it clear of everything; connect(a, b, width=1.2) lays a real path
between two features; check_path(path) -> {ok, problems}; resize_feature(target, factor, axes='xy');
improve_feature(target); paint_feature(target, color=(r,g,b), ...); remove_feature(target); clashes_of(target)."""
