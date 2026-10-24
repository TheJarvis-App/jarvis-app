"""Quick Access's double-press gesture (quick_keys.DoubleTap): only a deliberate double tap of the modifier alone opens
the panel; everyday use of Command or Shift never does."""
from quick_keys import DoubleTap


def run(events, step=0.016):
    """events: (seconds held or gap, held, others, count) segments, sampled every `step` like the watcher does.
    Returns the times the gesture fired."""
    tap, t, fired = DoubleTap(), 0.0, []
    for seconds, held, others, count in events:
        end = t + seconds
        while t < end:
            if tap.feed(t, held, others, count):
                fired.append(round(t, 3))
            t += step
    return fired


def taps(*segments):
    return run([s for seg in segments for s in seg])


TAP = [(0.09, True, False, 0)]
GAP = [(0.15, False, False, 0)]
IDLE = [(0.5, False, False, 0)]


def test_a_deliberate_double_tap_fires_once():
    assert len(taps(IDLE, TAP, GAP, TAP, IDLE)) == 1


def test_a_single_tap_or_a_long_hold_never_fires():
    assert taps(IDLE, TAP, IDLE) == []
    assert taps(IDLE, [(0.8, True, False, 0)], GAP, [(0.8, True, False, 0)], IDLE) == []


def test_too_slow_between_taps_does_not_fire():
    assert taps(IDLE, TAP, [(0.6, False, False, 0)], TAP, IDLE) == []


def test_shortcuts_and_typing_never_fire():
    # ⌘C then ⌘V: another key goes down while the modifier is held (the counter moves)
    assert run([(0.3, False, False, 0), (0.09, True, False, 1), (0.1, False, False, 1), (0.09, True, False, 2), (0.3, False, False, 2)]) == []
    # two capitals typed quickly: same thing with Shift
    assert run([(0.3, False, False, 5), (0.06, True, False, 6), (0.08, False, False, 6), (0.06, True, False, 7), (0.3, False, False, 7)]) == []
    # a key typed between two clean taps
    assert run([(0.3, False, False, 0), (0.09, True, False, 0), (0.1, False, False, 3), (0.09, True, False, 3), (0.3, False, False, 3)]) == []
    # Command with another modifier (⌘⇧) is not a tap of Command alone
    assert run([(0.3, False, False, 0), (0.09, True, True, 0), (0.1, False, False, 0), (0.09, True, True, 0), (0.3, False, False, 0)]) == []


def test_a_triple_tap_fires_once_and_a_fourth_waits_for_the_cooldown():
    fired = taps(IDLE, TAP, GAP, TAP, GAP, TAP, GAP, TAP, IDLE)
    assert len(fired) == 1
    fired = taps(IDLE, TAP, GAP, TAP, [(0.9, False, False, 0)], TAP, GAP, TAP, IDLE)
    assert len(fired) == 2


def test_the_windows_reader_counts_other_keys_only_during_a_gesture():
    from quick_keys import _WindowsKeys
    down = set()
    keys = _WindowsKeys.__new__(_WindowsKeys)
    keys.get, keys.count, keys.busy, calls = (lambda vk: 0x8000 if vk in down else 0), 0, False, []
    original = keys.get
    keys.get = lambda vk: (calls.append(vk), original(vk))[1]
    down.add(0x11)                     # Ctrl held
    assert keys.sample("command") == (True, False, 0)
    down.add(0x43)                     # …and C: Ctrl+C
    assert keys.sample("command")[2] == 1
    down.clear(); keys.busy = False; calls.clear()
    keys.sample("command")             # idle: only the modifiers are read, not every key
    assert len(calls) <= 6
    down.add(0x10)                     # Shift with Ctrl: another modifier
    down.add(0x11)
    assert keys.sample("command")[1] is True


def test_quick_access_settings_only_take_real_shortcuts():
    import pytest
    import settings
    import sys
    # the Mac's default is holding ⌘ for 3 s (⌥ Space beside it); elsewhere a key combination
    assert settings.BY_KEY["JARVIS_QUICK_SHORTCUT"]["default"] == ("hold-command" if sys.platform == "darwin" else "Alt+Space")
    choices = [c[0] for c in settings.BY_KEY["JARVIS_QUICK_SHORTCUT"]["choices"]]
    from quick_keys import GESTURES
    assert all(c in GESTURES or c == "custom" or settings.is_accelerator(c) for c in choices)
    assert settings.validate("JARVIS_QUICK_CUSTOM", "Control+Shift+K") == "Control+Shift+K"
    for bad in ("K", "Shift", "Control+Control+K", "Hyper+K", "Control+Shift+Banana"):
        with pytest.raises(ValueError):
            settings.validate("JARVIS_QUICK_CUSTOM", bad)


def hold(events, step=0.016):
    from quick_keys import Hold
    h, t, fired = Hold(), 0.0, []
    for seconds, held, others, count in events:
        end = t + seconds
        while t < end:
            if h.feed(t, held, others, count):
                fired.append(round(t, 2))
            t += step
    return fired


def test_holding_command_three_seconds_opens_once():
    assert hold([(0.5, False, False, 0), (1.0, True, False, 0), (0.5, False, False, 0)]) == []          # 1 s: nothing
    assert hold([(0.5, False, False, 0), (2.0, True, False, 0), (0.5, False, False, 0)]) == []          # 2 s: nothing
    assert hold([(0.5, False, False, 0), (2.9, True, False, 0), (0.5, False, False, 0)]) == []          # let go just before
    fired = hold([(0.5, False, False, 0), (6.0, True, False, 0), (0.5, False, False, 0)])
    assert len(fired) == 1 and 3.45 <= fired[0] <= 3.55                                             # at 3 s, once, still held
    # let go, hold again: opens again
    assert len(hold([(0.5, False, False, 0), (3.2, True, False, 0), (0.4, False, False, 0), (3.2, True, False, 0), (0.2, False, False, 0)])) == 2


def test_a_command_shortcut_during_the_hold_cancels_it():
    # ⌘C after 1 s, still holding ⌘ to 4 s: that press is spent
    assert hold([(0.5, False, False, 0), (1.0, True, False, 0), (3.0, True, False, 1), (0.5, False, False, 1)]) == []
    # ⌘⇧ (another modifier with it)
    assert hold([(0.5, False, False, 0), (1.0, True, False, 0), (3.0, True, True, 0), (0.5, False, False, 0)]) == []
    # already holding Shift when ⌘ goes down
    assert hold([(0.5, False, False, 0), (4.0, True, True, 0), (0.5, False, False, 0)]) == []


def test_a_hold_already_under_way_when_watching_starts_never_counts():
    # Jarvis started by holding ⌘ (Jarvis Wake): his own watcher must not count the same press and close the bar
    assert hold([(5.0, True, False, 0), (0.3, False, False, 0)]) == []
    assert len(hold([(5.0, True, False, 0), (0.3, False, False, 0), (3.3, True, False, 0)])) == 1
