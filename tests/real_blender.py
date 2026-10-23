"""A real Blender for tests and the Blender benchmark: headless (`-b`, no window, nothing on screen), running the
actual blender_bridge.py against a bridge folder of its own, with its home and temp folders in a scratch folder so a
save or a render never lands in the real Documents. Jarvis's side talks to it with the real BlenderBridge, exactly
as the app does; only the bridge folder differs, so the user's own Blender (if open) is never reached.

    with RealBlender(folder) as bridge:
        bridge.run("RESULT = bpy.app.version_string")
"""
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import blender_bridge   # noqa: E402
import blender_control  # noqa: E402


def find_blender():
    """The newest installed blender.exe (Windows) or Blender.app binary (macOS), or None."""
    patterns = [os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Blender Foundation", "Blender *",
                             "blender.exe"),
                "/Applications/Blender*.app/Contents/MacOS/Blender"]
    found = sorted(p for pattern in patterns for p in glob.glob(pattern))
    return os.environ.get("JARVIS_TEST_BLENDER") or (found[-1] if found else None)


# Runs inside Blender: the bridge exactly as install() sets it up, polled by a plain loop because a `-b` Blender
# exits when its --python script ends (timers never get a turn).
_LOOP = r'''
import os, sys, time
sys.path.insert(0, ROOT)
import blender_bridge as b
b.BRIDGE_DIR = DIR
b.REQUEST_FILE = os.path.join(DIR, "request.json")
b.RESPONSE_FILE = os.path.join(DIR, "response.json")
b.install()
open(os.path.join(DIR, "ready"), "w").close()
while not os.path.exists(os.path.join(DIR, "stop")):
    b.poll()
    time.sleep(0.02)
'''


class RealBlender:
    def __init__(self, folder, blender=None, startup_seconds=90):
        self.folder = str(folder)
        self.blender = blender or find_blender()
        self.startup_seconds = startup_seconds
        self.bridge_dir = os.path.join(self.folder, "bridge")
        self.home = os.path.join(self.folder, "home")
        self.process = None
        self._saved = None

    def __enter__(self):
        if not self.blender:
            raise RuntimeError("Blender isn't installed here")
        os.makedirs(self.bridge_dir, exist_ok=True)
        for leftover in ("ready", "stop"):   # from an earlier run in the same folder
            try:
                os.remove(os.path.join(self.bridge_dir, leftover))
            except OSError:
                pass
        os.makedirs(os.path.join(self.home, "Documents"), exist_ok=True)
        script = os.path.join(self.folder, "bridge_loop.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(f"ROOT = {ROOT!r}\nDIR = {self.bridge_dir!r}\n" + _LOOP)
        # APPDATA too: Blender's own config (and any startup scripts installed there) stays the user's
        env = dict(os.environ, USERPROFILE=self.home, HOME=self.home, APPDATA=self.home, TEMP=self.folder,
                   TMP=self.folder)
        self.log = open(os.path.join(self.folder, "blender.log"), "w", encoding="utf-8", errors="replace")
        self.process = subprocess.Popen([self.blender, "-b", "--factory-startup", "--python", script], env=env,
                                        stdout=self.log, stderr=subprocess.STDOUT)
        self._saved = (blender_bridge.BRIDGE_DIR, blender_bridge.REQUEST_FILE, blender_bridge.RESPONSE_FILE)
        blender_bridge.BRIDGE_DIR = self.bridge_dir
        blender_bridge.REQUEST_FILE = os.path.join(self.bridge_dir, "request.json")
        blender_bridge.RESPONSE_FILE = os.path.join(self.bridge_dir, "response.json")
        deadline = time.time() + self.startup_seconds
        while not os.path.exists(os.path.join(self.bridge_dir, "ready")):
            if self.process.poll() is not None or time.time() > deadline:
                self.__exit__(None, None, None)
                raise RuntimeError("the test Blender didn't start: see " + os.path.join(self.folder, "blender.log"))
            time.sleep(0.1)
        return blender_control.BlenderBridge()

    def __exit__(self, *exc):
        if self.process is not None:
            open(os.path.join(self.bridge_dir, "stop"), "w").close()
            try:
                self.process.wait(15)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            self.log.close()
        if self._saved:
            blender_bridge.BRIDGE_DIR, blender_bridge.REQUEST_FILE, blender_bridge.RESPONSE_FILE = self._saved
            self._saved = None
        return False
