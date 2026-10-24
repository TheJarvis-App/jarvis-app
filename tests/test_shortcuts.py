"""The window's keyboard shortcuts (keys.js): F, G, P, E, M and "/" work whatever the keyboard layout (with the keyboard
in Hebrew F types "כ" and "/" types "."), never fire while typing in any text field (Coding Mode's chat is a text
area), and wait while Coding Mode has the screen, except F. keys.js runs here in Node, as the page runs it."""
import fnmatch
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")


def run(cases: list) -> list:
    """Each case: {"e": event fields (target as {tagName, type, isContentEditable}), "name", "opts", "modal"}."""
    script = f"""
const keys = require({json.dumps(os.path.join(ROOT, 'keys.js'))});
const cases = {json.dumps(cases)};
console.log(JSON.stringify(cases.map((c) => {{
  keys.modal = () => Boolean(c.modal);
  const e = Object.assign({{ key: '', code: '', metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, repeat: false, isComposing: false }}, c.e);
  return c.fn === 'typing' ? keys.typing(e) : keys.shortcut(e, c.name, c.opts || {{}});
}})));"""
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


BODY = {"tagName": "BODY"}


@pytest.mark.parametrize("name, key, code", [
    ("f", "f", "KeyF"), ("f", "F", "KeyF"),            # US layout, with or without Shift
    ("f", "כ", "KeyF"), ("g", "ע", "KeyG"), ("p", "פ", "KeyP"), ("m", "צ", "KeyM"), ("e", "ק", "KeyE"),   # Hebrew layout
    ("/", "/", "Slash"), ("/", ".", "Slash"),          # "/" on a US keyboard; the same key in Hebrew types "."
    ("m", "m", "Semicolon"),                           # AZERTY: M is where the keycap says M
    ("f", "ф", "KeyA"),                                # Russian: "ф" sits on the A key, so by position it is A, not F
])
def test_each_shortcut_is_recognised_on_every_layout(name, key, code):
    fires = run([{"e": {"key": key, "code": code, "target": BODY}, "name": name}])[0]
    expected = not (key == "ф")            # the Russian "ф" sits on the A key, so it isn't F: position decides for non-Latin keys
    assert fires is expected


@pytest.mark.parametrize("name, key, code", [
    ("f", "a", "KeyF"),     # a Latin layout where the F position types "a" (Dvorak-like): the letter decides, not the position
    ("/", ".", "Period"),   # the full stop key is not "/"
    ("/", "?", "Slash"),    # Shift+/ is "?", not "/"
    ("g", "g", ""),         # (code missing) still the letter
])
def test_the_wrong_key_does_not_fire(name, key, code):
    assert run([{"e": {"key": key, "code": code, "target": BODY}, "name": name}])[0] is (key == "g")


@pytest.mark.parametrize("target, typing", [
    ({"tagName": "TEXTAREA"}, True),                       # Coding Mode's chat and its file editor
    ({"tagName": "INPUT", "type": "text"}, True), ({"tagName": "INPUT", "type": "search"}, True),
    ({"tagName": "INPUT", "type": ""}, True), ({"tagName": "SELECT"}, True),
    ({"tagName": "DIV", "isContentEditable": True}, True),
    ({"tagName": "INPUT", "type": "range"}, False),        # the volume slider: shortcuts still work there
    ({"tagName": "INPUT", "type": "checkbox"}, False), ({"tagName": "BUTTON"}, False), ({"tagName": "BODY"}, False),
])
def test_nothing_fires_while_typing(target, typing):
    assert run([{"fn": "typing", "e": {"target": target}}])[0] is typing
    assert run([{"e": {"key": "כ", "code": "KeyF", "target": target}, "name": "f"}])[0] is (not typing)


def test_modifiers_repeats_and_composition_are_not_shortcuts():
    base = {"key": "f", "code": "KeyF", "target": BODY}
    results = run([{"e": {**base, "metaKey": True}, "name": "f"}, {"e": {**base, "ctrlKey": True}, "name": "f"},
                   {"e": {**base, "altKey": True}, "name": "f"}, {"e": {**base, "repeat": True}, "name": "f"},
                   {"e": {**base, "isComposing": True}, "name": "f"}, {"e": {**base, "keyCode": 229}, "name": "f"}])
    assert results == [False] * 6


def test_while_coding_mode_is_open_only_full_screen_works():
    base = {"code": "KeyG", "key": "g", "target": BODY}
    assert run([{"e": base, "name": "g", "modal": True}, {"e": {**base, "key": "f", "code": "KeyF"}, "name": "f", "modal": True, "opts": {"inModal": True}},
                {"e": base, "name": "g", "modal": False}]) == [False, True, True]


def test_every_global_shortcut_goes_through_keys_js():
    """A regression guard: the old checks (e.key.toLowerCase() === 'f') ignored the keyboard layout and text areas."""
    for name in ("renderer.js", "graph.js", "planet.js", "earth.js", "coding/coding.js"):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            text = f.read()
        assert not re.search(r"e\.key\.toLowerCase\(\) === '[a-z]'", text), name
        assert not re.search(r"tagName === 'INPUT'\) return", text), name
    with open(os.path.join(ROOT, "renderer.js"), encoding="utf-8") as f:
        renderer = f.read()
    assert "keys.shortcut(e, 'f', { inModal: true })" in renderer and "keys.shortcut(e, '/')" in renderer and "keys.shortcut(e, 'm')" in renderer


def test_keys_js_is_on_the_window_even_where_node_s_module_exists():
    """Jarvis's window runs scripts with Node integration, so `module` is defined there: keys.js must still set
    window.jarvisKeys (it didn't, and every shortcut handler threw)."""
    script = (f"const vm = require('vm'); const window = {{}}; const module = {{ exports: {{}} }};"
              f"vm.runInNewContext(require('fs').readFileSync({json.dumps(os.path.join(ROOT, 'keys.js'))}, 'utf8'), {{ window, module, globalThis: window }});"
              f"console.log(typeof window.jarvisKeys.shortcut, typeof module.exports.shortcut)")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.stdout.split() == ["function", "function"], out.stderr


def test_every_script_the_window_loads_is_packaged():
    with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as f:
        page = f.read()
    with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as f:
        packaged = json.load(f)["build"]["files"]
    local = [src for src in re.findall(r'<(?:script|link)[^>]+(?:src|href)="([^"]+)"', page) if not re.match(r"^(?:https?:|data:|#)", src)]
    assert "keys.js" in local and local.index("keys.js") < local.index("renderer.js")
    for src in local:
        assert any(fnmatch.fnmatch(src, pattern.replace("**", "*")) or src == pattern for pattern in packaged), src
