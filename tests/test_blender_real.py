"""The Blender bridge and its helpers (blender_scene.py) in a real Blender: headless, its own bridge folder and home
folder (tests/real_blender.py), so the user's own Blender and files are never touched. Every assertion reads
Blender's real scene back. Skipped where Blender isn't installed."""
import json
import os
import time

import pytest

import blender_bridge
import blender_control
from real_blender import RealBlender, find_blender

pytestmark = pytest.mark.skipif(find_blender() is None, reason="Blender isn't installed here")

FRESH = "bpy.ops.wm.read_factory_settings(use_empty=False)\n"


@pytest.fixture(scope="module")
def bridge(tmp_path_factory):
    with RealBlender(tmp_path_factory.mktemp("real-blender")) as b:
        yield b


def kit(bridge, code, timeout=60):
    if code.startswith(FRESH):
        # A reset replaces Blender's data: in the same script, bpy.context.scene can still be the old scene, so
        # whatever comes after it must run in a request of its own.
        assert bridge.run(FRESH, timeout=30)["ok"]
        code = code[len(FRESH):]
    response = bridge.run(blender_control.with_kit(code), timeout=timeout)
    assert response["ok"], response.get("error")
    return response["output"]


def facts(bridge, code):
    return json.loads(kit(bridge, code))


# ---------- the bridge itself ----------

def test_a_script_calling_sys_exit_reports_an_error_and_the_bridge_keeps_answering(bridge):
    response = bridge.run("import sys\nsys.exit(1)", timeout=5)
    assert response["ok"] is False and "SystemExit" in response["error"]
    assert bridge.ping()


def test_a_request_jarvis_stopped_waiting_for_is_never_run(bridge, tmp_path):
    marker = str(tmp_path / "ran.txt")
    blender_bridge._write_json_atomic(blender_bridge.REQUEST_FILE, {
        "id": 999, "at": time.time() - 60, "expires": time.time() - 30,
        "code": f"open({marker!r}, 'w').write('ran')"})
    time.sleep(0.5)
    assert not os.path.exists(marker)
    assert bridge.ping()


def test_a_slow_script_is_reported_as_still_running_and_the_next_request_waits_for_it(bridge):
    slow = bridge.run("import time\ntime.sleep(2.5)\nRESULT = 'slow done'", timeout=0.5)
    assert slow["ok"] is False and slow.get("busy") is True
    started = time.time()
    after = bridge.run("RESULT = 'next'", timeout=5)
    assert after["ok"] and after["output"] == "next"
    assert time.time() - started > 1.0   # it queued behind the slow one instead of timing out


def test_the_helpers_load_once_and_are_there_for_later_requests(bridge):
    kit(bridge, "RESULT = 'loaded'")
    response = bridge.run("RESULT = str(callable(globals().get('frame')))", timeout=5)
    assert response["output"] == "True"


# ---------- reading and checking the scene ----------

def test_the_report_gives_each_objects_real_size_place_and_material(bridge):
    text = kit(bridge, FRESH + "RESULT = report()")
    assert "Cube [mesh] at (0, 0, 0), size (2, 2, 2) m" in text
    assert "point light 1000 W" in text and "lens 50 mm" in text


def test_a_camera_turned_away_from_everything_is_found_and_framing_fixes_it(bridge):
    problems = facts(bridge, FRESH + "bpy.data.objects['Camera'].rotation_euler = (0, 0, 0)\n"
                                     "RESULT = json.dumps(check())")
    assert any(p["severity"] == "error" and "camera" in p["problem"] for p in problems)
    problems = facts(bridge, "frame()\nRESULT = json.dumps(check())")
    assert not any("camera" in p["problem"] for p in problems)


def test_a_shader_cut_off_from_the_output_is_an_error_and_material_reconnects_it(bridge):
    problems = facts(bridge, FRESH + "m = bpy.data.objects['Cube'].active_material\n"
                                     "for l in list(m.node_tree.links): m.node_tree.links.remove(l)\n"
                                     "RESULT = json.dumps(check())")
    assert any("isn't connected" in p["problem"] for p in problems)
    problems = facts(bridge, "material(bpy.data.objects['Cube'].active_material.name)\nRESULT = json.dumps(check())")
    assert not any("isn't connected" in p["problem"] for p in problems)


def test_a_floating_object_and_one_inside_another_are_warned_about(bridge):
    problems = facts(bridge, FRESH + "bpy.ops.mesh.primitive_uv_sphere_add(location=(5, 0, 4))\n"
                                     "bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))\n"
                                     "RESULT = json.dumps(check())")
    text = " | ".join(p["object"] + " " + p["problem"] for p in problems)
    assert "Sphere floats" in text and "mostly inside" in text


# ---------- changing the scene ----------

def test_painting_one_object_never_changes_another_that_shares_its_material(bridge):
    out = facts(bridge, FRESH +
                "cube = bpy.data.objects['Cube']\n"
                "twin = cube.copy(); twin.data = cube.data.copy(); bpy.context.collection.objects.link(twin)\n"
                "twin.data.materials[0] = cube.active_material\n"
                "paint(cube, color=(0.8, 0.02, 0.02), metallic=1.0, roughness=0.2)\n"
                "def c(o): return list(o.active_material.node_tree.nodes['Principled BSDF'].inputs['Base Color']"
                ".default_value)[:3]\n"
                "RESULT = json.dumps({'cube': c(cube), 'twin': c(twin), 'metal': cube.active_material.node_tree"
                ".nodes['Principled BSDF'].inputs['Metallic'].default_value})")
    assert out["cube"][0] > 0.7 and out["cube"][1] < 0.1
    assert out["twin"][0] == pytest.approx(0.8, abs=0.01) and out["twin"][1] == pytest.approx(0.8, abs=0.01)
    assert out["metal"] == 1.0


def test_glass_and_glow_set_the_principled_inputs_blender_4_actually_has(bridge):
    out = facts(bridge, FRESH +
                "m = paint('Cube', transmission=1.0, roughness=0.02, ior=1.45)\n"
                "g = material('Glow', emission=(0.1, 0.3, 1.0))\n"
                "p, q = m.node_tree.nodes['Principled BSDF'], g.node_tree.nodes['Principled BSDF']\n"
                "RESULT = json.dumps([p.inputs['Transmission Weight'].default_value, "
                "q.inputs['Emission Strength'].default_value, list(q.inputs['Emission Color'].default_value)])")
    assert out[0] == 1.0 and out[1] > 0 and out[2][2] == 1.0


def test_bevel_subdivide_and_smooth_change_the_mesh_that_renders(bridge):
    out = facts(bridge, FRESH +
                "cube = find('cube')\n"
                "bevel(cube)\n"
                "dg = bpy.context.evaluated_depsgraph_get()\n"
                "bevelled = len(cube.evaluated_get(dg).to_mesh().vertices)\n"
                "subdivide(cube, 2); smooth(cube)\n"
                "dg = bpy.context.evaluated_depsgraph_get()\n"
                "RESULT = json.dumps([bevelled, len(cube.evaluated_get(dg).to_mesh().vertices), "
                "all(p.use_smooth for p in cube.data.polygons)])")
    assert out[0] > 8 and out[1] > out[0] and out[2] is True


def test_placing_things_uses_their_real_bounds(bridge):
    out = facts(bridge, FRESH +
                "bpy.ops.mesh.primitive_cone_add(location=(0, 0, 7)); cone = bpy.context.object\n"
                "drop_to_floor(cone); on_cube = box(cone)[0].z\n"
                "bpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 0)); ball = bpy.context.object\n"
                "free_spot(ball)\n"
                "inside = any(o is not ball and o.type == 'MESH' and all(box(ball)[0][i] < box(o)[1][i] and "
                "box(ball)[1][i] > box(o)[0][i] for i in range(3)) for o in bpy.context.scene.objects)\n"
                "set_size('Cube', 'z', 3.0)\n"
                "RESULT = json.dumps([on_cube, inside, find('Cube').dimensions.z])")
    assert out[0] == pytest.approx(1.0, abs=1e-4)   # rests on the 2 m cube's top, not the ground
    assert out[1] is False
    assert out[2] == pytest.approx(3.0, abs=1e-4)


def test_a_render_writes_a_real_picture_and_says_whether_it_is_empty(bridge, tmp_path):
    path = str(tmp_path / "shot.png")
    out = facts(bridge, FRESH + "bpy.context.scene.render.engine = 'BLENDER_WORKBENCH'\n"
                                f"RESULT = json.dumps(render({path!r}, resolution_percent=20))")
    assert os.path.exists(path) and out["width"] == 384 and out["flat"] is False
    out = facts(bridge, "for o in list(bpy.data.objects):\n    if o.type == 'MESH': bpy.data.objects.remove(o)\n"
                        f"RESULT = json.dumps(render({path!r}, resolution_percent=20))")
    assert out["flat"] is True


# ---------- the spoken commands, end to end (the benchmark's tasks, see tests/blender_bench.py) ----------

import blender_bench      # noqa: E402
import blender_commands   # noqa: E402
import computer_use       # noqa: E402

_EVERYDAY = [t for t in blender_bench.TASKS if not t[0].startswith("ai-") and t[0] != "render"]   # render: below


@pytest.mark.parametrize("task", _EVERYDAY, ids=[t[0] for t in _EVERYDAY])
def test_an_everyday_request_really_changes_the_scene_as_asked(bridge, task, tmp_path):
    name, _, setup, requests, check = task
    bridge.run(blender_bench.RESET, timeout=30)
    home = os.path.join(os.path.dirname(blender_bridge.BRIDGE_DIR), "home")
    sentinel = os.path.join(home, "Documents", "jarvis_scene.blend")
    if os.path.exists(sentinel):
        os.remove(sentinel)
    if setup == "SENTINEL":
        with open(sentinel, "wb") as f:
            f.write(b"an older project")
    elif setup:
        assert bridge.run(setup, timeout=30)["ok"]
    session = computer_use.ControlSession(env=None)
    ctx = {"bridge": bridge, "folder": str(tmp_path), "home": home, "replies": [],
           "before": blender_bench.state(bridge), "started": time.time()}
    for text in requests:
        reply, how = blender_bench.run_request(text, session, bridge, use_ai=False, max_steps=0)
        assert how == "deterministic", f"{text!r} wasn't handled without the AI"
        ctx["replies"].append(reply)
    ctx["after"] = blender_bench.state(bridge)
    assert check(ctx) == [], ctx["replies"]


def _say(bridge, session, text):
    return " ".join(action() for _, action in blender_commands.steps_for(text, session, bridge))


def test_undo_puts_a_material_back_exactly(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    session = computer_use.ControlSession(env=None)
    before = facts(bridge, "RESULT = json.dumps(shader_values('Cube'))")
    _say(bridge, session, "make the cube frosted glass")
    assert facts(bridge, "RESULT = json.dumps(shader_values('Cube'))")["transmission"] == 1.0
    assert "undid" in _say(bridge, session, "undo")
    assert facts(bridge, "RESULT = json.dumps(shader_values('Cube'))") == before


def test_undo_brings_back_a_removed_bevel_and_an_old_name(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    session = computer_use.ControlSession(env=None)
    _say(bridge, session, "bevel the cube")
    _say(bridge, session, "remove the bevel from the cube")
    assert facts(bridge, "RESULT = json.dumps([m.type for m in find('Cube').modifiers])") == []
    _say(bridge, session, "undo")
    assert facts(bridge, "RESULT = json.dumps([m.type for m in find('Cube').modifiers])") == ["BEVEL"]
    _say(bridge, session, "rename the cube to Crate")
    _say(bridge, session, "undo")
    assert facts(bridge, "RESULT = json.dumps(sorted(o.name for o in bpy.data.objects))") == ["Camera", "Cube", "Light"]


def test_the_render_command_saves_a_real_picture_and_says_where(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    bridge.run("bpy.context.scene.render.engine = 'BLENDER_WORKBENCH'\n"
               "bpy.context.scene.render.resolution_percentage = 20", timeout=30)
    reply = _say(bridge, computer_use.ControlSession(env=None), "render the scene")
    path = reply.split("saved to ", 1)[1].rstrip(".")
    assert reply.startswith("Done — rendered a 384 by 216 picture") and os.path.exists(path)
    assert "Jarvis renders" in path   # an unsaved scene's renders go to Documents\Jarvis renders, not anywhere else


def test_a_render_of_nothing_is_reported_as_empty_not_done(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    bridge.run("bpy.context.scene.render.engine = 'BLENDER_WORKBENCH'\n"
               "bpy.context.scene.render.resolution_percentage = 20\n"
               "bpy.data.objects['Camera'].rotation_euler = (3.14159, 0, 0)", timeout=30)
    with pytest.raises(RuntimeError, match="one flat color"):
        _say(bridge, computer_use.ControlSession(env=None), "render the scene")


# ---------- the free-form AI task's loop, with a scripted AI (no model): what it is shown and what it can do ----------

def _scripted_ai(*steps):
    from types import SimpleNamespace
    remaining, prompts = list(steps), []

    def ask(messages, tools):
        prompts.append(messages[-1]["content"])
        name, args = remaining.pop(0) if remaining else ("done", {"summary": "finished"})
        call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))])
    ask.prompts = prompts
    return ask


def test_the_ai_sees_why_old_blender_code_failed_and_can_fix_it_with_the_helpers(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    old_style = ("mat = bpy.data.materials.new('Shiny')\nmat.use_nodes = True\n"
                 "mat.node_tree.nodes['Principled BSDF'].inputs['Specular'].default_value = 1.0")
    brain = _scripted_ai(("run_python", {"code": old_style}),
                         ("run_python", {"code": "paint('Cube', color=(0.8, 0.1, 0.1), metallic=1, roughness=0.1)"}),
                         ("done", {"summary": "The cube is shiny red metal."}))
    task = computer_use.BlenderComputerTask("make the cube shiny red metal", blender_bench.NoScreen(), brain, bridge,
                                            max_steps=6, log=lambda *a: None)
    assert task.run() == "The cube is shiny red metal." and task.state == "completed"
    assert "at line 3" in brain.prompts[1] and "Specular IOR Level" in brain.prompts[1]
    assert "metallic 1.00" in brain.prompts[2]   # the next look at the scene shows the change, measured
    values = facts(bridge, "RESULT = json.dumps(shader_values('Cube'))")
    assert values["metallic"] == 1.0 and values["color"][0] == pytest.approx(0.8)


def test_the_ai_cannot_finish_on_a_scene_it_broke_without_being_told_once(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    cut = ("m = bpy.data.objects['Cube'].active_material\n"
           "for l in list(m.node_tree.links): m.node_tree.links.remove(l)")
    brain = _scripted_ai(("run_python", {"code": cut}), ("done", {"summary": "done"}),
                         ("run_python", {"code": "material(find('Cube').active_material.name)"}),
                         ("done", {"summary": "fixed"}))
    task = computer_use.BlenderComputerTask("tidy the cube's material", blender_bench.NoScreen(), brain, bridge,
                                            max_steps=8, log=lambda *a: None)
    assert task.run() == "fixed"
    assert any("isn't connected" in p and "couldn't be used" in p for p in brain.prompts)
    assert not any("isn't connected" in p["problem"] for p in facts(bridge, "RESULT = json.dumps(check())"))


def test_a_table_built_from_parts_stands_together_and_moves_and_resizes_as_one(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    bridge.run("bpy.data.objects.remove(bpy.data.objects['Cube'])", timeout=10)
    build = ("top = add_box('Table Top', size=(1.2, 0.8, 0.05), at=(0, 0, 0.7), color=(0.4, 0.25, 0.1))\n"
             "legs = [add_box(f'Table Leg {i}', size=(0.06, 0.06, 0.7), at=(x, y, 0)) for i, (x, y) in "
             "enumerate([(-0.55, -0.35), (0.55, -0.35), (-0.55, 0.35), (0.55, 0.35)])]\n"
             "group('Table', [top] + legs)")
    brain = _scripted_ai(("run_python", {"code": build}), ("done", {"summary": "Built a table."}))
    session = computer_use.ControlSession(env=None)
    task = computer_use.BlenderComputerTask("build a simple table with four legs", blender_bench.NoScreen(), brain,
                                            bridge, session=session, max_steps=4, log=lambda *a: None)
    before = blender_bench.state(bridge)
    assert task.run() == "Built a table."
    ctx = {"before": before, "after": blender_bench.state(bridge), "replies": []}
    assert blender_bench._check_ai_table(ctx) == []
    problems = facts(bridge, "RESULT = json.dumps(check())")
    assert not [p for p in problems if "floats" in p["problem"] or "inside" in p["problem"]], problems
    assert session.blender_focus == "Table"   # "it" now means the table, not its last leg
    _say(bridge, session, "move it left 2 meters")
    _say(bridge, session, "make it 2.4 meters wide")
    out = facts(bridge, "lo, hi = box(find('Table'))\nleg = box(find('Table Leg 0'))\n"
                        "RESULT = json.dumps([list(lo), list(hi), list(leg[0])])")
    assert out[0][0] == pytest.approx(-3.2, abs=1e-3) and out[1][0] == pytest.approx(-0.8, abs=1e-3)
    assert out[0][2] == pytest.approx(0.0, abs=1e-4) and out[1][2] == pytest.approx(0.75, abs=1e-4)
    assert out[2][0] == pytest.approx(-2 + 2 * -0.58, abs=1e-3)   # the legs went with the top (and widened)


def test_undo_twice_walks_back_two_changes(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    session = computer_use.ControlSession(env=None)
    _say(bridge, session, "move the cube up 2 meters")
    _say(bridge, session, "make the cube red")
    _say(bridge, session, "undo")
    _say(bridge, session, "undo")
    out = facts(bridge, "RESULT = json.dumps([list(find('Cube').location), shader_values('Cube')['color']])")
    assert out[0] == pytest.approx([0, 0, 0]) and out[1] == pytest.approx([0.8, 0.8, 0.8], abs=1e-3)
    with pytest.raises(RuntimeError, match="nothing I've done"):
        _say(bridge, session, "undo")


def test_before_the_ai_changes_anything_a_copy_of_the_scene_is_kept_and_named_if_it_fails(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    brain = _scripted_ai(("run_python", {"code": "bpy.data.objects.remove(bpy.data.objects['Cube'])"}),
                         ("fail", {"reason": "I couldn't finish that."}))
    task = computer_use.BlenderComputerTask("rebuild the cube", blender_bench.NoScreen(), brain, bridge,
                                            max_steps=4, log=lambda *a: None)
    result = task.run()
    assert task.checkpoint and task.checkpoint in result and os.path.exists(task.checkpoint)
    kept = facts(bridge, f"with bpy.data.libraries.load({task.checkpoint!r}) as (src, dst):\n"
                         "    names = list(src.objects)\nRESULT = json.dumps([names, bpy.data.filepath])")
    assert "Cube" in kept[0]          # the copy has what the AI then deleted
    assert kept[1] == ""              # and the open scene still isn't tied to that copy


def test_a_render_lit_by_almost_nothing_is_called_dark(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    bridge.run("s = bpy.context.scene\ns.render.engine = 'CYCLES'\ns.cycles.samples = 4\ns.cycles.device = 'CPU'\n"
               "s.render.resolution_percentage = 10\nbpy.data.objects['Light'].data.energy = 0.001\n"
               "s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.0", timeout=30)
    try:
        reply = _say(bridge, computer_use.ControlSession(env=None), "render the scene")
    except RuntimeError as e:   # pitch black all over: an empty picture, reported as not done
        reply = str(e)
    assert "very dark" in reply or "one flat color" in reply
    assert not reply.startswith("Done") or "very dark" in reply


def test_a_group_is_described_as_one_thing_and_warned_about_when_it_floats(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    out = facts(bridge, "parts = [add_box('Shelf Board', size=(1, 0.3, 0.03), at=(5, 0, 1.2)), "
                        "add_box('Shelf Bracket', size=(0.03, 0.2, 0.15), at=(5, 0, 1.05))]\n"
                        "group('Shelf', parts)\nRESULT = json.dumps([describe(), check()])")
    said, problems = out
    assert "Shelf, a group of 2 parts, 1 by 0.3 by 0.2 metres" in said and "Shelf Board" not in said
    assert any(p["object"] == "Shelf" and "floats 1.05 m above the ground" in p["problem"] for p in problems)


def test_glass_turned_into_metal_is_no_longer_see_through(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    session = computer_use.ControlSession(env=None)
    _say(bridge, session, "make the cube glass")
    _say(bridge, session, "make the cube chrome")
    out = facts(bridge, "m = find('Cube').active_material\n"
                        "RESULT = json.dumps([shader_values('Cube'), m.diffuse_color[3]])")
    assert out[0]["transmission"] == 0.0 and out[0]["metallic"] == 1.0 and out[1] == 1.0


def test_a_floor_goes_under_everything_and_hidden_things_come_back(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    session = computer_use.ControlSession(env=None)
    assert _say(bridge, session, "add a floor").startswith("Done — I added a floor")
    out = facts(bridge, "g = find('Ground')\nRESULT = json.dumps([box(g)[1].z, box(find('Cube'))[0].z, "
                        "[p['problem'] for p in check() if p['object'] == 'Cube']])")
    assert out[0] == pytest.approx(out[1]) and not any("floats" in p for p in out[2])
    _say(bridge, session, "hide the cube")
    assert facts(bridge, "RESULT = json.dumps(find('Cube').visible_get())") is False
    _say(bridge, session, "show everything")
    assert facts(bridge, "RESULT = json.dumps(find('Cube').visible_get())") is True
    _say(bridge, session, "undo")
    assert facts(bridge, "RESULT = json.dumps(find('Cube').visible_get())") is False
    _say(bridge, session, "undo")
    assert facts(bridge, "RESULT = json.dumps(find('Cube').visible_get())") is True


def test_a_two_word_shade_reaches_the_material(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    session = computer_use.ControlSession(env=None)
    _say(bridge, session, "make the cube light blue")
    _say(bridge, session, "make the cube dark green glass")
    values = facts(bridge, "RESULT = json.dumps(shader_values('Cube'))")
    assert values["color"] == pytest.approx(list(blender_commands._COLORS["dark green"]), abs=1e-3)
    assert values["transmission"] == 1.0


def test_after_each_script_the_ai_is_told_what_really_changed(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    brain = _scripted_ai(("run_python", {"code": "bpy.data.objects['Cube'].location.z += 3"}),
                         ("run_python", {"code": "x = 1"}),
                         ("done", {"summary": "Moved it up."}),   # stopped once: the cube now floats 2 m up
                         ("done", {"summary": "Moved it up."}))
    task = computer_use.BlenderComputerTask("move the cube up 3 meters", blender_bench.NoScreen(), brain, bridge,
                                            max_steps=5, log=lambda *a: None)
    assert task.run() == "Moved it up."
    assert "What changed in Blender: Cube: at (0, 0, 0) -> (0, 0, 3)" in brain.prompts[1]
    assert "no object in the scene changed" in brain.prompts[2]


def test_a_new_part_left_floating_stops_done_once_and_a_built_object_is_the_active_one(bridge):
    bridge.run(blender_bench.RESET, timeout=30)
    brain = _scripted_ai(("run_python", {"code": "add_box('Leg', size=(0.1, 0.1, 0.6), at=(5, -3, 0.3))\n"
                                                 "RESULT = bpy.context.object.name"}),
                         ("done", {"summary": "Built a leg."}),
                         ("run_python", {"code": "drop_to_floor('Leg')"}),
                         ("done", {"summary": "Built a leg."}))
    task = computer_use.BlenderComputerTask("build a table leg", blender_bench.NoScreen(), brain, bridge,
                                            max_steps=6, log=lambda *a: None)
    assert task.run() == "Built a leg."
    assert brain.prompts[1].count("Leg") and "Result of your last action: Leg" in brain.prompts[1]
    assert any("Leg floats 0.30 m" in p and "couldn't be used" in p for p in brain.prompts)
    assert "spans z 0.30..0.90 -> 0.00..0.60" in brain.prompts[3]


# ---------- whole buildings (blender_build.py): planned, built in stages, checked in Blender ----------

def _build(bridge, text, session=None):
    import blender_commands
    import computer_use
    session = session or computer_use.ControlSession(env=None)
    steps = blender_commands.steps_for(text, session, bridge)
    task = computer_use.ScriptedTask(text, steps, log=lambda *a: None)
    return task, task.run(), steps, session


_STATUE = (FRESH + "statue = add_sphere('My statue', 1.0, (0, 0, 0))\npaint(statue, color=(0.8, 0.1, 0.1))\n"
           "RESULT = 'ok'")


@pytest.mark.parametrize("text", ["create a villa", "build a cozy cottage", "build a traditional villa with a garden",
                                  "build me a modern three storey mansion with a pool and a garage",
                                  "crate a realistic villa"])
def test_a_building_request_builds_the_whole_building_and_checks_it_in_blender(bridge, text):
    kit(bridge, _STATUE)
    task, reply, _, _ = _build(bridge, text)
    assert task.state == "completed", reply
    assert reply.startswith("Done") and "requirements hold" in reply
    name = [o for o in json.loads(kit(bridge, "RESULT = json.dumps([o.name for o in bpy.data.objects if "
                                              "o.get('jarvis_role') == 'root'])"))][0]
    f = facts(bridge, f"RESULT = json.dumps(inspect_build({name!r}))")
    # Far more than a primitive: every kind of part a building needs, measured in Blender.
    for role in ("foundation", "slab", "wall", "interior_wall", "roof", "glass", "frame", "door", "steps", "path"):
        assert f["roles"].get(role), (role, f["roles"])
    assert f["parts"] > 30 and not f["floating"] and f["ground_gap"] == 0.0 and not f["clashes"]
    assert f["camera_sees"] and f["sun"] and f["glass_clear"]
    # A house you can walk through: every doorway, passage between its parts and stairwell is open (ray-cast).
    assert f["doorways"] and all(d["open"] for d in f["doorways"]), f["doorways"]
    if "cottage" not in text:
        assert f["roles"].get("stairs") and any(d["doorway"].endswith("stairs 1") for d in f["doorways"])
    statue = facts(bridge, "o = find('My statue')\nlo, hi = box(o)\n"
                           "RESULT = json.dumps({'at': list(o.location), 'mat': o.active_material.name, "
                           "'clear': not any(_overlap((lo, hi), box(p)) for p in bpy.data.objects "
                           "if p.get('jarvis_build') and p.type == 'MESH' and p.get('jarvis_role') != 'ground')})")
    assert statue["at"] == [0, 0, 0] and statue["mat"] == "My statue material"   # the user's work is untouched...
    assert statue["clear"]                                                          # ...and nothing was built into it


def test_the_same_request_again_rebuilds_in_place_and_never_duplicates(bridge):
    kit(bridge, FRESH + "RESULT = 'ok'")
    _build(bridge, "create a villa")
    count = "RESULT = str(len([o for o in bpy.data.objects if o.get('jarvis_build')]))"
    first = kit(bridge, count)
    task, _, _, _ = _build(bridge, "create a villa")
    assert task.state == "completed" and kit(bridge, count) == first


def test_a_wall_deleted_by_hand_is_found_missing_and_rebuilt_before_done(bridge):
    kit(bridge, FRESH + "RESULT = 'ok'")
    task, _, steps, _ = _build(bridge, "create a villa")
    assert task.state == "completed"
    kit(bridge, "bpy.data.objects.remove(bpy.data.objects['Villa main house wall front 1'], do_unlink=True)\n"
                "RESULT = 'gone'")
    verify = [action for description, action in steps if description.startswith("Checking")][0]
    assert verify().startswith("All")   # the check found it, re-ran the walls, and checked again
    assert kit(bridge, "RESULT = str('Villa main house wall front 1' in bpy.data.objects)") == "True"


def test_undo_after_a_build_removes_the_build_and_nothing_else(bridge):
    import blender_commands
    kit(bridge, _STATUE)
    _, _, _, session = _build(bridge, "create a villa")
    [(_, undo)] = blender_commands.steps_for("undo", session, bridge)
    assert undo().startswith("Done — undid: built the villa")
    left = json.loads(kit(bridge, "RESULT = json.dumps(sorted(o.name for o in bpy.data.objects))"))
    assert "My statue" in left and not any(n.startswith("Villa") for n in left)


def test_blenders_untouched_startup_lamp_goes_but_a_lamp_of_the_users_own_stays(bridge):
    kit(bridge, FRESH + "RESULT = 'ok'")   # the untouched startup scene: its lamp would glare inside the upper floor
    _build(bridge, "create a villa")
    assert kit(bridge, "RESULT = str('Light' in bpy.data.objects)") == "False"
    kit(bridge, FRESH + "bpy.data.objects['Light'].data.energy = 250\nRESULT = 'ok'")   # the user's own lamp now
    _build(bridge, "create a villa")
    assert kit(bridge, "RESULT = str(bpy.data.objects['Light'].data.energy)") == "250.0"


def test_a_wall_built_across_a_doorway_is_caught_as_a_room_you_cannot_reach(bridge):
    kit(bridge, FRESH + "RESULT = 'ok'")
    task, _, _, _ = _build(bridge, "create a villa")
    assert task.state == "completed"
    # Someone fills the doorway into the wing: the ray through the passage meets it.
    kit(bridge, "plan = json.loads(bpy.data.objects['Villa']['jarvis_plan'])\n"
                "main = plan['volumes'][0]\n"
                "o = [p for p in main['openings'] if p['kind'] == 'passage'][0]\n"
                "x = main['min'][0] + main['size'][0] - 0.125\n"
                "add_box('Blocking wall', size=(0.25, 1.4, 2.4), at=(x, main['min'][1] + o['at'], 0.55))\n"
                "RESULT = 'ok'")
    f = facts(bridge, "RESULT = json.dumps(inspect_build('Villa'))")
    assert [d["doorway"] for d in f["doorways"] if not d["open"]] == ["main house passage right"]


# ---------- editing what is there (blender_edit.py): the pool moves, the path joins, nothing is rebuilt ----------
# The follow-ups that failed on 2026-10-22, said one after another to the same scene, each checked in Blender's real
# scene by the test itself, not by trusting Jarvis's reply.

def _edit(bridge, session, text):
    steps = blender_commands.steps_for(text, session, bridge)
    assert steps is not None, f"not understood: {text}"
    task = computer_use.ScriptedTask(text, steps, log=lambda *a: None)
    return task, task.run()


def _features(bridge):
    return {f["id"]: f for f in facts(bridge, "RESULT = json.dumps(features())")}


def _centre(f):
    return [(f["lo"][i] + f["hi"][i]) / 2 for i in range(2)]


def test_a_villa_is_edited_conversationally_without_ever_being_rebuilt(bridge):
    kit(bridge, FRESH + "RESULT = 'ok'")
    session = computer_use.ControlSession(env=None)
    asked = []
    session.confirm = lambda question: asked.append(question) or True
    # 1. a simple villa with a pool
    task, reply = _edit(bridge, session, "create a villa with a pool")
    assert task.state == "completed", reply
    built = _features(bridge)
    house_uids = built["Villa/house"]["uids"]

    # 2-3. the same pool moves; the house stays exactly as it was
    task, reply = _edit(bridge, session, "move the pool more to the side")
    assert task.state == "completed", reply
    moved = _features(bridge)
    assert moved["Villa/pool"]["uids"] == built["Villa/pool"]["uids"]               # the same objects, not new ones
    assert _centre(moved["Villa/pool"])[0] - _centre(built["Villa/pool"])[0] >= 3.9   # 4 m sideways, away from it
    assert moved["Villa/house"]["uids"] == house_uids
    assert (moved["Villa/house"]["lo"], moved["Villa/house"]["hi"]) == (built["Villa/house"]["lo"],
                                                                        built["Villa/house"]["hi"])
    assert facts(bridge, "RESULT = json.dumps(clashes_of('Villa/pool'))") == []
    assert "it's now 5.8 m from the villa" in reply

    # 4-5. a path from the villa to the pool: really there, joining both, through nothing
    task, reply = _edit(bridge, session, "add a path from the villa to the pool")
    assert task.state == "completed", reply
    check = facts(bridge, "RESULT = json.dumps(check_path('Villa/path:house-pool'))")
    assert check["ok"] and check["continuous"] and check["clear"] and max(check["reaches"]) <= 0.15, check
    assert check["samples"] > 20 and check["length"] > 5
    # its far end lies against the pool's deck; it is visible and has a material
    ends = facts(bridge, "p = bpy.data.objects['Villa path villa to pool']\n"
                         "pts = json.loads(p['jarvis_points'])\n"
                         "lo, hi = box(bpy.data.objects['Villa pool deck'])\n"
                         "e = pts[-1]\n"
                         "RESULT = json.dumps({'end_on_deck_edge': lo.x - 0.05 <= e[0] <= hi.x + 0.05 and "
                         "lo.y - 0.05 <= e[1] <= hi.y + 0.05, 'mat': bool(p.active_material), "
                         "'visible': p.visible_get() and not p.hide_render})")
    assert ends == {"end_on_deck_edge": True, "mat": True, "visible": True}
    assert "front door" in reply or "glass doors" in reply   # it starts at a door of the house

    # 6-7. the pool is improved, not regenerated: every part it had is the same object, better looking
    before = _features(bridge)["Villa/pool"]
    task, reply = _edit(bridge, session, "make the pool better")
    assert task.state == "completed", reply
    after = _features(bridge)["Villa/pool"]
    assert all(after["uids"].get(name) == uid for name, uid in before["uids"].items())
    assert set(after["objects"]) > set(before["objects"])                             # steps added beside them
    water = facts(bridge, "RESULT = json.dumps(shader_values(find('Villa pool water')))")
    assert water["transmission"] > 0.5 and abs(water["ior"] - 1.33) < 0.01

    # 8. more follow-ups keep the context: "it" is the pool, the path is re-laid when the pool moves
    task, reply = _edit(bridge, session, "make it better")
    assert task.state == "completed" and "sun loungers" in reply, reply
    assert facts(bridge, "RESULT = json.dumps(inspect_build('Villa')['no_material'])") == []
    task, reply = _edit(bridge, session, "move the pool closer to the house")
    assert task.state == "completed" and "re-laid the path" in reply, reply
    assert facts(bridge, "RESULT = json.dumps(check_path('Villa/path:house-pool')['ok'])") is True
    task, reply = _edit(bridge, session, "widen the path")
    assert task.state == "completed", reply
    assert facts(bridge, "RESULT = json.dumps(check_path('Villa/path:house-pool')['width'])") > 1.2
    # a re-run of the stages that made the pool and the path builds the edited version, not the original
    pool = _features(bridge)["Villa/pool"]
    kit(bridge, "plan = json.loads(bpy.data.objects['Villa']['jarvis_plan'])\narch_extras(plan)\n"
                "arch_connections(plan)\nRESULT = 'ok'")
    again = _features(bridge)["Villa/pool"]
    assert _centre(again) == pytest.approx(_centre(pool), abs=0.02) and len(again["objects"]) == len(pool["objects"])
    assert facts(bridge, "RESULT = json.dumps(check_path('Villa/path:house-pool')['ok'])") is True
    assert _features(bridge)["Villa/house"]["uids"] == house_uids                    # never rebuilt along the way

    # 9. a missing thing and a failed edit are said plainly, and change nothing
    task, reply = _edit(bridge, session, "make the garden better")
    assert task.state == "error" and "garden" in reply and "Done" not in reply
    count = kit(bridge, "RESULT = str(len(bpy.context.scene.objects))")
    task, reply = _edit(bridge, session, "move the pool 30 m to the left")             # straight through the house
    assert task.state == "error" and "left it where it was" in reply, reply
    assert kit(bridge, "RESULT = str(len(bpy.context.scene.objects))") == count

    # 10. what is said matches the scene: delete, undo, and "delete everything" (asked first)
    task, reply = _edit(bridge, session, "delete the pool")
    assert task.state == "completed" and "Villa/pool" not in _features(bridge)
    [(_, undo)] = blender_commands.steps_for("undo", session, bridge)
    assert undo().startswith("Done — undid: removed the pool")
    assert _features(bridge)["Villa/pool"]["uids"] == again["uids"]
    task, reply = _edit(bridge, session, "delite evrything in bender")
    assert task.state == "completed" and asked, reply
    assert kit(bridge, "RESULT = str(len(bpy.context.scene.objects))") == "0"


def test_a_villa_asked_for_with_a_path_to_its_pool_gets_one_that_is_checked(bridge):
    kit(bridge, FRESH + "RESULT = 'ok'")
    task, reply, _, _ = _build(bridge, "create a villa with a pool and a path from the pool to the villa")
    assert task.state == "completed", reply
    assert "a path between the villa and the pool" in reply and "didn't model" not in reply
    f = facts(bridge, "RESULT = json.dumps(inspect_build('Villa'))")
    assert [c["between"] for c in f["connections"] if c["ok"]] == [["house", "pool"]]


def test_any_objects_can_be_moved_joined_and_improved_not_only_a_build(bridge):
    kit(bridge, FRESH + "bpy.data.objects.remove(bpy.data.objects['Cube'])\nRESULT = 'ok'")
    kit(bridge, "add_box('Shed', size=(3, 3, 2.5), at=(0, 0, 0))\nadd_cylinder('Fountain', 1.0, 0.8, (9, 4, 0))\n"
                "RESULT = 'ok'")
    session = computer_use.ControlSession(env=None)
    task, reply = _edit(bridge, session, "connect the shed and the fountain with a path")
    assert task.state == "completed", reply
    task, reply = _edit(bridge, session, "move the fountain further away from the shed")
    assert task.state == "completed" and "re-laid the path" in reply, reply
    path = [k for k, f in _features(bridge).items() if f["kind"] == "path"][0]
    assert facts(bridge, f"RESULT = json.dumps(check_path({path!r})['ok'])") is True
    task, reply = _edit(bridge, session, "make the shed better")
    assert task.state == "completed" and "rounded edges on Shed" in reply, reply


def test_building_again_over_a_changed_villa_asks_and_a_no_keeps_the_changes(bridge):
    kit(bridge, FRESH + "RESULT = 'ok'")
    session = computer_use.ControlSession(env=None)
    _edit(bridge, session, "create a villa with a pool")
    _edit(bridge, session, "move the pool to the side")
    pool = _features(bridge)["Villa/pool"]
    asked = []
    session.confirm = lambda question: asked.append(question) or False
    task, reply = _edit(bridge, session, "create a villa with a pool")
    assert task.state == "error" and "left the villa as it is" in reply
    assert "moved the pool" in asked[0]
    assert _features(bridge)["Villa/pool"]["uids"] == pool["uids"]
