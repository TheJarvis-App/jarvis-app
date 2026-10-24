"""The reusable side of Jarvis's character animation: templates that never depend on a scene.

  skeleton     the human bone layout (rest A-pose, metres, facing -Y) every character is built from
  characters   templates ("man", "woman") — height, build, clothing colours — scaled from that skeleton
  gaits        walking, slow, brisk and running: speed, cadence, stance share, swing height, arm swing, lean
  actions      timing and pose parameters for every action anim_core.py composes (door, sit, eat, wave...)
  props        what a held thing is (size, grip point, the point that goes to the mouth)
  environment  rain, wind, wet ground and lighting presets
  shots        camera templates (framing, lens, height, motion) the director picks from

Scene-specific choices (where the door is, which path, which take) live in the scene's own plan (stored on the
"Jarvis Animation" empty in the .blend), never here. Pure data and arithmetic: imported by the engine and loaded
into Blender as a module by blender_control.with_kit(), so it must not import bpy.
"""
import math

LIBRARY_VERSION = 1
FPS = 24
REST_HEIGHT = 1.78   # the skeleton below is drawn for this height

# (name, parent, head, tail, z axis of the bone (sets its roll), deform). Left side only; the right side mirrors it.
# Facing -Y, so the character's left is +X. Vertical bones have their Z axis forward, which makes a positive X
# rotation bend them forward, a positive Y rotation turn them left and a positive Z rotation lean them right.
_ARM_DOWN = math.radians(50)   # arms 50 degrees below horizontal: far enough from the body to skin cleanly
_ARM = (math.cos(_ARM_DOWN), 0.0, -math.sin(_ARM_DOWN))
_PALM = (-math.sin(_ARM_DOWN), 0.0, -math.cos(_ARM_DOWN))   # left palm faces the body


def _along(p, d, n, extra=(0.0, 0.0, 0.0)):
    return tuple(round(p[i] + d[i] * n + extra[i], 4) for i in range(3))


_SHOULDER_J = (0.17, 0.02, 1.42)
_ELBOW = _along(_SHOULDER_J, _ARM, 0.29, (0.0, 0.03, 0.0))
_WRIST = _along(_ELBOW, _ARM, 0.255, (0.0, -0.03, 0.0))
_KNUCKLE = _along(_WRIST, _ARM, 0.095)
_FINGER_MID = _along(_KNUCKLE, _ARM, 0.05)
_FINGER_TIP = _along(_FINGER_MID, _ARM, 0.045)
_THUMB_DIR = (0.35, -0.62, -0.70)
_THUMB_0 = _along(_WRIST, _ARM, 0.025, (0.0, -0.02, 0.0))
_THUMB_1 = _along(_THUMB_0, _THUMB_DIR, 0.04)
_THUMB_2 = _along(_THUMB_1, _THUMB_DIR, 0.032)

FWD = (0.0, -1.0, 0.0)
UP = (0.0, 0.0, 1.0)
SKELETON = [
    ("root", None, (0.0, 0.0, 0.0), (0.0, 0.3, 0.0), UP, False),
    ("hips", "root", (0.0, 0.0, 0.97), (0.0, 0.0, 1.08), FWD, True),
    ("spine", "hips", (0.0, 0.0, 1.08), (0.0, 0.0, 1.24), FWD, True),
    ("chest", "spine", (0.0, 0.0, 1.24), (0.0, 0.0, 1.44), FWD, True),
    ("neck", "chest", (0.0, 0.0, 1.44), (0.0, -0.01, 1.56), FWD, True),
    ("head", "neck", (0.0, -0.01, 1.56), (0.0, -0.01, 1.76), FWD, True),
    ("shoulder.L", "chest", (0.025, 0.0, 1.40), _SHOULDER_J, UP, True),
    ("upper_arm.L", "shoulder.L", _SHOULDER_J, _ELBOW, FWD, True),
    ("forearm.L", "upper_arm.L", _ELBOW, _WRIST, FWD, True),
    ("hand.L", "forearm.L", _WRIST, _KNUCKLE, _PALM, True),
    ("fingers1.L", "hand.L", _KNUCKLE, _FINGER_MID, _PALM, True),
    ("fingers2.L", "fingers1.L", _FINGER_MID, _FINGER_TIP, _PALM, True),
    ("thumb1.L", "hand.L", _THUMB_0, _THUMB_1, (-0.8, 0.0, -0.6), True),
    ("thumb2.L", "thumb1.L", _THUMB_1, _THUMB_2, (-0.8, 0.0, -0.6), True),
    ("thigh.L", "hips", (0.09, 0.0, 0.93), (0.095, -0.015, 0.50), FWD, True),
    ("shin.L", "thigh.L", (0.095, -0.015, 0.50), (0.10, 0.02, 0.08), FWD, True),
    ("foot.L", "shin.L", (0.10, 0.02, 0.08), (0.10, -0.115, 0.025), UP, True),
    ("toe.L", "foot.L", (0.10, -0.115, 0.025), (0.10, -0.19, 0.025), UP, True),
    # controls: IK targets with the same rest as the bone they drive, and pole targets for knees and elbows
    ("foot_ik.L", "root", (0.10, 0.02, 0.08), (0.10, -0.115, 0.025), UP, False),
    ("hand_ik.L", "root", _WRIST, _KNUCKLE, _PALM, False),
    ("knee_pole.L", "root", (0.095, -0.55, 0.50), (0.095, -0.65, 0.50), UP, False),
    ("elbow_pole.L", "root", (0.40, 0.45, 1.15), (0.40, 0.55, 1.15), UP, False),
]
CONTROLS = ("root", "hips", "foot_ik.L", "foot_ik.R", "hand_ik.L", "hand_ik.R", "knee_pole.L", "knee_pole.R",
            "elbow_pole.L", "elbow_pole.R")
FK_BONES = ("spine", "chest", "neck", "head", "shoulder.L", "shoulder.R", "toe.L", "toe.R", "fingers1.L",
            "fingers2.L", "fingers1.R", "fingers2.R", "thumb1.L", "thumb2.L", "thumb1.R", "thumb2.R", "hand.L",
            "hand.R")
# Where a foot meets the ground, in the foot's own frame (forward, up) from the ankle: the sole is ANKLE below it.
ANKLE = 0.08
HEEL = -0.06
BALL = 0.135
TOE = 0.21
FOOT_HALF_WIDTH = 0.045
# Joints a body may not bend past (degrees): checked on the evaluated rig by blender_character.inspect_motion.
JOINT_LIMITS = {"knee": (-3.0, 150.0), "elbow": (-3.0, 155.0), "spine": 45.0, "neck": 60.0}
# Body volumes for collision checks: (from bone, radius), sampled along the bone.
BODY_CAPSULES = {"spine": 0.14, "chest": 0.15, "head": 0.1, "neck": 0.06, "thigh": 0.075, "shin": 0.055,
                 "upper_arm": 0.05, "forearm": 0.042}


def mirror(name):
    return name[:-2] + (".R" if name.endswith(".L") else ".L") if name[-2:] in (".L", ".R") else name


def skeleton(height=REST_HEIGHT, width=1.0, hips=1.0):
    """The skeleton for a character `height` metres tall, both sides: {name: {parent, head, tail, z, deform}}.
    `width` scales the shoulders and `hips` the pelvis, around the body's centre line."""
    k = height / REST_HEIGHT
    out = {}

    def scaled(p, name):
        x = p[0] * (width if any(s in name for s in ("shoulder", "arm", "hand", "finger", "thumb", "elbow")) else
                    hips if any(s in name for s in ("thigh", "shin", "foot", "toe", "knee")) else 1.0)
        return (round(x * k, 4), round(p[1] * k, 4), round(p[2] * k, 4))

    for name, parent, head, tail, z, deform in SKELETON:
        sides = [(name, parent, head, tail, z)]
        if name.endswith(".L"):
            flip = (lambda v: (-v[0], v[1], v[2]))
            sides.append((mirror(name), mirror(parent) if parent else None, flip(head), flip(tail), flip(z)))
        for n, par, h, t, zz in sides:
            out[n] = {"parent": par, "head": scaled(h, n), "tail": scaled(t, n), "z": zz, "deform": deform}
    return out


# ---------- characters ----------
CHARACTERS = {
    "man": {"height": 1.78, "width": 1.0, "hips": 1.0, "build": 1.0, "hair": "short",
            "colors": {"jacket": (0.035, 0.05, 0.09), "trousers": (0.06, 0.06, 0.065), "shoes": (0.015, 0.012, 0.01),
                       "skin": (0.72, 0.5, 0.38), "hair": (0.06, 0.04, 0.03)}},
    "woman": {"height": 1.66, "width": 0.9, "hips": 1.06, "build": 0.86, "hair": "long",
              "colors": {"jacket": (0.42, 0.05, 0.06), "trousers": (0.05, 0.05, 0.07), "shoes": (0.03, 0.02, 0.02),
                         "skin": (0.8, 0.6, 0.48), "hair": (0.2, 0.1, 0.05)}},
}
CHARACTER_WORDS = {"man": "man", "guy": "man", "gentleman": "man", "boy": "man", "person": "man", "character": "man",
                   "someone": "man", "somebody": "man", "figure": "man", "human": "man", "he": "man", "him": "man",
                   "fellow": "man", "dude": "man", "woman": "woman", "lady": "woman", "girl": "woman", "she": "woman",
                   "her": "woman"}

# ---------- gaits ----------
# speed m/s, cadence = a + b * speed (steps/s), duty = share of a stride a foot is on the ground, swing clearance of
# the ankle (m), heel lift at toe-off (deg: real feet leave the ground steep, ~55-65 deg), pelvis bob (m) and sway (m), forward lean (deg), arm swing (m), elbow bend
# (hand height raised at the front of a swing), accel (m/s^2).
GAITS = {
    "slow": {"speed": 0.85, "cadence": (0.95, 0.75), "duty": 0.64, "clear": 0.05, "heel": 45, "bob": 0.014,
             "sway": 0.022, "lean": 3, "arm": 0.11, "elbow": 0.02, "accel": 1.1, "twist": 3},
    "walk": {"speed": 1.3, "cadence": (0.95, 0.72), "duty": 0.61, "clear": 0.06, "heel": 56, "bob": 0.02,
             "sway": 0.024, "lean": 4, "arm": 0.17, "elbow": 0.04, "accel": 1.3, "twist": 4},
    "brisk": {"speed": 1.65, "cadence": (1.0, 0.68), "duty": 0.59, "clear": 0.07, "heel": 60, "bob": 0.024,
              "sway": 0.02, "lean": 6, "arm": 0.21, "elbow": 0.06, "accel": 1.6, "twist": 5},
    "run": {"speed": 3.2, "cadence": (1.6, 0.42), "duty": 0.36, "clear": 0.16, "heel": 64, "bob": 0.045,
            "sway": 0.015, "lean": 11, "arm": 0.22, "elbow": 0.2, "accel": 3.0, "twist": 7},
}
STEP_WIDTH = 0.095     # each ankle's distance from the walking line
TOE_OUT = 6.0          # degrees each foot turns out
TURN_STEP = 55.0       # largest turn of one step when turning on the spot (degrees)

# ---------- actions: timing (seconds) and pose amounts ----------
ACTIONS = {
    "reach": {"time": 0.6, "grip": 0.15},
    "door": {"reach": 0.65, "unlatch": 0.3, "push": 1.2, "release_at": 42.0, "open": 86.0, "swing": 0.9,
             "close_release": 24.0, "close": 1.3, "shut": 0.45, "approach": 0.42, "handle_height": 1.0,
             "handle_in": 0.075, "inside": 1.55, "clearance": 0.26},
    "turn": {"step": 0.42},
    "sit": {"down": 1.3, "up": 1.2, "lean": 28.0, "seat_depth": 0.12},
    "stand": {"up": 1.2},
    "eat": {"reach": 0.7, "lift": 0.75, "bite": 0.55, "chew": 1.1, "lower": 0.7, "bites": 3, "put": 0.7},
    "drink": {"reach": 0.7, "lift": 0.8, "sip": 1.3, "lower": 0.7, "tilt": 55.0, "head_back": 12.0},
    "wave": {"raise": 0.5, "wave": 0.32, "waves": 3, "lower": 0.55},
    "point": {"raise": 0.55, "hold": 1.2, "lower": 0.5},
    "talk": {"gesture": 0.9},
    "phone": {"take": 0.7, "raise": 0.6, "lower": 0.6, "put": 0.6},
    "jump": {"crouch": 0.35, "push": 0.18, "land": 0.3, "recover": 0.45, "height": 0.35, "dip": 0.16},
    "dance": {"beat": 0.5},
    "pick_up": {"crouch": 0.9, "grab": 0.25, "rise": 0.9},
    "put_down": {"crouch": 0.9, "release": 0.25, "rise": 0.8},
    "handshake": {"reach": 0.6, "shake": 0.25, "shakes": 3, "release": 0.5},
    "idle": {"breath": 0.24},
}

# ---------- props ----------
# size (x, y, z) metres; grip: where the hand holds it (from its centre); mouth: the point that goes to the mouth.
PROPS = {
    "sandwich": {"size": (0.13, 0.09, 0.05), "grip": (0.0, 0.0, 0.0), "mouth": (0.0, -0.05, 0.0), "hands": 1,
                 "color": (0.82, 0.62, 0.35)},
    "cup": {"size": (0.08, 0.08, 0.1), "grip": (0.0, 0.0, 0.0), "mouth": (0.0, -0.03, 0.05), "hands": 1,
            "color": (0.92, 0.92, 0.9)},
    "glass": {"size": (0.07, 0.07, 0.12), "grip": (0.0, 0.0, 0.0), "mouth": (0.0, -0.03, 0.06), "hands": 1,
              "color": (0.8, 0.9, 1.0)},
    "apple": {"size": (0.08, 0.08, 0.08), "grip": (0.0, 0.0, 0.0), "mouth": (0.0, -0.04, 0.0), "hands": 1,
              "color": (0.7, 0.08, 0.06)},
    "phone": {"size": (0.075, 0.01, 0.15), "grip": (0.0, 0.0, 0.0), "mouth": (0.0, 0.0, 0.0), "hands": 1,
              "color": (0.03, 0.03, 0.035)},
    "box": {"size": (0.4, 0.3, 0.3), "grip": (0.0, 0.0, 0.0), "mouth": None, "hands": 2, "color": (0.55, 0.4, 0.25)},
    "bag": {"size": (0.32, 0.12, 0.3), "grip": (0.0, 0.0, 0.15), "mouth": None, "hands": 1,
            "color": (0.2, 0.12, 0.07)},
    "umbrella": {"size": (0.05, 0.05, 0.85), "grip": (0.0, 0.0, -0.3), "mouth": None, "hands": 1,
                 "color": (0.05, 0.05, 0.06)},
}
PROP_WORDS = {"sandwich": "sandwich", "burger": "sandwich", "toast": "sandwich", "food": "sandwich",
              "meal": "sandwich", "lunch": "sandwich", "breakfast": "sandwich", "dinner": "sandwich",
              "cup": "cup", "coffee": "cup", "tea": "cup", "mug": "cup", "glass": "glass", "water": "glass",
              "juice": "glass", "drink": "glass", "apple": "apple", "fruit": "apple", "phone": "phone",
              "box": "box", "package": "box", "parcel": "box", "bag": "bag", "suitcase": "bag", "umbrella": "umbrella"}
SEAT_HEIGHT = 0.46
TABLE_HEIGHT = 0.74

# ---------- environment ----------
RAIN = {"light": {"drops": 9000, "speed": 7.5, "length": 0.22, "radius": 0.0035, "splashes": 900},
        "rain": {"drops": 18000, "speed": 8.5, "length": 0.32, "radius": 0.004, "splashes": 1800},
        "heavy": {"drops": 32000, "speed": 9.5, "length": 0.42, "radius": 0.0045, "splashes": 3200}}
RAIN_HEIGHT = 9.0
WIND = {"none": 0.0, "breeze": 0.12, "wind": 0.25, "strong": 0.42}   # horizontal drift per metre fallen
WET = {"paving": {"darken": 0.55, "roughness": 0.12}, "ground": {"darken": 0.7, "roughness": 0.45},
       "deck": {"darken": 0.6, "roughness": 0.15}, "steps": {"darken": 0.55, "roughness": 0.12},
       "roof": {"darken": 0.8, "roughness": 0.25}, "walkway": {"darken": 0.55, "roughness": 0.12},
       "coping": {"darken": 0.65, "roughness": 0.15}}
LIGHTING = {
    "rain": {"sky": (0.03, 0.04, 0.055), "sky_strength": 1.0, "sun": 0.35, "sun_color": (0.6, 0.7, 0.9),
             "sun_elevation": 35, "porch": 120.0, "interior": 180.0, "warm": (1.0, 0.72, 0.45), "exposure": 0.6,
             "fog": 0.012},
    "night": {"sky": (0.008, 0.01, 0.02), "sky_strength": 1.0, "sun": 0.08, "sun_color": (0.5, 0.6, 0.9),
              "sun_elevation": 40, "porch": 150.0, "interior": 220.0, "warm": (1.0, 0.7, 0.42), "exposure": 1.0,
              "fog": 0.008},
    "day": {"sky": (0.55, 0.7, 0.92), "sky_strength": 0.45, "sun": 4.0, "sun_color": (1.0, 0.97, 0.92),
            "sun_elevation": 45, "porch": 0.0, "interior": 60.0, "warm": (1.0, 0.85, 0.7), "exposure": 0.0,
            "fog": 0.0},
    "sunset": {"sky": (0.6, 0.42, 0.32), "sky_strength": 0.35, "sun": 3.0, "sun_color": (1.0, 0.7, 0.45),
               "sun_elevation": 12, "porch": 60.0, "interior": 120.0, "warm": (1.0, 0.75, 0.5), "exposure": 0.2,
               "fog": 0.004},
}

# ---------- camera shots ----------
# distance in body heights, azimuth (degrees from the subject's facing, 0 = in front), height (m above the
# subject's feet), lens (mm), move: how the camera travels during the shot.
SHOTS = {
    "establishing": {"distance": 7.0, "azimuth": 35.0, "height": 2.6, "lens": 26.0, "move": "crane_in",
                     "aim": "chest", "lag": 0.6},
    "tracking": {"distance": 2.6, "azimuth": 70.0, "height": 1.45, "lens": 38.0, "move": "track", "aim": "chest",
                 "lag": 0.35},
    "follow": {"distance": 2.4, "azimuth": 165.0, "height": 1.7, "lens": 32.0, "move": "follow", "aim": "chest",
               "lag": 0.45},
    "door": {"distance": 2.1, "azimuth": 140.0, "height": 1.55, "lens": 32.0, "move": "push_in", "aim": "hand",
             "lag": 0.3},
    "interior": {"distance": 2.8, "azimuth": 20.0, "height": 1.6, "lens": 24.0, "move": "hold", "aim": "chest",
                 "lag": 0.4},
    "medium": {"distance": 2.2, "azimuth": 25.0, "height": 1.5, "lens": 40.0, "move": "drift", "aim": "chest",
               "lag": 0.4},
    "closeup": {"distance": 1.1, "azimuth": 20.0, "height": 1.6, "lens": 50.0, "move": "drift", "aim": "head",
                "lag": 0.3},
    "orbit": {"distance": 3.2, "azimuth": 0.0, "height": 1.6, "lens": 32.0, "move": "orbit", "aim": "chest",
              "lag": 0.4},
}
RENDER = {"preview": {"width": 640, "height": 360, "samples": 12, "motion_blur": False},
          "final": {"width": 1280, "height": 720, "samples": 48, "motion_blur": True},
          "high": {"width": 1920, "height": 1080, "samples": 64, "motion_blur": True}}


def gait(kind):
    return GAITS.get(kind) or GAITS["walk"]


def cadence(g, speed):
    a, b = g["cadence"]
    return a + b * max(0.0, speed)
