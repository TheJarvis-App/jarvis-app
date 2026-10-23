"""Deterministic handling for the common, everyday Blender commands ("create a cube", "make it two times bigger",
"color it red", "rotate it 45 degrees", "delete the cube", "undo", "save") — tried before ever asking the AI.

Why this exists: BlenderComputerTask (see computer_use.py) asks a model to write bpy code from scratch for every
request, including a small local one when there's no Groq key. For the things people actually say most of the time,
that is slow and unreliable — a small model can wander, claim success without checking, or invent an interpretation
of something vague. Here, each recognized command runs one specific, known-correct bpy snippet, re-queries Blender
afterward to confirm it actually happened, and only then reports success — no model call involved at all, so it
takes well under a second. Anything not recognized here still falls through to BlenderComputerTask.

Several commands can be chained ("select the cube and make it red", "create a sphere then move it left"): each part
must be recognized here, or the whole request goes to the AI instead.

Object references ("it", "the second one", "the cube") resolve against `session.blender_objects`
(computer_use.ControlSession) first, then against Blender's real scene (its default "Cube", or whatever the user
selected by hand). "it" means the object the last command worked on.
"""
import json
import re

import difflib

import blender_build
import blender_control
import blender_edit

_SHAPES = {
    "cube": "cube", "box": "cube",
    "sphere": "uv_sphere", "ball": "uv_sphere",
    "cylinder": "cylinder",
    "cone": "cone",
    "plane": "plane",
    "torus": "torus", "donut": "torus", "doughnut": "torus",
    "monkey": "monkey", "suzanne": "monkey",
}
# Each primitive operator takes its own size argument; passing `size` to the sphere/cylinder/cone/torus ones fails.
_SHAPE_ARGS = {"cube": "size=2", "plane": "size=2", "monkey": "size=2", "uv_sphere": "radius=1",
               "cylinder": "radius=1, depth=2", "cone": "radius1=1, depth=2", "torus": "major_radius=1, minor_radius=0.25"}
_SHAPE_WORDS = r"(?:cube|box|sphere|ball|cylinder|cone|plane|torus|donut|doughnut|monkey|suzanne)"
_COLORS = {"red": (0.8, 0.02, 0.02), "green": (0.05, 0.6, 0.05), "blue": (0.02, 0.1, 0.8),
           "yellow": (0.9, 0.8, 0.02), "orange": (0.9, 0.3, 0.02), "purple": (0.4, 0.05, 0.7),
           "pink": (0.9, 0.3, 0.5), "white": (0.9, 0.9, 0.9), "black": (0.01, 0.01, 0.01),
           "gray": (0.3, 0.3, 0.3), "grey": (0.3, 0.3, 0.3), "brown": (0.25, 0.1, 0.03),
           "gold": (0.9, 0.6, 0.1), "silver": (0.7, 0.7, 0.75), "cyan": (0.02, 0.7, 0.8),
           "navy": (0.01, 0.02, 0.2), "teal": (0.0, 0.35, 0.35), "turquoise": (0.05, 0.6, 0.55),
           "beige": (0.75, 0.65, 0.45), "cream": (0.9, 0.85, 0.7), "tan": (0.6, 0.45, 0.3),
           "maroon": (0.3, 0.01, 0.02), "lime": (0.3, 0.8, 0.02), "magenta": (0.8, 0.02, 0.6),
           "olive": (0.3, 0.3, 0.05), "lavender": (0.6, 0.5, 0.85), "violet": (0.45, 0.1, 0.8),
           "indigo": (0.12, 0.04, 0.4), "charcoal": (0.06, 0.06, 0.07), "sky blue": (0.3, 0.6, 0.9)}
for _hue in ("red", "green", "blue", "yellow", "orange", "purple", "pink", "gray", "grey", "brown"):
    _COLORS["light " + _hue] = tuple(round(c + (1 - c) * 0.5, 3) for c in _COLORS[_hue])
    _COLORS["dark " + _hue] = tuple(round(c * 0.3, 3) for c in _COLORS[_hue])
_PLEASE = r"^(?:please |can you |could you |would you |now )*"
_NUMBER = r"(?:\d+(?:\.\d+)?|two|three|four|five|ten)"
_TIMES_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "half": 2}

_CREATE = re.compile(
    _PLEASE + r"(?:create|add|make|build|insert)\s+(?:me\s+)?(?:a |an |another |a second |a third |one more |a new )?"
    rf"(?P<shape>{_SHAPE_WORDS})\b(?:\s+(?:in blender|please|for me))?\.?$", re.I)
_RESIZE_WORD = r"(?:taller|shorter|higher|lower|wider|narrower|bigger|larger|smaller|thinner|fatter)"
_RESIZE = re.compile(_PLEASE + rf"make\s+(?P<ref>.+?)\s+(?:(?P<times>{_NUMBER})\s*(?:times|x)\s+)?"
                     rf"(?P<direction>{_RESIZE_WORD})(?:\s+than (?:before|now|it is))?\.?$", re.I)
_TWICE = re.compile(_PLEASE + r"make\s+(?P<ref>.+?)\s+(?:twice|double)(?:\s+as\s+(?:big|large))?"
                    r"(?:\s+(?:the|its) size)?\.?$", re.I)
_HALF = re.compile(_PLEASE + r"make\s+(?P<ref>.+?)\s+half\s+(?:the|its|as)\s+(?:size|big|large)\.?$", re.I)
_DOUBLE = re.compile(_PLEASE + r"double\s+(?:the size of\s+)?(?P<ref>.+?)(?:'s size)?\.?$", re.I)
_SCALE = re.compile(_PLEASE + r"(?:scale|resize)\s+(?P<ref>.+?)\s+(?P<way>up|down)?\s*(?:by|to)?\s*(?:a factor of\s+)?"
                    rf"(?P<times>{_NUMBER}|half)\s*(?:times|x)?\.?$", re.I)
_COLOR = re.compile(
    _PLEASE + r"(?:make|colou?r|paint|turn|change(?: the colou?r of)?|set the colou?r of)\s+(?P<ref>.+?)\s+"
    r"(?:to\s+|into\s+)?(?:the colou?r\s+)?(?P<color>" + "|".join(_COLORS) + r")(?:\s+colou?r)?\.?$", re.I)
_ROTATE = re.compile(
    _PLEASE + r"(?:rotate|spin)\s+(?P<ref>.+?)(?:\s+(?:by\s+)?(?P<deg>-?\d+(?:\.\d+)?)\s*(?:degrees?|°))?"
    r"(?:\s+(?:around|on|about|along)\s+(?:the\s+)?(?P<axis>[xyz])(?:[ -]?axis)?)?\.?$", re.I)
_DELETE = re.compile(_PLEASE + r"(?:delete|remove|get rid of)\s+(?P<ref>.+?)\.?$", re.I)
_DUPLICATE = re.compile(_PLEASE + r"(?:duplicate|copy|clone)\s+(?P<ref>.+?)\.?$", re.I)
_SELECT = re.compile(_PLEASE + r"select\s+(?P<ref>.+?)\.?$", re.I)
_DIRECTION_WORD = r"(?:left|right|up|down|forward|forwards|back|backward|backwards)"
_MOVE_NEXT_TO = re.compile(
    _PLEASE + r"(?:move|put|place)\s+(?P<ref>.+?)\s+next to\s+(?P<target>.+?)\.?$", re.I)
_MOVE_DIR = re.compile(_PLEASE + rf"move\s+(?P<ref>.+?)\s+(?P<direction>{_DIRECTION_WORD})\.?$", re.I)
_FOCUS = re.compile(r"^(?:please )?(?:go (?:back )?to|switch (?:back )?to|bring (?:back )?|focus (?:back )?(?:on )?)"
                    r"\s*blender\.?$", re.I)
_UNDO = re.compile(r"^(?:please )?undo(?:\s+(?:that|it|the last (?:change|action|step)))?\.?$", re.I)
_REDO = re.compile(r"^(?:please )?redo(?:\s+(?:that|it))?\.?$", re.I)
_AGAIN = re.compile(r"^(?:do (?:that|it) again|again|repeat that|repeat it|one more time)\.?$", re.I)
_SAVE = re.compile(r"^(?:please )?save(?:\s+(?:the\s+)?(?:project|file|scene|blend(?:er)? file|it))?"
                   r"(?:\s+as\s+(?P<name>[\w .'-]+?))?\.?$", re.I)
# What a reference to a scene object looks like, so "delete the timer" / "copy that link" while Blender happens to
# be open aren't taken as Blender commands.
_OBJECT_REF = re.compile(rf"\b(?:it|that|this|them|one|object|selected|selection|everything|all|{_SHAPE_WORDS}|"
                         r"camera|light|lamp|mesh|first|second|third|last)\b", re.I)

# Speech recognition's usual mishearings ("make the cube be girl" = "bigger", "two times the big hill").
_MISHEARD = [(re.compile(r"\bbe (?:girl|gear|ger|gur|ghur)\b", re.I), "bigger"),
             (re.compile(r"\bsmall (?:her|ur)\b", re.I), "smaller"),
             (re.compile(rf"\b({_NUMBER})\s+times\s+(?:the|as|its)\s+(?:big|large|size)\w*\b.*$", re.I), r"\1 times bigger"),
             (re.compile(rf"\bsize\s+(?=(?:{_NUMBER})\s*(?:times|x)\b)", re.I), ""),
             (re.compile(r"\bthe cube's\b", re.I), "the cube")]
_FILLER = re.compile(r"^(?:(?:okay|ok|so|now|and|alright|all right|well|hey|jarvis|jervis|blender|please|"
                     r"in blender)\b[,.!]?\s*)+", re.I)
# A bare comma separates steps too ("create a sphere, make it red and move it up"); a part that isn't a command on
# its own ("move it to 1, 2, 3") makes the whole sentence be tried as one instead (see _match_steps).
_CLAUSE_SPLIT = re.compile(r"\s*,\s*(?:(?:and then|and also|and|then|after that)\b\s*,?\s*)?|"
                           r"\s*\b(?:and then|and also|and|then|after that)\b\s*,?\s*", re.I)

_ORDINAL = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
            "fifth": 4, "5th": 4, "last": -1, "latest": -1, "newest": -1}
_GROW = {"taller": True, "higher": True, "shorter": False, "lower": False, "wider": True, "narrower": False,
         "bigger": True, "larger": True, "smaller": False, "fatter": True, "thinner": False}
_RESIZE_AXES = {"taller": (0, 0, 1), "higher": (0, 0, 1), "shorter": (0, 0, 1), "lower": (0, 0, 1),
                "wider": (1, 0, 0), "narrower": (1, 0, 0), "fatter": (1, 1, 0), "thinner": (1, 1, 0),
                "bigger": (1, 1, 1), "larger": (1, 1, 1), "smaller": (1, 1, 1)}
_DIRECTION_VECTOR = {"left": (-1, 0, 0), "right": (1, 0, 0), "up": (0, 0, 1), "down": (0, 0, -1),
                     "forward": (0, 1, 0), "forwards": (0, 1, 0), "back": (0, -1, 0), "backward": (0, -1, 0),
                     "backwards": (0, -1, 0)}
MOVE_STEP = 2.0
RESIZE_FACTOR = 1.4

_GENERIC_REF = ("it", "", "object", "one", "thing", "selected", "selection", "selected object", "selected one",
                "active object", "that", "this")
_SCENE = ("scene = getattr(bpy.context, 'scene', None) or bpy.data.scenes[0]\n"
          "layer = scene.view_layers[0]\n")
RENDER_SECONDS = 900   # EEVEE's first render compiles its shaders (about a minute here); Cycles can take far longer
DARK_RENDER, BRIGHT_RENDER = 0.03, 0.95   # a render's average brightness (0..1) outside these is worth mentioning

# ---------- the commands built on blender_scene.py ----------
_WORD_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "twenty": 20, "half a": 0.5, "a half": 0.5}
_AMOUNT = r"(?:\d+(?:\.\d+)?|half a|a half|one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty|an?)"
_COUNT = r"(?:\d+|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty)"
_UNIT_METRES = {"m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0, "unit": 1.0, "units": 1.0,
                "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01, "centimetre": 0.01, "centimetres": 0.01,
                "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001, "millimetre": 0.001, "millimetres": 0.001,
                "ft": 0.3048, "foot": 0.3048, "feet": 0.3048, "in": 0.0254, "inch": 0.0254, "inches": 0.0254}
_UNIT = r"(?:" + "|".join(sorted(_UNIT_METRES, key=len, reverse=True)) + r")\b"
_DIR = r"(?:to the )?(?P<dir{n}>left|right|up|upwards|down|downwards|forward|forwards|back|backward|backwards)"
_DIRECTIONS = {**_DIRECTION_VECTOR, "upwards": (0, 0, 1), "downwards": (0, 0, -1)}

_SCENE_WORD = r"(?:the |my |this )?(?:blender )?scene"
_DESCRIBE = re.compile(
    r"^(?:what(?:'s| is| do (?:i|we) have| have (?:i|we) got)\s+(?:in|on)\s+(?:the |my |this )?(?:scene|blender)"
    rf"(?: scene)?|describe\s+{_SCENE_WORD}|what do you see\s+in (?:the )?(?:scene|blender)|"
    r"(?:list|show me|name)\s+(?:all\s+)?(?:of\s+)?(?:the\s+)?objects(?:\s+in (?:the )?scene)?|"
    r"(?:what|how many) objects (?:are there|are in the scene|do (?:i|we) have)(?: in (?:the )?scene)?)\s*[?.!]*$",
    re.I)
_CHECK = re.compile(
    rf"^(?:(?:check|inspect|review|audit)\s+{_SCENE_WORD}(?:\s+for (?:problems|issues|mistakes|errors))?|"
    rf"(?:is there |is )?anything wrong (?:with|in) {_SCENE_WORD}|what'?s wrong with {_SCENE_WORD}|"
    rf"(?:are there|do you see) (?:any )?(?:problems|issues|mistakes) (?:in|with) {_SCENE_WORD})\s*[?.!]*$", re.I)
_ADD_LIGHT = re.compile(
    _PLEASE + r"(?:add|create|insert|put in|make)\s+(?:a\s+|an\s+|another\s+|some\s+|one more\s+)?"
    r"(?:(?P<kind>sun|sunlight|point|spot|spotlight|area)(?:\s+(?:light|lamp))?|(?P<plain>light|lamp|lighting))"
    r"(?:\s+to the scene)?\.?$", re.I)
_LIGHT_KINDS = {"sun": "SUN", "sunlight": "SUN", "point": "POINT", "spot": "SPOT", "spotlight": "SPOT",
                "area": "AREA", "light": "POINT", "lamp": "POINT", "lighting": "SUN"}
_BRIGHTER = re.compile(_PLEASE + r"make\s+(?P<ref>(?:the\s+)?(?:\w+\s+)?(?:light|lamp|sun|spot(?:light)?))\s+"
                       r"(?P<how>brighter|stronger|dimmer|darker|weaker)\.?$", re.I)
_ADD_GROUND = re.compile(_PLEASE + r"(?:add|create|make|put)\s+(?:a\s+|some\s+)?(?:floor|ground(?: plane)?)"
                         r"(?:\s+(?:under|below|beneath)\s+(?:it|them|everything|the scene|all of it))?\.?$", re.I)
_HIDE = re.compile(_PLEASE + r"(?:hide\s+(?P<ref>.+?)|make\s+(?P<ref2>.+?)\s+invisible)\.?$", re.I)
_SHOW_ALL = re.compile(_PLEASE + r"(?:show|unhide|reveal)\s+(?:everything|all(?: the)? objects|all|the hidden "
                       r"(?:objects|ones|things))(?:\s+again)?\.?$", re.I)
_SHOW = re.compile(_PLEASE + r"(?:(?:show|unhide|reveal)\s+(?!(?:me|us|you)\b)(?P<ref>.+?)(?:\s+again)?|"
                   r"make\s+(?P<ref2>.+?)\s+visible(?:\s+again)?)\.?$", re.I)
_ADD_CAMERA = re.compile(_PLEASE + r"(?:add|create|insert)\s+(?:a\s+|another\s+|a new\s+)?camera"
                         r"(?:\s+(?:looking at|pointed at|aimed at|facing|that shows)\s+(?P<ref>.+?))?\.?$", re.I)
_AIM = re.compile(_PLEASE + r"(?:(?:point|aim|turn)\s+(?:the\s+)?camera\s+(?:at|to|towards?|on)|"
                  r"(?:make\s+)?the\s+camera\s+(?:look|point)\s+at|frame)\s+(?P<ref>.+?)"
                  r"(?:\s+(?:with|in) the camera)?\.?$", re.I)
_FRAME_ALL = re.compile(
    _PLEASE + r"(?:(?:make|let|get)\s+the\s+camera\s+(?:show|see|capture|fit|include)\s+|(?:frame|fit)\s+)"
    r"(?:everything|all(?: of)?(?: the)? objects|the (?:whole |entire )?scene|it all)"
    r"(?:\s+in (?:the )?(?:camera|view|shot|frame|picture))?\.?$", re.I)
_EVERYTHING = re.compile(r"^(?:everything|all(?: of)?(?: the)? objects|the (?:whole |entire )?scene|it all)$", re.I)
_RENDER = re.compile(
    _PLEASE + r"(?:(?:render|make a render of|do a render of|take a render of|give me a render of)"
    r"(?:\s+(?:the scene|the image|an image|a picture|a (?:quick )?preview|it|this|that|everything|the shot))?|"
    r"(?:make|do|take|give me)\s+(?:a\s+)?(?:quick\s+)?(?:preview\s+)?render)(?:\s+(?:for me|now))?\.?$", re.I)
_RENAME = re.compile(_PLEASE + r"(?:rename\s+(?P<ref>.+?)\s+(?:to|as)|call\s+(?P<ref2>.+?)|name\s+(?P<ref3>.+?))\s+"
                     r"(?P<new>[A-Za-z0-9][\w .'-]{0,60}?)\.?$", re.I)
_SIZE = re.compile(_PLEASE + r"(?:make|set|scale|resize)\s+(?P<ref>.+?)\s+(?:to\s+|so (?:that )?it'?s\s+)?"
                   rf"(?:exactly\s+)?(?P<n>{_AMOUNT})\s*(?P<u>{_UNIT})\s+"
                   r"(?P<dim>wide|tall|high|long|deep|thick|across|big|in size|in diameter)\.?$", re.I)
_SIZE_OF = re.compile(_PLEASE + r"(?:make|set|change)\s+(?:the\s+)?(?P<dim>width|height|length|depth|size)\s+of\s+"
                      rf"(?P<ref>.+?)\s+(?:to\s+)?(?P<n>{_AMOUNT})\s*(?P<u>{_UNIT})\.?$", re.I)
_DIMENSION_AXIS = {"wide": "x", "width": "x", "across": "x", "tall": "z", "high": "z", "height": "z", "long": "y",
                   "length": "y", "deep": "y", "depth": "y", "thick": "y", "big": "max", "size": "max",
                   "in size": "max", "in diameter": "max"}
_MOVE_BY = re.compile(_PLEASE + r"(?:move|shift|push|slide)\s+(?P<ref>.+?)\s+(?:"
                      + _DIR.format(n=1) + rf"\s+(?:by\s+)?(?P<n1>{_AMOUNT})\s*(?P<u1>{_UNIT})?|"
                      rf"(?:by\s+)?(?P<n2>{_AMOUNT})\s*(?P<u2>{_UNIT})?\s+" + _DIR.format(n=2) + r")\.?$", re.I)
_RAISE = re.compile(_PLEASE + r"(?P<verb>raise|lift|lower)\s+(?P<ref>.+?)"
                    rf"(?:\s+(?:by\s+)?(?P<n>{_AMOUNT})\s*(?P<u>{_UNIT})?)?\.?$", re.I)
_ON_FLOOR = re.compile(_PLEASE + r"(?:(?:put|place|set|move|drop|bring)\s+(?P<ref>.+?)\s+(?:down\s+)?"
                       r"(?:on|onto|to)\s+the\s+(?:floor|ground)|make\s+(?P<ref2>.+?)\s+(?:sit|stand|rest)\s+on\s+"
                       r"the\s+(?:floor|ground))\.?$", re.I)
_DROP = re.compile(_PLEASE + r"(?:drop\s+(?P<ref>.+?)(?:\s+down)?|let\s+(?P<ref2>.+?)\s+(?:fall|drop))\.?$", re.I)
_ON_TOP = re.compile(_PLEASE + r"(?:put|place|set|move|stack|stand)\s+(?P<ref>.+?)\s+(?:on top of|onto|on|atop)\s+"
                     r"(?P<target>.+?)\.?$", re.I)
_BEVEL = re.compile(
    _PLEASE + r"(?:bevel\s+(?P<ref>.+?)(?:'s|s')?(?:\s+edges)?|round\s+(?:off\s+)?(?:the\s+)?(?:edges|corners)\s+"
    r"(?:of|on)\s+(?P<ref2>.+?)|round\s+(?:off\s+)?(?P<ref3>.+?)(?:'s|s')?\s+(?:edges|corners)|"
    r"give\s+(?P<ref4>.+?)\s+(?:rounded|round|soft|softer|beveled|bevelled)\s+(?:edges|corners)|"
    r"add\s+(?:a\s+)?bevel(?:\s+modifier)?\s+to\s+(?P<ref5>.+?))"
    rf"(?:\s+(?:by\s+)?(?P<n>{_AMOUNT})\s*(?P<u>{_UNIT}))?\.?$", re.I)
_SUBDIVIDE = re.compile(
    _PLEASE + r"(?:subdivide\s+(?P<ref>.+?)|add\s+(?:a\s+)?(?:subdivision(?:\s+surface)?|subsurf)(?:\s+modifier)?\s+"
    r"to\s+(?P<ref2>.+?))(?:\s+(?:with\s+)?(?:(?P<n>\d)\s+levels?|(?:at\s+|to\s+)?level\s+(?P<n2>\d)))?\.?$", re.I)
_SHADE = re.compile(
    _PLEASE + r"(?:shade\s+(?P<ref>.+?)\s+(?P<how>smooth|flat)|(?P<how2>smooth|flat)[ -]shade\s+(?P<ref2>.+?)|"
    r"make\s+(?P<ref3>.+?)\s+(?:look\s+)?(?P<how3>smooth|smoother)(?:\s+shaded)?|"
    r"smooth\s+(?P<ref4>.+?)(?:\s+out)?)\.?$", re.I)
_REMOVE_PART = re.compile(_PLEASE + r"(?:remove|delete|get rid of|take off|clear)\s+(?:the\s+)?"
                          r"(?P<part>bevel|subdivision(?:\s+surface)?|subsurf|modifiers?|material|colou?r)"
                          r"(?:\s+modifier)?\s+(?:from|on|of)\s+(?P<ref>.+?)\.?$", re.I)
_COPIES = re.compile(
    _PLEASE + rf"(?:(?:make|create|add)\s+(?P<n>{_COUNT})\s+(?:more\s+)?(?:copies|duplicates|clones)\s+of\s+"
    rf"(?P<ref>.+?)|(?:duplicate|copy|clone)\s+(?P<ref2>.+?)\s+(?P<n2>{_COUNT})\s+times)"
    r"(?:\s+(?:in a (?:row|line)|next to each other|side by side))?\.?$", re.I)

# Material words: what each one sets on a Principled BSDF. Kinds first, then finishes ("shiny metal" is a metal,
# then made shiny), then colors, so the more specific word wins.
_MATERIAL_KINDS = {
    "metal": {"metallic": 1.0, "roughness": 0.25}, "metallic": {"metallic": 1.0, "roughness": 0.25},
    "steel": {"metallic": 1.0, "roughness": 0.3, "color": (0.56, 0.57, 0.58)},
    "iron": {"metallic": 1.0, "roughness": 0.45, "color": (0.53, 0.51, 0.49)},
    "aluminum": {"metallic": 1.0, "roughness": 0.3, "color": (0.91, 0.92, 0.92)},
    "aluminium": {"metallic": 1.0, "roughness": 0.3, "color": (0.91, 0.92, 0.92)},
    "chrome": {"metallic": 1.0, "roughness": 0.05, "color": (0.9, 0.9, 0.9)},
    "mirror": {"metallic": 1.0, "roughness": 0.0, "color": (0.95, 0.95, 0.95)},
    "copper": {"metallic": 1.0, "roughness": 0.25, "color": (0.955, 0.638, 0.538)},
    "bronze": {"metallic": 1.0, "roughness": 0.3, "color": (0.8, 0.5, 0.2)},
    "brass": {"metallic": 1.0, "roughness": 0.25, "color": (0.89, 0.73, 0.36)},
    "golden": {"metallic": 1.0, "roughness": 0.2, "color": (1.0, 0.766, 0.336)},
    "glass": {"transmission": 1.0, "roughness": 0.02, "ior": 1.45, "metallic": 0.0},
    "transparent": {"transmission": 1.0, "roughness": 0.02, "ior": 1.45, "metallic": 0.0},
    "clear": {"transmission": 1.0, "roughness": 0.02, "ior": 1.45, "metallic": 0.0},
    "see-through": {"transmission": 1.0, "roughness": 0.02, "ior": 1.45, "metallic": 0.0},
    "plastic": {"metallic": 0.0, "roughness": 0.35}, "rubber": {"metallic": 0.0, "roughness": 0.9},
    "ceramic": {"metallic": 0.0, "roughness": 0.15}, "porcelain": {"metallic": 0.0, "roughness": 0.12},
}
for _kind in _MATERIAL_KINDS.values():
    _kind.setdefault("transmission", 0.0)   # a metal or a plastic stops being glass
_MATERIAL_FINISHES = {
    "shiny": {"roughness": 0.1}, "glossy": {"roughness": 0.1}, "polished": {"roughness": 0.05},
    "reflective": {"roughness": 0.05}, "matte": {"roughness": 0.9}, "rough": {"roughness": 0.8},
    "dull": {"roughness": 0.8}, "brushed": {"roughness": 0.45}, "frosted": {"roughness": 0.35},
    "glow": {"emission": "BASE", "emission_strength": 5.0}, "glowing": {"emission": "BASE", "emission_strength": 5.0},
    "emissive": {"emission": "BASE", "emission_strength": 5.0}, "luminous": {"emission": "BASE",
                                                                           "emission_strength": 5.0},
    "neon": {"emission": "BASE", "emission_strength": 10.0},
}
_METAL_COLORS = {"gold": (1.0, 0.766, 0.336), "silver": (0.972, 0.960, 0.915)}
_MATERIAL_FILLER = {"a", "an", "and", "very", "really", "bit", "little", "look", "looking", "like", "made", "out",
                    "of", "into", "to", "be", "with", "material", "finish", "surface", "texture", "shader", "kind",
                    "see", "through"}
_MATERIAL_VERB = re.compile(_PLEASE + r"(?P<verb>make|turn|paint|change|set|give)\s+(?P<rest>.+?)\.?$", re.I)

# ---------- object references ----------

def _clean_ref(ref_text: str) -> str:
    w = re.sub(r"[^a-z0-9 ]", " ", (ref_text or "").lower()).strip()
    w = re.sub(r"^(?:the colou?r of|the size of)\s+", "", w)
    return re.sub(r"^(?:the|that|this|my)\s+", "", w).strip()


def _resolve_reference(ref_text: str, session, bridge=None):
    """Which object (its real Blender name) `ref_text` ("it", "the second one", "the cube") means, or None if
    nothing matches. Objects Jarvis made this session come first; otherwise the real scene is asked (Blender's
    default "Cube", or whatever the user selected by hand), never guessed."""
    found = _resolve_tracked(ref_text, session)
    if found and bridge is not None and not _exists(bridge, found):
        _forget(session, found)   # deleted by hand since: look in the scene instead
        found = None
    if not found and bridge is not None:
        found = _resolve_in_scene(ref_text, bridge)
        if found:
            session.remember_blender_object(found, "")
    if found:
        session.blender_focus = found
        session.blender_feature = None
    return found


def _exists(bridge, name: str) -> bool:
    response = _run(bridge, _SCENE + f"RESULT = '1' if {name!r} in scene.objects else '0'", timeout=8)
    return response.get("output") != "0"   # only a definite "not there" counts; an odd answer keeps the name


def _forget(session, name: str) -> None:
    session.blender_objects[:] = [o for o in session.blender_objects if o["name"] != name]
    if getattr(session, "blender_focus", None) == name:
        session.blender_focus = None


def _resolve_in_scene(ref_text: str, bridge):
    w = _clean_ref(ref_text)
    response = _run(bridge, f"w = {w!r}\n" + _SCENE +
                            "objs = list(scene.objects)\n"
                            f"if w in {_GENERIC_REF!r}:\n"
                            "    pick = layer.objects.active or next((o for o in objs if o.select_get(view_layer=layer)),"
                            " None)\n"
                            "else:\n"
                            "    pick = (next((o for o in objs if o.name.lower() == w), None)\n"
                            "            or next((o for o in objs if o.name.lower().startswith(w)), None)\n"
                            "            or next((o for o in objs if w.endswith(o.name.lower())), None))\n"
                            # "the light" / "the sun" / "the camera" when nothing is named that
                            "    kinds = {'light': 'LIGHT', 'lamp': 'LIGHT', 'sun': 'LIGHT', 'camera': 'CAMERA'}\n"
                            "    last = w.split()[-1] if w.split() else ''\n"
                            "    if not pick and last in kinds:\n"
                            "        pick = (scene.camera if last == 'camera' else None) or next("
                            "(o for o in objs if o.type == kinds[last]), None)\n"
                            "RESULT = pick.name if pick else ''", timeout=8)
    if not response.get("ok"):
        return None
    return (response.get("output") or "").strip() or None


def _resolve_tracked(ref_text: str, session):
    w = _clean_ref(ref_text)
    if not session.blender_objects:
        return None
    if w in _GENERIC_REF:
        return getattr(session, "blender_focus", None) or session.last_blender_object
    for word, idx in _ORDINAL.items():
        if re.search(rf"\b{word}\b", w):
            try:
                return session.blender_objects[idx]["name"]
            except IndexError:
                return None
    for obj in reversed(session.blender_objects):
        if obj["kind"] and obj["kind"] in w:
            return obj["name"]
    for obj in session.blender_objects:
        if obj["name"].lower() in w:
            return obj["name"]
    return None   # names something not tracked here: the scene lookup decides


def _run(bridge, code: str, timeout: float = 15):
    return bridge.run(code, timeout=timeout)


def _error(response) -> str:
    return (response.get("error") or "unknown error").strip().splitlines()[-1][:200]


def _target(bridge, session, ref_text: str, doing: str) -> str:
    name = _resolve_reference(ref_text, session, bridge)
    if not name:
        raise RuntimeError(f"I couldn't find \"{ref_text.strip()}\" in Blender's scene, so I didn't {doing}.")
    return name


def _before_after(response, failed: str, unchanged: str):
    if not response.get("ok"):
        raise RuntimeError(f"{failed}: {_error(response)}")
    before, _, after = (response.get("output") or "").partition("|")
    if not after or before == after:
        raise RuntimeError(unchanged)
    return before


# ---------- actions: each runs, checks Blender's real state, and only then reports success ----------

def _create_action(bridge, session, shape_word: str):
    op = _SHAPES.get(shape_word.lower(), "cube")
    kind = "sphere" if op == "uv_sphere" else op

    def action():
        offset = sum(1 for o in session.blender_objects if o["kind"] == kind) * 3.0
        # free_spot: slid clear of whatever is already there (Blender's own cube sits at the origin).
        response = _kit_run(bridge, "before = set(bpy.data.objects.keys())\n"
                                    f"bpy.ops.mesh.primitive_{op}_add({_SHAPE_ARGS[op]}, location=({offset}, 0, 0))\n"
                                    "made = [n for n in bpy.data.objects.keys() if n not in before]\n"
                                    "if made: free_spot(made[0])\n"
                                    "RESULT = made[0] if made else ''")
        if not response.get("ok"):
            raise RuntimeError(f"I tried to create a {shape_word} but Blender reported an error: {_error(response)}")
        new_name = (response.get("output") or "").strip()
        verify = _run(bridge, f"RESULT = '1' if bpy.data.objects.get({new_name!r}) else '0'", timeout=8)
        if not new_name or verify.get("output") != "1":
            raise RuntimeError(f"I ran the command to create a {shape_word}, but Blender's scene doesn't actually "
                               "show it — I won't claim that worked.")
        session.remember_blender_object(new_name, kind)
        session.blender_focus = new_name
        session.last_undo = {"description": f"created a {shape_word}",
                             "code": f"obj = bpy.data.objects.get({new_name!r})\n"
                                     "if obj: bpy.data.objects.remove(obj, do_unlink=True)\n"
                                     "RESULT = 'removed'"}
        return f"Done — I created a {shape_word} ({new_name})."
    return action


def _resize_action(bridge, session, ref_text: str, direction: str, times: float = None):
    def action():
        name = _target(bridge, session, ref_text, "resize anything")
        amount = times or RESIZE_FACTOR
        factor = amount if _GROW[direction] else 1 / amount
        ax, ay, az = _RESIZE_AXES[direction]
        sx, sy, sz = (factor if ax else 1.0), (factor if ay else 1.0), (factor if az else 1.0)
        response = _run(bridge, f"obj = bpy.data.objects.get({name!r})\n"
                                f"before = tuple(obj.scale)\n"
                                f"obj.scale = (obj.scale[0]*{sx}, obj.scale[1]*{sy}, obj.scale[2]*{sz})\n"
                                f"RESULT = str(before) + '|' + str(tuple(obj.scale))")
        before_s = _before_after(response, f"I tried to make it {direction} but Blender reported an error",
                                 "I ran the resize, but the object's scale in Blender didn't actually change — "
                                 "I won't claim that worked.")
        how = f"{amount:g} times {direction}" if times else direction
        session.last_undo = {"description": f"made it {how}",
                             "code": f"obj = bpy.data.objects.get({name!r})\n"
                                     f"obj.scale = {before_s}\nRESULT = 'restored'"}
        return f"Done — I made {name} {how}."
    return action


def _move_direction_action(bridge, session, ref_text: str, direction: str):
    def action():
        name = _target(bridge, session, ref_text, "move anything")
        dx, dy, dz = _DIRECTION_VECTOR[direction]
        response = _run(bridge, f"obj = bpy.data.objects.get({name!r})\n"
                                f"before = tuple(obj.location)\n"
                                f"obj.location = (obj.location[0]+{dx * MOVE_STEP}, "
                                f"obj.location[1]+{dy * MOVE_STEP}, obj.location[2]+{dz * MOVE_STEP})\n"
                                f"RESULT = str(before) + '|' + str(tuple(obj.location))")
        before_s = _before_after(response, f"I tried to move it {direction} but Blender reported an error",
                                 "I ran the move, but the object's location in Blender didn't actually change — "
                                 "I won't claim that worked.")
        session.last_undo = {"description": f"moved it {direction}",
                             "code": f"obj = bpy.data.objects.get({name!r})\n"
                                     f"obj.location = {before_s}\nRESULT = 'restored'"}
        return f"Done — I moved {name} {direction}."
    return action


def _move_next_to_action(bridge, session, ref_text: str, target_text: str):
    def action():
        name = _resolve_reference(ref_text, session, bridge)
        target_name = _resolve_reference(target_text, session, bridge)
        if target_name == name:
            others = [o["name"] for o in session.blender_objects if o["name"] != name]
            target_name = others[-1] if others else None
        if not name or not target_name:
            raise RuntimeError("I don't have two distinct objects to work with yet in this session.")
        session.blender_focus = name
        response = _run(bridge, f"obj = bpy.data.objects.get({name!r})\n"
                                f"ref = bpy.data.objects.get({target_name!r})\n"
                                f"before = tuple(obj.location)\n"
                                f"obj.location = (ref.location[0] + 3.0, ref.location[1], ref.location[2])\n"
                                f"RESULT = str(before) + '|' + str(tuple(obj.location))")
        if not response.get("ok"):
            raise RuntimeError("I tried to move it next to the other object but Blender reported an error: "
                               f"{_error(response)}")
        before_s, _, after_s = (response.get("output") or "").partition("|")
        if not after_s:
            raise RuntimeError("I ran the move, but Blender didn't report a location back — I won't claim that "
                               "worked.")
        if before_s == after_s:
            # It was already exactly where "next to" would put it (e.g. still at its original creation offset) —
            # genuinely nothing to do, not a failure to report as one.
            return "Done — it was already next to the other one."
        session.last_undo = {"description": "moved it next to the other one",
                             "code": f"obj = bpy.data.objects.get({name!r})\n"
                                     f"obj.location = {before_s}\nRESULT = 'restored'"}
        return "Done — I moved it next to the other one."
    return action


def _color_action(bridge, session, ref_text: str, color: str):
    r, g, b = _COLORS[color.lower()]

    def action():
        name = _target(bridge, session, ref_text, "color anything")
        material = f"Jarvis {color.lower()}"
        response = _run(bridge, f"obj = bpy.data.objects.get({name!r})\n"
                                "before = obj.active_material.name if obj.active_material else ''\n"
                                f"mat = bpy.data.materials.get({material!r}) or bpy.data.materials.new({material!r})\n"
                                f"mat.diffuse_color = ({r}, {g}, {b}, 1)\n"
                                "try:\n"
                                "    mat.use_nodes = True\n"
                                "    bsdf = mat.node_tree.nodes.get('Principled BSDF')\n"
                                f"    if bsdf: bsdf.inputs['Base Color'].default_value = ({r}, {g}, {b}, 1)\n"
                                "except Exception:\n"
                                "    pass\n"
                                "if obj.data and hasattr(obj.data, 'materials'):\n"
                                "    if obj.data.materials:\n"
                                "        obj.data.materials[0] = mat\n"
                                "    else:\n"
                                "        obj.data.materials.append(mat)\n"
                                "RESULT = before + '|' + (obj.active_material.name if obj.active_material else '')")
        if not response.get("ok"):
            raise RuntimeError(f"I tried to color it {color} but Blender reported an error: {_error(response)}")
        before, _, after = (response.get("output") or "").partition("|")
        if after != material:
            raise RuntimeError(f"I ran the color change, but {name} doesn't show the {color} material — I won't "
                               "claim that worked.")
        restore = f"bpy.data.materials.get({before!r})" if before else "None"
        session.last_undo = {"description": f"colored it {color}",
                             "code": f"obj = bpy.data.objects.get({name!r})\n"
                                     f"old = {restore}\n"
                                     "if old: obj.data.materials[0] = old\n"
                                     "else: obj.data.materials.clear()\n"
                                     "RESULT = 'restored'"}
        return f"Done — {name} is {color} now."
    return action


def _rotate_action(bridge, session, ref_text: str, degrees: float, axis: str):
    index = "xyz".index(axis)

    def action():
        name = _target(bridge, session, ref_text, "rotate anything")
        response = _run(bridge, "import math\n"
                                f"obj = bpy.data.objects.get({name!r})\n"
                                "before = tuple(obj.rotation_euler)\n"
                                f"obj.rotation_euler[{index}] += math.radians({degrees})\n"
                                "RESULT = str(before) + '|' + str(tuple(obj.rotation_euler))")
        before_s = _before_after(response, "I tried to rotate it but Blender reported an error",
                                 "I ran the rotation, but the object didn't actually turn — I won't claim that "
                                 "worked.")
        session.last_undo = {"description": f"rotated it {degrees:g} degrees",
                             "code": f"obj = bpy.data.objects.get({name!r})\n"
                                     f"obj.rotation_euler = {before_s}\nRESULT = 'restored'"}
        return f"Done — I rotated {name} {degrees:g} degrees around {axis.upper()}."
    return action


def _delete_action(bridge, session, ref_text: str):
    def action():
        name = _target(bridge, session, ref_text, "delete anything")
        # A hidden copy is kept (fake user) so "undo" can put it back exactly as it was.
        response = _run(bridge, _SCENE +
                                f"obj = bpy.data.objects.get({name!r})\n"
                                "home = obj.users_collection[0].name if obj.users_collection else ''\n"
                                "keep = obj.copy()\n"
                                "keep.use_fake_user = True\n"
                                "bpy.data.objects.remove(obj, do_unlink=True)\n"
                                f"keep.name = {name!r}\n"
                                f"RESULT = home + '|' + keep.name + '|' + ('0' if {name!r} in scene.objects else '1')")
        if not response.get("ok"):
            raise RuntimeError(f"I tried to delete {name} but Blender reported an error: {_error(response)}")
        home, kept, gone = ((response.get("output") or "").split("|") + ["", "", ""])[:3]
        if gone != "1":
            raise RuntimeError(f"I ran the delete, but {name} is still in the scene — I won't claim that worked.")
        _forget(session, name)
        collection = f"bpy.data.collections.get({home!r})" if home else "None"
        session.last_undo = {"description": f"deleted {name}",
                             "code": _SCENE +
                                     f"obj = bpy.data.objects.get({kept!r})\n"
                                     f"home = {collection} or scene.collection\n"
                                     "home.objects.link(obj)\n"
                                     "obj.use_fake_user = False\n"
                                     "RESULT = obj.name"}
        return f"Done — I deleted {name}."
    return action


def _duplicate_action(bridge, session, ref_text: str):
    def action():
        name = _target(bridge, session, ref_text, "duplicate anything")
        response = _run(bridge, _SCENE +
                                f"obj = bpy.data.objects.get({name!r})\n"
                                "new = obj.copy()\n"
                                "if obj.data: new.data = obj.data.copy()\n"
                                "(obj.users_collection[0] if obj.users_collection else scene.collection).objects.link(new)\n"
                                "new.location.x += 3.0\n"
                                "RESULT = new.name if new.name in scene.objects else ''")
        if not response.get("ok") or not (response.get("output") or "").strip():
            raise RuntimeError(f"I tried to duplicate {name} but it didn't work: {_error(response)}")
        new_name = response["output"].strip()
        kind = next((o["kind"] for o in session.blender_objects if o["name"] == name), "")
        session.remember_blender_object(new_name, kind)
        session.blender_focus = new_name
        session.last_undo = {"description": f"duplicated {name}",
                             "code": f"obj = bpy.data.objects.get({new_name!r})\n"
                                     "if obj: bpy.data.objects.remove(obj, do_unlink=True)\n"
                                     "RESULT = 'removed'"}
        return f"Done — I duplicated {name} ({new_name})."
    return action


def _select_action(bridge, session, ref_text: str):
    def action():
        name = _target(bridge, session, ref_text, "select anything")
        response = _run(bridge, _SCENE +
                                "for o in scene.objects: o.select_set(False, view_layer=layer)\n"
                                f"obj = bpy.data.objects.get({name!r})\n"
                                "obj.select_set(True, view_layer=layer)\n"
                                "layer.objects.active = obj\n"
                                "RESULT = layer.objects.active.name if layer.objects.active else ''")
        if not response.get("ok") or (response.get("output") or "").strip() != name:
            raise RuntimeError(f"I tried to select {name} but it didn't work: {_error(response)}")
        return f"Done — {name} is selected."
    return action


def _focus_action():
    """Bring Blender's window forward — a plain OS window-focus action, no bpy/bridge round trip needed, so it
    works even if Blender happens to be mid-operation or the bridge is momentarily busy."""
    def action():
        import app_launcher
        import winctl
        windows = app_launcher.app_windows("Blender")
        if not windows:
            raise RuntimeError("Blender doesn't seem to be open anymore.")
        winctl.focus(windows[0][0])
        return "Done — switched to Blender."
    return action


def _undo_action(bridge, session):
    """Reverses whatever Jarvis's own last deterministic action did, rather than calling Blender's native
    bpy.ops.ed.undo() — that operator's poll() rejects calls made from a script/timer context (confirmed: it fails
    even with temp_override supplying a window/area/region), and more importantly, undoing Jarvis's own last change
    specifically is what "undo that" means here — not whatever the user may have done by hand in Blender."""
    def action():
        pending = session.last_undo
        if not pending:
            raise RuntimeError("There's nothing I've done in this session yet for me to undo.")
        response = _run(bridge, pending["code"])
        if not response.get("ok"):
            raise RuntimeError(f"Undo didn't work: {_error(response)}")
        session.last_undo = None
        return f"Done — undid: {pending['description']}."
    return action


def _redo_action():
    def action():
        return "There's nothing to redo — I can undo my own changes, one at a time, but not redo them."
    return action


# A new file never replaces one that's already there (another project, or an earlier session's jarvis_scene):
# it gets the next free name instead ("jarvis_scene 2.blend"). Saving the file that's open is a normal save.
_SAVE_AS = """import os
path = os.path.join(os.path.expanduser('~'), 'Documents', {name!r})
os.makedirs(os.path.dirname(path), exist_ok=True)
same = bpy.data.filepath and os.path.normcase(os.path.abspath(bpy.data.filepath)) == os.path.normcase(path)
stem, ext = os.path.splitext(path)
n = 2
while os.path.exists(path) and not same:
    path = f"{{stem}} {{n}}{{ext}}"
    n += 1
bpy.ops.wm.save_as_mainfile(filepath=path)
RESULT = bpy.data.filepath + ('|kept the other file' if n > 2 else '')"""


def _save_action(bridge, name: str = None):
    def action():
        if name:
            safe = name.strip()
            if not safe.lower().endswith(".blend"):
                safe += ".blend"
            code = _SAVE_AS.format(name=safe)
        else:
            code = ("if bpy.data.filepath:\n    bpy.ops.wm.save_mainfile()\n    RESULT = bpy.data.filepath\nelse:\n" +
                    "\n".join("    " + line for line in _SAVE_AS.format(name="jarvis_scene.blend").splitlines()))
        response = _run(bridge, code, timeout=60)
        if not response.get("ok") or not response.get("output"):
            raise RuntimeError("I tried to save but Blender reported an error: "
                               f"{(response.get('error') or 'no file path came back')[:200]}")
        verify = _run(bridge, "import os\nRESULT = '1' if os.path.exists(bpy.data.filepath) else '0'", timeout=8)
        if verify.get("output") != "1":
            raise RuntimeError("I ran the save, but the file doesn't actually exist on disk — I won't claim that "
                               "worked.")
        saved, _, kept = response["output"].partition("|")
        if kept:
            return f"Done — saved to {saved}. A file with that name was already there, so I didn't replace it."
        return f"Done — saved to {saved}."
    return action


# ---------- actions built on blender_scene.py's helpers (see blender_control.with_kit) ----------
# Each one changes Blender and checks the result in the same call, reading Blender's own data back (not the values
# it meant to set), and keeps a snapshot so "undo" puts the object back exactly as it was.

def _kit_run(bridge, code: str, timeout: float = 30):
    return _run(bridge, blender_control.with_kit(code), timeout=timeout)


def _rename_tracked(session, old: str, new: str) -> None:
    for o in session.blender_objects:
        if o["name"] == old:
            o["name"] = new
    if getattr(session, "blender_focus", None) == old:
        session.blender_focus = new


def _edit_action(bridge, session, ref_text: str, doing: str, change: str, verify: str, done: str,
                 description: str, timeout: float = 30):
    """One object changed by `change` (Python using `o`, the object), then `verify` — an expression giving
    (ok, detail) from Blender's state afterwards. `done` may use {name} and {detail}."""
    def action():
        name = _target(bridge, session, ref_text, doing)
        code = (f"o = find({name!r})\nsnap = snapshot(o)\n{change}\n_sync()\nok, detail = {verify}\n"
                "RESULT = json.dumps({'snap': snap, 'ok': bool(ok), 'detail': str(detail), 'name': o.name})")
        response = _kit_run(bridge, code, timeout)
        if not response.get("ok"):
            raise RuntimeError(f"I tried to {doing} but Blender reported an error: {_error(response)}")
        out = json.loads(response["output"])
        if not out["ok"]:
            raise RuntimeError(f"I ran it, but {out['detail']} — I won't claim that worked.")
        if out["name"] != name:
            _rename_tracked(session, name, out["name"])
        session.blender_focus = out["name"]
        session.last_undo = {"description": description,
                             "code": blender_control.with_kit(
                                 f"RESULT = restore(json.loads({json.dumps(out['snap'])!r}), {out['name']!r})")}
        return done.format(name=out["name"], detail=out["detail"])
    return action


def _new_object_action(bridge, session, code: str, kind: str, doing: str, done: str, description: str):
    """`code` makes one object and sets `made` to it; it must exist in the scene afterwards. Undo removes it."""
    def action():
        response = _kit_run(bridge, code + "\n_sync()\nRESULT = json.dumps({'name': made.name, 'there': "
                                           "made.name in bpy.context.scene.objects, 'detail': str(detail)})")
        if not response.get("ok"):
            raise RuntimeError(f"I tried to {doing} but Blender reported an error: {_error(response)}")
        out = json.loads(response["output"])
        if not out["there"]:
            raise RuntimeError(f"I ran it, but the new {kind} isn't in the scene — I won't claim that worked.")
        session.remember_blender_object(out["name"], kind)
        session.blender_focus = out["name"]
        session.last_undo = {"description": description,
                             "code": f"obj = bpy.data.objects.get({out['name']!r})\n"
                                     "if obj: bpy.data.objects.remove(obj, do_unlink=True)\n"
                                     "scene = bpy.context.scene\n"   # removing the scene camera leaves none
                                     "if scene.camera is None:\n"
                                     "    scene.camera = next((o for o in scene.objects if o.type == 'CAMERA'), None)\n"
                                     "RESULT = 'removed'"}
        return done.format(name=out["name"], detail=out["detail"])
    return action


def _describe_action(bridge):
    def action():
        response = _kit_run(bridge, "RESULT = describe()", timeout=20)
        if not response.get("ok"):
            raise RuntimeError(f"I couldn't read Blender's scene: {_error(response)}")
        return response["output"]
    return action


def _check_action(bridge):
    def action():
        response = _kit_run(bridge, "RESULT = json.dumps(check())", timeout=30)
        if not response.get("ok"):
            raise RuntimeError(f"I couldn't check Blender's scene: {_error(response)}")
        problems = json.loads(response["output"])
        if not problems:
            return "I checked the scene: nothing's floating, hidden from the camera, unlit or missing a material."
        said = [(f"{p['object']} {p['problem']}" if p["object"] else p["problem"]) for p in problems[:4]]
        more = f" — and {len(problems) - 4} more" if len(problems) > 4 else ""
        return "I checked the scene and found: " + "; ".join(said) + more + "."
    return action


_RENDER_CODE = """import os, time
blend = bpy.data.filepath
home = os.path.join(os.path.expanduser('~'), 'Documents', 'Jarvis renders')
folder = os.path.join(os.path.dirname(blend), 'renders') if blend else home
stem = os.path.splitext(os.path.basename(blend))[0] if blend else 'render'
facts = render(os.path.join(folder, stem + time.strftime(' %Y-%m-%d %H-%M-%S') + '.png'), resolution_percent={percent})
facts['problems'] = [p['problem'] for p in check() if p['severity'] == 'error'] if facts['flat'] else []
RESULT = json.dumps(facts)"""


def _render_action(bridge, preview: bool):
    def action():
        response = _kit_run(bridge, _RENDER_CODE.format(percent=50 if preview else None), timeout=RENDER_SECONDS)
        if response.get("busy"):
            raise RuntimeError(f"Blender is still rendering after {RENDER_SECONDS // 60} minutes; it will finish "
                               "on its own and save the picture in a 'renders' folder.")
        if not response.get("ok"):
            raise RuntimeError(f"I tried to render but Blender reported an error: {_error(response)}")
        facts = json.loads(response["output"])
        if facts["flat"]:
            why = f" ({'; '.join(facts['problems'][:2])})" if facts["problems"] else ""
            raise RuntimeError(f"I rendered it, but the picture came out as one flat color{why}. It's at "
                               f"{facts['path']}.")
        done = (f"Done — rendered a {facts['width']} by {facts['height']} picture in {facts['seconds']:g} seconds, "
                f"saved to {facts['path']}.")
        # Measured from the picture's pixels (blender_scene.render): worth saying, not worth failing over.
        if facts["brightness"] < DARK_RENDER:
            done += (f" It came out very dark (average brightness {facts['brightness']:.0%}): the lights may be too "
                     "weak or blocked.")
        elif facts["brightness"] > BRIGHT_RENDER:
            done += f" It came out almost white (average brightness {facts['brightness']:.0%}): it's overexposed."
        return done
    return action


def _material_action(bridge, session, ref_text: str, values: dict, said: str):
    values = dict(values)
    glow_from_base = values.get("emission") == "BASE"   # "make it glow": in the color it already has
    if glow_from_base:
        del values["emission"]
    args = [f"{k}={v!r}" for k, v in values.items()]
    if glow_from_base:
        args.append("emission=shader_values(o).get('color', (1, 1, 1))")
    change = f"paint(o, {', '.join(args)})"
    expected = dict(values)
    if glow_from_base:
        expected["emission_strength"] = values.get("emission_strength", 5.0)
    return _edit_action(bridge, session, ref_text, f"make it {said}", change, f"matches(o, {expected!r})",
                        "Done — {name} is " + said + " now.", f"made it {said}")


def _copies_action(bridge, session, ref_text: str, count: int):
    def action():
        name = _target(bridge, session, ref_text, "copy anything")
        response = _kit_run(bridge, f"made = [o.name for o in row_of_copies(find({name!r}), {count})]\n"
                                    "RESULT = json.dumps([n for n in made if n in bpy.context.scene.objects])")
        if not response.get("ok"):
            raise RuntimeError(f"I tried to copy {name} but Blender reported an error: {_error(response)}")
        made = json.loads(response["output"])
        if len(made) != count:
            raise RuntimeError(f"I asked for {count} copies, but {len(made)} are in the scene — I won't claim "
                               "that worked.")
        kind = next((o["kind"] for o in session.blender_objects if o["name"] == name), "")
        for n in made:
            session.remember_blender_object(n, kind)
        session.blender_focus = made[-1]
        session.last_undo = {"description": f"made {count} copies of {name}",
                             "code": f"for n in {made!r}:\n    o = bpy.data.objects.get(n)\n"
                                     "    if o: bpy.data.objects.remove(o, do_unlink=True)\nRESULT = 'removed'"}
        return f"Done — I made {count} copies of {name} in a row."
    return action


def _aim_camera_action(bridge, session, ref_text):
    """Point the scene camera at an object (or, with no object, at everything), backing it off along its line
    of sight until the whole thing is in the picture. Makes a camera when there's none (undo removes it)."""
    def action():
        target = _target(bridge, session, ref_text, "aim the camera") if ref_text else None
        code = (f"targets = {[target] if target else None!r}\n"
                "cam = bpy.context.scene.camera\nhad = cam is not None\nsnap = snapshot(cam) if had else None\n"
                "if had and targets:\n    look_at(cam, targets[0])\n"
                "if not had or not sees(cam, targets):\n    cam = frame(targets)\n"
                "RESULT = json.dumps({'snap': snap, 'name': cam.name, 'ok': sees(cam, targets), 'had': had})")
        response = _kit_run(bridge, code)
        if not response.get("ok"):
            raise RuntimeError(f"I tried to aim the camera but Blender reported an error: {_error(response)}")
        out = json.loads(response["output"])
        if not out["ok"]:
            raise RuntimeError("I moved the camera, but it still doesn't see all of it — I won't claim that worked.")
        if out["had"]:
            session.last_undo = {"description": "moved the camera", "code": blender_control.with_kit(
                f"RESULT = restore(json.loads({json.dumps(out['snap'])!r}))")}
        else:
            session.last_undo = {"description": "added a camera",
                                 "code": f"obj = bpy.data.objects.get({out['name']!r})\n"
                                         "if obj: bpy.data.objects.remove(obj, do_unlink=True)\nRESULT = 'removed'"}
        what = target or "everything"
        return f"Done — the camera shows {what} now." if out["had"] else f"Done — I added a camera that shows {what}."
    return action


_SHOW_ALL_CODE = """hidden = [o for o in bpy.context.scene.objects if not o.visible_get() or o.hide_render]
names = {o.name: [o.hide_get(), o.hide_viewport, o.hide_render] for o in hidden}
for o in hidden:
    o.hide_set(False)
    o.hide_viewport = False
    o.hide_render = False
_sync()
RESULT = json.dumps({'shown': names, 'still': [o.name for o in hidden if not o.visible_get()]})"""


def _show_all_action(bridge, session):
    def action():
        response = _kit_run(bridge, _SHOW_ALL_CODE)
        if not response.get("ok"):
            raise RuntimeError(f"I tried to show everything but Blender reported an error: {_error(response)}")
        out = json.loads(response["output"])
        if not out["shown"]:
            return "Nothing was hidden — everything already shows."
        if out["still"]:
            raise RuntimeError(f"I unhid them, but {', '.join(out['still'][:4])} still don't show (a hidden "
                               "collection, probably) — I won't claim that worked.")
        session.last_undo = {"description": "showed everything",
                             "code": f"for n, (h, v, r) in {out['shown']!r}.items():\n"
                                     "    o = bpy.data.objects.get(n)\n"
                                     "    if o:\n        o.hide_set(h)\n        o.hide_viewport, o.hide_render = v, r\n"
                                     "RESULT = 'hidden again'"}
        return f"Done — {len(out['shown'])} hidden object{'s' if len(out['shown']) != 1 else ''} show again."
    return action


def _add_camera_action(bridge, session, ref_text):
    def action():
        target = _target(bridge, session, ref_text, "aim a camera") if ref_text else None
        code = (f"targets = {[target] if target else None!r}\n"
                "made = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))\n"
                "bpy.context.collection.objects.link(made)\nmade.location = (7.4, -6.5, 5.3)\n"
                "bpy.context.scene.camera = made\nframe(targets, camera=made)\n"
                "if not sees(made, targets):\n    raise RuntimeError('the new camera still does not see it all')\n"
                "detail = targets[0] if targets else 'everything'")
        return _new_object_action(bridge, session, code, "camera", "add a camera",
                                  "Done — I added a camera ({name}) that shows {detail}, and made it the scene's "
                                  "camera.", "added a camera")()
    return action


def _units(number: str, unit: str) -> float:
    n = float(_WORD_NUMBERS.get(number.lower().strip(), number))
    return n * _UNIT_METRES.get((unit or "m").lower().rstrip("."), 1.0)


def _parse_material(text: str):
    """("the cube", {"metallic": 1.0, "roughness": 0.1}, "shiny metal") for "make the cube shiny metal", or None.
    Only when a material kind or finish is said: a color alone stays with the plain color command."""
    m = _MATERIAL_VERB.match(text)
    if not m:
        return None
    rest = re.sub(r"\bsee\s+through\b", "see-through", m.group("rest"), flags=re.I)
    # two-word colors ("light blue") become one word here: "light-blue"
    rest = re.sub(r"\b(light|dark|sky)\s+([a-z]+)\b",
                  lambda c: c.group(0).replace(" ", "-") if c.group(0).lower() in _COLORS else c.group(0), rest,
                  flags=re.I)
    raw = rest.split()
    vocabulary = set(_MATERIAL_KINDS) | set(_MATERIAL_FINISHES) | set(_COLORS) | set(_METAL_COLORS)
    for i in range(1, len(raw)):
        words = [w.strip(",.").lower() for w in raw[i:]]
        words = [w.replace("-", " ") if w.replace("-", " ") in _COLORS else w for w in words
                 if w and w not in _MATERIAL_FILLER]
        if not words or any(w not in vocabulary for w in words):
            continue
        if not any(w in _MATERIAL_KINDS or w in _MATERIAL_FINISHES for w in words):
            return None
        values = {}
        for w in words:
            values.update(_MATERIAL_KINDS.get(w, {}))
        for w in words:
            values.update(_MATERIAL_FINISHES.get(w, {}))
        metal = values.get("metallic", 0) > 0.5
        color = next((_METAL_COLORS[w] if metal and w in _METAL_COLORS else _COLORS[w]
                      for w in words if w in _COLORS or w in _METAL_COLORS), None)
        if color is not None:
            values["color"] = color
            if values.get("emission") == "BASE":
                values["emission"] = color
        said = " ".join({"glow": "glowing"}.get(w, w) for w in words)
        return " ".join(raw[:i]), values, said
    return None


def _move_by_action(bridge, session, ref_text, direction, metres):
    d = tuple(v * metres for v in _DIRECTIONS[direction])
    return _edit_action(bridge, session, ref_text, "move anything", f"start = o.location.copy()\n"
                        f"o.location += Vector({d!r})",
                        f"((o.location - start - Vector({d!r})).length < 1e-4, "
                        "'it is at ' + str(tuple(round(v, 3) for v in o.location)))",
                        "Done — I moved {name} " + f"{direction} {metres:g} m.", f"moved it {direction} {metres:g} m")


def _size_action(bridge, session, ref_text, axis, metres, word):
    side = "max(size_of(o))" if axis == "max" else f"size_of(o)[{'xyz'.index(axis)}]"
    return _edit_action(bridge, session, ref_text, "resize anything", f"set_size(o, {axis!r}, {metres!r})",
                        f"(abs({side} - {metres!r}) < 1e-3, 'it is %.3f m' % {side})",
                        "Done — {name} is " + f"{metres:g} m {word} now.", f"made it {metres:g} m {word}")


def _on_top_action(bridge, session, ref_text, target_text):
    def action():
        target = _target(bridge, session, target_text, "put anything on it")
        name = _target(bridge, session, ref_text, "move anything")
        if name == target:
            raise RuntimeError(f"I can't put {name} on top of itself.")
        return _edit_action(bridge, session, name, "move anything", f"place_on(o, {target!r})",
                            f"(abs(box(o)[0].z - box(find({target!r}))[1].z) < 1e-3, "
                            "'its bottom is at %.3f m' % box(o)[0].z)",
                            "Done — {name} sits on top of " + f"{target} now.", f"put it on {target}")()
    return action


def _shade_action(bridge, session, ref_text, on: bool, subdivide_low_poly: bool):
    change = ((f"if {subdivide_low_poly!r} and o.type == 'MESH' and len(o.data.polygons) < 200 and "
               "not any(m.type == 'SUBSURF' for m in o.modifiers):\n    subdivide(o, 2)\n") +
              f"smooth(o, {on!r})\n"
              f"wanted = ('subdivided and ' if {subdivide_low_poly!r} and any(m.type == 'SUBSURF' for m in "
              f"o.modifiers) else '') + '{'smooth' if on else 'flat'} shaded'\n"
              f"done = all(p.use_smooth == {on!r} for p in o.data.polygons)")
    verify = "(done, wanted if done else 'some of its faces still are not ' + wanted)"
    return _edit_action(bridge, session, ref_text, "change its shading", change, verify,
                        "Done — {name} is {detail} now.", "changed its shading")


_PART_CODE = {"bevel": ("for m in [m for m in o.modifiers if m.type == 'BEVEL']: o.modifiers.remove(m)",
                        "(not any(m.type == 'BEVEL' for m in o.modifiers), 'it still has a bevel')"),
              "subdivision": ("for m in [m for m in o.modifiers if m.type == 'SUBSURF']: o.modifiers.remove(m)",
                              "(not any(m.type == 'SUBSURF' for m in o.modifiers), 'it is still subdivided')"),
              "modifiers": ("o.modifiers.clear()", "(not o.modifiers, 'it still has modifiers')"),
              "material": ("o.data.materials.clear()",
                           "(not any(s.material for s in o.material_slots), 'it still has a material')")}


def _part_key(part: str) -> str:
    part = part.lower()
    if part.startswith(("subdivision", "subsurf")):
        return "subdivision"
    if part.startswith("modifier"):
        return "modifiers"
    return "material" if part in ("material", "color", "colour") else part


def _ref_ok(ref: str, bridge) -> bool:
    """Whether `ref` can name a Blender object. While routing (no bridge yet: is_command) only words that clearly
    refer to one count, so "rename the file to notes" with Blender merely open isn't taken; once a request is
    already going to Blender, any name may be an object's (a missing one is reported, never guessed)."""
    return bool(_OBJECT_REF.search(ref or "")) or bridge is not None


# ---------- recognizing what was said ----------

# The words Blender requests are made of, for fixing typos in them ("delite evrything in bender"). Only words of four
# letters or more, and only to a word this close, so ordinary words are never "corrected" into commands.
_VOCABULARY = ("delete", "remove", "everything", "blender", "create", "villa", "building", "garden", "terrace",
               "balcony", "garage", "improve", "better", "beautiful", "swimming", "connect", "entrance", "between",
               "rotate", "bigger", "smaller", "wider", "narrower", "walkway", "pathway", "cottage", "mansion", "scene",
               "render", "move", "house", "widen", "enlarge", "shrink", "lengthen", "expand", "paint", "colour",
               "color", "duplicate", "select", "rename", "camera", "light", "pool", "path")
_FORMS = ("s", "es", "d", "ed", "ing", "r", "er", "st", "est", "n")
# Real words one letter away from a command word, never "corrected" into it ("point the camera" is not "paint").
# shortcut: a hand-made list, not a dictionary; add a word here when a real sentence gets mangled.
_REAL_WORDS = {"point", "print", "plant", "place", "pole", "poll", "pull", "bath", "math", "mode", "more", "mouse",
               "horse", "hose", "remote", "tender", "sender", "lender", "render", "letter", "bitter", "butter", "winder",
               "great", "grate", "crate", "creator", "night", "right", "sight", "tight", "fight", "might", "eight",
               "elect", "delta", "label", "scent", "camel", "cameo", "rotation", "colon", "cooler", "pain", "pail",
               "past", "paste", "patch", "pooh", "hours", "house", "movie", "moved", "mover", "garter", "bigger",
               "builder", "delay", "deleted", "removal", "widow", "window", "windows", "linger", "select", "scenes",
               "scones", "shrimp", "expend", "lighter", "lightly", "villain", "villas", "garbage", "blend", "blends", "plain", "readme"}


def fix_typos(text: str) -> str:
    def fix(m):
        word = m.group(0)
        low = word.lower()
        if len(low) < 4 or low in _VOCABULARY or low in _REAL_WORDS or any(
                low in (v + f, v[:-1] + f) or v in (low + f, low[:-1] + f) for v in _VOCABULARY for f in _FORMS):
            return word   # a real word, or one of its forms ("moved", "houses", "wide" of "wider")
        close = difflib.get_close_matches(low, _VOCABULARY, n=1, cutoff=0.8)
        # a slip of a key or two, never a different word ("small" isn't "smaller", "reminder" isn't "render")
        return close[0] if close and close[0][0] == low[0] and abs(len(close[0]) - len(low)) <= 1 else word
    return re.sub(r"[A-Za-z]+", fix, text or "")


def normalize(text: str) -> str:
    """Speech as heard -> the instruction in it: "Okay, make the cube be girl." -> "make the cube bigger";
    "Blender, you have a cube selected. Make the cube two times bigger." -> "Make the cube two times bigger"."""
    t = " ".join(fix_typos(text).split())
    for pattern, fix in _MISHEARD:
        t = pattern.sub(fix, t)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]
    if len(sentences) > 1:
        instructions = [s for s in sentences if _CONCRETE_VERB.search(s)]
        if instructions:
            t = instructions[-1]
    t = _FILLER.sub("", t).strip(" .!?,")
    return re.sub(r"\s+in blender$", "", t, flags=re.I)


def _clauses(text: str) -> list:
    return [c.strip(" ,.") for c in _CLAUSE_SPLIT.split(text) if c.strip(" ,.")]


def _group(m, *names):
    return next((m.group(n) for n in names if m.group(n)), None)


def _match_kit(t: str, session, bridge):
    """[(description, action)] for the commands built on blender_scene.py, or None. Tried before the older
    commands, which would otherwise take "make the cube glow blue" for a color or "delete the bevel from the cube"
    for deleting the cube."""
    if _DESCRIBE.match(t):
        return [("Reading the scene", _describe_action(bridge))]
    if _CHECK.match(t):
        return [("Checking the scene", _check_action(bridge))]
    if _RENDER.match(t):
        preview = bool(re.search(r"\b(?:preview|quick)\b", t, re.I))
        return [("Rendering the scene (this can take a while)", _render_action(bridge, preview))]
    m = _ADD_LIGHT.match(t)
    if m:
        kind = _LIGHT_KINDS[(m.group("kind") or m.group("plain")).lower()]
        code = (f"made = add_light({kind!r})\n"
                "detail = ('sun light of strength %g' % made.data.energy if made.data.type == 'SUN' else "
                "'%s light of %g W' % (made.data.type.lower(), made.data.energy))")
        return [(f"Adding a {kind.lower()} light",
                 _new_object_action(bridge, session, code, "light", "add a light",
                                    "Done — I added a {detail} ({name}), aimed at the scene.",
                                    f"added a {kind.lower()} light"))]
    if _SHOW_ALL.match(t):
        return [("Showing everything", _show_all_action(bridge, session))]
    for pattern, hide in ((_HIDE, True), (_SHOW, False)):
        m = pattern.match(t)
        if m and _ref_ok(_group(m, "ref", "ref2"), bridge):
            change = ("o.hide_set(True)\no.hide_render = True" if hide else
                      "o.hide_set(False)\no.hide_viewport = False\no.hide_render = False")
            verify = ("(not o.visible_get() and o.hide_render, 'it still shows')" if hide else
                      "(o.visible_get() and not o.hide_render, 'it is still hidden (its collection may be hidden)')")
            word = "hidden" if hide else "showing again"
            return [(f"{'Hiding' if hide else 'Showing'} {_group(m, 'ref', 'ref2')}",
                     _edit_action(bridge, session, _group(m, "ref", "ref2"), "hide it" if hide else "show it",
                                  change, verify, "Done — {name} is " + word + " now.",
                                  "hid it" if hide else "showed it"))]
    if _ADD_GROUND.match(t):
        code = "made = add_ground()\ndetail = '%g by %g metres' % tuple(made.dimensions[:2])"
        return [("Adding a floor", _new_object_action(bridge, session, code, "ground", "add a floor",
                                                      "Done — I added a floor ({name}, {detail}) under everything.",
                                                      "added a floor"))]
    m = _ADD_CAMERA.match(t)
    if m:
        return [("Adding a camera", _add_camera_action(bridge, session, m.group("ref")))]
    if _FRAME_ALL.match(t):
        return [("Framing everything in the camera", _aim_camera_action(bridge, session, None))]
    m = _AIM.match(t)
    if m and (_EVERYTHING.match(m.group("ref")) or _ref_ok(m.group("ref"), bridge)):
        ref = None if _EVERYTHING.match(m.group("ref")) else m.group("ref")
        return [(f"Pointing the camera at {ref or 'everything'}", _aim_camera_action(bridge, session, ref))]
    m = _BRIGHTER.match(t)
    if m:
        factor = 1.5 if m.group("how").lower() in ("brighter", "stronger") else 1 / 1.5
        change = ("if o.type != 'LIGHT':\n    raise ValueError(o.name + ' is not a light')\n"
                  f"before = o.data.energy\no.data.energy *= {factor!r}")
        verify = f"(abs(o.data.energy - before * {factor!r}) < 1e-6, '%g W' % o.data.energy)"
        return [(f"Making {m.group('ref')} {m.group('how')}",
                 _edit_action(bridge, session, m.group("ref"), "change the light", change, verify,
                              "Done — {name} is " + m.group("how").lower() + " now ({detail}).",
                              f"made the light {m.group('how').lower()}"))]
    m = _COPIES.match(t)
    if m and _ref_ok(_group(m, "ref", "ref2"), bridge):
        said = _group(m, "n", "n2").lower()
        count = int(_WORD_NUMBERS.get(said, said))
        if 1 <= count <= 50:
            return [(f"Making {count} copies", _copies_action(bridge, session, _group(m, "ref", "ref2"), count))]
    m = _REMOVE_PART.match(t)
    if m and _ref_ok(m.group("ref"), bridge):
        key = _part_key(m.group("part"))
        change, verify = _PART_CODE[key]
        return [(f"Removing the {key} from {m.group('ref')}",
                 _edit_action(bridge, session, m.group("ref"), f"remove the {key}", change, verify,
                              "Done — I removed the " + key + " from {name}.", f"removed the {key}"))]
    m = _RENAME.match(t)
    if m:
        ref = _group(m, "ref", "ref2", "ref3")
        loose = m.group("ref") is None   # "call it X" / "name it X" could mean anything: an object word only
        idiom = loose and re.match(r"(?:a|an|the|quits|off|done|over|good|it)\b", m.group("new"), re.I)
        if not idiom and (_OBJECT_REF.search(ref) if loose else _ref_ok(ref, bridge)):
            new = m.group("new").strip()
            return [(f"Renaming {ref} to {new}",
                     _edit_action(bridge, session, ref, "rename anything", f"o.name = {new!r}",
                                  f"(o.name.startswith({new!r}), o.name)", "Done — it's called {detail} now.",
                                  f"renamed it {new}"))]
    m = _SIZE.match(t) or _SIZE_OF.match(t)
    if m and _ref_ok(m.group("ref"), bridge):
        word = m.group("dim").lower()
        metres = _units(m.group("n"), m.group("u"))
        if metres > 0:
            return [(f"Making {m.group('ref')} {metres:g} m {word}",
                     _size_action(bridge, session, m.group("ref"), _DIMENSION_AXIS[word], metres, word))]
    parsed = _parse_material(t)
    if parsed and _ref_ok(parsed[0], bridge):
        ref, values, said = parsed
        return [(f"Making {ref} {said}", _material_action(bridge, session, ref, values, said))]
    m = _BEVEL.match(t)
    ref = m and _group(m, "ref", "ref2", "ref3", "ref4", "ref5")
    if m and _ref_ok(ref, bridge):
        width = _units(m.group("n"), m.group("u")) if m.group("n") else None
        verify = ("(any(m.type == 'BEVEL' and m.width > 0 for m in o.modifiers) and "
                  "evaluated_vertex_count(o) > len(o.data.vertices), 'its edges still render sharp')")
        return [("Rounding the edges", _edit_action(bridge, session, ref, "bevel anything", f"bevel(o, {width!r})",
                                                    verify, "Done — {name} has rounded edges now.", "bevelled it"))]
    m = _SUBDIVIDE.match(t)
    if m and _ref_ok(_group(m, "ref", "ref2"), bridge):
        levels = int(_group(m, "n", "n2") or 2)
        verify = ("(any(m.type == 'SUBSURF' and m.levels >= 1 for m in o.modifiers) and "
                  "evaluated_vertex_count(o) > len(o.data.vertices), 'the mesh that renders is not any finer')")
        return [("Subdividing", _edit_action(bridge, session, _group(m, "ref", "ref2"), "subdivide anything",
                                             f"subdivide(o, {levels})", verify,
                                             "Done — {name} is subdivided " + f"({levels} levels) now.",
                                             "subdivided it"))]
    m = _SHADE.match(t)
    ref = m and _group(m, "ref", "ref2", "ref3", "ref4")
    if m and _ref_ok(ref, bridge):
        how = (_group(m, "how", "how2", "how3") or "smooth").lower()
        loose = bool(m.group("ref3") or m.group("ref4"))   # "make it smooth": a 6-sided cube needs more than shading
        return [("Changing the shading", _shade_action(bridge, session, ref, how != "flat", loose))]
    m = _ON_FLOOR.match(t) or _DROP.match(t)
    ref = m and _group(m, "ref", "ref2")
    if m and _ref_ok(ref, bridge):
        floor = 0.0 if m.re is _ON_FLOOR else None
        return [("Putting it down", _edit_action(
            bridge, session, ref, "move anything", f"landed = drop_to_floor(o, {floor!r})",
            "(abs(box(o)[0].z - landed) < 1e-3, '%.2f' % landed)",
            "Done — {name} rests on the floor now." if floor == 0.0 else
            "Done — {name} rests on what's under it now (at {detail} m).", "put it down"))]
    m = _ON_TOP.match(t)
    if m and _ref_ok(m.group("ref"), bridge) and _ref_ok(m.group("target"), bridge) and not re.search(
            r"\b(?:floor|ground|left|right|fire|hold|top)$", m.group("target"), re.I):
        return [(f"Putting {m.group('ref')} on {m.group('target')}",
                 _on_top_action(bridge, session, m.group("ref"), m.group("target")))]
    m = _MOVE_BY.match(t)
    if m and _ref_ok(m.group("ref"), bridge):
        direction = _group(m, "dir1", "dir2").lower()
        metres = _units(_group(m, "n1", "n2"), _group(m, "u1", "u2"))
        return [(f"Moving {m.group('ref')} {direction} {metres:g} m",
                 _move_by_action(bridge, session, m.group("ref"), direction, metres))]
    m = _RAISE.match(t)
    if m and _ref_ok(m.group("ref"), bridge):
        direction = "down" if m.group("verb").lower() == "lower" else "up"
        metres = _units(m.group("n"), m.group("u")) if m.group("n") else MOVE_STEP
        return [(f"Moving {m.group('ref')} {direction} {metres:g} m",
                 _move_by_action(bridge, session, m.group("ref"), direction, metres))]
    return None


def is_scene_question(text: str) -> bool:
    """"What's in the scene?" / "anything wrong with the scene?": a question only Blender itself can answer."""
    t = normalize(text)
    return bool(_DESCRIBE.match(t) or _CHECK.match(t))


def _match_one(t: str, session, bridge, *, everyday_only: bool = False):
    """[(description, action)] for one clause, or None. `everyday_only` leaves out undo/redo/save/"again", which
    without "Blender" said could mean any app."""
    if _FOCUS.match(t):
        return [("Switching to Blender", _focus_action())]
    m = _MOVE_NEXT_TO.match(t)
    if m:
        return [(f"Moving {m.group('ref')} next to {m.group('target')}",
                 _move_next_to_action(bridge, session, m.group("ref"), m.group("target")))]
    found = _match_kit(t, session, bridge)
    if found:
        return found
    m = _CREATE.match(t)
    if m:
        shape = m.group("shape")
        return [(f"Creating a {shape}", _create_action(bridge, session, shape))]
    m = _COLOR.match(t)
    if m and _OBJECT_REF.search(m.group("ref")):
        color = m.group("color").lower()
        return [(f"Coloring {m.group('ref')} {color}", _color_action(bridge, session, m.group("ref"), color))]
    m = _RESIZE.match(t)
    if m:
        direction = m.group("direction").lower()
        times = m.group("times")
        times = float(_TIMES_WORDS.get(times.lower(), times)) if times else None
        return [(f"Making {m.group('ref')} {direction}",
                 _resize_action(bridge, session, m.group("ref"), direction, times))]
    for pattern, direction, times in ((_TWICE, "bigger", 2.0), (_HALF, "smaller", 2.0), (_DOUBLE, "bigger", 2.0)):
        m = pattern.match(t)
        if m and _OBJECT_REF.search(m.group("ref")):
            return [(f"Making {m.group('ref')} {times:g} times {direction}",
                     _resize_action(bridge, session, m.group("ref"), direction, times))]
    m = _SCALE.match(t)
    if m and _OBJECT_REF.search(m.group("ref")):
        word = m.group("times").lower()
        amount = float(_TIMES_WORDS.get(word, word))
        shrink = word == "half" or (m.group("way") or "").lower() == "down" or amount < 1
        amount = 1 / amount if amount < 1 else amount
        direction = "smaller" if shrink else "bigger"
        return [(f"Scaling {m.group('ref')}", _resize_action(bridge, session, m.group("ref"), direction, amount))]
    m = _MOVE_DIR.match(t)
    if m:
        direction = m.group("direction").lower()
        return [(f"Moving {m.group('ref')} {direction}",
                 _move_direction_action(bridge, session, m.group("ref"), direction))]
    m = _ROTATE.match(t)
    if m and _OBJECT_REF.search(m.group("ref")):
        degrees = float(m.group("deg") or 90)
        axis = (m.group("axis") or "z").lower()
        return [(f"Rotating {m.group('ref')}", _rotate_action(bridge, session, m.group("ref"), degrees, axis))]
    for pattern, make, label in ((_DELETE, _delete_action, "Deleting"), (_DUPLICATE, _duplicate_action, "Duplicating"),
                                 (_SELECT, _select_action, "Selecting")):
        m = pattern.match(t)
        # "delete the top of the cube" / "remove the texture from it" name a part, not the object: never delete
        # the whole object for those.
        if m and _OBJECT_REF.search(m.group("ref")) and not re.search(r"\b(?:from|of)\b", m.group("ref"), re.I):
            return [(f"{label} {m.group('ref')}", make(bridge, session, m.group("ref")))]
    if everyday_only:
        return None
    if _UNDO.match(t):
        return [("Undoing the last change", _undo_action(bridge, session))]
    if _REDO.match(t):
        return [("Redoing", _redo_action())]
    m = _SAVE.match(t)
    if m:
        return [("Saving the project", _save_action(bridge, m.group("name")))]
    return None


def _match_steps(t: str, session, bridge, everyday_only: bool = False):
    # Clauses first: matched whole, "select the cube and make it red" would read as selecting "the cube and make it red".
    parts = _clauses(t)
    if len(parts) > 1:
        steps = []
        for part in parts:
            found = _match_one(part, session, bridge, everyday_only=everyday_only)
            if found is None:
                break
            steps += found
        else:
            return steps
    return _match_one(t, session, bridge, everyday_only=everyday_only)


def is_command(text: str) -> bool:
    """Whether `text` is made of the everyday object commands here (create / resize / color / move / rotate /
    delete / duplicate / select / switch to Blender). Nothing is run."""
    t = normalize(text)
    return (blender_build.parse(t) is not None or blender_edit.is_edit(t) or
            _match_steps(t, None, None, everyday_only=True) is not None)


def steps_for(text: str, session, bridge):
    """[(description, action)] for `text` if it's made of the common, deterministic Blender commands this module
    knows — each action executes, re-verifies against real Blender state, and returns a clean result string (or
    raises, which ScriptedTask reports as a failure, never a false success). None if nothing recognized here;
    the caller falls back to BlenderComputerTask's free-form AI loop."""
    t = normalize(text)
    if _AGAIN.match(t):
        previous = getattr(session, "last_deterministic_text", None)
        return steps_for(previous, session, bridge) if previous else None
    steps = blender_build.steps_for(t, session, bridge)   # a whole building: planned, staged and checked
    if steps:
        return steps
    steps = blender_edit.steps_for(t, session, bridge)    # an edit of what's there: the pool, a path, "it"
    if steps:
        return steps
    steps = _match_steps(t, session, bridge)
    if steps is not None:
        session.last_deterministic_text = t
    return steps


# ---------- never invent a technical interpretation of vague/incomplete language ----------
_COPULA_COMPLAINT = re.compile(r"^(?:it'?s|that'?s|this is|there'?s|something(?:'?s| is)|things? (?:is|are))\b", re.I)
_VAGUE_TRAILING = re.compile(r"\b(?:a level|totally|somewhat|kind of|sort of)\s*\.?$", re.I)
_CONCRETE_VERB = re.compile(
    r"\b(create|add|make|build|move|put|place|rotate|scale|resize|delete|remove|save|undo|redo|duplicate|copy|"
    r"render|export|set|change|turn|switch|open|close|select|colou?r|paint|texture|material|assign|group|rename|"
    r"align|snap|parent|join|separate|extrude|bevel|subdivide|apply|link|flip|mirror|merge|go (?:to|back)|bring|"
    r"focus|double|spin|insert)\b", re.I)
# Naming Blender itself removes the main source of ambiguity even with a generic verb ("go back to Blender"),
# unlike a bare pronoun ("take it to a level") which still leaves the actual target unclear.
_NAMES_BLENDER = re.compile(r"\bblender\b", re.I)


def looks_concrete(text: str) -> bool:
    """Whether `text` reads like an actual instruction Blender could carry out, rather than a vague or incomplete
    remark ("it's sticky", "take it to a level", "make the cube totally"). When this is False, the caller should
    ask for clarification instead of ever handing it to an AI that might invent a technical-sounding guess."""
    t = (text or "").strip()
    if not t:
        return False
    if _COPULA_COMPLAINT.match(t) and not _CONCRETE_VERB.search(t):
        return False
    if _VAGUE_TRAILING.search(t) and len(t.split()) <= 6:
        return False
    return bool(_CONCRETE_VERB.search(t) or _NAMES_BLENDER.search(t))


def clarification_for(text: str) -> str:
    return ("I'm not sure what you'd like me to do there. Try something like: create a cube, make it two times "
            "bigger, color it red, rotate it 45 degrees, or move it left.")
