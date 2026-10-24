"""Reading any scene request as a plan (scene_plan.py): what a sentence asks for, in what order, about what — for
requests of very different kinds — and the follow-ups that change a scene instead of rebuilding it."""
import pytest

import blender_commands
import scene_plan as sp


def kinds(plan, kind):
    return [t for t in plan["tasks"] if t["kind"] == kind]


def one(plan, kind):
    found = kinds(plan, kind)
    assert len(found) == 1, (kind, plan["tasks"])
    return found[0]


def test_a_city_with_a_flying_vehicle_in_the_rain_followed_by_the_camera_is_every_part_of_one_scene():
    p = sp.parse("Create a futuristic city at night, then animate a flying vehicle moving between the skyscrapers "
                 "while rain falls and the camera follows it")
    city = one(p, "environment")
    assert city["type"] == "city" and city["style"] == "futuristic"
    car = one(p, "object")
    assert car["asset"] == "flying_car"
    motion = one(p, "motion")
    assert motion["subject"] == car["id"]
    assert motion["steps"] == [{"do": "fly", "rel": "between", "target": {"task": city["id"], "items": "building"}}]
    assert one(p, "weather")["type"] == "rain" and one(p, "lighting")["time"] == "night"
    assert one(p, "camera") == {"id": one(p, "camera")["id"], "kind": "camera", "shot": "follow", "subject": car["id"]}


def test_the_villa_sequence_keeps_its_order_and_its_door_and_every_sentence():
    text = ("Create a realistic modern villa, then animate a realistic man approaching the entrance in heavy rain, "
            "opening the front door, entering the house, and closing the door behind him. Use cinematic camera "
            "movements, realistic lighting, wet surfaces, and a polished final render.")
    assert blender_commands.normalize(text) == text.rstrip(".")   # no sentence dropped
    p = sp.parse(text)
    villa = one(p, "building")
    man = one(p, "character")
    act = one(p, "action")
    assert act["subject"] == man["id"]
    assert [s["do"] for s in act["steps"]] == ["walk", "open_door", "enter", "close_door"]
    assert all(s["target"]["task"] == villa["id"] for s in act["steps"])   # "the house" is the villa
    assert one(p, "weather")["intensity"] == "heavy"
    assert one(p, "camera")["shot"] == "cinematic" and one(p, "render")["quality"] == "final"


@pytest.mark.parametrize("text, environment, assets", [
    ("create a living room with a sofa, a coffee table, two chairs and a lamp", "room",
     {"sofa": 1, "table": 1, "chair": 2, "lamp": 1}),
    ("build a forest with a river and make it snow", "forest", {}),
    ("create a desert with rocks and a spaceship flying over it", "desert", {"rock": 4, "spaceship": 1}),
    ("make a park with 3 benches and a fountain", "park", {"bench": 3, "fountain": 1}),
    ("create a beach with palm trees and a boat sailing along the coast", "beach", {"palm": 4, "boat": 1}),
])
def test_environments_with_what_is_in_them(text, environment, assets):
    p = sp.parse(text)
    assert one(p, "environment")["type"] == environment
    got = {t["asset"]: t["count"] for t in kinds(p, "object")}
    assert got == assets
    assert sp.is_scene_request(text)


def test_a_multi_step_interaction_is_one_ordered_action_with_its_targets_and_props():
    p = sp.parse("a woman walks to the table, picks up a cup and drinks from it")
    woman = one(p, "character")
    assert woman["template"] == "woman"
    table = next(t for t in kinds(p, "object") if t["asset"] == "table")
    cup = next(t for t in kinds(p, "object") if t["asset"] == "cup")
    steps = one(p, "action")["steps"]
    assert [s["do"] for s in steps] == ["walk", "pick_up", "drink"]
    assert steps[0]["target"] == {"task": table["id"]} and steps[2]["target"] == {"task": cup["id"]}


def test_a_group_of_people_all_do_what_they_are_told():
    p = sp.parse("two people dance in a park at night")
    people = kinds(p, "character")
    assert [c["template"] for c in people] == ["man", "woman"]
    acts = kinds(p, "action")
    assert {a["subject"] for a in acts} == {c["id"] for c in people}
    assert all(a["steps"][0]["do"] == "dance" and a["together"] == people[0]["id"] for a in acts)


def test_how_fast_and_which_way_are_read_from_the_words():
    p = sp.parse("a red car drives quickly along the street of a small town at sunset")
    car = one(p, "object")
    assert car["color"] == "red"
    m = one(p, "motion")
    assert m["speed"] == 1.5 and m["steps"][0]["rel"] == "along"
    assert one(p, "environment")["type"] == "town" and one(p, "environment")["size"] == "small"
    assert one(p, "lighting")["time"] == "sunset"


def test_something_no_recipe_makes_still_takes_part_and_is_marked_unknown():
    p = sp.parse("create a dragon flying around a castle")
    castle = next(t for t in kinds(p, "object") if t["asset"] == "castle")
    dragon = next(t for t in kinds(p, "object") if t["asset"] == "unknown")
    assert dragon["name"] == "dragon"
    assert one(p, "motion") == {"id": one(p, "motion")["id"], "kind": "motion", "subject": dragon["id"],
                                "steps": [{"do": "fly", "rel": "around", "target": {"task": castle["id"]}}]}


def test_pronouns_and_definite_names_point_at_what_is_already_in_the_scene():
    scene = sp.parse("create a villa, then animate a man walking to the entrance")
    later = sp.parse("Have him open the door and enter naturally.", scene)
    assert not kinds(later, "character")   # "him" is the man who's there, not a new one
    act = one(later, "action")
    man = one(scene, "character")
    assert act["subject"] == man["id"]
    assert [s["do"] for s in act["steps"]] == ["open_door", "enter"]


@pytest.mark.parametrize("text", [
    "create a cube", "make the cube red", "make the cube bigger", "move the car to the left", "create a villa",
    "move the pool to the side", "delete everything", "whether it rains", "show me the weather",
    "make me a sandwich", "put the ball on the floor", "what's the weather like tomorrow", "make it dark green glass",
    "build a simple rocket", "is it going to rain", "render it",
    "build me a modern three storey mansion with a pool and a garage", "build a traditional villa with a garden",
])
def test_everyday_speech_and_the_existing_commands_are_never_taken_for_a_scene(text):
    assert not sp.is_scene_request(text)


def test_follow_ups_are_edits_of_the_plan_that_touch_only_what_they_change():
    scene = sp.with_defaults(sp.parse("Create a futuristic city at night, then animate a flying vehicle moving "
                                      "between the skyscrapers while rain falls and the camera follows it"))
    motion = one(scene, "motion")
    edits = sp.parse_followup("make it faster", scene)
    assert edits == [{"edit": "speed", "task": motion["id"], "factor": 1.5}]
    plan, touched = sp.apply_edits(scene, edits)
    assert one(plan, "motion")["speed"] == 1.5 and touched == {"motion", "camera", "render"}

    plan, touched = sp.apply_edits(scene, sp.parse_followup("change the weather to snow", scene))
    assert [w["type"] for w in kinds(plan, "weather")] == ["snow"] and touched == {"weather", "render"}

    plan, touched = sp.apply_edits(scene, sp.parse_followup("add more buildings", scene))
    assert one(plan, "environment")["density"] == 1.6 and "environment" in touched and "weather" not in touched

    plan, touched = sp.apply_edits(scene, sp.parse_followup("make it daytime", scene))
    assert one(plan, "lighting")["time"] == "day" and touched == {"lighting", "render"}


def test_the_camera_can_be_told_to_follow_the_character():
    scene = sp.with_defaults(sp.parse("a man walks to the bench in a park"))
    man = one(scene, "character")
    edits = sp.parse_followup("make the camera follow the character", scene)
    plan, touched = sp.apply_edits(scene, edits)
    assert one(plan, "camera")["shot"] == "follow" and one(plan, "camera")["subject"] == man["id"]
    assert touched == {"camera", "render"}


def test_what_a_scene_needs_but_was_not_said_is_added():
    p = sp.with_defaults(sp.parse("a drone hovers"))
    assert one(p, "environment")["type"] == "ground"            # something under it
    assert one(p, "camera")["shot"] == "follow"                 # following what moves
    assert one(p, "render")["video"] is True and one(p, "lighting")["time"] == "day"


def test_an_ai_plan_is_checked_field_by_field_before_anything_runs():
    answer = ('{"tasks": [{"id": "t1", "kind": "environment", "type": "volcano"}, '
              '{"id": "t2", "kind": "object", "asset": "composite", "name": "dragon", "parts": ['
              '{"shape": "sphere", "size": [2, 4, 1.5], "at": [0, 0, 0.5], "mat": "lava"},'
              '{"shape": "box", "size": [999, 1, 1], "at": [0, 0, 0]}, {"shape": "teapot", "size": [1, 1, 1], "at": [0, 0, 0]}]},'
              '{"id": "t3", "kind": "motion", "subject": "t2", "steps": [{"do": "fly"}]},'
              '{"id": "t4", "kind": "run_python", "code": "import os"}]}')
    plan = sp.ai_plan("a dragon over a volcano", lambda messages: answer)
    kinds_ = [t["kind"] for t in plan["tasks"]]
    assert kinds_ == ["object", "motion"]                       # no volcano environment, no code
    parts = plan["tasks"][0]["parts"]
    assert len(parts) == 2 and parts[0]["mat"] == "plastic" and parts[1]["size"][0] == 50.0   # clamped and checked
    assert sp.ai_plan("x", lambda m: "I can't do that") is None
