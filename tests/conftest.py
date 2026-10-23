import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Tests never write into the project folder or the real user data folder.
os.environ.setdefault("JARVIS_DATA_DIR", tempfile.mkdtemp(prefix="jarvis-tests-"))
os.environ.setdefault("JARVIS_AUDIO", "off")

# ... and never reach a Blender the user has open: its bridge folder is %TEMP%\jarvis_blender_bridge.
import blender_bridge  # noqa: E402

blender_bridge.BRIDGE_DIR = tempfile.mkdtemp(prefix="jarvis-tests-bridge-")
blender_bridge.REQUEST_FILE = os.path.join(blender_bridge.BRIDGE_DIR, "request.json")
blender_bridge.RESPONSE_FILE = os.path.join(blender_bridge.BRIDGE_DIR, "response.json")
