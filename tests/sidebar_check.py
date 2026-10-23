"""The window's sidebar controls and Take Control, end to end and isolated: the real engine (its own data, TEMP,
APPDATA and home folders, audio off, no AI reachable), a headless Blender answering on that engine's own bridge
folder, and the real window code (index.html, renderer.js, panels.js) in an Electron harness that clicks, types and
takes screenshots (tests/sidebar_check.js). Nothing reaches the user's Blender, data, microphone or GPU, and no
overlay or window change touches their desktop (the harness leaves main.js out).

    python tests/sidebar_check.py <output folder>      (results.json + screenshots there; about 2 minutes)
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tests"))
from real_blender import _LOOP, find_blender   # noqa: E402


def main(out):
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if os.path.isfile(os.path.join(out, f)):
            os.remove(os.path.join(out, f))
    t = tempfile.mkdtemp(prefix="jarvis-ui-")
    for sub in ("data", "appdata", os.path.join("home", "Documents")):
        os.makedirs(os.path.join(t, sub), exist_ok=True)
    bridge_dir = os.path.join(t, "jarvis_blender_bridge")   # the engine's bridge folder, with TEMP pointed at t
    os.makedirs(bridge_dir, exist_ok=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    token = secrets.token_hex(16)
    isolated = dict(os.environ, TEMP=t, TMP=t, APPDATA=os.path.join(t, "appdata"), HOME=os.path.join(t, "home"),
                    USERPROFILE=os.path.join(t, "home"))

    loop = os.path.join(t, "bridge_loop.py")
    with open(loop, "w", encoding="utf-8") as f:
        f.write(f"ROOT = {REPO!r}\nDIR = {bridge_dir!r}\n" + _LOOP)
    blender_log = open(os.path.join(out, "blender.log"), "w", encoding="utf-8", errors="replace")
    blender = subprocess.Popen([find_blender(), "-b", "--factory-startup", "--python", loop], env=isolated,
                               stdout=blender_log, stderr=subprocess.STDOUT)
    engine_env = dict(isolated, JARVIS_WS_PORT=str(port), JARVIS_WS_TOKEN=token, JARVIS_DATA_DIR=os.path.join(t, "data"),
                      JARVIS_AUDIO="off", GROQ_API_KEY="", OLLAMA_URL="http://127.0.0.1:9", JARVIS_NO_AI_SETUP="1",
                      JARVIS_COMPUTER_CONTROL="ask", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    engine_log = open(os.path.join(out, "engine.log"), "w", encoding="utf-8", errors="replace")
    engine = subprocess.Popen([sys.executable, os.path.join(REPO, "app.py")], cwd=REPO, env=engine_env,
                              stdout=engine_log, stderr=subprocess.STDOUT)
    deadline = time.time() + 90
    while not os.path.exists(os.path.join(bridge_dir, "ready")) and time.time() < deadline:
        time.sleep(0.2)

    electron = os.path.join(REPO, "node_modules", "electron", "dist",
                            "electron.exe" if sys.platform == "win32" else "electron")
    # The window gets its own data folder through --user-data-dir: Electron on Windows ignores the APPDATA variable
    # (and exits when USERPROFILE moves); the engine has full isolation.
    ui_env = dict(os.environ, APPDATA=os.path.join(t, "appdata"), REPO=REPO, OUT=out,
                  WS_URL=f"ws://127.0.0.1:{port}/?token={token}")
    ui = subprocess.Popen([electron, os.path.join(REPO, "tests", "sidebar_check.js"),
                           f"--user-data-dir={os.path.join(t, 'window')}"], env=ui_env)
    try:
        while ui.poll() is None:
            if os.path.exists(os.path.join(out, "kill-engine")) and engine.poll() is None:
                engine.kill()   # the harness checks how the window shows an engine that went away
            time.sleep(0.2)
    finally:
        if engine.poll() is None:
            engine.kill()
        open(os.path.join(bridge_dir, "stop"), "w").close()
        try:
            blender.wait(15)
        except subprocess.TimeoutExpired:
            blender.kill()
    with open(os.path.join(out, "results.json"), encoding="utf-8") as f:
        results = json.load(f)
    for c in results["checks"]:
        print("PASS" if c["ok"] else "FAIL", c["name"])
    if results.get("error"):
        print("ERROR", results["error"])
    print(f"{sum(c['ok'] for c in results['checks'])}/{len(results['checks'])} passed; screenshots in {out}")
    return all(c["ok"] for c in results["checks"]) and not results.get("error")


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1]) else 1)
