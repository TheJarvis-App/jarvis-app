"""The 3D projector: when a question is about something you can see in space, Jarvis shows it as an interactive 3D model.

"Show me a sunflower", "what's inside a computer", "how does a car engine work", "what does DNA look like", "show me a
carbon atom", "how does a gearbox work", "explain a black hole", "show me z = sin(x)·cos(y) in 3D"... open a window with
a holographic projector at the bottom, the model in it, and an explanation above that follows the part you pick.

How a model is chosen:
  1. The planets, the Sun, the Moon and the Earth globe keep their own, older paths (planets.py, earth.py): they are
     handled before this module is ever asked.
  2. The AI turns the question into a small plan (a JSON "spec"): which builder to use and its settings, the words to
     say, and what each part does. Everything it returns is checked here: unknown builders, colours, sizes, shapes and
     expressions are dropped or clamped, so the window only ever draws what this file allowed.
  3. Facts that can be computed are computed, never guessed: an atom's electron shells (from its atomic number), the
     neutrons of its most common isotope, a gear train's ratio, the real geometry of common molecules.
  4. Builders that draw something exact say so; everything else is labelled a simplified illustration.

Nothing here talks to the AI or the window itself: app.py asks (handle_projector_command) and sends what this returns.
"""
import json
import os
import math
import re
import time

GENERATORS = ("parts", "flower", "tree", "helix", "molecule", "atom", "gears", "engine", "computer", "blackhole", "surface",
              "animal", "humanoid", "building", "vehicle", "device", "guitar", "shoe", "heart")
SHAPES = ("sphere", "ellipsoid", "box", "roundbox", "cylinder", "cone", "torus", "capsule", "ring", "ico", "plane", "tube", "lathe", "extrude")
MATERIALS = ("matte", "plastic", "metal", "chrome", "paint", "glass", "tinted", "glow", "organic", "fabric", "skin", "fur", "rubber", "wood", "gloss")
HONEST = "A simplified educational illustration, not an exact reconstruction."
FOLLOW_UP_SECONDS = 10 * 60

# ---------- when a 3D model helps ----------
_NOT_SUBJECTS = (r"picture|photo|image|drawing|painting|video|trailer|episode|movie|film|song|music|playlist|weather|forecast|"
                 r"time|clock|graph|chart|plot of|map|route|directions|calendar|schedule|file|folder|desktop|screen|window|tab|"
                 r"settings|password|messages?|email|inbox|notifications?|news|score|price|stocks?|recipe|code|project|"
                 r"globe|planet|earth|moon|sun|mercury|venus|mars|jupiter|saturn|uranus|neptune|pluto|distance|how far")
_EXPLICIT = re.compile(r"\b(?:3d|3-d|three[- ]d(?:imensional)?|hologram|holographic|projector|(?:a |the )?model of|exploded view|cross[- ]section)\b")
_SHOW = re.compile(r"^(?:can you |could you |please |jarvis,? )*(?:show|display|project|visuali[sz]e|render|build me)(?: me)?(?: (?:a|an|the|some|what))? (?P<subject>[a-z0-9][a-z0-9 '\-,()^*/=+.]{1,70})$")
_LOOKS = re.compile(r"\bwhat (?:does|do) (?:a |an |the )?(?P<subject>[a-z0-9][a-z0-9 '\-]{1,50}?) look like\b")
_INSIDE = re.compile(r"\b(?:what(?:'s| is) inside|the inside of|inside (?:of )?(?:a |an |the )|internal structure|structure of|parts of|anatomy of|"
                     r"how (?:does|do) (?:a |an |the )?(?P<subject>[a-z0-9][a-z0-9 '\-]{1,40}?) work)\b")
_EXPLAIN = re.compile(r"^(?:can you |please )?(?:explain|describe|tell me about) (?:how )?(?:a |an |the )?(?P<subject>[a-z0-9][a-z0-9 '\-]{2,50})$")
_COMPARE = re.compile(r"\b(?:compare|comparing|comparison|versus|vs\.?|differences? between|side by side)\b")
_FOLLOW = re.compile(r"\b(?:its|it|them|this|that|these|those|the (?:model|flower|engine|plant|parts?))\b|^(?:and |now )?(?:show|explain|zoom|label|open|take)\b"
                     r"|\b(?:inside|internal|structure|cross[- ]section|exploded|parts?|label|work|pollinat\w*|compare|side by side)\b")


def wants_model(text: str, previous: dict | None = None) -> bool:
    """Whether to ask for a 3D plan at all (the AI still decides if a model would really help, see 'visual')."""
    t = " ".join(re.sub(r"[?!.]+$", "", (text or "").lower()).split())
    if not t or len(t) > 160:
        return False
    if re.search(rf"\b(?:{_NOT_SUBJECTS})s?\b", t) and not _EXPLICIT.search(t):
        return False
    recent = bool(previous) and time.time() - previous.get("at", 0) < FOLLOW_UP_SECONDS
    if not recent and re.search(r"\b(?:its|it|them)\b", t):
        return False   # "show me its inside" with nothing on the projector: "it" has nothing to point at
    if _EXPLICIT.search(t) or _SHOW.search(t) or _LOOKS.search(t) or _INSIDE.search(t) or _COMPARE.search(t):
        return True
    if recent and _FOLLOW.search(t):
        return True
    return bool(_EXPLAIN.search(t))   # "explain a black hole": the AI says whether a model helps


# ---------- the plan the AI writes ----------
SYSTEM = """You plan 3D models for Jarvis's holographic projector. Answer with ONE JSON object and nothing else.
Decide first: would an interactive 3D model really help with this request? If not (a plain fact, an opinion, an abstract
idea with no shape, anything unsafe), answer {"visual": false}. If the person asks to see a thing (show me, what does it
look like, a 3D model of), it is always visual: build it.
Otherwise:
{"visual": true, "title": "short name", "summary": "one sentence: what the subject is (not the model)",
 "explanation": "2-4 plain sentences that answer the request itself, as you would say it aloud to a curious person; true facts only; never mention the model, the projector or what is shown; no markdown",
 "generator": one of BUILDERS, "params": {...}, "parts": [...only for generator parts...],
 "info": {"Part name": "one sentence: what this part is or does"}, "focus": ["part names to highlight now"],
 "same_model": true only if a follow-up is still about the same subject and needs no new model}
BUILDERS (use the most specific one; "parts" only when nothing else fits):
- flower: params {"petals":3-60,"layers":1-4,"petal_color":"#hex","center_color":"#hex","petal_shape":"round|pointed|long","leaves":0-4,"composite":true|false,"cutaway":true|false}. composite is true only for a flower head made of many tiny florets (sunflower, daisy, dandelion), false for a single flower (rose, tulip, lily). Parts: Petal, Sepal, Stamen, Anther, Filament, Pistil, Stigma, Style, Ovary, Receptacle, Stem, Leaf. cutaway shows the inside (for structure or pollination).
- tree: params {"kind":"oak|pine|palm|birch","leaf_color":"#hex"}. Parts: Crown, Branches, Trunk, Roots.
- helix: params {"kind":"dna|rna","turns":1-4}. Parts: Backbone, Adenine, Thymine (Uracil for rna), Guanine, Cytosine.
- molecule: params {"name":"common name","formula":"H2O"} and, only if it is not a common small molecule, "atoms":[["C",x,y,z]...] in angstroms and "bonds":[[i,j,order]...].
- atom: params {"element":"symbol, Z <= 36"} (shells are computed for you).
- gears: params {"teeth":[driver, next, ...] 2-4 gears, 8-60 teeth each}.
- engine: a four-stroke piston engine (no params).
- computer: a desktop PC in an exploded view (no params).
- blackhole: params {"jets":true|false}.
- animal: params {"kind":"dog|cat|horse|zebra|cow|lion|tiger|wolf|fox|bear|panda|elephant|rabbit|deer|pig|sheep|giraffe|mouse","color":"#hex coat","color2":"#hex markings"} for any four-legged mammal (pick the closest kind; colours optional).
- humanoid: params {"preset":"person|ironman|spiderman|batman|superman|captain_america|hulk|robot|astronaut|knight","color":"#hex","color2":"#hex"} for people, heroes in suits or armour, robots (pick the closest preset).
- building: params {"kind":"house|skyscraper|eiffel|pyramid","floors":1-3,"wall_color":"#hex","roof_color":"#hex"}; the house and the pyramid open to show inside.
- vehicle: params {"kind":"sedan|sports|suv|plane|rocket","color":"#hex"}.
- device: params {"kind":"tv|laptop|phone","color":"#hex"}; each opens into its layers.
- guitar: params {"kind":"acoustic|electric","color":"#hex"}.
- shoe: a sneaker, params {"color":"#hex","color2":"#hex accent"}.
- heart: the human heart, beating, with its chambers and vessels (no params).
- surface: params {"expr":"z as a function of x and y, using + - * / ^ ( ) sin cos tan exp log sqrt abs pi and t for time","range":1-6}.
- parts: sculpt it from shapes, only when no builder fits. "parts":[{"name":"...","shape":"ellipsoid|roundbox|lathe|extrude|sphere|box|cylinder|cone|torus|capsule|ring|plane|tube",
  "size":[...] (ellipsoid [rx,ry,rz]; roundbox [w,h,d]; sphere [r]; box [w,h,d]; cylinder/cone [r,h]; torus/ring [R,r]; capsule [r,h]; plane [w,d]; tube [r] with "path":[[x,y,z]...];
  lathe [1] with "profile":[[radius,y]...] turned round the y axis (bottles, vases, bodies); extrude [depth] with "outline":[[x,y]...] given thickness along z (wings, fins, signs)),
  "at":[x,y,z],"rot":[x,y,z] degrees,"color":"#hex","material":"matte|plastic|metal|chrome|paint|glass|tinted|glow|organic|fabric|skin|fur|rubber|wood|gloss","explode":[x,y,z] (offset in exploded view),
  "repeat":{"count":2-24,"radius":r,"axis":"y"} (copies in a ring)}], 8-18 parts. Sculpt with real proportions: parts touch and overlap
  (no floating pieces), the ground at y 0, the front facing +z, all within a 3x3x3 box; prefer ellipsoid, roundbox, lathe and extrude
  to plain boxes; real colours and materials.
The number ranges in BUILDERS are drawing limits, not facts: never repeat them in the words.
Keep part names short and Title Case. Every name in info and focus must be a part of the chosen builder.
Write the explanation about the subject, never about the model. Wrong: "The model shows the CPU and the RAM." Right: "The
processor runs programs, while memory holds what it is working on right now."
Comparing two subjects ("compare X and Y", "X vs Y", "the difference between X and Y") when seeing both side by side
really helps: {"visual": true, "title": "X vs Y", "summary": "one sentence", "explanation": "2-4 sentences on how they
differ and what they share", "compare": [plan for X, plan for Y]}, each plan {"title","generator","params","parts","info"}
as above (each its own builder).
Follow-ups: if a previous subject is given, first decide whether this request is about THAT subject (it uses it/its/this,
or asks how something about that subject works, like pollination for a flower) or about a NEW subject (it names a
different thing: DNA, a computer, an atom...). A new subject gets its own model, as if nothing came before. A follow-up
about the same subject keeps "visual": true, the same builder, "same_model": true unless it needs a different view (like
the inside), and focus on the parts involved."""


def build_messages(text: str, previous: dict | None) -> list:
    context = ""
    if previous and time.time() - previous.get("at", 0) < FOLLOW_UP_SECONDS:
        context = (f"\nPrevious subject on the projector: {previous.get('title')} (builder {previous.get('generator')}, "
                   f"parts {', '.join(previous.get('part_names', [])[:14])}). Only use it if this request is about that subject.")
    known = catalog(text)
    if len(known) >= 2 and _COMPARE.search(text.lower()):
        context += "\nUse these builders in the comparison: " + "; ".join(f"{t}: {g} {json.dumps(p)}" for t, g, p in known[:2]) + "."
    elif known and not (previous and context and _FOLLOW.search(text.lower()) and not explicit(text)):
        t, g, p = known[0]
        context += f"\nUse the {g} builder with params {json.dumps(p)} (change colours only if the request asks)."
    if explicit(text):
        context += "\nThey asked to see it, so answer with visual true."
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Request: {text}{context}"}]


def parse_reply(raw: str) -> dict | None:
    """The AI's answer as a dict: the first JSON object in it, or None."""
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(raw)):
        depth += {"{": 1, "}": -1}.get(raw[i], 0)
        if depth == 0:
            try:
                return json.loads(raw[start:i + 1])
            except ValueError:
                return None
    return None


# ---------- checking everything the AI wrote ----------
def _text(v, n=400) -> str:
    return " ".join(str(v or "").split())[:n]


def _num(v, lo, hi, default):
    try:
        x = float(v)
        return default if math.isnan(x) else max(lo, min(hi, x))
    except (TypeError, ValueError):
        return default


def _int(v, lo, hi, default):
    return int(round(_num(v, lo, hi, default)))


def _color(v, default="#9fb3c8") -> str:
    v = str(v or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return v.lower()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", v):
        return "#" + "".join(c * 2 for c in v[1:]).lower()
    return default


def _vec(v, n=3, lo=-6.0, hi=6.0, default=0.0) -> list:
    v = v if isinstance(v, (list, tuple)) else []
    return [_num(v[i] if i < len(v) else default, lo, hi, default) for i in range(n)]


def _name(v) -> str:
    return re.sub(r"[^\w '\-()+/]", "", _text(v, 40)).strip()


_EXPR_WORDS = {"sin", "cos", "tan", "exp", "log", "sqrt", "abs", "pi", "x", "y", "t", "e"}


def clean_expression(expr: str) -> str | None:
    """A surface's formula, only if it uses nothing but numbers, x, y, t, operators and the listed functions."""
    e = (expr or "").lower().replace("**", "^").replace("·", "*").replace("×", "*")
    e = re.sub(r"^\s*z\s*=\s*", "", e).strip()
    if not e or len(e) > 120 or not re.fullmatch(r"[0-9a-z+\-*/^()., ]+", e):
        return None
    if any(w not in _EXPR_WORDS for w in re.findall(r"[a-z]+", e)):
        return None
    if e.count("(") != e.count(")"):
        return None
    return e


def _clean_part(p) -> dict | None:
    if not isinstance(p, dict):
        return None
    shape = str(p.get("shape", "")).lower()
    if shape not in SHAPES:
        return None
    part = {"name": _name(p.get("name")) or shape.title(), "shape": shape, "size": _vec(p.get("size"), 3, 0.01, 3, 0.4),
            "at": _vec(p.get("at"), 3, -2.5, 2.5), "rot": _vec(p.get("rot"), 3, -360, 360),
            "color": _color(p.get("color")), "material": p.get("material") if p.get("material") in MATERIALS else "matte"}
    if p.get("explode"):
        part["explode"] = _vec(p.get("explode"), 3, -2.5, 2.5)
    if isinstance(p.get("repeat"), dict):
        r = p["repeat"]
        part["repeat"] = {"count": _int(r.get("count"), 2, 24, 2), "radius": _num(r.get("radius"), 0, 2.5, 0.6),
                          "axis": r.get("axis") if r.get("axis") in ("x", "y", "z") else "y"}
    if shape == "tube":
        path = [ _vec(q, 3, -2.5, 2.5) for q in (p.get("path") or [])[:24] if isinstance(q, (list, tuple)) ]
        if len(path) < 2:
            return None
        part["path"] = path
    elif shape == "lathe":
        profile = [_vec(q, 2, -3, 3) for q in (p.get("profile") or [])[:40] if isinstance(q, (list, tuple))]
        profile = [[abs(r), y] for r, y in profile]
        if len(profile) < 2:
            return None
        part["profile"] = profile
    elif shape == "extrude":
        outline = [_vec(q, 2, -3, 3) for q in (p.get("outline") or [])[:60] if isinstance(q, (list, tuple))]
        if len(outline) < 3:
            return None
        part["outline"] = outline
    return part


def sanitize(spec: dict, question: str = "") -> dict | None:
    """The spec the window will draw: only allowed builders, shapes, sizes, colours and formulas; facts computed."""
    if not isinstance(spec, dict) or not spec.get("visual"):
        return None
    if isinstance(spec.get("compare"), list):
        return _compare(spec, question)
    gen = str(spec.get("generator", "")).lower()
    if gen not in GENERATORS:
        return None
    raw = spec.get("params") if isinstance(spec.get("params"), dict) else {}
    out = {"title": _text(spec.get("title"), 60) or "3D model", "summary": _text(spec.get("summary"), 240),
           "explanation": _text(spec.get("explanation"), 900), "generator": gen, "question": _text(question, 160),
           "params": {}, "info": {}, "facts": [], "exact": False, "same_model": bool(spec.get("same_model"))}
    params, facts = out["params"], out["facts"]
    if gen == "flower":
        params.update(petals=_int(raw.get("petals"), 3, 60, 8), layers=_int(raw.get("layers"), 1, 4, 1),
                      petal_color=_color(raw.get("petal_color"), "#f2c94c"), center_color=_color(raw.get("center_color"), "#6b4423"),
                      petal_shape=raw.get("petal_shape") if raw.get("petal_shape") in ("round", "pointed", "long") else "round",
                      leaves=_int(raw.get("leaves"), 0, 4, 2), composite=bool(raw.get("composite")), cutaway=bool(raw.get("cutaway")) and not raw.get("composite"))
    elif gen == "tree":
        params.update(kind=raw.get("kind") if raw.get("kind") in ("oak", "pine", "palm", "birch") else "oak",
                      leaf_color=_color(raw.get("leaf_color"), "#4f8a3a"))
    elif gen == "helix":
        params.update(kind="rna" if raw.get("kind") == "rna" else "dna", turns=_int(raw.get("turns"), 1, 4, 2))
    elif gen == "molecule":
        known = known_molecule(raw.get("name"), raw.get("formula"))
        if known:
            params.update(name=known["name"], atoms=known["atoms"], bonds=known["bonds"])
            facts.append(f"Geometry: {known['geometry']}")
            out["exact"] = True
        else:
            atoms = [[str(a[0])[:2].title(), *_vec(a[1:], 3, -8, 8)] for a in (raw.get("atoms") or [])[:60]
                     if isinstance(a, (list, tuple)) and len(a) >= 4 and re.fullmatch(r"[A-Za-z]{1,2}", str(a[0]))]
            if len(atoms) < 2:
                return None
            bonds = [[_int(b[0], 0, 59, 0), _int(b[1], 0, 59, 0), _int(b[2] if len(b) > 2 else 1, 1, 3, 1)]
                     for b in (raw.get("bonds") or [])[:80] if isinstance(b, (list, tuple)) and len(b) >= 2]
            params.update(name=_text(raw.get("name"), 40), atoms=atoms, bonds=[b for b in bonds if b[0] < len(atoms) and b[1] < len(atoms) and b[0] != b[1]])
        params["formula"] = _text(raw.get("formula"), 20)
    elif gen == "atom":
        el = element(raw.get("element"))
        if not el:
            return None
        params.update(el)
        out["exact"] = True   # the counts are exact; the picture is the Bohr model, said in the facts
        facts += [f"Atomic number {el['z']}: {el['z']} protons, {el['neutrons']} neutrons (the most common isotope, {el['symbol']}-{el['mass']})",
                  f"Electron shells: {', '.join(map(str, el['shells']))}", "Drawn as the Bohr model: electrons really sit in clouds of probability, not on rings."]
        for i, n in enumerate(el["shells"]):
            out["info"][f"Shell {i + 1}"] = (f"Electron shell {i + 1}: {n} electron{'s' if n != 1 else ''} here, out of the {2 * (i + 1) ** 2} it can hold"
                                             + (". The outermost shell's electrons are the ones that form bonds." if i == len(el["shells"]) - 1 else "."))
    elif gen == "gears":
        teeth = [_int(t, 8, 60, 20) for t in (raw.get("teeth") or [])[:4]] or [12, 36]
        teeth = teeth if len(teeth) >= 2 else teeth + [teeth[0] * 2]
        params["teeth"] = teeth
        ratio = teeth[-1] / teeth[0]
        out["exact"] = True
        facts.append(f"Gear ratio {teeth[-1]}:{teeth[0]} = {ratio:.2f}: the last gear turns {'%.2f' % (1 / ratio)} times for each turn of the first"
                     + (", the other way round" if len(teeth) % 2 == 0 else ", the same way round"))
        for i, n in enumerate(teeth):
            spin = teeth[0] / n
            out["info"][f"Gear {i + 1}"] = (f"The driving gear, with {n} teeth." if i == 0 else
                f"{n} teeth: it turns {spin:.2f} times for each turn of the first gear, {'the other way round' if i % 2 else 'the same way round'}.")
    elif gen == "blackhole":
        params["jets"] = bool(raw.get("jets"))
    elif gen in ("animal", "humanoid", "building", "vehicle", "device", "guitar", "shoe"):
        key, options, default = VARIANTS[gen]
        if gen != "shoe":
            v = str(raw.get(key, "")).lower().replace("-", "_").replace(" ", "_")
            params[key] = v if v in options else default
        for c in ("color", "color2", "wall_color", "roof_color"):
            if raw.get(c):
                params[c] = _color(raw.get(c))
        if gen == "building":
            params["floors"] = _int(raw.get("floors"), 1, 3, 2)
    elif gen == "surface":
        expr = clean_expression(raw.get("expr"))
        if not expr:
            return None
        params.update(expr=expr, range=_num(raw.get("range"), 1, 6, 3))
        out["exact"] = True
        facts.append(f"z = {expr}, for x and y from -{params['range']:g} to {params['range']:g}")
    elif gen == "parts":
        parts = [p for p in (_clean_part(p) for p in (spec.get("parts") or [])[:18]) if p]
        if not parts:
            return None
        out["parts"] = parts
    # what each part does: the curated words where this file has them, the AI's for the rest
    names = part_names(out)
    info = spec.get("info") if isinstance(spec.get("info"), dict) else {}
    for name in names:
        about = (out["info"].get(name) or CURATED.get(gen, {}).get(name)
                 or (ELEMENT_INFO.get(name) if gen == "molecule" else None) or _text(info.get(name), 260))
        if about:
            out["info"][name] = about
    out["focus"] = [n for n in (_name(f) for f in (spec.get("focus") or [])[:6]) if n in names]
    out["part_names"] = names
    out["kicker"] = "3D model" if out["exact"] else "3D illustration"
    if not out["exact"]:
        out["honesty"] = HONEST
    return out


def _compare(spec: dict, question: str) -> dict | None:
    """Two subjects side by side: each plan checked on its own, its parts named after it ("Rose: Petal")."""
    models = [m for m in (sanitize({**p, "visual": True, "compare": None}, "") for p in spec["compare"][:2] if isinstance(p, dict)) if m]
    if len(models) < 2:   # only one could be drawn: show that one, with the comparison's words
        if not models:
            return None
        return {**models[0], "explanation": _text(spec.get("explanation"), 900) or models[0]["explanation"], "question": _text(question, 160)}
    if models[0]["title"].lower() == models[1]["title"].lower():
        models[1]["title"] += " 2"
    out = {"title": _text(spec.get("title"), 60) or f"{models[0]['title']} vs {models[1]['title']}",
           "summary": _text(spec.get("summary"), 240), "explanation": _text(spec.get("explanation"), 900), "generator": "compare",
           "question": _text(question, 160), "params": {"cutaway": any(m["params"].get("cutaway") for m in models)}, "models": models, "info": {}, "facts": [], "part_names": [],
           "exact": all(m["exact"] for m in models), "same_model": bool(spec.get("same_model"))}
    for m in models:
        for n in m["part_names"]:
            key = f"{m['title']}: {n}"
            out["part_names"].append(key)
            if m["info"].get(n):
                out["info"][key] = m["info"][n]
        out["facts"] += [f"{m['title']}: {f}" for f in m["facts"]]
    out["focus"] = [n for n in (_text(f, 80) for f in (spec.get("focus") or [])[:6]) if n in out["part_names"]]
    out["kicker"] = "3D comparison"
    if not out["exact"]:
        out["honesty"] = HONEST
    return out


def part_names(spec: dict) -> list:
    gen = spec["generator"]
    if gen == "parts":
        return list(dict.fromkeys(p["name"] for p in spec.get("parts", [])))
    if gen == "atom":
        return ["Nucleus", "Protons", "Neutrons"] + [f"Shell {i + 1}" for i in range(len(spec["params"]["shells"]))]
    if gen == "gears":
        return [f"Gear {i + 1}" for i in range(len(spec["params"]["teeth"]))]
    if gen == "helix":
        return ["Backbone", "Adenine", "Uracil" if spec["params"]["kind"] == "rna" else "Thymine", "Guanine", "Cytosine"]
    if gen == "molecule":
        return sorted({ELEMENT_NAMES.get(a[0], a[0]) for a in spec["params"]["atoms"]}) + ["Bonds"]
    if gen == "surface":
        return ["Surface"]
    if gen in ("animal", "humanoid", "building", "vehicle", "device", "guitar"):
        return list(_PARTS[gen](spec["params"]))
    return list(CURATED.get(gen, {}).keys())


# ---------- what the parts of the built-in models do (checked wording, not left to the AI) ----------
CURATED = {
    "flower": {
        "Petal": "The coloured leaves of the flower; their colour and scent attract pollinators such as bees.",
        "Sepal": "The small leaf-like parts under the petals that protected the flower while it was a bud.",
        "Stamen": "The male part of the flower: a filament topped by an anther.",
        "Anther": "The tip of a stamen, where pollen is made.",
        "Filament": "The thin stalk that holds an anther up where pollinators brush against it.",
        "Pistil": "The female part of the flower: stigma, style and ovary together.",
        "Stigma": "The sticky top of the pistil that catches pollen: pollination is pollen landing here.",
        "Style": "The tube a pollen grain grows down to reach the ovary.",
        "Ovary": "Holds the ovules; once fertilised they become seeds, and the ovary becomes the fruit.",
        "Receptacle": "The top of the stem that all the parts of the flower grow from.",
        "Stem": "Holds the flower up and carries water and nutrients between the roots and the leaves.",
        "Leaf": "Makes food for the plant from sunlight, water and carbon dioxide (photosynthesis).",
    },
    "tree": {
        "Crown": "The leaves and branches at the top, where the tree makes its food from sunlight.",
        "Branches": "Spread the leaves out to catch as much light as possible.",
        "Trunk": "Holds the tree up and carries water up and sugars down through layers just under the bark.",
        "Roots": "Anchor the tree and take in water and minerals from the soil.",
    },
    "helix": {
        "Backbone": "Alternating sugar and phosphate groups: the two sides of the ladder, twisting into a helix.",
        "Adenine": "A base (A). In DNA it pairs with thymine; in RNA with uracil.",
        "Thymine": "A base (T) found in DNA; it pairs with adenine through two hydrogen bonds.",
        "Uracil": "A base (U) that takes thymine's place in RNA; it pairs with adenine.",
        "Guanine": "A base (G); it pairs with cytosine through three hydrogen bonds.",
        "Cytosine": "A base (C); it pairs with guanine.",
    },
    "engine": {
        "Cylinder": "The chamber the piston moves up and down in; the fuel burns at its top.",
        "Piston": "Pushed down by the burning fuel and air; it turns that push into motion.",
        "Connecting Rod": "Links the piston to the crankshaft.",
        "Crankshaft": "Turns the piston's up-and-down motion into rotation that drives the wheels.",
        "Intake Valve": "Opens on the intake stroke to let the fuel and air mixture in.",
        "Exhaust Valve": "Opens on the exhaust stroke to let the burnt gases out.",
        "Spark Plug": "Makes the spark that ignites the compressed mixture at the start of the power stroke.",
    },
    "computer": {
        "Case": "Holds and protects everything, and guides the air that cools it.",
        "Motherboard": "The main circuit board: every other part plugs into it and talks through it.",
        "CPU": "The processor: it runs the programs, one instruction after another, billions of times a second.",
        "CPU Cooler": "Draws heat away from the processor so it can keep running fast.",
        "Memory (RAM)": "Fast, temporary storage for what the computer is working on right now; it empties when the power goes off.",
        "Graphics Card (GPU)": "Draws everything you see on screen, and runs many small calculations in parallel.",
        "Storage (SSD)": "Keeps your files and programs, even when the computer is off.",
        "Power Supply": "Turns the electricity from the wall into the steady voltages the parts need.",
    },
    "blackhole": {
        "Event Horizon": "The boundary beyond which nothing, not even light, can escape.",
        "Photon Sphere": "Where gravity bends light into orbit around the black hole; it shapes the bright ring in images.",
        "Accretion Disk": "Gas and dust spiralling in, heated by friction until it glows.",
        "Jets": "In some black holes, matter is flung out in narrow beams along the spin axis, close to the speed of light.",
    },
    "atom": {
        "Nucleus": "The tiny, dense centre of the atom, holding nearly all of its mass.",
        "Protons": "Positively charged; their number (the atomic number) decides which element it is.",
        "Neutrons": "No charge; they hold the nucleus together with the protons.",
    },
    "surface": {"Surface": "Each point's height is z, worked out from its x and y."},
    "gears": {},
}

# ---------- elements (Z 1-36): symbol, name, mass number of the most common isotope ----------
_ELEMENTS = [("H", "Hydrogen", 1), ("He", "Helium", 4), ("Li", "Lithium", 7), ("Be", "Beryllium", 9), ("B", "Boron", 11),
             ("C", "Carbon", 12), ("N", "Nitrogen", 14), ("O", "Oxygen", 16), ("F", "Fluorine", 19), ("Ne", "Neon", 20),
             ("Na", "Sodium", 23), ("Mg", "Magnesium", 24), ("Al", "Aluminium", 27), ("Si", "Silicon", 28), ("P", "Phosphorus", 31),
             ("S", "Sulfur", 32), ("Cl", "Chlorine", 35), ("Ar", "Argon", 40), ("K", "Potassium", 39), ("Ca", "Calcium", 40),
             ("Sc", "Scandium", 45), ("Ti", "Titanium", 48), ("V", "Vanadium", 51), ("Cr", "Chromium", 52), ("Mn", "Manganese", 55),
             ("Fe", "Iron", 56), ("Co", "Cobalt", 59), ("Ni", "Nickel", 58), ("Cu", "Copper", 63), ("Zn", "Zinc", 64),
             ("Ga", "Gallium", 69), ("Ge", "Germanium", 74), ("As", "Arsenic", 75), ("Se", "Selenium", 80), ("Br", "Bromine", 79),
             ("Kr", "Krypton", 84)]
ELEMENT_NAMES = {s: n for s, n, _ in _ELEMENTS}
ELEMENT_INFO = {   # the atoms of a molecule model: true of them in any common molecule they're shown in
    "Hydrogen": "Hydrogen atoms (white): each shares its one electron with a neighbour in a covalent bond.",
    "Carbon": "Carbon atoms (dark grey): each forms four bonds in total.",
    "Oxygen": "Oxygen atoms (red): each forms two bonds in total and keeps two lone pairs of electrons.",
    "Nitrogen": "Nitrogen atoms (blue): each usually forms three bonds and keeps one lone pair of electrons.",
    "Bonds": "Shared pairs of electrons holding the atoms together; two sticks show a double bond, three a triple bond.",
}


def shells(z: int) -> list:
    """Electrons per shell, filling orbitals in the usual (Madelung) order, with chromium's and copper's known exceptions."""
    order = [(1, 2), (2, 2), (2, 6), (3, 2), (3, 6), (4, 2), (3, 10), (4, 6)]   # (shell, capacity) for 1s 2s 2p 3s 3p 4s 3d 4p
    counts, left = {}, z
    for n, cap in order:
        take = min(cap, left)
        counts[n] = counts.get(n, 0) + take
        left -= take
    if z in (24, 29):   # Cr [Ar] 3d5 4s1, Cu [Ar] 3d10 4s1
        counts[3] += 1; counts[4] -= 1
    return [counts[n] for n in sorted(counts) if counts[n]]


def element(v) -> dict | None:
    v = str(v or "").strip()
    for z, (sym, name, mass) in enumerate(_ELEMENTS, 1):
        if v.lower() in (sym.lower(), name.lower(), str(z)) or (name == "Aluminium" and v.lower() == "aluminum"):
            return {"z": z, "symbol": sym, "element": name, "mass": mass, "neutrons": mass - z, "shells": shells(z)}
    return None


# ---------- common molecules with real geometry (angstroms) ----------
def _tetra(center, r):
    k = r / math.sqrt(3)
    return [[center[0] + a * k, center[1] + b * k, center[2] + c * k] for a, b, c in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1))]


def _water():
    a = math.radians(104.45 / 2); r = 0.9572
    return {"atoms": [["O", 0, 0, 0], ["H", r * math.sin(a), -r * math.cos(a), 0], ["H", -r * math.sin(a), -r * math.cos(a), 0]],
            "bonds": [[0, 1, 1], [0, 2, 1]], "geometry": "bent, H-O-H angle 104.5 degrees, O-H 0.96 angstrom"}


def _methane():
    hs = _tetra((0, 0, 0), 1.087)
    return {"atoms": [["C", 0, 0, 0]] + [["H", *h] for h in hs], "bonds": [[0, i, 1] for i in range(1, 5)],
            "geometry": "tetrahedral, H-C-H angle 109.5 degrees, C-H 1.09 angstrom"}


def _ammonia():
    r, ang = 1.012, math.radians(106.7)
    # three H below N at equal angles: their tilt from the axis follows from the H-N-H angle
    tilt = math.asin(math.sqrt((2 - 2 * math.cos(ang)) / 3))
    hs = [[r * math.sin(tilt) * math.cos(t), -r * math.cos(tilt), r * math.sin(tilt) * math.sin(t)] for t in (0, 2 * math.pi / 3, 4 * math.pi / 3)]
    return {"atoms": [["N", 0, 0, 0]] + [["H", *h] for h in hs], "bonds": [[0, i, 1] for i in (1, 2, 3)],
            "geometry": "trigonal pyramid, H-N-H angle 106.7 degrees, N-H 1.01 angstrom"}


def _co2():
    return {"atoms": [["C", 0, 0, 0], ["O", 1.16, 0, 0], ["O", -1.16, 0, 0]], "bonds": [[0, 1, 2], [0, 2, 2]],
            "geometry": "linear, O=C=O, C=O 1.16 angstrom"}


def _diatomic(el, d, order, text):
    return lambda: {"atoms": [[el, -d / 2, 0, 0], [el, d / 2, 0, 0]], "bonds": [[0, 1, order]], "geometry": text}


def _benzene():
    atoms, bonds = [], []
    for i in range(6):
        a = math.radians(60 * i)
        atoms.append(["C", 1.39 * math.cos(a), 0, 1.39 * math.sin(a)])
    for i in range(6):
        a = math.radians(60 * i)
        atoms.append(["H", 2.48 * math.cos(a), 0, 2.48 * math.sin(a)])
        bonds += [[i, (i + 1) % 6, 2 if i % 2 == 0 else 1], [i, i + 6, 1]]
    return {"atoms": atoms, "bonds": bonds, "geometry": "flat hexagon, C-C 1.39 angstrom (between single and double), C-H 1.09 angstrom"}


_MOLECULES = {
    "water": ("Water", ("h2o",), _water), "methane": ("Methane", ("ch4",), _methane), "ammonia": ("Ammonia", ("nh3",), _ammonia),
    "carbon dioxide": ("Carbon dioxide", ("co2",), _co2), "benzene": ("Benzene", ("c6h6",), _benzene),
    "oxygen": ("Oxygen", ("o2",), _diatomic("O", 1.21, 2, "two oxygen atoms with a double bond, 1.21 angstrom")),
    "nitrogen": ("Nitrogen", ("n2",), _diatomic("N", 1.10, 3, "two nitrogen atoms with a triple bond, 1.10 angstrom")),
    "hydrogen": ("Hydrogen", ("h2",), _diatomic("H", 0.74, 1, "two hydrogen atoms, 0.74 angstrom apart")),
}


def known_molecule(name, formula) -> dict | None:
    n, f = str(name or "").strip().lower(), str(formula or "").strip().lower()
    for key, (title, formulas, make) in _MOLECULES.items():
        if n in (key, title.lower()) or f in formulas:
            return {"name": title, **make()}
    return None



# ---------- the builders for everyday things: their variants and parts (as projector/living.js and made.js draw them) ----------
ANIMAL_KINDS = ("dog", "cat", "horse", "zebra", "cow", "lion", "tiger", "wolf", "fox", "bear", "panda", "elephant", "rabbit",
                "deer", "pig", "sheep", "giraffe", "mouse")
HUMANOID_PRESETS = ("person", "ironman", "spiderman", "batman", "superman", "captain_america", "hulk", "robot", "astronaut", "knight")
VARIANTS = {"animal": ("kind", ANIMAL_KINDS, "dog"), "humanoid": ("preset", HUMANOID_PRESETS, "person"),
            "building": ("kind", ("house", "skyscraper", "eiffel", "pyramid"), "house"),
            "vehicle": ("kind", ("sedan", "sports", "suv", "plane", "rocket"), "sedan"),
            "device": ("kind", ("tv", "laptop", "phone"), "tv"), "guitar": ("kind", ("acoustic", "electric"), "acoustic"),
            "shoe": ("kind", (), None)}
_HOOVES = {"horse", "zebra", "cow", "deer", "pig", "sheep", "giraffe"}


def _animal_parts(p):
    k = p["kind"]
    out = ["Head", "Eyes", "Ears"] + ([] if k == "elephant" else ["Muzzle", "Nose"]) + ["Neck", "Body", "Legs"]
    out.append("Hooves" if k in _HOOVES else "Feet" if k == "elephant" else "Paws")
    out.append("Tail")
    out += {"lion": ["Mane"], "horse": ["Mane"], "zebra": ["Mane"], "giraffe": ["Mane", "Ossicones"], "cow": ["Horns"],
            "deer": ["Antlers"], "elephant": ["Trunk", "Tusks"], "sheep": ["Wool"]}.get(k, [])
    return out


def _humanoid_parts(p):
    k = p["preset"]
    armour = k in ("ironman", "robot", "knight")
    head = {"ironman": "Helmet", "spiderman": "Mask", "batman": "Cowl", "captain_america": "Helmet", "astronaut": "Helmet", "knight": "Helmet"}.get(k, "Head")
    out = [head, "Eyes", "Neck", "Chest Plate" if k in ("ironman", "knight") else "Torso", "Arms",
           "Gloves" if armour or k in ("spiderman", "batman", "captain_america") else "Hands", "Legs",
           "Boots" if armour or k in ("spiderman", "batman", "superman", "captain_america") else "Feet"]
    return out + {"person": ["Hair", "Trousers"], "superman": ["Hair", "Emblem", "Cape", "Belt"], "hulk": ["Hair", "Shorts"],
                  "ironman": ["Arc Reactor", "Abdomen Plates", "Repulsors", "Boot Jets"], "spiderman": ["Spider Emblem", "Web Shooters"],
                  "batman": ["Jaw", "Bat Emblem", "Cape", "Utility Belt"], "captain_america": ["Jaw", "Star", "Stripes", "Shield", "Belt"],
                  "robot": ["Antenna", "Chest Panel"], "astronaut": ["Visor", "Life Support Pack", "Mission Patch"],
                  "knight": ["Plume", "Sword", "Shield"]}.get(k, [])


_PARTS = {
    "animal": _animal_parts,
    "humanoid": _humanoid_parts,
    "building": lambda p: {"house": ["Roof", "Walls", "Windows", "Door", "Chimney", "Floors", "Rooms", "Stairs", "Foundation", "Garden"],
                           "skyscraper": ["Tower", "Lobby", "Core", "Crown", "Spire", "Plaza"],
                           "eiffel": ["Legs", "Lattice", "Arches", "First Floor", "Second Floor", "Top Floor", "Antenna"],
                           "pyramid": ["Casing", "Capstone", "King's Chamber", "Queen's Chamber", "Grand Gallery", "Subterranean Chamber", "Passages", "Plateau"]}[p["kind"]],
    "vehicle": lambda p: {"plane": ["Fuselage", "Cockpit", "Wings", "Engines", "Tail Fin", "Stabilizers", "Landing Gear"],
                          "rocket": ["Payload Fairing", "Payload", "Second Stage", "Interstage", "First Stage", "Fins", "Engines", "Exhaust"]}.get(
        p["kind"], ["Body", "Cabin", "Wheels", "Engine", "Interior", "Headlights", "Taillights"]),
    "device": lambda p: {"tv": ["Screen", "Front Glass", "Backlight", "Mainboard", "Power Supply", "Speakers", "Back Cover", "Frame", "Stand"],
                         "laptop": ["Screen", "Keyboard", "Trackpad", "Battery", "Motherboard", "Fan", "Case"],
                         "phone": ["Screen", "Frame", "Battery", "Logic Board", "Cameras", "Back Glass"]}[p["kind"]],
    "guitar": lambda p: ["Body", "Sound Hole" if p["kind"] == "acoustic" else "Pickups"] + ([] if p["kind"] == "acoustic" else ["Knobs"])
    + ["Bridge", "Strings", "Neck", "Fretboard", "Frets", "Headstock", "Tuning Pegs"],
}

CURATED.update({
    "animal": {
        "Head": "Holds the brain and the main senses: eyes, ears, nose and mouth all sit close to it.",
        "Eyes": "Two forward-and-sideways eyes; hunters' eyes face more forward to judge distance, prey animals' more sideways to watch all round.",
        "Ears": "Catch sound and turn toward it; many animals move each ear on its own to find where a sound comes from.",
        "Muzzle": "The snout: it holds the jaws and teeth and a long nasal passage for smelling.",
        "Nose": "Damp skin on the nose helps catch scent molecules; many mammals smell far better than people do.",
        "Neck": "Carries the head and lets it turn; almost every mammal has seven neck vertebrae, from a mouse to a giraffe.",
        "Body": "The chest holds the heart and lungs, the belly the stomach and gut; the spine runs along the top.",
        "Legs": "Four legs carry the weight; most mammals that run walk on their toes, so the 'knee' bending backwards is really an ankle.",
        "Paws": "Soft pads cushion each step and grip; claws help with digging, climbing or holding on.",
        "Hooves": "A hard covering of keratin, like a thick toenail, that the animal walks on.",
        "Feet": "Broad padded feet spread a heavy body's weight over the ground.",
        "Tail": "Helps with balance and turning, swats insects, and signals mood to others.",
        "Mane": "Long hair along the neck or round the face; it can protect the neck and signal health to rivals and mates.",
        "Horns": "Permanent bone cores covered in keratin, kept for life, used for defence and display.",
        "Ossicones": "Skin-covered bony knobs on a giraffe's head; males use them when they spar with their necks.",
        "Antlers": "Bone that grows fresh every year and is shed in winter; males use them in fights for mates.",
        "Trunk": "The nose and upper lip joined into one long, boneless limb with tens of thousands of muscles: it breathes, smells, drinks and grabs.",
        "Tusks": "Very long incisor teeth that keep growing; used for digging, lifting and defence.",
        "Wool": "A thick fleece of crimped fibres that traps air and keeps the animal warm and dry.",
    },
    "humanoid": {
        "Head": "Holds the brain and the senses: sight, hearing, smell and taste.",
        "Helmet": "Protects the head; in a suit it often holds the displays and sensors too.",
        "Mask": "Hides the wearer's identity and covers the whole head.",
        "Cowl": "A hood-like mask over the head and upper face, leaving the mouth and chin bare.",
        "Eyes": "Where the wearer sees out: lenses or slits, sometimes with displays behind them.",
        "Neck": "Carries the head and lets it turn and nod.",
        "Torso": "The chest and belly, which protect the heart, lungs and the organs of digestion.",
        "Chest Plate": "The armour over the chest, protecting the heart and lungs.",
        "Arms": "Shoulder, upper arm, elbow and forearm: they reach, lift and carry.",
        "Hands": "Each hand has 27 bones and an opposable thumb for gripping.",
        "Gloves": "Cover and protect the hands while keeping them able to grip.",
        "Legs": "Hip, thigh, knee and shin: they carry the body's weight and walk, run and jump.",
        "Feet": "Each foot has 26 bones and arches that act like springs when walking.",
        "Boots": "Protect the feet and lower legs.",
        "Hair": "Hair on the head helps keep it warm and shields it from the sun.",
        "Trousers": "Clothing for the hips and legs.",
        "Shorts": "Clothing for the hips and thighs.",
        "Arc Reactor": "The glowing power source in Iron Man's chest that runs the whole suit.",
        "Abdomen Plates": "Overlapping armour plates over the belly, so the suit can bend at the waist.",
        "Repulsors": "Iron Man's glowing palm emitters: they help him fly and steer, and fire as weapons.",
        "Boot Jets": "Iron Man's boot thrusters, which lift the suit and let it fly.",
        "Spider Emblem": "The spider on Spider-Man's chest, his symbol.",
        "Web Shooters": "Devices on Spider-Man's wrists that fire his webs; in the original comics he built them himself.",
        "Bat Emblem": "The bat on Batman's chest, his symbol.",
        "Jaw": "The part of the face left uncovered by the mask.",
        "Cape": "A long cloak from the shoulders, the classic mark of a superhero.",
        "Utility Belt": "Batman's belt of pouches holding his gadgets.",
        "Belt": "Holds the suit together at the waist.",
        "Emblem": "Superman's 'S' shield, the crest of his Kryptonian family, the House of El.",
        "Star": "The white star on Captain America's chest.",
        "Stripes": "Red and white stripes across Captain America's suit, from the US flag.",
        "Shield": "A round or kite-shaped shield carried on the arm to block blows.",
        "Antenna": "Sends and receives radio signals so the robot can be talked to.",
        "Chest Panel": "Status lights showing what the robot is doing.",
        "Visor": "A gold-coated visor that reflects the Sun's glare and heat.",
        "Life Support Pack": "The backpack that supplies oxygen, removes carbon dioxide, and cools the suit.",
        "Mission Patch": "A badge for the mission and the country flying it.",
        "Plume": "Feathers on top of the helmet, so a knight could be told apart in battle.",
        "Sword": "A double-edged steel blade with a cross-guard to protect the hand.",
    },
    "building": {
        "Roof": "Sloped so rain and snow run off; its overhang keeps water away from the walls.",
        "Walls": "Carry the floors and the roof, and keep out wind, rain and cold.",
        "Windows": "Let in light and air; double glazing traps a layer of gas to keep heat in.",
        "Door": "The way in, sealed against draughts when shut.",
        "Chimney": "Carries smoke from a fireplace or boiler up and away above the roof.",
        "Floors": "Each storey's floor rests on beams that pass its load to the walls.",
        "Rooms": "Inside walls divide the house into rooms for living, cooking and sleeping.",
        "Stairs": "Connect the floors; each step is usually about 18 cm high.",
        "Foundation": "Concrete under the walls that spreads the building's weight into the ground.",
        "Garden": "The plot around the house.",
        "Tower": "A steel or concrete frame with glass walls hung on it like a curtain.",
        "Lobby": "The entrance hall at street level.",
        "Core": "The stiff concrete heart of the tower, holding the lifts and stairs and resisting the wind.",
        "Crown": "The top of the tower, often holding machinery and water tanks.",
        "Spire": "The tall point on top, with a light to warn aircraft.",
        "Plaza": "The open public space around the tower's base.",
        "Lattice": "Thousands of wrought-iron bars braced in triangles, light but stiff against the wind.",
        "Arches": "The arches between the legs, added mostly for looks.",
        "First Floor": "The first platform, 57 metres up.",
        "Second Floor": "The second platform, 115 metres up.",
        "Top Floor": "The top platform, 276 metres up, with Gustave Eiffel's private apartment.",
        "Antenna": "Broadcasting antennas that bring the tower to about 330 metres.",
        "Casing": "Once covered in polished white limestone; most of it was taken away for other buildings.",
        "Capstone": "The pointed top stone of the pyramid; the original is missing.",
        "King's Chamber": "A granite room deep in the pyramid holding Khufu's stone sarcophagus.",
        "Queen's Chamber": "A smaller chamber below the King's; despite its name, it was not for a queen.",
        "Grand Gallery": "A tall sloping passage, 47 metres long, leading up to the King's Chamber.",
        "Subterranean Chamber": "An unfinished room cut into the bedrock below the pyramid.",
        "Passages": "Narrow sloping corridors connecting the chambers to the entrance.",
        "Plateau": "The Giza plateau, the rocky ground the pyramids stand on.",
        "Legs": "Four great curved legs that carry the tower's weight down to its foundations.",
    },
    "vehicle": {
        "Body": "A strong steel shell, with crumple zones at the front and back that absorb a crash.",
        "Cabin": "The passenger space with its windows; the roof and pillars form a cage that protects the people inside.",
        "Wheels": "Rubber tyres on metal rims; the tread grips the road and pushes water away.",
        "Engine": "Burns fuel to turn the crankshaft, which the gearbox passes to the wheels.",
        "Interior": "The seats, steering wheel and dashboard.",
        "Headlights": "Light the road ahead and let others see the car.",
        "Taillights": "Red lights at the back that brighten when the car brakes.",
        "Fuselage": "The long tube holding the passengers and cargo; it is pressurised at cruising height.",
        "Cockpit": "Where the pilots fly the plane.",
        "Wings": "Shaped and angled to push air down, which lifts the plane; they also hold most of the fuel.",
        "Engines": "Turbofans: a big fan pushes air backwards to drive the plane forward.",
        "Tail Fin": "Keeps the plane flying straight; its rudder turns the nose left and right.",
        "Stabilizers": "Small wings at the tail that keep the nose steady; their elevators tilt it up and down.",
        "Landing Gear": "Wheels and shock absorbers for take-off and landing, folded away in flight.",
        "Payload Fairing": "The nose cone that protects the satellite on the way up, then splits off in space.",
        "Payload": "What the rocket is carrying to space, here a satellite with solar panels.",
        "Second Stage": "Takes over in space and pushes the payload into orbit.",
        "Interstage": "Joins the stages and lets them separate cleanly.",
        "First Stage": "The biggest stage, with most of the fuel; it lifts the rocket through the thick lower air.",
        "Fins": "Keep the rocket pointing straight while it climbs through the air.",
        "Exhaust": "Hot gas thrown out of the nozzles at high speed; pushing it down pushes the rocket up.",
    },
    "device": {
        "Screen": "The panel that makes the picture: millions of pixels, each made of red, green and blue parts.",
        "Front Glass": "Protects the screen; on a phone it also senses your touch.",
        "Backlight": "LEDs and a diffuser that shine an even white light through the LCD panel.",
        "Mainboard": "Turns the video signal into the picture and runs the TV's software.",
        "Power Supply": "Turns mains electricity into the low voltages the electronics need.",
        "Speakers": "Turn electrical signals into sound.",
        "Back Cover": "Encloses and protects the electronics.",
        "Frame": "Holds the layers together and makes the device rigid.",
        "Stand": "Holds the screen up.",
        "Keyboard": "Each key presses a switch the computer reads as a letter or command.",
        "Trackpad": "Senses your finger's position and gestures through tiny changes in electric charge.",
        "Battery": "Lithium-ion cells that store energy and power the device away from a socket.",
        "Motherboard": "The main circuit board, holding the processor and memory and connecting everything else.",
        "Fan": "Blows heat out of the case so the processor doesn't overheat.",
        "Case": "The aluminium shell that holds and protects everything.",
        "Logic Board": "A tiny motherboard holding the processor, memory and storage.",
        "Cameras": "Several cameras with different lenses: wide, ultra-wide and zoom.",
        "Back Glass": "Glass on the back lets wireless charging reach the coil inside.",
    },
    "guitar": {
        "Body": "The hollow wooden body; its top vibrates with the strings and makes the sound louder.",
        "Sound Hole": "Lets the sound out of the body.",
        "Pickups": "Magnets wrapped in wire that turn the strings' vibration into an electric signal for an amplifier.",
        "Knobs": "Control the volume and tone.",
        "Bridge": "Anchors the strings to the body and passes their vibration into it.",
        "Strings": "Six steel strings; the thicker and looser a string, the lower its note.",
        "Neck": "The long wooden arm that holds the fretboard; a steel rod inside stops it bending.",
        "Fretboard": "Where the fingers press the strings to change the notes.",
        "Frets": "Metal strips across the fretboard; each one raises the note by a semitone.",
        "Headstock": "The top of the neck, holding the tuning pegs.",
        "Tuning Pegs": "Turn to tighten or loosen each string and tune it.",
    },
    "shoe": {
        "Outsole": "The rubber bottom that grips the ground and resists wear.",
        "Midsole": "Foam that cushions each step and gives some energy back.",
        "Upper": "The fabric and mesh over the foot: light, breathable, and shaped to hold it.",
        "Collar": "The padded opening round the ankle.",
        "Tongue": "A padded flap under the laces that stops them pressing on the foot.",
        "Toe Cap": "Reinforces the front, where the shoe wears fastest.",
        "Heel Counter": "A stiff cup round the heel that holds it steady.",
        "Side Stripe": "The brand's stripe, which also stiffens the side of the shoe.",
        "Laces": "Pull the upper snugly round the foot.",
    },
    "heart": {
        "Heart Wall": "Thick cardiac muscle that squeezes about 100,000 times a day without tiring.",
        "Right Atrium": "Collects oxygen-poor blood returning from the body.",
        "Left Atrium": "Collects oxygen-rich blood coming from the lungs.",
        "Right Ventricle": "Pumps oxygen-poor blood to the lungs.",
        "Left Ventricle": "The strongest chamber: it pumps oxygen-rich blood to the whole body, so its wall is the thickest.",
        "Septum": "The wall that keeps the heart's left and right sides apart.",
        "Valves": "Four one-way valves that stop blood flowing backwards; their closing makes the 'lub-dub' sound.",
        "Aorta": "The body's largest artery, carrying blood from the left ventricle to everywhere else.",
        "Pulmonary Artery": "Carries oxygen-poor blood from the right ventricle to the lungs.",
        "Vena Cava": "The two great veins that bring blood back from the body to the right atrium.",
        "Pulmonary Veins": "Bring oxygen-rich blood from the lungs to the left atrium.",
        "Coronary Arteries": "Feed the heart muscle itself; a blockage here causes a heart attack.",
        "Blood Flow": "Blue: oxygen-poor blood going to the lungs. Red: oxygen-rich blood going to the body.",
    },
})


# ---------- subjects recognised without asking the AI which builder: reliable, and the AI still writes the words ----------
_CATALOG = [   # (pattern, title, generator, params): the first match wins, so the specific comes before the general
    (r"car engine|engine of a car|piston engine|combustion engine|\bengines? work", "Car Engine", "engine", {}),
    (r"laptop|notebook computer|macbook", "Laptop", "device", {"kind": "laptop"}),
    (r"smart ?phones?|iphone|android phone|mobile phone|cell ?phone|\bphones?\b", "Smartphone", "device", {"kind": "phone"}),
    (r"\btvs?\b|television|flat[- ]?screen|\bmonitor\b", "Television", "device", {"kind": "tv"}),
    (r"\bcomputers?\b|desktop pc|\bpc\b", "Computer", "computer", {}),
    (r"electric guitar", "Electric Guitar", "guitar", {"kind": "electric"}),
    (r"\bguitars?\b", "Acoustic Guitar", "guitar", {"kind": "acoustic"}),
    (r"sneakers?|trainers?|running shoes?|\bshoes?\b", "Sneaker", "shoe", {}),
    (r"\bhearts?\b", "Human Heart", "heart", {}),
    (r"eiffel", "Eiffel Tower", "building", {"kind": "eiffel"}),
    (r"pyramids?", "Great Pyramid of Giza", "building", {"kind": "pyramid"}),
    (r"skyscrapers?|tall building|office tower|burj|empire state", "Skyscraper", "building", {"kind": "skyscraper"}),
    (r"\bhouses?\b|\bhomes?\b|cottage", "House", "building", {"kind": "house", "floors": 2}),
    (r"rockets?|spaceship|space ?craft|falcon 9", "Rocket", "vehicle", {"kind": "rocket"}),
    (r"air ?planes?|aeroplanes?|airliners?|\bplanes?\b|\bjets?\b|boeing|airbus", "Airliner", "vehicle", {"kind": "plane"}),
    (r"sports car|ferrari|lamborghini|porsche|race car|racing car|supercar", "Sports Car", "vehicle", {"kind": "sports"}),
    (r"\bsuvs?\b|\bjeep\b|4x4", "SUV", "vehicle", {"kind": "suv"}),
    (r"\bcars?\b|automobile|sedan|tesla", "Car", "vehicle", {"kind": "sedan"}),
    (r"iron ?man|tony stark", "Iron Man", "humanoid", {"preset": "ironman"}),
    (r"spider[- ]?man|peter parker", "Spider-Man", "humanoid", {"preset": "spiderman"}),
    (r"batman|bruce wayne", "Batman", "humanoid", {"preset": "batman"}),
    (r"superman|clark kent", "Superman", "humanoid", {"preset": "superman"}),
    (r"captain america|steve rogers", "Captain America", "humanoid", {"preset": "captain_america"}),
    (r"\bhulk\b", "Hulk", "humanoid", {"preset": "hulk"}),
    (r"astronauts?|space ?suit|cosmonaut", "Astronaut", "humanoid", {"preset": "astronaut"}),
    (r"\brobots?\b|cyborg", "Robot", "humanoid", {"preset": "robot"}),
    (r"\bknights?\b|suit of armou?r", "Knight", "humanoid", {"preset": "knight"}),
    (r"\bdogs?\b|pupp(?:y|ies)|labrador|retriever|beagle|poodle|bulldog|husky|corgi", "Dog", "animal", {"kind": "dog"}),
    (r"\bcats?\b|kittens?|kitty", "Cat", "animal", {"kind": "cat"}),
    (r"\bzebras?\b", "Zebra", "animal", {"kind": "zebra"}),
    (r"\bhorses?\b|\bpon(?:y|ies)\b|stallion", "Horse", "animal", {"kind": "horse"}),
    (r"\bcows?\b|cattle|\bbulls?\b|\bcalf\b", "Cow", "animal", {"kind": "cow"}),
    (r"\blions?\b", "Lion", "animal", {"kind": "lion"}),
    (r"\btigers?\b", "Tiger", "animal", {"kind": "tiger"}),
    (r"\bwol(?:f|ves)\b", "Wolf", "animal", {"kind": "wolf"}),
    (r"\bfox(?:es)?\b", "Fox", "animal", {"kind": "fox"}),
    (r"\bpandas?\b", "Panda", "animal", {"kind": "panda"}),
    (r"polar bears?", "Polar Bear", "animal", {"kind": "bear", "color": "#f1efe8", "color2": "#d9d4c8"}),
    (r"\bbears?\b|grizzl", "Bear", "animal", {"kind": "bear"}),
    (r"elephants?", "Elephant", "animal", {"kind": "elephant"}),
    (r"rabbits?|bunn(?:y|ies)|\bhares?\b", "Rabbit", "animal", {"kind": "rabbit"}),
    (r"\bdeer\b|reindeer|\bstags?\b|\belk\b|\bmoose\b", "Deer", "animal", {"kind": "deer"}),
    (r"\bpigs?\b|piglets?|\bhogs?\b", "Pig", "animal", {"kind": "pig"}),
    (r"\bsheep\b|\blambs?\b", "Sheep", "animal", {"kind": "sheep"}),
    (r"giraffes?", "Giraffe", "animal", {"kind": "giraffe"}),
    (r"\bmice\b|\bmouse\b|\brats?\b|hamsters?", "Mouse", "animal", {"kind": "mouse"}),
    (r"\bperson\b|human body|\bhumans?\b|\bman\b|\bwoman\b|\bpeople\b", "Person", "humanoid", {"preset": "person"}),
]
_CATALOG = [(re.compile(rx), title, gen, params) for rx, title, gen, params in _CATALOG]


def catalog(text: str) -> list:
    """The known subjects named in a request, in the order they're named: [(title, generator, params), ...]."""
    t = (text or "").lower()
    found = []
    for rx, title, gen, params in _CATALOG:
        m = rx.search(t)
        if m and not any(m.start() < e and s < m.end() for _, _, _, s, e in found):
            found.append((title, gen, params, m.start(), m.end()))
    return [(title, gen, params) for title, gen, params, _, _ in sorted(found, key=lambda f: f[3])]


def explicit(text: str) -> bool:
    """Whether the person asked to see something (rather than asked a question a model might help with)."""
    t = " ".join(re.sub(r"[?!.]+$", "", (text or "").lower()).split())
    return bool(_EXPLICIT.search(t) or _SHOW.search(t) or _LOOKS.search(t))


def fallback(text: str) -> dict | None:
    """A model without the AI's plan, for a subject this file knows (the AI declined, failed or was unreachable)."""
    known = catalog(text)
    if not known:
        return None
    if _COMPARE.search((text or "").lower()) and len(known) >= 2:
        plans = [_library_plan(*k) for k in known[:2]]
        return sanitize({"visual": True, "title": f"{plans[0]['title']} vs {plans[1]['title']}", "compare": plans,
                         "explanation": " ".join(p.get("explanation", "") for p in plans).strip()}, text)
    return sanitize(_library_plan(*known[0]), text)


def _library_plan(title, gen, params):
    words = LIBRARY_WORDS.get(title, ("", ""))
    return {"visual": True, "title": title, "generator": gen, "params": dict(params), "summary": words[0], "explanation": words[1]}


# ---------- the library: models anyone can open from the gallery, without asking ----------
LIBRARY_WORDS = {   # title: (summary, explanation)
    "Dog": ("Our oldest companion animal.", "Dogs were domesticated from wolves at least 15,000 years ago. They see fewer colours than we do but smell far better: a dog's nose has up to 300 million scent receptors, against our 6 million."),
    "Cat": ("A small hunter that lives with people.", "A cat walks on its toes and keeps its claws pulled in until it needs them. Its whiskers sense air currents and help it judge whether a gap is wide enough to get through."),
    "Horse": ("A fast, strong grazing animal.", "Horses can doze standing up: tendons and ligaments in their legs lock in place so they don't fall. Each hoof is made of keratin, the same material as our fingernails."),
    "Zebra": ("A wild African horse with stripes.", "No two zebras have the same stripes. The stripes seem to put off biting flies, and may also help zebras keep cool."),
    "Cow": ("A grazing animal kept for milk and meat.", "A cow's stomach has four compartments; it brings grass back up to chew again as cud, which lets it digest tough plants we can't."),
    "Lion": ("The big cat of the African savanna.", "Lions are the only cats that live in groups, called prides. Only males grow a mane, which makes them look bigger to rivals."),
    "Tiger": ("The largest wild cat.", "The tiger is the largest wild cat, and every tiger's stripes are different. Its skin is striped too, not just its fur."),
    "Wolf": ("A wild dog that hunts in packs.", "Wolves live and hunt in family packs and talk to each other by howling, which can carry for many kilometres."),
    "Fox": ("A small wild dog with a bushy tail.", "Foxes hunt alone, mostly at dusk and at night. They use their bushy tails for balance and wrap them round themselves to keep warm."),
    "Bear": ("A large, powerful omnivore.", "Bears eat both plants and animals. Many sleep through the winter, living off fat they stored up in the autumn."),
    "Polar Bear": ("The Arctic's largest hunter.", "Polar bears have black skin under see-through fur, which looks white. They hunt seals from the sea ice."),
    "Panda": ("A bear that eats bamboo.", "Giant pandas eat almost nothing but bamboo, up to about 12 to 38 kilograms a day, because it gives them so little energy."),
    "Elephant": ("The largest animal on land.", "The African elephant is the largest land animal, weighing up to about 6 tonnes. Its trunk is a nose and upper lip joined together, and its tusks are very long incisor teeth."),
    "Rabbit": ("A small grazing mammal with long ears.", "Rabbits have eyes high on the sides of their heads and can see almost all the way round, to spot danger from any direction."),
    "Deer": ("A grazing animal whose males grow antlers.", "A male deer grows a new set of antlers every year and sheds them in winter; antlers are among the fastest-growing tissue of any animal."),
    "Pig": ("A farm animal, clever and curious.", "Pigs are among the most intelligent animals and have an excellent sense of smell. They roll in mud to keep cool because they barely sweat."),
    "Sheep": ("A grazing animal kept for its wool.", "A sheep's fleece keeps growing, so farmed sheep are shorn about once a year; one fleece can weigh several kilograms."),
    "Giraffe": ("The tallest animal alive.", "The giraffe is the tallest animal, up to about 5.5 metres. Its neck has just seven vertebrae, the same number as ours, but each is up to about 25 centimetres long."),
    "Mouse": ("A small rodent.", "A mouse's front teeth never stop growing, so it gnaws constantly to keep them short."),
    "Person": ("The human body.", "An adult human body has 206 bones and more than 600 muscles. We walk upright on two legs, which leaves our hands free to use tools."),
    "Iron Man": ("Tony Stark in his powered armour.", "Iron Man is Tony Stark, a Marvel Comics hero who first appeared in 1963. His armour is powered by the arc reactor in its chest, and repulsors in the gloves and boots let him fly."),
    "Spider-Man": ("Peter Parker, the web-slinging hero.", "Spider-Man is Peter Parker, created by Stan Lee and Steve Ditko in 1962. A spider's bite gave him strength, agility and a spider-sense for danger, and he swings on webs fired from his wrists."),
    "Batman": ("Bruce Wayne, the caped detective.", "Batman is Bruce Wayne, a DC Comics hero who first appeared in 1939. He has no superpowers: he relies on training, detective work and the gadgets on his utility belt."),
    "Superman": ("The hero from Krypton.", "Superman, created by Jerry Siegel and Joe Shuster, first appeared in 1938. He comes from the planet Krypton, and under Earth's yellow sun he can fly and has enormous strength and speed."),
    "Captain America": ("Steve Rogers, the super-soldier.", "Captain America is Steve Rogers, a Marvel hero first published in 1941. A super-soldier serum made him as strong and fast as a human can be, and he carries a nearly indestructible round shield."),
    "Hulk": ("Bruce Banner's enormous green alter ego.", "The Hulk is scientist Bruce Banner, who turns into a huge green giant when he gets angry. The angrier he gets, the stronger he becomes."),
    "Astronaut": ("A spacewalker in a pressure suit.", "A spacesuit is a small spacecraft shaped like a person. It holds air at pressure, supplies oxygen, keeps the wearer at a safe temperature, and its gold visor reflects the Sun's glare."),
    "Robot": ("A humanoid machine.", "A humanoid robot is shaped like us so it can use tools and spaces built for people. Motors move its joints, sensors let it see and feel, and a computer decides what to do."),
    "Knight": ("A medieval warrior in plate armour.", "A knight's full plate armour weighed about 15 to 25 kilograms, spread over the whole body, so a trained knight could still run, climb and get up from the ground."),
    "House": ("A family home.", "A house stands on a foundation that spreads its weight into the ground. Its walls carry the floors and the roof, and the sloping roof sheds rain and snow."),
    "Skyscraper": ("A very tall building.", "A skyscraper stands on a steel or concrete frame on deep foundations. A stiff central core holds the lifts and stairs, and its glass walls hang on the frame like a curtain."),
    "Eiffel Tower": ("The iron tower of Paris.", "The Eiffel Tower was finished in 1889 for the World's Fair in Paris. It is about 330 metres tall with its antennas, built from some 18,000 wrought-iron parts held together by 2.5 million rivets."),
    "Great Pyramid of Giza": ("The tomb of the pharaoh Khufu.", "The Great Pyramid was built for the pharaoh Khufu around 2560 BC, from about 2.3 million stone blocks. At about 146 metres, it was the tallest structure on Earth for more than 3,800 years."),
    "Car": ("A family car.", "A car's engine turns the crankshaft, and the gearbox passes that turning to the wheels. The body is a strong shell with crumple zones at the front and back that absorb the energy of a crash."),
    "Sports Car": ("A fast two-door car.", "A sports car sits low to the ground, so air flows over it smoothly and it corners without leaning. A powerful engine and a light body let it speed up quickly."),
    "SUV": ("A tall car built for space and rough roads.", "An SUV rides higher than an ordinary car, with more room inside, and often drives all four wheels for grip on rough or slippery ground."),
    "Airliner": ("A passenger jet.", "An airliner flies because its wings are shaped and angled to push air down, which pushes the wings up. Its turbofan engines' big fans push air backwards to drive it forward."),
    "Rocket": ("A launch vehicle that carries satellites to space.", "A rocket carries its fuel and the oxygen to burn it, so it works in space. It flies in stages: each one drops away when its fuel runs out, leaving less weight to carry."),
    "Television": ("A flat-screen LCD TV.", "An LCD TV makes its picture by shining a backlight through millions of tiny liquid-crystal shutters and colour filters. The mainboard turns the signal into an image and sets how much light each one lets through."),
    "Laptop": ("A portable computer.", "A laptop packs a whole computer into a thin case: the processor and memory on the motherboard, a battery to run it unplugged, a fan to carry away the heat, and a screen in the lid."),
    "Smartphone": ("A computer that fits in your pocket.", "A smartphone's logic board holds its processor and memory, a lithium-ion battery powers it, and the touchscreen senses your finger by tiny changes in electric charge."),
    "Acoustic Guitar": ("A six-string acoustic guitar.", "When a string is plucked it vibrates; the bridge passes the vibration to the wooden top, which moves the air inside the body and out through the sound hole. Pressing a string onto a fret shortens it and raises its note."),
    "Electric Guitar": ("A solid-body electric guitar.", "An electric guitar's solid body barely makes a sound on its own. Its pickups turn the strings' vibration into an electric signal, which an amplifier makes loud."),
    "Sneaker": ("A running shoe.", "A running shoe's midsole is foam that cushions each step, its rubber outsole grips the ground, and the heel counter holds the heel steady."),
    "Human Heart": ("The muscle that pumps blood round the body.", "The heart is a muscular pump about the size of a fist that beats around 100,000 times a day. Its right side pumps blood to the lungs to collect oxygen; its left side pumps that oxygen-rich blood to the whole body."),
    "Car Engine": ("A four-stroke petrol engine.", "A four-stroke engine repeats intake, compression, power and exhaust. Burning fuel pushes the piston down, and the crankshaft turns that up-and-down motion into rotation."),
    "Computer": ("Inside a desktop PC.", "Inside a desktop computer the processor runs programs, memory holds what it is working on, storage keeps files, and the graphics card draws the screen. The power supply turns mains electricity into the low voltages they need."),
}
_BY_TITLE = {title: (title, gen, params) for _, title, gen, params in _CATALOG}
LIBRARY = [   # (title, generator, params): what the gallery's library offers, in this order
    *[_BY_TITLE[t] for t in ("Iron Man", "Spider-Man", "Batman", "Superman", "Captain America", "Hulk", "Astronaut", "Robot", "Knight", "Person",
                             "Dog", "Cat", "Horse", "Zebra", "Lion", "Tiger", "Elephant", "Giraffe", "Panda", "Wolf", "Fox", "Bear", "Polar Bear",
                             "Cow", "Pig", "Sheep", "Deer", "Rabbit", "Mouse",
                             "House", "Eiffel Tower", "Great Pyramid of Giza", "Skyscraper", "Car", "Sports Car", "SUV", "Airliner", "Rocket",
                             "Television", "Laptop", "Smartphone", "Acoustic Guitar", "Electric Guitar", "Sneaker", "Human Heart", "Car Engine", "Computer")],
    ("DNA", "helix", {"kind": "dna", "turns": 2}), ("Carbon Atom", "atom", {"element": "C"}), ("Water Molecule", "molecule", {"name": "water", "formula": "H2O"}),
    ("Sunflower", "flower", {"petals": 34, "layers": 2, "petal_color": "#f6c21c", "center_color": "#4a2d16", "petal_shape": "long", "leaves": 2, "composite": True}),
    ("Rose", "flower", {"petals": 30, "layers": 3, "petal_color": "#c1121f", "center_color": "#f2c94c", "petal_shape": "round", "leaves": 2, "cutaway": True}),
    ("Oak Tree", "tree", {"kind": "oak"}), ("Black Hole", "blackhole", {"jets": True}), ("Gear Train", "gears", {"teeth": [12, 24, 36]}),
]
LIBRARY_WORDS.update({
    "DNA": ("The molecule of heredity.", "DNA carries the instructions for building and running living things. Two strands twist into a double helix, held together by pairs of bases: adenine with thymine, guanine with cytosine."),
    "Carbon Atom": ("Element 6.", "Carbon has six protons and, in its most common form, six neutrons. Its four outer electrons let it bond in long chains and rings, the basis of all life on Earth."),
    "Water Molecule": ("H2O.", "A water molecule is one oxygen atom bonded to two hydrogen atoms, bent at about 104.5 degrees. Oxygen pulls the shared electrons toward itself, so the molecule is slightly charged at each end, which is why water dissolves so many things."),
    "Sunflower": ("A composite flower head.", "A sunflower head is not one flower but up to about 2,000 tiny florets, packed in spirals that follow the golden angle. The yellow ray florets round the edge attract bees; the disc florets in the middle become the seeds."),
    "Rose": ("A single flower.", "A rose's petals attract pollinators, its stamens make pollen, and its pistil in the middle receives pollen and grows the seeds in the rose hip."),
    "Oak Tree": ("A broadleaf tree.", "An oak can live for many centuries. Its roots draw water from the soil, and its leaves use sunlight to turn water and carbon dioxide into sugar, giving off oxygen."),
    "Black Hole": ("Gravity so strong light can't escape.", "A black hole is a region where gravity is so strong that nothing, not even light, can escape past its edge, the event horizon. Gas spiralling in heats up and glows as an accretion disc."),
    "Gear Train": ("Three meshing gears.", "Meshing gears trade speed for turning force: a small gear driving a big one turns it more slowly but more strongly, and each pair turns in opposite directions."),
})


def library() -> list:
    """The gallery's library, as checked specs the window can open as they are (projector/library.json)."""
    out = []
    seen = set()
    for title, gen, params in LIBRARY:
        if title in seen:
            continue
        seen.add(title)
        spec = sanitize(_library_plan(title, gen, params), "")
        if spec:
            spec["question"] = ""
            spec["library"] = True
            out.append(spec)
    return out


def write_library(path: str | None = None) -> str:
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "projector", "library.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(library(), f, ensure_ascii=False, indent=1)
        f.write("\n")
    return path


# ---------- follow-ups ----------
def memory(spec: dict) -> dict:
    """What the next question may refer to ("its inside", "how does it work")."""
    return {"title": spec["title"], "generator": spec["generator"], "part_names": spec.get("part_names", []), "at": time.time()}


def spoken(spec: dict) -> str:
    """What Jarvis says as the model appears: the answer, then what can be done with it."""
    text = spec.get("explanation") or spec.get("summary") or spec["title"]
    return f"{text}\n\nIt's in the projector: drag to turn it, and pick a part to learn what it does."
