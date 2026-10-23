"""Changing what is already in Blender: "move the pool more to the side and add a path", "make the pool better",
"widen the path", "delete the garden", "add a garage to the villa", "delete everything in Blender".

Why this exists: once a villa was built, every follow-up either matched nothing (and went to the free-form AI, whose
small local model wrote broken bpy for minutes and said "Okay"), or matched the build pattern again and rebuilt the
whole villa. Here a follow-up is read as an edit of what is there:

  intent     each clause becomes one operation — move, connect (a path), improve, resize, remove, clear, extend
             (add a pool/garden/garage to a building), paint — of a target the user names ("the pool", "it")
  scene      the target is found in the real scene by blender_scene.py's features(): the pool is its rim, water,
             basin and deck together; "it" is whatever the last edit or build worked on (session.blender_feature)
  execution  blender_scene.py's edit operations (move_feature, connect, improve_feature...), which work on the
             existing objects and write the change into the build's plan, so nothing is regenerated
  checking   every operation is measured afterwards — the same objects moved by the amount said and stand clear of
             everything; a path is ray-cast along its length and touches both ends; an improved feature still has
             every part it had — and a failed check is reported as a failure, never as done

Anything that isn't one of these operations returns None and goes on to the older one-object commands or the AI.
"""
import json
import re
import time

import blender_build
import blender_control

_FEATURE_NOUN = (r"(?:swimming pools?|pool decks?|pools?|paths?|walkways?|pathways?|footpaths?|trails?|houses?|villas?|"
                 r"homes?|buildings?|mansions?|cottages?|cabins?|bungalows?|gardens?|trees?|hedges?|shrubs|flowers|"
                 r"terraces?|patios?|balcon(?:y|ies)|garages?|decks?|entrance|front steps|driveway|lawn|grass|water)")
_PRONOUN = r"(?:it|that|this|them|those|these|that one|this one)"
_SCENE_WORDS = r"(?:everything|all of it|it all|the (?:whole |entire )?(?:scene|thing|project|place|property|design)|" \
               r"(?:the )?whole (?:villa|house|home|building|mansion|cottage)|(?:the )?entire (?:villa|house|home|" \
               r"building|mansion|cottage))"
_DESCRIBING = r"(?:(?!(?:and|then|to|from|with|by|of|in|on|at|for|more|further|farther|a|an)\b)[\w'-]+\s+){0,3}"
_TARGET = rf"(?:(?:the|my|this|that|our|your)\s+)?(?:{_DESCRIBING}{_FEATURE_NOUN}\b(?:\s+(?:area|itself))?|{_PRONOUN})"
# A target that says which one, where nothing else follows it: "the path between the garden and the pool".
_WHICH = (rf"{_TARGET}(?:\s+(?:between|to|from|leading to|that goes to|going to|by|near|next to|in front of|behind|"
          rf"of|around|beside)\s+(?:the |my )?[\w ]+?)?")
_PLEASE = r"^(?:please |can you |could you |would you |will you |now |also |i want you to |i'd like you to |let's |go ahead and )*"
_TAIL = re.compile(r"\s+(?:please|for me|a bit|a little|now|again|too|as well|in the scene|in blender)$", re.I)

_PATH_NOUN = (r"(?:(?:stone|paved|garden|little|small|short|wide|wider|narrow|nice|new|nice little|straight|proper|"
              r"real|curved|gravel|brick)\s+)*(?:path|walkway|pathway|footpath|walk|trail|sidewalk|paving)")
_CONNECT_ADD = re.compile(_PLEASE + r"(?:add|create|build|make|lay(?: down)?|draw|put(?: in)?|place|give (?:it|me|us)|"
                          r"construct|pave|i want|i'd like|we need)\s+(?:a |an |another |one more |some )"
                          rf"(?P<noun>{_PATH_NOUN})s?\b(?P<rest>.*)$", re.I)
_CONNECT = re.compile(_PLEASE + rf"(?:connect|link|join)\s+(?P<a>.+?)\s+(?:and|to|with)\s+(?P<b>.+?)"
                      rf"(?:\s+(?:with|by|using|via)\s+(?:a |an )?{_PATH_NOUN})?$", re.I)
_MOVE = re.compile(_PLEASE + rf"(?:move|shift|push|slide|put|place|relocate|reposition|bring|set)\s+(?P<target>{_TARGET})"
                   r"(?P<how>(?:\s+.*)?)$", re.I)
_BETTER = (r"(?:better|nicer|prettier|more beautiful|beautiful|gorgeous|more realistic|realistic|more detailed|detailed|"
           r"more attractive|attractive|fancier|fancy|more luxurious|luxurious|more elegant|elegant|more modern|cooler|"
           r"good|great|amazing|awesome|stunning|lovely|more interesting|higher quality|of higher quality|"
           r"more professional|professional|more polished|polished|more impressive|impressive)")
_IMPROVE_VERB = re.compile(_PLEASE + r"(?:improve|enhance|upgrade|refine|polish|beautify|prettify|perfect|"
                           r"spruce up|dress up|fix up|touch up|level up|rework|redesign|redo)\s+"
                           rf"(?P<target>{_WHICH}|{_SCENE_WORDS})(?:\s+(?:more|further|even more|a lot))?$", re.I)
_IMPROVE_QUALITY = re.compile(_PLEASE + r"(?:improve|raise|increase|up) the (?:quality|look|design)"
                              rf"(?:\s+of\s+(?P<target>{_TARGET}|{_SCENE_WORDS}))?$", re.I)
_MAKE_BETTER = re.compile(_PLEASE + rf"make\s+(?P<target>{_WHICH}|{_SCENE_WORDS})\s+(?:look\s+)?"
                          r"(?:(?:a (?:bit|lot|little)|much|way|even|far|more|so|really|very|a lot|super)\s+)*"
                          rf"(?:look\s+)?{_BETTER}(?:\s+looking)?(?:\s+than (?:before|now|it is))?$", re.I)
# Any object the user named ("the shed", "my fountain"), for what only this module does with it (improve, connect,
# move to the side / away / closer): the older one-object commands keep everything else.
_ANY = r"(?:the|my|this|that|our)\s+[\w'-]+(?:\s+[\w'-]+){0,2}?"
_IMPROVE_ANY = re.compile(_PLEASE + r"(?:improve|enhance|upgrade|refine|polish|beautify|prettify|perfect|spruce up|"
                          rf"dress up|fix up|touch up)\s+(?P<target>{_ANY})$", re.I)
_MAKE_BETTER_ANY = re.compile(_PLEASE + rf"make\s+(?P<target>{_ANY})\s+(?:look\s+)?"
                              r"(?:(?:a (?:bit|lot|little)|much|way|even|far|more|so|really|very|a lot|super)\s+)*"
                              rf"(?:look\s+)?{_BETTER}(?:\s+looking)?$", re.I)
_MOVE_ANY = re.compile(_PLEASE + rf"(?:move|shift|push|slide|put|place|relocate|reposition)\s+(?P<target>{_ANY})"
                       r"(?P<how>\s+(?:(?:a bit|a little|a lot|much|even|more|slightly|\d+(?:\.\d+)?\s*m)\s+)*"
                       r"(?:to the side|aside|sideways|further away|farther away|further|farther|away|closer|nearer|"
                       r"behind|in front|to the front|to the back).*)$", re.I)
_NEEDS_BETTER = re.compile(rf"^(?P<target>{_TARGET}|{_SCENE_WORDS})\s+(?:needs|need|could|should|has)\s+(?:to\s+)?"
                           rf"(?:look|be)\s+(?:(?:a (?:bit|lot|little)|much|way|more)\s+)*{_BETTER}$", re.I)
_RESIZE = re.compile(_PLEASE + rf"(?:make|scale|resize)\s+(?P<target>{_WHICH})\s+"
                     r"(?P<amount>(?:(?:a (?:bit|little|lot)|much|even|slightly|way|twice as|two times|three times)\s+)*)"
                     r"(?P<how>bigger|larger|smaller|wider|narrower|longer|shorter|broader|thinner|wide|big|large)"
                     r"(?:\s+than (?:before|now|it is))?$", re.I)
_RESIZE_VERB = re.compile(_PLEASE + r"(?P<verb>widen|enlarge|shrink|narrow|lengthen|expand|broaden)\s+"
                          rf"(?P<target>{_WHICH})(?P<amount>(?:\s+(?:a (?:bit|little|lot)|slightly|a lot))*)$", re.I)
_REMOVE = re.compile(_PLEASE + r"(?:delete|remove|get rid of|take away|take out|erase|drop)\s+"
                     rf"(?P<target>{_WHICH})(?:\s+(?:from (?:the scene|blender)|completely|entirely))?$", re.I)
_CLEAR = re.compile(_PLEASE + r"(?:(?:delete|remove|clear|erase|wipe|get rid of|empty|reset|clean)\s+(?:out\s+)?"
                    r"(?:everything|all(?: the)?(?: objects| things| of it| stuff)?|it all|the (?:whole |entire )?scene|"
                    r"blender|the blender scene|the whole thing)(?:\s+(?:in|from|out of|on)\s+(?:the )?"
                    r"(?:scene|blender))?|start (?:over|again|from scratch)|clear the scene)$", re.I)
_EXTEND = re.compile(_PLEASE + r"(?:add|put|build|create|give (?:it|the \w+)|i want|make|include)\s+(?:a |an |some |a new )?"
                     r"(?P<what>swimming pool|pool|garden|trees|terrace|patio|balcony|garage|carport)"
                     r"(?:\s+(?:to|for|next to|beside|by|near|behind|in front of|on|at|around)\s+(?P<target>.+))?$", re.I)
_PAINT = re.compile(_PLEASE + rf"(?:make|paint|colou?r|turn|change)\s+(?P<target>{_TARGET})\s+(?:to\s+|into\s+)?"
                    r"(?:the colou?r\s+)?(?P<look>.+)$", re.I)
_EXTENSION_NAMES = {"swimming pool": "pool", "trees": "garden", "patio": "terrace", "carport": "garage"}
_SURFACES = {"wood": dict(color=(0.42, 0.27, 0.15), roughness=0.6), "wooden": dict(color=(0.42, 0.27, 0.15), roughness=0.6),
             "stone": dict(color=(0.62, 0.6, 0.55), roughness=0.85), "marble": dict(color=(0.9, 0.89, 0.86), roughness=0.2),
             "concrete": dict(color=(0.55, 0.55, 0.53), roughness=0.9), "brick": dict(color=(0.5, 0.2, 0.12), roughness=0.85),
             "tiled": dict(color=(0.5, 0.76, 0.8), roughness=0.25), "plaster": dict(color=(0.93, 0.91, 0.87), roughness=0.75)}

_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "ten": 10,
                 "a": 1, "an": 1, "half a": 0.5}
_DISTANCE = re.compile(r"\b(?P<n>\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|ten|half a|an?)\s*"
                       r"(?P<u>m|metres?|meters?|ft|feet|foot)\b", re.I)


class EditSteps(blender_build.BuildSteps):
    """Edits of the scene, run like a build: shown step by step, stoppable, each step checked in Blender."""


# ---------- what was said ----------

def _clean(text: str) -> str:
    t = " ".join((text or "").lower().replace("’", "'").split()).strip(" .!?,")
    while True:
        shorter = _TAIL.sub("", t)
        if shorter == t:
            return t
        t = shorter


def _target_text(t):
    return " ".join((t or "").split()) or None


def _how(text: str):
    """(how, distance, ref) from what follows "move the pool": "more to the side", "5 m left", "away from the
    house", "closer to the villa", "behind the house"."""
    t = f" {text.lower()} "
    distance = None
    m = _DISTANCE.search(t)
    if m:
        n = m.group("n").lower()
        value = float(_NUMBER_WORDS.get(n, n) if not n.replace(".", "").isdigit() else n)
        distance = value * (0.3048 if m.group("u").lower() in ("ft", "feet", "foot") else 1.0)
    elif re.search(r"\b(?:a bit|a little|slightly|a touch)\b", t):
        distance = 2.0
    elif re.search(r"\b(?:a lot|much|far|way)\b", t):
        distance = 8.0
    ref = None
    r = re.search(rf"\b(?:from|to|towards?|of|than|beside|next to|near)\s+(?P<ref>(?:the |my )?{_DESCRIBING}{_FEATURE_NOUN})\b", t) \
        or re.search(r"\b(?:from|to|towards?|than|beside|next to|near)\s+(?P<ref>(?:the|my) (?!side\b|left\b|right\b|"
                     r"front\b|back\b)[\w'-]+(?: [\w'-]+)?)\s*$", t)   # any object named at the end: "from the shed"
    if r:
        ref = r.group("ref").strip()
    if re.search(r"\b(?:left)\b", t):
        how = "left"
    elif re.search(r"\b(?:right)\b", t):
        how = "right"
    elif re.search(r"\bbehind\b|\bto the back\b|\bat the back\b", t):
        how = "behind"   # the far side of the building (its front faces -y)
    elif re.search(r"\bbackwards?\b|\bback\b", t) and not re.search(r"\bback (?:to|from)\b", t):
        how = "back"
    elif re.search(r"\bforwards?\b", t):
        how = "forward"
    elif re.search(r"\bin front\b|\bto the front\b", t):
        how = "front"
    elif re.search(r"\bside\b|\baside\b|\bsideways\b", t):
        how = "side"
    elif re.search(r"\b(?:closer|nearer|towards?|next to|beside|near)\b", t):
        how = "closer"
    elif re.search(r"\b(?:away|further|farther|apart)\b", t):
        how = "away"
    else:
        how = "side"   # "move the pool" / "move the pool more": sideways, away from the building
    return how, distance, ref


def _path_ends(rest: str):
    """(a, b) for what follows "add a path": "from the villa to the pool", "between the pool and the house",
    "to the pool", "leading to the garden from the house", "" (both left to the scene)."""
    r = " " + (rest or "").lower().strip() + " "
    r = re.sub(r"\b(?:that |which )?(?:leads?|leading|goes|going|runs?|running|connecting|linking|joining)\b", " ", r)
    m = re.search(r"\bbetween\s+(?P<a>.+?)\s+(?:and|to)\s+(?P<b>.+?)\s*$", r)
    if m:
        return _target_text(m.group("a")), _target_text(m.group("b"))
    m = re.search(r"\b(?:connect|link|join)\w*\s+(?P<a>.+?)\s+(?:and|to|with)\s+(?P<b>.+?)\s*$", r)
    if m:
        return _target_text(m.group("a")), _target_text(m.group("b"))
    a = re.search(r"\bfrom\s+(?P<x>.+?)(?=\s+(?:to|towards?|into|up to|all the way to)\b|\s*$)", r)
    b = re.search(r"\b(?:to|towards?|into|up to|for)\s+(?P<x>.+?)(?=\s+from\b|\s*$)", r)
    return (_target_text(a.group("x")) if a else None), (_target_text(b.group("x")) if b else None)


def _path_width(noun: str, rest: str):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|metres?|meters?)\s+wide", rest or "", re.I)
    if m:
        return max(0.5, min(4.0, float(m.group(1))))
    if re.search(r"\b(?:wide|wider)\b", noun):
        return 1.8
    if re.search(r"\b(?:narrow|little|small)\b", noun):
        return 0.9
    return 1.2


def _paint_values(look: str):
    """What "white", "shiny metal", "wooden", "light blue stone" sets on a material, or None."""
    import blender_commands
    look = look.strip().lower()
    words = look.split()
    if look in blender_commands._COLORS:
        return {"color": blender_commands._COLORS[look]}
    if all(w in _SURFACES or w in blender_commands._COLORS for w in words) and any(w in _SURFACES for w in words):
        values = {}
        for w in words:
            values.update(_SURFACES.get(w, {}))
        color = next((blender_commands._COLORS[w] for w in words if w in blender_commands._COLORS), None)
        if color:
            values["color"] = color
        return values
    parsed = blender_commands._parse_material(f"make it {look}")
    return parsed[1] if parsed else None


def parse_clause(text: str):
    """One operation for one clause, or None when it isn't an edit this module does. Pure text: nothing in Blender
    is looked at (routing uses this before Blender is reached)."""
    t = _clean(text)
    if not t:
        return None
    if _CLEAR.match(t):
        return {"op": "clear"}
    m = _CONNECT_ADD.match(t)
    if m:
        a, b = _path_ends(m.group("rest"))
        return {"op": "connect", "a": a, "b": b, "width": _path_width(m.group("noun"), m.group("rest"))}
    m = _CONNECT.match(t)
    if m and (re.search(_FEATURE_NOUN, m.group("a")) or re.search(_FEATURE_NOUN, m.group("b")) or
              re.search(r"\b(?:path|walkway|pathway|footpath)\b", t)):
        return {"op": "connect", "a": _target_text(m.group("a")), "b": _target_text(m.group("b")), "width": 1.2}
    for pattern in (_IMPROVE_VERB, _MAKE_BETTER, _NEEDS_BETTER, _IMPROVE_QUALITY, _IMPROVE_ANY, _MAKE_BETTER_ANY):
        m = pattern.match(t)
        if m:
            target = _target_text(m.group("target"))
            if target is None or re.fullmatch(_SCENE_WORDS, target):
                whole = re.search(rf"\b{_FEATURE_NOUN}\b", target or "")
                return {"op": "improve", "target": whole.group(0) if whole else None, "whole": True}
            return {"op": "improve", "target": target, "whole": False}
    m = _EXTEND.match(t)
    if m and not re.search(r"\bpath|walkway", t):
        what = m.group("what").lower()
        return {"op": "extend", "what": _EXTENSION_NAMES.get(what, what), "target": _target_text(m.group("target"))}
    m = _RESIZE.match(t)
    if m:
        how, amount = m.group("how").lower(), (m.group("amount") or "").lower()
        return {"op": "resize", "target": _target_text(m.group("target")), **_resize_factor(how, amount)}
    m = _RESIZE_VERB.match(t)
    if m:
        verb = {"widen": "wider", "broaden": "wider", "enlarge": "bigger", "expand": "bigger", "shrink": "smaller",
                "narrow": "narrower", "lengthen": "longer"}[m.group("verb").lower()]
        return {"op": "resize", "target": _target_text(m.group("target")),
                **_resize_factor(verb, (m.group("amount") or "").lower())}
    m = _REMOVE.match(t)
    if m:
        return {"op": "remove", "target": _target_text(m.group("target"))}
    m = _MOVE.match(t) or _MOVE_ANY.match(t)
    if m:
        how, distance, ref = _how(m.group("how") or "")
        if re.match(r"\s*(?:on|onto|on top of|in|into|inside)\b", m.group("how") or ""):
            return None   # "put the ball on the table": the older placing commands
        return {"op": "move", "target": _target_text(m.group("target")), "how": how, "distance": distance, "ref": ref}
    m = _PAINT.match(t)
    if m:
        values = _paint_values(m.group("look"))
        if values:
            return {"op": "paint", "target": _target_text(m.group("target")), "values": values,
                    "said": m.group("look").strip()}
    return None


def _resize_factor(how, amount):
    grow = how in ("bigger", "larger", "wider", "longer", "broader", "wide", "big", "large")
    factor = 1.3
    if re.search(r"\b(?:a bit|a little|slightly)\b", amount):
        factor = 1.15
    elif re.search(r"\b(?:a lot|much|way)\b", amount):
        factor = 1.6
    elif re.search(r"\b(?:twice as|two times)\b", amount):
        factor = 2.0
    elif "three times" in amount:
        factor = 3.0
    axes = {"wider": "w", "broader": "w", "wide": "w", "narrower": "w", "thinner": "w", "longer": "l",
            "shorter": "l"}.get(how, "xy")
    return {"factor": factor if grow else 1 / factor, "axes": axes, "how": how}


def _is_pronoun(target):
    return bool(target and re.fullmatch(_PRONOUN, target.strip()))


def _clauses(text: str):
    """The clauses of a sentence, with a bare noun phrase ("the villa" in "a path between the pool and the villa")
    joined back to the clause before it."""
    import blender_commands
    parts = blender_commands._clauses(text)
    out = []
    for part in parts:
        if out and re.fullmatch(rf"(?:the |my |a |an )?{_DESCRIBING}{_FEATURE_NOUN}", part.strip().lower()):
            out[-1] += " and " + part
        else:
            out.append(part)
    return out


def parse(text: str):
    """[operation] for a sentence made only of edits, or None. Tried clause by clause, then as one sentence."""
    t = _clean(text)
    parts = _clauses(t)
    if len(parts) > 1:
        ops = [parse_clause(p) for p in parts]
        if all(ops):
            return ops
    op = parse_clause(t)
    return [op] if op else None


def is_edit(text: str) -> bool:
    """Routing: whether `text` is an edit of features (or of "it", when it's an operation only this module does)."""
    ops = parse(text)
    if not ops:
        return False
    return all(op["op"] in ("clear", "connect", "improve", "extend") or not _is_pronoun(op.get("target")) or
               (op["op"] == "move" and op["how"] in ("side", "away", "closer")) for op in ops)


# ---------- doing it, and checking it ----------

def _kit(bridge, code, doing, timeout=90):
    response = bridge.run(blender_control.with_kit(code), timeout=timeout)
    if response.get("busy"):
        raise RuntimeError(f"Blender is still busy {doing}; it will finish on its own. Ask me to check the scene in a "
                           "moment.")
    if not response.get("ok"):
        lines = (response.get("error") or "").strip().splitlines()
        last = lines[-1] if lines else "unknown error"
        said = re.match(r"^(?:ValueError|RuntimeError|KeyError): (.+)$", last)
        if said:   # the kit's own words: say them as they are
            text = said.group(1).strip("'\"")
            raise RuntimeError(text[:1].upper() + text[1:] + ".")
        raise RuntimeError(f"Blender reported an error while {doing}: {last}")
    return json.loads(response.get("output") or "null")


def _call(bridge, call, doing, timeout=90):
    return _kit(bridge, f"RESULT = json.dumps({call})", doing, timeout)


def _features(bridge):
    return {f["id"]: f for f in _call(bridge, "features()", "looking at the scene")}


def _resolve(target, session):
    """What to send the kit for a target: a pronoun becomes the feature the last edit or build worked on."""
    if _is_pronoun(target):
        focus = getattr(session, "blender_feature", None) if session is not None else None
        if not focus:
            raise RuntimeError(f"I'm not sure what “{target}” means here — say which part, like “the pool”.")
        return focus
    return target


def _focus(session, fid):
    if session is not None:
        session.blender_feature = fid
        session.blender_focus = None   # "it" now means this feature, not an object an older command touched


def _name(features, fid):
    return features[fid]["name"] if fid in features else fid.split("/", 1)[-1]


def _round(x):
    return f"{x:.1f}".rstrip("0").rstrip(".")


_WAY_WORDS = {"left": "to the left", "right": "to the right", "forward": "forward", "back": "back",
              "behind": "towards the back", "front": "towards the front", "side": "to the side", "away": "further away",
              "closer": "closer"}


def _verify_unmoved(before, after, skip):
    """Solid features that changed although nothing was meant to touch them."""
    changed = []
    for fid, f in before.items():
        if fid in skip or f["kind"] in ("path", "ground", "sun", "camera"):
            continue
        g = after.get(fid)
        if g is None or any(abs(a - b) > 0.01 for a, b in zip(f["lo"] + f["hi"], g["lo"] + g["hi"])):
            changed.append(f["name"])
    return changed


def _check_paths(bridge, names, doing):
    """Every path re-laid for an edit, checked as a new one is; the problems, in words."""
    problems = []
    for name in names:
        check = _call(bridge, f"check_path({name!r})", doing)
        if not check["ok"]:
            a, b = (check["between"] or ["?", "?"])[:2]
            problems.append(f"the path between the {a} and the {b}: {'; '.join(check['problems'])}")
    return problems


def _move_action(op, session, bridge):
    def action():
        target = _resolve(op["target"], session)
        before = _features(bridge)
        out = _call(bridge, f"move_feature({target!r}, {op['how']!r}, {op['distance']!r}, {op['ref']!r})",
                    "moving it")
        after = _features(bridge)
        fid = out["feature"]
        f0, f1 = before.get(fid), after.get(fid)
        problems = []
        if f1 is None:
            problems.append(f"the {out['name']} isn't in the scene any more")
        else:
            if f0["uids"] != f1["uids"]:
                problems.append(f"the {out['name']} is made of different objects than before")
            moved = [(f1["lo"][i] + f1["hi"][i] - f0["lo"][i] - f0["hi"][i]) / 2 for i in range(2)]
            if out["feature"].endswith("/house"):
                pass   # a whole build: its own paths and garden move with it
            elif any(abs(m - d) > 0.05 for m, d in zip(moved, out["moved"])):
                problems.append(f"it moved by ({_round(moved[0])}, {_round(moved[1])}) m, not as planned")
            clash = _call(bridge, f"clashes_of({fid!r})", "checking around it")
            if clash:
                problems.append(f"it stands in {', '.join(clash[:3])}")
        own = {k for k in before if k == fid or (fid.endswith("/house") and before[k]["build"] == before[fid]["build"])}
        disturbed = _verify_unmoved(before, after, own)
        if disturbed:
            problems.append(f"{', '.join(disturbed[:3])} changed too")
        problems += _check_paths(bridge, out["rerouted"], "checking the path")
        if problems:
            raise RuntimeError(f"I moved the {out['name']}, but {'; '.join(problems)} — so I won't call that done.")
        _focus(session, fid)
        dx, dy = out["moved"]
        if session is not None:
            session.last_undo = {"description": f"moved the {out['name']}", "code": blender_control.with_kit(
                f"RESULT = json.dumps(shift_feature({fid!r}, {-dx!r}, {-dy!r}))")}
        way = _WAY_WORDS.get(op["how"], "")
        if op["how"] in ("away", "closer", "side") and out["ref"]:
            way = {"away": f"further from the {out['ref']}", "closer": f"closer to the {out['ref']}",
                   "side": f"to the side, away from the {out['ref']}"}[op["how"]]
        text = f"Done — I moved the {out['name']} {_round(out['distance'])} m {way}"
        if out["pushed"] and op["how"] != "closer":
            text += f" ({_round(out['pushed'])} m further than {'you said' if op['distance'] else 'usual'}, to keep it clear of what's next to it)"
        if out["gap"] is not None:
            text += f"; it's now {_round(out['gap'])} m from the {out['ref']}"
        text += ". It's the same " + out["name"] + ", whole, standing clear of everything"
        if out["rerouted"]:
            text += ", and I re-laid the path to it, which I checked still joins both ends"
        return text + "."
    return action


def _door_words(door):
    if not door:
        return ""
    d = door.lower()
    if " door front " in d:
        return "'s front door"
    if "glass_door back" in d:
        return "'s glass doors at the back"
    side = next((s for s in ("front", "back", "left", "right") if f" {s} " in d), "")
    return f"'s {side} doors" if side else "'s door"


def _connect_action(op, session, bridge):
    def action():
        a = _resolve(op["a"], session) if op["a"] else None
        b = _resolve(op["b"], session) if op["b"] else None
        if a is None and b is None and session is not None and getattr(session, "blender_feature", None) and \
                not session.blender_feature.endswith("/house"):
            b = session.blender_feature   # "move the pool and add a path": the path goes to the pool
        before = _features(bridge)
        out = _call(bridge, f"connect({a!r}, {b!r}, {op['width']!r})", "laying the path")
        check = _call(bridge, f"check_path({out['feature']!r})", "checking the path")
        if not check["ok"]:   # once more, from the scene as it is now
            out = _call(bridge, f"connect({a!r}, {b!r}, {op['width']!r})", "laying the path again")
            check = _call(bridge, f"check_path({out['feature']!r})", "checking the path")
        if not check["ok"]:
            raise RuntimeError(f"I laid a path between the {out['between'][0]} and the {out['between'][1]}, but it "
                               f"isn't right: {'; '.join(check['problems'])}. I won't call that done.")
        after = _features(bridge)
        disturbed = _verify_unmoved(before, after, set())
        if disturbed:
            raise RuntimeError(f"I laid the path, but {', '.join(disturbed[:3])} changed too — I won't call that done.")
        _focus(session, out["feature"])
        if session is not None:
            session.last_undo = {"description": f"laid the path between the {out['between'][0]} and the "
                                                f"{out['between'][1]}",
                                 "code": blender_control.with_kit(
                                     f"RESULT = json.dumps(remove_feature({out['feature']!r})['removed'])")}
        turns = {0: "straight", 1: "with one turn"}.get(out["turns"], f"with {out['turns']} turns")
        again = "There was already a path between them, so I re-laid it rather than add a second: " \
            if out.get("replaced") else ""
        ends = [f"the {name}" + (_door_words(out["door"]) if i == out.get("door_end") else "")
                for i, name in enumerate(out["between"])]
        return (f"Done — {again}I laid a {_round(out['width'])} m wide path from {ends[0]} to {ends[1]}, "
                f"{_round(out['length'])} m long, {turns}. "
                f"Checked in Blender: it's there all the way ({check['samples']} points along it), it reaches both "
                "ends, and it doesn't run through anything.")
    return action


def _improve_targets(op, session, bridge):
    """The features an improvement is for: the one named, or for "everything" / "the whole villa" every part of
    the building (or every object, in a scene with no building)."""
    if not op.get("whole"):
        return [_resolve(op["target"], session)]
    fs = _features(bridge)
    builds = [f["build"] for f in fs.values() if f["build"]]
    if builds:
        build = builds[-1]
        if op.get("target"):
            named = _call(bridge, f"(feature({op['target']!r}) or {{}}).get('build')", "finding it")
            build = named or build
        order = {"house": 0, "pool": 1, "path": 2, "garden": 3}
        return [fid for fid, f in sorted(fs.items(), key=lambda kv: order.get(kv[1]["kind"], 9))
                if f["build"] == build and f["kind"] in order]
    return [fid for fid, f in fs.items() if f["kind"] == "object"]


def _improve_action(op, session, bridge):
    def action():
        targets = _improve_targets(op, session, bridge)
        if not targets:
            raise RuntimeError("There's nothing in the scene to improve yet.")
        import computer_use
        checkpoint = computer_use.save_blender_checkpoint(bridge)
        done, nothing = [], []
        for target in targets:
            before = _features(bridge)
            out = _call(bridge, f"improve_feature({target!r})", "improving it", timeout=180)
            after = _features(bridge)
            fid = out["feature"]
            if out["lost"]:
                raise RuntimeError(f"I tried to improve the {out['name']}, but {', '.join(out['lost'][:3])} went "
                                   "missing — I won't call that done.")
            kept = before[fid]["uids"]
            changed = {n: u for n, u in after.get(fid, {}).get("uids", {}).items() if n in kept and kept[n] != u}
            if changed and not fid.endswith(("/path", "/garden")) and ":" not in fid:
                raise RuntimeError(f"Improving the {out['name']} replaced {', '.join(list(changed)[:3])} instead of "
                                   "changing them — I won't call that done.")
            if out["changes"]:
                done.append((out["name"], out["changes"]))
                _focus(session, fid)
            else:
                nothing.append(out["name"])
        if not done:
            raise RuntimeError(f"The {' and the '.join(nothing)} already {'has' if len(nothing) == 1 else 'have'} "
                               "everything I know how to add. Tell me what you'd like different — the size, where it "
                               "is, its colours or materials — and I'll change that.")
        if session is not None:
            session.last_undo = {"description": "improved it", "code": (
                f"raise RuntimeError({'I cannot take back an improvement piece by piece; the scene from before it is saved at ' + str(checkpoint)!r})")}
        parts = [f"the {name}: {', '.join(changes)}" for name, changes in done]
        text = "Done — I improved " + "; ".join(parts) + ". It's the same scene, changed in place — every part that " \
                                                          "was there still is"
        if nothing:
            text += f" (the {' and the '.join(nothing)} already had everything I know how to add)"
        return text + "."
    return action


def _resize_action(op, session, bridge):
    def action():
        target = _resolve(op["target"], session)
        axes = op["axes"]
        if axes in ("w", "l"):   # the narrower or the longer side of what it is now
            f = _call(bridge, f"_need({target!r})", "finding it")
            wide_x = (f["hi"][0] - f["lo"][0]) >= (f["hi"][1] - f["lo"][1])
            axes = ("y" if wide_x else "x") if axes == "w" else ("x" if wide_x else "y")
        out = _call(bridge, f"resize_feature({target!r}, {op['factor']!r}, {axes!r})", "resizing it")
        grow = op["factor"] > 1
        if out["feature"].split("/")[-1].startswith("path"):
            ok = (out["after"][0] > out["before"][0]) == grow
            what = f"{_round(out['before'][0])} m wide to {_round(out['after'][0])} m"
            problems = _check_paths(bridge, [out["feature"]], "checking the path")
        else:
            idx = [i for i, a in enumerate("xyz") if a in axes]
            ok = all((out["after"][i] > out["before"][i]) == grow for i in idx)
            what = (f"{_round(out['before'][0])} x {_round(out['before'][1])} m to "
                    f"{_round(out['after'][0])} x {_round(out['after'][1])} m")
            problems = _check_paths(bridge, out.get("rerouted", []), "checking the path")
            clash = _call(bridge, f"clashes_of({out['feature']!r})", "checking around it")
            if clash:
                problems.append(f"it stands in {', '.join(clash[:3])}")
        if not ok or problems:
            raise RuntimeError(f"I resized the {out['name']}, but {'; '.join(problems) or 'its size did not change that way'}"
                               " — I won't call that done.")
        _focus(session, out["feature"])
        text = f"Done — the {out['name']} went from {what}"
        if out.get("moved"):
            text += f", and I moved it {_round(out['moved']['distance'])} m away so it stays clear of the {out['moved']['ref']}"
        if out.get("rerouted"):
            text += "; the path to it was re-laid and still joins both ends"
        return text + "."
    return action


def _remove_action(op, session, bridge):
    def action():
        target = _resolve(op["target"], session)
        out = _call(bridge, f"remove_feature({target!r})", "removing it")
        if out["still"]:
            raise RuntimeError(f"I tried to remove it, but {', '.join(out['still'][:3])} is still in the scene.")
        what = target if not _is_pronoun(op["target"]) else "it"
        what = what if what.startswith(("the ", "it")) else "the " + what
        if session is not None:
            session.last_undo = {"description": f"removed {what}", "code": blender_control.with_kit(
                f"RESULT = json.dumps(bring_back(json.loads({json.dumps(out['homes'])!r}), {out['build']!r}, "
                f"{out['plan_before']!r}))")}
            session.blender_feature = None
        paths = [n for n in out["removed"] if " path " in n.lower() or n.lower().startswith("path ")]
        n = len(out["removed"])
        text = f"Done — I removed {what} ({n} object{'s' if n != 1 else ''})"
        if paths and "path" not in what:
            text += ", and the path that led to it"
        return text + ". Say “undo” to bring it back."
    return action


def _clear_action(session, bridge):
    def action():
        fs = _features(bridge)
        trivial = {f["id"] for f in fs.values()} <= {"Cube", "Light", "Camera"}
        if fs and not trivial:
            confirm = getattr(session, "confirm", None) if session is not None else None
            names = ", ".join(sorted({f["name"] for f in fs.values() if f["kind"] not in ("sun", "camera")}))[:160]
            if confirm is None or not confirm(f"Delete everything in the Blender scene ({names})? I'll keep a copy "
                                              "of it first."):
                raise RuntimeError("Okay — I left the scene exactly as it was.")
        import computer_use
        checkpoint = computer_use.save_blender_checkpoint(bridge) if fs else None
        out = _call(bridge, "clear_scene()", "clearing the scene")
        left = _features(bridge)
        if out["left"] or left:
            raise RuntimeError(f"I ran the delete, but {', '.join(out['left'][:3] or list(left)[:3])} is still in the "
                               "scene — I won't claim it's empty.")
        if session is not None:
            session.blender_feature = None
            session.blender_objects[:] = []
            session.blender_focus = None
            session.last_undo = {"description": "cleared the scene", "code": (
                f"raise RuntimeError({'I cannot undo clearing the scene here; the scene from before is saved at ' + str(checkpoint)!r})")}
        if not out["removed"]:
            return "The scene was already empty."
        return (f"Done — the scene is empty: I deleted all {out['removed']} objects and checked that none are left."
                + (f" A copy of the scene from before is at {checkpoint}." if checkpoint else ""))
    return action


def _paint_action(op, session, bridge):
    def action():
        target = _resolve(op["target"], session)
        values = {k: (list(v) if isinstance(v, tuple) else v) for k, v in op["values"].items()}
        args = ", ".join(f"{k}={v!r}" for k, v in values.items())
        out = _call(bridge, f"paint_feature({target!r}, {args})", "changing its look")
        wrong = []
        for name, got in out["values"].items():
            want = values.get("color")
            if want and got.get("color") and any(abs(a - b) > 0.02 for a, b in zip(got["color"][:3], want[:3])):
                wrong.append(name)
        if wrong:
            raise RuntimeError(f"I changed it, but {', '.join(wrong)} doesn't show the new colour — I won't call that "
                               "done.")
        _focus(session, out["feature"])
        return f"Done — the {out['name']} is {op['said']} now ({len(out['objects'])} parts, checked in Blender)."
    return action


_PREVIEW = r"""import os, time
scene = bpy.context.scene
cam = scene.camera
if cam is None:
    RESULT = json.dumps(None)
else:
    if cam.get('jarvis_build'):   # Jarvis's own build camera: framed again on what the build is now
        frame([p.name for p in _building_parts(cam['jarvis_build'])], camera=cam, margin=0.06)
    blend = bpy.data.filepath
    home = os.path.join(os.path.expanduser('~'), 'Documents', 'Jarvis renders')
    folder = os.path.join(os.path.dirname(blend), 'renders') if blend else home
    RESULT = json.dumps(preview(os.path.join(folder, time.strftime('Edit preview %Y-%m-%d %H-%M-%S') + '.png')))"""


def _preview_action(bridge, state):
    def action():
        shot = _kit(bridge, _PREVIEW, "rendering a preview", timeout=180)
        if shot is None:
            return ""
        problems = blender_build._picture_problems({**shot, "subject": max(shot["subject"], 0.12)})
        if problems:
            raise RuntimeError(f"The change is made, but the preview picture isn't right: {'; '.join(problems)}. "
                               f"It's at {shot['path']}.")
        state["preview"] = shot["path"]
        return ""
    action.state = "verifying"
    return action


_INTRO = {"move": "moving the {t}", "connect": "laying a path", "improve": "improving the {t}", "resize": "resizing the {t}",
          "remove": "removing the {t}", "clear": "clearing the scene", "extend": "adding a {w}",
          "paint": "changing the {t}'s look"}


def intro_for(text: str, session=None):
    """What Jarvis says as edits start ("On it — moving the pool and laying a path..."), from the words alone; None
    when `text` isn't edits (or, with `session`, isn't edits this module would take — see steps_for)."""
    ops = parse(text)
    if not ops or (session is not None and _for_older_commands(ops, session)):
        return None
    return f"On it — {' and '.join(_said(op) for op in ops)}. I'll check each change in Blender before I say it's done."


def _for_older_commands(ops, session):
    """"move it left" after "create a cube": "it" is an object the older one-object commands made, not a feature."""
    return (any(_is_pronoun(op.get("target")) for op in ops) and not getattr(session, "blender_feature", None) and
            not all(op["op"] in ("improve", "connect", "clear", "extend") for op in ops))


def _said(op):
    t = (op.get("target") or "scene").removeprefix("the ")
    return _INTRO[op["op"]].format(t=t, w=op.get("what", "")).replace("the it", "it")


def steps_for(text: str, session, bridge):
    """EditSteps for a sentence made of edits of what is in the scene, or None."""
    ops = parse(text)
    if not ops or (session is not None and _for_older_commands(ops, session)):
        return None
    steps = EditSteps()
    state = {"results": []}
    said = []

    def recorded(action):
        # A task's summary is its last step's words: every edit's own report is kept for the summing up instead.
        def run():
            try:
                outcome = action()
            except Exception as e:
                if state["results"]:   # what was already done stays said: a later failure doesn't undo it
                    raise RuntimeError(" ".join(state["results"]) + f" But then: {e}") from e
                raise
            if isinstance(outcome, str) and outcome.startswith(("Done", "The scene was already")):
                state["results"].append(outcome)
            return outcome
        run.state = getattr(action, "state", "acting")
        return run

    for op in ops:
        kind = op["op"]
        said.append(_said(op))
        if kind == "extend":
            steps.extend((d, recorded(a)) for d, a in blender_build.extend_steps(op["what"], op.get("target"),
                                                                                 session, bridge))
            continue
        label = said[-1][:1].upper() + said[-1][1:]
        make = {"move": _move_action, "connect": _connect_action, "improve": _improve_action,
                "resize": _resize_action, "remove": _remove_action, "paint": _paint_action}.get(kind)
        steps.append((label, recorded(make(op, session, bridge) if make else _clear_action(session, bridge))))
    if any(op["op"] in ("improve", "connect", "move", "resize") for op in ops):
        steps.append(("Rendering a preview and looking at it", _preview_action(bridge, state)))

    def report():
        text = " ".join(state["results"])
        return text + (f" Preview: {state['preview']}." if state.get("preview") else "")
    report.state = "verifying"
    steps.append(("Summing up", report))
    steps.intro = intro_for(text)
    return steps
