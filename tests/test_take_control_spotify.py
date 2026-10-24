"""Taking control to play something on Spotify (the reported failure: "I couldn't bring Spotify to the front").

  * Which app is in front is read fresh from the system (lsappinfo): AppKit's own frontmostApplication() and
    runningApplications() never update in Jarvis's engine, so Spotify coming to the front was never seen.
  * With the user's Spotify keys, the exact playlist / album / song is found, its page opened in the app, and the app
    plays it; it is called done only when Spotify reports that exact thing playing.
  * A Spotify that accepts a request but doesn't play is never announced as "Playing …"."""
import sys
import time
from types import SimpleNamespace

import pytest

import sandbox

app = screen_mac = spotify_local = None


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app, screen_mac, spotify_local
    sandbox.install()
    import app as a, screen_mac as s, spotify_local as sl
    app, screen_mac, spotify_local = a, s, sl
    yield
    sandbox.uninstall()


# ---- the front app, read fresh ----
def test_running_app_reads_lsappinfo_as_it_really_prints(monkeypatch):
    calls = []

    def fake(*args):
        calls.append(args)
        if args[0] == "find":
            return 'ASN:0x0-0x1e41e4-"Spotify":\n'          # the real format: the name is part of it
        return '"pid"=50119\n'
    monkeypatch.setattr(screen_mac, "_lsappinfo", fake)
    monkeypatch.setattr(screen_mac, "AppKit", SimpleNamespace(NSRunningApplication=SimpleNamespace(
        runningApplicationWithProcessIdentifier_=lambda pid: SimpleNamespace(pid=pid, localizedName=lambda: "Spotify"))))
    found = screen_mac.running_app("Spotify")
    assert found.pid == 50119 and calls[1] == ("info", "-only", "pid", "ASN:0x0-0x1e41e4:")


def test_front_app_is_read_fresh_each_time(monkeypatch):
    fronts = iter(['ASN:0x0-0x1:\n', 'ASN:0x0-0x2:\n'])
    names = {"0x1": "Finder", "0x2": "Spotify"}
    last = {}

    def fake(*args):
        if args[0] == "front":
            last["asn"] = next(fronts)
            return last["asn"]
        return f'"pid"={int(last["asn"].strip().split("-")[1].rstrip(":"), 16)}\n'
    monkeypatch.setattr(screen_mac, "_lsappinfo", fake)
    monkeypatch.setattr(screen_mac, "AppKit", SimpleNamespace(NSRunningApplication=SimpleNamespace(
        runningApplicationWithProcessIdentifier_=lambda pid: SimpleNamespace(localizedName=lambda: names[f"0x{pid}"]))))
    assert [screen_mac.front_name(), screen_mac.front_name()] == ["Finder", "Spotify"]   # not frozen at the first answer


def test_nothing_in_computer_control_uses_appkits_stale_lists():
    for name in ("screen_mac.py", "spotify_local.py"):
        with open(name, encoding="utf-8") as f:
            code = "\n".join(line for line in f if not line.lstrip().startswith("#"))
        assert "frontmostApplication()" not in code.replace("NSWorkspace.frontmostApplication() and runningApplications() never", "")
        assert "sharedWorkspace().runningApplications()" not in code, name


# ---- the exact steps ----
@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(spotify_local, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))
    monkeypatch.setattr(spotify_local, "installed", lambda: True)
    monkeypatch.setattr(spotify_local, "IS_MAC", True)
    monkeypatch.setattr(spotify_local, "_mac_bring_forward", lambda: True)
    monkeypatch.setattr(spotify_local, "_mac_now", lambda: ("playing", "spotify:track:before", "x"))
    monkeypatch.setattr(spotify_local, "open_uri", lambda uri: None)


def run_steps(steps):
    out = None
    for _label, step in steps:
        out = step()
    return out


def test_done_only_when_spotify_confirms_that_exact_playlist(quick, monkeypatch):
    confirms = iter([False, False, True])      # for a moment Spotify still reports what played before
    monkeypatch.setattr(spotify_local, "_osa", lambda c, timeout=8.0: "")
    monkeypatch.setattr(spotify_local, "now_playing", lambda: (True, "Enjoy the Silence by Depeche Mode"))
    steps = spotify_local.exact_steps(lambda: ("spotify:playlist:p", "your playlist My favorite songs"), lambda uri: next(confirms))
    assert run_steps(steps) == "Playing your playlist My favorite songs on Spotify (now: Enjoy the Silence by Depeche Mode)."


def test_something_else_playing_is_never_called_done(quick, monkeypatch):
    monkeypatch.setattr(spotify_local, "_osa", lambda c, timeout=8.0: "")
    monkeypatch.setattr(spotify_local, "now_playing", lambda: (True, "Relax by Frankie Goes To Hollywood"))
    steps = spotify_local.exact_steps(lambda: ("spotify:playlist:p", "your playlist My favorite songs"), lambda uri: False)
    with pytest.raises(spotify_local.SpotifyLocalError, match="playing Relax by Frankie Goes To Hollywood, not your playlist"):
        run_steps(steps)


def test_not_found_stops_before_anything_plays(quick, monkeypatch):
    played = []
    monkeypatch.setattr(spotify_local, "_osa", lambda c, timeout=8.0: played.append(c))

    def find():
        raise spotify_local.SpotifyLocalError("I couldn't find a playlist called Zebra in your Spotify.")
    with pytest.raises(spotify_local.SpotifyLocalError, match="couldn't find a playlist called Zebra"):
        run_steps(spotify_local.exact_steps(find, lambda uri: True))
    assert not played


def test_liked_songs_are_started_through_spotify_not_the_apps_command(quick, monkeypatch):
    """The app's own play command can't start the liked songs (measured: it kept playing what it was)."""
    used = []
    monkeypatch.setattr(spotify_local, "_osa", lambda c, timeout=8.0: used.append(c))
    monkeypatch.setattr(spotify_local, "now_playing", lambda: (True, "a liked song"))
    steps = spotify_local.exact_steps(lambda: (app.LIKED_SONGS, "your liked songs"), lambda uri: True, start=lambda uri: used.append(("api", uri)))
    assert run_steps(steps).startswith("Playing your liked songs on Spotify") and used == [("api", app.LIKED_SONGS)]


# ---- never "Playing …" when it didn't start ----
def test_a_start_spotify_accepts_but_never_plays_is_said_honestly(monkeypatch):
    calls = []
    fake = SimpleNamespace(start_playback=lambda **k: calls.append(k), shuffle=lambda *a, **k: None,
                           current_playback=lambda: {"is_playing": False, "context": {"uri": "spotify:playlist:p"}})
    monkeypatch.setattr(app, "sp", fake)
    monkeypatch.setattr(app, "spotify_library", lambda: SimpleNamespace(
        current_user_playlists=lambda limit, offset: {"items": [{"name": "My favorite songs", "uri": "spotify:playlist:p"}], "next": None},
        current_playback=fake.current_playback))
    monkeypatch.setattr(app, "ensure_spotify_device", lambda timeout=20.0: "dev")
    monkeypatch.setattr(app.osal, "IS_MAC", False)       # the Web API path (as on Windows)
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    reply = app.play_spotify_collection(app.music.parse_music_request('play "My favorite songs" playlist on spotify'))
    assert reply.startswith("I asked Spotify to play My favorite songs, but it didn't start") and "Playing" not in reply
    assert calls and calls[-1] == {"device_id": "dev"}   # it also tried pressing play once on what it had loaded
