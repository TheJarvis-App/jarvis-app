"""Whole buildings in Blender (blender_build.py): what a request means, the plan it becomes, and what has to hold
before Jarvis may say it's built. Pure Python — the real-Blender side is in test_blender_real.py."""
import json

import pytest

import blender_build as bb
import computer_use


# ---------- what was asked ----------

def test_a_villa_request_becomes_a_building_spec_not_a_primitive():
    spec = bb.parse("create a villa")
    assert spec["kind"] == "villa" and spec["storeys"] == 2 and spec["features"] == []


@pytest.mark.parametrize("text", ["make the house red", "move the villa left", "what's a villa", "create a cube",
                                  "delete the house", "build a table"])
def test_edits_questions_and_other_objects_are_not_new_buildings(text):
    assert bb.parse(text) is None


def test_only_the_features_that_were_asked_for_are_planned():
    spec = bb.parse("build a modern villa with a pool and a garden")
    assert set(spec["features"]) == {"pool", "garden"}
    plain = bb.plan(bb.parse("create a villa"))
    assert plain["extras"] == {} and plain["driveways"] == []


def test_storeys_style_and_roof_follow_the_words():
    assert bb.parse("build a three storey mansion")["storeys"] == 3
    assert bb.parse("build a single-storey villa")["storeys"] == 1
    cottage = bb.parse("build a cozy cottage")
    assert cottage["style"] == "classic" and cottage["roof"] == "gable" and cottage["storeys"] == 1
    assert bb.parse("build a traditional villa")["roof"] == "hip"
    assert bb.parse("build a modern house with a gable roof")["roof"] == "gable"


def test_what_nothing_here_builds_is_said_back_instead_of_dropped():
    assert bb.parse("build a small cottage with a fountain")["not_built"] == ["fountain"]
    assert bb.parse("create a beautiful modern house with large glass windows, a swimming pool, a garden, and "
                    "cinematic lighting")["not_built"] == []


# ---------- the plan ----------

def _walls(vol):
    return {"front": vol["size"][0], "back": vol["size"][0], "left": vol["size"][1], "right": vol["size"][1]}


@pytest.mark.parametrize("text", ["create a villa", "build a modern villa with a pool, a garden, a garage, a terrace "
                                  "and a balcony", "build a cozy cottage", "build me a three storey mansion",
                                  "build a small house"])
def test_every_opening_fits_its_wall_and_none_overlap(text):
    p = bb.plan(bb.parse(text))
    for vol in p["volumes"]:
        lengths = _walls(vol)
        for side in lengths:
            for storey in range(vol["storeys"]):
                spans = sorted((o["at"] - o["width"] / 2, o["at"] + o["width"] / 2) for o in vol["openings"]
                               if o["side"] == side and o["storey"] == storey)
                for a, b in spans:
                    assert 0 < a and b < lengths[side], (vol["name"], side, a, b)
                for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
                    assert a1 <= b0, (vol["name"], side, storey, spans)
        for o in vol["openings"]:
            assert o.get("sill", 0) + o["height"] <= bb.STOREY_HEIGHT - bb.SLAB, o
            assert o["side"] not in vol["open_sides"] or o["storey"] >= vol["open_storeys"]


def test_a_villa_has_an_entrance_door_on_the_front_and_more_than_one_volume_that_never_overlap():
    p = bb.plan(bb.parse("create a villa"))
    assert len(p["volumes"]) == 2
    doors = [o for o in p["volumes"][0]["openings"] if o["kind"] == "door"]
    assert len(doors) == 1 and doors[0]["side"] == "front" and doors[0]["storey"] == 0
    (a, b) = p["volumes"]
    ax0, ax1 = a["min"][0], a["min"][0] + a["size"][0]
    bx0 = b["min"][0]
    assert bx0 >= ax1 - 1e-9   # side by side, sharing one wall, never inside each other
    assert "left" in b["open_sides"]


def test_the_site_holds_the_building_and_everything_around_it():
    p = bb.plan(bb.parse("build a modern villa with a pool, a garden and a garage"))
    x0, y0, x1, y1 = bb.site_bounds(p)
    for vol in p["volumes"]:
        assert x0 < vol["min"][0] and vol["min"][0] + vol["size"][0] < x1
        assert y0 < vol["min"][1] and vol["min"][1] + vol["size"][1] < y1
    pool = p["extras"]["pool"]
    assert x0 < pool["min"][0] and pool["min"][0] + pool["size"][0] < x1
    for x, y, _ in p["extras"]["garden"]["trees"]:
        assert x0 < x < x1 and y0 < y < y1


def test_a_balcony_on_a_one_storey_house_is_not_promised():
    spec = bb.parse("build a cottage with a balcony")
    p = bb.plan(spec)
    assert "balcony" not in p["extras"]
    assert "balcony" not in [r[0] for r in bb.requirements(spec, p)]


# ---------- what "done" means ----------

def _good_facts(spec, p):
    """What inspect_build reports for a build that came out exactly as planned."""
    windows = sum(1 for v in p["volumes"] for o in v["openings"] if o["kind"] in ("window", "glass_door"))
    roles = {"wall": bb._expected_walls(p), "slab": sum(v["storeys"] for v in p["volumes"]),
             "foundation": len(p["volumes"]), "interior_wall": 2, "glass": windows, "door": 1, "roof": len(p["volumes"]),
             "water": 1, "pool": 1, "tree": 10, "hedge": 2, "garage_door": 1, "balcony": 1, "railing": 1, "terrace": 1,
             "stairs": sum(v["storeys"] - 1 for v in p["volumes"])}
    doorways = [{"doorway": f"doorway {i}", "open": True} for i in range(20)]
    return {"roles": roles, "doorways": doorways,
            "volumes": [{"name": v["name"], "storeys": v["storeys"], "roofed": True,
                                         "wall_top": bb.PLINTH + v["storeys"] * bb.STOREY_HEIGHT} for v in p["volumes"]],
            "ground_gap": 0.0, "floating": [], "openings_filled": windows + 1, "openings_in_walls": windows + 1,
            "door_on_front": True, "path_reaches_entrance": True, "clashes": [], "no_material": [], "unconnected": [],
            "glass_clear": True, "sun": True, "camera_sees": True, "coverage": 0.5, "size": [20, 10, 7], "parts": 90}


def test_a_scene_holding_one_cube_fails_almost_every_villa_requirement():
    spec = bb.parse("create a villa")
    p = bb.plan(spec)
    cube = {"roles": {}, "volumes": [], "ground_gap": None, "floating": ["Cube"], "openings_filled": 0,
            "openings_in_walls": 0, "door_on_front": False, "path_reaches_entrance": False, "clashes": [],
            "no_material": ["Cube"], "unconnected": [], "glass_clear": False, "sun": False, "camera_sees": False,
            "coverage": 0.0}
    failed = {f[0] for f in bb.unmet(bb.requirements(spec, p), cube)}
    assert {"volumes", "floors", "roof", "windows", "doors", "entrance", "grounded", "materials", "light"} <= failed


def test_a_build_that_came_out_as_planned_meets_every_requirement():
    spec = bb.parse("build a modern villa with a pool, a garden, a garage, a terrace and a balcony")
    p = bb.plan(spec)
    assert bb.unmet(bb.requirements(spec, p), _good_facts(spec, p)) == []


def test_a_missing_roof_is_repaired_by_rebuilding_the_roof_and_reframing_the_camera():
    spec = bb.parse("create a villa")
    p = bb.plan(spec)
    facts = _good_facts(spec, p)
    facts["volumes"][1]["roofed"] = False
    failed = bb.unmet(bb.requirements(spec, p), facts)
    assert [f[0] for f in failed] == ["roof"]
    assert bb.stages_to_repair(failed) == ["roof", "lighting"]


def test_a_requested_pool_that_is_missing_fails_the_build():
    spec = bb.parse("create a villa with a pool")
    p = bb.plan(spec)
    facts = _good_facts(spec, p)
    facts["roles"]["water"] = 0
    assert [f[0] for f in bb.unmet(bb.requirements(spec, p), facts)] == ["pool"]


# ---------- running it: never "done" on a failed check ----------

class ScriptedBridge:
    """Answers the build's requests: the scene probe, each stage, and inspect_build with `facts`."""

    def __init__(self, facts_for):
        self.facts_for = facts_for
        self.calls = []

    def run(self, code, timeout=20):
        if code.startswith("if globals().get('JARVIS_KIT')"):
            code = "\n".join(code.split("\n")[3:])   # the kit's own source names every helper: look past it
        self.calls.append(code)
        if "copy=True" in code:
            return {"ok": True, "output": "1"}
        if "RESULT = json.dumps({\"removed\"" in code:
            return {"ok": True, "output": json.dumps({"removed": [], "others": None, "builds": []})}
        if "inspect_build(" in code:
            return {"ok": True, "output": json.dumps(self.facts_for())}
        if "preview(" in code:
            return {"ok": True, "output": json.dumps({"path": "p.png", "brightness": 0.4, "contrast": 0.2,
                                                      "flat": False, "subject": 0.6})}
        if "arch_" in code:
            return {"ok": True, "output": json.dumps({"parts": 3})}
        return {"ok": True, "output": ""}


def _run(text, facts_for):
    session = computer_use.ControlSession(env=None)
    bridge = ScriptedBridge(facts_for)
    steps = bb.steps_for(text, session, bridge)
    task = computer_use.ScriptedTask(text, steps, log=lambda *a: None)
    return task, task.run(), bridge, session


def test_a_build_whose_checks_keep_failing_ends_as_unfinished_and_says_what_is_missing():
    spec = bb.parse("create a villa")
    p = bb.plan(spec, "Villa")
    def facts():
        f = _good_facts(spec, p)
        f["volumes"][0]["roofed"] = False
        return f
    task, reply, bridge, _ = _run("create a villa", facts)
    assert task.state == "error"
    assert "isn't finished" in reply and "a roof over every part" in reply
    assert not reply.startswith("Done")
    assert sum("arch_roof(" in c for c in bridge.calls) == 1 + bb.REPAIR_ROUNDS   # built, then repaired twice


def test_a_build_that_passes_every_check_is_reported_with_what_was_verified():
    spec = bb.parse("create a villa")
    p = bb.plan(spec, "Villa")
    task, reply, _, session = _run("create a villa", lambda: _good_facts(spec, p))
    assert task.state == "completed"
    assert reply.startswith("Done") and f"all {len(bb.requirements(spec, p))} requirements hold" in reply
    assert session.blender_focus == "Villa" and session.last_undo["description"] == "built the villa"


def test_stages_run_in_dependency_order_with_the_check_last():
    task, _, bridge, _ = _run("create a villa", lambda: _good_facts(bb.parse("create a villa"),
                                                                    bb.plan(bb.parse("create a villa"), "Villa")))
    order = [s for c in bridge.calls for s, _ in bb.STAGES if f"arch_{s}(" in c]
    assert order == [s for s, _ in bb.STAGES]
    descriptions = [d for d, _ in bb.steps_for("create a villa", None, bridge)]
    assert descriptions[0] == "Planning the building" and descriptions[-2].startswith("Checking")


# ---------- for the free-form AI ----------

def test_things_made_of_parts_need_more_than_one_new_object():
    assert bb.min_new_parts("build a simple table with four legs") == 5
    assert bb.min_new_parts("build a snowman out of three spheres") == 3
    assert bb.min_new_parts("make me a chair and a table") == 6
    assert bb.min_new_parts("make the table red") == 0   # an edit of a table that's already there
    assert bb.min_new_parts("build a table leg") == 0     # one leg, not a table
    assert bb.min_new_parts("put a house plant on the desk") == 0
    assert bb.min_new_parts("create a wooden chair, please") == 6
    assert bb.min_new_parts("what is a table") == 0
    assert bb.min_new_parts("create a cube") == 0


def test_a_free_form_house_without_a_roof_or_door_is_named_as_missing():
    assert bb.missing_features("build a house", ["Wall front", "Wall back", "Window 1"]) == ["roof", "door"]
    assert bb.missing_features("build a house", ["VillaBase"]) == ["wall", "roof", "door", "window"]
    assert bb.missing_features("make the cube red", ["Cube.001"]) == []


# ---------- a house you can walk through ----------

def test_the_wing_and_the_garage_open_into_the_house_through_a_passage():
    p = bb.plan(bb.parse("build a modern villa with a garage"))
    passages = [(v["name"], o["side"]) for v in p["volumes"] for o in v["openings"] if o["kind"] == "passage"]
    assert sorted(passages) == [("main house", "left"), ("main house", "right")]   # to the garage and to the wing


def test_a_two_storey_house_has_stairs_that_fit_inside_and_keep_clear_of_its_windows_and_doors():
    for text in ("create a villa", "build a small house", "build me a three storey mansion", "build a two storey cottage"):
        p = bb.plan(bb.parse(text))
        main = p["volumes"][0]
        stairs = main["stairs"]
        (x0, y0), (w, d) = main["min"], main["size"]
        run = stairs["going"] * stairs["risers"]
        assert 0.22 <= stairs["going"] <= 0.28, text   # a comfortable step
        lo, hi = (x0, x0 + w) if stairs["axis"] == 0 else (y0, y0 + d)
        assert lo + bb.WALL <= stairs["start"] and stairs["start"] + run <= hi - bb.WALL, text
        base = x0 if stairs["axis"] == 0 else y0
        for o in main["openings"]:
            if o["side"] == stairs["side"] and o["storey"] == 0:
                assert (o["at"] + o["width"] / 2 <= stairs["start"] - base or
                        o["at"] - o["width"] / 2 >= stairs["start"] - base + run), (text, o)


def test_a_blocked_doorway_or_a_missing_flight_fails_the_build():
    spec = bb.parse("create a villa")
    p = bb.plan(spec)
    facts = _good_facts(spec, p)
    facts["doorways"][3] = {"doorway": "main house passage right", "open": False}
    facts["roles"]["stairs"] = 0
    assert sorted(f[0] for f in bb.unmet(bb.requirements(spec, p), facts)) == ["connected", "stairs"]
