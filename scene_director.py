"""Carrying out a scene plan (scene_plan.py) in Blender, stage by stage, each one checked — for any plan.

  plan      read from the request, or a follow-up's edits of the plan kept in the scene (the "Jarvis Scene" empty)
  stages    environment -> buildings (the villa builder) -> objects -> characters -> lighting -> weather ->
            motion (things travelling, characters acting) -> camera -> preview pictures -> video -> saved project;
            a follow-up runs only the stages its edits touch
  checks    after each stage, measured in Blender (blender_world.inspect_scene, blender_fx.inspect_motion_paths /
            inspect_camera / subject_coverage / rain_visible, blender_character.inspect_motion), with repairs that
            change the cause (another seed, more clearance, a higher route, another camera angle, more exposure)
            and are checked again; what still fails is reported as failed, never as done

Targets are resolved here from the real scene: "the door" is the build's front door (blender_character.door_facts),
"the chair" a seat with its height and facing, "the table" a surface, "between the skyscrapers" the city's towers.
"""
import json
import math
import os
import re
import subprocess
import sys
import time

import blender_build
import blender_control
import scene_plan

REPAIRS = 2
CHUNK = 24   # frames per render request: Stop is honoured between chunks, and progress is shown


class SceneSteps(blender_build.BuildSteps):
    """A scene plan's stages, run like a build (shown, stoppable). `task` is set by ScriptedTask while running."""
    intro = "On it — I'll build the scene in stages and check each one in Blender. Say “stop” to cancel."
    task = None


class Stopped(Exception):
    pass


def _kit(bridge, code, doing, timeout=300):
    r = bridge.run(blender_control.with_kit(code), timeout=timeout)
    if r.get("busy"):
        raise RuntimeError(f"Blender is still busy {doing}; it will finish on its own.")
    if not r.get("ok"):
        err = (r.get("error") or "").strip().splitlines()
        raise RuntimeError(f"Blender reported an error while {doing}: {err[-1] if err else 'unknown'}")
    out = r.get("output") or "null"
    try:
        return json.loads(out)
    except ValueError:
        return out


def _call(bridge, func, *args, doing="working", timeout=300):
    params = ", ".join(f"json.loads({json.dumps(json.dumps(a))})" for a in args)
    return _kit(bridge, f"import json\nRESULT = json.dumps({func}({params}))", doing, timeout)


# ---------- what to do ----------

def _stored(bridge):
    try:
        plan = _kit(bridge, "import json\nRESULT = json.dumps(scene_plan_get())", "reading the scene's plan", 20)
    except (RuntimeError, AttributeError):
        return None
    # what comes back from Blender is data: only a plan of the right shape counts
    if isinstance(plan, dict) and isinstance(plan.get("tasks"), list) and all(isinstance(t, dict) and "id" in t and
                                                                              "kind" in t for t in plan["tasks"]):
        return plan
    return None


def steps_for(text, session, bridge, ask_ai=None):
    """SceneSteps for `text` (a new scene, more for the scene there, or an edit of it), or None when it isn't a
    scene request."""
    stored = _stored(bridge) if bridge is not None else None
    edits = scene_plan.parse_followup(text, stored) if stored else None
    if edits:
        plan, touched = scene_plan.apply_edits(stored, edits)
        stages = [s for s in scene_plan.STAGE_ORDER if s in touched]
        only = None
        what = ", ".join(e["edit"] for e in edits)
        intro = f"On it — changing the scene ({what}) and redoing only what that touches, then checking it."
    else:
        if not scene_plan.is_scene_request(text, stored):
            return None
        new = scene_plan.parse(text, stored)
        if new.get("unknown") and ask_ai is not None and any(t.get("asset") == "unknown" for t in new["tasks"]):
            pass   # unknown objects are shaped one by one in their stage (_shape_unknown)
        fresh = bool(re.search(r"\b(?:new scene|start over|from scratch|empty scene)\b", text, re.I))
        plan = new if (fresh or not stored) else scene_plan.merge(stored, new)
        only = {t["id"] for t in new["tasks"]} if (stored and not fresh) else None
        stages = list(scene_plan.STAGE_ORDER)
        intro = f"On it — {scene_plan.describe(new) or 'the scene'}. I'll build it in stages and check each one."
    plan = scene_plan.with_defaults(plan)
    if only is not None:   # what was added, plus the defaults it brought and what looks at everything
        only |= {t["id"] for t in plan["tasks"] if t.get("default")} | {t["id"] for t in plan["tasks"] if t["kind"] in (
            "camera", "render", "lighting")}
    steps = SceneSteps()
    steps.intro = intro
    steps.plan = plan
    state = {"plan": plan, "session": session, "bridge": bridge, "stages": stages, "only": only, "facts": {},
             "checks": [], "problems": [], "outputs": {}, "ask_ai": ask_ai, "steps": steps, "text": text}
    _add_steps(steps, state)
    return steps


def _tasks(state, kind):
    return [t for t in state["plan"]["tasks"] if scene_plan.stage_of(t) == kind and (
        state["only"] is None or t["id"] in state["only"] or kind in ("camera", "render", "lighting", "weather"))]


def _add_steps(steps, state):
    bridge = state["bridge"]

    def prepare():
        import computer_use
        state["checkpoint"] = computer_use.save_blender_checkpoint(bridge)
        if state["only"] is None and not any(t["kind"] == "building" for t in state["plan"]["tasks"]):
            _kit(bridge, "BUILD = '__scene__'\n" + blender_build._PREPARE, "looking at the scene", 30)
        _call(bridge, "scene_plan_set", state["plan"], doing="saving the scene's plan")
        return "Planned: " + scene_plan.describe(state["plan"])
    prepare.state = "planning"
    steps.append(("Planning the scene", prepare))
    stages = state["stages"]
    if "environment" in stages and _tasks(state, "environment"):
        steps.append(("Building the environment", _stage(state, _environment)))
    if "building" in stages:
        for t in _tasks(state, "building"):
            _add_building(steps, state, t)
    if "object" in stages and _tasks(state, "object"):
        steps.append(("Placing the objects", _stage(state, _objects)))
    if "character" in stages and _tasks(state, "character"):
        steps.append(("Creating the characters", _stage(state, _characters)))
    if "lighting" in stages:
        steps.append(("Setting the lighting", _stage(state, _lighting)))
    if "weather" in stages:
        steps.append(("Setting the weather", _stage(state, _weather)))
    if "motion" in stages and (_tasks(state, "motion")):
        steps.append(("Animating", _stage(state, _motion)))
    if "camera" in stages:
        steps.append(("Setting up the camera", _stage(state, _camera)))
    if "render" in stages:
        steps.append(("Rendering preview pictures and checking them", _stage(state, _previews, "verifying")))
        if any(t.get("video") for t in _tasks(state, "render")):
            steps.append(("Rendering the video", _stage(state, _video)))
    steps.append(("Saving the project and checking it reopens", _stage(state, _save, "verifying")))


def _stage(state, fn, kind="acting"):
    def action():
        task = state["steps"].task
        if task is not None and task._stop.is_set():
            raise Stopped()
        return fn(state)
    action.state = kind
    return action


def _note(state, what, ok, detail=""):
    state["checks"].append({"what": what, "ok": bool(ok), "detail": detail})
    if not ok:
        state["problems"].append(f"{what}: {detail}" if detail else what)


# ---------- stages ----------

def _environment(state):
    bridge = state["bridge"]
    made = []
    for t in _tasks(state, "environment"):
        if t.get("type") == "room":   # the furniture asked for is the room's to arrange: along walls, table free
            asked = [x for x in state["plan"]["tasks"] if x["kind"] == "object" and not x.get("place") and
                     scene_plan.world_library.RECIPES.get(x.get("asset")) and
                     scene_plan.world_library.recipe(x["asset"]).get("category") == "furniture"]
            if asked:
                t["furniture_for"] = [[x["asset"], x["id"]] for x in asked for _ in range(int(x.get("count") or 1))]
                for x in asked:
                    x["by_env"] = t["id"]
        facts = _call(bridge, "build_environment", t, doing="building the environment", timeout=600)
        check = _call(bridge, "inspect_scene", [t["id"]], doing="checking the environment")
        for _ in range(REPAIRS):
            if not check["clashes"] and not check["floating"]:
                break
            t["seed"] = (t.get("seed") or 11) + 17   # another arrangement of the same place
            facts = _call(bridge, "build_environment", t, doing="rebuilding the environment", timeout=600)
            check = _call(bridge, "inspect_scene", [t["id"]], doing="checking the environment")
        _note(state, f"the {t.get('room') or t['type']}", not check["clashes"] and not check["floating"],
              f"{len(check['clashes'])} overlapping, {len(check['floating'])} floating" if check["clashes"] or
              check["floating"] else f"{facts['objects']} objects")
        made.append(f"{t.get('room') or t['type']} ({facts['objects']} objects)")
    _call(bridge, "scene_plan_set", state["plan"], doing="saving the scene's plan")
    return "Built " + ", ".join(made) + "."


def _add_building(steps, state, t):
    """A building is the villa builder's own staged, checked build, run as part of this scene."""
    words = f"create a {t.get('noun', 'villa')}"
    said = t.get("said") or ""
    for w in ("modern", "classic", "traditional", "pool", "garden", "garage", "terrace", "balcony", "two storey",
              "one storey", "three storey", "big windows", "small", "large"):
        if w in said.lower():
            words += f" {('with a ' + w) if w in ('pool', 'garden', 'garage', 'terrace', 'balcony') else w}"
    build = blender_build.steps_for(words, state["session"], state["bridge"])
    if build is None:
        return
    for description, action in build:
        steps.append((description, action))

    def tag():
        _kit(state["bridge"], "import json\nnames = sorted({o.get('jarvis_build') for o in bpy.data.objects if "
                              "o.get('jarvis_build')})\n"
                              f"root = bpy.data.objects.get(names[-1]) if names else None\n"
                              f"if root is not None:\n    root['jarvis_plan_task'] = {t['id']!r}\n"
                              "RESULT = json.dumps(names)", "noting the build", 20)
        return "Building done."
    tag.state = "acting"
    steps.append(("Fitting the building into the scene", tag))


def _near_for(state, t, facts):
    place = t.get("place")
    if not place:
        return None
    target = place["target"]
    objs = facts["tasks"].get(target.get("task"), []) if target.get("task") else [
        o for objs in facts["tasks"].values() for o in objs if o.get("asset") == target.get("asset")]
    objs = [o for o in objs if o.get("lo")]
    if not objs:
        return None
    o = objs[0]
    if place["rel"] in ("on", "on top of", "onto") and o.get("surface"):
        pad = 0.12
        return {"surface": o["surface"], "rect": [o["lo"][0] + pad, o["lo"][1] + pad, o["hi"][0] - pad, o["hi"][1] - pad]}
    return {"at": [(o["lo"][0] + o["hi"][0]) / 2, (o["lo"][1] + o["hi"][1]) / 2]}


def _implied_objects(state):
    """Things an action needs that weren't asked for: something to sit on, a table for a meal, the food, the cup."""
    plan = state["plan"]
    tasks = plan["tasks"]
    added = []
    have = {t.get("asset") for t in tasks if t["kind"] == "object"}
    facts = state["facts"].get("scene") or {}
    in_env = {o.get("asset") for objs in facts.get("tasks", {}).values() for o in objs}
    n = max(int(re.sub(r"\D", "", t["id"]) or 0) for t in tasks)
    for t in [x for x in tasks if x["kind"] == "action"]:
        for s in t["steps"]:
            need = []
            if s["do"] == "sit" and not ({"chair", "sofa", "bench", "bed"} & (have | in_env)):
                need.append(("chair", None))
            if s["do"] in ("eat", "drink"):
                if not ({"table", "desk", "cabinet"} & (have | in_env)):
                    need.append(("table", None))
                prop = s.get("prop") or ("sandwich" if s["do"] == "eat" else "cup")
                if prop not in have and prop not in in_env:
                    need.append((prop, "table"))
                if any(x["do"] == "sit" for x in t["steps"]) and not ({"chair", "sofa", "bench"} & (have | in_env)):
                    need.append(("chair", "table"))
            if s["do"] in ("pick_up", "carry", "phone") and (s.get("prop") or "box") not in have | in_env:
                need.append((s.get("prop") or "box", None))
            for asset, on in need:
                if asset in have:
                    continue
                n += 1
                nt = {"id": f"t{n}", "kind": "object", "asset": asset, "count": 1, "implied": True}
                if on:
                    tid = next((x["id"] for x in tasks if x.get("asset") == on), None)
                    if tid:
                        nt["place"] = {"rel": "on" if asset not in ("chair",) else "near", "target": {"task": tid}}
                tasks.append(nt)
                have.add(asset)
                added.append(asset)
                if state["only"] is not None:
                    state["only"].add(nt["id"])
    # what a hand takes, said without a place, waits on the table (or desk, counter) when there is one
    surfaces = [x for x in tasks if x["kind"] == "object" and x.get("asset") in ("table", "desk", "cabinet")]
    taken = {s.get("prop") for x in tasks if x["kind"] == "action" for s in x["steps"]}
    for x in tasks:
        if x["kind"] == "object" and x.get("asset") in taken and not x.get("place") and surfaces:
            x["place"] = {"rel": "on", "target": {"task": surfaces[0]["id"]}}
    # a table goes before what stands on it
    tasks.sort(key=lambda x: (scene_plan.STAGE_ORDER.index(scene_plan.stage_of(x)), 1 if x.get("place") else 0))
    return added


def _shape_unknown(state, t):
    """Something no recipe makes ("a dragon"): the local AI describes it in parts (checked), else a plain stand-in."""
    name = t.get("name") or "object"
    ask = state.get("ask_ai")
    parts = None
    if ask is not None:
        prompt = (f"Describe a simple 3D model of {name} as primitive parts. Answer with ONLY JSON: "
                  '{"parts": [{"shape": "box"|"cyl"|"sphere", "size": [x, y, z], "at": [x, y, z], "mat": material}]} '
                  "in metres, 'at' is the centre of the part's bottom, the model stands on z=0 facing -y, 6 to 20 "
                  f"parts. Materials: {', '.join(sorted(scene_plan.world_library.MATERIALS))}.")
        try:
            answer = ask([{"role": "user", "content": prompt}])
            m = re.search(r"\{.*\}", answer or "", re.S)
            data = json.loads(m.group(0)) if m else None
            checked = scene_plan.validate([{"id": "x", "kind": "object", "asset": "composite", "name": name,
                                            "parts": (data or {}).get("parts")}])
            parts = checked[0]["parts"] if checked else None
        except Exception:
            parts = None
    t["asset"] = "composite"
    if parts:
        t["parts"] = parts
        t["shaped_by"] = "ai"
    else:   # honest stand-in: a body and a head, said as such in the report
        t["parts"] = [{"shape": "sphere", "size": [2.0, 4.0, 1.6], "at": [0, 0, 0.4], "mat": "dark_metal"},
                      {"shape": "sphere", "size": [1.0, 1.2, 1.0], "at": [0, -2.2, 1.2], "mat": "dark_metal"}]
        t["shaped_by"] = "stand-in"
        state["problems"].append(f"I have no model of a {name}, and no local AI to shape one: it's a plain stand-in")


def _objects(state):
    bridge = state["bridge"]
    state["facts"]["scene"] = _call(bridge, "scene_facts", doing="reading the scene")
    implied = _implied_objects(state)
    made = []
    for t in _tasks(state, "object"):
        if t.get("by_env"):   # the room arranged it already
            made.append(f"{t.get('count', 1)} {t['asset'].replace('_', ' ')} (arranged with the room)")
            continue
        if t.get("asset") == "unknown":
            _shape_unknown(state, t)
        facts = _call(bridge, "scene_facts", doing="reading the scene")
        out = _call(bridge, "place_objects", t, _near_for(state, t, facts), doing=f"placing the {t['asset']}")
        made.append(f"{len(out['made'])} {t.get('name') or t['asset'].replace('_', ' ')}")
    ids = [t["id"] for t in _tasks(state, "object")]
    check = _call(bridge, "inspect_scene", ids, doing="checking the objects")
    for _ in range(REPAIRS):
        bad = {c[0] for c in check["clashes"]} | {c[1] for c in check["clashes"]} | {f[0] for f in check["floating"]}
        if not bad:
            break
        for t in _tasks(state, "object"):   # put them elsewhere: another free spot
            if t.get("by_env"):
                continue
            t["seed"] = (t.get("seed") or 0) + 1
            facts = _call(bridge, "scene_facts", doing="reading the scene")
            _call(bridge, "place_objects", t, _near_for(state, t, facts), doing="moving things apart")
        check = _call(bridge, "inspect_scene", ids, doing="checking the objects")
    _note(state, "the objects stand on something and clear of each other", not check["clashes"] and
          not check["floating"], f"overlapping: {check['clashes'][:3]}, floating: {check['floating'][:3]}")
    _call(bridge, "scene_plan_set", state["plan"], doing="saving the scene's plan")
    state["facts"]["scene"] = _call(bridge, "scene_facts", doing="reading the scene")
    return "Placed " + ", ".join(made) + (f" (and {', '.join(implied)} the actions need)" if implied else "") + "."


def _characters(state):
    bridge = state["bridge"]
    names = []
    for i, t in enumerate(_tasks(state, "character")):
        name = t.get("name") or f"{t['template'].title()}{' ' + str(i + 1) if i else ''}"
        t["name"] = name
        out = _kit(bridge, f"import json\nRESULT = json.dumps(character_build({name!r}, {t['template']!r}))\n"
                           f"o = bpy.data.objects[{name!r}]\no['jarvis_scene'] = {t['id']!r}\n"
                           f"for c in o.children:\n    c['jarvis_scene'] = {t['id']!r}",
                   "creating a character", 120)
        ok = out["unweighted"] == 0 and out["axes_error"] < 1e-3
        _note(state, f"{name}'s rig", ok, f"{out['bones']} bones, {out['vertices']} vertices")
        names.append(name)
    _call(bridge, "scene_plan_set", state["plan"], doing="saving the scene's plan")
    return "Created " + ", ".join(names) + ": rigged, skinned and checked."


def _lighting(state):
    t = next(iter(_tasks(state, "lighting")), {"time": "day"})
    weather = [w["type"] for w in state["plan"]["tasks"] if w["kind"] == "weather"]
    out = _call(state["bridge"], "set_lighting", t, weather, doing="setting the light")
    return f"Lighting: {out['time']}" + (f", {out['lamps']} lamps lit" if out["lamps"] else "") + "."


def _weather(state):
    tasks = [t for t in state["plan"]["tasks"] if t["kind"] == "weather"]
    out = _call(state["bridge"], "set_weather", tasks, doing="setting the weather", timeout=300)
    return ("Weather: " + ", ".join(t["type"] for t in tasks) + ".") if tasks else "No weather."


# ----- motion: things travelling, characters acting -----

def _motion(state):
    bridge = state["bridge"]
    out = []
    movers = [t for t in _tasks(state, "motion") if t["kind"] == "motion"]
    actors = [t for t in _tasks(state, "motion") if t["kind"] == "action"]
    if actors:
        out.append(_act(state, actors))
    for t in movers:
        clearance, lift = None, 0.0
        res = _call(bridge, "animate_motion", t, 1, clearance, lift, doing="animating", timeout=600)
        check = _call(bridge, "inspect_motion_paths", {t["id"]: t["subject"]}, doing="checking the motion")[t["id"]]
        for k in range(REPAIRS):
            if not check.get("hits") and check.get("travelled", 0) > 1.0:
                break
            if check.get("hits"):   # through something: more room around it, and a flier's route a little higher
                clearance = (clearance or 2.0) + 2.0
                lift += 4.0
            else:                   # it found no way at all: let it pass closer to things
                clearance = max(0.5, (clearance or 2.5) - 1.0)
            res = _call(bridge, "animate_motion", t, 1, clearance, lift, doing="re-routing", timeout=600)
            check = _call(bridge, "inspect_motion_paths", {t["id"]: t["subject"]}, doing="checking the motion")[t["id"]]
        ok = not check.get("hits") and check.get("travelled", 0) > 1.0
        _note(state, f"the {_subject_name(state, t)}'s route", ok,
              f"{check.get('travelled')} m in {round((res['frames'][1] - res['frames'][0]) / 24, 1)} s, "
              f"{len(check.get('hits') or [])} contacts")
        out.append(f"the {_subject_name(state, t)} travels {check.get('travelled')} m")
    _call(bridge, "scene_plan_set", state["plan"], doing="saving the scene's plan")
    return "Animated: " + "; ".join(out) + "."


def _subject_name(state, t):
    s = next((x for x in state["plan"]["tasks"] if x["id"] == t.get("subject")), {})
    return (s.get("name") or s.get("asset") or s.get("template") or "thing").replace("_", " ")


def _act(state, actions):
    """Characters' actions become one anim_core script: each target resolved to a real point in the scene."""
    bridge = state["bridge"]
    facts = _call(bridge, "scene_facts", doing="reading the scene")
    tasks = state["plan"]["tasks"]
    chars = {t["id"]: t for t in tasks if t["kind"] == "character"}
    script = {"actors": [], "doors": [], "props": [], "seats": [], "script": []}
    door_facts = None
    objs = facts["tasks"]
    flat = [dict(o, task=tid) for tid, os_ in objs.items() for o in os_ if o.get("lo")]
    used_spots = []
    for a in actions:
        c = chars.get(a["subject"])
        if c is None:
            continue
        if any(s["do"] in ("open_door", "enter", "close_door") for s in a["steps"]) and door_facts is None:
            door_facts = _kit(bridge, "import json\nRESULT = json.dumps(door_facts())", "finding the door", 60)
            if door_facts:
                script["doors"].append({"id": "front", "build": door_facts.get("build")})
        start, heading = _start_for(state, a, flat, door_facts, used_spots)
        used_spots.append(start)
        actor = {"id": c["id"], "name": c["name"], "template": c["template"], "at": start, "heading": heading}
        script["actors"].append(actor)
        for s in a["steps"]:
            item = _resolve_step(state, c, s, flat, door_facts, script, a)
            mine = [x for x in script["script"] if x["actor"] == c["id"]]
            if item and mine and item["do"] == "open_door" and mine[-1]["do"] == "open_door":
                continue   # "opening the door, entering": the opening already walks him in
            if item:
                if a.get("speed") and item["do"] in ("walk", "run"):
                    item["speed"] = (1.3 if item["do"] == "walk" else 3.2) * a["speed"]
                script["script"].append(item)
    if not script["script"]:
        raise RuntimeError("I couldn't work out what the characters should do in this scene.")
    res = _call(bridge, "animate", script, doing="animating the characters", timeout=900)
    insp = _call(bridge, "inspect_motion", doing="checking the characters' motion", timeout=900)
    for name, m in insp.get("characters", {}).items():
        ok = (m["slide"] < 0.01 and m["sink"] < 0.03 and m["float"] < 0.03 and not m["wall_hits"] and
              not m["door_hits"] and m["knee_backwards"] == 0 and m["jump_deg"] < 60 and m["ik_leg"] < 0.01)
        _note(state, f"{name}'s motion", ok, f"slide {m['slide'] * 100:.1f} cm, sink {m['sink'] * 100:.1f} cm, "
                                             f"{len(m['wall_hits'])} wall / {len(m['door_hits'])} door contacts, "
                                             f"worst turn {m['jump_deg']}°")
        if m.get("hold_frames"):
            _note(state, f"{name}'s hand on the door handle", m["hand_handle"] < 0.06,
                  f"within {m['hand_handle'] * 100:.1f} cm over {m['hold_frames']} frames")
        if m.get("carry_frames"):
            _note(state, f"{name}'s hand on what it carries", m["hand_prop"] < 0.06,
                  f"within {m['hand_prop'] * 100:.1f} cm over {m['carry_frames']} frames")
    for d, v in insp.get("doors", {}).items():
        _note(state, "the door", v["max"] > 60 and (v["end"] < 1 or not any(
            s["do"] == "close_door" for a in actions for s in a["steps"])), f"opens to {v['max']}°, ends at {v['end']}°")
    return f"{len(script['actors'])} character(s) act over {res['frames']} frames"


def _start_for(state, action, flat, door, used):
    """Where a character starts: in front of a build's door when the first thing is going to it, else a few
    metres from the first thing it goes to, else in the open middle."""
    steps = action["steps"]
    first = steps[0]
    if door and (first["do"] in ("enter", "open_door") or first.get("target", {}).get("part") == "door" or any(
            s["do"] in ("enter", "open_door") for s in steps)):
        u, n = door["u"], door["n_in"]
        mid = [door["hinge"][0] + u[0] * door["width"] / 2, door["hinge"][1] + u[1] * door["width"] / 2]
        return [round(mid[0] - n[0] * 7.0, 3), round(mid[1] - n[1] * 7.0, 3)], round(math.degrees(math.atan2(n[0], -n[1])),
                                                                                    1)
    env = next(iter(state["facts"].get("scene", {}).get("envs", {}).values()), None) if state["facts"].get("scene") else None
    room = env.get("room") if env else None
    target = _target_objects(first.get("target"), flat) if first.get("target") else []
    if room:
        p = [0.0, -room["depth"] / 2 + 0.8]
    elif target:
        o = target[0]
        cx, cy = (o["lo"][0] + o["hi"][0]) / 2, (o["lo"][1] + o["hi"][1]) / 2
        p = [round(cx + 0.5, 2), round(cy - 5.0, 2)]
    else:
        p = [0.0, -2.0]
    while any(math.hypot(p[0] - q[0], p[1] - q[1]) < 1.2 for q in used):
        p = [p[0] + 1.4, p[1]]
    goal = target[0] if target else None
    if goal:
        gx, gy = (goal["lo"][0] + goal["hi"][0]) / 2, (goal["lo"][1] + goal["hi"][1]) / 2
        heading = math.degrees(math.atan2(gx - p[0], -(gy - p[1])))
    else:
        heading = 0.0
    return p, round(heading, 1)


def _target_objects(target, flat):
    if not target:
        return []
    if target.get("task"):
        return [o for o in flat if o["task"] == target["task"] and o.get("role") not in ("ground", "floor", "wall",
                                                                                         "ceiling", "sidewalk")]
    if target.get("asset"):
        return [o for o in flat if o.get("asset") == target["asset"]]
    return []


def _approach(o, frm, gap=0.55):
    """A point beside object `o`, on the side facing `frm`, `gap` metres from its edge."""
    cx, cy = (o["lo"][0] + o["hi"][0]) / 2, (o["lo"][1] + o["hi"][1]) / 2
    hx, hy = (o["hi"][0] - o["lo"][0]) / 2, (o["hi"][1] - o["lo"][1]) / 2
    dx, dy = frm[0] - cx, frm[1] - cy
    if abs(dx) / max(hx, 0.1) > abs(dy) / max(hy, 0.1):
        return [round(cx + math.copysign(hx + gap, dx), 3), round(cy, 3)]
    return [round(cx, 3), round(cy + math.copysign(hy + gap, dy), 3)]


def _resolve_step(state, c, s, flat, door, script, action):
    do = s["do"]
    actor = c["id"]
    here = next(a["at"] for a in script["actors"] if a["id"] == actor)
    targets = _target_objects(s.get("target"), flat)
    if do in ("walk", "run"):
        if s.get("target", {}).get("part") == "door" and door:
            return None   # the door action walks up to it itself
        if targets:
            return {"actor": actor, "do": "run" if do == "run" else "walk", "to": _approach(targets[0], here)}
        far = [here[0] + 0.0, here[1] + 5.0]
        return {"actor": actor, "do": "run" if do == "run" else "walk", "to": far}
    if do in ("open_door", "enter"):
        return {"actor": actor, "do": "open_door", "door": "front", "enter": True} if door else None
    if do == "close_door":
        return {"actor": actor, "do": "close_door", "door": "front"} if door else None
    if do == "sit":
        seats = [o for o in flat if o.get("seat")]
        if not seats:
            return None
        seat = min(seats, key=lambda o: math.hypot(o["at"][0] - here[0], o["at"][1] - here[1]))
        sid = seat["name"]
        if not any(x["id"] == sid for x in script["seats"]):
            script["seats"].append({"id": sid, "at": [seat["at"][0], seat["at"][1], seat["lo"][2]],
                                    "height": seat["seat"]["height"], "facing": seat["yaw"]})
        return {"actor": actor, "do": "sit", "seat": sid}
    if do == "stand":
        return {"actor": actor, "do": "stand"}
    if do in ("eat", "drink", "pick_up", "carry", "phone"):
        want = s.get("prop")
        props = [o for o in flat if o.get("asset") == want] or targets
        if not props:
            return None
        p = props[0]
        kind = {"sandwich": "sandwich", "cup": "cup", "bottle": "glass", "phone": "phone", "box": "box"}.get(
            p.get("asset"), "box")
        if not any(x["id"] == p["name"] for x in script["props"]):
            script["props"].append({"id": p["name"], "kind": kind, "at": p["at"], "yaw": p.get("yaw", 0.0)})
        do2 = {"eat": "eat", "drink": "drink", "pick_up": "pick_up", "carry": "carry", "phone": "phone"}[do]
        item = {"actor": actor, "do": do2, "prop": p["name"]}
        if do == "carry":
            item["to"] = [here[0], here[1] + 4.0]
        return item
    if do == "put_down":
        return {"actor": actor, "do": "put_down"}
    if do in ("wave", "talk", "dance", "jump", "wait", "fight", "work", "turn_around", "look", "point", "handshake"):
        item = {"actor": actor, "do": {"turn_around": "turn", "look": "idle", "wait": "idle"}.get(do, do)}
        if do == "turn_around":
            item["yaw"] = (next(a["heading"] for a in script["actors"] if a["id"] == actor) + 180) % 360
        if do == "point" and targets:
            o = targets[0]
            item["at"] = [(o["lo"][0] + o["hi"][0]) / 2, (o["lo"][1] + o["hi"][1]) / 2, o["hi"][2]]
        if do in ("dance", "talk", "wait", "look"):
            item["seconds"] = 6.0 if do == "dance" else 3.0
        if do == "handshake":
            other = next((t for t in state["plan"]["tasks"] if t["kind"] == "character" and t["id"] != actor), None)
            if other is None:
                return None
            item["with"] = other["id"]
        return item
    return None


# ----- camera, pictures, video, the saved project -----

def _camera(state):
    bridge = state["bridge"]
    t = next(iter(_tasks(state, "camera")), None) or {"shot": "establishing", "subject": None}
    res = _call(bridge, "set_camera", t, 0, doing="setting up the camera", timeout=600)
    check = _call(bridge, "inspect_camera", t.get("subject"), doing="checking what the camera sees", timeout=600)

    def bad(ch):
        n = max(1, ch.get("frames", 1))
        if ch.get("still"):   # a still scene: everything asked for is in the picture
            return bool(ch.get("outside")) or bool(ch.get("camera_inside"))
        return (len(ch.get("outside", [])) + len(ch.get("hidden", []))) / n > 0.15 or len(ch.get("camera_inside", [])) > 0
    attempt = 0
    while bad(check) and attempt < REPAIRS + 1:
        attempt += 1
        res = _call(bridge, "set_camera", t, attempt, doing="trying another camera angle", timeout=600)
        check = _call(bridge, "inspect_camera", t.get("subject"), doing="checking what the camera sees", timeout=600)
    n = max(1, check.get("frames", 1))
    _note(state, "the camera keeps the subject in view", not bad(check),
          f"out of frame {len(check.get('outside', []))}/{n}, hidden {len(check.get('hidden', []))}/{n} sampled frames"
          + (f", inside something on {len(check['camera_inside'])}" if check.get("camera_inside") else ""))
    return f"Camera: {res['shot']}."


def _folder(state):
    if "folder" not in state:
        stamp = time.strftime("%Y-%m-%d %H-%M-%S")
        name = re.sub(r"[^\w -]", "", (scene_plan.describe(state["plan"]) or "scene")[:40]).strip() or "scene"
        state["folder"] = _kit(state["bridge"], "import os, json\nblend = bpy.data.filepath\n"
                                                "home = os.path.join(os.path.expanduser('~'), 'Documents', 'Jarvis renders')\n"
                                                "base = os.path.join(os.path.dirname(blend), 'renders') if blend else home\n"
                                                f"RESULT = json.dumps(os.path.join(base, {(name + ' ' + stamp)!r}))",
                               "choosing where to save", 20)
    return state["folder"]


def _previews(state):
    bridge = state["bridge"]
    frames = _kit(bridge, "import json\ns = bpy.context.scene\nRESULT = json.dumps([s.frame_start, s.frame_end])",
                  "reading the frames", 20)
    a, b = frames
    moving = any(t["kind"] in ("motion", "action") for t in state["plan"]["tasks"])
    picks = sorted({a + 2, (a + b) // 2, max(a, b - 8)}) if b > a + 10 and moving else [a]
    folder = os.path.join(_folder(state), "preview")
    shots = _call(bridge, "render_frames", folder, picks, "preview", doing="rendering preview pictures", timeout=900)
    for _ in range(REPAIRS):
        dark = [s for s in shots if s["brightness"] < 0.05]
        if not dark:
            break
        _kit(bridge, "s = bpy.context.scene\ns.view_settings.exposure += 1.2\nRESULT = 'ok'", "brightening", 20)
        shots = _call(bridge, "render_frames", folder, picks, "preview", doing="rendering preview pictures again",
                      timeout=900)
    _note(state, "the pictures are lit and not empty", all(0.05 <= s["brightness"] <= 0.95 and not s["flat"]
                                                           for s in shots),
          ", ".join(f"frame {s['frame']}: brightness {s['brightness']:.0%}" for s in shots))
    cam = next((t for t in state["plan"]["tasks"] if t["kind"] == "camera" and t.get("subject")), None)
    if cam:
        def coverage():
            return [_call(bridge, "subject_coverage", cam["subject"], f, os.path.join(folder, f"subject mask {f}.png"),
                          doing="checking the subject is in the picture") for f in picks]
        covs = coverage()
        attempt = 0
        while any(c["coverage"] <= 0.002 for c in covs) and attempt < REPAIRS:
            # it's missing from a picture the camera checks passed: another angle, then look again
            attempt += 1
            _call(bridge, "set_camera", cam, attempt + 2, doing="re-aiming the camera", timeout=600)
            shots = _call(bridge, "render_frames", folder, picks, "preview", doing="rendering preview pictures again",
                          timeout=900)
            covs = coverage()
        _note(state, "the subject shows in every picture", all(c["coverage"] > 0.002 for c in covs),
              ", ".join(f"{c['coverage']:.1%} of frame {c['frame']}" for c in covs))
    if any(t["kind"] == "weather" and t["type"] in ("rain", "snow", "storm") for t in state["plan"]["tasks"]):
        vis = _call(bridge, "rain_visible", picks[len(picks) // 2], folder, doing="checking the weather shows")
        for _ in range(REPAIRS):
            if not vis.get("weather") or vis["changed"] > 0.004:
                break
            _kit(bridge, "for m in bpy.data.materials:\n    if m.name.startswith(('Rain streak', 'Snowflake')):\n"
                         "        n = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')\n"
                         "        n.inputs['Emission Strength'].default_value *= 3\nRESULT = 'ok'", "making the rain show",
                 20)
            vis = _call(bridge, "rain_visible", picks[len(picks) // 2], folder, doing="checking the weather shows")
        _note(state, "the weather shows in the picture", vis.get("weather") and vis["changed"] > 0.004,
              f"{vis.get('changed', 0):.1%} of the pixels change with it")
    state["outputs"]["previews"] = [s["path"] for s in shots]
    return f"Preview pictures in {folder}."


def _video(state):
    bridge = state["bridge"]
    quality = next((t.get("quality") for t in _tasks(state, "render")), "preview")
    frames = _kit(bridge, "import json\ns = bpy.context.scene\nRESULT = json.dumps([s.frame_start, s.frame_end])",
                  "reading the frames", 20)
    a, b = frames
    folder = os.path.join(_folder(state), "frames")
    task = state["steps"].task
    f = a
    started = time.time()
    while f <= b:
        if task is not None:
            if not task._checkpoint():
                raise Stopped()
            task._report("acting", f"Rendering frames {f}-{min(b, f + CHUNK - 1)} of {b}")
        _call(bridge, "render_video_chunk", folder, f, min(b, f + CHUNK - 1), quality, doing="rendering the video",
              timeout=1800)
        f += CHUNK
    out = os.path.join(_folder(state), "animation.mp4")
    enc = _call(bridge, "encode_video", folder, out, doing="making the video file", timeout=1800)
    ok = enc["bytes"] > 10000 and enc["frames"] == b - a + 1
    _note(state, "the video", ok, f"{enc['frames']} frames, {enc['seconds']} s, {enc['bytes'] // 1024} KB")
    state["outputs"]["video"] = enc["path"]
    return f"Video: {enc['path']} ({enc['seconds']} s, rendered in {round(time.time() - started)} s)."


def _save(state):
    bridge = state["bridge"]
    _call(bridge, "scene_plan_set", state["plan"], doing="saving the scene's plan")
    path = os.path.join(_folder(state), "scene.blend")
    _kit(bridge, f"import os\nos.makedirs(os.path.dirname({path!r}), exist_ok=True)\n"
                 f"bpy.ops.wm.save_as_mainfile(filepath={path!r}, copy=True)\nRESULT = '1'", "saving the project", 120)
    state["outputs"]["blend"] = path
    reopened = reopen_check(path)
    _note(state, "the saved project reopens", reopened.get("ok"), reopened.get("detail", ""))
    return _report(state)


def _blender_exe():
    try:
        import app_launcher
        exe = app_launcher.program_path(blender_control._blender_display_name())
        if exe and os.path.basename(exe).lower() == "blender-launcher.exe":
            # the Start menu's launcher hands over to a window and returns at once: no headless run, no output
            exe = os.path.join(os.path.dirname(exe), "blender.exe")
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"))
        from real_blender import find_blender
        return find_blender()
    except Exception:
        return None


_REOPEN = r"""
import bpy, json, sys
s = bpy.context.scene
acts = [o.name for o in s.objects if o.animation_data and o.animation_data.action]
root = bpy.data.objects.get('Jarvis Scene')
print('JARVIS_REOPEN ' + json.dumps({'objects': len(s.objects), 'frames': [s.frame_start, s.frame_end],
      'animated': len(acts), 'plan': bool(root and root.get('jarvis_plan')), 'camera': bool(s.camera)}))
"""


def reopen_check(path):
    """Open the saved .blend in a separate, headless Blender (its own empty APPDATA, so no startup scripts — the
    bridge included — run) and read it back."""
    exe = _blender_exe()
    if not exe or not os.path.exists(path):
        return {"ok": False, "detail": "no Blender to reopen it with" if not exe else "the file wasn't written"}
    import tempfile
    home = tempfile.mkdtemp(prefix="jarvis-reopen-")
    env = dict(os.environ, APPDATA=home, USERPROFILE=home, HOME=home)
    try:
        r = subprocess.run([exe, "-b", "--factory-startup", path, "--python-expr", _REOPEN], capture_output=True,
                           text=True, timeout=180, env=env, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "detail": f"reopening failed: {e}"}
    m = re.search(r"JARVIS_REOPEN (\{.*\})", r.stdout or "")
    if not m:
        return {"ok": False, "detail": "Blender couldn't read it back"}
    facts = json.loads(m.group(1))
    ok = facts["objects"] > 0 and facts["plan"] and facts["camera"]
    return {"ok": ok, "detail": f"{facts['objects']} objects, frames {facts['frames'][0]}-{facts['frames'][1]}, "
                                f"{facts['animated']} animated", **facts}


def _report(state):
    plan = state["plan"]
    passed = [c for c in state["checks"] if c["ok"]]
    failed = [c for c in state["checks"] if not c["ok"]]
    stand_ins = [t.get("name") for t in plan["tasks"] if t.get("shaped_by") == "stand-in"]
    head = "Built, with problems" if failed else (f"Built, with a plain stand-in for the {', '.join(stand_ins)}"
                                                  if stand_ins else "Done")
    text = f"{head} — {scene_plan.describe(plan)}."
    text += f" Checked in Blender: {len(passed)} of {len(state['checks'])} checks pass"
    if passed:
        text += " (" + "; ".join(f"{c['what']}: {c['detail']}" for c in passed[:6] if c["detail"]) + ")"
    text += "."
    if failed:
        text += " Still failing after repairs: " + "; ".join(f"{c['what']} ({c['detail']})" for c in failed) + "."
    extra = [p for p in state["problems"] if not any(p.startswith(c["what"]) for c in failed)]
    if extra:
        text += " Also: " + "; ".join(extra) + "."
    if plan.get("unknown"):
        text += f" Not modelled: {', '.join(sorted(set(plan['unknown']))[:5])}."
    out = state["outputs"]
    if out.get("video"):
        text += f" Video: {out['video']}."
    if out.get("blend"):
        text += f" Project: {out['blend']}."
    if failed:
        raise RuntimeError(text)
    return text
