"""Editing what is already in Blender (blender_edit.py): what a follow-up means, where it is routed, and that a
destructive one asks first. Pure Python with a pretend bridge — the real-Blender side (the pool really moves, the path
really joins both ends) is in test_blender_real.py.

The sentences here are the ones that failed on 2026-10-22: after "create a villa with a pool", each of them either
rebuilt the whole villa, or went to the small local AI, which flailed while Jarvis said "Okay"."""
import json

import pytest

import blender_build
import blender_commands
import blender_edit
import computer_use
import sandbox


def session():
    return computer_use.ControlSession(env=None)


class FakeBridge:
    """Answers features() with `scene` and records every script; anything else gets `answers` in order."""

    def __init__(self, scene=(), answers=()):
        self.scene = list(scene)
        self.answers = list(answers)
        self.calls = []

    def run(self, code, timeout=15):
        self.calls.append(code)
        if code.endswith("RESULT = json.dumps(features())"):
            return {"ok": True, "output": json.dumps(self.scene)}
        if self.answers:
            return self.answers.pop(0)
        return {"ok": True, "output": "null"}


def ran(bridge, call):
    """Whether the bridge was asked to run `call` (every request carries the kit's source, so match its end)."""
    return any(c.endswith(f"RESULT = json.dumps({call})") for c in bridge.calls)


def feature(fid, kind, build=None):
    return {"id": fid, "kind": kind, "name": fid.split("/")[-1], "build": build, "objects": [fid], "lo": [0, 0, 0],
            "hi": [1, 1, 1], "connects": None, "uids": {fid: 1}}


# ---------- what a follow-up means ----------

@pytest.mark.parametrize("text, ops", [
    ("move the pool more to the side and add a path", ["move", "connect"]),
    ("add a path from the villa to a pool", ["connect"]),
    ("create a path from the pool to the villa", ["connect"]),
    ("add a path to the pool", ["connect"]),
    ("make the pool better", ["improve"]),
    ("delete everything in blender", ["clear"]),
    ("make the entire villa much more beautiful", ["improve"]),
    ("widen the path", ["resize"]),
    ("move the pool closer to the house", ["move"]),
    ("remove the path between the garden and the pool", ["remove"]),
    ("add a garage to the villa", ["extend"]),
    ("paint the house white", ["paint"]),
])
def test_follow_ups_after_a_build_are_edits_of_what_is_there(text, ops):
    parsed = blender_edit.parse(blender_commands.normalize(text))
    assert [op["op"] for op in parsed] == ops


@pytest.mark.parametrize("text", ["add a path from the villa to a pool", "add a garage to the villa",
                                  "put a fountain next to the house", "make a garden for the cottage"])
def test_an_edit_naming_a_building_is_never_read_as_a_new_building(text):
    assert blender_build.parse(text) is None


def test_a_new_villa_with_a_path_asks_for_the_path_and_checks_it_and_says_nothing_was_left_out():
    spec = blender_build.parse("create a villa with a pool and a path from the pool to the villa")
    assert spec["connections"] == [["house", "pool"]] and spec["not_built"] == []
    p = blender_build.plan(spec)
    assert p["connections"] == [{"between": ["house", "pool"], "width": 1.2, "quality": 0}]
    path = [r for r in blender_build.requirements(spec, p) if r[0] == "path house-pool"]
    assert path and path[0][2] == "connections"
    assert path[0][3]({"connections": []}) == "no path"
    assert path[0][3]({"connections": [{"between": ["house", "pool"], "ok": True, "problems": []}]}) == ""
    assert "a path between the villa and the pool" in blender_build.describe(spec, p)


def test_moving_says_which_way_how_far_and_from_what():
    [op] = blender_edit.parse("move the pool 5 m to the right")
    assert (op["how"], op["distance"]) == ("right", 5.0)
    [op] = blender_edit.parse("move the pool a bit further away from the house")
    assert (op["how"], op["distance"], op["ref"]) == ("away", 2.0, "the house")
    [op] = blender_edit.parse("move the pool to the back of the house")
    assert op["how"] == "behind"
    [op] = blender_edit.parse("move the pool")
    assert op["how"] == "side"


def test_a_path_with_no_ends_named_is_left_for_the_scene_to_decide():
    [op] = blender_edit.parse("add a path")
    assert (op["a"], op["b"]) == (None, None)
    [op] = blender_edit.parse("add a path between the pool and the villa")
    assert (op["a"], op["b"]) == ("the pool", "the villa")
    [op] = blender_edit.parse("add a wide path to the garden")
    assert (op["a"], op["b"], op["width"]) == (None, "the garden", 1.8)


@pytest.mark.parametrize("text", ["move the cube left", "make the cube red", "create a cube", "rotate the cube 45 degrees",
                                  "delete the cube", "put the ball on the table", "point the camera at the cube"])
def test_one_object_commands_stay_with_the_older_verified_commands(text):
    assert blender_edit.parse(blender_commands.normalize(text)) is None
    assert blender_commands.steps_for(text, session(), FakeBridge()) is not None


@pytest.mark.parametrize("typed, meant", [("delite evrything in bender", "delete everything in blender"),
                                          ("make the pool beter", "make the pool better"),
                                          ("creat a vila", "create a villa"),
                                          ("add a pathh to the pool", "add a path to the pool"),
                                          ("crate a realistic villa", "create a realistic villa"),
                                          ("Crate two cubes", "Create two cubes")])
def test_typos_in_blender_words_are_fixed(typed, meant):
    assert blender_commands.fix_typos(typed) == meant


@pytest.mark.parametrize("text", ["point the camera at the cube", "build a small house", "set a reminder",
                                  "make the cube 4 meters wide",
                                  "Answer in plain words.", "open README.md", "the garbage is full",
                                  "Check the internet connection", "rename the cube to Crate", "put the crate on the table",
                                  "crate it up"])
def test_real_words_are_never_corrected_into_commands(text):
    assert blender_commands.fix_typos(text) == text


def test_a_mistyped_create_still_builds_the_villa():
    """"crate a realistic villa" (2026-10-23) got "I'm not sure what you'd like me to do there" instead of a build."""
    assert blender_build.parse(blender_commands.normalize("crate a realistic villa")) is not None


# ---------- "it" ----------

def test_it_means_the_feature_the_last_edit_worked_on_and_otherwise_stays_with_the_older_commands():
    s = session()
    assert blender_edit.steps_for("move it to the left", s, FakeBridge()) is None   # after "create a cube"
    s.blender_feature = "Villa/pool"
    steps = blender_edit.steps_for("move it to the left", s, FakeBridge())
    assert isinstance(steps, blender_edit.EditSteps)


def test_an_older_command_touching_an_object_makes_it_mean_that_object_again():
    s = session()
    s.blender_feature = "Villa/pool"
    bridge = FakeBridge(answers=[{"ok": True, "output": "Cube"}])
    assert blender_commands._resolve_reference("the cube", s, bridge) == "Cube"
    assert s.blender_feature is None and s.blender_focus == "Cube"


def test_edits_start_by_saying_what_they_will_do_not_okay():
    assert blender_edit.intro_for("move the pool more to the side and add a path") == (
        "On it — moving the pool and laying a path. I'll check each change in Blender before I say it's done.")
    assert blender_edit.intro_for("make it better").startswith("On it — improving it.")
    assert blender_edit.intro_for("what time is it") is None


# ---------- destructive edits ask, and a refusal leaves everything as it was ----------

def test_deleting_everything_asks_first_and_a_no_leaves_the_scene_alone():
    s = session()
    asked = []
    s.confirm = lambda question: asked.append(question) or False
    bridge = FakeBridge(scene=[feature("Villa/house", "house", "Villa"), feature("Villa/pool", "pool", "Villa")])
    task = computer_use.ScriptedTask("delete everything", blender_commands.steps_for("delete everything in blender", s,
                                                                                     bridge), log=lambda *a: None)
    reply = task.run()
    assert task.state == "error" and "left the scene exactly as it was" in reply
    assert asked and "Delete everything" in asked[0]
    assert not ran(bridge, "clear_scene()")


def test_deleting_everything_with_no_way_to_ask_does_nothing():
    bridge = FakeBridge(scene=[feature("Villa/house", "house", "Villa")])
    task = computer_use.ScriptedTask("x", blender_commands.steps_for("delete everything", session(), bridge),
                                     log=lambda *a: None)
    task.run()
    assert task.state == "error" and not ran(bridge, "clear_scene()")


def test_blenders_untouched_start_scene_is_cleared_without_asking():
    s = session()
    s.confirm = lambda question: pytest.fail("asked about the startup cube")
    bridge = FakeBridge(scene=[feature("Cube", "object"), feature("Light", "light"), feature("Camera", "camera")],
                        answers=[{"ok": True, "output": "1"},   # the checkpoint was saved
                                 {"ok": True, "output": json.dumps({"removed": 3, "left": []})}])
    original = bridge.run

    def run(code, timeout=15):
        if code.endswith("RESULT = json.dumps(clear_scene())"):
            bridge.scene = []
        return original(code, timeout)
    bridge.run = run
    task = computer_use.ScriptedTask("x", blender_commands.steps_for("delete everything", s, bridge),
                                     log=lambda *a: None)
    reply = task.run()
    assert task.state == "completed" and "deleted all 3 objects" in reply


def test_a_failed_check_is_reported_as_a_failure_never_as_done():
    s = session()
    path = {"path": "Villa path villa to pool", "feature": "Villa/path:house-pool", "between": ["villa", "pool"],
            "door": "Villa main house door front 1.1 leaf", "width": 1.2, "length": 12.0, "turns": 1}
    gap = {"ok": False, "problems": ["it stops 2.0 m short of the pool"], "samples": 30}
    answers = [{"ok": True, "output": json.dumps(x)} for x in (path, gap, path, gap)]
    bridge = FakeBridge(scene=[feature("Villa/house", "house", "Villa")], answers=answers)
    task = computer_use.ScriptedTask("x", blender_commands.steps_for("add a path to the pool", s, bridge),
                                     log=lambda *a: None)
    reply = task.run()
    assert task.state == "error" and "stops 2.0 m short of the pool" in reply and "Done" not in reply


def test_a_later_failure_still_says_what_was_already_done():
    s = session()
    moved = {"feature": "Villa/pool", "name": "pool", "moved": [4.0, 0.0], "distance": 4.0, "pushed": 0,
             "rerouted": [], "gap": 5.8, "ref": "villa", "center": [26, -3.5]}
    before = [feature("Villa/house", "house", "Villa"), feature("Villa/pool", "pool", "Villa")]
    after = [before[0], {**before[1], "lo": [4, 0, 0], "hi": [5, 1, 1]}]
    states = iter([before, after])
    bridge = FakeBridge(answers=[{"ok": True, "output": json.dumps(moved)}, {"ok": True, "output": "[]"},
                                 {"ok": False, "error": "Traceback...\nValueError: there's no building in the scene"}])
    original = bridge.run

    def run(code, timeout=15):
        if code.endswith("RESULT = json.dumps(features())"):
            bridge.scene = next(states, after)
        return original(code, timeout)
    bridge.run = run
    task = computer_use.ScriptedTask("x", blender_commands.steps_for("move the pool to the side and add a path", s,
                                                                     bridge), log=lambda *a: None)
    reply = task.run()
    assert task.state == "error"
    assert reply.startswith("Done — I moved the pool 4 m to the side") and "But then: There's no building" in reply


# ---------- the app: these reach Blender, and say what is starting ----------

@pytest.fixture(scope="module")
def app():
    sandbox.install()
    import app as imported
    yield imported
    sandbox.uninstall()


@pytest.mark.parametrize("text", ["move the pool more to the side and add a path", "add a path to the pool",
                                  "make the pool better", "delite evrything in bender", "widen the path"])
def test_with_blender_open_follow_ups_go_to_blender_not_the_chat_ai(app, monkeypatch, text):
    monkeypatch.setattr(app.blender_control, "blender_running", lambda: True)
    assert app.is_blender_goal(blender_commands.normalize(text), said=text)


def test_a_follow_up_in_a_take_control_session_says_what_it_is_doing(app):
    s = session()
    s.blender = object()   # the session works in Blender
    assert app._starting_reply("move the pool more to the side and add a path", s).startswith(
        "On it — moving the pool and laying a path.")
    assert app._starting_reply("create a villa with a pool", s) == blender_build.BuildSteps.intro
    assert app._starting_reply("open notepad", s) == "On it: open notepad. Say stop to cancel."
    # not in Blender (a document, a browser): no talk of pools and paths
    assert app._starting_reply("make it shorter", session()) == "On it: make it shorter. Say stop to cancel."
