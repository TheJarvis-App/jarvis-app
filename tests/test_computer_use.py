"""The computer-control loop, on a pretend screen with a scripted AI: what reaches the mouse, and what never does."""
import json
import re
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import computer_use
from computer_use import ComputerTask, Element, Environment, Observation


class FakeScreen(Environment):
    """A tiny app: a search field, a Search button, a Send button, a password field. Records every action."""
    name = "fake"

    def __init__(self):
        self.actions = []
        self.query = ""
        self.results = False
        self.cursor_at = (500, 500)
        self.user_moves_mouse_after = None   # step number at which "the user" grabs the mouse

    def available(self):
        return True, ""

    def observe(self):
        elements = [
            Element(1, "search field", "Search", self.query, (10, 10, 300, 30)),
            Element(2, "button", "Search", rect=(320, 10, 80, 30)),
            Element(3, "button", "Send message", rect=(420, 10, 80, 30)),
            Element(4, "text field", "Password", rect=(10, 60, 300, 30), password=True),
        ]
        if self.results:
            elements.append(Element(5, "link", f"Results for {self.query}", rect=(10, 120, 400, 20)))
        return Observation(app="FakeApp", window="Fake window", elements=elements, cursor=self.cursor_at)

    def press_element(self, element):
        self.actions.append(("press", element.name))
        if element.name == "Search" and element.role == "button":
            self.results = True
        return ""

    def click(self, point, button="left", double=False):
        self.actions.append(("click", point, button, double))
        return ""

    def type_text(self, text):
        self.actions.append(("type", text))
        self.query += text
        return ""

    def press_keys(self, keys):
        self.actions.append(("keys", "+".join(keys)))
        if keys == ["enter"]:
            self.results = True
        return ""

    def scroll(self, amount, point=None):
        self.actions.append(("scroll", amount))
        return ""

    def switch_window(self, title):
        return ""


def ai(*steps):
    """An AI that answers with these tool calls in order (then keeps saying done)."""
    remaining = list(steps)
    prompts = []

    def ask(messages, tools):
        prompts.append(messages[-1]["content"])
        name, args = remaining.pop(0) if remaining else ("done", {"summary": "finished"})
        call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))])
    ask.prompts = prompts
    return ask


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(computer_use, "SETTLE_TIMEOUT", 0.05)
    monkeypatch.setattr(computer_use, "time", SimpleNamespace(time=time.time, sleep=lambda s: None))


def test_completes_a_search_step_by_step():
    screen = FakeScreen()
    brain = ai(("type_text", {"element": 1, "text": "minecraft", "press_enter": True}),
               ("done", {"summary": "Searched for minecraft."}))
    task = ComputerTask("search for minecraft", screen, brain)
    assert task.run() == "Searched for minecraft."
    assert ("type", "minecraft") in screen.actions and ("keys", "enter") in screen.actions
    assert task.state == "completed"
    assert "Results for minecraft" in brain.prompts[-1]   # the AI saw the new result before saying done


def test_typing_replaces_a_one_line_field_but_not_a_document():
    screen = FakeScreen()
    screen.query = "old"
    ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": "new"}))).run()
    assert screen.actions[:2] == [("press", "Search"), ("keys", "ctrl+a")]

    screen = FakeScreen()
    screen.query = "old"
    ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": "new", "append": True}))).run()
    assert ("keys", "ctrl+a") not in screen.actions


def test_invalid_choices_never_reach_the_mouse():
    screen = FakeScreen()
    brain = ai(("click", {"element": 99}), ("teleport", {}), ("click", {"element": "the big one"}),
               ("done", {"summary": "ok"}))
    task = ComputerTask("do it", screen, brain)
    task.run()
    assert screen.actions == []
    assert "there is no element [99]" in brain.prompts[1]   # told why, so it can correct itself


def test_gives_up_after_repeated_unusable_answers():
    screen = FakeScreen()
    task = ComputerTask("do it", screen, ai(*[("nonsense", {})] * 10))
    assert "couldn't work out" in task.run()
    assert task.state == "error" and screen.actions == []


def test_never_types_into_a_password_field():
    screen = FakeScreen()
    brain = ai(("type_text", {"element": 4, "text": "hunter2"}), ("done", {"summary": "ok"}))
    ComputerTask("log in", screen, brain).run()
    assert ("type", "hunter2") not in screen.actions
    assert "password" in brain.prompts[1].lower()


def test_risky_step_waits_for_ok_and_is_skipped_on_no():
    screen = FakeScreen()
    asked = []
    task = ComputerTask("send it", screen, ai(("click", {"element": 3}), ("done", {"summary": "left it"})),
                        confirm=lambda q: asked.append(q) or False)
    task.run()
    assert asked and "Send message" in asked[0]
    assert ("press", "Send message") not in screen.actions


def test_risky_step_runs_after_ok():
    screen = FakeScreen()
    ComputerTask("send it", screen, ai(("click", {"element": 3})), confirm=lambda q: True).run()
    assert ("press", "Send message") in screen.actions


def _chat(focused_name, app="WhatsApp", role="text field"):
    return Observation(app=app, window="Dana", elements=[Element(1, role, focused_name, focused=True, rect=(0, 0, 9, 9))])


def test_enter_in_a_chat_needs_ok_even_when_the_box_just_has_focus():
    assert computer_use.risk_of({"action": "press_keys", "keys": "enter"}, None, _chat("Type a message"))
    assert computer_use.risk_of({"action": "type_text", "text": "hi", "press_enter": True}, None, _chat(""))


def test_enter_in_a_search_box_is_not_treated_as_sending():
    assert not computer_use.risk_of({"action": "type_text", "text": "invoices", "press_enter": True}, None,
                                    _chat("Search mail", app="Mail", role="search field"))
    assert not computer_use.risk_of({"action": "press_keys", "keys": "enter"}, None, _chat("Address", app="Safari"))


def test_emergency_stop_shortcut_is_never_pressed():
    screen = FakeScreen()
    ComputerTask("x", screen, ai(("press_keys", {"keys": "ctrl+alt+q"}), ("done", {"summary": "ok"}))).run()
    assert not any(a[0] == "keys" for a in screen.actions)


def test_stop_ends_the_task_before_the_next_action():
    screen = FakeScreen()
    task = None

    def slow_ai(messages, tools):
        task.stop()   # the user presses Stop while the AI is thinking
        call = SimpleNamespace(function=SimpleNamespace(name="click", arguments='{"element": 2}'))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))])
    task = ComputerTask("x", screen, slow_ai)
    assert "Stopped" in task.run()
    assert screen.actions == [] and task.state == "stopped"


def test_moving_the_mouse_pauses_and_resume_continues():
    """After Jarvis's step the pointer is somewhere else: the user took over, so Jarvis pauses until told to go on."""
    screen = FakeScreen()
    states = []
    task = ComputerTask("x", screen, ai(("click", {"element": 2}), ("done", {"summary": "done"})),
                        report=lambda s: states.append(s["state"]))
    settle = task._settle

    def settle_then_user_moves_mouse(before):
        after = settle(before)          # Jarvis notes where the pointer is after his step...
        screen.cursor_at = (1200, 900)  # ...and then the user grabs the mouse
        return after
    task._settle = settle_then_user_moves_mouse
    runner = threading.Thread(target=task.run)
    runner.start()
    for _ in range(500):
        if "paused" in states:
            break
        threading.Event().wait(0.01)
    assert "paused" in states and task.state == "paused"
    task.resume()
    runner.join(5)
    assert task.state == "completed"


def test_switching_to_another_app_pauses_before_typing():
    screen = FakeScreen()
    screen.focus_moved = lambda: True   # the user clicked into another app while the AI was thinking
    states = []
    task = ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": "hello"})),
                        report=lambda s: states.append(s["state"]))
    runner = threading.Thread(target=task.run)
    runner.start()
    for _ in range(500):
        if "paused" in states:
            break
        threading.Event().wait(0.01)
    task.stop()
    runner.join(5)
    assert "paused" in states and ("type", "hello") not in screen.actions


def test_nothing_is_typed_when_the_cursor_cant_be_placed():
    screen = FakeScreen()
    screen.focus_element = lambda element: "I couldn't put the cursor in it, so nothing was typed."
    brain = ai(("type_text", {"element": 1, "text": "18"}), ("done", {"summary": "ok"}))
    ComputerTask("x", screen, brain).run()
    assert not any(a[0] == "type" for a in screen.actions)
    assert "nothing was typed" in brain.prompts[1]


def test_an_action_that_keeps_changing_nothing_is_refused_then_the_task_stops():
    """Small local models loop ("click View" 20 times). Twice is allowed; after that it's refused, and then stopped."""
    screen = FakeScreen()
    brain = ai(*[("click", {"element": 1})] * 20)
    task = ComputerTask("x", screen, brain)
    assert "stuck" in task.run()
    assert screen.actions.count(("press", "Search")) == 2
    assert task.state == "error" and task.step < 10
    assert "already tried" in brain.prompts[3]


def test_many_steps_that_change_nothing_stop_the_task():
    screen = FakeScreen()
    moves = [("scroll", {"direction": d}) for d in ("up", "down")] + [("click", {"element": e}) for e in (1, 4)] \
        + [("scroll", {"direction": "down", "element": e}) for e in (1, 2, 3, 4)]
    task = ComputerTask("x", screen, ai(*moves, *moves))
    assert "stuck" in task.run()
    assert task.step == computer_use.MAX_STALE + 1   # stopped before the next step


def test_typing_only_goes_into_things_that_take_text():
    screen = FakeScreen()
    brain = ai(("type_text", {"element": 2, "text": "18"}), ("done", {"summary": "ok"}))
    ComputerTask("x", screen, brain).run()
    assert not any(a[0] == "type" for a in screen.actions)
    assert "doesn't take typing" in brain.prompts[1]


def test_an_ai_that_cant_be_reached_ends_the_task_in_plain_words():
    def down(messages, tools):
        raise computer_use.AIError("My local AI isn't running yet.")
    task = ComputerTask("x", FakeScreen(), down)
    assert task.run() == "My local AI isn't running yet. So I stopped. You have control again."
    assert task.state == "error"


def test_typing_that_never_arrives_is_put_in_directly():
    """Keys can get lost (a busy app, a remote desktop): the field is read back and filled in directly."""
    screen = FakeScreen()
    screen.type_text = lambda text: screen.actions.append(("lost", text)) or ""   # the keys go nowhere
    screen.read_value = lambda element: screen.query
    screen.set_value = lambda element, value: (setattr(screen, "query", value), screen.actions.append(("set", value)))[0] or ""
    ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": "minecraft"}), ("done", {"summary": "ok"}))).run()
    assert ("set", "minecraft") in screen.actions and screen.query == "minecraft"


def test_the_direct_fallback_never_cuts_a_long_document():
    screen = FakeScreen()
    long_text = "x" * 5000
    doc = Element(1, "text area", "Document", long_text[:200], (10, 10, 600, 400), focused=True)
    screen.observe = lambda: Observation(app="Editor", window="Doc", elements=[doc])
    screen.type_text = lambda text: ""                      # the keys go nowhere
    screen.read_value = lambda element: long_text
    stored = {}
    screen.set_value = lambda element, value: stored.setdefault("value", value) and ""
    ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": " end"}), ("done", {"summary": "ok"}))).run()
    assert stored["value"] == long_text + " end"


def test_typing_that_arrived_is_left_alone():
    screen = FakeScreen()
    screen.read_value = lambda element: screen.query
    screen.set_value = lambda element, value: pytest.fail("set_value used although the typing arrived")
    ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": "minecraft"}), ("done", {"summary": "ok"}))).run()
    assert screen.query == "minecraft"


def test_stops_after_the_step_limit():
    screen = FakeScreen()
    scroll = screen.scroll

    def scroll_and_change(amount, point=None):   # a long page: every scroll shows something new
        screen.query += "x"
        return scroll(amount, point)
    screen.scroll = scroll_and_change
    task = ComputerTask("x", screen, ai(*[("scroll", {"direction": "down"})] * 50), max_steps=5)
    assert "5 steps" in task.run()
    assert len([a for a in screen.actions if a[0] == "scroll"]) == 5


def test_tells_the_ai_when_nothing_changed():
    screen = FakeScreen()
    brain = ai(("scroll", {"direction": "down"}), ("done", {"summary": "ok"}))
    ComputerTask("x", screen, brain).run()
    assert "Nothing on screen changed" in brain.prompts[1]


def test_a_crashing_action_is_reported_not_fatal():
    screen = FakeScreen()

    def broken(amount, point=None):
        raise OSError("device gone")
    screen.scroll = broken
    brain = ai(("scroll", {"direction": "down"}), ("done", {"summary": "ok"}))
    assert ComputerTask("x", screen, brain).run() == "ok"
    assert "That action failed (OSError" in brain.prompts[1]


def test_json_text_instead_of_a_tool_call_is_understood():
    """Small local models sometimes write the call as text."""
    screen = FakeScreen()
    answers = iter(['{"name": "click", "arguments": {"element": 2}}', '{"name": "done", "arguments": {"summary": "x"}}'])

    def texty(messages, tools):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None,
                                                                                content=next(answers)))])
    assert ComputerTask("x", screen, texty).run() == "x"
    assert ("press", "Search") in screen.actions


def test_unavailable_platform_explains_itself():
    class NoScreen(Environment):
        def available(self):
            return False, "Jarvis needs permission to use this Mac."
    assert ComputerTask("x", NoScreen(), ai()).run() == "Jarvis needs permission to use this Mac."


def test_screenshots_go_local_when_the_local_model_is_available(monkeypatch):
    """When the local vision model is there, a screenshot goes to it, at the size it answers about — never online,
    even with an online AI key, unless the local model is unavailable AND online was explicitly turned on."""
    import images
    import screen_vision
    from PIL import Image
    sent = {}

    def local(paths, prompt, max_tokens):
        sent["size"] = Image.open(paths[0]).size
        return '{"bbox_2d": [0, 0, 20, 10]}'
    monkeypatch.setattr(images, "_local_vision_call", local)
    monkeypatch.setattr(images, "_groq_vision_call", lambda *a, **k: pytest.fail("a screenshot went to the online AI"))
    monkeypatch.setattr(screen_vision, "_local_available", lambda: True)
    point = screen_vision.ScreenVision().locate(Image.new("RGB", (2880, 1800)), "the logo", (1440, 900))
    assert max(sent["size"]) == images.LOCAL_VISION_MAX_DIMENSION
    assert point == (int(10 * 1440 / sent["size"][0]), int(5 * 900 / sent["size"][1]))


def test_screenshots_never_go_online_by_default(monkeypatch):
    """No local vision model, and online screen vision not turned on (the default): looking at the screen fails
    outright rather than silently sending a screenshot of the whole screen to an online service."""
    import images
    import screen_vision
    from PIL import Image
    monkeypatch.setattr(screen_vision, "_local_available", lambda: False)
    monkeypatch.setattr(images, "_groq_vision_call", lambda *a, **k: pytest.fail("a screenshot went to the online AI"))
    monkeypatch.delenv("JARVIS_SCREEN_VISION", raising=False)   # default: "local"
    with pytest.raises(images.ImageError):
        screen_vision.ScreenVision().locate(Image.new("RGB", (100, 100)), "the logo", (100, 100))


def test_screenshots_go_online_when_explicitly_turned_on(monkeypatch):
    """No local vision model, but the user explicitly set Settings, Computer control, "Look at the screen with" to
    online: a screenshot may go to Groq for this feature only."""
    import images
    import screen_vision
    from PIL import Image
    sent = {}

    def online(paths, prompt, max_tokens):
        sent["called"] = True
        return '{"bbox_2d": [0, 0, 20, 10]}'
    monkeypatch.setattr(screen_vision, "_local_available", lambda: False)
    monkeypatch.setattr(images, "_groq_vision_call", online)
    monkeypatch.setenv("JARVIS_SCREEN_VISION", "online")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    point = screen_vision.ScreenVision().locate(Image.new("RGB", (100, 100)), "the logo", (100, 100))
    assert sent.get("called") and point is not None


def test_scripted_steps_run_in_order_and_report_each_one():
    done, states = [], []
    task = computer_use.ScriptedTask("play it", [("Opening Spotify", lambda: done.append("open")),
                                                 ("Playing it", lambda: "Playing Jane! on Spotify.")],
                                     report=lambda s: states.append((s["state"], s["detail"])))
    assert task.run() == "Playing Jane! on Spotify."
    assert done == ["open"] and ("acting", "Opening Spotify") in states and states[-1][0] == "completed"


def test_stop_ends_a_scripted_task_before_the_next_step():
    done = []
    task = None
    task = computer_use.ScriptedTask("x", [("first", lambda: task.stop()), ("second", lambda: done.append("second"))])
    assert "Stopped" in task.run()
    assert done == [] and task.state == "stopped"


def test_moving_the_mouse_pauses_a_scripted_task():
    """Between two steps the pointer is somewhere else: the user took over, so Jarvis pauses."""
    positions = iter([(100, 100), (100, 100), (900, 700)])   # before step 1, after step 1, before step 2
    states, done = [], []
    task = computer_use.ScriptedTask("x", [("first", lambda: None), ("second", lambda: done.append("second"))],
                                     report=lambda s: states.append(s["state"]),
                                     cursor=lambda: next(positions, (900, 700)))
    runner = threading.Thread(target=task.run)
    runner.start()
    for _ in range(300):
        if "paused" in states:
            break
        threading.Event().wait(0.01)
    assert "paused" in states and done == []
    task.stop()
    runner.join(5)
    assert task.state == "stopped" and done == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows UI Automation")
def test_the_screen_can_be_read_from_the_computer_control_thread():
    """Computer control runs on its own thread, and UI Automation is COM, which must be started on each thread that
    uses it: without that, every task stopped at once with "Something went wrong while using the computer (OSError)"."""
    import threading
    import screen_windows
    outcome = {}

    def look():
        try:
            outcome["observation"] = screen_windows.WindowsScreen().observe()
        except Exception as e:   # the bug: OSError [WinError -2147221008] CoInitialize has not been called
            outcome["error"] = e

    worker = threading.Thread(target=look)
    worker.start()
    worker.join(30)
    assert "error" not in outcome, outcome.get("error")
    assert outcome["observation"] is not None


class MenuScreen(FakeScreen):
    """A window with an Edit menu: clicking it opens the menu and puts the focus on its first item."""

    def __init__(self):
        super().__init__()
        self.menu_open = False

    def observe(self):
        elements = [Element(1, "menu item", "Edit", rect=(10, 10, 40, 20), focused=not self.menu_open)]
        if self.menu_open:
            elements.append(Element(2, "menu item", "Undo", rect=(10, 40, 80, 20), focused=True))
        return Observation(app="notepad", window="Notes - Notepad", elements=elements, cursor=self.cursor_at)

    def press_element(self, element):
        self.actions.append(("press", element.name))
        if element.name == "Edit":
            self.menu_open = not self.menu_open
        return ""


def test_a_one_click_goal_is_done_after_the_click_that_worked():
    """"Click the Edit menu": a small AI clicked it open, then shut, open, shut… and wandered off. One action that
    changed the screen completes a one-action goal."""
    screen = MenuScreen()
    task = ComputerTask("click the Edit menu", screen, ai(*[("click", {"element": 1})] * 6),
                        finish_after={"click", "double_click", "right_click"})
    assert task.run() == "Done: click menu item “Edit”."
    assert screen.actions == [("press", "Edit")] and screen.menu_open and task.state == "completed"


def test_typing_is_refused_when_the_focus_is_on_a_menu():
    """Letters sent to an open menu are shortcuts (in Notepad's Edit menu they start "Search with Bing")."""
    screen = MenuScreen()
    screen.menu_open = True
    brain = ai(("type_text", {"text": "Edit"}), ("done", {"summary": "ok"}))
    ComputerTask("x", screen, brain).run()
    assert not any(a[0] == "type" for a in screen.actions)


# ---------- persistent sessions (ControlSession) and Blender (BlenderComputerTask) ----------

def test_listening_is_a_recognized_state():
    """ControlSession's "idle, session open, waiting for the next command" state (see app.py)."""
    assert "listening" in computer_use.STATES


def test_tidy_summary_cleans_garbled_or_structured_text_but_keeps_plain_ones():
    # A small local model's garbled/structured output must never reach the user as-is.
    assert computer_use.tidy_summary("$$", "Done.") == "Done."
    assert computer_use.tidy_summary("---", "Done.") == "Done."
    assert computer_use.tidy_summary("", "Done.") == "Done."
    assert computer_use.tidy_summary("**Cube**\n1. (Kinematic)\n$$", "Done.") == "Cube 1. (Kinematic)"
    # Plain, even terse, text is left alone.
    assert computer_use.tidy_summary("ok", "Done.") == "ok"
    assert computer_use.tidy_summary("Created a cube at the origin.", "Done.") == "Created a cube at the origin."


def test_a_garbled_done_summary_is_cleaned_before_it_becomes_the_result():
    screen = FakeScreen()
    assert ComputerTask("x", screen, ai(("done", {"summary": "$$"}))).run() == "Done."


def test_change_description_default_matches_the_old_behavior():
    """BlenderComputerTask overrides this; plain ComputerTask must behave exactly as before the hook existed."""
    screen = FakeScreen()
    task = ComputerTask("x", screen, ai())
    before = screen.observe()
    screen.results = True
    after = screen.observe()
    assert task._change_description("click", "did it.", before, after) == \
        f"did it. {computer_use.describe_change(before, after)}".strip()


def test_control_session_tracks_blender_in_front():
    screen = FakeScreen()
    session = computer_use.ControlSession(screen)
    assert session.blender_in_front() is False
    screen.observe = lambda: Observation(app="Blender", window="Untitled.blend")
    assert session.blender_in_front() is True


def test_control_session_remembers_a_bounded_history():
    session = computer_use.ControlSession(FakeScreen())
    for i in range(10):
        session.remember(f"goal {i}", f"result {i}")
    assert len(session.history) == computer_use.ControlSession.HISTORY
    assert session.history[-1] == ("goal 9", "result 9")


class FakeBridge:
    """Stands in for blender_control.BlenderBridge: no real Blender, just records what it was asked to run."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def run(self, code, timeout=20):
        self.calls.append(code)
        if "copy=True" in code:   # BlenderComputerTask's checkpoint before the first script
            return {"ok": True, "output": "1"}
        if code.endswith("json.dumps(digest())"):   # ... and its before/after look at the objects
            return {"ok": True, "output": "{}"}
        if "#ERRORS" in code:   # BlenderComputerTask's own scene-summary query
            return {"ok": True, "output": "Active: Cube. Objects: Cube (MESH) at (0, 0, 0)"}
        if self._responses:
            return self._responses.pop(0)
        return {"ok": True, "output": "Done."}


def test_blender_task_runs_python_then_finishes():
    bridge = FakeBridge(responses=[{"ok": True, "output": "Created a cube."}])
    brain = ai(("run_python", {"code": "bpy.ops.mesh.primitive_cube_add()"}), ("done", {"summary": "Created a cube."}))
    task = computer_use.BlenderComputerTask("create a cube", FakeScreen(), brain, bridge)
    assert task.run() == "Created a cube."
    assert any("primitive_cube_add" in c for c in bridge.calls)


def test_blender_task_prompt_includes_scene_summary_and_session_history():
    bridge = FakeBridge()
    session = computer_use.ControlSession(FakeScreen())
    session.remember("create a chair", "Created a chair.")
    brain = ai(("done", {"summary": "ok"}))
    task = computer_use.BlenderComputerTask("make it wooden", FakeScreen(), brain, bridge, session=session)
    task.run()
    assert "Active: Cube" in brain.prompts[0]
    assert "create a chair -> Created a chair." in brain.prompts[0]


def test_blender_task_asks_before_running_dangerous_code():
    bridge = FakeBridge()
    asked = []

    def confirm(question):
        asked.append(question)
        return False   # the user says no
    brain = ai(("run_python", {"code": "os.remove('/etc/passwd')"}), ("done", {"summary": "ok"}))
    task = computer_use.BlenderComputerTask("x", FakeScreen(), brain, bridge, confirm=confirm)
    task.run()
    assert asked and "os.remove" in asked[0]
    assert not any("os.remove" in c for c in bridge.calls)   # never actually ran


def test_blender_task_error_counts_as_no_change_for_staleness():
    """Blender's accessibility tree barely reflects a script's effect, so an error must still look like "nothing
    changed" to the base class's stale/fruitless-repeat detection (the exact sentinel it checks for)."""
    bridge = FakeBridge()
    task = computer_use.BlenderComputerTask("x", FakeScreen(), ai(), bridge)
    outcome = "The script raised an error: NameError: name 'bpy' is not defined"
    before = after = FakeScreen().observe()
    assert task._change_description("run_python", outcome, before, after) == outcome + " Nothing on screen changed."
    ok_outcome = "Created a cube."
    assert task._change_description("run_python", ok_outcome, before, after) == ok_outcome


def test_blender_task_falls_back_to_gui_tools():
    """The hybrid: a plain click still works on a BlenderComputerTask for the rare step that needs the UI."""
    screen = FakeScreen()
    brain = ai(("click", {"element": 2}), ("done", {"summary": "clicked"}))
    task = computer_use.BlenderComputerTask("x", screen, brain, FakeBridge())
    assert task.run() == "clicked"
    assert ("press", "Search") in screen.actions


def test_blender_task_cannot_claim_done_without_doing_anything():
    """A small model asserting "done" with zero real actions must never be accepted as success."""
    bridge = FakeBridge()
    brain = ai(("done", {"summary": "I created a cube."}))   # claims success, never actually ran anything
    task = computer_use.BlenderComputerTask("create a cube", FakeScreen(), brain, bridge, max_steps=6)
    result = task.run()
    assert task.state == "error"   # never silently accepted as "completed"
    assert not any("primitive" in c for c in bridge.calls)


def test_blender_task_accepts_done_after_a_real_run_python_action():
    bridge = FakeBridge(responses=[{"ok": True, "output": "Created a cube."}])
    brain = ai(("run_python", {"code": "bpy.ops.mesh.primitive_cube_add()"}), ("done", {"summary": "ok"}))
    task = computer_use.BlenderComputerTask("create a cube", FakeScreen(), brain, bridge)
    assert task.run() == "ok"
    assert task.state == "completed"


def test_blender_task_updates_session_object_context_from_free_form_code():
    """When the free-form AI creates something itself, "it" must still resolve to it afterward (see
    blender_commands.py's _resolve_reference, which reads session.blender_objects)."""
    session = computer_use.ControlSession(env=None)
    created = {"done": False}

    class Bridge:
        def run(self, code, timeout=15):
            if "o.name + ':' + o.type" in code:   # the object-name listing query
                return {"ok": True, "output": "Cube:MESH" if created["done"] else ""}
            if "primitive_cube_add" in code:
                created["done"] = True
                return {"ok": True, "output": "Created a cube."}
            return {"ok": True, "output": "(scene summary)"}
    brain = ai(("run_python", {"code": "bpy.ops.mesh.primitive_cube_add()"}), ("done", {"summary": "ok"}))
    task = computer_use.BlenderComputerTask("create a cube", FakeScreen(), brain, Bridge(), session=session)
    task.run()
    assert session.blender_objects == [{"name": "Cube", "kind": "mesh"}]


# ---------- the Blender task's look at its own work (blender_scene.py's report and check) ----------

def test_a_script_error_shows_the_exception_and_the_failing_line_first():
    import blender_control
    offset = blender_control.with_kit("").count("\n")
    error = ("Traceback (most recent call last):\n"
             f'  File "<jarvis>", line {offset + 2}, in <module>\n'
             "KeyError: 'bpy_prop_collection[key]: key \"Specular\" not found'")
    text = computer_use._script_error(error, "p = mat.node_tree.nodes['Principled BSDF']\np.inputs['Specular'] = 1")
    assert text.startswith("KeyError")
    assert "at line 2: p.inputs['Specular'] = 1" in text and "Specular IOR Level" in text


def test_blender_scripts_run_with_the_helpers_loaded():
    bridge = FakeBridge(responses=[{"ok": True, "output": "made"}])
    brain = ai(("run_python", {"code": "frame()"}), ("done", {"summary": "ok"}))
    computer_use.BlenderComputerTask("frame it", FakeScreen(), brain, bridge).run()
    sent = [c for c in bridge.calls if c.endswith("frame()")]
    assert sent and "JARVIS_KIT" in sent[0]


def test_the_blender_instructions_list_the_helpers():
    task = computer_use.BlenderComputerTask("x", FakeScreen(), ai(), FakeBridge())
    assert "paint(obj" in task.system_prompt and "frame(objects=None)" in task.system_prompt


class CheckingBridge(FakeBridge):
    """A scene whose checks find a new error once the AI's script has run."""

    def __init__(self):
        super().__init__()
        self.broken = False

    def run(self, code, timeout=20):
        self.calls.append(code)
        if "#ERRORS" in code:
            errors = ["Cube material Glass's shader isn't connected to its output"] if self.broken else []
            return {"ok": True, "output": "- Cube [mesh]\n#ERRORS " + json.dumps(errors)}
        self.broken = True
        return {"ok": True, "output": "Done."}


def test_done_is_refused_once_when_the_checks_find_a_new_problem_then_accepted():
    bridge = CheckingBridge()
    brain = ai(("run_python", {"code": "mess_up()"}), ("done", {"summary": "made it glass"}),
               ("done", {"summary": "made it glass"}))
    task = computer_use.BlenderComputerTask("make it glass", FakeScreen(), brain, bridge)
    assert task.run() == "made it glass" and task.state == "completed"
    assert any("isn't connected" in p and "couldn't be used" in p for p in brain.prompts)


def test_a_slow_script_is_reported_as_still_running_not_as_an_error():
    bridge = FakeBridge(responses=[{"ok": False, "busy": True, "error": "still working"}])
    task = computer_use.BlenderComputerTask("render", FakeScreen(), ai(), bridge)
    outcome = task._execute({"action": "run_python", "code": "render('x.png')"}, None, FakeScreen().observe())
    assert "still running" in outcome and "Don't run it again" in outcome
    assert task._did_something


# ---------- reading a small model's answer (real answers from llama3.2 through Ollama) ----------

def _texted(content):
    """An AI that answers once with `content` as text, the way small local models often do instead of a tool call."""
    def ask(messages, tools):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content=content))])
    return ask


@pytest.mark.parametrize("content,code", [
    ('{"name":"run_python","parameters":"import bpy; bpy.data.objects[\'Cube\'].location.z += 3"}',
     "import bpy; bpy.data.objects['Cube'].location.z += 3"),
    ('{"name": "run_python", "parameters": {"code": "import bpy\nbpy.ops.object.light_add(type=\'SUN\')"}}',
     "import bpy\nbpy.ops.object.light_add(type='SUN')"),
    ('{"name":"run_python","parameters":{"code":"x = 1"}}{"name":"switch_window","parameters":{"title":"Blen"}}',
     "x = 1"),
])
def test_a_tool_call_written_as_text_is_understood_however_its_arguments_were_written(content, code):
    task = computer_use.BlenderComputerTask("x", FakeScreen(), _texted(content), FakeBridge())
    tools = computer_use.BASE_TOOLS + computer_use.BLENDER_TOOLS
    action, _ = task._decide(FakeScreen().observe(), "", tools)
    assert action == {"action": "run_python", "code": code}


def test_a_native_tool_call_with_just_the_code_as_its_arguments_still_runs_it():
    call = SimpleNamespace(function=SimpleNamespace(name="run_python", arguments=json.dumps("frame()")))
    def ask(messages, tools):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))])
    task = computer_use.BlenderComputerTask("x", FakeScreen(), ask, FakeBridge())
    action, _ = task._decide(FakeScreen().observe(), "", computer_use.BASE_TOOLS + computer_use.BLENDER_TOOLS)
    assert action == {"action": "run_python", "code": "frame()"}


def test_truncated_json_arguments_are_still_refused():
    call = SimpleNamespace(function=SimpleNamespace(name="run_python", arguments='{"code": "import bpy'))
    def ask(messages, tools):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))])
    task = computer_use.BlenderComputerTask("x", FakeScreen(), ask, FakeBridge())
    action, _ = task._decide(FakeScreen().observe(), "", computer_use.BASE_TOOLS + computer_use.BLENDER_TOOLS)
    assert action.get("_bad_json") is True


@pytest.mark.parametrize("content,code", [   # real answers from qwen2.5-coder:7b once the helpers were listed
    ('{"name": "frame", "arguments": {"objects": ["Sphere", "Cube", "Cone"]}}',
     "RESULT = str(frame(objects=['Sphere', 'Cube', 'Cone']))"),
    ('```json\n{"name": "paint", "arguments": {"obj": "Cube", "color": (1, 1, 1), "metallic": 1, "roughness": 0.05}}'
     '\n```', "RESULT = str(paint('Cube', color=(1, 1, 1), metallic=1, roughness=0.05))"),
    ("run_python(bpy.ops.object.light_add(type='SUN'))", "bpy.ops.object.light_add(type='SUN')"),
    ("run_python\n```python\nx = 1\n```", "x = 1"),
])
def test_a_helper_called_like_a_tool_or_code_written_as_a_call_still_runs_as_code(content, code):
    task = computer_use.BlenderComputerTask("x", FakeScreen(), _texted(content), FakeBridge())
    tools = computer_use.BASE_TOOLS + computer_use.BLENDER_TOOLS
    action, _ = task._decide(FakeScreen().observe(), "", tools)
    assert task._validate(action, FakeScreen().observe()) == ""
    assert action == {"action": "run_python", "code": code}


def test_a_python_style_dict_answer_is_read_as_the_call_it_is():
    task = computer_use.BlenderComputerTask("x", FakeScreen(), _texted("{'name': 'open_app', 'arguments': "
                                                                       "{'name': 'Blender'}}"), FakeBridge())
    action, _ = task._decide(FakeScreen().observe(), "", computer_use.BASE_TOOLS + computer_use.BLENDER_TOOLS)
    assert action == {"action": "open_app", "name": "Blender"}


# ---------- local models' answers as text, checked before anything runs ----------

def _texty(*answers):
    """An AI that writes its answers as plain text (then keeps saying done)."""
    remaining = list(answers)
    prompts = []

    def ask(messages, tools):
        prompts.append(messages[-1]["content"])
        content = remaining.pop(0) if remaining else '{"name": "done", "arguments": {"summary": "finished"}}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content=content))])
    ask.prompts = prompts
    return ask


def test_a_run_python_call_with_broken_json_still_reaches_the_syntax_check_and_its_error_goes_back():
    # What llama3.2 really wrote for "create a villa": unescaped quotes inside the code break the JSON.
    broken = ('{"name": "run_python", "parameters": {"code": "import bpy\nbpy.ops.object.select_all(action="SELECT-all'
              '\nbpy.ops.object.delete()"}}')
    bridge = FakeBridge()
    brain = _texty(broken, '{"name": "fail", "arguments": {"reason": "gave up"}}')
    computer_use.BlenderComputerTask("create a villa", FakeScreen(), brain, bridge).run()
    assert "SyntaxError" in brain.prompts[1] and "at line 2" in brain.prompts[1]
    assert "it wasn't a tool call" not in brain.prompts[1]
    assert not any("select_all" in c for c in bridge.calls)   # nothing that can't even be parsed is sent to Blender


@pytest.mark.parametrize("answer", [
    "Here you go:\n```python\nimport bpy\nbpy.ops.mesh.primitive_cube_add()\n```",
    '{"tool_calls": [{"type": "function", "function": {"name": "run_python", "arguments": '
    '"{\\"code\\": \\"bpy.ops.mesh.primitive_cube_add()\\"}"}}]}',
    '{"function": {"name": "run_python", "arguments": {"code": "bpy.ops.mesh.primitive_cube_add()"}}}',
    '<tool_call>{"name": "run_python", "arguments": {"code": "bpy.ops.mesh.primitive_cube_add()"}}</tool_call>',
])
def test_code_written_as_a_fenced_block_or_an_openai_shaped_call_is_run(answer):
    bridge = FakeBridge()
    computer_use.BlenderComputerTask("add a cube", FakeScreen(), _texty(answer), bridge).run()
    assert any(c.endswith("bpy.ops.mesh.primitive_cube_add()") for c in bridge.calls)


class SceneBridge(FakeBridge):
    """A FakeBridge whose scene really gains objects: a script with "#ADD n" adds n meshes, seen by digest()."""

    def __init__(self):
        super().__init__()
        self.objects = {"Cube": {"type": "mesh"}}

    def run(self, code, timeout=20):
        if code.endswith("json.dumps(digest())"):
            self.calls.append(code)
            return {"ok": True, "output": json.dumps(self.objects)}
        added = re.search(r"#ADD (\d+)", code)
        if added:
            for _ in range(int(added.group(1))):
                self.objects[f"Part {len(self.objects)}"] = {"type": "mesh"}
        return super().run(code, timeout)


def test_a_table_that_is_still_one_box_is_never_reported_as_done():
    bridge = SceneBridge()
    brain = ai(("run_python", {"code": "add_box('Table', size=(1, 1, 1))  #ADD 1"}),
               *[("done", {"summary": "Built a table."})] * 5)
    task = computer_use.BlenderComputerTask("build a simple table with four legs", FakeScreen(), brain, bridge)
    result = task.run()
    assert task.state == "error"
    assert result.startswith("I stopped without finishing") and "at least 5 separate parts" in result
    assert "not yet" in brain.prompts[2]   # it was told why, and given the chance to keep building


def test_a_table_made_of_its_parts_finishes_normally():
    bridge = SceneBridge()
    brain = ai(("run_python", {"code": "top_and_legs()  #ADD 5"}), ("done", {"summary": "Built a table."}))
    task = computer_use.BlenderComputerTask("build a simple table with four legs", FakeScreen(), brain, bridge)
    assert task.run() == "Built a table." and task.state == "completed"


def test_a_free_form_house_needs_its_roof_and_door_named_before_done():
    bridge = SceneBridge()
    brain = ai(("run_python", {"code": "walls_and_windows()  #ADD 9"}), *[("done", {"summary": "Built."})] * 5)
    task = computer_use.BlenderComputerTask("build a house", FakeScreen(), brain, bridge)
    task.run()
    assert task.state == "error"
    assert any("nothing in the scene is a wall, roof, door, window" in p or "still no" in p for p in brain.prompts)


# ---------- the task's state, as the window and the overlay show it ----------

def test_a_step_can_say_what_kind_of_work_it_is():
    reported = []

    def checking():
        return "All checks pass."
    checking.state = "verifying"
    computer_use.ScriptedTask("x", [("Checking", checking)], report=reported.append).run()
    assert [r["state"] for r in reported] == ["verifying", "completed"]


def test_stopping_mid_step_says_it_is_stopping_then_stops():
    reported = []
    started, release = threading.Event(), threading.Event()

    def long_step():
        started.set()
        release.wait(5)
        return "made it"
    task = computer_use.ScriptedTask("x", [("Long", long_step), ("Never", lambda: "never")], report=reported.append)
    worker = threading.Thread(target=task.run)
    worker.start()
    started.wait(5)
    task.stop()
    assert reported[-1]["state"] == "cancelling"   # said at once, while the step is still running
    release.set()
    worker.join(5)
    assert task.state == "stopped" and [r["state"] for r in reported][-1] == "stopped"


# ---------- the closed loop: plan, re-check before acting, check "done", recover, stop at once ----------
def test_a_plan_comes_first_and_stays_in_front_of_the_ai():
    screen = FakeScreen()
    brain = ai(("plan", {"steps": ["Type minecraft in the search field", "Press Enter"]}),
               ("type_text", {"element": 1, "text": "minecraft", "press_enter": True}),
               ("done", {"summary": "Searched."}))
    states = []
    task = ComputerTask("search for minecraft", screen, brain, report=states.append, plan_first=True)
    assert task.run() == "Searched."
    assert task.plan == ["Type minecraft in the search field", "Press Enter"]
    assert "1. Type minecraft in the search field 2. Press Enter" in brain.prompts[1]
    assert states[0]["state"] == "planning" and states[-1]["plan"] == task.plan


def test_done_is_sent_back_when_the_screen_check_disagrees():
    screen = FakeScreen()
    brain = ai(("done", {"summary": "Searched."}),
               ("verdict", {"achieved": False, "evidence": "the search field is still empty."}),
               ("type_text", {"element": 1, "text": "cats", "press_enter": True}),
               ("done", {"summary": "Searched for cats."}),
               ("verdict", {"achieved": True, "evidence": "Results for cats are showing."}))
    task = ComputerTask("search for cats", screen, brain, verify=True)
    assert task.run() == "Searched for cats."
    assert ("type", "cats") in screen.actions
    assert "the search field is still empty" in brain.prompts[2]   # told why it isn't done
    assert task.verified is True
    assert [s["status"] for s in task.timeline if s["text"] == "Check the result"] == ["failed", "ok"]


def test_done_the_check_never_confirms_is_reported_as_a_failure_not_as_success():
    screen = FakeScreen()
    steps = []
    for _ in range(computer_use.MAX_DONE_REFUSALS + 1):
        steps += [("done", {"summary": "Done it."}), ("verdict", {"achieved": False, "evidence": "nothing changed."})]
    task = ComputerTask("do it", screen, ai(*steps), verify=True)
    result = task.run()
    assert task.state == "error" and task.verified is False
    assert result.startswith("I couldn't get that done properly: nothing changed.") and "Done it" not in result


def test_a_check_with_no_clear_answer_is_not_taken_as_success():
    steps = []
    for _ in range(computer_use.MAX_DONE_REFUSALS + 1):
        steps += [("done", {"summary": "Done it."}), ("verdict", {"achieved": "maybe", "evidence": ""})]
    task = ComputerTask("do it", FakeScreen(), ai(*steps), verify=True)
    task.run()
    assert task.state == "error" and task.verified is False


# ---------- typed text: never the AI's own call syntax, and checked in the app itself ----------
class FakeNotepad(FakeScreen):
    """A Notepad-like document whose text can be read back, the way Windows 11's Notepad exposes it."""

    def __init__(self, text="", garble=""):
        super().__init__()
        self.text = text
        self.garble = garble   # what a mixed-up app adds after each typing

    def observe(self):
        return Observation(app="Notepad", window="Untitled - Notepad", cursor=self.cursor_at, elements=[
            Element(1, "document", "Text editor", self.text[:40], (0, 40, 800, 500), focused=True),
            Element(2, "menu item", "File", rect=(0, 0, 40, 20))])

    def type_text(self, text):
        self.actions.append(("type", text))
        self.text += text + self.garble
        return ""

    def press_keys(self, keys):
        self.actions.append(("keys", "+".join(keys)))
        if keys == ["enter"]:
            self.text += "\n"
        return ""

    def read_value(self, element):
        return self.text if element.role == "document" else None

    def set_value(self, element, value):
        self.text = value
        return ""


def said(*texts):
    """An AI that writes its answers as plain text instead of tool calls, as small local models do."""
    remaining = list(texts)

    def ask(messages, tools):
        content = remaining.pop(0) if remaining else "done"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[], content=content))])
    return ask


SHOPPING = "open Notepad and write a shopping list: milk, eggs, bread"


@pytest.mark.parametrize("text", ['milk" {"element": 1, "press_enter": true}', '{"element": 1, "press_enter": true}',
                                  "bread', 'press_enter': True}", "type_text(milk)", "[1] document “Text editor”"])
def test_call_syntax_the_ai_puts_in_its_text_is_never_typed(text):
    notepad = FakeNotepad()
    brain = ai(("type_text", {"element": 1, "text": text}), ("fail", {"reason": "gave up"}))
    ComputerTask(SHOPPING, notepad, brain).run()
    assert notepad.actions == [] and notepad.text == ""
    assert "contains call syntax" in brain.prompts[1]   # told why, so it can try again with just the words


def test_the_real_notepad_answers_are_typed_as_just_their_words_or_refused():
    """The answers qwen2.5-coder:7b gave on 2026-10-23, which put {"element": 1, ...} into the user's Notepad."""
    notepad = FakeNotepad()
    brain = said('type_text("milk" {"element": 1, "press_enter": true})', 'type_text {"element": 1, "text": "milk"}',
                 "fail: gave up")
    ComputerTask(SHOPPING, notepad, brain).run()
    assert [a for a in notepad.actions if a[0] == "type"] == [("type", "milk")]
    assert notepad.text == "milk"


def test_calls_written_as_lines_of_name_and_json_run_in_order():
    """2026-10-23 answers: calls as text, several at once, the last one cut off. They used to be read as an action
    called "Notepad" (from "name") and thrown away."""
    class Steady(FakeNotepad):
        def still_valid(self, element=None):   # nothing else moves on this screen: planned calls may go ahead
            return True
    notepad = Steady()
    opened = []
    notepad.open_app = lambda name: opened.append(name) or ""
    brain = said('type_text {"text": "milk", "press_enter": true}\ntype_text {"text": "eggs", "press_enter": true}\n'
                 'type_text {"text":', 'open_app\n{"name": "Notepad", "arguments": {}}', "fail: gave up")
    ComputerTask(SHOPPING, notepad, brain).run()
    assert notepad.text == "milk\neggs\n" and opened == ["Notepad"]


def test_a_call_wrapped_in_the_text_argument_types_only_its_words():
    notepad = FakeNotepad()
    ComputerTask(SHOPPING, notepad, ai(("type_text", {"element": 1, "text": '{"element": 1, "text": "milk"}'}))).run()
    assert notepad.text == "milk"


def test_json_the_user_asked_for_is_still_typed():
    notepad = FakeNotepad()
    goal = 'type {"name": "Sam", "age": 3} in Notepad'
    ComputerTask(goal, notepad, ai(("type_text", {"element": 1, "text": '{"name": "Sam", "age": 3}'}))).run()
    assert notepad.text == '{"name": "Sam", "age": 3}'


def test_a_shopping_list_typed_right_is_confirmed_from_the_apps_own_text():
    notepad = FakeNotepad()
    brain = ai(("type_text", {"element": 1, "text": "Shopping list:\nmilk\neggs\nbread"}),
               ("done", {"summary": "Wrote the list."}))
    task = ComputerTask(SHOPPING, notepad, brain, verify=True)
    assert task.run() == "Wrote the list." and task.state == "completed" and task.verified is True
    assert len(brain.prompts) == 2   # settled by the text itself: the AI wasn't asked to judge its own work
    assert task.timeline[-1]["note"] == "The text in the app is exactly what you asked for."


def test_text_that_was_in_the_document_before_is_left_out_of_the_check():
    notepad = FakeNotepad(text="Notes from Monday {draft}\n")
    brain = ai(("type_text", {"element": 1, "text": "milk, eggs, bread"}), ("done", {"summary": "Wrote it."}))
    task = ComputerTask(SHOPPING, notepad, brain, verify=True)
    task.run()
    assert task.state == "completed" and task.verified is True


def test_a_missing_item_is_sent_back_even_when_the_ai_approves_its_own_work():
    notepad = FakeNotepad()
    brain = ai(("type_text", {"element": 1, "text": "milk, eggs"}), ("done", {"summary": "Wrote the list."}),
               ("type_text", {"element": 1, "text": ", bread"}), ("done", {"summary": "Wrote the list."}),
               *[("verdict", {"achieved": True, "evidence": "The list is there."})] * 3)
    task = ComputerTask(SHOPPING, notepad, brain, verify=True)
    assert task.run() == "Wrote the list."
    assert "which is missing: bread" in brain.prompts[2]
    assert notepad.text == "milk, eggs, bread" and task.verified is True


def test_corrupted_text_is_reported_as_a_failure_never_as_success():
    notepad = FakeNotepad(garble='{"element": 1}')   # the app ends up with call syntax in it
    steps = [("type_text", {"element": 1, "text": "milk, eggs, bread"})]
    steps += [("done", {"summary": "The shopping list is written."}),
              ("verdict", {"achieved": True, "evidence": "Notepad shows the list."})] * (computer_use.MAX_DONE_REFUSALS + 1)
    task = ComputerTask(SHOPPING, notepad, ai(*steps), verify=True)
    result = task.run()
    assert task.state == "error" and task.verified is False
    assert "got mixed up with my own instruction code" in result and "shopping list is written" not in result
    assert not any(s["status"] == "ok" for s in task.timeline if s["text"] == "Check the result")


def test_an_item_typed_twice_is_reported_as_a_failure():
    notepad = FakeNotepad()
    steps = [("type_text", {"element": 1, "text": "milk"}), ("type_text", {"element": 1, "text": "milk eggs bread"})]
    steps += [("done", {"summary": "Done."})] * (computer_use.MAX_DONE_REFUSALS + 1)
    task = ComputerTask(SHOPPING, notepad, ai(*steps), verify=True)
    assert "milk got typed more than once" in task.run() and task.state == "error"


@pytest.mark.parametrize("goal, pieces, whole", [
    (SHOPPING, ["milk", "eggs", "bread"], True),
    ("type hello world in notepad", ["hello world"], True),
    ("type hello in the search field and press enter", ["hello"], False),
    ("In Notepad, type “Dear Sam,” and save it", ["Dear Sam,"], False),
    ("open notepad and write a note: buy milk and eggs then save it", ["buy milk", "eggs"], False),
])
def test_the_text_a_goal_asks_for(goal, pieces, whole):
    assert computer_use.requested_text(goal) == (pieces, whole)


@pytest.mark.parametrize("goal", ["write a poem in notepad", "search for cats", "type in the search box"])
def test_goals_that_dont_spell_out_the_words_ask_for_no_exact_text(goal):
    assert computer_use.requested_text(goal) is None


def test_done_right_after_a_failed_step_is_sent_back_once():
    class Broken(FakeScreen):
        def press_element(self, element):
            raise RuntimeError("the button didn't respond")
    brain = ai(("click", {"element": 2}), ("done", {"summary": "Clicked."}), ("done", {"summary": "Clicked."}),
               ("verdict", {"achieved": True, "evidence": "ok"}))
    task = ComputerTask("press search", Broken(), brain, verify=True)
    task.run()
    assert "Your last action failed" in brain.prompts[2]
    assert task.timeline[0]["status"] == "failed"


def test_an_element_that_moved_while_the_ai_was_thinking_is_found_again(monkeypatch):
    monkeypatch.setattr(computer_use, "STALE_AFTER", -1)   # every decision counts as slow

    class Shifting(FakeScreen):
        looks = 0

        def observe(self):
            self.looks += 1
            observation = super().observe()
            if self.looks > 1:   # a banner pushed everything down after the first look
                for e in observation.elements:
                    x, y, w, h = e.rect
                    e.rect = (x, y + 100, w, h)
                    e.id += 10
            return observation

        def click(self, point, button="left", double=False):
            self.actions.append(("click", point, button, double))
            return ""
    screen = Shifting()
    ComputerTask("open the menu", screen, ai(("right_click", {"element": 2}))).run()
    assert ("click", (360, 125), "right", False) in screen.actions   # where the button is now, not where it was


def test_an_element_gone_by_the_time_of_acting_is_not_clicked(monkeypatch):
    monkeypatch.setattr(computer_use, "STALE_AFTER", -1)

    class Vanishing(FakeScreen):
        looks = 0

        def observe(self):
            self.looks += 1
            observation = super().observe()
            if self.looks > 1:
                observation.elements = [e for e in observation.elements if e.role != "button"]
            return observation
    screen = Vanishing()
    brain = ai(("click", {"element": 2}), ("fail", {"reason": "It's gone."}))
    ComputerTask("search", screen, brain).run()
    assert screen.actions == []
    assert "isn't there any more" in brain.prompts[1]


def test_a_step_that_changed_nothing_is_reported_as_recovering():
    screen = FakeScreen()
    states = []
    ComputerTask("x", screen, ai(("scroll", {"direction": "down"}), ("done", {"summary": "ok"})),
                 report=states.append).run()
    names = [s["state"] for s in states]
    assert "recovering" in names
    assert states[-1]["steps"][0]["status"] == "nochange"


def test_stop_ends_the_task_while_the_ai_is_still_thinking():
    release = threading.Event()

    def slow(messages, tools):
        release.wait(10)
        raise AssertionError("its answer must not be used")
    task = ComputerTask("x", FakeScreen(), slow)
    runner = threading.Thread(target=task.run)
    runner.start()
    while task.state != "thinking":
        time.sleep(0.01)
    started = time.time()
    task.stop()
    runner.join(5)
    release.set()
    assert not runner.is_alive() and time.time() - started < 2
    assert task.state == "stopped"


def test_a_task_past_its_time_limit_stops_in_plain_words(monkeypatch):
    task = ComputerTask("x", FakeScreen(), ai(*[("scroll", {"direction": "down"})] * 5))
    task.max_seconds = -1
    assert "took over" in task.run() and task.state == "error"


def test_each_report_carries_the_app_in_front_and_the_steps_so_far():
    states = []
    ComputerTask("x", FakeScreen(), ai(("click", {"element": 2}), ("done", {"summary": "ok"})),
                 report=states.append).run()
    last = states[-1]
    assert last["app"] == "FakeApp" and last["window"] == "Fake window"
    assert last["steps"][0] == {"n": 1, "text": "Click button “Search”", "status": "ok", "note": last["steps"][0]["note"]}


def batch_ai(*answers):
    """An AI that answers each question with several tool calls at once (then keeps saying done)."""
    remaining = list(answers)
    prompts = []

    def ask(messages, tools):
        prompts.append(messages[-1]["content"])
        calls = [SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(args)))
                 for name, args in (remaining.pop(0) if remaining else [("done", {"summary": "finished"})])]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=calls, content=""))])
    ask.prompts = prompts
    return ask


class SteadyScreen(FakeScreen):
    """A FakeScreen that can tell cheaply whether it changed, like the real Windows one."""

    def __init__(self, valid=True):
        super().__init__()
        self.valid = valid
        self.looks = 0

    def observe(self):
        self.looks += 1
        observation = super().observe()
        observation.sample = self.screen_sample()
        return observation

    def screen_sample(self):
        return f"{self.query}|{self.results}".encode().ljust(64, b" ")

    def still_valid(self, element=None):
        return self.valid


def test_actions_planned_together_run_back_to_back_without_asking_again():
    screen = SteadyScreen()
    brain = batch_ai([("type_text", {"element": 1, "text": "cats", "append": True}), ("press_keys", {"keys": "tab"}),
                      ("press_keys", {"keys": "enter"})],
                     [("done", {"summary": "Searched for cats."})])
    task = ComputerTask("search for cats", screen, brain)
    assert task.run() == "Searched for cats."
    assert screen.actions == [("press", "Search"), ("type", "cats"), ("keys", "tab"), ("keys", "enter")]
    assert len(brain.prompts) == 2   # one question for all three actions, one for "done"


def test_planned_actions_are_dropped_when_the_window_changed_under_them():
    screen = SteadyScreen(valid=False)
    brain = batch_ai([("click", {"element": 1}), ("type_text", {"text": "cats"})],
                     [("done", {"summary": "ok"})])
    ComputerTask("x", screen, brain).run()
    assert screen.actions == [("press", "Search")]   # the typing was never done blind
    assert len(brain.prompts) == 2


def test_planned_actions_stop_when_the_user_grabs_the_mouse():
    screen = SteadyScreen()
    screen.cursor = lambda: (1500, 900)   # far from where Jarvis left it
    brain = batch_ai([("click", {"element": 2}), ("click", {"element": 3})])
    task = ComputerTask("x", screen, brain)
    task._expected_cursor = (500, 500)
    task._next_queued(screen.observe())   # nothing queued yet: nothing happens
    task._queued = [({"action": "click", "element": 3}, "click")]
    task._last_status = "ok"
    assert task._next_queued(screen.observe()) is None and task._queued == []


def test_an_unchanged_screen_is_not_read_twice():
    screen = SteadyScreen()
    task = ComputerTask("x", screen, ai(("press_keys", {"keys": "tab"}), ("done", {"summary": "ok"})))
    task.run()
    # one look after the key press (when it settled), reused for the next decision instead of reading it again
    assert screen.looks == 2


def test_dragging_needs_two_real_elements_and_asks_before_dropping_on_the_bin():
    screen = FakeScreen()
    drags = []
    screen.drag = lambda start, end: drags.append((start, end)) or ""
    brain = ai(("drag", {"element": 1}), ("drag", {"element": 1, "to_element": 2}), ("done", {"summary": "ok"}))
    ComputerTask("x", screen, brain).run()
    assert "to_element must be a number" in brain.prompts[1]
    assert drags == [((160, 25), (360, 25))]

    bin_view = Observation(elements=[Element(1, "list item", "notes.txt", rect=(0, 0, 10, 10)),
                                     Element(2, "list item", "Recycle Bin", rect=(50, 0, 10, 10))])
    assert "Recycle Bin" in computer_use.risk_of({"action": "drag", "element": 1, "to_element": 2},
                                                 bin_view.elements[0], bin_view)


def test_the_element_being_acted_on_is_reported_while_acting_only():
    states = []
    ComputerTask("x", FakeScreen(), ai(("click", {"element": 2}), ("done", {"summary": "ok"})),
                 report=states.append).run()
    acting = [s for s in states if s["state"] == "acting"]
    assert acting and acting[0]["target"]["rect"] == [320, 10, 80, 30]
    assert all(s["target"] is None for s in states if s["state"] != "acting")


def test_screen_samples_differing_in_a_few_pixels_count_as_the_same_screen():
    a = bytes(15360)
    blink = bytearray(a)
    blink[100:110] = b"\xff" * 10   # a caret
    page = bytearray(a)
    page[:3000] = b"\xff" * 3000    # a new page
    assert computer_use.same_sample(a, bytes(blink))
    assert not computer_use.same_sample(a, bytes(page))
    assert not computer_use.same_sample(a, None)


def test_after_opening_an_app_the_loop_waits_for_its_window_before_reading_the_screen():
    screen = SteadyScreen()
    calls = {"since_open": None}

    def open_app(name):
        calls["since_open"] = 0
        return ""

    def sample():
        if calls["since_open"] is not None:
            calls["since_open"] += 1
            if calls["since_open"] > 4:   # the window shows up a moment later
                screen.results = True
        return f"{screen.query}|{screen.results}".encode().ljust(64, b" ")
    screen.open_app, screen.screen_sample = open_app, sample
    brain = ai(("open_app", {"name": "Notepad"}), ("done", {"summary": "ok"}))
    ComputerTask("open notepad", screen, brain).run()
    assert "Results for" in brain.prompts[1]   # the next decision saw the opened window, not the screen before it


def test_a_call_written_as_plain_words_is_understood_when_it_is_unambiguous():
    screen = FakeScreen()
    view = screen.observe()
    tools = computer_use.BASE_TOOLS
    call = ComputerTask._plain_call
    assert call("press_keys ctrl+a", view, tools) == {"action": "press_keys", "keys": "ctrl+a"}
    assert call("open_app(Notepad)", view, tools) == {"action": "open_app", "name": "Notepad"}
    assert call("click [3]", view, tools) == {"action": "click", "element": 3}
    assert call("click button “Send message”", view, tools) == {"action": "click", "element": 3}
    assert call("click button “Search”", view, tools) == {"action": "click", "element": 2}
    assert call("click “Search”", view, tools) is None          # the field and the button are both called that
    assert call("I think we should click it", view, tools) is None
    assert call("teleport there", view, tools) is None


def test_a_small_models_plain_word_answer_is_carried_out():
    screen = FakeScreen()

    def say(*answers):
        remaining = list(answers)

        def ask(messages, tools):
            text = remaining.pop(0) if remaining else '{"name": "done", "arguments": {"summary": "ok"}}'
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content=text))])
        return ask
    ComputerTask("x", screen, say("click button “Search”")).run()
    assert ("press", "Search") in screen.actions


def test_a_summary_that_is_the_calls_own_json_is_said_as_plain_words():
    said = computer_use.tidy_summary('{"summary": "Text in Notepad has been replaced."}}', "Done.")
    assert said == "Text in Notepad has been replaced."


def test_a_web_address_typed_into_the_address_bar_is_opened_but_a_search_word_is_not():
    class Browser(FakeScreen):
        def observe(self):
            bar = Element(1, "text field", "Address and search bar", self.query, (10, 10, 600, 30), focused=True)
            return Observation(app="msedge", window="New tab", elements=[bar], cursor=self.cursor_at)
    screen = Browser()
    ComputerTask("x", screen, ai(("type_text", {"text": "wikipedia.org"}))).run()
    assert ("keys", "enter") in screen.actions
    screen = Browser()
    ComputerTask("x", screen, ai(("type_text", {"text": "alan turing"}))).run()
    assert ("keys", "enter") not in screen.actions


def test_an_app_named_by_the_goal_is_brought_forward_before_the_first_decision():
    screen = FakeScreen()
    switched = []
    screen.switch_window = lambda title: switched.append(title) or ""
    ComputerTask("In Notepad, write a list", screen, ai(("done", {"summary": "ok"}))).run()
    assert switched == ["Notepad"]
    switched.clear()
    ComputerTask("open Notepad and write a list", screen, ai(("done", {"summary": "ok"}))).run()
    assert switched == []


def test_the_mouse_grabbed_while_a_step_settles_pauses_before_the_next_action():
    screen = FakeScreen()
    hand = {"at": (500, 500)}
    screen.cursor = lambda: hand["at"]
    real_observe = screen.observe

    def observe():
        if screen.actions:   # the first action is done: the user grabs the mouse while the screen settles
            hand["at"] = (1500, 900)
        return real_observe()
    screen.observe = observe
    states = []
    task = ComputerTask("x", screen, ai(("scroll", {"direction": "down"}), ("scroll", {"direction": "up"})),
                        report=lambda s: states.append(s["state"]))
    runner = threading.Thread(target=task.run)
    runner.start()
    deadline = time.time() + 5
    while "paused" not in states and time.time() < deadline:
        time.sleep(0.01)
    task.stop()
    runner.join(5)
    assert "paused" in states
    assert screen.actions == [("scroll", -5)]   # the second scroll never happened


def test_grabbing_the_mouse_while_the_ai_thinks_pauses_at_once_and_drops_that_decision():
    screen = FakeScreen()
    hand = {"at": (500, 500)}
    screen.cursor = lambda: hand["at"]
    states = []
    answers = iter([("scroll", {"direction": "down"}), ("click", {"element": 2})])

    def slow_ai(messages, tools):
        name, args = next(answers, ("done", {"summary": "ok"}))
        if name == "click":   # while this one is being thought about, the user takes the mouse
            hand["at"] = (1500, 900)
            time.sleep(0.4)
        call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))])
    task = ComputerTask("x", screen, slow_ai, report=lambda s: states.append(s["state"]))
    runner = threading.Thread(target=task.run)
    runner.start()
    deadline = time.time() + 5
    while "paused" not in states and time.time() < deadline:
        time.sleep(0.01)
    assert "paused" in states
    task.resume()
    runner.join(5)
    assert ("press", "Search") not in screen.actions   # decided before the user's move: never carried out


def test_plain_verbs_name_the_same_calls():
    view = FakeScreen().observe()
    call = ComputerTask._plain_call
    assert call("switch to “File Explorer”", view, computer_use.BASE_TOOLS) == {"action": "switch_window",
                                                                                 "title": "File Explorer"}
    assert call("press ctrl+l", view, computer_use.BASE_TOOLS) == {"action": "press_keys", "keys": "ctrl+l"}
    assert call("open Notepad", view, computer_use.BASE_TOOLS) == {"action": "open_app", "name": "Notepad"}
