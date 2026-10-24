"""What Jarvis can put in a Blender scene, as data: object recipes, environment layouts and route finding.

  recipes     every object (a chair, a skyscraper, a flying car) is a list of simple shaped parts with materials and
              a few functional points (where to sit, the surface things stand on, which way is front). One generic
              builder in Blender (blender_world.instantiate) makes any of them, and the local AI describes an
              object that isn't here in the same format — so adding a kind of object is adding data.
  layouts     environments (a city, a forest, a room...) are generators that place recipes: pure arithmetic,
              tested without Blender, seeded so a rebuild ("add more buildings") keeps what was there.
  routes      a grid search through free space, used for anything that travels: a car along streets, a drone
              between towers, a person across a room.

No bpy: loaded into Blender as a module by blender_control.with_kit(), imported directly by the engine.
"""
import heapq
import math
import random

# ---------- materials (Principled values; "emission" glows) ----------
MATERIALS = {
    "wood": dict(color=(0.42, 0.26, 0.13), roughness=0.55), "dark_wood": dict(color=(0.2, 0.11, 0.06), roughness=0.5),
    "fabric": dict(color=(0.32, 0.36, 0.42), roughness=0.9), "leather": dict(color=(0.25, 0.13, 0.07), roughness=0.45),
    "metal": dict(color=(0.62, 0.63, 0.65), metallic=1.0, roughness=0.28),
    "dark_metal": dict(color=(0.08, 0.08, 0.09), metallic=0.9, roughness=0.35),
    "chrome": dict(color=(0.9, 0.9, 0.92), metallic=1.0, roughness=0.08),
    "glass": dict(color=(0.75, 0.86, 0.95), transmission=1.0, roughness=0.03),
    "dark_glass": dict(color=(0.05, 0.07, 0.1), metallic=0.4, roughness=0.06),
    "plastic": dict(color=(0.85, 0.85, 0.83), roughness=0.4), "black_plastic": dict(color=(0.03, 0.03, 0.03), roughness=0.4),
    "rubber": dict(color=(0.02, 0.02, 0.02), roughness=0.85), "paint": dict(color=(0.6, 0.06, 0.05), roughness=0.3),
    "concrete": dict(color=(0.5, 0.5, 0.48), roughness=0.9), "asphalt": dict(color=(0.07, 0.07, 0.075), roughness=0.85),
    "stone": dict(color=(0.45, 0.43, 0.4), roughness=0.85), "brick": dict(color=(0.48, 0.2, 0.12), roughness=0.85),
    "plaster": dict(color=(0.88, 0.86, 0.82), roughness=0.8), "tile": dict(color=(0.78, 0.78, 0.76), roughness=0.3),
    "grass": dict(color=(0.13, 0.3, 0.08), roughness=0.95), "sand": dict(color=(0.76, 0.66, 0.46), roughness=0.95),
    "soil": dict(color=(0.2, 0.13, 0.07), roughness=0.95), "snow": dict(color=(0.92, 0.94, 0.97), roughness=0.6),
    "water": dict(color=(0.04, 0.22, 0.32), transmission=0.6, roughness=0.04),
    "foliage": dict(color=(0.09, 0.27, 0.07), roughness=0.85), "pine": dict(color=(0.05, 0.18, 0.08), roughness=0.85),
    "bark": dict(color=(0.24, 0.15, 0.08), roughness=0.9), "rock": dict(color=(0.36, 0.34, 0.31), roughness=0.9),
    "light": dict(color=(1.0, 0.92, 0.75), emission=(1.0, 0.85, 0.6), emission_strength=8.0),
    "neon_cyan": dict(color=(0.1, 0.9, 1.0), emission=(0.1, 0.85, 1.0), emission_strength=12.0),
    "neon_pink": dict(color=(1.0, 0.1, 0.6), emission=(1.0, 0.1, 0.6), emission_strength=12.0),
    "screen": dict(color=(0.05, 0.1, 0.2), emission=(0.3, 0.55, 1.0), emission_strength=3.0),
    "food": dict(color=(0.82, 0.62, 0.35), roughness=0.7), "lettuce": dict(color=(0.3, 0.6, 0.15), roughness=0.7),
    "ceramic": dict(color=(0.93, 0.93, 0.9), roughness=0.2), "paper": dict(color=(0.9, 0.88, 0.8), roughness=0.9),
    "cardboard": dict(color=(0.55, 0.4, 0.25), roughness=0.9), "red": dict(color=(0.7, 0.05, 0.04), roughness=0.4),
    "windows": dict(color=(0.12, 0.13, 0.15), roughness=0.2, metallic=0.3),   # blender_world adds the lit panes
}
COLORS = {"red": (0.7, 0.04, 0.03), "blue": (0.04, 0.15, 0.6), "green": (0.05, 0.45, 0.1), "yellow": (0.9, 0.7, 0.05),
          "orange": (0.9, 0.35, 0.03), "purple": (0.35, 0.08, 0.5), "pink": (0.9, 0.35, 0.55), "white": (0.9, 0.9, 0.88),
          "black": (0.02, 0.02, 0.02), "grey": (0.4, 0.4, 0.4), "gray": (0.4, 0.4, 0.4), "silver": (0.7, 0.7, 0.72),
          "gold": (0.85, 0.6, 0.15), "brown": (0.35, 0.2, 0.09), "teal": (0.05, 0.45, 0.45), "cyan": (0.1, 0.7, 0.8)}


def box(size, at=(0, 0, 0), mat="plastic", rot=None, bevel=0.0):
    return {"shape": "box", "size": list(size), "at": list(at), "mat": mat, "rot": rot, "bevel": bevel}


def cyl(diameter, height, at=(0, 0, 0), mat="metal", rot=None, top=None, segments=24):
    """A cylinder standing on `at`; `top` (a diameter) makes it a cone or a tapered post."""
    return {"shape": "cyl", "size": [diameter, diameter, height], "at": list(at), "mat": mat, "rot": rot,
            "top": top, "segments": segments}


def ball(diameter, at=(0, 0, 0), mat="plastic", squash=(1, 1, 1)):
    return {"shape": "sphere", "size": [diameter * squash[0], diameter * squash[1], diameter * squash[2]],
            "at": list(at), "mat": mat}


def _wheel(x, y, d=0.62, w=0.22):
    return cyl(d, w, (x - w / 2 if x > 0 else x + w / 2, y, d / 2), "rubber", rot=(0, 90, 0))


# ---------- recipes ----------
# Each: {"parts", "size" (overall w, d, h), "category", optional "seat" {"height", "depth"}, "surface" (height things
# stand on), "front": "-y" (which way it faces), "moves": how it travels ("drive", "fly", "sail", None)}.
# Functions take `p` (the request's details: style, colour, size) and return a recipe.

def _table(p):
    w, d, h = 1.4, 0.8, 0.75
    top = 0.04
    legs = [box((0.06, 0.06, h - top), (sx * (w / 2 - 0.08), sy * (d / 2 - 0.08), 0), "wood") for sx in (-1, 1)
            for sy in (-1, 1)]
    return {"parts": [box((w, d, top), (0, 0, h - top), "wood", bevel=0.008)] + legs, "size": (w, d, h),
            "category": "furniture", "surface": h}


def _chair(p):
    s = 0.46
    legs = [box((0.04, 0.04, s - 0.04), (sx * 0.19, sy * 0.19, 0), "wood") for sx in (-1, 1) for sy in (-1, 1)]
    return {"parts": legs + [box((0.46, 0.46, 0.04), (0, 0, s - 0.04), "wood", bevel=0.006),
                             box((0.44, 0.04, 0.48), (0, 0.21, s), "wood", bevel=0.006)],
            "size": (0.46, 0.46, s + 0.48), "category": "furniture", "seat": {"height": s, "depth": 0.0}}


def _sofa(p):
    w = 2.1
    return {"parts": [box((w, 0.9, 0.12), (0, 0, 0.1), "dark_wood"), box((w - 0.3, 0.75, 0.22), (0, -0.05, 0.22),
                                                                          "fabric", bevel=0.05),
                      box((w, 0.22, 0.55), (0, 0.34, 0.22), "fabric", bevel=0.06),
                      box((0.2, 0.9, 0.42), (-w / 2 + 0.1, 0, 0.22), "fabric", bevel=0.05),
                      box((0.2, 0.9, 0.42), (w / 2 - 0.1, 0, 0.22), "fabric", bevel=0.05)] +
                     [cyl(0.05, 0.1, (sx * (w / 2 - 0.1), sy * 0.35, 0), "dark_wood") for sx in (-1, 1)
                      for sy in (-1, 1)],
            "size": (w, 0.9, 0.77), "category": "furniture", "seat": {"height": 0.44, "depth": -0.05}}


def _bed(p):
    return {"parts": [box((1.6, 2.1, 0.3), (0, 0, 0.1), "dark_wood"), box((1.55, 2.0, 0.22), (0, 0, 0.4), "fabric",
                                                                         bevel=0.05),
                      box((1.6, 0.08, 0.9), (0, 1.04, 0.1), "dark_wood", bevel=0.01),
                      box((0.6, 0.35, 0.12), (-0.38, 0.78, 0.62), "plaster", bevel=0.04),
                      box((0.6, 0.35, 0.12), (0.38, 0.78, 0.62), "plaster", bevel=0.04)],
            "size": (1.6, 2.1, 1.0), "category": "furniture", "seat": {"height": 0.62, "depth": -0.6}}


def _desk(p):
    r = _table(p)
    r["parts"] = [box((1.3, 0.65, 0.04), (0, 0, 0.72), "wood", bevel=0.006),
                  box((0.04, 0.6, 0.72), (-0.61, 0, 0), "wood"), box((0.04, 0.6, 0.72), (0.61, 0, 0), "wood"),
                  box((0.45, 0.55, 0.5), (0.38, 0.02, 0.2), "wood")]
    r["size"] = (1.3, 0.65, 0.76)
    r["surface"] = 0.76
    return r


def _lamp(p):
    return {"parts": [cyl(0.3, 0.03, (0, 0, 0), "dark_metal"), cyl(0.03, 1.5, (0, 0, 0.03), "dark_metal"),
                      cyl(0.42, 0.3, (0, 0, 1.45), "paper", top=0.28), ball(0.1, (0, 0, 1.5), "light")],
            "size": (0.42, 0.42, 1.75), "category": "furniture", "glows": True}


def _bookshelf(p):
    parts = [box((0.9, 0.32, 1.9), (0, 0, 0), "dark_wood")]
    for i, z in enumerate((0.35, 0.75, 1.15, 1.55)):
        x = -0.35
        while x < 0.36:
            w = 0.04 + 0.03 * ((i * 7 + int(x * 100)) % 3)
            parts.append(box((w, 0.22, 0.25 + 0.04 * (int(x * 50) % 3)), (x + w / 2, -0.06, z),
                             ("red", "paper", "fabric", "leather")[(i + int(x * 40)) % 4]))
            x += w + 0.01
    return {"parts": parts, "size": (0.9, 0.32, 1.9), "category": "furniture"}


def _tv(p):
    return {"parts": [box((1.2, 0.08, 0.7), (0, 0, 0.45), "black_plastic"), box((1.12, 0.01, 0.62), (0, -0.045, 0.49),
                                                                                  "screen"),
                      box((0.35, 0.25, 0.04), (0, 0, 0), "black_plastic"), box((0.06, 0.06, 0.45), (0, 0, 0.03),
                                                                               "black_plastic")],
            "size": (1.2, 0.25, 1.15), "category": "furniture", "glows": True}


def _rug(p):
    return {"parts": [box((2.4, 1.7, 0.012), (0, 0, 0), "fabric")], "size": (2.4, 1.7, 0.012), "category": "furniture",
            "flat": True}


def _plant(p):
    return {"parts": [cyl(0.32, 0.32, (0, 0, 0), "ceramic", top=0.38), ball(0.6, (0, 0, 0.5), "foliage",
                                                                             (1, 1, 1.2))],
            "size": (0.6, 0.6, 1.1), "category": "furniture"}


def _cabinet(p):
    return {"parts": [box((1.2, 0.45, 0.85), (0, 0, 0), "wood", bevel=0.01), box((1.24, 0.5, 0.04), (0, 0, 0.85),
                                                                                  "stone")],
            "size": (1.24, 0.5, 0.89), "category": "furniture", "surface": 0.89}


def _fridge(p):
    return {"parts": [box((0.7, 0.7, 1.8), (0, 0, 0), "plastic", bevel=0.02), box((0.04, 0.04, 0.5), (0.28, -0.37, 1.0),
                                                                                    "chrome")],
            "size": (0.7, 0.7, 1.8), "category": "furniture"}


def _tree(p):
    h = 4.5 * p.get("scale", 1.0)
    return {"parts": [cyl(0.32, h * 0.45, (0, 0, 0), "bark", top=0.2, segments=10),
                      ball(h * 0.45, (0, 0, h * 0.35), "foliage", (1, 1, 1.1)),
                      ball(h * 0.32, (h * 0.12, h * 0.06, h * 0.55), "foliage"),
                      ball(h * 0.3, (-h * 0.1, -h * 0.08, h * 0.5), "foliage")],
            "size": (h * 0.6, h * 0.6, h), "category": "nature", "sways": True}


def _pine(p):
    h = 6.0 * p.get("scale", 1.0)
    parts = [cyl(0.3, h * 0.3, (0, 0, 0), "bark", segments=10)]
    for i in range(3):
        parts.append(cyl(h * (0.5 - 0.12 * i), h * 0.38, (0, 0, h * (0.2 + 0.22 * i)), "pine", top=0.02, segments=12))
    return {"parts": parts, "size": (h * 0.5, h * 0.5, h), "category": "nature", "sways": True}


def _palm(p):
    h = 6.0
    parts = [cyl(0.32, h, (0, 0, 0), "bark", top=0.22, segments=10)]
    for i in range(6):
        a = i * 60
        parts.append(box((0.35, 2.4, 0.05), (math.sin(math.radians(a)) * 1.0, math.cos(math.radians(a)) * 1.0, h - 0.2),
                         "foliage", rot=(-25, 0, -a)))
    return {"parts": parts, "size": (4, 4, h + 0.3), "category": "nature", "sways": True}


def _rock(p):
    s = p.get("scale", 1.0)
    return {"parts": [ball(1.4 * s, (0, 0, -0.25 * s), "rock", (1.2, 1, 0.75)), ball(0.8 * s, (0.5 * s, 0.2 * s, -0.1 * s),
                                                                                    "rock", (1, 0.9, 0.7))],
            "size": (1.7 * s, 1.4 * s, 0.8 * s), "category": "nature", "rough": True}


def _bench(p):
    return {"parts": [box((1.8, 0.45, 0.05), (0, 0, 0.42), "wood", bevel=0.005),
                      box((1.8, 0.05, 0.4), (0, 0.22, 0.5), "wood", bevel=0.005),
                      box((0.06, 0.45, 0.42), (-0.8, 0, 0), "dark_metal"), box((0.06, 0.45, 0.42), (0.8, 0, 0),
                                                                               "dark_metal")],
            "size": (1.8, 0.5, 0.9), "category": "outdoor", "seat": {"height": 0.47, "depth": 0.0}}


def _streetlight(p):
    futuristic = p.get("style") == "futuristic"
    return {"parts": [cyl(0.18, 5.5, (0, 0, 0), "dark_metal", top=0.12, segments=12),
                      box((0.12, 1.1, 0.12), (0, -0.5, 5.4), "dark_metal"),
                      box((0.3, 0.45, 0.08), (0, -1.0, 5.32), "neon_cyan" if futuristic else "light")],
            "size": (0.3, 1.3, 5.6), "category": "outdoor", "glows": True}


def _car(p):
    color = p.get("material") or "paint"
    return {"parts": [box((1.8, 4.3, 0.6), (0, 0, 0.32), color, bevel=0.08),
                      box((1.55, 2.2, 0.55), (0, 0.2, 0.9), "dark_glass", bevel=0.1),
                      box((0.3, 0.05, 0.12), (0.6, -2.16, 0.65), "light"), box((0.3, 0.05, 0.12), (-0.6, -2.16, 0.65),
                                                                               "light")] +
                     [_wheel(sx * 0.9, sy * 1.35) for sx in (-1, 1) for sy in (-1, 1)],
            "size": (1.8, 4.3, 1.45), "category": "vehicle", "moves": "drive", "speed": 9.0}


def _bus(p):
    return {"parts": [box((2.5, 11.0, 2.6), (0, 0, 0.4), p.get("material") or "paint", bevel=0.1),
                      box((2.52, 9.5, 0.9), (0, 0.3, 1.7), "dark_glass")] +
                     [_wheel(sx * 1.25, sy * 3.8, 1.0, 0.3) for sx in (-1, 1) for sy in (-1, 1)],
            "size": (2.5, 11.0, 3.0), "category": "vehicle", "moves": "drive", "speed": 7.0}


def _flying_car(p):
    color = p.get("material") or "chrome"
    return {"parts": [ball(4.0, (0, 0, 0.0), color, (0.45, 1.0, 0.24)),
                      ball(1.6, (0, 0.2, 0.42), "dark_glass", (0.8, 1.2, 0.45)),
                      cyl(1.0, 0.18, (1.25, -1.2, 0.18), "dark_metal"), cyl(1.0, 0.18, (-1.25, -1.2, 0.18), "dark_metal"),
                      cyl(1.0, 0.18, (1.25, 1.2, 0.18), "dark_metal"), cyl(1.0, 0.18, (-1.25, 1.2, 0.18), "dark_metal"),
                      cyl(0.8, 0.06, (1.25, -1.2, 0.1), "neon_cyan"), cyl(0.8, 0.06, (-1.25, -1.2, 0.1), "neon_cyan"),
                      cyl(0.8, 0.06, (1.25, 1.2, 0.1), "neon_cyan"), cyl(0.8, 0.06, (-1.25, 1.2, 0.1), "neon_cyan"),
                      box((0.9, 0.06, 0.1), (0, -1.98, 0.45), "light"), box((1.0, 0.06, 0.08), (0, 1.95, 0.45),
                                                                            "neon_pink")],
            "size": (3.6, 4.0, 1.0), "category": "vehicle", "moves": "fly", "speed": 12.0, "glows": True}


def _drone(p):
    parts = [box((0.35, 0.35, 0.12), (0, 0, 0.1), "black_plastic", bevel=0.02)]
    for sx in (-1, 1):
        for sy in (-1, 1):
            parts += [box((0.32, 0.03, 0.03), (sx * 0.2, sy * 0.2, 0.17), "black_plastic", rot=(0, 0, 45 * sx * sy)),
                      cyl(0.28, 0.01, (sx * 0.32, sy * 0.32, 0.21), "plastic")]
    return {"parts": parts, "size": (0.95, 0.95, 0.25), "category": "vehicle", "moves": "fly", "speed": 6.0,
            "spins": True}


def _airplane(p):
    return {"parts": [cyl(2.2, 16.0, (0, 8.0, 1.5), "plastic", rot=(90, 0, 0), top=1.4),
                      box((22.0, 3.0, 0.3), (0, 0.5, 1.6), "plastic"), box((7.0, 1.6, 0.25), (0, 6.8, 2.2), "plastic"),
                      box((0.25, 2.0, 3.0), (0, 7.0, 2.3), "paint")],
            "size": (22.0, 17.0, 5.0), "category": "vehicle", "moves": "fly", "speed": 40.0}


def _boat(p):
    return {"parts": [box((2.2, 6.0, 0.9), (0, 0, 0), "plastic", bevel=0.25), box((1.4, 2.0, 0.9), (0, 0.6, 0.9),
                                                                                  "dark_glass", bevel=0.08)],
            "size": (2.2, 6.0, 1.8), "category": "vehicle", "moves": "sail", "speed": 6.0}


def _spaceship(p):
    r = _flying_car(p)
    r["parts"] = [cyl(3.0, 9.0, (0, 4.5, 1.5), "chrome", rot=(90, 0, 0), top=0.6),
                  box((9.0, 3.5, 0.25), (0, -2.0, 1.4), "dark_metal"),
                  cyl(1.4, 0.8, (0, -4.6, 1.5), "neon_cyan", rot=(90, 0, 0))]
    r["size"] = (9.0, 9.5, 3.0)
    r["speed"] = 25.0
    return r


def _skyscraper(p):
    """A tower `p["height"]` tall on a `p["width"]` footprint; futuristic ones are glass with glowing edges."""
    h = p.get("height", 60.0)
    w = p.get("width", 14.0)
    d = p.get("depth", w)
    futuristic = p.get("style") == "futuristic"
    base = 4.0
    parts = [box((w + 0.6, d + 0.6, base), (0, 0, 0), "concrete" if not futuristic else "dark_metal"),
             box((w, d, h - base), (0, 0, base), "windows")]
    if futuristic:
        for sx in (-1, 1):
            for sy in (-1, 1):
                parts.append(box((0.25, 0.25, h - base), (sx * (w / 2), sy * (d / 2), base),
                                 "neon_cyan" if (sx + sy) % 4 else "neon_pink"))
        parts.append(cyl(min(w, d) * 0.5, 3.0, (0, 0, h), "dark_metal", top=min(w, d) * 0.3))
        parts.append(cyl(0.3, 8.0, (0, 0, h + 3.0), "dark_metal", top=0.05))
    else:
        parts.append(box((w * 0.6, d * 0.6, 2.5), (0, 0, h), "concrete"))
    return {"parts": parts, "size": (w + 0.6, d + 0.6, h + (11 if futuristic else 2.5)), "category": "structure",
            "solid": True}


def _house(p):
    """A simple house for towns and villages (the villa builder makes the detailed ones)."""
    w, d, h = p.get("width", 8.0), p.get("depth", 7.0), 3.0
    return {"parts": [box((w, d, h), (0, 0, 0), "plaster"), box((1.0, 0.06, 2.1), (0, -d / 2 - 0.03, 0), "dark_wood"),
                      box((1.4, 0.06, 1.2), (w / 4, -d / 2 - 0.03, 1.1), "glass"),
                      box((1.4, 0.06, 1.2), (-w / 4, -d / 2 - 0.03, 1.1), "glass"),
                      cyl(max(w, d) * 1.3, h * 0.7, (0, 0, h), "brick", top=0.2, segments=4, rot=(0, 0, 45))],
            "size": (w, d, h * 1.7), "category": "structure", "solid": True}


def _road(p):
    return {"parts": [box((p.get("width", 10.0), p.get("length", 50.0), 0.05), (0, 0, 0), "asphalt")],
            "size": (p.get("width", 10.0), p.get("length", 50.0), 0.05), "category": "ground", "flat": True}


def _cup(p):
    return {"parts": [cyl(0.08, 0.1, (0, 0, 0), "ceramic", top=0.085)], "size": (0.085, 0.085, 0.1), "category": "prop",
            "prop": "cup"}


def _sandwich(p):
    return {"parts": [box((0.13, 0.09, 0.02), (0, 0, 0), "food", bevel=0.006), box((0.12, 0.085, 0.012), (0, 0, 0.02),
                                                                                    "lettuce"),
                      box((0.13, 0.09, 0.02), (0, 0, 0.032), "food", bevel=0.006)],
            "size": (0.13, 0.09, 0.052), "category": "prop", "prop": "sandwich"}


def _plate(p):
    return {"parts": [cyl(0.25, 0.015, (0, 0, 0), "ceramic", top=0.27)], "size": (0.27, 0.27, 0.015), "category": "prop",
            "flat": True}


def _box_prop(p):
    return {"parts": [box((0.4, 0.3, 0.3), (0, 0, 0), "cardboard", bevel=0.005)], "size": (0.4, 0.3, 0.3),
            "category": "prop", "prop": "box"}


def _ball_prop(p):
    return {"parts": [ball(0.22, (0, 0, 0.11), p.get("material") or "red")], "size": (0.22, 0.22, 0.22),
            "category": "prop", "prop": "ball"}


def _laptop(p):
    return {"parts": [box((0.34, 0.24, 0.02), (0, 0, 0), "dark_metal"), box((0.34, 0.01, 0.23), (0, 0.12, 0.02),
                                                                             "dark_metal", rot=(-12, 0, 0)),
                      box((0.31, 0.005, 0.2), (0, 0.112, 0.035), "screen", rot=(-12, 0, 0))],
            "size": (0.34, 0.26, 0.25), "category": "prop", "glows": True}


def _book(p):
    return {"parts": [box((0.16, 0.24, 0.035), (0, 0, 0), "red", bevel=0.003)], "size": (0.16, 0.24, 0.035),
            "category": "prop"}


def _bottle(p):
    return {"parts": [cyl(0.075, 0.2, (0, 0, 0), "glass"), cyl(0.075, 0.08, (0, 0, 0.2), "glass", top=0.025)],
            "size": (0.075, 0.075, 0.28), "category": "prop", "prop": "glass"}


def _phone(p):
    return {"parts": [box((0.075, 0.15, 0.01), (0, 0, 0), "black_plastic", bevel=0.004)], "size": (0.075, 0.15, 0.01),
            "category": "prop", "prop": "phone"}


def _fountain(p):
    return {"parts": [cyl(4.0, 0.5, (0, 0, 0), "stone", segments=32), cyl(3.6, 0.42, (0, 0, 0.1), "water", segments=32),
                      cyl(0.5, 1.5, (0, 0, 0.5), "stone"), cyl(1.4, 0.2, (0, 0, 2.0), "stone", segments=24)],
            "size": (4.0, 4.0, 2.2), "category": "outdoor", "solid": True}


def _fence(p):
    n = 6
    parts = [box((0.08, 0.08, 1.1), (i * 0.9 - n * 0.45, 0, 0), "wood") for i in range(n + 1)]
    parts += [box((n * 0.9, 0.04, 0.1), (0, 0.03, z), "wood") for z in (0.35, 0.85)]
    return {"parts": parts, "size": (n * 0.9, 0.1, 1.1), "category": "outdoor"}


def _cactus(p):
    return {"parts": [cyl(0.45, 2.6, (0, 0, 0), "foliage", top=0.38, segments=12),
                      cyl(0.25, 0.9, (0.38, 0, 1.0), "foliage", top=0.22, segments=10),
                      cyl(0.25, 0.8, (-0.36, 0, 1.4), "foliage", top=0.22, segments=10)],
            "size": (1.1, 0.5, 2.6), "category": "nature"}


def _castle(p):
    w = 24.0
    parts = []
    for sx in (-1, 1):
        parts.append(box((1.6, w, 7.0), (sx * w / 2, 0, 0), "stone"))
        parts.append(box((w, 1.6, 7.0), (0, sx * w / 2, 0), "stone"))
        for sy in (-1, 1):
            parts.append(cyl(4.5, 11.0, (sx * w / 2, sy * w / 2, 0), "stone", segments=16))
            parts.append(cyl(5.2, 3.5, (sx * w / 2, sy * w / 2, 11.0), "brick", top=0.3, segments=16))
    parts.append(box((9.0, 9.0, 16.0), (0, 2.0, 0), "stone"))
    parts.append(cyl(9.5, 6.0, (0, 2.0, 16.0), "brick", top=0.4, segments=4, rot=(0, 0, 45)))
    parts.append(box((3.0, 0.4, 4.0), (0, -w / 2 - 0.9, 0), "dark_wood"))
    return {"parts": parts, "size": (w + 5, w + 5, 22.0), "category": "structure", "solid": True}


RECIPES = {
    "table": _table, "chair": _chair, "sofa": _sofa, "bed": _bed, "desk": _desk, "lamp": _lamp,
    "bookshelf": _bookshelf, "tv": _tv, "rug": _rug, "plant": _plant, "cabinet": _cabinet, "fridge": _fridge,
    "tree": _tree, "pine": _pine, "palm": _palm, "rock": _rock, "bench": _bench, "streetlight": _streetlight,
    "car": _car, "bus": _bus, "flying_car": _flying_car, "drone": _drone, "airplane": _airplane, "boat": _boat,
    "spaceship": _spaceship, "skyscraper": _skyscraper, "house": _house, "road": _road, "cup": _cup,
    "sandwich": _sandwich, "plate": _plate, "box": _box_prop, "ball": _ball_prop, "laptop": _laptop, "book": _book,
    "bottle": _bottle, "phone": _phone, "fountain": _fountain, "fence": _fence, "cactus": _cactus,
    "castle": _castle,
}
# What people call them (longest first when matching). Plurals are handled by the matcher.
ASSET_WORDS = {
    "flying car": "flying_car", "flying vehicle": "flying_car", "hover car": "flying_car", "hovercar": "flying_car",
    "flying taxi": "flying_car", "air taxi": "flying_car", "hover vehicle": "flying_car", "aircar": "flying_car",
    "spaceship": "spaceship", "space ship": "spaceship", "starship": "spaceship", "ufo": "spaceship",
    "airplane": "airplane", "aeroplane": "airplane", "plane": "airplane", "jet": "airplane", "drone": "drone",
    "car": "car", "sports car": "car", "taxi": "car", "vehicle": "car", "truck": "bus", "bus": "bus", "van": "bus",
    "boat": "boat", "ship": "boat", "yacht": "boat",
    "skyscraper": "skyscraper", "tower": "skyscraper", "high rise": "skyscraper", "highrise": "skyscraper",
    "office building": "skyscraper", "building": "skyscraper", "house": "house", "cottage": "house", "hut": "house",
    "table": "table", "dining table": "table", "coffee table": "table", "kitchen table": "table",
    "chair": "chair", "stool": "chair", "armchair": "sofa", "sofa": "sofa", "couch": "sofa", "bed": "bed",
    "desk": "desk", "lamp": "lamp", "floor lamp": "lamp", "bookshelf": "bookshelf", "bookcase": "bookshelf",
    "shelf": "bookshelf", "tv": "tv", "television": "tv", "rug": "rug", "carpet": "rug", "plant": "plant",
    "potted plant": "plant", "cabinet": "cabinet", "counter": "cabinet", "dresser": "cabinet", "fridge": "fridge",
    "refrigerator": "fridge", "tree": "tree", "oak": "tree", "pine": "pine", "pine tree": "pine", "fir": "pine",
    "palm": "palm", "palm tree": "palm", "rock": "rock", "boulder": "rock", "stone": "rock", "bench": "bench",
    "streetlight": "streetlight", "street light": "streetlight", "street lamp": "streetlight",
    "lamp post": "streetlight", "lamppost": "streetlight", "cup": "cup", "mug": "cup", "coffee": "cup",
    "sandwich": "sandwich", "burger": "sandwich", "food": "sandwich", "plate": "plate", "box": "box",
    "crate": "box", "package": "box", "parcel": "box", "ball": "ball", "football": "ball", "laptop": "laptop",
    "computer": "laptop", "book": "book", "bottle": "bottle", "phone": "phone", "fountain": "fountain",
    "fence": "fence", "cactus": "cactus", "castle": "castle", "fortress": "castle", "palace": "castle",
}

# ---------- environments ----------
# kind -> words; each has a layout generator below and a ground material.
ENVIRONMENTS = {
    "city": ("city", "cities", "downtown", "metropolis", "skyline", "urban", "cityscape"),
    "town": ("town", "village", "neighborhood", "neighbourhood", "suburb", "street", "streets"),
    "forest": ("forest", "woods", "woodland", "jungle"),
    "park": ("park", "garden", "meadow", "field", "lawn"),
    "desert": ("desert", "dunes"),
    "mountains": ("mountain", "mountains", "hills", "valley", "landscape"),
    "beach": ("beach", "coast", "shore", "seaside", "island", "ocean", "sea", "lake"),
    "room": ("room", "living room", "lounge", "bedroom", "kitchen", "office", "interior", "apartment", "studio",
             "dining room", "study"),
}
ROOM_FURNITURE = {
    "living room": ["sofa", "table", "tv", "lamp", "plant", "rug", "bookshelf"],
    "bedroom": ["bed", "cabinet", "lamp", "plant", "rug"],
    "kitchen": ["cabinet", "fridge", "table", "chair", "chair"],
    "office": ["desk", "chair", "bookshelf", "lamp", "plant"],
    "dining room": ["table", "chair", "chair", "chair", "chair", "cabinet", "lamp"],
    "room": ["sofa", "table", "lamp", "plant", "rug"],
}


def recipe(name, p=None):
    p = dict(p or {})
    f = RECIPES.get(name)
    if f is None:
        raise KeyError(name)
    r = f(p)
    r.setdefault("front", "-y")
    r["asset"] = name
    return r


def _footprint(item):
    """(x0, y0, x1, y1) of a placed item, with its rotation (multiples of 90 degrees) and scale."""
    w, d = item["size"][0] * item.get("scale", 1.0), item["size"][1] * item.get("scale", 1.0)
    if int(round(item.get("yaw", 0) / 90.0)) % 2:
        w, d = d, w
    x, y = item["at"][:2]
    return (x - w / 2, y - d / 2, x + w / 2, y + d / 2)


def overlaps(a, b, gap=0.0):
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


def scatter(rng, asset, count, area, taken, gap=0.5, p=None, scale=(0.8, 1.25), tries=60, yaw=True):
    """`count` copies of `asset` at random spots in `area` (x0, y0, x1, y1), each clear of `taken` footprints
    (extended as it goes). Returns the placed items."""
    out = []
    for _ in range(count):
        for _ in range(tries):
            s = rng.uniform(*scale)
            r = recipe(asset, dict(p or {}, scale=s) if asset in ("tree", "pine", "rock") else p)
            item = {"asset": asset, "params": dict(p or {}, scale=s) if asset in ("tree", "pine", "rock") else dict(
                p or {}), "size": r["size"], "scale": 1.0 if asset in ("tree", "pine", "rock") else s,
                    "at": [round(rng.uniform(area[0], area[2]), 2), round(rng.uniform(area[1], area[3]), 2), 0.0],
                    "yaw": rng.choice((0, 90, 180, 270)) if yaw else 0}
            fp = _footprint(item)
            if fp[0] < area[0] or fp[2] > area[2] or fp[1] < area[1] or fp[3] > area[3]:
                continue
            if any(overlaps(fp, t, gap) for t in taken):
                continue
            taken.append(fp)
            out.append(item)
            break
    return out


def layout(kind, p=None):
    """The environment `kind` as placed items and its ground: {"items": [...], "ground": {...}, "bounds",
    "streets" (centre lines of streets, for anything that drives or flies along them), "kind"}."""
    p = dict(p or {})
    rng = random.Random(p.get("seed", 11))
    size = {"small": 0.6, "medium": 1.0, "large": 1.6, "huge": 2.2}.get(p.get("size"), 1.0)
    density = p.get("density", 1.0)
    f = {"city": _city, "town": _town, "forest": _nature, "park": _nature, "desert": _nature, "mountains": _nature,
         "beach": _nature, "room": _room}[kind]
    out = f(kind, p, rng, size, density)
    out["kind"] = kind
    return out


def _city(kind, p, rng, size, density):
    """Blocks of towers on a grid of streets: taller in the middle, sidewalks, street lights along the streets."""
    blocks = max(2, int(round(3 * size)))
    block, street = 34.0, 12.0
    pitch = block + street
    half = blocks * pitch / 2
    items, streets = [], []
    futuristic = p.get("style") == "futuristic"
    per_block = max(1, min(4, int(round(2 * density))))
    for i in range(blocks):
        for j in range(blocks):
            cx = -half + street / 2 + block / 2 + i * pitch
            cy = -half + street / 2 + block / 2 + j * pitch
            centre = 1.0 - (abs(i - (blocks - 1) / 2) + abs(j - (blocks - 1) / 2)) / max(1.0, blocks)
            n = per_block if per_block < 4 else 4
            cells = [(0, 0)] if n == 1 else [(-1, -1), (1, 1)] if n == 2 else [(-1, -1), (1, -1), (0, 1)] if n == 3 \
                else [(-1, -1), (1, -1), (-1, 1), (1, 1)]
            for cxo, cyo in cells:
                w = rng.uniform(11, 15) if n > 1 else rng.uniform(18, 26)
                h = rng.uniform(25, 45) + 90 * centre * rng.uniform(0.5, 1.0)
                at = [round(cx + cxo * block / 4, 2), round(cy + cyo * block / 4, 2), 0.0]
                items.append({"asset": "skyscraper", "params": {"height": round(h, 1), "width": round(w, 1),
                                                                 "depth": round(w * rng.uniform(0.8, 1.2), 1),
                                                                 "style": p.get("style")},
                              "at": at, "yaw": 0, "size": [w, w, h], "role": "building"})
    # streets: the gaps between blocks (centre lines), with lights along them
    lines = [-half + i * pitch for i in range(blocks + 1)]
    for x in lines:
        streets.append([[x, -half], [x, half]])
    for y in lines:
        streets.append([[-half, y], [half, y]])
    for (a, b) in streets:
        n = int(math.hypot(b[0] - a[0], b[1] - a[1]) / 22)
        vertical = abs(b[0] - a[0]) < 1e-6
        for k in range(1, n):
            t = k / n
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            off = street / 2 - 0.6
            if vertical:
                items.append({"asset": "streetlight", "params": {"style": p.get("style")}, "at": [x + off, y, 0.0],
                              "yaw": 90, "role": "light"})
            else:
                items.append({"asset": "streetlight", "params": {"style": p.get("style")}, "at": [x, y + off, 0.0],
                              "yaw": 0, "role": "light"})
    ground = {"size": [2 * half + 60, 2 * half + 60], "material": "asphalt", "sidewalks": {
        "blocks": [[-half + street / 2 + i * pitch, -half + street / 2 + j * pitch, block] for i in range(blocks)
                   for j in range(blocks)]}}
    return {"items": items, "ground": ground, "bounds": [-half, -half, half, half], "streets": streets,
            "street_width": street, "futuristic": futuristic}


def _town(kind, p, rng, size, density):
    n = max(4, int(round(8 * size * density)))
    items, taken = [], []
    half = 30.0 * size ** 0.5
    road = [[-half - 10, 0.0], [half + 10, 0.0]]
    taken.append((-half - 10, -4.0, half + 10, 4.0))
    for k in range(n):
        side = 1 if k % 2 else -1
        x = -half + (k // 2 + 0.5) * (2 * half / max(1, (n + 1) // 2))
        item = {"asset": "house", "params": {"width": round(rng.uniform(7, 10), 1), "depth": round(rng.uniform(6, 8), 1)},
                "at": [round(x, 2), side * 10.0, 0.0], "yaw": 0 if side > 0 else 180, "role": "building"}
        item["size"] = [item["params"]["width"], item["params"]["depth"], 5.0]
        items.append(item)
        taken.append(_footprint(item))
    items += [dict(i, role="nature") for i in scatter(rng, "tree", int(10 * density), (-half - 8, -25, half + 8, 25), taken,
                                                       1.0)]
    items.append({"asset": "road", "params": {"width": 8.0, "length": 2 * half + 20}, "at": [0.0, 0.0, 0.0], "yaw": 90,
                  "size": [8.0, 2 * half + 20, 0.05], "role": "ground"})
    return {"items": items, "ground": {"size": [2 * half + 80, 80], "material": "grass"}, "bounds": [-half, -25, half, 25],
            "streets": [road], "street_width": 8.0}


def _nature(kind, p, rng, size, density):
    half = 35.0 * size
    taken = []
    items = []
    ground = {"size": [2 * half + 60, 2 * half + 60], "material": {"desert": "sand", "beach": "sand",
                                                                   "mountains": "grass"}.get(kind, "grass")}
    area = (-half, -half, half, half)
    if kind == "forest":
        items += scatter(rng, "pine", int(40 * density * size), area, taken, 0.8)
        items += scatter(rng, "tree", int(20 * density * size), area, taken, 0.8)
        items += scatter(rng, "rock", int(10 * density * size), area, taken, 0.5)
    elif kind == "park":
        items.append({"asset": "fountain", "params": {}, "at": [0.0, 0.0, 0.0], "yaw": 0, "size": [4, 4, 2.2]})
        taken.append((-3, -3, 3, 3))
        items += scatter(rng, "tree", int(14 * density * size), area, taken, 2.0)
        items += scatter(rng, "bench", int(6 * density), (-14, -14, 14, 14), taken, 1.0)
        items += scatter(rng, "streetlight", 4, (-12, -12, 12, 12), taken, 2.0)
    elif kind == "desert":
        items += scatter(rng, "cactus", int(14 * density * size), area, taken, 2.0)
        items += scatter(rng, "rock", int(14 * density * size), area, taken, 1.0, scale=(0.8, 2.5))
        ground["dunes"] = True
    elif kind == "mountains":
        ground["mountains"] = True
        items += scatter(rng, "pine", int(25 * density * size), (-half * 0.6, -half * 0.6, half * 0.6, half * 0.6), taken,
                         1.0)
        items += scatter(rng, "rock", int(12 * density * size), area, taken, 1.0, scale=(1.0, 3.0))
    elif kind == "beach":
        ground["water"] = {"from_y": half * 0.15}
        items += scatter(rng, "palm", int(8 * density * size), (-half, -half, half, 0.0), taken, 2.0)
        items += scatter(rng, "rock", int(5 * density), (-half, -half, half, 0.0), taken, 1.0)
    for it in items:
        it.setdefault("role", "nature")
    return {"items": items, "ground": ground, "bounds": list(area), "streets": [], "street_width": 0.0}


def _room(kind, p, rng, size, density):
    """A room with walls (a door gap and a window), a ceiling light, and furniture placed along the walls the way
    people arrange rooms: big pieces against walls, a table in the open, nothing in the doorway."""
    name = p.get("room") or "room"
    w, d, h = 7.0 * size ** 0.5, 6.0 * size ** 0.5, 2.8
    furniture = list(p.get("furniture") or ROOM_FURNITURE.get(name, ROOM_FURNITURE["room"]))
    asked = list(p.get("furniture_for") or [])   # [asset, task id] for what the request itself asked for
    if asked:
        furniture = [a for a, _ in asked] + [d for d in ("rug", "plant") if d not in [a for a, _ in asked]]
    owners = [t for _, t in asked] + [None] * 10
    items, taken = [], [(-0.7, -d / 2 - 0.5, 0.7, -d / 2 + 1.2)]   # the doorway stays clear
    wall_slots = [("back", 0.0), ("left", 0.0), ("right", 0.0), ("back", -1.8), ("back", 1.8), ("left", 1.5),
                  ("right", -1.5)]
    for name_ in furniture:
        r = recipe(name_)
        fw, fd = r["size"][0], r["size"][1]
        placed = None
        if name_ in ("rug",):
            placed = {"at": [0.0, 0.3, 0.0], "yaw": 0}
        elif name_ in ("table", "chair") and name_ != "desk":
            pass
        if placed is None and name_ not in ("table", "chair"):
            for side, off in wall_slots:
                if side == "back":
                    at, yaw = [off, d / 2 - fd / 2 - 0.05, 0.0], 0
                elif side == "left":
                    at, yaw = [-w / 2 + fd / 2 + 0.05, off, 0.0], 270
                else:
                    at, yaw = [w / 2 - fd / 2 - 0.05, off, 0.0], 90
                item = {"asset": name_, "at": at, "yaw": yaw, "size": r["size"], "params": {}}
                fp = _footprint(item)
                if not any(overlaps(fp, t, 0.15) for t in taken):
                    placed = {"at": at, "yaw": yaw}
                    taken.append(fp)
                    break
        if placed is None:   # in the open: the table in the middle, chairs around it
            if name_ == "table":
                at = [0.0, 0.2, 0.0]
            elif name_ == "chair":
                tables = [i for i in items if i["asset"] in ("table", "desk")]
                k = sum(1 for i in items if i["asset"] == "chair")
                if tables:
                    t = tables[0]
                    sides = [(0, -1, 0), (0, 1, 180), (-1, 0, 270), (1, 0, 90)]
                    sx, sy, yaw = sides[k % 4]
                    at = [t["at"][0] + sx * (t["size"][0] / 2 + 0.3), t["at"][1] + sy * (t["size"][1] / 2 + 0.3), 0.0]
                    item = {"asset": "chair", "at": at, "yaw": yaw, "size": r["size"], "params": {},
                            "for": next((t for a, t in asked if a == "chair"), None)}
                    items.append(item)
                    taken.append(_footprint(item))
                    continue
                at = [rng.uniform(-w / 3, w / 3), rng.uniform(-d / 3, d / 3), 0.0]
            else:
                at = [rng.uniform(-w / 3, w / 3), rng.uniform(-d / 3, d / 3), 0.0]
            placed = {"at": at, "yaw": 0}
            taken.append(_footprint({"at": at, "yaw": 0, "size": r["size"]}))
        items.append({"asset": name_, "at": placed["at"], "yaw": placed["yaw"], "size": r["size"], "params": {},
                      "for": owners[furniture.index(name_)] if furniture.index(name_) < len(asked) else None})
    for it in items:
        it.setdefault("role", "furniture")
    room = {"width": w, "depth": d, "height": h, "door": {"side": "front", "width": 1.0, "height": 2.1},
            "window": {"side": "left", "width": 1.6, "height": 1.2, "sill": 0.9}}
    return {"items": items, "ground": {"size": [w, d], "material": "wood", "room": room},
            "bounds": [-w / 2, -d / 2, w / 2, d / 2], "streets": [], "street_width": 0.0}


# ---------- routes through free space ----------

def route(free, start, goal, cell=1.0, bounds=None, clearance=0.0):
    """A* on a grid of `cell` metres: `free(x, y)` -> bool (in Blender: nothing solid there at the height the mover
    travels). Returns [(x, y), ...] from start to goal (simplified to its turns), or None when there's no way."""
    if bounds is None:
        bounds = (min(start[0], goal[0]) - 50, min(start[1], goal[1]) - 50, max(start[0], goal[0]) + 50,
                  max(start[1], goal[1]) + 50)

    def key(p):
        return (int(math.floor((p[0] - bounds[0]) / cell)), int(math.floor((p[1] - bounds[1]) / cell)))

    def centre(k):
        return (bounds[0] + (k[0] + 0.5) * cell, bounds[1] + (k[1] + 0.5) * cell)

    nx, ny = int((bounds[2] - bounds[0]) / cell) + 1, int((bounds[3] - bounds[1]) / cell) + 1
    s, g = key(start), key(goal)
    cache = {}

    def ok(k):
        if k in (s, g):
            return True
        if not (0 <= k[0] < nx and 0 <= k[1] < ny):
            return False
        if k not in cache:
            cache[k] = free(*centre(k))
        return cache[k]

    openq = [(0.0, 0.0, s)]
    came = {s: None}
    cost = {s: 0.0}
    steps = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414),
             (-1, -1, 1.414)]
    found = False
    budget = 200000
    while openq and budget:
        budget -= 1
        _, c, cur = heapq.heappop(openq)
        if cur == g:
            found = True
            break
        for dx, dy, w in steps:
            n = (cur[0] + dx, cur[1] + dy)
            if not ok(n) or (dx and dy and (not ok((cur[0] + dx, cur[1])) or not ok((cur[0], cur[1] + dy)))):
                continue
            nc = c + w
            if nc < cost.get(n, 1e18):
                cost[n] = nc
                came[n] = cur
                h = math.hypot(n[0] - g[0], n[1] - g[1])
                heapq.heappush(openq, (nc + h, nc, n))
    if not found:
        return None
    path = []
    k = g
    while k is not None:
        path.append(centre(k))
        k = came[k]
    path.reverse()
    path[0], path[-1] = tuple(start[:2]), tuple(goal[:2])
    return simplify(path, free, cell)


def _line_free(a, b, free, step):
    n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
    return all(free(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n))


def simplify(path, free, cell=1.0):
    """Drop the points a straight line can skip without leaving free space."""
    if len(path) < 3:
        return list(path)
    out = [path[0]]
    i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1 and not _line_free(path[i], path[j], free, cell * 0.5):
            j -= 1
        out.append(path[j])
        i = j
    return out


def gaps_between(points, max_pairs=12):
    """Midpoints between neighbouring objects (each with its nearest two): the places "between the towers" are."""
    mids = []
    for i, a in enumerate(points):
        near = sorted((math.hypot(a[0] - b[0], a[1] - b[1]), j) for j, b in enumerate(points) if j != i)[:2]
        for _, j in near:
            b = points[j]
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if all(math.hypot(m[0] - q[0], m[1] - q[1]) > 0.5 for q in mids):
                mids.append(m)
    return mids[:max_pairs * 3]


def tour(start, points):
    """Visit `points` in nearest-next order from `start`."""
    left_ = list(points)
    out = []
    cur = start
    while left_:
        nxt = min(left_, key=lambda q: math.hypot(q[0] - cur[0], q[1] - cur[1]))
        out.append(nxt)
        left_.remove(nxt)
        cur = nxt
    return out
