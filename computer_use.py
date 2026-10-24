"""Jarvis using the computer like a person: look at the screen, decide, act, check what happened, and go on.

    goal -> OBSERVE (what's on screen) -> DECIDE (the AI picks one action) -> ACT -> OBSERVE AGAIN -> VERIFY
         -> recover if nothing happened or something unexpected appeared -> ... -> DONE (or stopped, or asks)

How the screen is read: mainly through the operating system's accessibility information (every button, field, link
and menu item of the window in front, with its name and position), which is exact, instant and needs no vision
model. Where the computer can afford it, a vision model can also look at a screenshot ("look", "click_on").
How it acts: an element's own "press" action where possible, otherwise the mouse at the element's centre, and real
keyboard input. The platform parts live in screen_windows.py and screen_mac.py.

The user stays in control:
  - it only runs when allowed (Settings: ask before each task / allowed / never),
  - a visible "AI control active" bar shows every step, with Pause and Stop,
  - moving the mouse yourself pauses it at once (you're taking over),
  - risky steps (send, delete, buy, pay, sign out...) wait for your OK,
  - it never types into password fields, and never presses Jarvis's own emergency-stop keys,
  - it stops after a fixed number of steps rather than wandering on.
"""
import hashlib
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field

MAX_STEPS = 25
MAX_STALE = 8        # steps in a row that get nowhere (nothing changed, or the answer was unusable): stuck, stop
MAX_REPEATS = 2      # the same action may change nothing this many times; after that it's refused
MAX_INVALID = 4          # the AI's answer couldn't be used this many times in a row: give up and say so
SETTLE_TIMEOUT = 4.5     # seconds to wait for the screen to settle after an action (a slower computer — Jarvis's own
                         # local AI is several GB and runs alongside everything else — just needs more of this)
SETTLE_STILL_TIMEOUT = 2.5   # with cheap screen samples: a video or an animation never holds still, stop here
TYPED_ARRIVES = 1.8      # seconds typed text may take to show up in a field before it counts as lost
MAX_BATCH = 4            # actions the AI may plan from one look at the screen; they run back to back (see _next_queued)
TAKEOVER_PIXELS = 40     # the pointer moved this far without Jarvis moving it: the user took over
MAX_ELEMENTS_SHOWN = 120
TASK_SECONDS = 15 * 60   # a task's whole working time (pauses don't count): past it, it stops however it's going
STALE_AFTER = 2.0        # a decision that took longer than this was made on an old screen: look again before acting
MAX_DONE_REFUSALS = 2    # "done" the screen check disagrees with is sent back this often, then reported as unconfirmed
TIMELINE_SHOWN = 12      # steps sent to the window with each state
# What the window registers as the emergency stop (never pressed by Jarvis himself), as said aloud.
STOP_SHORTCUT = "Control Option Q" if sys.platform == "darwin" else "Ctrl+Alt+Q"

STATES = ("starting", "planning", "observing", "thinking", "acting", "verifying", "waiting", "paused", "cancelling",
          "recovering", "listening", "completed", "stopped", "error")
# "listening": a persistent control session is open but no task is running right now (see app.py's
# ControlSession/start_computer_task) — control is still active, Jarvis is just waiting for the next command.
# "planning"/"verifying": a build's stages (blender_build.py). "cancelling": stop was asked while a step that can't
# be interrupted (a Blender script) is still finishing; the task stops right after it. "recovering": the last step
# failed or changed nothing, and the next one is being worked out differently.

# What makes a step consequential enough to ask first.
RISKY_WORDS = re.compile(
    r"\b(send|sent|post|publish|reply|tweet|delete|remove|erase|trash|discard|empty|wipe|format|uninstall|reset|"
    r"buy|purchase|order|checkout|check out|pay|payment|transfer|donate|subscribe|unsubscribe|confirm|submit|"
    r"sign out|log out|logout|sign off|close account|deactivate|change password|forget)\b", re.I)
RISKY_KEYS = {"shift+delete", "ctrl+shift+delete", "cmd+backspace", "cmd+delete", "ctrl+enter", "cmd+enter",
              "alt+f4", "cmd+q"}
FORBIDDEN_KEYS = {"ctrl+alt+q", "ctrl+alt+delete", "cmd+alt+q"}
# Blender code that reaches outside the scene it's meant to be building: still allowed, but only after asking
# (saving the file the user actually asked to save is not in this list — see BLENDER_SYSTEM_PROMPT).
BLENDER_DANGEROUS_CODE = re.compile(
    r"\b(?:os\.(?:remove|unlink|rmdir|system|popen|rename)|shutil\.\w+|subprocess\.\w+|"
    r"bpy\.ops\.wm\.(?:quit_blender|read_factory_settings|read_homefile)|__import__\(|"
    r"\bexec\(|\beval\(|urllib\.\w+|requests\.\w+|socket\.\w+)")
# Compared as sets, so "alt+ctrl+q" or "control option q" is the same shortcut.
_RISKY_COMBOS = {frozenset(k.split("+")) for k in RISKY_KEYS}
_FORBIDDEN_COMBOS = {frozenset(k.split("+")) for k in FORBIDDEN_KEYS}


@dataclass
class Element:
    id: int
    role: str
    name: str = ""
    value: str = ""
    rect: tuple = (0, 0, 0, 0)        # x, y, width, height in screen pixels
    enabled: bool = True
    focused: bool = False
    password: bool = False
    handle: object = None             # the platform's own object for the element (used to press it)

    @property
    def center(self):
        x, y, w, h = self.rect
        return (int(x + w / 2), int(y + h / 2))

    def label(self) -> str:
        text = self.name or self.value or ""
        return f"{self.role} “{text[:60]}”" if text else self.role

    def describe(self) -> str:
        parts = [f"[{self.id}] {self.role}"]
        if self.name:
            parts.append(f"“{self.name[:80]}”")
        if self.value and not self.password:
            parts.append(f"value=“{self.value[:60]}”")
        if self.password:
            parts.append("(password field)")
        if self.focused:
            parts.append("(focused)")
        if not self.enabled:
            parts.append("(disabled)")
        return " ".join(parts)


@dataclass
class Observation:
    app: str = ""
    window: str = ""
    elements: list = field(default_factory=list)
    other_windows: list = field(default_factory=list)
    screenshot: object = None          # a PIL image, when the platform can capture the screen
    screen_size: tuple = (0, 0)
    cursor: tuple = None
    note: str = ""                     # e.g. "accessibility permission is missing"
    sample: object = None              # Environment.screen_sample() when this was read: is the screen still like this?

    def element(self, element_id):
        return next((e for e in self.elements if e.id == element_id), None)

    def fingerprint(self) -> str:
        items = [(e.role, e.name, e.value, tuple(int(v) // 4 for v in e.rect), e.focused) for e in self.elements]
        digest = hashlib.sha1(json.dumps([self.app, self.window, items], default=str).encode()).hexdigest()
        if self.screenshot is not None:
            try:
                small = self.screenshot.convert("L").resize((16, 10))
                digest += hashlib.sha1(small.tobytes()).hexdigest()[:12]
            except Exception:
                pass
        return digest


SINGLE_LINE_ROLES = {"text field", "search field", "combo box"}
TEXT_ROLES = SINGLE_LINE_ROLES | {"text area", "document", "cell", "spinner"}   # the elements that take typing


class Environment:
    """What a platform provides. screen_windows.WindowsScreen and screen_mac.MacScreen implement it."""
    name = "unknown"
    select_all = ["ctrl", "a"]

    def available(self) -> tuple:
        """(True, "") if computer control can work here, else (False, what's missing, in plain words)."""
        return False, "Computer control isn't available on this computer."

    def observe(self) -> Observation:
        raise NotImplementedError

    def press_element(self, element: Element) -> str:
        return self.click(element.center)

    def click(self, point, button="left", double=False) -> str:
        raise NotImplementedError

    def type_text(self, text: str) -> str:
        raise NotImplementedError

    def press_keys(self, keys: list) -> str:
        raise NotImplementedError

    def scroll(self, amount: int, point=None) -> str:
        raise NotImplementedError

    def switch_window(self, title: str) -> str:
        raise NotImplementedError

    def open_app(self, name: str) -> str:
        from app_launcher import open_application
        return open_application(name)

    def cursor(self):
        return None

    def screen_sample(self):
        """A tiny, cheap picture of the screen (bytes) for telling whether it's still changing; None where that can't
        be done cheaply (then the loop reads the whole window again instead)."""
        return None

    def still_valid(self, element=None) -> bool:
        """The window worked in is still in front and `element` still where it was, so an action the AI planned from
        the last look can go ahead without looking again. False when it can't be told."""
        return False

    def drag(self, start, end) -> str:
        return "Dragging isn't supported on this computer."

    def focus_moved(self) -> bool:
        """True when the user has since switched to another app (not Jarvis's own window): keys must not follow."""
        return False

    def focus_element(self, element: Element) -> str:
        """Put the typing cursor in this element. "" when it's there; otherwise why not (then nothing is typed)."""
        return self.press_element(element) or ""

    def read_value(self, element: Element):
        """The element's current text, read fresh, or None if it can't be read."""
        return None

    def set_value(self, element: Element, value: str) -> str:
        """Put this text in the element directly (through accessibility, not keys). "" when done, else why not."""
        return "not supported here"


def same_sample(a, b) -> bool:
    """Whether two screen_sample pictures show the same screen: a blinking caret or a spinner doesn't count."""
    if not a or not b or len(a) != len(b):
        return False
    changed = sum(1 for x, y in zip(a, b) if abs(x - y) > 24)
    return changed <= len(a) // 500


# ---------- the actions the AI may choose (the only things it can do) ----------
def _tool(name, description, properties=None, required=()):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": list(required)}}}


_ID = {"element": {"type": "integer", "description": "The number in [brackets] from the element list."}}
BASE_TOOLS = [
    _tool("click", "Click an element (buttons, links, fields, menu items, tabs, list items).", _ID, ["element"]),
    _tool("double_click", "Double-click an element (e.g. open a file in a list).", _ID, ["element"]),
    _tool("right_click", "Right-click an element to open its menu.", _ID, ["element"]),
    _tool("drag", "Drag one element onto another (move a file into a folder, move a slider, select text by dragging).",
          {**_ID, "to_element": {"type": "integer", "description": "The number of the element to drop it on."}},
          ["element", "to_element"]),
    _tool("type_text", "Type text into `element` (or into whatever has focus). In a one-line field (text field, "
                       "search field, combo box) it replaces what's there; in a document or text area it is inserted "
                       "at the cursor.",
          {"text": {"type": "string"}, "element": {"type": "integer", "description": "Optional field to type into."},
           "press_enter": {"type": "boolean", "description": "Press Enter after typing (e.g. to search)."},
           "append": {"type": "boolean", "description": "Keep what's in a one-line field and add to the end."}},
          ["text"]),
    _tool("press_keys", "Press a key or shortcut, e.g. 'enter', 'escape', 'tab', 'ctrl+l', 'cmd+t', 'down'.",
          {"keys": {"type": "string"}}, ["keys"]),
    _tool("scroll", "Scroll the page or list up or down.",
          {"direction": {"type": "string", "enum": ["up", "down"]},
           "element": {"type": "integer", "description": "Optional: scroll inside this element."}}, ["direction"]),
    _tool("open_app", "Open (or bring forward) an app by name, e.g. 'Google Chrome', 'Settings', 'Notepad'.",
          {"name": {"type": "string"}}, ["name"]),
    _tool("switch_window", "Bring another open window to the front (use a title from 'Other windows').",
          {"title": {"type": "string"}}, ["title"]),
    _tool("wait", "Wait for something to load (1 to 5 seconds).", {"seconds": {"type": "number"}}, ["seconds"]),
    _tool("done", "The goal is achieved. Summarize what you did in one short sentence.",
          {"summary": {"type": "string"}}, ["summary"]),
    _tool("fail", "The goal can't be done (explain why in one sentence, and what the user could do).",
          {"reason": {"type": "string"}}, ["reason"]),
    _tool("ask_user", "Ask the user one short question when the goal is ambiguous (e.g. which file).",
          {"question": {"type": "string"}}, ["question"]),
]
VISION_TOOLS = [
    _tool("look", "Look at the screenshot to answer a question about what's visible (use when the element list "
                  "doesn't show what you need).", {"question": {"type": "string"}}, ["question"]),
    _tool("click_on", "Click something you can see but that isn't in the element list, by describing it.",
          {"description": {"type": "string"}}, ["description"]),
]

SYSTEM_PROMPT = """You operate the user's computer to achieve their goal, one action at a time, like a careful person.

Each turn you get: the goal, the app and window in front, a numbered list of the window's elements, other open
windows, what your last action did, and your earlier steps. Reply with one tool call — or, when the next few
actions are certain from this screen alone (click a field, type into it, press Enter), up to 4 tool calls in order:
they run back to back without looking again, and the rest are dropped if the screen changes unexpectedly.

Rules:
- Use element numbers from the CURRENT list only. Never guess coordinates.
- To type into a field, pass its number to type_text (it gets clicked first). Use press_enter to submit searches.
- To replace all the text in a document: press_keys ctrl+a, then type_text the new text (the old text is replaced).
- Browsers: ctrl+l (cmd+l on a Mac) focuses the address bar; type a search or address and press enter.
- If a popup, cookie banner or dialog appears, deal with it or dismiss it before continuing.
- If your last action changed nothing, don't repeat it: try something different (another element, a shortcut, wait).
- type_text's text is only the words that should appear on screen: never JSON, element numbers or other arguments.
- Never type passwords, payment details or personal data the user didn't give you.
- When the goal is achieved, call done with a one-sentence summary. If it truly can't be done, call fail.
- The screen not matching the goal yet (wrong text, wrong page) is your job to change, never a reason to fail.
- Stay on the user's goal; don't open things they didn't ask for."""

# Before the first step: a short plan, shown to the user and kept in front of the AI so a long task doesn't drift.
PLAN_TOOL = _tool("plan", "The steps that reach the goal, in order.",
                  {"steps": {"type": "array", "items": {"type": "string"},
                             "description": "2 to 6 short steps, each one thing to do on screen."}}, ["steps"])
PLAN_PROMPT = """You plan how to reach the user's goal on their computer, before anything is done. Given the goal and \
what is on screen now, list 2 to 6 short, concrete steps ("Open Notepad", "Type the note into the document", "Save \
with Ctrl+S"). Don't add steps the goal didn't ask for. Reply with one plan call."""

# When the AI says "done": a separate look at the screen as it is now, so success is never just claimed.
VERDICT_TOOL = _tool("verdict", "Whether the goal is achieved, judged from the screen as it is now.",
                     {"achieved": {"type": "boolean"},
                      "evidence": {"type": "string", "description": "What on screen shows it, in one short sentence."}},
                     ["achieved", "evidence"])
VERIFY_PROMPT = """You check another assistant's work on the user's computer. It says the goal is done. Judge only \
from the screen as it is now (the app in front, its window title and its elements) and the steps it took whether the \
goal is really achieved. If the screen can't show it either way (a sound played, a file saved in the background), \
judge from the steps. Reply with one verdict call."""

# An outcome that means the step itself didn't happen (as opposed to "it happened and nothing visible changed").
_FAILED_OUTCOME = re.compile(r"^(?:That action failed|The typing didn't reach|Couldn't find|No screenshot|"
                             r"The script raised an error)")


PLAIN_VERBS = {"switch-to": "switch_window", "open": "open_app", "press": "press_keys", "type": "type_text",
               "double-click": "double_click", "right-click": "right_click"}
NAMED_APP = re.compile(r"(?:in|on|using)\s+(?:the\s+)?([A-Za-z][\w .'-]{1,30}?)(?:\s+(?:app|window))?\s*,", re.I)
ADDRESS_BAR = re.compile(r"\baddress\b|enter web address|\burl\b|כתובות|כתובת", re.I)
WEB_ADDRESS = re.compile(r"(?:https?://)?(?:[\w-]+\.)+[a-z]{2,}(?:[/?#]\S*)?", re.I)

# Where Enter sends something to other people (a chat box, an email), unless it's that app's search box.
MESSAGING = re.compile(r"\b(messages?|reply|comment|chat|post|tweet|e-?mail|mail|compose|whatsapp|telegram|signal|"
                       r"slack|discord|teams|messenger|imessage|outlook|gmail|inbox|dm)\b", re.I)


def _enter_sends(target, observation) -> bool:
    if target is not None and (target.role == "search field" or re.search(r"\bsearch\b", target.name or "", re.I)):
        return False
    context = " ".join(filter(None, [target.name if target else "", target.role if target else "",
                                     observation.app if observation else "", observation.window if observation else ""]))
    return bool(MESSAGING.search(context))


def risk_of(action: dict, element, observation=None) -> str:
    """Why this step needs the user's OK first, or "" if it doesn't."""
    kind = action.get("action")
    focused = next((e for e in observation.elements if e.focused), None) if observation else None
    if kind in ("click", "double_click", "click_on"):
        text = " ".join(filter(None, [element.name if element else "", element.value if element else "",
                                      action.get("description", "")]))
        match = RISKY_WORDS.search(text)
        if match:
            return f"click “{(element.name if element else action.get('description', '')) or match.group(0)}”"
    if kind == "drag" and observation is not None:
        onto = observation.element(action.get("to_element"))
        if onto is not None and re.search(r"\brecycle bin\b|" + RISKY_WORDS.pattern, onto.name or "", re.I):
            return f"drop {element.label() if element else 'that'} on “{onto.name}”"
    if kind == "press_keys":
        combo = normalize_keys(action.get("keys", ""))
        if frozenset(combo) in _RISKY_COMBOS:
            return f"press {'+'.join(combo)}"
        if combo == ["enter"]:
            target = element or focused
            if target is not None and RISKY_WORDS.search(target.name or ""):
                return f"press Enter on “{target.name}”"
            if _enter_sends(target, observation):
                return "press Enter, which may send what's typed"
    if kind == "type_text" and action.get("press_enter") and _enter_sends(element or focused, observation):
        return f"send “{action.get('text', '')[:60]}”"
    if kind == "run_python":
        match = BLENDER_DANGEROUS_CODE.search(action.get("code", ""))
        if match:
            return f"run Blender code that does “{match.group(0)}”"
    return ""


def normalize_keys(keys: str) -> list:
    aliases = {"control": "ctrl", "command": "cmd", "option": "alt", "opt": "alt", "return": "enter",
               "esc": "escape", "del": "delete", "arrowdown": "down", "arrowup": "up", "arrowleft": "left",
               "arrowright": "right", "pgdn": "pagedown", "pgup": "pageup", "windows": "win", "meta": "cmd"}
    parts = [p.strip().lower() for p in re.split(r"[+\s]+", keys or "") if p.strip()]
    return [aliases.get(p, p) for p in parts]


def describe_change(before: Observation, after: Observation) -> str:
    """What an action did, in words the AI can reason about."""
    if before is None:
        return ""
    notes = []
    if (before.app, before.window) != (after.app, after.window):
        notes.append(f"Now in {after.app or 'another app'} — window “{after.window}”.")
    old = {(e.role, e.name) for e in before.elements}
    new = [e for e in after.elements if (e.role, e.name) not in old]
    gone = len(old - {(e.role, e.name) for e in after.elements})
    if new:
        shown = ", ".join(e.label() for e in new[:6])
        notes.append(f"{len(new)} new element(s) appeared: {shown}{'…' if len(new) > 6 else ''}.")
    if gone:
        notes.append(f"{gone} element(s) disappeared.")
    # Changed contents, for elements that can be told apart (several unnamed "text" elements can't); focused first.
    counts = {}
    for e in before.elements:
        counts[(e.role, e.name)] = counts.get((e.role, e.name), 0) + 1
    before_values = {(e.role, e.name): e.value for e in before.elements}
    changed = [e for e in after.elements if not e.password and counts.get((e.role, e.name)) == 1
               and before_values[(e.role, e.name)] != e.value]
    changed.sort(key=lambda e: not e.focused)
    for e in changed[:2]:
        what = f"[{e.id}] {e.role}" + (f" “{e.name[:60]}”" if e.name else "")
        notes.append(f"{what} now contains “{e.value[:80]}”." if e.value else f"{what} is now empty.")
    focused = next((e for e in after.elements if e.focused), None)
    before_focused = next((e for e in before.elements if e.focused), None)
    if focused and (not before_focused or (focused.role, focused.name) != (before_focused.role, before_focused.name)):
        notes.append(f"Focus is now on [{focused.id}] {focused.label()}.")
    if not notes:
        notes.append("Nothing on screen changed.")
    return " ".join(notes)


def tidy_summary(text, fallback: str, max_len: int = 200) -> str:
    """A tool call's human-facing text (done's summary, fail's reason, ask_user's question) can be markdown, several
    lines, or outright garbled — small local models especially are prone to this. None of that may reach the user
    as internal/execution-looking text; this either cleans it up or falls back to something plain and safe."""
    text = " ".join(str(text or "").split())            # collapse newlines/whitespace to single spaces
    # the call's own JSON written into the text ({"summary": "..."}}): only the words inside it
    wrapped = re.match(r'^\{\s*"(?:summary|reason|question|text)"\s*:\s*"(.*?)"\s*\}*\s*$', text)
    if wrapped:
        text = wrapped.group(1)
    text = re.sub(r"[*_`#]|\${1,2}", "", text)            # markdown emphasis/headers, stray math delimiters
    text = re.sub(r"^\d+[.)]\s*", "", text)               # a stray leading "1. "
    text = text.strip(" -•")
    if not text or not any(c.isalpha() for c in text):   # e.g. "$$", "---", "42": no actual words left
        return fallback
    return text[:max_len]


# A small model's own call written into the text it types: {"element": 1, "text": "milk"}, a tool's name, or a line of
# the prompt echoed back ("[3] document “Text editor”"). Seen for real: Notepad ended up holding these.
_ARGUMENT_KEYS = (r"element|to_element|text|press_enter|append|keys|title|name|seconds|direction|summary|reason|"
                  r"question|description|action|arguments|parameters|function|tool_calls|code")
LEAKED_SYNTAX = [
    re.compile(rf"\{{\s*[\"']?(?:{_ARGUMENT_KEYS})[\"']?\s*:|[\"'](?:{_ARGUMENT_KEYS})[\"']\s*:", re.I),
    re.compile(r"\b(?:type_text|press_keys|open_app|switch_window|double_click|right_click|ask_user|click_on|"
               r"run_python|tool_calls?)\b", re.I),
    re.compile(r"\[\d+\]\s+(?:button|link|document|text field|search field|text area|combo box|menu item|tab|"
               r"list item|check box)\b|Result of your last action|Your steps so far|Reply with one tool call", re.I),
]


def leaked_syntax(text: str, goal: str = "") -> str:
    """The piece of `text` that is the AI's own call syntax or prompt rather than words for the screen, or "".
    What the user's goal itself contains (they asked for JSON to be typed) doesn't count."""
    for pattern in LEAKED_SYNTAX:
        found = pattern.search(text or "")
        if found and not pattern.search(goal or ""):
            return found.group(0)
    return ""


def _norm(text: str) -> str:
    """Text compared the way a person reads it: case, curly quotes and spacing don't matter."""
    text = (text or "").translate(str.maketrans("“”‘’ ", "\"\"'' ")).casefold()
    return " ".join(text.split())


# What a text-entry goal asks to appear: "write a shopping list: milk, eggs, bread", "type “hello there” in Notepad",
# "open Notepad and type hello world". Anything after "then ..."/"and save ..." is another step, checked by the AI.
_QUOTED = re.compile(r"[“\"]([^”\"]+)[”\"]|(?<!\w)'([^']+)'(?!\w)")
_COLON_TEXT = re.compile(r"\b(?:write|type|jot|note|put|enter|add|make|create)\b[^:]{0,60}:\s*(.+)$", re.I | re.S)
_TYPE_TEXT = re.compile(r"\btype\s+(?!in\b|into\b|it\b|the text\b)(.+?)(?:\s+(?:in|into|on)\s+(?:the\s+)?"
                        r"[A-Za-z][\w ]{0,30}?(?:\s+(?:app|window))?)?\s*[.!]?$", re.I | re.S)
_MORE_STEPS = re.compile(r"\s*(?:,\s*)?\b(?:and then|then|and (?:save|close|send|print|press|email|share))\b.*$",
                         re.I | re.S)


def requested_text(goal: str):
    """(pieces, whole) for a goal that says what text to type: each piece must appear once, in any layout; `whole`
    is False when the goal also asks for something after the typing. None otherwise ("write a poem" says what to
    write about, not the words)."""
    goal = (goal or "").strip()
    quoted = [a or b for a, b in _QUOTED.findall(goal)]
    if quoted:
        rest = _QUOTED.sub("", goal)
        return quoted, not _MORE_STEPS.search(rest)
    cut = _MORE_STEPS.search(goal)
    head = goal[:cut.start()] if cut else goal
    match = _COLON_TEXT.search(head) or _TYPE_TEXT.search(head)
    if not match:
        return None
    whole = cut is None
    said = match.group(1).strip().rstrip(".!")
    if match.re is _TYPE_TEXT:
        return ([said], whole) if said else None
    pieces = [p.strip().rstrip(".") for p in re.split(r"\s*(?:[,;\n]|\band\b)\s*", said)]
    pieces = [p for p in pieces if p]
    return (pieces, whole) if pieces else None


def text_problem(goal: str, before: str, now: str):
    """Whether a field's text now holds what the goal asked to type, judged on what was added to it (`before` is its
    text before Jarvis typed). (problem for the AI, problem for the user), or None when it's right."""
    added = now if not before or before not in now else now.replace(before, "", 1)
    shown = " ".join(added.split())
    shown = f"“{shown[:80]}{'…' if len(shown) > 80 else ''}”"
    leak = leaked_syntax(added, goal)
    if leak:
        return (f"the text now reads {shown}: it has call syntax ({leak}) typed into it. Type only the words that "
                "should appear.", "the text in the app got mixed up with my own instruction code")
    wanted = requested_text(goal)
    if wanted is None:
        return None
    pieces = wanted[0]
    have, goal_words = _norm(added), set(re.findall(r"[^\W_]+", _norm(goal)))
    if not have:
        return "nothing has been typed into it yet.", "nothing got typed"
    missing = [p for p in pieces if _norm(p) not in have]
    if missing:
        return (f"the text now reads {shown}, which is missing: {', '.join(missing)}.",
                f"it's missing {', '.join(missing)}")
    twice = [p for p in pieces if have.count(_norm(p)) > _norm(goal).count(_norm(p))]
    if twice:
        return (f"the text now reads {shown}: {', '.join(twice)} is in it more than once.",
                f"{', '.join(twice)} got typed more than once")
    rest = have
    for p in sorted(pieces, key=len, reverse=True):
        rest = rest.replace(_norm(p), " ")
    extra = [w for w in re.findall(r"[^\W_]+", rest) if w not in goal_words]
    if extra:
        return (f"the text now reads {shown}, with words that weren't asked for: {' '.join(extra[:6])}.",
                "the app has extra text I didn't mean to type")
    return None


def _first_json_object(text: str):
    """The first JSON object in `text` (line breaks inside its strings allowed) — or, failing that, the first
    Python-style dict ({'name': 'x', 'arguments': {'color': (1, 0, 0)}}, which small models also write). None if
    there's neither."""
    decoder = json.JSONDecoder(strict=False)
    start = text.find("{")
    while start != -1:
        try:
            return decoder.raw_decode(text[start:])[0]
        except ValueError:
            pass
        end = _closing_brace(text, start)
        if end:
            try:
                import ast
                value = ast.literal_eval(text[start:end + 1])
                if isinstance(value, dict):
                    return value
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                pass
        start = text.find("{", start + 1)
    return None


def _closing_brace(text: str, start: int):
    """Where the brace opened at `start` closes (quotes respected), or None."""
    depth, quote = 0, None
    for i in range(start, len(text)):
        c = text[i]
        if quote:
            if c == quote and text[i - 1] != "\\":
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _run_python_text(text: str):
    """The code in a run_python call written as text — run_python(bpy.ops.object.light_add(type='SUN')), or
    run_python followed by a fenced block — or None."""
    t = text.strip().strip("`").strip()
    m = re.match(r"run_python\b\s*", t, re.I)
    if not m:
        return None
    code = t[m.end():].strip()
    if code.startswith("(") and code.endswith(")"):
        code = code[1:-1].strip()
    code = re.sub(r"^code\s*=\s*", "", code)
    code = re.sub(r"^```\w*\s*|\s*```$", "", code).strip()
    if len(code) > 1 and code[0] == code[-1] and code[0] in "'\"":
        code = code[1:-1]
    return code if code and not code.startswith("{") else None


_LOOSE_CODE = re.compile(r'"code"\s*:\s*"(?P<code>.*)"\s*\}\s*\}?\s*(?:</tool_call>)?\s*$', re.S)
_FENCED = re.compile(r"```(?:python|py)?[ \t]*\n(?P<code>.*?)```", re.S | re.I)


def _loose_code(text: str):
    """run_python's code from a call whose JSON is broken — usually by unescaped quotes inside the code
    ({"name": "run_python", "parameters": {"code": "bpy.ops.object.select_all(action="SELECT")"}}). The code is
    still worth running through the compile check: a precise syntax error teaches the model more than "that wasn't
    a tool call" does."""
    if "run_python" not in text:
        return None
    m = _LOOSE_CODE.search(text)
    if not m:
        return None
    code = m.group("code")
    for escaped, plain in (("\\n", "\n"), ("\\t", "\t"), ('\\"', '"'), ("\\\\", "\\")):
        code = code.replace(escaped, plain)
    return code.strip() or None


def _fenced_code(text: str):
    """A bare ```python block with Blender code in it, written instead of a tool call."""
    m = _FENCED.search(text)
    code = m.group("code").strip() if m else ""
    return code if "bpy" in code else None


def _written_calls(text: str, tools: list) -> list:
    """Calls a small model wrote as lines of `tool_name {json}` instead of tool calls, often several at once:
    open_app {"name": "Notepad", "arguments": {}} / type_text {"text": "milk", "press_enter": true}. [(name, args)];
    a call whose JSON doesn't close (an answer cut off) ends the list."""
    names = {t["function"]["name"] for t in tools}
    calls = []
    for m in re.finditer(r"(?m)^[ \t]*(?:\d+[.)][ \t]*)?(\w+)[ \t]*[:(]?[ \t]*\n?[ \t]*(?=\{)", text):
        if m.group(1) not in names:
            continue
        end = _closing_brace(text, m.end())
        given = _first_json_object(text[m.end():end + 1]) if end else None
        if not isinstance(given, dict):
            break
        for wrapper in ("arguments", "parameters"):   # {"name": "Notepad", "arguments": {}}: the call's own wrapper
            inner = given.pop(wrapper, None)
            if isinstance(inner, dict):
                given.update(inner)
        calls.append((m.group(1), given))
    return calls


def _arguments(name: str, given, tools: list):
    """A tool call's arguments as a dict, however the AI wrote them: an object, an object in JSON text (raw line
    breaks allowed), or just the value of a tool's one required parameter (run_python's code as a plain string).
    None when they're broken JSON."""
    if isinstance(given, str):
        try:
            given = json.loads(given, strict=False)
        except ValueError:
            if given.lstrip().startswith("{"):
                return None
    if isinstance(given, dict):
        for key, value in list(given.items()):   # {"title": "{\"title\": \"Notepad\"}"}: the value it wraps
            if isinstance(value, str) and value.lstrip().startswith("{"):
                try:
                    inner = json.loads(value)
                except ValueError:
                    continue
                if isinstance(inner, dict) and isinstance(inner.get(key), str):
                    given[key] = inner[key]
        return given
    tool = next((t["function"] for t in tools if t["function"]["name"] == name), None)
    required = (tool or {}).get("parameters", {}).get("required") or []
    if len(required) == 1 and isinstance(given, str) and given.strip():
        return {required[0]: given}
    return {}


class AIError(Exception):
    """The AI couldn't be asked what to do next. The message is for the user."""


class InputBlocked(Exception):
    """The system refused the key presses or clicks, so no step can work."""


class _Stopped(Exception):
    """Stop was asked while waiting for the AI: the task ends without waiting for its answer."""


class ControlSession:
    """A persistent "take control of my computer" session: it outlives any single goal. Created once, when control
    is first granted; the same session then runs every goal the user gives until they explicitly say stop. See
    app.py's start_computer_task / handle_control_voice."""

    HISTORY = 6

    def __init__(self, env: Environment):
        self.env = env
        self.blender = None          # a blender_control.BlenderBridge, once a Blender goal has attached one
        self.history = []            # [(goal, result)], most recent last — short context for later goals
        # Which Blender objects exist and in what order, so "it" / "the second one" / "the cube" resolve without
        # asking the AI to remember — see blender_commands.py. Kept in sync by both the deterministic commands
        # there and BlenderComputerTask (when the free-form AI creates something new itself).
        self.blender_objects = []    # [{"name": "Cube.001", "kind": "cube"}], creation order
        self.blender_focus = None    # the object the last Blender command worked on: what "it" means next
        # ... or the feature ("Villa/pool") the last edit or build worked on — see blender_edit.py; whichever was
        # touched last is what "it" means (each one clears the other).
        self.blender_feature = None
        self.confirm = None          # question -> bool, for a destructive step ("delete everything") mid-task
        self.last_deterministic_text = None   # the last recognized blender_commands text, for "do that again"
        self._undo = []   # [{"description", "code"}]: how to reverse each deterministic action, newest last
        self.started_at = time.time()
        self.last_activity = time.time()

    def remember(self, goal: str, result: str) -> None:
        self.history.append((goal, result))
        del self.history[:-self.HISTORY]
        self.last_activity = time.time()

    def blender_in_front(self) -> bool:
        """Is Blender the app currently in front? Used to keep routing goals to it without saying "in Blender"
        every time, for as long as it stays the window being worked in."""
        try:
            return "blender" in (self.env.observe().app or "").lower()
        except Exception:
            return False

    def remember_blender_object(self, name: str, kind: str = "") -> None:
        if name and not any(o["name"] == name for o in self.blender_objects):
            self.blender_objects.append({"name": name, "kind": (kind or "").lower()})
            del self.blender_objects[:-20]

    @property
    def last_blender_object(self):
        return self.blender_objects[-1]["name"] if self.blender_objects else None

    UNDO_STEPS = 20

    @property
    def last_undo(self):
        """How to reverse the newest deterministic action ({"description", "code"}), for "undo"; None if none."""
        return self._undo[-1] if self._undo else None

    @last_undo.setter
    def last_undo(self, value):
        # Setting records one more step; None means the newest was just undone, so "undo" again reaches the one
        # before it (a single slot only ever allowed one undo).
        if value is None:
            if self._undo:
                self._undo.pop()
        else:
            self._undo.append(value)
            del self._undo[:-self.UNDO_STEPS]


class ComputerTask:
    """One goal, carried out step by step on its own thread. Drive it with pause(), resume(), stop().

    `plan_first`: ask the AI for a short plan before the first step. `verify`: when the AI says done, check the
    screen separately before believing it (see _check_done). `preview`: called with each fresh Observation, so the
    window can show what Jarvis sees."""
    max_elements = MAX_ELEMENTS_SHOWN
    max_seconds = TASK_SECONDS
    max_batch = MAX_BATCH

    def __init__(self, goal: str, env: Environment, ask_ai, report=None, confirm=None, vision=None,
                 max_steps: int = MAX_STEPS, log=print, finish_after=None, plan_first=False, verify=False,
                 preview=None):
        self.goal = goal
        # A one-action goal ("click the Edit menu"): done as soon as an action of these kinds changes the screen,
        # instead of relying on the AI to notice (a small model clicks the menu shut again, then wanders off).
        self.finish_after = set(finish_after or ())
        self.env = env
        self.ask_ai = ask_ai            # (messages, tools) -> OpenAI-style response (Jarvis's own AI plumbing)
        self.report = report or (lambda state: None)
        self.confirm = confirm or (lambda question: False)   # blocking; True = the user said yes
        self.vision = vision            # optional: object with look(image, question) and locate(image, description)
        self.max_steps = max_steps
        self.log = log
        self.system_prompt = SYSTEM_PROMPT   # overridden by BlenderComputerTask
        self.extra_tools = []                # tools this task adds on top of BASE_TOOLS (BlenderComputerTask: run_python)
        self.history = []               # [(action description, what happened)]
        self._fruitless = {}            # action description -> how often it changed nothing
        self._stop = threading.Event()
        self._running = threading.Event()
        self._running.set()
        self.state = "starting"
        self.result = ""
        self.step = 0
        self._expected_cursor = None
        self.plan_first = plan_first
        self.verify = verify
        self.preview = preview
        self.plan = []                  # the AI's steps, as the user sees them
        self.timeline = []              # [{"n", "text", "status", "note"}]: what each step did, for the window
        self.app = ""                   # what's in front, as last seen
        self.window = ""
        self.verified = None            # True: the screen check confirmed "done"; False: it didn't; None: not checked
        self._doubt = ""                # what the screen check said was still missing
        self._done_refusals = 0
        self._recovering = False        # the last step failed or changed nothing
        self._last_status = ""
        self._paused_seconds = 0.0
        self._queued = []               # [(action, raw)]: the rest of the actions the AI planned from its last look
        self._target = None             # what is being acted on, for the window: {"rect", "screen"}
        self._kind = ""                 # the kind of action being carried out (see _settle)
        self._grabbed = False           # the user took the mouse while the AI was thinking (see _ask)
        self._typed = {}                # (role, name) of each field typed into -> its text before the first typing
        self._typed_last = None         # the one typed into last: what a text goal is checked against

    # ---------- control from outside (voice, the window, the emergency shortcut) ----------
    def stop(self):
        already = self._stop.is_set()
        self._stop.set()
        self._running.set()   # wake a paused task so it can stop
        if not already and self.state in ("planning", "observing", "thinking", "acting", "verifying", "waiting"):
            # A step under way (a Blender script, the AI's answer) can't be cut off mid-way: say it's stopping.
            self._report("cancelling", "Stopping after the current step…")

    def pause(self, why: str = "Paused. Say “continue” or press Resume.") -> None:
        if not self._stop.is_set():
            self._running.clear()
            self._report("paused", why)

    def resume(self) -> None:
        self._expected_cursor = None   # the user may have moved the pointer while paused
        self._running.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _report(self, state: str, detail: str = "") -> None:
        self.state = state
        try:
            self.report({"state": state, "detail": detail, "goal": self.goal, "step": self.step,
                         "maxSteps": self.max_steps, "app": self.app, "window": self.window,
                         "steps": self.timeline[-TIMELINE_SHOWN:], "plan": self.plan, "verified": self.verified,
                         "target": self._target if state == "acting" else None})
        except Exception as e:
            self.log(f"Could not report computer-control state: {e}")

    def _checkpoint(self) -> bool:
        """Honour Pause and Stop between steps. False means stop now."""
        if not self._running.is_set():
            paused_at = time.time()
            self._running.wait()
            self._paused_seconds += time.time() - paused_at
        return not self._stop.is_set()

    def _note(self, text: str, status: str, note: str = "") -> None:
        """One line of the step timeline the window shows: "ok", "nochange", "failed", "declined" or "checked"."""
        self.timeline.append({"n": self.step, "text": text[:1].upper() + text[1:], "status": status,
                              "note": " ".join(str(note or "").split())[:200]})
        del self.timeline[:-40]

    def _seen(self, observation: Observation) -> None:
        self.app, self.window = observation.app or "", observation.window or ""
        if self.preview and observation.screenshot is not None:
            try:
                self.preview(observation)
            except Exception as e:
                self.log(f"Could not send the screen preview: {e}")

    def _ask(self, messages, tools):
        """The AI's answer, waited for on another thread, so Stop ends the task at once even while a slow local
        model is still thinking (its late answer is simply dropped)."""
        box = {}

        def ask():
            try:
                box["response"] = self.ask_ai(messages, tools)
            except BaseException as e:
                box["error"] = e
        worker = threading.Thread(target=ask, daemon=True, name="computer-control-ai")
        worker.start()
        while worker.is_alive():
            worker.join(0.1)
            if self._stop.is_set():
                raise _Stopped()
            if self._running.is_set() and self._user_took_over(self.env.cursor()):
                # The user took the mouse while the AI thinks: say so now, not when the answer comes.
                self._grabbed = True
                self.pause("You moved the mouse, so I paused. Say “continue” when you want me to go on.")
        if "error" in box:
            raise box["error"]
        return box["response"]

    # ---------- the loop ----------
    def run(self) -> str:
        ok, why = self.env.available()
        if not ok:
            self._report("error", why)
            self.result = why
            return why
        before = None
        last_change = ""
        invalid = 0
        stale = 0
        tools = BASE_TOOLS + (VISION_TOOLS if self.vision else []) + list(self.extra_tools)
        started = time.time()
        decided_on = None   # the screen the AI's queued actions were planned from
        try:
            named = NAMED_APP.match(self.goal or "")
            if named and not self.extra_tools:   # (Blender's own tasks work through its bridge, not its window)
                # "In Notepad, ..." with Notepad open behind: put it in front first. Plain mechanics, no AI needed
                # (a small model would rather say "please open Notepad" than switch to it).
                if not self.env.switch_window(named.group(1).strip()):
                    self._note(f"Switch to {named.group(1).strip()}", "ok", "It was already open, so I brought it "
                                                                             "to the front.")
            if self.plan_first and not self.finish_after:
                self._report("planning", "Working out the steps…")
                before = self.env.observe()
                self.plan = self._make_plan(before)
            for self.step in range(1, self.max_steps + 1):
                if not self._checkpoint():
                    return self._finish("stopped", "Stopped. You have control again.")
                if stale >= MAX_STALE:
                    return self._finish("error", "I got stuck: nothing I tried got closer to that, so I stopped. "
                                                 "You have control again.")
                if time.time() - started - self._paused_seconds > self.max_seconds:
                    return self._finish("error", f"That took over {round(self.max_seconds / 60)} minutes, so I "
                                                 "stopped. You have control again.")
                queued = self._next_queued(decided_on)
                if queued:   # planned from the last look and still valid: no new look, no new question to the AI
                    action, raw = queued
                    observation = decided_on
                    seen_at = time.time()
                else:
                    if self._recovering:
                        self._report("recovering", "That didn't work, so I'm looking again to try another way…")
                    else:
                        self._report("observing", "Looking at the screen…")
                    observation = self._look(before)
                    if self._user_took_over(self.env.cursor() or observation.cursor):
                        self.pause("You moved the mouse, so I paused. Say “continue” when you want me to go on.")
                        if not self._checkpoint():
                            return self._finish("stopped", "Stopped. You have control again.")
                        observation = self.env.observe()
                        last_change = "The user used the computer while you were paused; look at the screen again."
                    self._seen(observation)
                    seen_at = time.time()
                    if self._recovering:
                        self._report("recovering", "Working out another way…")
                    else:
                        self._report("thinking", "Deciding what to do next…")
                    try:
                        action, raw = self._decide(observation, last_change, tools)
                    except AIError as e:
                        return self._finish("error", f"{e} So I stopped. You have control again.")
                    decided_on = observation
                    if not self._checkpoint():
                        return self._finish("stopped", "Stopped. You have control again.")
                    if self._grabbed:   # decided on a screen the user has since been working on: look again
                        self._grabbed = False
                        self._queued.clear()
                        last_change = "The user used the computer while you were paused; look at the screen again."
                        continue
                problem = self._validate(action, observation)
                if problem:
                    self._queued.clear()   # planned on the same wrong idea
                    invalid += 1
                    stale += 1
                    self._recovering = True
                    self.history.append((f"(invalid action: {raw[:120]})", problem))
                    self.log(f"Computer control step {self.step}: unusable answer {raw[:160]!r} ({problem})")
                    last_change = f"Your last answer couldn't be used: {problem}"
                    if invalid >= MAX_INVALID:
                        return self._finish("error", "I couldn't work out how to do that on this screen, so I "
                                                     "stopped. You have control again.")
                    continue
                kind = action["action"]
                element = observation.element(action.get("element")) if action.get("element") is not None else None
                signature = self._describe(action, element)
                if self._fruitless.get(signature, 0) >= MAX_REPEATS:   # small models tend to loop
                    invalid += 1
                    stale += 1
                    self.history.append((f"(refused repeat: {signature})", "it changed nothing twice already"))
                    last_change = (f"You already tried “{signature}” {MAX_REPEATS} times and nothing changed. Choose a "
                                   "different element or action, or call fail if the goal can't be reached.")
                    if invalid >= MAX_INVALID:
                        return self._finish("error", "I got stuck on this screen, so I stopped. You have control "
                                                     "again.")
                    continue
                invalid = 0
                if kind == "done":
                    doubt = self._check_done(action.get("summary") or "Done.")
                    if doubt:
                        stale += 1
                        self._recovering = True
                        self.history.append(("(said done)", doubt))
                        last_change = doubt
                        continue
                    if self.verified is False:   # never reported as success
                        return self._finish("error", f"I couldn't get that done properly: "
                                                     f"{self._doubt.rstrip('.')}. So I stopped. You have control "
                                                     "again.")
                    return self._finish("completed", action.get("summary") or "Done.")
                if kind == "fail":
                    return self._finish("error", action.get("reason") or "I couldn't do that.")
                if kind == "ask_user":
                    return self._finish("completed", action.get("question") or "What should I do?")
                risk = risk_of(action, element, observation)
                if risk:
                    self._report("waiting", f"Waiting for your OK to {risk}.")
                    if not self.confirm(f"Can I {risk}?"):
                        self.history.append((self._describe(action, element), "The user said no. Don't do it."))
                        self._note(self._describe(action, element), "declined", "You said no, so I didn't.")
                        last_change = "The user declined that step. Do something else, or call done/fail."
                        continue
                    if not self._checkpoint():
                        return self._finish("stopped", "Stopped. You have control again.")
                if self._user_took_over(self.env.cursor()):
                    self._queued.clear()
                    self.pause("You moved the mouse, so I paused. Say “continue” when you want me to go on.")
                    last_change = "The user used the computer while you were paused; look at the screen again."
                    if not self._checkpoint():
                        return self._finish("stopped", "Stopped. You have control again.")
                    continue
                if kind not in ("open_app", "switch_window", "wait", "look") and self.env.focus_moved():
                    self.pause("You switched to another window, so I paused. Say “continue” when you want me to go on.")
                    last_change = "The user switched windows while you were paused; look at the screen again."
                    if not self._checkpoint():
                        return self._finish("stopped", "Stopped. You have control again.")
                    continue
                if element is not None and time.time() - seen_at > STALE_AFTER:
                    # The AI (or the user's OK) took a while: the page may have moved on since that screen was read.
                    element, observation, moved = self._still_there(element)
                    if moved:
                        stale += 1
                        self._recovering = True
                        self.history.append((self._describe(action, None), moved))
                        last_change = moved
                        continue
                description = self._describe(action, element)
                self._target = ({"rect": list(element.rect), "screen": list(observation.screen_size)}
                                if element is not None else None)
                self._report("acting", description[0].upper() + description[1:])
                self._kind = kind
                try:
                    outcome = self._execute(action, element, observation)
                    self._expected_cursor = self.env.cursor() or self._expected_cursor
                except InputBlocked:
                    return self._finish("error", "Windows is blocking my key presses and clicks: the screen may be "
                                                 "locked, or the app in front runs as administrator. You have control "
                                                 "again.")
                after = self._settle(observation)
                last_change = self._change_description(kind, outcome, observation, after)
                self.history.append((description, last_change))
                if kind != "wait" and last_change.endswith("Nothing on screen changed."):
                    self._fruitless[description] = self._fruitless.get(description, 0) + 1
                    stale += 1
                else:
                    stale = 0
                failed = bool(_FAILED_OUTCOME.match(outcome or ""))
                self._last_status = ("failed" if failed else "nochange" if kind not in ("wait", "look") and
                                     last_change.endswith("Nothing on screen changed.") else "ok")
                self._recovering = self._last_status != "ok"
                self._note(description, self._last_status, last_change)
                self.log(f"Computer control step {self.step}: {description} -> {last_change[:160]}")
                before = after
                if kind in self.finish_after and not last_change.endswith("Nothing on screen changed.") \
                        and not last_change.startswith("That action failed"):
                    return self._finish("completed", f"Done: {description}.")
            return self._finish("error", f"I took {self.max_steps} steps without finishing, so I stopped. "
                                         "You have control again.")
        except _Stopped:
            return self._finish("stopped", "Stopped. You have control again.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._finish("error", f"Something went wrong while using the computer ({type(e).__name__}), "
                                         "so I stopped. You have control again.")
        finally:
            del before

    def _check_typed(self, element: Element, text: str, replacing: bool) -> str:
        """Keys can get lost (a busy app, a remote desktop): read the field back, and if the text isn't there, put it
        there directly. Returns "" or what went wrong."""
        def plain(s):
            return re.sub(r"[\s,.\u00a0]", "", s or "")
        # Some apps show typed text to accessibility only after a moment (Windows 11's Notepad: about a second), and
        # "fixing" text that was only late would put it there twice: wait for it before deciding it's missing.
        arrive_by = time.time() + TYPED_ARRIVES
        while True:
            time.sleep(0.15)
            now = self.env.read_value(element)
            if now is None or plain(text) in plain(now):
                return ""
            if time.time() >= arrive_by:
                break
        wanted = text if replacing else now + text   # (now: the whole text; element.value is only its start)
        problem = self.env.set_value(element, wanted)
        self.log(f"Computer control: the typed text didn't arrive; set it directly ({problem or 'ok'}).")
        return f"The typing didn't reach the field ({problem})." if problem else ""

    def _change_description(self, kind: str, outcome: str, before: Observation, after: Observation) -> str:
        """What a step's outcome was, for the next prompt and for the stale/fruitless-repeat checks in run().
        Overridden by BlenderComputerTask for run_python, where the screen (a custom-drawn viewport) doesn't
        reflect what actually changed the way an accessibility tree does."""
        return f"{outcome} {describe_change(before, after)}".strip()

    def _finish(self, state: str, message: str) -> str:
        self.result = message
        self._report(state, message)
        return message

    def _user_took_over(self, cursor) -> bool:
        if self._expected_cursor is None or cursor is None:
            return False
        dx = cursor[0] - self._expected_cursor[0]
        dy = cursor[1] - self._expected_cursor[1]
        return (dx * dx + dy * dy) ** 0.5 > TAKEOVER_PIXELS

    def _look(self, latest):
        """The screen now: the look taken when the last action settled, if nothing has changed since (reading a whole
        window costs up to a second or two; a screen sample costs a few milliseconds), else a new one."""
        if latest is not None and latest.sample is not None and same_sample(latest.sample, self.env.screen_sample()):
            return latest
        return self.env.observe()

    def _next_queued(self, observation):
        """The next action the AI planned from its last look, if it can still go ahead without looking again: the
        step before it worked, the user hasn't taken the mouse, and the window and the elements it names are still
        where they were. Otherwise the rest of the plan is dropped, and the loop looks and asks again."""
        if not self._queued:
            return None
        action, raw = self._queued.pop(0)

        def named(key):
            given = action.get(key)
            return observation.element(int(given)) if str(given).isdigit() and observation else None
        elements = [named(key) for key in ("element", "to_element") if action.get(key) is not None]
        if (self._last_status != "ok" or self._user_took_over(self.env.cursor()) or None in elements
                or not all(self.env.still_valid(e) for e in elements or [None])):
            self._queued.clear()
            return None
        return action, raw

    def _settle(self, before: Observation) -> Observation:
        """Wait (briefly) until the screen stops changing, so the next decision sees the result, not a half-drawn page."""
        deadline = time.time() + SETTLE_TIMEOUT
        time.sleep(0.15)
        last = self.env.screen_sample()
        if last is not None:
            if self._kind in ("open_app", "switch_window") and same_sample(before.sample or last, last):
                # A window that opens or comes forward can take a moment to show: wait for it before "still" counts.
                shows_by = time.time() + SETTLE_STILL_TIMEOUT
                while time.time() < shows_by and same_sample(before.sample or last, last):
                    time.sleep(0.1)
                    last = self.env.screen_sample()
            # Tiny screen samples (tens of milliseconds) until it holds still, then one real look.
            calm, still_by = 0, min(deadline, time.time() + SETTLE_STILL_TIMEOUT)
            while calm < 2 and time.time() < still_by:
                time.sleep(0.08)
                now = self.env.screen_sample()
                calm = calm + 1 if same_sample(last, now) else 0
                last = now
            latest = self.env.observe()
            if self.env.cursor() is None:
                self._expected_cursor = latest.cursor
            return latest
        time.sleep(0.2)
        latest = self.env.observe()
        while time.time() < deadline:
            time.sleep(0.4)
            again = self.env.observe()
            if again.fingerprint() == latest.fingerprint():
                latest = again
                break
            latest = again
        self._expected_cursor = latest.cursor
        return latest

    def _still_there(self, element: Element):
        """(the same element on the screen as it is now, that screen, "") — it may have moved — or (None, the screen,
        why the action can't go ahead), for the AI to look again."""
        fresh = self.env.observe()
        self._seen(fresh)
        same = [e for e in fresh.elements if (e.role, e.name) == (element.role, element.name)]
        if not same:
            return None, fresh, (f"The screen changed while you were deciding: {element.label()} isn't there any "
                                 "more. Nothing was done; choose from the new screen.")
        cx, cy = element.center
        best = min(same, key=lambda e: (e.center[0] - cx) ** 2 + (e.center[1] - cy) ** 2)
        far = ((best.center[0] - cx) ** 2 + (best.center[1] - cy) ** 2) ** 0.5 > TAKEOVER_PIXELS
        if far and len(same) > 1 and not element.name:
            return None, fresh, ("The screen changed while you were deciding, and that element can't be told apart "
                                 "from the others now. Nothing was done; choose from the new screen.")
        if not best.enabled:
            return None, fresh, f"{best.label()} is disabled now. Nothing was done."
        return best, fresh, ""

    def _make_plan(self, observation: Observation) -> list:
        """A few short steps for the goal, from the AI; [] when it can't give any (the task goes on without)."""
        self._seen(observation)
        lines = [f"Goal: {self.goal}", f"In front: {observation.app or 'unknown app'} — window “{observation.window}”"]
        if observation.other_windows:
            lines.append("Other windows: " + "; ".join(f"“{w[:60]}”" for w in observation.other_windows[:12]))
        named = [e.label() for e in observation.elements if e.name][:40]
        if named:
            lines.append("Some of what's on screen: " + ", ".join(named))
        try:
            args = self._tool_answer([{"role": "system", "content": PLAN_PROMPT},
                                      {"role": "user", "content": "\n".join(lines)}], PLAN_TOOL)
        except AIError as e:
            self.log(f"Computer control: no plan ({e}).")
            return []
        steps = (args or {}).get("steps")
        if isinstance(steps, str):
            steps = re.split(r"\n+|;\s*", steps)
        if not isinstance(steps, list):
            return []
        cleaned = [tidy_summary(step, "", 90) for step in steps if isinstance(step, str)]
        return [step for step in cleaned if step][:6]

    def _check_done(self, summary: str) -> str:
        """With `verify`: "" when "done" can be believed, else what is still missing (sent back to the AI). Text
        Jarvis typed is read back from the app itself and compared with what the goal asked for (see text_problem);
        a goal that is only that typing is settled by it. Anything else is checked by a separate question, judged
        only on what is visible now. After MAX_DONE_REFUSALS disagreements the task ends unconfirmed
        (self.verified False), which run() reports as a failure."""
        if not self.verify:
            return ""
        if self._last_status == "failed" and self._done_refusals == 0:
            self._done_refusals += 1
            return "Your last action failed, so the goal can't be done yet. Try another way, or call fail."
        self._report("verifying", "Checking the result on screen…")
        observation = self.env.observe()
        self._seen(observation)
        checked = self._check_text(observation)
        if checked:
            return self._refuse(*checked)
        wanted = requested_text(self.goal)
        if checked is not None and wanted and wanted[1]:   # the goal is only that typing: its text settles it
            self.verified = True
            self._note("Check the result", "ok", "The text in the app is exactly what you asked for.")
            return ""
        lines = [f"Goal: {self.goal}", f"The assistant says: {summary}",
                 f"In front now: {observation.app or 'unknown app'} — window “{observation.window}”", "Elements:"]
        lines.extend(e.describe() for e in observation.elements[:80])
        if self.history:
            lines.append("Its steps:")
            lines.extend(f"- {did} → {happened[:160]}" for did, happened in self.history[-6:])
        try:
            args = self._tool_answer([{"role": "system", "content": VERIFY_PROMPT},
                                      {"role": "user", "content": "\n".join(lines)}], VERDICT_TOOL)
        except AIError as e:
            self.log(f"Computer control: the result couldn't be checked ({e}).")
            args = None
        achieved = (args or {}).get("achieved")
        if isinstance(achieved, str):
            achieved = {"true": True, "yes": True, "false": False, "no": False}.get(achieved.strip().lower())
        evidence = tidy_summary((args or {}).get("evidence"), "")
        if achieved is True:
            self.verified = True
            self._note("Check the result", "ok", evidence or "The screen shows it's done.")
            return ""
        if achieved is not False:   # no clear answer is no confirmation either
            evidence = "the check of the screen gave no clear answer."
        return self._refuse(f"a check of the screen says {evidence or 'it does not show the goal achieved.'}",
                            evidence or "the screen doesn't show it done.")

    def _refuse(self, for_ai: str, for_user: str) -> str:
        """A "done" the check doesn't confirm: sent back to the AI with what's wrong, until MAX_DONE_REFUSALS."""
        self._done_refusals += 1
        self._note("Check the result", "failed", for_user)
        if self._done_refusals > MAX_DONE_REFUSALS:
            self.verified, self._doubt = False, for_user
            return ""
        return f"Not done yet: {for_ai} Keep going, or call fail if it can't be done."

    def _check_text(self, observation: Observation):
        """The field typed into last, read fresh from the app: (what's wrong for the AI, for the user), None when
        it can't be read (nothing typed, or the app doesn't expose its text), or () when it holds the right text."""
        if self._typed_last is None:
            return None
        fields = [e for e in observation.elements if (e.role, e.name) == self._typed_last]
        field = next((e for e in fields if e.focused), fields[0] if fields else None)
        now = self.env.read_value(field) if field is not None and not field.password else None
        if now is None:
            return None
        return text_problem(self.goal, self._typed[self._typed_last], now) or ()

    def _tool_answer(self, messages, tool):
        """The arguments of the AI's call of this one tool (or of the same thing written as JSON text); None if
        it answered something else."""
        name = tool["function"]["name"]
        message = self._ask(messages, [tool]).choices[0].message
        calls = getattr(message, "tool_calls", None) or []
        if calls:
            return _arguments(name, calls[0].function.arguments or "{}", [tool]) if calls[0].function.name == name \
                else None
        data = _first_json_object((getattr(message, "content", "") or "").strip())
        if not isinstance(data, dict):
            return None
        given = data.get("arguments", data.get("parameters", data))
        return _arguments(name, given, [tool])

    # ---------- asking the AI ----------
    def _prompt(self, observation: Observation, last_change: str) -> str:
        lines = [f"Goal: {self.goal}"]
        if self.plan:
            lines.append("Your plan (adapt it if the screen differs): " +
                         " ".join(f"{i}. {step}" for i, step in enumerate(self.plan, 1)))
        lines.append(f"In front: {observation.app or 'unknown app'} — window “{observation.window}”")
        if observation.note:
            lines.append(f"Note: {observation.note}")
        if observation.other_windows:
            lines.append("Other windows: " + "; ".join(f"“{w[:60]}”" for w in observation.other_windows[:12]))
        lines.append("Elements:")
        shown = observation.elements[:self.max_elements]
        lines.extend(e.describe() for e in shown)
        if not shown:
            lines.append("(this window exposes no elements" + (": use look / click_on" if self.vision else
                                                             "; try keyboard shortcuts, or switch window") + ")")
        if len(observation.elements) > self.max_elements:
            lines.append(f"(+{len(observation.elements) - self.max_elements} more; scroll to see others)")
        if self.history:
            lines.append("Your steps so far:")
            for i, (did, happened) in enumerate(self.history[-8:], max(1, len(self.history) - 7)):
                lines.append(f"{i}. {did} → {happened[:200]}")
        if last_change:
            lines.append(f"Result of your last action: {last_change}")
        if self.history:   # small models forget to stop: ask them outright
            lines.append(f"Is the goal (“{self.goal}”) achieved now? If yes, call done.")
        lines.append(f"Step {self.step} of {self.max_steps}. Reply with one tool call" +
                     (" (or a few in order, when they're certain from this screen)." if self.max_batch > 1 else "."))
        return "\n".join(lines)

    def _decide(self, observation: Observation, last_change: str, tools: list):
        messages = [{"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": self._prompt(observation, last_change)}]
        response = self._ask(messages, tools)
        message = response.choices[0].message
        calls = getattr(message, "tool_calls", None) or []
        text = (getattr(message, "content", "") or "").strip()
        calls = [(c.function.name, c.function.arguments or "{}") for c in calls] or _written_calls(text, tools)
        self._queued = []
        if calls:
            decided = []
            for name, given in calls[:self.max_batch]:
                args = _arguments(name, given, tools)
                if args is None:
                    decided.append(({"action": name, "_bad_json": True}, f"{name}({given})"))
                    break
                decided.append(({"action": name, **args}, f"{name}({json.dumps(args)[:100]})"))
                if name in ("done", "fail", "ask_user"):
                    break
            self._queued = decided[1:]
            return decided[0]
        # Small local models sometimes write the call as JSON text instead of a tool call — often with the code
        # as a bare string ({"name": "run_python", "parameters": "import bpy..."}), raw line breaks inside its
        # strings, or a second call glued on after it. The first object is the call.
        data = _first_json_object(text)
        # OpenAI-shaped calls written out as text: {"tool_calls": [{"function": {...}}]} / {"function": {...}}.
        while isinstance(data, dict) and (isinstance(data.get("tool_calls"), list) or
                                          isinstance(data.get("function"), dict)):
            calls = data.get("tool_calls")
            data = (calls[0] if calls else None) if isinstance(calls, list) else data["function"]
        if isinstance(data, dict):
            name = data.get("name") or data.get("action") or data.get("tool")
            given = next((data[k] for k in ("arguments", "parameters") if k in data),
                         {k: v for k, v in data.items() if k not in ("name", "action", "tool")})
            args = _arguments(name, given, tools) if isinstance(name, str) else None
            if name and args is not None:
                return {"action": name, **args}, text
        # ... or as a function call: run_python(bpy.ops.object.light_add(type='SUN')), the code inside it.
        if any(t["function"]["name"] == "run_python" for t in tools):
            code = _run_python_text(text) or _loose_code(text) or _fenced_code(text)
            if code:
                return {"action": "run_python", "code": code}, text
        said = self._plain_call(text, observation, tools)
        if said:
            return said, text
        return {"action": None}, text or "(no answer)"

    @staticmethod
    def _plain_call(text: str, observation: Observation, tools: list):
        """A small model's call written as words instead of a tool call ("press_keys ctrl+a", "open_app Notepad",
        "click document “Text editor”", "click [12]"): the call it plainly means, or None."""
        lines = (text or "").strip().splitlines()
        if len(lines) == 1:   # the same in plain verbs: "switch to File Explorer", "press ctrl+l", "type hello"
            lines = [re.sub(r"^(switch to|open|press|type|double[- ]click|right[- ]click)\b",
                            lambda m: PLAIN_VERBS[m.group(1).lower().replace(" ", "-")], lines[0].strip(), flags=re.I)]
        match = re.fullmatch(r"(\w+)\s*[:(]?\s*(.*?)\s*\)?", lines[0].strip()) if len(lines) == 1 else None
        if not match or match.group(1) not in {t["function"]["name"] for t in tools}:
            return None
        name, said = match.group(1), match.group(2).strip()
        bare = said.strip("\"'“”")
        fields = {"press_keys": "keys", "open_app": "name", "switch_window": "title", "type_text": "text"}
        if name in fields and said.startswith("{"):   # type_text {"element": 1, "text": "milk"}: the call's own JSON
            given = _first_json_object(said)
            if isinstance(given, dict) and isinstance(given.get(fields[name]), str):
                return {"action": name, **given}
        if name in fields and bare:
            return {"action": name, fields[name]: bare}
        if name in ("click", "double_click", "right_click") and said:
            number = re.fullmatch(r"\[?(\d+)\]?", said)
            if number:
                return {"action": name, "element": int(number.group(1))}
            same = [e for e in observation.elements if e.label() == said or (e.name and e.name == bare)]
            return {"action": name, "element": same[0].id} if len(same) == 1 else None
        if name == "done":
            return {"action": "done", "summary": bare or "Done."}
        return None

    def _validate(self, action: dict, observation: Observation) -> str:
        """Why this action can't be carried out, or "" if it can. Nothing unvalidated ever reaches the mouse."""
        kind = action.get("action")
        names = {t["function"]["name"] for t in BASE_TOOLS + (VISION_TOOLS if self.vision else []) + list(self.extra_tools)}
        if action.get("_bad_json"):
            return "its arguments weren't valid JSON."
        if kind not in names:
            return f"“{kind}” isn't one of the available actions." if kind else "it wasn't a tool call."
        if kind == "drag":
            to_id = action.get("to_element")
            if not isinstance(to_id, int) and not (isinstance(to_id, str) and to_id.isdigit()):
                return "to_element must be a number from the list."
            action["to_element"] = int(to_id)
            if observation.element(action["to_element"]) is None:
                return f"there is no element [{to_id}] on the screen now."
            action["_to_label"] = observation.element(action["to_element"]).label()
        if kind in ("click", "double_click", "right_click", "drag") or (kind in ("type_text", "scroll") and
                                                                       action.get("element") is not None):
            element_id = action.get("element")
            if not isinstance(element_id, int) and not (isinstance(element_id, str) and element_id.isdigit()):
                return "element must be a number from the list."
            action["element"] = int(element_id)
            element = observation.element(action["element"])
            if element is None:
                return f"there is no element [{element_id}] on the screen now."
            if not element.enabled and kind != "scroll":
                return f"[{element_id}] is disabled."
            if kind == "type_text" and element.password:
                return "that's a password field; Jarvis never types passwords. Ask the user to type it."
            if kind == "type_text" and element.role not in TEXT_ROLES:
                return (f"[{element_id}] is a {element.role}, which doesn't take typing. Type into a text field, "
                        "or click this instead.")
        if kind == "type_text":
            if not isinstance(action.get("text"), str) or not action["text"]:
                return "type_text needs some text."
            if len(action["text"]) > 2000:
                return "that's too much text to type at once."
            leak = leaked_syntax(action["text"], self.goal)
            if leak:   # never typed: it would land in the user's document as garbage
                return (f"the text to type contains call syntax ({leak[:40]}). Put only the words that should appear "
                        "in text, and the element number in element.")
            focused = next((e for e in observation.elements if e.focused), None)
            if action.get("element") is None and focused is not None and focused.password:
                return "the focused field is a password field; Jarvis never types passwords."
            if action.get("element") is None and focused is not None and focused.role not in TEXT_ROLES:
                # Keys sent to a menu or a button aren't typing: they're shortcuts (in Notepad's Edit menu, letters
                # start "Search with Bing"). Only type where text goes.
                return (f"the focus is on {focused.label()}, which doesn't take typing. Give the text field's element "
                        "number, or use press_keys for a shortcut.")
        if kind == "press_keys":
            combo = normalize_keys(action.get("keys", ""))
            if not combo:
                return "press_keys needs a key."
            if frozenset(combo) in _FORBIDDEN_COMBOS:
                return "that shortcut is reserved (it's the emergency stop, or a system shortcut)."
        if kind == "scroll" and action.get("direction") not in ("up", "down"):
            return "scroll direction must be up or down."
        if kind == "wait":
            try:
                action["seconds"] = max(0.5, min(5.0, float(action.get("seconds", 1))))
            except (TypeError, ValueError):
                return "wait needs a number of seconds."
        if kind in ("open_app", "switch_window") and not str(action.get("name") or action.get("title") or "").strip():
            return f"{kind} needs a name."
        if kind in ("look", "click_on") and not str(action.get("question") or action.get("description") or "").strip():
            return f"{kind} needs a description."
        # Whatever free text the AI attaches here reaches the user almost verbatim (spoken and shown) — clean it up
        # now, once, rather than trusting it at every later use site.
        if kind == "done":
            action["summary"] = tidy_summary(action.get("summary"), "Done.")
        if kind == "fail":
            action["reason"] = tidy_summary(action.get("reason"), "I couldn't do that.")
        if kind == "ask_user":
            action["question"] = tidy_summary(action.get("question"), "Can you say that a different way?")
        return ""

    # ---------- doing it ----------
    @staticmethod
    def _describe(action: dict, element) -> str:
        kind = action["action"]
        target = element.label() if element else ""
        if kind in ("click", "double_click", "right_click"):
            return f"{kind.replace('_', '-')} {target}"
        if kind == "drag":
            return f"drag {target} onto {action.get('_to_label') or 'the other element'}"
        if kind == "type_text":
            where = f" into {target}" if target else ""
            return f"type “{action['text'][:60]}”{where}" + (" and press Enter" if action.get("press_enter") else "")
        if kind == "press_keys":
            return f"press {'+'.join(normalize_keys(action['keys']))}"
        if kind == "scroll":
            return f"scroll {action['direction']}" + (f" in {target}" if target else "")
        if kind == "open_app":
            return f"open {action['name']}"
        if kind == "switch_window":
            return f"switch to “{action['title']}”"
        if kind == "wait":
            return f"wait {action['seconds']:.0f} s"
        if kind == "look":
            return f"look at the screen ({action['question'][:60]})"
        if kind == "click_on":
            return f"click {action['description'][:60]}"
        return kind

    def _execute(self, action: dict, element, observation: Observation) -> str:
        kind = action["action"]
        try:
            if kind == "click":
                return self.env.press_element(element) or ""
            if kind == "double_click":
                return self.env.click(element.center, double=True) or ""
            if kind == "right_click":
                return self.env.click(element.center, button="right") or ""
            if kind == "drag":
                return self.env.drag(element.center, observation.element(action["to_element"]).center) or ""
            if kind == "type_text":
                if element is not None and not element.focused:
                    problem = self.env.focus_element(element)
                    if problem:
                        return problem   # typing now would land somewhere else
                    time.sleep(0.1)
                replacing = bool(element is not None and element.role in SINGLE_LINE_ROLES and element.value
                                 and not action.get("append"))
                # Typed into whatever had the focus: that field is checked too (keys get lost in a busy app).
                typed_into = element or next((e for e in observation.elements if e.focused and e.role in TEXT_ROLES),
                                             None)
                if typed_into is not None and not typed_into.password:   # for the check when the AI says done
                    key = (typed_into.role, typed_into.name)
                    if key not in self._typed:
                        self._typed[key] = self.env.read_value(typed_into) or ""
                    self._typed_last = key
                if replacing:
                    self.env.press_keys(list(self.env.select_all))   # replace the old value, don't add to it
                    time.sleep(0.05)
                result = self.env.type_text(action["text"]) or ""
                if typed_into is not None and not typed_into.password and not result:
                    result = self._check_typed(typed_into, action["text"], replacing)
                # A web address typed into a browser's address bar is only ever meant to be opened.
                if action.get("press_enter") or (typed_into is not None and not result and
                                                 ADDRESS_BAR.search(typed_into.name or "") and
                                                 WEB_ADDRESS.fullmatch(action["text"].strip())):
                    time.sleep(0.1)
                    self.env.press_keys(["enter"])
                return result
            if kind == "press_keys":
                return self.env.press_keys(normalize_keys(action["keys"])) or ""
            if kind == "scroll":
                amount = -5 if action["direction"] == "down" else 5
                return self.env.scroll(amount, element.center if element else None) or ""
            if kind == "open_app":
                return str(self.env.open_app(action["name"]) or "")
            if kind == "switch_window":
                return self.env.switch_window(action["title"]) or ""
            if kind == "wait":
                time.sleep(action["seconds"])
                return ""
            if kind == "look":
                if observation.screenshot is None:
                    return "No screenshot is available on this computer."
                return f"You looked: {self.vision.look(observation.screenshot, action['question'])}"
            if kind == "click_on":
                if observation.screenshot is None:
                    return "No screenshot is available on this computer."
                point = self.vision.locate(observation.screenshot, action["description"], observation.screen_size)
                if point is None:
                    return f"Couldn't find “{action['description']}” on the screen."
                return self.env.click(point) or ""
        except Exception as e:   # one failed step is reported back to the AI, it never ends Jarvis
            self.log(f"Computer control action failed: {type(e).__name__}: {e}")
            if type(e).__name__ == "InputRefused":   # nothing more can work: see winctl.InputRefused
                raise InputBlocked() from e
            return f"That action failed ({type(e).__name__}: {str(e)[:120]})."
        return ""


BLENDER_TOOLS = [
    _tool("run_python", "Run Python in Blender's own scripting environment (bpy, bmesh and mathutils are already "
                        "in scope) to create or change the scene. Prefer this over clicking for anything that "
                        "builds or edits objects, materials, or transforms — one script can do what would "
                        "otherwise take many clicks, and far more reliably. Set a short string on a module-level "
                        "RESULT variable to report what you did; otherwise whatever the code prints is used.",
          {"code": {"type": "string", "description": "Python to exec() in Blender right now."}}, ["code"]),
]

BLENDER_SYSTEM_PROMPT = """You operate Blender to achieve the user's goal, almost always by writing Python through \
run_python (bpy/bmesh/mathutils are already imported) — one script can create a whole object, with reasonable \
proportions and materials, at once. Virtually everything in Blender — creating, editing, selecting, moving, \
duplicating, arranging, materials, saving — is reachable through bpy, so run_python is almost always the right \
tool. Use the mouse/keyboard tools only for a Blender UI step that truly cannot be scripted (this is rare).

The window list you're shown is the whole desktop, not just Blender — other apps (a browser, chat, an editor) may \
be listed too. Never click, type into, or switch to anything that isn't Blender's own window: if Blender isn't in \
front, the one UI action you may take is switch_window to bring it back, then continue with run_python.

Each turn you get: a summary of the current Blender scene (read from Blender itself, not guessed), what happened \
earlier in this session, the window's on-screen elements (for the rare UI-only step), and what your last action \
did. Reply with exactly ONE tool call.

Rules:
- Prefer run_python for anything that changes the scene: creating/editing meshes, materials, transforms, \
duplicating, arranging, and saving the file (bpy.ops.wm.save_as_mainfile / save_mainfile).
- Code runs in a namespace that persists between your own steps, and across the user's earlier requests in this \
session: reuse bpy.context.object or a variable you set earlier instead of re-deriving it from scratch.
- Keep each script focused on one step; if it raises, the error comes back to you so you can fix it and try again.
- Never call bpy.ops.wm.quit_blender, read_factory_settings/read_homefile, touch files outside the current \
project, or reach outside Blender (delete files, run shell commands, use the network) without asking first.
- Never call done before you have actually run something that changed the scene (the scene summary each turn is \
the real state — check it, don't just assume your last script worked). If the goal is already met with no action \
needed, say so by running a no-op check first, not by skipping straight to done.
- After each script, read the scene again: the sizes, materials and "Problems the checks found" there are measured \
in Blender. Fix problems with what you built before calling done; never describe a change you haven't made.
- The user is usually changing a scene that already exists ("make the pool rounder", "add a bench by the pool"): \
change or add to what's there, found in the features list each turn, and never rebuild or delete things that weren't \
asked about. For a feature (a pool, a path, a building) use move_feature / connect / improve_feature / resize_feature \
/ remove_feature / paint_feature where they fit, and check a path you made with check_path.
- When the goal is achieved, call done with a one-sentence summary. If it truly can't be done, call fail."""


class BlenderComputerTask(ComputerTask):
    """A ComputerTask whose AI mainly builds things by writing Python for Blender's own API (run_python) instead
    of clicking, with the regular mouse/keyboard tools still available for the rare step that genuinely needs the
    UI. `bridge` is a blender_control.BlenderBridge (already confirmed responsive by the caller); `session` is the
    app.py ControlSession, if any, so earlier goals in the same session can be referred back to ("make it wooden")."""

    max_elements = 30   # the desktop's elements matter only for the rare UI-only step; they crowd out the scene
    max_batch = 1       # each script's result decides the next one
    max_seconds = 60 * 60   # one script may take up to SCRIPT_SECONDS, and a build has many

    def __init__(self, goal: str, env: Environment, ask_ai, bridge, session=None, **kwargs):
        super().__init__(goal, env, ask_ai, **kwargs)
        self.bridge = bridge
        self.session = session
        import blender_control
        self.system_prompt = BLENDER_SYSTEM_PROMPT + "\n\n" + blender_control.kit_help()
        self.extra_tools = BLENDER_TOOLS
        self._did_something = False   # has any step actually changed Blender's state yet? see _validate's "done" check
        self._first_errors = None     # the scene checks' errors before this task did anything (see _validate)
        self._errors = set()          # ... and at the latest look
        self._done_refused = False
        self._last_kind = None
        self.checkpoint = None        # the scene's copy from before this task's first script (_save_checkpoint)
        self._checkpoint_tried = False
        self._start_digest = None     # the scene before this task's first script, and after its latest one
        self._latest_digest = None    # (see _new_meshes)
        self._short_refusals = 0      # "done" refused because the scene plainly lacks what was asked for
        self._unfinished = ""

    _SUMMARY = ("issues = check()\n"
                "RESULT = report() + '\\n' + scene_manifest() + (('\\nProblems the checks found (' + str(len(issues)) + '):\\n' + '\\n'.join("
                "'- ' + (p['object'] + ' ' if p['object'] else '') + p['problem'] + ' [' + p['severity'] + ']' "
                "for p in issues[:8])) if issues else '\\nThe checks found no problems.') + "
                # what blocks "done" once (see _validate): errors, and things left floating or inside each other
                "'\\n#ERRORS ' + json.dumps([(p['object'] + ' ' + p['problem']).strip() for p in issues "
                "if p['severity'] == 'error' or 'floats' in p['problem'] or 'mostly inside' in p['problem']])")

    def _scene_summary(self) -> str:
        """The scene as Blender reports it (blender_scene.report: sizes, materials, modifiers, lights, camera) and
        what its checks measure as wrong (blender_scene.check), so the AI can see whether its last script did what
        it meant — not only that it ran."""
        if self.bridge is None:
            return "(no Blender connection)"
        import blender_control
        response = self.bridge.run(blender_control.with_kit(self._SUMMARY), timeout=15)
        if not response.get("ok"):
            return f"(couldn't read the scene: {_script_error(response.get('error'), '')})"
        text, _, errors = (response.get("output") or "").partition("\n#ERRORS ")
        try:
            self._errors = set(json.loads(errors)) if errors else set()
        except ValueError:
            self._errors = set()
        if self._first_errors is None:
            self._first_errors = set(self._errors)
        return text or "(empty scene)"

    def _prompt(self, observation: Observation, last_change: str) -> str:
        header = [f"Blender scene (from Blender itself): {self._scene_summary()}"]
        if self.session and self.session.history:
            header.append("Earlier in this session:")
            header.extend(f"- {goal} -> {result[:160]}" for goal, result in self.session.history[-4:])
        return "\n".join(header) + "\n\n" + super()._prompt(observation, last_change)

    @staticmethod
    def _helper_as_code(action: dict) -> None:
        """A helper "called" as if it were a tool ({"name": "frame", "arguments": {"objects": [...]}}, which models
        do once the helpers are listed): the same call, as the run_python code it stands for."""
        import blender_control
        name = action.get("action")
        if name not in blender_control.kit_functions():
            return
        args = {k: v for k, v in action.items() if k not in ("action", "_bad_json")}
        first = next((args.pop(k) for k in ("obj", "object", "o") if k in args), None)
        given = ([repr(first)] if first is not None else []) + [f"{k}={v!r}" for k, v in args.items()]
        action.clear()
        action.update({"action": "run_python", "code": f"RESULT = str({name}({', '.join(given)}))"})

    def _validate(self, action: dict, observation: Observation) -> str:
        self._helper_as_code(action)
        problem = super()._validate(action, observation)
        if problem:
            return problem
        if action.get("action") == "run_python" and not str(action.get("code") or "").strip():
            return "run_python needs some code."
        if action.get("action") == "done" and not self._did_something:
            # Never let the AI claim success without having actually changed anything yet — a small model
            # especially may otherwise just assert "done" outright. (Real scene state is re-checked each turn via
            # the scene summary in _prompt, but this stops the claim from ever being accepted in the first place.)
            return ("you haven't actually changed anything in Blender yet for this request — call run_python (or "
                    "a UI action) to do it first, or call fail if it genuinely can't be done.")
        if action.get("action") == "done":
            short = self._what_is_missing()
            if short:
                self._short_refusals += 1
                if self._short_refusals > self.MAX_SHORT_REFUSALS:
                    self._unfinished = short   # _finish turns this "done" into an honest "not finished"
                    return ""
                return (f"not yet: {short} Keep building with run_python; call done only when the scene really "
                        "has it.")
        new_errors = sorted(self._errors - (self._first_errors or set()))
        if action.get("action") == "done" and new_errors and not self._done_refused:
            # Once only: the checks measure things (a shader cut off from its output, a camera that sees nothing),
            # but the AI may know the user wants exactly that — a second "done" is accepted.
            self._done_refused = True
            return ("the scene checks found new problems since you started: " + "; ".join(new_errors[:4]) +
                    ". Fix them with run_python, or call done again if that is what the user asked for.")
        return ""

    MAX_SHORT_REFUSALS = 3

    def _what_is_missing(self) -> str:
        """Why the scene can't yet be what the goal asked for, measured in Blender ("" when nothing is known to be
        missing): a table that is still one box, a house with no roof. A single primitive never completes a request
        for something made of parts."""
        import blender_build
        need = blender_build.min_new_parts(self.goal)
        lacking = blender_build.missing_features(self.goal, self._new_meshes())
        made = len(self._new_meshes())
        if need and made < need:
            return (f"the request needs at least {need} separate parts, and the scene has {made} new "
                    f"object{'s' if made != 1 else ''}" + (f" (still no {', '.join(lacking)})" if lacking else "") +
                    ".")
        if lacking:
            return f"nothing in the scene is a {', '.join(lacking)} yet (name each part for what it is)."
        return ""

    def _new_meshes(self) -> list:
        """The names of mesh objects that weren't there when this task started (from the digests _execute takes
        around every script — no extra question to Blender)."""
        if self._start_digest is None or self._latest_digest is None:
            return []
        return sorted(n for n, facts in self._latest_digest.items()
                      if n not in self._start_digest and facts.get("type") == "mesh")

    def _finish(self, state: str, message: str) -> str:
        if state == "completed" and self._unfinished:
            state, message = "error", (f"I stopped without finishing: {self._unfinished} What I did build is still "
                                       "in the scene.")
        if state == "error" and self.checkpoint:
            message += f" The scene as it was before I started is saved at {self.checkpoint}."
        return ComputerTask._finish(self, state, message)

    @staticmethod
    def _describe(action: dict, element) -> str:
        if action["action"] == "run_python":
            first_line = next(iter((action.get("code") or "").strip().splitlines()), "")
            shown = first_line[:60] + ("…" if len(first_line) > 60 else "")
            return f"run Python ({shown})" if shown else "run Python"
        return ComputerTask._describe(action, element)

    def _change_description(self, kind: str, outcome: str, before: Observation, after: Observation) -> str:
        if kind == "run_python":
            # Blender's accessibility tree barely reflects a script's effect (the viewport is custom-drawn), so
            # don't let describe_change() judge it; an error is the only case the stale/fruitless checks need to
            # see as "nothing changed" (the exact sentinel run() checks for).
            if outcome.startswith("The script raised an error") or outcome.startswith("That action failed"):
                return f"{outcome} Nothing on screen changed."
            self._did_something = True
            return outcome
        result = super()._change_description(kind, outcome, before, after)
        if kind not in ("wait", "look") and not result.endswith("Nothing on screen changed."):
            self._did_something = True
        return result

    def _digest(self):
        """blender_scene.digest(): each object's facts, or None when Blender didn't give them."""
        import blender_control
        response = self.bridge.run(blender_control.with_kit("RESULT = json.dumps(digest())"), timeout=15)
        try:
            facts = json.loads(response.get("output") or "") if response.get("ok") else None
        except ValueError:
            return None
        return facts if isinstance(facts, dict) else None

    def _object_names(self) -> set:
        if self.bridge is None:
            return set()
        response = self.bridge.run("RESULT = '|'.join(o.name + ':' + o.type + ('\\t' + o.parent.name if o.parent "
                                   "else '') for o in bpy.data.objects)", timeout=5)
        if not response.get("ok"):
            return set()
        output = response.get("output") or ""
        return set(output.split("|")) if output else set()

    def _settle(self, before: Observation) -> Observation:
        if self._last_kind == "run_python":
            # A script's effect is read from Blender itself next turn; waiting for the screen to settle (several
            # accessibility scans of the whole window) only adds seconds to every step.
            self._expected_cursor = before.cursor
            return before
        return super()._settle(before)

    CHECKPOINTS_KEPT = 3

    def _save_checkpoint(self) -> None:
        self.checkpoint = save_blender_checkpoint(self.bridge, self.CHECKPOINTS_KEPT, self.log)

    def _execute(self, action: dict, element, observation: Observation) -> str:
        self._last_kind = action["action"]
        if action["action"] == "run_python":
            import blender_control
            try:   # a script that can't even be parsed never needs a round trip to Blender (or a checkpoint)
                compile(action["code"], "<jarvis>", "exec")
            except SyntaxError as e:
                lines = action["code"].splitlines()
                line = lines[e.lineno - 1].strip()[:120] if e.lineno and 0 < e.lineno <= len(lines) else ""
                return (f"The script raised an error: SyntaxError: {e.msg}" +
                        (f" — at line {e.lineno}: {line}" if line else "") +
                        " (nothing was run; check quotes and brackets)")
            if not self._checkpoint_tried:
                self._checkpoint_tried = True
                self._save_checkpoint()
            before_names = self._object_names() if self.session else set()
            before = self._digest()
            if self._start_digest is None:
                self._start_digest = before
            try:
                # With the helpers (blender_scene.py) loaded, so the AI's code can call material(), frame()...
                response = self.bridge.run(blender_control.with_kit(action["code"]), timeout=SCRIPT_SECONDS)
            except Exception as e:
                self.log(f"Blender bridge failed: {type(e).__name__}: {e}")
                return f"That action failed ({type(e).__name__}: {str(e)[:120]})."
            if response.get("busy"):
                self._did_something = True
                return ("Blender is still running that script (it is slow — a render or a heavy modifier) and will "
                        "finish on its own. Don't run it again: wait, then look at the scene.")
            if response.get("ok"):
                if self.session:
                    # So a later command ("make it red") can refer to something the free-form AI just created,
                    # exactly as it would for something blender_commands.py created.
                    made = []
                    for entry in self._object_names() - before_names:
                        head, _, parent = entry.partition("\t")
                        name, _, kind = head.rpartition(":")
                        if name:
                            made.append((bool(parent), name, kind.lower()))
                    # Parts first, then whole things: "it" next means what was built (the table), not one leg.
                    for _, name, kind in sorted(made, key=lambda m: not m[0]):
                        self.session.remember_blender_object(name, kind)
                    if made:
                        self.session.blender_focus = self.session.last_blender_object
                said = response.get("output") or "Done."
                after = self._digest()
                self._latest_digest = after if after is not None else self._latest_digest
                if before is None or after is None:
                    return said
                changes = _scene_changes(before, after)
                if not changes:
                    return (f"{said} The script ran, but no object in the scene changed (a render or a save "
                            "doesn't change them).")
                return f"{said} What changed in Blender: " + "; ".join(changes)
            return f"The script raised an error: {_script_error(response.get('error'), action['code'])}"
        return super()._execute(action, element, observation)


def save_blender_checkpoint(bridge, kept: int = 3, log=print):
    """Before free-form code or a whole build changes the scene, a copy of it goes to Jarvis's own data folder (the
    user's file and its path are left alone): such changes can remove or overwrite work no single undo brings back.
    Returns the copy's path, or None when it couldn't be saved."""
    import datetime
    import paths
    folder = paths.data_dir("blender checkpoints")
    try:
        old = sorted(f for f in os.listdir(folder) if f.endswith(".blend"))
        for name in old[:max(0, len(old) - kept + 1)]:
            os.remove(os.path.join(folder, name))
    except OSError:
        pass
    path = os.path.join(folder, datetime.datetime.now().strftime("before %Y-%m-%d %H-%M-%S.blend"))
    response = bridge.run(f"bpy.ops.wm.save_as_mainfile(filepath={path!r}, copy=True)\n"
                          f"import os\nRESULT = '1' if os.path.exists({path!r}) else '0'", timeout=60)
    if response.get("output") == "1":
        return path
    log(f"Couldn't save a Blender checkpoint: {(response.get('error') or '')[-200:]}")
    return None


SCRIPT_SECONDS = 60
MAX_CHANGES_SHOWN = 8


def _scene_changes(before: dict, after: dict) -> list:
    """What a script really did, from blender_scene.digest() before and after it: ["Added Sphere (mesh) at ...",
    "Cube: at (0, 0, 0) -> (0, 0, 3)"]."""
    lines = []
    for name in after.keys() - before.keys():
        facts = after[name]
        extra = ", ".join(f"{k} {facts[k]}" for k in ("size", "material", "light") if k in facts)
        lines.append(f"Added {name} ({facts.get('type')}) at {facts.get('at')}" + (f", {extra}" if extra else ""))
    lines += [f"Removed {name}" for name in before.keys() - after.keys()]
    for name in before.keys() & after.keys():
        was, now = before[name], after[name]
        changed = [f"{k} {was.get(k, '-')} -> {now.get(k, '-')}" for k in sorted(was.keys() | now.keys())
                   if was.get(k) != now.get(k)]
        if changed:
            lines.append(f"{name}: " + ", ".join(changed))
    if len(lines) > MAX_CHANGES_SHOWN:
        lines = lines[:MAX_CHANGES_SHOWN] + [f"(and {len(lines) - MAX_CHANGES_SHOWN} more changes)"]
    return lines

# Blender 4.0 renamed these Principled BSDF inputs; older code (and models trained on it) still uses the old names.
_RENAMED_INPUTS = {"Specular": "Specular IOR Level", "Transmission": "Transmission Weight",
                   "Emission": "Emission Color", "Subsurface": "Subsurface Weight", "Clearcoat": "Coat Weight",
                   "Sheen": "Sheen Weight", "Subsurface Color": "Base Color"}


def _script_error(error: str, code: str) -> str:
    """A script's traceback as what the AI needs to fix it: the exception itself first (a traceback's start is
    only "Traceback (most recent call last)"), the line of its own code that failed, and a hint for the mistakes
    Blender 4 scripts are known to make."""
    import blender_control
    lines = [line for line in (error or "").strip().splitlines() if line.strip()]
    message = lines[-1].strip() if lines else "unknown error"
    where = ""
    offset = blender_control.with_kit("").count("\n")   # the helper loader's lines come before the AI's code
    for line in reversed(lines):
        m = re.search(r'File "<jarvis>", line (\d+)', line)
        if m:
            n = int(m.group(1)) - offset
            source = (code or "").splitlines()
            if 0 < n <= len(source):
                where = f" — at line {n}: {source[n - 1].strip()[:120]}"
            break
    hint = ""
    renamed = next((new for old, new in _RENAMED_INPUTS.items() if re.search(rf'key "{old}" not found', message)), None)
    if renamed:
        hint = f" (Blender 4 calls that input '{renamed}'; material()/paint() set these for you)"
    elif "context is incorrect" in message or "poll() failed" in message:
        hint = (" (that operator needs a 3D View under the mouse, which a script doesn't have: change bpy.data "
                "directly, or use the helpers — smooth(), bevel(), subdivide(), drop_to_floor()...)")
    elif re.search(r'keyword "\w+" unrecognized', message):
        hint = (" (an operator takes only its own settings: set the rest on the new object afterwards, or use a "
                "helper — add_light('SUN', energy=3), add_box(name, size=..., at=...)...)")
    elif re.search(r'Calling operator "bpy\.ops\.[\w.]+" error, could not be found', message):
        hint = " (Blender has no such operator: use bpy.data, or one of the helpers listed in your instructions)"
    return f"{message[:300]}{where}{hint}"


class ScriptedTask(ComputerTask):
    """A task whose steps are known in advance (playing something in Spotify, say), shown and controlled exactly like
    one the AI works out: the overlay shows each step, and Stop, Pause, the stop shortcut and moving the mouse work
    the same. `steps` is a list of (what the user sees, function); a function's text result becomes the summary."""

    def __init__(self, goal: str, steps: list, report=None, cursor=None, log=print):
        super().__init__(goal, env=None, ask_ai=None, report=report, max_steps=len(steps), log=log)
        self.steps = steps
        self.cursor = cursor or (lambda: None)

    def run(self) -> str:
        summary = ""
        if hasattr(self.steps, "task"):   # long steps (a video render) report progress and honour Stop themselves
            self.steps.task = self
        try:
            for self.step, (description, action) in enumerate(self.steps, 1):
                if not self._checkpoint():
                    return self._finish("stopped", "Stopped. You have control again.")
                now = self.cursor()
                if self._expected_cursor and now and ((now[0] - self._expected_cursor[0]) ** 2 +
                                                      (now[1] - self._expected_cursor[1]) ** 2) ** 0.5 > TAKEOVER_PIXELS:
                    self.pause("You moved the mouse, so I paused. Say “continue” when you want me to go on.")
                    if not self._checkpoint():
                        return self._finish("stopped", "Stopped. You have control again.")
                # A step may say what kind of work it is (a build's "planning" and "verifying" stages).
                self._report(getattr(action, "state", "acting"), description)
                self.log(f"Computer control step {self.step}: {description}")
                outcome = action()
                if isinstance(outcome, str) and outcome:
                    summary = outcome
                self._note(description, "ok", outcome if isinstance(outcome, str) else "")
                self._expected_cursor = self.cursor()
            return self._finish("completed", summary or "Done.")
        except Exception as e:   # a step that can't be done ends the task in plain words
            if type(e).__name__ == "Stopped":   # scene_director: Stop was said in the middle of a long step
                return self._finish("stopped", "Stopped. What was finished so far is still in Blender. You have "
                                               "control again.")
            self.log(f"Computer control step failed: {type(e).__name__}: {e}")
            if self.step:
                self._note(self.steps[self.step - 1][0], "failed", str(e))
            return self._finish("error", f"{e} You have control again.")
