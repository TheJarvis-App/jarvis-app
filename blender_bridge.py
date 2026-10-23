"""Runs *inside* Blender (`blender --python blender_bridge.py`), so Jarvis can build things with Blender's own
Python API instead of guessing mouse clicks.

The protocol is two files in a temp folder: Jarvis writes `request.json` ({"id", "code"}), this script execs
`code` and writes `response.json` ({"id", "ok", "output", "error"}). Requests are polled from a Blender timer
(`bpy.app.timers`) because the `bpy` API only works on Blender's own main thread — a background thread calling it
directly would crash or silently do nothing.

`code` runs against a namespace that persists for as long as Blender stays open, so a later command ("make it
wooden") can refer to what an earlier one left behind (`bpy.context.object`, a variable it set, a helper function
it defined) without re-establishing context. Setting a module-level `RESULT` string in the code is how a step
reports what it did; without one, whatever the code printed is used instead.

`process_one()` has no `bpy` of its own (only what the caller's `namespace` provides), which is what makes it
testable without a real Blender process — see tests/test_blender_control.py.

A request may say when Jarvis stops waiting for it ("expires"). One read after that is skipped, never run: Jarvis
has already told the user it didn't happen, so running it late would be a surprise change — like a request left in
the folder when Blender closed, which the next Blender would otherwise run on whatever file it opens. While a
script runs, `busy.json` names it, so Jarvis can tell "still working" (a long render) from "not answering".
"""
import contextlib
import io
import json
import os
import random
import tempfile
import time
import traceback

BRIDGE_DIR = os.path.join(tempfile.gettempdir(), "jarvis_blender_bridge")
REQUEST_FILE = os.path.join(BRIDGE_DIR, "request.json")
RESPONSE_FILE = os.path.join(BRIDGE_DIR, "response.json")
POLL_SECONDS = 0.15

_namespace = {"__name__": "jarvis_blender"}
_last_id = None


def busy_file() -> str:
    return os.path.join(os.path.dirname(REQUEST_FILE), "busy.json")


def process_one(request: dict, namespace: dict) -> dict:
    """Run one request's code against `namespace` (mutated in place, so it persists across calls); return the
    response to write back. Never raises: a broken script is reported as an error, not a crash — that includes
    sys.exit()/SystemExit, which would otherwise end the bridge (or Blender itself) for good."""
    code = request.get("code") or ""
    namespace.pop("RESULT", None)
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            exec(compile(code, "<jarvis>", "exec"), namespace)
        output = str(namespace.get("RESULT", "") or buffer.getvalue().strip())
        return {"id": request.get("id"), "ok": True, "output": output, "error": ""}
    except BaseException:
        return {"id": request.get("id"), "ok": False, "output": buffer.getvalue().strip(),
                "error": traceback.format_exc(limit=4)}


def _write_json_atomic(path: str, data: dict) -> None:
    """Both sides (Jarvis writing a request, Blender writing a response) poll the same filename every ~0.1s, and on
    Windows a rename can briefly collide with the other side's plain open() for reading ("being used by another
    process", or "access denied") — a transient sharing violation, not a real failure, so retries clear it. Up to
    ~2 s with jitter, so the two pollers don't stay in step (8 quick tries in 0.4 s once weren't enough)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    deadline = time.time() + 2.0
    while True:
        try:
            os.replace(tmp, path)   # atomic on Windows too (since Python 3.3)
            return
        except OSError:
            if time.time() >= deadline:
                raise
            time.sleep(0.02 + random.random() * 0.04)


def _read_request():
    for attempt in range(8):
        try:
            with open(REQUEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except ValueError:   # a read caught the file mid-write: try again rather than treat it as "no request"
            time.sleep(0.05)
        except OSError:
            return None
    return None


def _answer(request: dict) -> dict:
    if request.get("expires") and time.time() > request["expires"]:
        return {"id": request.get("id"), "ok": False, "output": "",
                "error": "Skipped: Jarvis had stopped waiting for this, so it was never run."}
    busy = busy_file()
    try:
        _write_json_atomic(busy, {"id": request.get("id"), "since": time.time(), "pid": os.getpid()})
    except OSError:
        pass   # only a hint for Jarvis's side; the request itself still runs
    try:
        return process_one(request, _namespace)
    finally:
        try:
            os.remove(busy)
        except OSError:
            pass


def poll():
    """One timer tick: process a new request if there is one. Returns the next delay (bpy.app.timers' contract).
    Never raises: Blender silently unregisters a timer whose callback raises, which would leave the bridge dead
    until Blender restarts (a Windows file lock on the response file is enough to cause that)."""
    global _last_id
    try:
        request = _read_request()
        # (id, sent at): ids start again at 1 whenever Jarvis restarts, so an id alone can repeat a request seen
        # before the restart, which would then be ignored.
        key = request and (request.get("id"), request.get("at"))
        if request and key != _last_id:
            _last_id = key
            response = _answer(request)
            try:
                _write_json_atomic(RESPONSE_FILE, response)
            except OSError:
                time.sleep(0.2)
                _write_json_atomic(RESPONSE_FILE, response)
    except Exception:
        traceback.print_exc()
    return POLL_SECONDS


def install() -> None:
    """Called once, at Blender startup — from `--python blender_bridge.py`, or from the copy Jarvis puts in Blender's
    startup scripts folder (see blender_control.install_startup_script): prepare the namespace and start polling."""
    global _last_id
    import sys
    import bpy
    # Both ways can run in the same Blender (startup copy + --python): two pollers would run every request twice.
    # The flag lives on `sys` because Blender resets bpy.app.driver_namespace when it loads the startup file.
    if getattr(sys, "jarvis_bridge_running", False) or bpy.app.driver_namespace.get("jarvis_bridge_running"):
        return
    sys.jarvis_bridge_running = True
    bpy.app.driver_namespace["jarvis_bridge_running"] = True
    os.makedirs(BRIDGE_DIR, exist_ok=True)
    for leftover in (RESPONSE_FILE, busy_file()):
        try:
            os.remove(leftover)   # a previous Blender's answer or busy note must never look like this one's
        except OSError:
            pass
    try:   # a request from an older Jarvis carries no expiry: one left lying for a while is just as stale
        if time.time() - os.path.getmtime(REQUEST_FILE) > 30:
            old = _read_request()
            _last_id = old and (old.get("id"), old.get("at"))
    except OSError:
        pass
    import bmesh
    import mathutils
    _namespace.update(bpy=bpy, bmesh=bmesh, mathutils=mathutils)
    if not bpy.app.timers.is_registered(poll):
        bpy.app.timers.register(poll, persistent=True)


def register() -> None:
    """Blender calls this for scripts in its startup folder, every time it opens — however it was opened."""
    try:
        install()
    except Exception:
        traceback.print_exc()


def unregister() -> None:
    pass


if __name__ == "__main__":
    install()
