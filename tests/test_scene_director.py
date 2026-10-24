"""How a scene request or a follow-up becomes stages (scene_director.py), decided without Blender: a fake bridge
that holds a stored plan. What each stage does in Blender is tested in tests/test_blender_real.py."""
import json

import blender_build
import blender_commands
import computer_use
import scene_director
import scene_plan


class PlanBridge:
    """Answers "what's the scene's plan" with `plan`, and records everything else."""

    def __init__(self, plan=None):
        self.plan = plan
        self.calls = []

    def run(self, code, timeout=20):
        self.calls.append(code)
        if "scene_plan_get()" in code.split("\n", 3)[-1]:
            return {"ok": True, "output": json.dumps(self.plan)}
        return {"ok": True, "output": "null"}

    def ping(self, timeout=1):
        return True


CITY = ("Create a futuristic city at night, then animate a flying vehicle moving between the skyscrapers while rain "
        "falls and the camera follows it")


def _labels(steps):
    return [d for d, _ in steps]


def test_a_new_scene_is_every_stage_in_order_with_a_video():
    steps = scene_director.steps_for(CITY, computer_use.ControlSession(env=None), PlanBridge())
    assert isinstance(steps, blender_build.BuildSteps)   # the app runs it as a staged, stoppable task
    assert _labels(steps) == ["Planning the scene", "Building the environment", "Placing the objects",
                              "Setting the lighting", "Setting the weather", "Animating", "Setting up the camera",
                              "Rendering preview pictures and checking them", "Rendering the video",
                              "Saving the project and checking it reopens"]
    assert steps.intro.startswith("On it — a futuristic city, a flying car")


def test_a_follow_up_redoes_only_the_stages_it_touches_on_the_stored_plan():
    stored = scene_plan.with_defaults(scene_plan.parse(CITY))
    bridge = PlanBridge(stored)
    steps = blender_commands.steps_for("make it faster", computer_use.ControlSession(env=None), bridge)
    assert isinstance(steps, scene_director.SceneSteps)
    assert _labels(steps) == ["Planning the scene", "Animating", "Setting up the camera",
                              "Rendering preview pictures and checking them", "Rendering the video",
                              "Saving the project and checking it reopens"]   # the city isn't rebuilt
    motion = next(t for t in steps.plan["tasks"] if t["kind"] == "motion")
    assert motion["speed"] == 1.5
    weather = blender_commands.steps_for("change the weather to snow", computer_use.ControlSession(env=None), bridge)
    assert "Building the environment" not in _labels(weather) and "Setting the weather" in _labels(weather)
    assert [t["type"] for t in weather.plan["tasks"] if t["kind"] == "weather"] == ["snow"]


def test_more_said_to_a_scene_joins_it_instead_of_replacing_it():
    stored = scene_plan.with_defaults(scene_plan.parse("create a park with a fountain"))
    steps = blender_commands.steps_for("add a man walking to the fountain", computer_use.ControlSession(env=None),
                                       PlanBridge(stored))
    kinds = [t["kind"] for t in steps.plan["tasks"]]
    assert kinds.count("environment") == 1 and "character" in kinds and "action" in kinds
    assert "Building the environment" not in _labels(steps)   # the park stays as it is


def test_a_lone_villa_still_goes_to_the_villa_builder_unchanged():
    steps = blender_commands.steps_for("create a villa", computer_use.ControlSession(env=None), PlanBridge())
    assert type(steps) is blender_build.BuildSteps
    assert _labels(steps)[0] == "Planning the building"


def test_the_villa_sequence_runs_the_villa_builder_inside_the_scene():
    text = ("Create a realistic villa, then animate a man walking toward the entrance in the rain, opening the door, "
            "entering, and closing it.")
    steps = blender_commands.steps_for(blender_commands.normalize(text), computer_use.ControlSession(env=None),
                                       PlanBridge())
    labels = _labels(steps)
    assert labels[:2] == ["Planning the scene", "Planning the building"]
    assert labels.index("Fitting the building into the scene") < labels.index("Creating the characters") < \
        labels.index("Animating") < labels.index("Rendering the video")


def test_a_plan_from_blender_that_isnt_one_is_ignored():
    bridge = PlanBridge({"tasks": "rm -rf"})
    assert scene_director._stored(bridge) is None


def test_an_edit_of_a_named_thing_stays_with_the_editor_even_when_the_word_could_be_a_place():
    steps = blender_commands.steps_for("make the garden better", computer_use.ControlSession(env=None), PlanBridge())
    assert not isinstance(steps, scene_director.SceneSteps)   # never "build a park" for it
