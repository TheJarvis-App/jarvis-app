"""Computer control on Windows: reading the window in front through UI Automation, acting through winctl.py.

UI Automation is the accessibility layer Windows itself provides: every button, field, link and menu item of a window
with its name and on-screen position, for normal apps, Office, File Explorer, Settings and the browsers. No special
permission is needed. Screenshots (for the optional vision model) come from mss.
"""
import re
import threading
import time

import computer_use
import winctl
from computer_use import Element, Observation

try:
    import uiautomation as auto
except Exception:   # not Windows, or the package is missing: available() says so
    auto = None

if winctl.IS_WIN:
    winctl.make_dpi_aware()   # before any window work, so read positions and clicked positions agree

INTERACTIVE = {
    "ButtonControl": "button", "EditControl": "text field", "HyperlinkControl": "link", "MenuItemControl": "menu item",
    "ListItemControl": "list item", "TabItemControl": "tab", "CheckBoxControl": "checkbox",
    "RadioButtonControl": "radio button", "ComboBoxControl": "combo box", "TreeItemControl": "tree item",
    "DataItemControl": "item", "SplitButtonControl": "split button", "SliderControl": "slider",
    "MenuBarControl": "menu bar", "SpinnerControl": "spinner", "DocumentControl": "document",
}
CONTEXT = {"TextControl": "text", "HeaderItemControl": "header", "ImageControl": "image"}
OWN_PROCESSES = {"jarvis.exe", "electron.exe", "jarvis-backend.exe"}   # never operate Jarvis himself
MAX_ELEMENTS = 400
TIME_BUDGET_MS = 2000   # a huge web page, or an app that stopped answering, must not stall a step
_com_ready = threading.local()
# UI Automation property ids (UIAutomationClient.h), read for every element in one cross-process call (see _collect)
CONTROL_TYPE, NAME, RECT, ENABLED, FOCUSED, OFFSCREEN, PASSWORD, VALUE = (30003, 30005, 30001, 30010, 30008, 30022,
                                                                          30019, 30045)


def _ensure_com() -> None:
    """UI Automation is COM, and COM must be started on each thread that uses it ("CoInitialize has not been called"
    otherwise). Computer control runs on its own thread, so start it there, once per thread."""
    if getattr(_com_ready, "done", False):
        return
    import comtypes
    try:
        comtypes.CoInitializeEx()   # the same mode the main thread gets on import
    except OSError:
        pass   # already started on this thread in another mode: usable as it is
    _com_ready.done = True


def _uia():
    """This thread's UI Automation client, with timeouts: an app that hangs gives up after TIME_BUDGET_MS instead of
    stalling the whole task (the plain client waits forever)."""
    client = getattr(_com_ready, "client", None)
    if client is None:
        import comtypes.client
        core = auto.uiautomation._AutomationClient.instance().UIAutomationCore
        client = comtypes.client.CreateObject(core.CUIAutomation8, interface=core.IUIAutomation2)
        client.ConnectionTimeout = client.TransactionTimeout = TIME_BUDGET_MS
        request = client.CreateCacheRequest()
        for prop in (CONTROL_TYPE, NAME, RECT, ENABLED, FOCUSED, PASSWORD, VALUE):
            request.AddProperty(prop)
        kinds = [client.CreatePropertyCondition(CONTROL_TYPE, getattr(auto.ControlType, name))
                 for name in list(INTERACTIVE) + list(CONTEXT)]
        wanted = kinds[0]
        for kind in kinds[1:]:
            wanted = client.CreateOrCondition(wanted, kind)
        _com_ready.condition = client.CreateAndCondition(wanted, client.CreatePropertyCondition(OFFSCREEN, False))
        _com_ready.request = request
        _com_ready.client = client
    return client


def _control(handle):
    """The uiautomation Control for a raw element (its patterns: Invoke, Value, Toggle...), or None."""
    return auto.Control.CreateControlFromElement(handle) if handle is not None else None


class WindowsScreen(computer_use.Environment):
    name = "Windows"

    def available(self):
        if not winctl.IS_WIN:
            return False, "This is the Windows version of computer control."
        if auto is None:
            return False, "Computer control needs the UI Automation package, which is missing from this install."
        return True, ""

    # ---------- looking ----------
    def _target_window(self):
        """The window the user is working in: the one in front, or the one right behind Jarvis's own window."""
        front = winctl.foreground_window()
        if front and winctl.window_process_name(front) not in OWN_PROCESSES:
            return front
        for hwnd, _title in winctl.list_windows():
            if winctl.window_process_name(hwnd) not in OWN_PROCESSES:
                return hwnd
        return front

    def observe(self) -> Observation:
        _ensure_com()
        hwnd = self._target_window()
        self._target = hwnd
        observation = Observation()
        observation.cursor = winctl.cursor_position()
        observation.sample = self.screen_sample()
        observation.screenshot, observation.screen_size = self._screenshot()
        observation.other_windows = [title for h, title in winctl.list_windows()
                                     if h != hwnd and winctl.window_process_name(h) not in OWN_PROCESSES][:15]
        if not hwnd:
            observation.note = "No window is in front."
            return observation
        window = auto.ControlFromHandle(hwnd)
        if window is None:
            observation.note = "The window in front can't be read."
            return observation
        observation.window = window.Name or ""
        observation.app = (winctl.window_process_name(hwnd) or "").removesuffix(".exe")
        observation.elements = self._collect(hwnd)
        return observation

    def _collect(self, hwnd) -> list:
        """Every interesting element of the window, read in one cached UI Automation call: several times faster than
        walking the tree property by property, which ran out of time halfway through a browser or VS Code."""
        names = {getattr(auto.ControlType, name): name for name in list(INTERACTIVE) + list(CONTEXT)}
        elements = []
        try:
            client = _uia()
            found = client.ElementFromHandle(hwnd).FindAllBuildCache(4, _com_ready.condition,   # 4: descendants
                                                                     _com_ready.request)
            count = found.Length if found else 0
        except Exception as e:   # the app didn't answer in time, or its window just closed
            print(f"Reading the window failed: {e}", flush=True)
            return elements
        for i in range(count):
            if len(elements) >= MAX_ELEMENTS:
                break
            try:
                item = found.GetElement(i)
                type_name = names.get(item.CachedControlType, "")
                kind = INTERACTIVE.get(type_name) or CONTEXT.get(type_name)
                rect = item.CachedBoundingRectangle
                width, height = rect.right - rect.left, rect.bottom - rect.top
                if not kind or width <= 1 or height <= 1:
                    continue
                name = (item.CachedName or "").strip()
                if type_name in CONTEXT and not name:
                    continue
                password = bool(item.CachedIsPassword)
                value = ""
                if kind in ("text field", "combo box", "document") and not password:
                    value = str(item.GetCachedPropertyValue(VALUE) or "")[:200]
                elements.append(Element(
                    id=len(elements) + 1, role=kind, name=name[:120], value=value,
                    rect=(rect.left, rect.top, width, height), enabled=bool(item.CachedIsEnabled),
                    focused=bool(item.CachedHasKeyboardFocus), password=password, handle=item))
            except Exception:
                continue   # an element that vanished mid-read is simply skipped
        return elements

    def _screenshot(self):
        try:
            import mss
            from PIL import Image
            with mss.mss() as grab:
                monitor = grab.monitors[1]
                shot = grab.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.rgb), (monitor["width"], monitor["height"])
        except Exception:
            return None, (0, 0)

    def cursor(self):
        return winctl.cursor_position()

    def screen_sample(self):
        try:
            return winctl.screen_sample()
        except Exception:
            return None

    def still_valid(self, element=None) -> bool:
        """The window being worked in is still in front and the element (if any) is where it was: a planned next action
        can go ahead without reading the whole window again."""
        target = getattr(self, "_target", None)
        front = winctl.foreground_window()
        if not target or (front != target and winctl.window_process_name(front) not in OWN_PROCESSES):
            return False
        if element is None:
            return True
        try:
            rect = element.handle.CurrentBoundingRectangle
            same = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top) == tuple(element.rect)
            return same and bool(element.handle.CurrentIsEnabled) and not element.handle.CurrentIsOffscreen
        except Exception:
            return False   # it's gone

    # ---------- acting ----------
    def _bring_forward(self) -> None:
        """Keys and clicks go to the window in front: if that is Jarvis's own, put the one being worked in first."""
        target = getattr(self, "_target", None)
        front = winctl.foreground_window()
        if target and front != target and winctl.window_process_name(front) in OWN_PROCESSES:
            winctl.focus(target)
            time.sleep(0.15)

    def focus_moved(self) -> bool:
        target = getattr(self, "_target", None)
        front = winctl.foreground_window()
        if not target or not front or front == target or winctl.window_process_name(front) in OWN_PROCESSES:
            return False
        return winctl.window_process_name(front) != winctl.window_process_name(target)   # a dialog of the same app is fine

    def read_value(self, element: Element):
        try:
            control = _control(element.handle)
            pattern = control.GetPattern(auto.PatternId.ValuePattern) if control is not None else None
            return None if pattern is None else (pattern.Value or "")
        except Exception:
            return None

    def set_value(self, element: Element, value: str) -> str:
        try:
            control = _control(element.handle)
            pattern = control.GetPattern(auto.PatternId.ValuePattern) if control is not None else None
            if pattern is None or pattern.IsReadOnly:
                return "this field can't be filled in directly"
            pattern.SetValue(value)
            return ""
        except Exception as e:
            return f"{type(e).__name__}"

    def focus_element(self, element: Element) -> str:
        self._bring_forward()
        control = _control(element.handle)
        if control is not None:
            try:
                control.SetFocus()
                time.sleep(0.15)
                if control.HasKeyboardFocus:
                    return ""
            except Exception:
                pass
        self.click(element.center)   # some fields only take the cursor from a real click
        time.sleep(0.3)
        try:
            focused = auto.GetFocusedControl()   # a combo box's text part is a child of the combo box
            if control is None or control.HasKeyboardFocus or (
                    focused is not None and auto.ControlsAreSame(focused.GetParentControl(), control)):
                return ""
        except Exception:
            return ""   # can't tell: the click is the best there is
        return (f"I couldn't put the cursor in [{element.id}] {element.label()}, so nothing was typed. Try clicking "
                "it first, or pick another element.")

    def press_element(self, element: Element) -> str:
        control = _control(element.handle)
        if control is not None:
            try:
                if element.role in ("text field", "combo box", "document"):
                    control.SetFocus()
                    return ""
                pattern = control.GetPattern(auto.PatternId.InvokePattern)
                if pattern is not None:
                    pattern.Invoke()
                    return ""
                for pattern_id, call in ((auto.PatternId.TogglePattern, "Toggle"),
                                         (auto.PatternId.SelectionItemPattern, "Select"),
                                         (auto.PatternId.ExpandCollapsePattern, "Expand")):
                    pattern = control.GetPattern(pattern_id)
                    if pattern is not None:
                        getattr(pattern, call)()
                        return ""
            except Exception:
                pass   # fall back to a real click
        return self.click(element.center)

    def click(self, point, button="left", double=False) -> str:
        self._bring_forward()
        winctl.click(point[0], point[1], button=button, double=double)
        return ""

    def drag(self, start, end) -> str:
        self._bring_forward()
        winctl.drag(start[0], start[1], end[0], end[1])
        return ""

    def type_text(self, text: str) -> str:
        self._bring_forward()
        # A paste arrives whole; keys typed one by one get garbled by a slow app (Windows 11's Notepad while the
        # screen is being captured). Keys only for a character or two, or when the clipboard holds a picture or files.
        if len(text) > 2 and winctl.paste_text(text):
            return ""
        winctl.type_text(text, strict=True)
        return ""

    def press_keys(self, keys: list) -> str:
        names = []
        for key in keys:
            key = {"cmd": "ctrl", "meta": "win", "return": "enter", "option": "alt"}.get(key, key)
            if key not in winctl.VK:
                return f"Unknown key “{key}”."
            names.append(key)
        self._bring_forward()
        winctl.press(*names, strict=True)
        return ""

    def _target_center(self):
        """The middle of the window being worked in (where a scroll with no element goes), or None."""
        import ctypes
        from ctypes import wintypes
        target = getattr(self, "_target", None) or self._target_window()
        rect = wintypes.RECT()
        if not target or not ctypes.windll.user32.GetWindowRect(wintypes.HWND(target), ctypes.byref(rect)):
            return None
        return ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)

    def scroll(self, amount: int, point=None) -> str:
        # Wheel turns go to whatever is under the pointer: with no element given, that must be the window being
        # worked in (brought forward), not wherever the pointer happened to be (Jarvis's own window, the desktop).
        self._bring_forward()
        point = point or self._target_center()
        if point is not None:
            winctl.scroll(amount, point[0], point[1])
        else:
            winctl.scroll(amount)
        return ""

    def switch_window(self, title: str) -> str:
        windows = [(hwnd, t) for hwnd, t in winctl.list_windows()
                   if winctl.window_process_name(hwnd) not in OWN_PROCESSES]
        # The whole title first, then its parts: an AI often writes "Notepad - Notes" for the window "*Notes - Notepad".
        parts = [title] + [p for p in re.split(r"\s+[-–—|]\s+", title) if len(p.strip()) > 2]
        for wanted in (p.strip().lower().lstrip("*") for p in parts):
            for hwnd, window_title in windows:
                if wanted in window_title.lower():
                    if hwnd == getattr(self, "_target", None):
                        return f"“{window_title}” is already the window in front: work in it."
                    return "" if winctl.focus(hwnd) else f"Windows didn't let me bring “{window_title}” to the front."
        return f"No open window called “{title}”."
