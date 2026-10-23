"""Whole buildings in Blender ("build a modern villa with a pool"), planned, built in stages, checked and repaired
before Jarvis says it's done.

Why this exists: such a request used to go to BlenderComputerTask's free-form AI loop, where the small local model
wrote one script that added a single box (its JSON was often broken, so most of its follow-up steps were thrown away)
and nothing compared what Blender held with what "a villa" means. Here the request becomes:

  spec          what was asked: kind, style, storeys, roof, and the features named (pool, garden, garage...)
  plan          a structured layout in metres: volumes, every window and door, entrance, site, extras
  stages        built through blender_scene.py's arch_* helpers, in dependency order, each re-runnable without
                duplicating anything (it first removes only its own parts)
  requirements  acceptance criteria measured in Blender (inspect_build: walls, roof over every part, openings in
                walls, a door at the entrance, nothing floating, materials, sun, camera framing) plus a preview render
                checked from its pixels; a failed requirement re-runs the stage that owns it, then is checked again

and the reply says exactly what was built and what wasn't — never "done" when a requirement still fails.
"""
import json
import math
import re

import blender_control

BUILD_NOUNS = ("villa", "house", "home", "mansion", "cottage", "cabin", "bungalow")
_PLEASE = r"^(?:please |can you |could you |would you |now |i want you to |i'd like you to )*"
_BUILD = re.compile(
    _PLEASE + r"(?:build|create|make|model|design|generate|construct|add|put)\s+(?:me\s+|us\s+)?"
    r"(?P<article>an? |another |one more |a new |a second )(?P<desc>[\w ,'-]*?)\b(?P<noun>" + "|".join(BUILD_NOUNS) +
    r")\b(?P<rest>.*)$", re.I)
_NUMBERS = {"one": 1, "single": 1, "two": 2, "double": 2, "three": 3, "four": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_STOREYS = re.compile(r"\b(one|single|two|double|three|four|[1-4])[- ](?:stor(?:e)?y|stories|storeys|floors?|levels?)\b"
                      r"|\b(?:with|of|on|has|having)\s+(one|two|three|four|[1-4])\s+(?:floors|stories|storeys|levels)\b",
                      re.I)
_MODERN = re.compile(r"\b(?:modern|contemporary|minimal(?:ist)?|futuristic|sleek|glass)\b", re.I)
_CLASSIC = re.compile(r"\b(?:classic(?:al)?|traditional|mediterranean|spanish|tuscan|italian|colonial|cozy|cosy|rustic|"
                      r"farmhouse|country|old|victorian|stone)\b", re.I)
FEATURES = {
    "pool": re.compile(r"\b(?:swimming\s+)?pool\b", re.I),
    "garden": re.compile(r"\b(?:garden|yard|backyard|trees?|landscap\w*|lawn|plants|greenery|hedges?)\b", re.I),
    "garage": re.compile(r"\b(?:garage|carport)\b", re.I),
    "balcony": re.compile(r"\bbalcon(?:y|ies)\b", re.I),
    "terrace": re.compile(r"\b(?:terrace|patio|deck|veranda|porch)\b", re.I),
    "big windows": re.compile(r"\b(?:large|big|huge|tall|wide|floor[- ]to[- ]ceiling|panoramic|lots of|many)\s+"
                              r"(?:glass\s+)?(?:windows|glass|glazing)\b", re.I),
    "cinematic lighting": re.compile(r"\b(?:cinematic|dramatic|golden[- ]hour|sunset)\b(?:\s+light\w*)?", re.I),
}
_SMALL = re.compile(r"\b(?:small|tiny|little|compact|simple)\b", re.I)
_LARGE = re.compile(r"\b(?:large|big|huge|grand|luxury|luxurious|giant|enormous)\b(?!\s+(?:glass\s+)?windows)", re.I)
_ROOF = {"flat": re.compile(r"\bflat[- ]roof", re.I), "gable": re.compile(r"\b(?:gable|gabled|pitched|sloped|pointed|"
                                                                          r"slanted|a-frame)\b", re.I),
         "hip": re.compile(r"\bhip(?:ped)?[- ]roof", re.I)}
# Words that are part of a request's description and need nothing built of their own.
# Words that can't sit between "a" and the building noun of a request for a new building: "add a path from the villa",
# "put a fountain next to the house" and "make a garden for the cottage" name something else, done to a building.
_NOT_DESCRIBING = re.compile(r"\b(?:from|to|towards?|between|beside|behind|near|next|around|along|into|onto|for|of|"
                             r"in|on|at|by|the|my|path|walkway|pathway|footpath|road|pool|garden|fence|wall|tree|"
                             r"fountain|garage|terrace|deck|door|window|roof|room)\b", re.I)
# "... and a path from the pool to the villa": a path the build lays between two of its parts.
_PATH_TO = re.compile(r"\b(?:path|walkway|pathway|footpath|walk)s?\b(?P<rest>[^,.;]*)", re.I)
_PART_WORDS = {"pool": r"(?:swimming )?pool", "garden": r"garden", "garage": r"garage", "terrace": r"terrace|patio",
               "house": r"villa|house|home|mansion|cottage|cabin|bungalow|building|entrance|door"}
_NOISE = re.compile(r"\b(?:a|an|and|the|with|of|in|on|for|me|some|nice|beautiful|pretty|cool|lovely|stunning|"
                    r"amazing|realistic|detailed|blender|please|style|styled|looking|roof|lighting|light|lights|"
                    r"windows?|glass|large|big|huge|small|tiny|little|simple|modern|classic|storey|story|stories|"
                    r"storeys|floors?|levels?|one|two|three|four|single|double|[1-4])\b", re.I)


class BuildSteps(list):
    """The stages of one build, as [(description, action)] like blender_commands.steps_for returns — marked so the
    app knows this is a long, multi-stage job (shown with progress, stoppable) rather than a sub-second command.
    `intro` is what Jarvis says as it starts."""
    spec = None
    intro = "On it — I'll build that in stages and check it in Blender before I say it's done. Say “stop” to cancel."


def parse(text: str):
    """The spec for a whole-building request, or None. "make the house red" (an edit) is not one: a new building
    is always introduced as one ("a villa", "another house")."""
    m = _BUILD.match(" ".join((text or "").split()).strip(" .!?"))
    if not m or _NOT_DESCRIBING.search(m.group("desc")):
        return None
    noun = m.group("noun").lower()
    said = f"{m.group('desc')} {noun} {m.group('rest')}"
    features = [name for name, pattern in FEATURES.items() if pattern.search(said)]
    if _MODERN.search(said):
        style = "modern"
    elif _CLASSIC.search(said) or noun in ("cottage", "cabin"):
        style = "classic"
    else:
        style = "modern"
    storeys = {"villa": 2, "house": 2, "home": 2, "mansion": 3, "cottage": 1, "cabin": 1, "bungalow": 1}[noun]
    s = _STOREYS.search(said)
    if s:
        storeys = _NUMBERS[(s.group(1) or s.group(2)).lower()]
    roof = next((kind for kind, pattern in _ROOF.items() if pattern.search(said)), None)
    if roof is None:
        roof = "flat" if style == "modern" else ("hip" if noun in ("villa", "mansion") else "gable")
    scale = 0.8 if _SMALL.search(said) else 1.2 if _LARGE.search(said) else 1.0
    connections = []
    for path in _PATH_TO.finditer(m.group("rest")):
        named = [part for part, words in _PART_WORDS.items() if re.search(rf"\b(?:{words})\b", path.group("rest"), re.I)]
        ends = (named + ["house"])[:2] if "house" not in named else ["house"] + [n for n in named if n != "house"][:1]
        if len(ends) == 2 and ends[0] != ends[1] and ends[1] in features + ["house"]:
            connections.append(sorted(ends))
    # What was said that nothing here builds ("with a fountain"): said back honestly instead of silently dropped.
    rest = _PATH_TO.sub(" ", m.group("rest")) if connections else m.group("rest")
    for pattern in list(FEATURES.values()) + list(_ROOF.values()):
        rest = pattern.sub(" ", rest)
    leftover = [p.strip() for p in re.split(r",|\band\b|\bwith\b", _NOISE.sub(" ", rest)) if len(p.strip()) > 2]
    return {"kind": noun, "style": style, "storeys": max(1, min(4, storeys)), "roof": roof, "scale": scale,
            "features": features, "another": m.group("article").strip().lower() in ("another", "one more",
                                                                                     "a second"),
            "not_built": leftover, "said": text, "connections": connections}


# ---------- the plan: every size in metres ----------
STOREY_HEIGHT, PLINTH, SLAB, WALL = 3.2, 0.35, 0.2, 0.25
DOOR_WIDTH, DOOR_HEIGHT = 1.2, 2.3


def _window(style, big):
    """(width, sill, height) of a window."""
    if style == "classic":
        return (1.2, 0.9, 1.5) if not big else (1.6, 0.6, 1.9)
    return (2.4, 0.3, 2.4) if big else (1.8, 0.6, 1.9)


def _slots(length, width, keep_clear=()):
    """Where windows `width` wide fit along a wall `length` long (centre offsets), evenly, staying clear of the
    spans in `keep_clear` (a door)."""
    n = max(1, int((length - 0.8) // (width + 1.3)))
    out = []
    for i in range(n):
        at = length * (i + 0.5) / n
        if all(abs(at - c) > (width + w) / 2 + 0.5 for c, w in keep_clear):
            out.append(at)
    if not out and not keep_clear:
        out = [length / 2]
    return out


def _volume(name, x0, y0, w, d, storeys, roof, style, big, sides=("front", "back", "left", "right"),
            open_sides=(), entrance=False, back_doors=False, accent=None):
    window_w, sill, height = _window(style, big)
    openings = []
    for side in sides:
        if side in open_sides:
            continue
        length = w if side in ("front", "back") else d
        for k in range(storeys):
            clear = []
            if entrance and side == "front" and k == 0:
                at = length / 2
                openings.append({"side": side, "storey": k, "kind": "door", "at": at, "width": DOOR_WIDTH,
                                 "sill": 0.0, "height": DOOR_HEIGHT})
                clear.append((at, DOOR_WIDTH))
            if back_doors and side == "back" and k == 0:   # big sliding glass doors to the garden
                at = length * 0.3   # in the room left of the inner wall; the stairs take the back wall right of it
                openings.append({"side": side, "storey": k, "kind": "glass_door", "at": at, "width": 3.0,
                                 "sill": 0.0, "height": 2.5})
                clear.append((at, 3.0))
            for at in _slots(length, window_w, clear):
                openings.append({"side": side, "storey": k, "kind": "window", "at": round(at, 3), "width": window_w,
                                 "sill": sill, "height": height})
    return {"name": name, "min": [x0, y0], "size": [w, d], "storeys": storeys, "roof": roof, "openings": openings,
            "open_sides": list(open_sides), "open_storeys": 1, "accent": accent}


PASSAGE_WIDTH, PASSAGE_HEIGHT = 1.1, 2.2
RISERS, STAIR_WIDTH = 16, 1.0   # 16 risers of 0.2 m climb one 3.2 m storey


def _rooms_and_stairs(vol):
    """The inner wall that makes two rooms of a volume (with a doorway), and for more than one storey the stairs:
    along the back wall beside the inner wall, or along the left wall when that's too short. The windows the stairs
    would stand in front of on the ground floor go."""
    (x0, y0), (w, d) = vol["min"], vol["size"]
    vol["inner_wall"] = [round(x0 + w * 0.55, 3), round(y0 + d / 2, 3), 1.0] if w >= 7 and d >= 5 else None
    if vol["storeys"] < 2:
        return
    start = (vol["inner_wall"][0] + 0.06) if vol["inner_wall"] else x0 + WALL + 0.2
    going = min(0.28, (x0 + w - WALL - 0.2 - start) / RISERS)
    if going >= 0.22:
        stairs = {"axis": 0, "start": round(start, 3), "going": round(going, 3), "side": "back",
                  "across": [round(y0 + d - WALL - STAIR_WIDTH, 3), round(y0 + d - WALL, 3)]}
        base = x0
    else:
        going = min(0.28, (d - 2 * WALL - 0.4) / RISERS)
        stairs = {"axis": 1, "start": round(y0 + WALL + 0.2, 3), "going": round(going, 3), "side": "left",
                  "across": [round(x0 + WALL, 3), round(x0 + WALL + STAIR_WIDTH, 3)]}
        base = y0
    stairs["risers"] = RISERS
    stairs["inward"] = -1 if stairs["side"] == "back" else 1   # the second lane of a switchback, into the room
    vol["stairs"] = stairs
    lo, hi = stairs["start"] - base, stairs["start"] - base + going * RISERS
    vol["openings"] = [o for o in vol["openings"] if not (
        o["side"] == stairs["side"] and o["storey"] == 0 and o["at"] + o["width"] / 2 > lo - 0.2
        and o["at"] - o["width"] / 2 < hi + 0.2)]


def _connect(volumes, vol):
    """A doorway through the wall `vol` shares with its neighbour. `vol`'s own side there is left open, so the wall
    that stands is the neighbour's: the passage goes in that one, centred on the stretch the two have in common."""
    side = vol["open_sides"][0]
    x_face = vol["min"][0] if side == "left" else vol["min"][0] + vol["size"][0]
    other_side = "right" if side == "left" else "left"
    for other in volumes:
        face = other["min"][0] + other["size"][0] if other_side == "right" else other["min"][0]
        if other is vol or abs(face - x_face) > 1e-6:
            continue
        lo = max(vol["min"][1], other["min"][1])
        hi = min(vol["min"][1] + vol["size"][1], other["min"][1] + other["size"][1])
        if hi - lo < PASSAGE_WIDTH + 1.0:
            continue
        other["openings"] = [o for o in other["openings"] if not (o["side"] == other_side and o["storey"] == 0)]
        other["openings"].append({"side": other_side, "storey": 0, "kind": "passage",
                                  "at": round((lo + hi) / 2 - other["min"][1], 3), "width": PASSAGE_WIDTH,
                                  "sill": 0.0, "height": PASSAGE_HEIGHT})
        return


def plan(spec, build="Villa", origin=(0.0, 0.0)):
    """A complete layout for `spec`, in plan coordinates centred on `origin`: the volumes with every opening, the
    entrance, the site, and the extras asked for. Pure arithmetic, so it's tested without Blender."""
    s, style, kind = spec["scale"], spec["style"], spec["kind"]
    big = "big windows" in spec["features"] or style == "modern"
    storeys, roof = spec["storeys"], spec["roof"]
    sizes = {"villa": (14, 9), "mansion": (18, 11), "house": (11, 8), "home": (11, 8), "cottage": (8.5, 6.5),
             "cabin": (7, 5.5), "bungalow": (12, 8)}
    w, d = (round(v * s, 1) for v in sizes[kind])
    x0, y0 = origin[0] - w / 2, origin[1] - d / 2
    volumes = [_volume("main house", x0, y0, w, d, storeys, roof, style, big, entrance=True,
                       back_doors=kind in ("villa", "mansion", "house", "home", "bungalow"),
                       accent="front" if style == "modern" else None)]
    wing_roof = "flat" if style == "modern" else roof
    if kind in ("villa", "mansion"):   # a lower wing, set back from the front: more than one box
        ww, wd = round(8 * s, 1), round(7 * s, 1)
        volumes.append(_volume("wing", x0 + w, y0 + 1.2, ww, wd, 1, wing_roof, style, big, open_sides=("left",)))
        volumes[0]["openings"] = [o for o in volumes[0]["openings"] if not (o["side"] == "right" and o["storey"] == 0)]
    if kind == "mansion":
        ww, wd = round(8 * s, 1), round(7 * s, 1)
        volumes.append(_volume("east wing", x0 - ww, y0 + 1.2, ww, wd, 1, wing_roof, style, big,
                               open_sides=("right",)))
        volumes[0]["openings"] = [o for o in volumes[0]["openings"] if not (o["side"] == "left" and o["storey"] == 0)]
    driveways = []
    if "garage" in spec["features"]:
        gw, gd = 6.5, 6.5
        gx = min(v["min"][0] for v in volumes) - gw
        garage = _volume("garage", gx, y0 + 0.6, gw, gd, 1, "flat" if style == "modern" else roof, style, False,
                         sides=("back", "left"), open_sides=("right",))
        garage["openings"].append({"side": "front", "storey": 0, "kind": "garage", "at": gw / 2, "width": 3.0,
                                   "sill": 0.0, "height": 2.4})
        volumes.append(garage)
        if "left" not in volumes[0].get("open_sides", []):
            volumes[0]["openings"] = [o for o in volumes[0]["openings"] if not (o["side"] == "left" and o["storey"] == 0)]
        driveways.append({"span": [gx + gw / 2 - 1.7, gx + gw / 2 + 1.7], "face_y": y0 + 0.6})
    for vol in volumes[1:]:   # every added volume opens into the one it leans on: a house, not boxes side by side
        _connect(volumes, vol)
    for vol in volumes:
        _rooms_and_stairs(vol)
    entrance = {"volume": "main house", "span": [origin[0] - DOOR_WIDTH / 2, origin[0] + DOOR_WIDTH / 2],
                "top": PLINTH + SLAB + DOOR_HEIGHT, "face_y": y0,
                # under a low pitched eave the roof already shelters the door, and a canopy would cut into it
                "canopy": roof == "flat" or storeys > 1}
    lo_x = min(v["min"][0] for v in volumes)
    hi_x = max(v["min"][0] + v["size"][0] for v in volumes)
    hi_y = max(v["min"][1] + v["size"][1] for v in volumes)
    extras = {}
    if "pool" in spec["features"]:
        pw, pd = round(8 * s, 1), round(4 * s, 1)
        extras["pool"] = {"min": [hi_x + 3.0, y0 - 1.0], "size": [pw, pd]}
        hi_x = hi_x + 3.0 + pw + 1.2
    if "terrace" in spec["features"]:
        wing = volumes[1] if len(volumes) > 1 and volumes[1]["name"] == "wing" else volumes[0]
        extras["terrace"] = {"min": [wing["min"][0] + 0.5, wing["min"][1] - 3.0], "size": [wing["size"][0] - 1.0, 3.0]}
    if "balcony" in spec["features"] and storeys >= 2:
        span = [x0 + w * 0.62, x0 + w * 0.62 + 4.0]
        main = volumes[0]
        main["openings"] = [o for o in main["openings"] if not (o["side"] == "front" and o["storey"] == 1 and
                                                                 span[0] - 1.5 < x0 + o["at"] < span[1] + 1.5)]
        main["openings"].append({"side": "front", "storey": 1, "kind": "glass_door", "at": w * 0.62 + 2.0,
                                 "width": 2.4, "sill": 0.0, "height": 2.4})
        extras["balcony"] = {"span": span, "face_y": y0, "depth": 1.6, "z": PLINTH + STOREY_HEIGHT + SLAB,
                             "side": "front"}
    front_margin, side_margin = 10.0, 6.0
    site = {"min": [lo_x - side_margin, y0 - front_margin],
            "size": [hi_x - lo_x + 2 * side_margin, hi_y - (y0 - front_margin) + side_margin]}
    if "garden" in spec["features"]:
        sx0, sy0 = site["min"]
        sx1, sy1 = sx0 + site["size"][0], sy0 + site["size"][1]
        trees = [(sx0 + 2.5, y0 - 4.0, 1.1), (sx0 + 2.5, hi_y - 1.0, 1.0), (sx1 - 2.5, hi_y + 2.5, 1.2),
                 (lo_x + 1.5, hi_y + 3.0, 0.9), (hi_x - 1.0, sy0 + 2.5, 0.8)]
        hedges = [((sx0 + 0.5, sy0 + 0.5), (origin[0] - 2.0, sy0 + 1.2)),
                  ((origin[0] + 2.0, sy0 + 0.5), (sx1 - 0.5, sy0 + 1.2))]
        if driveways:   # leave the drive open
            d0, d1 = driveways[0]["span"]
            hedges = [((sx0 + 0.5, sy0 + 0.5), (d0 - 0.5, sy0 + 1.2)),
                      ((d1 + 0.5, sy0 + 0.5), (origin[0] - 2.0, sy0 + 1.2)),
                      ((origin[0] + 2.0, sy0 + 0.5), (sx1 - 0.5, sy0 + 1.2))]
        extras["garden"] = {"trees": [list(t) for t in trees], "hedges": [[list(a), list(b)] for a, b in hedges]}
    sun = {"elevation": 22, "energy": 5.0} if "cinematic lighting" in spec["features"] else {"elevation": 45, "energy": 4.0}
    connections = [{"between": ends, "width": 1.2, "quality": 0} for ends in spec.get("connections", [])
                   if all(e == "house" or e in extras for e in ends)]
    return {"build": build, "kind": kind, "style": style, "origin": [origin[0], origin[1]], "spec": spec,
            "connections": connections,
            "storey_height": STOREY_HEIGHT, "plinth": PLINTH, "slab": SLAB, "wall": WALL, "overhang": 0.45,
            "pitch": 30 if roof != "flat" else 0, "volumes": volumes, "entrance": entrance, "site": site,
            "driveways": driveways, "extras": extras, "sun": sun}


def site_bounds(p):
    (x0, y0), (w, d) = p["site"]["min"], p["site"]["size"]
    return x0, y0, x0 + w, y0 + d


# ---------- what "done" means for this request ----------

def _expected_walls(p):
    return sum(v["storeys"] * 4 - len(v.get("open_sides", [])) for v in p["volumes"])


def requirements(spec, p):
    """[(id, what it means, the stage that fixes it, check(facts) -> "" or what's wrong)]: what must hold in
    Blender before this build counts as done. Only features that were asked for are required."""
    windows = sum(1 for v in p["volumes"] for o in v["openings"] if o["kind"] in ("window", "glass_door"))
    doors = sum(1 for v in p["volumes"] for o in v["openings"] if o["kind"] == "door")
    storeys = sum(v["storeys"] for v in p["volumes"])
    flights = sum(v["storeys"] - 1 for v in p["volumes"] if v.get("stairs"))
    # What blender_scene._doorways ray-casts through: inner doorways per storey, passages, one per flight.
    doorways = (sum(v["storeys"] for v in p["volumes"] if v.get("inner_wall")) + flights +
                sum(1 for v in p["volumes"] for o in v["openings"] if o["kind"] == "passage"))
    roles = lambda f, r: f["roles"].get(r, 0)
    reqs = [
        ("volumes", f"{len(p['volumes'])} building volume(s) with outer walls", "structure",
         lambda f: "" if len(f["volumes"]) == len(p["volumes"]) and roles(f, "wall") >= _expected_walls(p)
         else f"{roles(f, 'wall')} of {_expected_walls(p)} walls built"),
        ("floors", f"a floor slab for each of {storeys} storey(s), on a foundation", "structure",
         lambda f: "" if roles(f, "slab") >= storeys and roles(f, "foundation") >= len(p["volumes"])
         else f"{roles(f, 'slab')} floor slabs, {roles(f, 'foundation')} foundations"),
        ("rooms", "inner walls dividing the floors into rooms", "structure",
         lambda f: "" if roles(f, "interior_wall") >= 1 else "no inner walls"),
        ("connected", "every room reachable: open doorways, passages between the parts, stairs into open stairwells",
         "structure",
         lambda f: "" if len(f.get("doorways", [])) >= doorways and all(d["open"] for d in f["doorways"])
         else "blocked: " + (", ".join(d["doorway"] for d in f.get("doorways", []) if not d["open"])
                             or f"{len(f.get('doorways', []))} of {doorways} doorways found")),
        ("stairs", f"stairs up to every upper storey ({flights} flight{'s' if flights != 1 else ''})", "structure",
         lambda f: "" if roles(f, "stairs") >= flights else f"{roles(f, 'stairs')} of {flights} stair flights"),
        ("roof", "a roof over every part of the building", "roof",
         lambda f: "" if f["volumes"] and all(v["roofed"] for v in f["volumes"])
         else "no roof over: " + ", ".join(v["name"] for v in f["volumes"] if not v["roofed"]) or "no volumes"),
        ("proportions", f"storeys {STOREY_HEIGHT} m high", "structure",
         lambda f: "" if all(abs(v["wall_top"] - (PLINTH + v["storeys"] * STOREY_HEIGHT)) < 0.06 for v in f["volumes"])
         else "walls stop at " + ", ".join(f"{v['wall_top']} m" for v in f["volumes"])),
        ("windows", f"{windows} windows and glass doors, glazed", "openings",
         lambda f: "" if roles(f, "glass") >= windows else f"{roles(f, 'glass')} of {windows} glazed"),
        ("doors", "an entrance door in the front wall", "openings",
         lambda f: "" if roles(f, "door") >= doors and f["door_on_front"] else "no door at the entrance"),
        ("openings in walls", "every window and door sits in a gap in a wall", "openings",
         lambda f: "" if f["openings_filled"] and f["openings_in_walls"] == f["openings_filled"]
         else f"{f['openings_filled'] - f['openings_in_walls']} not in a wall"),
        ("entrance", "steps and a path leading to the entrance", "site",
         lambda f: "" if f["path_reaches_entrance"] else "no path reaches the entrance steps"),
        ("grounded", "the building stands on the ground, nothing floats", "structure",
         lambda f: "" if f["ground_gap"] is not None and abs(f["ground_gap"]) < 0.03 and not f["floating"]
         else f"ground gap {f['ground_gap']}; floating: {', '.join(f['floating'][:4]) or 'none'}"),
        ("no clashes", "no part stands inside another", "extras",
         lambda f: "" if not f["clashes"] else "overlapping: " + "; ".join(f["clashes"][:3])),
        ("materials", "every part has a working material; glass is clear", "structure",
         lambda f: "" if not f["no_material"] and not f["unconnected"] and f["glass_clear"]
         else f"no material: {f['no_material'][:3]}, broken shader: {f['unconnected'][:3]}, glass clear: "
              f"{f['glass_clear']}"),
        ("light", "a sun lighting the scene", "lighting",
         lambda f: "" if f["sun"] else "no sun"),
        ("camera", "a camera framing the whole building", "lighting",
         lambda f: "" if f["camera_sees"] and f["coverage"] >= 0.12
         else f"camera sees all of it: {f['camera_sees']}, fills {f['coverage']:.0%} of the picture"),
    ]
    feature_checks = {
        "pool": ("a swimming pool with water", "extras",
                 lambda f: "" if roles(f, "water") and roles(f, "pool") else "no pool"),
        "garden": ("a garden with trees and hedges", "extras",
                   lambda f: "" if roles(f, "tree") >= 6 and roles(f, "hedge") >= 1 else "no garden"),
        "garage": ("a garage with a garage door", "openings",
                   lambda f: "" if roles(f, "garage_door") else "no garage door"),
        "balcony": ("a balcony with a railing", "extras",
                    lambda f: "" if roles(f, "balcony") and roles(f, "railing") else "no balcony"),
        "terrace": ("a terrace", "extras", lambda f: "" if roles(f, "terrace") else "no terrace"),
        "big windows": ("large windows", "openings",
                        lambda f: "" if roles(f, "glass") >= windows else "too few windows"),
    }
    for c in p.get("connections", []):
        ends = c["between"]
        def joined(f, ends=ends):
            found = next((x for x in f.get("connections", []) if sorted(x["between"]) == sorted(ends)), None)
            return "" if found and found["ok"] else "; ".join((found or {}).get("problems", ["no path"]))
        reqs.append((f"path {ends[0]}-{ends[1]}", f"a path between the {ends[0]} and the {ends[1]}, joining both",
                     "connections", joined))
    for feature in spec["features"]:
        if feature in feature_checks:
            what, stage, check = feature_checks[feature]
            if feature == "balcony" and spec["storeys"] < 2:
                continue   # nowhere to put one: said in the reply instead
            reqs.append((feature, what, stage, check))
    return reqs


# In dependency order: the site comes from the plan alone, and the walls are checked against its ground.
STAGES = [("site", "Laying the ground, steps and path"),
          ("structure", "Building the foundations, floors and walls"),
          ("openings", "Fitting the windows and doors"),
          ("roof", "Putting the roof on"),
          ("extras", "Adding what you asked for around it"),
          ("connections", "Laying the paths between the parts"),
          ("lighting", "Setting up the sun, sky and camera")]
# What else must be re-run when a stage is: the camera frames whatever the others built.
_AFTER = {"structure": ["openings", "roof", "connections", "lighting"], "roof": ["lighting"],
          "extras": ["connections", "lighting"], "site": ["connections", "lighting"], "openings": [],
          "connections": [], "lighting": []}
REPAIR_ROUNDS = 2


def unmet(reqs, facts):
    out = []
    for rid, what, stage, check in reqs:
        try:
            problem = check(facts)
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
            problem = f"couldn't be measured ({type(e).__name__})"
        if problem:
            out.append((rid, what, stage, problem))
    return out


def stages_to_repair(failed) -> list:
    wanted = set()
    for _, _, stage, _ in failed:
        wanted.add(stage)
        wanted.update(_AFTER[stage])
    return [s for s, _ in STAGES if s in wanted]


# ---------- running it ----------

def _kit(bridge, code, timeout=60):
    return bridge.run(blender_control.with_kit(code), timeout=timeout)


def _json(response, doing):
    if response.get("busy"):
        raise RuntimeError(f"Blender is still busy {doing}; it will finish on its own. Ask me to check the scene "
                           "in a moment.")
    if not response.get("ok"):
        error = (response.get("error") or "").strip().splitlines()
        raise RuntimeError(f"Blender reported an error while {doing}: {error[-1] if error else 'unknown'}")
    return json.loads(response.get("output") or "null")


# Runs in Blender before planning: where the build can go without touching anything, and Blender's untouched
# factory cube (not anyone's work) out of the way — "a villa" was never meant to have a grey box in its hall.
_PREPARE = r"""
import json
scene = bpy.context.scene
removed = []
cube = scene.objects.get('Cube')
if (cube is not None and cube.type == 'MESH' and len(cube.data.vertices) == 8 and not cube.modifiers
        and not cube.get('jarvis_build') and tuple(round(v, 4) for v in cube.location) == (0, 0, 0)
        and tuple(round(v, 4) for v in cube.dimensions) == (2, 2, 2)
        and all(not s.material or s.material.name == 'Material' for s in cube.material_slots)):
    bpy.data.objects.remove(cube, do_unlink=True)
    removed.append('Cube')
    # The startup scene's lamp too, when it is untouched: it stands where the house's upper floor goes and shows as a
    # glaring spot in a window. Only alongside the untouched cube, so a lamp in anyone's own scene is never removed.
    lamp = scene.objects.get('Light')
    if (lamp is not None and lamp.type == 'LIGHT' and lamp.data.type == 'POINT' and abs(lamp.data.energy - 1000) < 1e-3
            and not lamp.get('jarvis_build') and (lamp.location - mathutils.Vector((4.0762, 1.0055, 5.9039))).length < 1e-3):
        bpy.data.objects.remove(lamp, do_unlink=True)
        removed.append('Light')
others =[o for o in scene.objects if o.type == 'MESH' and o.visible_get() and o.get('jarvis_build') != BUILD]
_sync()
if others:
    lo = [min(box(o)[0][i] for o in others) for i in range(2)]
    hi = [max(box(o)[1][i] for o in others) for i in range(2)]
else:
    lo = hi = None
names = sorted({o.get('jarvis_build') for o in scene.objects if o.get('jarvis_build')})
RESULT = json.dumps({"removed": removed, "others": [lo, hi] if lo else None, "builds": names})
"""


def _place(p_at_zero, others):
    """Where the plan's centre goes so its whole site stays clear of what's already in the scene (+x of it)."""
    if not others:
        return 0.0, 0.0
    (lo_x, lo_y), (hi_x, hi_y) = others
    x0, _, _, _ = site_bounds(p_at_zero)
    return round(hi_x - x0 + 2.0, 2), 0.0


def _name_for(spec, existing):
    base = spec["kind"].title()
    if not spec.get("another") and base in existing:
        return base          # the same build again: re-done in place, never a duplicate on top
    if base not in existing:
        return base
    n = 2
    while f"{base} {n}" in existing:
        n += 1
    return f"{base} {n}"


def describe(spec, p, facts=None) -> str:
    storeys = {1: "single-storey", 2: "two-storey", 3: "three-storey", 4: "four-storey"}[spec["storeys"]]
    parts = [v["name"] for v in p["volumes"]]
    windows = sum(1 for v in p["volumes"] for o in v["openings"] if o["kind"] in ("window", "glass_door"))
    roof = {"flat": "flat roofs", "gable": "gabled roofs", "hip": "hipped roofs"}[spec["roof"]]
    extras = [{"pool": "a swimming pool", "garden": "a garden", "garage": "a garage", "balcony": "a balcony",
               "terrace": "a terrace"}[f] for f in spec["features"] if f in ("pool", "garden", "garage", "balcony",
                                                                              "terrace")]
    if "balcony" in spec["features"] and spec["storeys"] < 2:
        extras.remove("a balcony")
    rooms = "rooms joined by doorways" + (", stairs to every floor" if any(v.get("stairs") for v in p["volumes"])
                                          else "")
    text = (f"a {storeys} {spec['style']} {spec['kind']} — {', '.join(parts)} — with {windows} windows and glass doors, "
            f"an entrance door with steps and a path, {rooms}, {roof}")
    if extras:
        text += ", " + ", ".join(extras)
    for c in p.get("connections", []):
        a, b = c["between"]
        text += f", a path between the {spec['kind'] if a == 'house' else a} and the {spec['kind'] if b == 'house' else b}"
    return text


def steps_for(text: str, session, bridge):
    """BuildSteps for a whole-building request, or None if `text` isn't one."""
    spec = parse(text)
    if spec is None:
        return None

    def make_plan(found):
        name = _name_for(spec, found["builds"])
        probe = plan(spec, name)
        origin = _place(probe, found["others"]) if name not in found["builds"] else _existing_origin(bridge, name)
        if name in found["builds"]:
            edits = _edits_in(_existing_plan(bridge, name))
            confirm = getattr(session, "confirm", None)
            if edits and confirm is not None and not confirm(
                    f"There's already a {spec['kind']} here that you changed ({', '.join(edits)}). Build a new one in "
                    f"its place? A copy of the scene is kept first."):
                raise RuntimeError(f"Okay — I left the {spec['kind']} as it is. Say “another {spec['kind']}” for a "
                                   f"second one, or tell me what to change on this one.")
        return spec, name, plan(spec, name, origin)
    steps = _staged(session, bridge, make_plan, spec["kind"])
    steps.spec = spec
    return steps


EXTENSIONS = ("pool", "garden", "terrace", "balcony", "garage")


def extend_steps(addition: str, target: str, session, bridge):
    """BuildSteps that add `addition` (a pool, a garden, a terrace, a balcony, a garage) to the building already in
    the scene (`target` names it when there are several), keeping everything that was done to it since it was built:
    where its parts were moved, what was improved, its paths. Only the stages the addition touches run again — a
    garage changes the walls, so it needs all of them; a pool only the extras, paths and camera."""
    def make_plan(found):
        if not found["builds"]:
            raise RuntimeError(f"There's no building in the scene to add a {addition} to. Say “create a villa with a "
                               f"{addition}” to build one with it.")
        name = next((b for b in found["builds"] if target and b.lower() in target.lower()), found["builds"][-1])
        old = _existing_plan(bridge, name)
        spec = dict(old.get("spec") or _spec_from_plan(old))
        if addition in spec["features"] and addition in old.get("extras", {}):
            raise RuntimeError(f"The {name.lower()} already has a {addition}. Tell me what to change about it — move "
                               f"it, make it bigger, or make it better.")
        spec["features"] = list(dict.fromkeys(spec["features"] + [addition]))
        spec["not_built"] = []
        new = plan(spec, name, tuple(old["origin"]))
        for key in ("quality", "materials", "bevels"):
            if key in old:
                new[key] = old[key]
        new["extras"].update(old.get("extras", {}))   # the parts already there stay where they are now
        new["connections"] = old.get("connections", [])
        if old.get("entrance", {}).get("planters"):
            new["entrance"]["planters"] = True
        return spec, name, new
    stages = None if addition == "garage" else ["extras", "connections", "lighting"]
    steps = _staged(session, bridge, make_plan, addition, stages=stages, adding=addition)
    steps.intro = f"On it — adding a {addition} to the building that's there, then checking it in Blender."
    return steps


def _edits_in(p) -> list:
    """What was done to a build since it was built, in words (nothing for an untouched one)."""
    edits = []
    if p.get("quality"):
        edits.append("improved " + " and ".join(sorted(p["quality"])))
    if p.get("connections") and not p.get("spec", {}).get("connections"):
        edits.append("added paths")
    if p.get("materials") and not p.get("quality"):
        edits.append("new colours")
    built = plan(p["spec"], p["build"], tuple(p["origin"]))["extras"] if p.get("spec") else {}
    moved = [k for k, v in p.get("extras", {}).items() if k in built and v.get("min") != built[k].get("min")]
    if moved:
        edits.append("moved the " + " and the ".join(moved))
    if set(p.get("extras", {})) - set(built) and p.get("spec"):
        edits.append("added " + " and ".join(sorted(set(p["extras"]) - set(built))))
    return edits


def _existing_plan(bridge, name):
    found = _json(bridge.run(f"o = bpy.data.objects.get({name!r})\n"
                             "RESULT = o['jarvis_plan'] if o and o.get('jarvis_plan') else 'null'", timeout=15),
                  "reading the building's plan")
    if not found:
        raise RuntimeError(f"I can't find the plan of the {name.lower()} in Blender, so I can't extend it safely.")
    return found


def _spec_from_plan(p):
    """The spec of a build made before plans kept their spec: what its plan shows."""
    main = p["volumes"][0]
    return {"kind": p["kind"], "style": p["style"], "storeys": main["storeys"], "roof": main["roof"],
            "scale": round(main["size"][0] / {"villa": 14, "mansion": 18, "house": 11, "home": 11, "cottage": 8.5,
                                              "cabin": 7, "bungalow": 12}[p["kind"]], 2),
            "features": [k for k in p.get("extras", {})] + (["garage"] if any(v["name"] == "garage" for v in
                                                                             p["volumes"]) else []),
            "another": False, "not_built": [], "said": "", "connections": [c["between"] for c in
                                                                           p.get("connections", [])]}


def _staged(session, bridge, make_plan, what, stages=None, adding=None):
    """The build steps: plan (make_plan(found) -> (spec, name, plan)), the stages (all, or only `stages`), the
    checks with repairs, and a preview picture that is looked at."""
    state = {}
    steps = BuildSteps()

    def prepare():
        import computer_use
        state["checkpoint"] = computer_use.save_blender_checkpoint(bridge)
        found = _json(_kit(bridge, f"BUILD = {what.title()!r}\n" + _PREPARE), "looking at the scene")
        spec, name, p = make_plan(found)
        state.update(spec=spec, plan=p, name=name, reqs=requirements(spec, p), removed=found["removed"],
                     adding=adding)
        if session is not None and not adding:
            # From the first stage on, "undo" removes the whole build — finished, failed or cancelled half-way.
            session.remember_blender_object(name, spec["kind"])
            session.blender_focus = name
            session.last_undo = {"description": f"built the {spec['kind']}", "code": _REMOVE.format(build=name)}
        if session is not None:
            session.blender_feature = f"{name}/{adding}" if adding else f"{name}/house"
        return f"Planned {describe(spec, p)}."
    prepare.state = "planning"
    steps.append(("Planning the building" if not adding else f"Planning where the {adding} goes", prepare))

    for stage, label in STAGES:
        if stages is None or stage in stages:
            steps.append((label, _stage_action(bridge, state, stage)))

    def verify():
        p, reqs = state["plan"], state["reqs"]
        facts = _inspect(bridge, p)
        failed = unmet(reqs, facts)
        for _ in range(REPAIR_ROUNDS):
            if not failed:
                break
            for stage in stages_to_repair(failed):
                _run_stage(bridge, p, stage)
            facts = _inspect(bridge, p)
            failed = unmet(reqs, facts)
        state.update(facts=facts, failed=failed)
        if failed:
            raise RuntimeError(_partial_report(state))
        return f"All {len(reqs)} checks pass in Blender."
    verify.state = "verifying"
    steps.append(("Checking the building against what you asked for", verify))

    def look():
        shot = _preview(bridge, state)
        state["preview"] = shot
        problems = _picture_problems(shot)
        if problems:   # usually the framing: re-aim the camera once and look again
            _run_stage(bridge, state["plan"], "lighting")
            shot = _preview(bridge, state)
            state["preview"] = shot
            problems = _picture_problems(shot)
        if problems:
            raise RuntimeError(f"I built it, but the preview picture isn't right: {'; '.join(problems)}. It's at "
                               f"{shot['path']}.")
        return _final_report(state)
    look.state = "verifying"
    steps.append(("Rendering a preview and checking it", look))
    return steps


def _existing_origin(bridge, name):
    found = _json(bridge.run(f"o = bpy.data.objects.get({name!r})\nimport json\n"
                             "RESULT = json.dumps(json.loads(o['jarvis_plan'])['origin'] if o and o.get('jarvis_plan') "
                             "else [0, 0])", timeout=15), "reading the earlier build")
    return tuple(found)


_REMOVE = ("for o in [o for o in bpy.data.objects if o.get('jarvis_build') == {build!r}]:\n"
           "    bpy.data.objects.remove(o, do_unlink=True)")


def _run_stage(bridge, p, stage):
    return _json(_kit(bridge, f"RESULT = json.dumps(arch_{stage}(json.loads({json.dumps(p)!r})))", timeout=120),
                 f"working on the {stage}")


def _stage_action(bridge, state, stage):
    def action():
        made = _run_stage(bridge, state["plan"], stage)
        if stage == "structure":   # the critical stage: check it right away, before building on top of it
            facts = _inspect(bridge, state["plan"])
            failed = [f for f in unmet(state["reqs"], facts) if f[0] in ("volumes", "floors", "grounded")]
            if failed:
                _run_stage(bridge, state["plan"], stage)   # once more: a stage re-run replaces its own parts
                facts = _inspect(bridge, state["plan"])
                failed = [f for f in unmet(state["reqs"], facts) if f[0] in ("volumes", "floors", "grounded")]
                if failed:
                    raise RuntimeError("The walls didn't come out right: " + "; ".join(f[3] for f in failed))
        return f"{made.get('parts', 0)} parts for the {stage}."
    action.state = "acting"
    return action


def _inspect(bridge, p):
    return _json(_kit(bridge, f"RESULT = json.dumps(inspect_build({p['build']!r}))", timeout=60),
                 "checking the building")


_PREVIEW = r"""import os, time
blend = bpy.data.filepath
home = os.path.join(os.path.expanduser('~'), 'Documents', 'Jarvis renders')
folder = os.path.join(os.path.dirname(blend), 'renders') if blend else home
RESULT = json.dumps(preview(os.path.join(folder, BUILD + time.strftime(' preview %Y-%m-%d %H-%M-%S') + '.png')))"""


def _preview(bridge, state):
    return _json(_kit(bridge, f"BUILD = {state['name']!r}\n" + _PREVIEW, timeout=180), "rendering a preview")


def _picture_problems(shot) -> list:
    """What's wrong with a preview, measured from its pixels: empty, black, washed out, or nothing in it."""
    out = []
    if shot["flat"]:
        out.append("it is one flat colour")
    if shot["brightness"] < 0.06:
        out.append(f"it is almost black (brightness {shot['brightness']:.0%})")
    if shot["brightness"] > 0.95:
        out.append(f"it is washed out (brightness {shot['brightness']:.0%})")
    if shot["subject"] < 0.12:
        out.append(f"the building fills only {shot['subject']:.0%} of it")
    return out


def _partial_report(state) -> str:
    built = describe(state["spec"], state["plan"])
    missing = "; ".join(f"{what} ({problem})" for _, what, _, problem in state["failed"][:5])
    return (f"I built {built}, but it isn't finished: after {REPAIR_ROUNDS} rounds of repairs these checks still "
            f"fail in Blender: {missing}.")


def _final_report(state) -> str:
    spec, p, facts, shot = state["spec"], state["plan"], state["facts"], state["preview"]
    w, d, h = facts["size"]
    if state.get("adding"):
        return (f"Done — I added a {state['adding']} to the {state['name'].lower()}, keeping everything else as it was. "
                f"I checked it in Blender: all {len(state['reqs'])} requirements hold, the new {state['adding']} "
                f"included. Preview: {shot['path']}.")
    text = (f"Done — I built {describe(spec, p)}: {facts['parts']} parts, about {w:.0f} by {d:.0f} metres and "
            f"{h:.0f} m tall. I checked it in Blender: all {len(state['reqs'])} requirements hold (walls, floors, roof "
            f"on every part, windows and doors in their openings, nothing floating, materials, sun and camera). "
            f"Preview: {shot['path']}.")
    if state.get("removed"):
        text += (" I removed Blender's untouched starting cube" +
                 (" and lamp" if "Light" in state["removed"] else "") + " first.")
    if spec["not_built"]:
        text += f" I didn't model: {', '.join(spec['not_built'][:4])}."
    if "balcony" in spec["features"] and spec["storeys"] < 2:
        text += " A single-storey house has nowhere for a balcony, so there isn't one."
    return text


# ---------- for the free-form AI's own work (BlenderComputerTask) ----------
_PART_COUNTS = {"table": 5, "chair": 6, "snowman": 3, "car": 6, "truck": 6, "castle": 8, "tower": 3, "tree": 2,
                "lamp post": 3, "street lamp": 3, "desk": 5, "bed": 4, "sofa": 4, "couch": 4, "bench": 3, "robot": 6,
                "rocket": 4, "boat": 3, "bridge": 4, "fence": 4, "house": 8, "building": 6, "village": 10, "city": 12,
                "room": 5, "kitchen": 6, "bookshelf": 4, "shelf": 3, "temple": 6, "airplane": 4, "windmill": 4,
                "lighthouse": 3, "train": 5, "villa": 10, "mansion": 12, "cottage": 6, "cabin": 6, "bungalow": 8}


def min_new_parts(goal: str) -> int:
    """How many new objects a free-form "build X" request must at least leave in the scene before "done" can be
    believed: a table is more than one box. 0 when the goal isn't about making something new."""
    g = (goal or "").lower()
    if not re.search(r"\b(?:build|create|make|model|add|design|construct|put|place|generate)\b", g):
        return 0
    # Only something introduced as new ("a table", "two chairs"): "make the table red" edits one that exists. And only
    # as the thing itself, not as a word describing another ("a table leg", "a house plant" are one part each).
    # Between the article and the thing, only describing words: "a house plant on the desk" never reaches "desk".
    describing = r"(?:(?!(?:the|on|of|in|to|at|with|from|onto|into|for|and|or|my|its|it)\b)[\w'-]+[ ,]+){0,4}"
    counts = [n for word, n in _PART_COUNTS.items()
              if re.search(rf"\b(?:a|an|another|some|new|one|two|three|four|five|\d+)\s+{describing}{word}s?\b"
                           rf"(?=\s*(?:$|[,.;:!?]|(?:with|and|or|on|in|out|of|for|that|which|next|near|by|made|from|"
                           rf"to|at|please|then|using|under|beside|behind)\b))", g)]
    return max(counts, default=0)


_BUILDING = re.compile(r"\b(?:" + "|".join(BUILD_NOUNS) + r"|building)s?\b", re.I)
_BUILDING_PARTS = {"wall": r"wall|facade", "roof": r"roof", "door": r"door|entrance", "window": r"window|glass|glazing"}


def missing_features(goal: str, new_names) -> list:
    """For a free-form request to build a building: which of its essential parts (walls, roof, door, windows) no
    new object is named for. [] for anything that isn't a building request."""
    g = goal or ""
    if not (_BUILDING.search(g) and re.search(r"\b(?:build|create|make|model|design|construct|generate)\b", g, re.I)):
        return []
    names = " ".join(new_names).lower()
    return [part for part, words in _BUILDING_PARTS.items() if not re.search(words, names)]
