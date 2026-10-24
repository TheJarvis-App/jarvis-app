"""Quick Access's modifier gestures: holding ⌘ Command (Ctrl on Windows) for three seconds, or pressing ⌘ Command, ⌥
Option (Alt) or Shift twice, opens the Jarvis bar from any app.

Key combinations (⌥ Space and the like) are registered by the window (quick.js, Electron's globalShortcut: the
operating system's own hotkey service, no permission needed). A modifier pressed on its own can't be registered that
way, so this watches the modifier keys instead, and only counts a deliberate double tap:

  * a tap is the modifier alone, pressed and released within TAP_MAX seconds, with no other key, mouse button or
    modifier touched while it was down (so ⌘C, Shift+A and ⌘-click never count);
  * the second tap starts within GAP_MAX seconds of the first ending, again with nothing else pressed in between
    (so ⌘C ⌘V, or typing two capitals, never count);
  * after a trigger, nothing counts for COOLDOWN seconds.

A hold (the Mac's default) is the modifier alone, held down for HOLD_SECONDS: it opens the bar the moment the time is
up (no need to let go), once; letting go sooner cancels it; any other key or modifier pressed meanwhile (⌘C, ⌘Tab)
spoils that press until the modifier is released. Mouse clicks don't (an auto-clicker or a stray tap mustn't block
it), but a button held down when the time is up (dragging with ⌘) does. Left and right keys count the same.

How it watches: the state of the modifier keys is read about 60 times a second (macOS: Quartz's event-source state,
with its key-press counter telling whether anything else was typed; Windows: GetAsyncKeyState). Nothing is
intercepted or delayed: other apps receive every key exactly as before. No keystroke is read, only whether keys are
down and how many have been pressed, which macOS gives without Input Monitoring (checked on macOS 26: a Jarvis started
in the background, with no such permission, sees the hold and a ⌘C during it). Every hold of a second or more is
logged with how it ended, so a hold that "did nothing" can be explained.
"""
import sys
import threading
import time

TAP_MAX = 0.4
GAP_MAX = 0.5
COOLDOWN = 0.7
HOLD_SECONDS = 3.0
GESTURES = {"hold-command": "command", "double-command": "command", "double-option": "option", "double-shift": "shift",
            "double-control": "control"}


class DoubleTap:
    """The gesture itself, fed samples: feed(t, held, others, count) -> True when a double tap completes.

    held: the watched modifier is down; others: any other modifier is down; count: a counter that changes whenever
    any other key or mouse button is pressed (the platform supplies it)."""

    def __init__(self):
        self.down_at = None        # when the current press began
        self.down_count = None
        self.clean = True          # nothing else touched during the current press
        self.last_tap = None       # (ended at, count at that moment) of a clean tap, waiting for its pair
        self.cool_until = 0.0

    def feed(self, t: float, held: bool, others: bool, count: int) -> bool:
        if self.last_tap and (t - self.last_tap[0] > GAP_MAX or count != self.last_tap[1]) and self.down_at is None:
            self.last_tap = None   # too slow, or something was typed between the taps
        if held:
            if self.down_at is None:
                self.down_at, self.down_count, self.clean = t, count, not others
                if self.last_tap and (t - self.last_tap[0] > GAP_MAX or count != self.last_tap[1]):
                    self.last_tap = None
            elif others or count != self.down_count:
                self.clean = False
            return False
        if self.down_at is None:
            return False
        began, self.down_at = self.down_at, None
        tap = self.clean and count == self.down_count and t - began <= TAP_MAX and not others
        if not tap or t < self.cool_until:
            self.last_tap = None
            return False
        if self.last_tap:
            self.last_tap = None
            self.cool_until = t + COOLDOWN
            return True
        self.last_tap = (t, count)
        return False


class Hold:
    """The hold gesture, fed the same samples as DoubleTap: True once, the moment the modifier has been held alone
    for `seconds`."""

    def __init__(self, seconds: float = HOLD_SECONDS):
        self.seconds = seconds
        self.down_at = None
        self.down_count = None
        self.spent = False       # this press was used for a shortcut, or has already opened the bar
        self.armed = False       # a release has been seen: a press already under way when watching began never counts
        self.last_tap = None     # (DoubleTap's; never set here)

    def feed(self, t: float, held: bool, others: bool, count: int) -> bool:
        if not held:
            self.down_at, self.spent, self.armed = None, False, True   # let go: the next press starts afresh
            return False
        if self.down_at is None:
            self.down_at, self.down_count, self.spent = t, count, others or not self.armed
            return False
        if others or count != self.down_count:
            self.spent = True
        if not self.spent and t - self.down_at >= self.seconds:
            self.spent = True
            return True
        return False


# ---------- reading the keyboard ----------
class _MacKeys:
    def __init__(self):
        import Quartz
        self.Q = Quartz
        # the combined state: the keyboard itself plus keys posted by software (assistive tools, tests); the hardware
        # state alone misses those
        self.source = Quartz.kCGEventSourceStateCombinedSessionState
        self.masks = {"command": Quartz.kCGEventFlagMaskCommand, "option": Quartz.kCGEventFlagMaskAlternate,
                      "shift": Quartz.kCGEventFlagMaskShift, "control": Quartz.kCGEventFlagMaskControl}
        self.counted = [Quartz.kCGEventKeyDown]   # keys only: clicks (an auto-clicker, a tap) don't spoil a hold

    def allowed(self) -> bool:
        try:
            return bool(self.Q.CGPreflightListenEventAccess())
        except AttributeError:   # older macOS: no such permission
            return True

    def ask(self) -> None:
        try:
            self.Q.CGRequestListenEventAccess()
        except AttributeError:
            pass

    def mouse_down(self) -> bool:
        return any(self.Q.CGEventSourceButtonState(self.source, b) for b in (0, 1, 2))

    def sample(self, which: str):
        flags = self.Q.CGEventSourceFlagsState(self.source)
        held = bool(flags & self.masks[which])
        others = any(flags & m for k, m in self.masks.items() if k != which)
        count = sum(self.Q.CGEventSourceCounterForEventType(self.source, e) for e in self.counted)
        return held, others, count


_WIN_MODIFIERS = (0x10, 0x11, 0x12, 0x5B, 0x5C)   # Shift, Ctrl, Alt, both Windows keys
# every other key and the mouse buttons: scanned only while a gesture is under way, so idle costs nothing
_WIN_MOUSE = (0x01, 0x02, 0x04, 0x05, 0x06)
_WIN_OTHERS = [vk for vk in range(0x01, 0xFF) if vk not in _WIN_MODIFIERS + _WIN_MOUSE and vk not in range(0xA0, 0xA6) and vk not in (0x07, 0x0A, 0x0B)]


class _WindowsKeys:
    VK = {"command": 0x11, "control": 0x11, "option": 0x12, "shift": 0x10}   # Ctrl, Ctrl, Alt, Shift
    MODIFIERS = _WIN_MODIFIERS
    OTHERS = _WIN_OTHERS

    def __init__(self):
        import ctypes
        self.get = ctypes.windll.user32.GetAsyncKeyState
        self.count = 0
        self.busy = False

    def allowed(self) -> bool:
        return True

    def ask(self) -> None:
        pass

    def _down(self, vk) -> bool:
        return bool(self.get(vk) & 0x8000)

    def mouse_down(self) -> bool:
        return any(self._down(vk) for vk in _WIN_MOUSE)

    def sample(self, which: str):
        mine = self.VK[which]
        held = self._down(mine)
        others = any(self._down(vk) for vk in self.MODIFIERS if vk != mine)
        if held or self.busy:   # a press, or a gap between taps: is anything else down?
            if any(self._down(vk) for vk in self.OTHERS):
                self.count += 1
        return held, others, self.count


class Watcher:
    """Watches for the chosen gesture on a background thread and calls on_trigger(). configure() changes it."""

    def __init__(self, on_trigger, log=print):
        self.on_trigger, self.log = on_trigger, log
        self.gesture = None
        self.keys = None
        self.thread = None
        self.stop_event = threading.Event()
        self.status = {"gesture": None, "ok": True, "message": ""}

    def configure(self, gesture):
        """gesture: one of GESTURES, or None to stop watching. Returns the status for Settings."""
        gesture = gesture if gesture in GESTURES else None
        if gesture == self.gesture and (self.thread or not gesture):
            return self.status
        self.stop()
        self.gesture = gesture
        if not gesture:
            self.status = {"gesture": None, "ok": True, "message": ""}
            return self.status
        try:
            self.keys = _MacKeys() if sys.platform == "darwin" else _WindowsKeys() if sys.platform == "win32" else None
        except Exception as e:
            self.keys = None
            self.log(f"Quick Access: can't watch the keyboard ({e}).")
        if self.keys is None:
            self.status = {"gesture": gesture, "ok": False, "message": "A double press isn't available on this computer. Choose a key combination instead."}
            return self.status
        self.status = {"gesture": gesture, "ok": True, "message": ""}
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, args=(gesture,), daemon=True, name="quick-keys")
        self.thread.start()
        return self.status

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)
        self.thread = None

    def _run(self, gesture):
        which, keys = GESTURES[gesture], self.keys
        tap = Hold() if gesture.startswith("hold-") else DoubleTap()
        was_held, fired = False, False
        while not self.stop_event.is_set():
            try:
                held, others, count = keys.sample(which)
            except Exception as e:
                self.log(f"Quick Access: stopped watching the keyboard ({e}).")
                return
            now = time.monotonic()
            if isinstance(tap, Hold) and held != was_held:   # every hold of a second or more, in the log, with how it ended
                if not held and tap.down_at is not None and now - tap.down_at >= 1.0 and not tap.spent:
                    self.log(f"Quick Access: ⌘ held {now - tap.down_at:.1f} s, let go before {tap.seconds:g} s.")
                elif not held and tap.down_at is not None and now - tap.down_at >= 1.0 and not fired:
                    self.log(f"Quick Access: ⌘ held {now - tap.down_at:.1f} s, not counted (another key or modifier, or already down when watching began).")
                if not held:
                    fired = False
                was_held = held
            if tap.feed(now, held, others, count) and not keys.mouse_down():   # (dragging with the key held: not for us)
                fired = True
                try:
                    self.on_trigger(gesture)
                except Exception as e:
                    self.log(f"Quick Access: couldn't open the panel ({e}).")
            busy = tap.down_at is not None or tap.last_tap is not None
            if isinstance(keys, _WindowsKeys):
                keys.busy = busy
            # quicker while a gesture is under way, relaxed otherwise
            self.stop_event.wait(0.008 if busy else 0.016)
