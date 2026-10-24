"""What a Blender request asks for, as a plan of tasks — for any combination of what Jarvis can make.

"Create a futuristic city at night, then animate a flying vehicle moving between the skyscrapers while rain
falls and the camera follows it" becomes:

    environment city (futuristic)  ·  object flying_car  ·  motion fly, between the skyscrapers
    weather rain  ·  lighting night  ·  camera follow (the flying car)  ·  render video

Nothing here knows any particular scene. A request is split into clauses (then / while / as / and <verb>...),
and each clause is read for mentions of the capabilities the vocabularies list — environments, buildings,
objects (world_library), characters and their actions (anim_library / anim_core), how things travel and relative
to what ("between the towers", "to the door", "around the fountain"), weather, time of day, camera and render.
Pronouns ("it", "him") are whatever was mentioned last, in this request or in the scene's stored plan.

Follow-ups ("make it faster", "add more buildings", "change the weather to snow", "make the camera follow the
character") are edits of the stored plan (parse_followup), so only what they touch is redone.

What the vocabularies don't cover can still be planned by the local AI (ai_plan) — its answer must be the same
JSON, and every field is checked here before anything runs. Pure Python: tested without Blender.
"""
import copy
import json
import re

import anim_library
import world_library

# ---------- vocabularies ----------
_CREATE = (r"create|build|make|model|generate|design|construct|add|put|place|set up|give me|show me|draw|spawn|"
           r"include|i want|i'd like|there should be|there is|there are|with")
_NUMBER = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
           "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
           "a couple of": 2, "a pair of": 2, "a few": 3, "several": 4, "some": 3, "many": 8, "lots of": 10,
           "a lot of": 10, "dozens of": 24, "a dozen": 12}
_STYLE = {"futuristic": "futuristic", "sci-fi": "futuristic", "scifi": "futuristic", "cyberpunk": "futuristic",
          "neon": "futuristic", "modern": "modern", "old": "old", "medieval": "old", "ancient": "old",
          "rustic": "old", "classic": "old", "abandoned": "old"}
_SIZE = {"small": "small", "tiny": "small", "little": "small", "big": "large", "large": "large",
         "huge": "huge", "giant": "huge", "massive": "huge", "enormous": "huge", "vast": "huge"}
# character actions: words -> anim_core action ("do")
_CHAR_ACTIONS = [
    (r"walk(?:s|ing|ed)?|stroll(?:s|ing)?|go(?:es|ing)?|head(?:s|ing)?|approach(?:es|ing)?|step(?:s|ping)?|move(?:s|ing)?|"
     r"come(?:s)?|coming", "walk"),
    (r"run(?:s|ning)?|ran|jog(?:s|ging)?|sprint(?:s|ing)?|rush(?:es|ing)?|hurr(?:y|ies|ying)", "run"),
    (r"jump(?:s|ing|ed)?|leap(?:s|ing)?|hop(?:s|ping)?", "jump"),
    (r"sit(?:s|ting)?(?: down)?|sat|take(?:s)? a seat|seat(?:s|ed)? (?:him|her)self", "sit"),
    (r"st(?:a|o)nd(?:s|ing)? up|get(?:s)? up|rise(?:s)?", "stand"),
    (r"eat(?:s|ing)?|ate|tak(?:e|es|ing) a bite|munch(?:es|ing)?", "eat"),
    (r"drink(?:s|ing)?|drank|sip(?:s|ping)?", "drink"),
    (r"danc(?:e|es|ing)", "dance"),
    (r"wav(?:e|es|ing)(?: hello| goodbye)?", "wave"),
    (r"talk(?:s|ing)?|speak(?:s|ing)?|chat(?:s|ting)?|convers\w*", "talk"),
    (r"(?:call(?:s|ing)?|talk(?:s|ing)? on|use(?:s)?|using|check(?:s|ing)?) (?:a |the |his |her )?(?:phone|mobile)|"
     r"phon(?:e|es|ing)", "phone"),
    (r"point(?:s|ing)? (?:at|to)", "point"),
    (r"pick(?:s|ing)? up|grab(?:s|bing)?|lift(?:s|ing)?|tak(?:e|es|ing)", "pick_up"),
    (r"put(?:s|ting)? down|drop(?:s|ping)?|set(?:s|ting)? down|place(?:s)? (?:it|the \w+) down", "put_down"),
    (r"carr(?:y|ies|ying)", "carry"),
    (r"open(?:s|ing|ed)?", "open_door"),
    (r"(?:enter(?:s|ing|ed)?|go(?:es|ing)? in(?:side|to)?|walk(?:s|ing)? in(?:to|side)?|come(?:s)? in)", "enter"),
    (r"clos(?:e|es|ing|ed)|shut(?:s|ting)?", "close_door"),
    (r"fight(?:s|ing)?|box(?:es|ing)|punch(?:es|ing)?|spar(?:s|ring)?", "fight"),
    (r"work(?:s|ing)?|typ(?:e|es|ing)|hammer(?:s|ing)?", "work"),
    (r"turn(?:s|ing)? (?:around|round)", "turn_around"),
    (r"wait(?:s|ing)?|stand(?:s|ing)? still|idl(?:e|es|ing)|pause(?:s)?", "wait"),
    (r"look(?:s|ing)? (?:at|around)", "look"),
    (r"shake(?:s)? hands|shaking hands", "handshake"),
]
# how things travel: words -> verb
_MOTIONS = [
    (r"fly(?:ing)?|flies|flew|soar(?:s|ing)?|glid(?:e|es|ing)|hover(?:s|ing)?(?= (?:between|through|over|around|across|"
     r"along|above|to|toward))", "fly"),
    (r"driv(?:e|es|ing)|drove|rac(?:e|es|ing)|speed(?:s|ing)", "drive"),
    (r"sail(?:s|ing)?|float(?:s|ing)?", "sail"),
    (r"orbit(?:s|ing)?|circl(?:e|es|ing)", "orbit"),
    (r"spin(?:s|ning)?|rotat(?:e|es|ing)|turn(?:s|ing) (?:around|in place)", "spin"),
    (r"hover(?:s|ing)?|bob(?:s|bing)?", "hover"),
    (r"bounc(?:e|es|ing)|roll(?:s|ing)?", "bounce"),
    (r"mov(?:e|es|ing)|travel(?:s|ling|ing)?|go(?:es|ing)?|cruis(?:e|es|ing)|zoom(?:s|ing)?|pass(?:es|ing)?|"
     r"weav(?:e|es|ing)", "move"),
]
_RELATIONS = r"between|among|amongst|through|around|round|across|along|over|above|past|to|toward|towards|into|" \
             r"from|up to|onto|on|at|inside|in|out of|near|beside|next to|under|in front of|behind"
_WEATHER = [(r"thunder ?storm\w*|storm(?:s|y)?|lightning", "storm"), (r"snow\w*|blizzard|snowfall", "snow"),
            (r"rain\w*|drizzl\w*|downpour|shower(?:s)?|wet", "rain"), (r"fog\w*|mist\w*|haz(?:e|y)", "fog"),
            (r"wind(?:y|s)?|gust\w*|breez\w*", "wind")]
_HEAVY = re.compile(r"\b(?:heavy|heavily|pouring|torrential|hard|lots of|strong|intense|downpour|storm\w*)\b", re.I)
_LIGHT = re.compile(r"\b(?:light|lightly|gentle|soft|drizzl\w*|a little)\b", re.I)
_TIME = [(r"midnight|night(?:time|fall)?|at night|dark|neon[- ]lit", "night"),
         (r"sunset|dusk|evening|golden hour|twilight", "sunset"), (r"sunrise|dawn|morning", "sunrise"),
         (r"overcast|cloudy|gloomy|grey sky|gray sky", "overcast"), (r"daylight|daytime|midday|noon|sunny|by day", "day")]
_CAMERA = [(r"(?:camera|cam|shot|we) (?:follows?|following|tracks?|tracking|chases?|chasing)|follow(?:s|ing)? (?:it|him|"
            r"her|them|the \w+) with the camera|chase cam|follow cam|tracking shot", "follow"),
           (r"orbit(?:s|ing)?(?: camera| shot)?|camera (?:circles|orbits|goes around|around)|360", "orbit"),
           (r"close[- ]?up", "closeup"), (r"wide shot|establishing shot|aerial|bird'?s[- ]eye|drone shot|overview|"
                                         r"from above", "establishing"),
           (r"static (?:camera|shot)|locked[- ]off|fixed camera", "static"),
           (r"cinematic(?: camera| shots?| movements?)?|camera movements?", "cinematic")]
_RENDER = re.compile(r"\b(?:render\w*|video|movie|film|clip|animation file|mp4|export (?:the |a )?(?:video|animation)|"
                     r"polished|final render|high quality|4k|1080p)\b", re.I)
_FINAL = re.compile(r"\b(?:final|polished|high quality|best quality|4k|1080p|full quality|production)\b", re.I)
_STILL = re.compile(r"\b(?:picture|image|still|screenshot|photo)\b", re.I)
_SPEED = [(r"very (?:fast|quickly)|really fast|at high speed|at full speed|racing", 2.0),
          (r"fast|quickly|rapidly|speedily|in a hurry|hurriedly", 1.5), (r"very slowly|really slowly", 0.45),
          (r"slowly|slow|leisurely|calmly|gently", 0.7)]
_PRONOUN = re.compile(r"\b(it|him|her|them|he|she|they|itself|himself|herself)\b", re.I)
_PARTS = {"door": r"front door|door(?:way)?|entrance|entry", "inside": r"inside|interior|indoors",
          "window": r"window"}
_BUILDING_NOUNS = r"villa|mansion|house|home|cottage|cabin|bungalow"
_FILLER = re.compile(r"^(?:(?:okay|ok|so|now|and|alright|well|hey|jarvis|jervis|please|in blender|blender)\b[,.!]?\s*)+",
                     re.I)


def _words_alt(words):
    return "|".join(sorted((re.escape(w) for w in words), key=len, reverse=True))


_ASSET_RE = re.compile(r"\b(?P<w>" + _words_alt(world_library.ASSET_WORDS) + r")(?:e?s)?\b", re.I)
_ENV_WORDS = {w: k for k, ws in world_library.ENVIRONMENTS.items() for w in ws}
_ENV_RE = re.compile(r"\b(?P<w>" + _words_alt(_ENV_WORDS) + r")\b", re.I)
_CHAR_RE = re.compile(r"\b(?P<w>" + _words_alt([w for w in anim_library.CHARACTER_WORDS if w not in (
    "he", "him", "she", "her")] + ["people", "persons", "men", "women", "characters", "kids", "children", "child",
                                   "robot", "worker", "workers", "dancer", "dancers"]) + r")\b", re.I)
_BUILD_RE = re.compile(r"\b(?P<w>" + _BUILDING_NOUNS + r")s?\b", re.I)
# what an environment can have running through it
_FEATURES = {"river": "river", "stream": "river", "creek": "river", "lake": "lake", "pond": "lake", "bridge": "bridge"}
_FEATURE_RE = re.compile(r"\b(?P<w>river|stream|creek|lake|pond|bridge)s?\b", re.I)
_CLAUSE = re.compile(r"(?:[.!?;]\s+|\s*,?\s*\b(?:and then|then|after that|afterwards|next|finally|while|as|"
                     r"meanwhile|before|once)\b\s*,?\s*)", re.I)


_BUILD_FEATURE = re.compile(r"(?:swimming )?pool|garden|yard|backyard|lawn|trees?|hedges?|garage|carport|balcon(?:y|ies)|"
                            r"terrace|patio|deck|veranda|porch|greenery|plants", re.I)


def _known_word(word):
    """Whether a vocabulary names `word` (an object, a place, a building feature...): then it is never "unknown"."""
    return any(r.fullmatch(word) for r in (_ASSET_RE, _ENV_RE, _CHAR_RE, _BUILD_RE, _FEATURE_RE)) or bool(
        _BUILD_FEATURE.fullmatch(word))


class Plan(dict):
    """{"tasks": [...], "said": text, "unknown": [phrases nothing here builds]}"""


def _clean(text):
    t = " ".join((text or "").replace("’", "'").split())
    return _FILLER.sub("", t).strip(" .!?")


def _count_before(text, start):
    """The number said just before a noun ("two chairs", "20 skyscrapers", "lots of trees"), or None."""
    before = text[max(0, start - 40):start].lower()
    before = re.split(r"\b(?:with|and|of|in|on|at|to|then|while|between|,)\b", before)[-1]
    m = re.search(r"(\d+)\s+(?:[\w-]+\s+){0,3}$", before)
    if m:
        return int(m.group(1))
    best = None
    for word, n in sorted(_NUMBER.items(), key=lambda kv: -len(kv[0])):
        mm = re.search(rf"\b{re.escape(word)}\s+(?:[\w-]+\s+){{0,3}}$", before)
        if mm and (best is None or mm.start() > best[0]):
            best = (mm.start(), n)
    return best[1] if best else None


def _adjectives_before(text, start, span=40):
    before = text[max(0, start - span):start].lower()
    before = re.split(r"\b(?:and|with|then|while|of|to|in|on|at|between|the)\b", before)[-1]
    style = next((v for k, v in _STYLE.items() if re.search(rf"\b{re.escape(k)}\b", before)), None)
    size = next((v for k, v in _SIZE.items() if re.search(rf"\b{re.escape(k)}\b", before)), None)
    color = next((k for k in world_library.COLORS if re.search(rf"\b{k}\b", before)), None)
    return style, size, color


def _mentions(clause):
    """Everything a clause names, in order: (start, end, kind, value, word)."""
    found = []
    taken = []

    def add(m, kind, value):
        s, e = m.start("w"), m.end()
        if any(s < b and a < e for a, b in taken):
            return
        taken.append((s, e))
        found.append((s, e, kind, value, m.group("w").lower()))

    for m in _BUILD_RE.finditer(clause):
        add(m, "building", m.group("w").lower())
    for m in _ENV_RE.finditer(clause):
        add(m, "environment", _ENV_WORDS[m.group("w").lower()])
    for m in _CHAR_RE.finditer(clause):
        add(m, "character", m.group("w").lower())
    for m in _ASSET_RE.finditer(clause):
        add(m, "asset", world_library.ASSET_WORDS[m.group("w").lower()])
    for m in _FEATURE_RE.finditer(clause):
        add(m, "feature", _FEATURES[m.group("w").lower()])
    return sorted(found)


def _actions_in(clause, mentions=()):
    """Action verbs in order: (start, end, kind "char"|"motion", value). A verb that is part of a thing's name
    ("a flying car") isn't one."""
    out = []
    taken = [(s, e) for s, e, *_ in mentions]
    for kind, table in (("char", _CHAR_ACTIONS), ("motion", _MOTIONS)):
        for pattern, value in table:
            for m in re.finditer(rf"\b(?:{pattern})\b", clause, re.I):
                if any(m.start() < b and a < m.end() for a, b in taken):
                    continue
                taken.append((m.start(), m.end()))
                out.append((m.start(), m.end(), kind, value))
    return sorted(out)


_NOT_TARGET = re.compile(r"^(?:heavy |light |the |a )*(?:rain|snow|fog|mist|storm|wind|night|day|dark|daylight|"
                         r"sunset|sunrise|it|him|her|them|himself|herself|itself|behind|slow|motion|style|"
                         r"time|way|order|front|place)\b", re.I)


def _relation_after(text):
    """The first "<relation> <thing>" in `text` - or a direct object ("approaching the entrance", "opening the
    door") - as (relation, thing words), or (None, None). Weather and time ("in the rain", "at night") aren't
    places to go."""
    d = re.match(r"\s*(?:the |a |an |his |her |its |their |this |that )(?P<what>[\w' -]{2,40}?)(?=$|[,.;]|\s+(?:and|"
                 r"while|then|as|with|before|after|so|until|in|at|on|from|behind)\b)", text, re.I)
    if d and not _NOT_TARGET.match(d.group("what")):
        return "to", d.group("what").strip().lower()
    for m in re.finditer(rf"\b(?P<rel>{_RELATIONS})\s+(?:the |a |an |his |her |its |their |this |that |some )?"
                  rf"(?P<what>[\w' -]{{2,40}}?)(?=$|[,.;]|\s+(?:and|while|then|as|with|before|after|so|until)\b)",
                  text, re.I):
        if not _NOT_TARGET.match(m.group("what")):
            return m.group("rel").lower(), m.group("what").strip().lower()
    return None, None


def _speed_in(text):
    for pattern, factor in _SPEED:
        if re.search(rf"\b(?:{pattern})\b", text, re.I):
            return factor
    return None


def _ref(words, tasks, scene_tasks=()):
    """Which task (or part of one) `words` refer to: {"task": id} / {"task": id, "part": "door"} / {"kind": asset}."""
    if not words:
        return None
    w = words.lower()
    part = next((p for p, pat in _PARTS.items() if re.search(rf"\b(?:{pat})\b", w)), None)
    pool = list(tasks) + list(scene_tasks)
    if re.search(rf"\b(?:{_BUILDING_NOUNS}|building)s?\b", w):   # "the house" when the villa is the build
        b = next((t for t in reversed(pool) if t["kind"] == "building"), None)
        if b:
            return {"task": b["id"], "part": part} if part else {"task": b["id"]}
    for t in reversed(pool):
        names = {t.get("asset"), t.get("type"), t.get("noun"), t.get("template"), t.get("word")}
        names |= {world_library.ASSET_WORDS.get(n) for n in list(names) if n}
        for n in names:
            if n and re.search(rf"\b{re.escape(str(n).replace('_', ' '))}e?s?\b", w):
                return {"task": t["id"], "part": part} if part else {"task": t["id"]}
        if t["kind"] == "environment" and t.get("type") == "city" and re.search(r"\b(?:skyscraper|tower|building)s?\b",
                                                                                 w):
            return {"task": t["id"], "items": "building"}
        if t["kind"] == "environment" and re.search(r"\b(?:tree|trees|rocks?|buildings?|houses?|streets?|roads?)\b",
                                                    w):
            item = re.search(r"\b(tree|rock|building|house|street|road)", w).group(1)
            return {"task": t["id"], "items": {"tree": "nature", "rock": "nature", "house": "building",
                                               "street": "street", "road": "street"}.get(item, item)}
    if part:
        b = next((t for t in reversed(pool) if t["kind"] in ("building", "environment")), None)
        if b:
            return {"task": b["id"], "part": part}
    m = _ASSET_RE.search(w)
    if m:
        return {"asset": world_library.ASSET_WORDS[m.group("w").lower()], "words": w}
    m = _ENV_RE.search(w)
    if m:
        return {"environment": _ENV_WORDS[m.group("w").lower()], "words": w}
    return {"words": w}


def parse(text, scene_plan=None):
    """The plan for `text`, or None when it names nothing Jarvis knows how to make or animate. `scene_plan` is
    what's already in the scene (its tasks can be referred to: "him", "the villa")."""
    said = _clean(text)
    if not said:
        return None
    scene_tasks = list((scene_plan or {}).get("tasks", []))
    tasks = []
    counter = [len(scene_tasks)]

    def new(kind, **kw):
        counter[0] += 1
        t = {"id": f"t{counter[0]}", "kind": kind}
        t.update({k: v for k, v in kw.items() if v is not None})
        tasks.append(t)
        return t

    last_subject = next((t for t in reversed(scene_tasks) if t["kind"] in ("character", "object")), None)
    clauses = [c.strip(" ,") for c in _CLAUSE.split(said) if c and c.strip(" ,")]
    for clause in clauses:
        mentions = _mentions(clause)
        if any(m[2] == "building" for m in mentions):
            # "a villa with a pool, a garden and a garage": those are the villa builder's own features of the
            # house (blender_build.FEATURES), not a park and a garage of their own beside it
            mentions = [m for m in mentions if not (m[2] in ("environment", "asset", "feature") and _BUILD_FEATURE.fullmatch(
                m[4]))]
        actions = _actions_in(clause, mentions)
        made = {}   # mention start -> task
        for s, e, kind, value, word in mentions:
            # a thing named only as where something goes ("walk to the table", "between the skyscrapers") is a
            # reference, not something new — unless nothing like it exists yet
            rel_before = re.search(rf"\b(?:{_RELATIONS})\s+(?:the |a |an |this |that |his |her |its )?(?:[\w-]+\s+)?$",
                                   clause[max(0, s - 30):s], re.I)
            definite = re.search(r"\b(?:the|this|that|his|her|its|their)\s+(?:[\w-]+\s+)?$", clause[max(0, s - 20):s],
                                 re.I)
            if (rel_before or definite) and _ref(word, tasks, scene_tasks) and "task" in (_ref(word, tasks,
                                                                                              scene_tasks) or {}):
                continue
            plural = clause[e - 1:e].lower() == "s" and word not in ("bus", "glass", "grass", "cactus", "people")
            count = _count_before(clause, s) or (4 if plural else 1)
            style, size, color = _adjectives_before(clause, s)
            if style is None:
                style = next((v for k, v in _STYLE.items() if re.search(rf"\b{re.escape(k)}\b", said, re.I)), None) \
                    if kind in ("environment", "asset") else None
            if kind == "environment":
                same = next((t for t in tasks if t["kind"] == "environment" and t["type"] == value), None)
                if same is not None:
                    made[s] = same
                    if size and not same.get("size"):
                        same["size"] = size
                    continue
                room = word if value == "room" else None
                made[s] = new("environment", type=value, style=style, size=size, room=room, word=word)
            elif kind == "feature":
                env = next((t for t in reversed(tasks + scene_tasks) if t["kind"] == "environment"), None)
                if env is not None:
                    env.setdefault("features", [])
                    if value not in env["features"]:
                        env["features"].append(value)
                else:
                    made[s] = new("environment", type="park", features=[value], word=word)
                continue
            elif kind == "building":
                if any(t["kind"] == "environment" and t["type"] in ("town",) for t in tasks) and count > 1:
                    continue
                made[s] = new("building", noun=word, said=clause, word=word)
            elif kind == "character":
                group = word in ("people", "persons", "characters", "men", "women", "kids", "children", "workers",
                                 "dancers")
                n = count if count > 1 or not group else 2
                template = anim_library.CHARACTER_WORDS.get(word, "woman" if word in ("women",) else "man")
                members = []
                for i in range(min(n, 6)):
                    tmpl = template if not group or word in ("men", "women") else ("man", "woman")[i % 2]
                    members.append(new("character", template=tmpl, word=word, color=color))
                for extra in members[1:]:
                    extra["group"] = members[0]["id"]
                made[s] = members[0]
            elif kind == "asset":
                if value == "skyscraper" and any(t["kind"] == "environment" and t["type"] == "city" for t in tasks + scene_tasks):
                    if count > 1 or re.search(r"\bmore\b", clause, re.I):
                        city = next(t for t in tasks + scene_tasks if t["kind"] == "environment" and t["type"] == "city")
                        city["buildings"] = count
                        continue
                made[s] = new("object", asset=value, count=min(count, 60), style=style, size=size, color=color,
                              word=word)
                # where it goes: "a cup on the table", "a bench near the fountain"
                pm = re.match(r"\s*(?P<rel>on top of|on|onto|next to|near|beside|by|in front of|behind|under|inside|in)"
                              r"\s+(?:the |a |an |his |her )?(?P<what>[\w -]{2,30}?)(?=$|[,.;]|\s+(?:and|with|while|then)\b)",
                              clause[e:], re.I)
                if pm:
                    ref = _ref(pm.group("what"), tasks, scene_tasks)
                    if ref and (ref.get("task") or ref.get("asset")):
                        made[s]["place"] = {"rel": pm.group("rel").lower(), "target": ref}
        # a noun nothing here knows ("a dragon") that is made or moves: its own object, shaped later
        if actions or _CREATE_RE.match(clause):
            first = (actions[0][0] if actions else len(clause))
            lead = clause[:first]
            m = re.search(r"\b(?:a|an|the|one|some)\s+(?:[\w-]+\s+){0,2}?(?P<w>[a-z][\w-]{2,})\s*$", lead.strip() + " ",
                          re.I)
            named = m and (any(a <= m.start("w") < b for a, b, *_ in mentions) or _known_word(m.group("w")))
            if m and not named and m.group("w").lower() not in _STOP and m.group("w").lower() not in _STYLE and \
                    m.group("w").lower() not in _SIZE and not _PRONOUN.fullmatch(m.group("w")):
                t = new("object", asset="unknown", name=m.group("w").lower(), count=1, word=m.group("w").lower())
                made[m.start("w")] = t
                mentions = sorted(mentions + [(m.start("w"), m.end("w"), "asset", "unknown", m.group("w").lower())])
        # what the clause's subjects do
        if actions:
            subject = None
            for s, e, kind, value, word in mentions:
                if s < actions[0][0] and s in made and made[s]["kind"] in ("character", "object"):
                    subject = made[s]
            if subject is None:
                first = next((made[s] for s, *_ in mentions if s in made and made[s]["kind"] in ("character", "object")),
                             None)
                pron = _PRONOUN.search(clause[:actions[0][0] + 1]) or _PRONOUN.search(clause)
                if first is not None and (not pron or first is not None and mentions and mentions[0][0] < actions[-1][0]):
                    subject = first
                elif pron or last_subject is not None:
                    subject = next((t for t in reversed(tasks) if t["kind"] in ("character", "object")), None) or \
                        last_subject
            if subject is not None:
                _add_motion(subject, clause, actions, tasks, scene_tasks, new, said)
                last_subject = subject
        for s, _, _, _, _ in mentions:
            if s in made and made[s]["kind"] in ("character", "object"):
                last_subject = made[s]
    _globals(said, tasks, scene_tasks, new, last_subject)
    if not tasks:
        return None
    plan = Plan(tasks=tasks, said=said, unknown=_unknown(said))
    return plan


def _add_motion(subject, clause, actions, tasks, scene_tasks, new, said):
    """The motion task for `subject` from the clause's action verbs (each with what follows it, up to the next
    verb, as its target)."""
    is_char = subject["kind"] == "character"
    speed = _speed_in(clause)
    steps = []
    for i, (s, e, kind, value) in enumerate(actions):
        rest = clause[e:actions[i + 1][0]] if i + 1 < len(actions) else clause[e:]
        rel, what = _relation_after(rest)
        target = _ref(what, tasks, scene_tasks) if what else None
        pron = re.match(r"\s*(?:\w+\s+)?(?:it|them)\b", rest, re.I)
        rel_p = re.match(rf"\s*(?P<rel>{_RELATIONS})\s+(?:it|them)\b", rest, re.I)
        if target is None and (pron or rel_p) and (kind == "motion" or value in ("drink", "eat")):
            place = rel_p and rel_p.group("rel").lower() in ("over", "above", "across", "through", "around", "in")
            other = next((t for t in reversed(tasks + list(scene_tasks)) if t["id"] != subject["id"] and t["kind"] in (
                ("environment", "building") if place else ("object", "environment", "building"))), None)
            if other is not None:
                target = {"task": other["id"]}
                rel = rel_p.group("rel").lower() if rel_p else rel
        if kind == "char" and not is_char:
            if value in ("walk", "run", "jump"):
                kind, value = "motion", {"walk": "move", "run": "move", "jump": "bounce"}[value]
            elif value in ("turn_around",):
                kind, value = "motion", "spin"
            else:
                continue
        if kind == "motion" and not is_char and value == "move":
            r_ = world_library.RECIPES.get(subject.get("asset"))
            value = {"fly": "fly", "drive": "drive", "sail": "sail"}.get(r_({}).get("moves") if r_ else None, "move")
        if steps and kind == "motion" and steps[-1]["do"] == value and "target" not in steps[-1]:
            steps.pop()   # "flying ... moving between": one journey
        if kind == "motion" and is_char:
            value = {"fly": "walk", "drive": "walk", "move": "walk", "sail": "walk", "orbit": "walk",
                     "hover": "wait", "spin": "turn_around", "bounce": "jump"}.get(value, "walk")
            kind = "char"
        step = {"do": value}
        if rel:
            step["rel"] = rel
        if target:
            step["target"] = target
        if kind == "char":
            if value in ("eat", "drink", "pick_up", "carry", "phone"):
                m = re.search(r"\b(?:a|an|the|some|his|her)?\s*(?P<w>[\w ]+?)(?=$|[,.;]|\s+(?:and|while|then|from|at|"
                              r"on|with|before|after)\b)", rest.strip(), re.I)
                prop = None
                if m:
                    pm = _ASSET_RE.search(m.group("w"))
                    prop = world_library.ASSET_WORDS[pm.group("w").lower()] if pm else None
                step["prop"] = prop or {"eat": "sandwich", "drink": "cup", "phone": "phone"}.get(value, "box")
            if value in ("enter", "open_door", "close_door") and "target" not in step:
                step["target"] = _ref("door", tasks, scene_tasks)
            if value == "walk" and rel in ("into", "inside", "in") and target and target.get("task"):
                step = {"do": "enter", "target": dict(target, part="door")}
        if step.get("target", {}).get("task") == subject["id"]:
            step.pop("target")   # nothing goes around itself
        if steps and steps[-1] == step:
            continue
        steps.append(step)
    if not steps:
        return
    kind = "action" if is_char else "motion"
    group = [subject] + [t for t in tasks if t.get("group") == subject["id"]]
    for member in group:
        existing = next((t for t in tasks if t["kind"] == kind and t.get("subject") == member["id"]), None)
        if existing:
            existing["steps"] += copy.deepcopy(steps)
            if speed:
                existing["speed"] = speed
        else:
            new(kind, subject=member["id"], steps=copy.deepcopy(steps), speed=speed,
                together=group[0]["id"] if len(group) > 1 else None)


def _globals(said, tasks, scene_tasks, new, last_subject):
    """Weather, time of day, camera and render, wherever in the request they're said."""
    for pattern, kind in _WEATHER:
        if re.search(rf"\b(?:{pattern})\b", said, re.I):
            if kind == "rain" and re.search(r"\bwet (?:surfaces?|ground|streets?)\b", said, re.I) and not re.search(
                    r"\brain", said, re.I):
                new("weather", type="wet")
                continue
            intensity = "heavy" if _HEAVY.search(said) else "light" if _LIGHT.search(said) and kind != "wind" else None
            if not any(t["kind"] == "weather" and t["type"] == kind for t in tasks):
                new("weather", type=kind, intensity=intensity)
    for pattern, kind in _TIME:
        if re.search(rf"\b(?:{pattern})\b", said, re.I):
            if not any(t["kind"] == "lighting" for t in tasks):
                new("lighting", time=kind, mood="cinematic" if re.search(r"\bcinematic|dramatic|realistic lighting\b",
                                                                          said, re.I) else None)
            break
    else:
        if re.search(r"\b(?:cinematic|dramatic|realistic) (?:lighting|light)\b", said, re.I):
            new("lighting", time=None, mood="cinematic")
    for pattern, shot in _CAMERA:
        m = re.search(rf"\b(?:{pattern})", said, re.I)
        if m:
            rest = said[m.end():]
            what = re.match(r"\s*(?:the |a )?(?P<w>[\w ]{2,30}?)(?=$|[,.;]|\s+(?:and|while|then|as|through|around|"
                            r"with|across|between)\b)", rest)
            subject = None
            if what and not _PRONOUN.fullmatch(what.group("w").strip()):
                ref = _ref(what.group("w"), tasks, scene_tasks)
                subject = ref.get("task") if ref else None
            if subject is None and last_subject is not None:
                subject = last_subject["id"]
            new("camera", shot=shot, subject=subject)
            break
    if _RENDER.search(said):
        new("render", quality="final" if _FINAL.search(said) else "preview",
            video=not (_STILL.search(said) and not re.search(r"\b(?:video|animat\w*|movie)\b", said, re.I)))


_STOP = set("a an the and or with of in on at to into onto for from by then while as it its it's this that these "
            "those his her him he she they them their there is are be being been was were will would should could "
            "please make create build add put place set have has had let get show give me us i want like some "
            "very really more much many lots lot few one two three four five six seven eight nine ten all every "
            "each also too just so now after before when where who what which up down out over under between "
            "through around across along near next behind front inside outside back side way time scene blender "
            "animate animation animated render rendering video movie camera shot shots cinematic realistic "
            "polished final quality natural naturally beautiful nice cool amazing detailed movements movement "
            "lighting light lights surfaces surface wet heavy heavily lightly gentle soft dark bright towards toward "
            "behind him herself himself itself using use do does doing done using high low new old big small large"
            " huge tiny little modern futuristic falls fall falling follows follow following start end while slowly "
            "quickly fast slow then finally".split())


def _unknown(said):
    """Nouns-ish words nothing in the vocabularies covers ("a dragon"): said back, or handed to the AI planner."""
    covered = [m.span() for r in (_ASSET_RE, _ENV_RE, _CHAR_RE, _BUILD_RE) for m in r.finditer(said)]
    for table in (_CHAR_ACTIONS, _MOTIONS, _WEATHER, _TIME, _CAMERA):
        for pattern, _ in table:
            covered += [m.span() for m in re.finditer(rf"\b(?:{pattern})\b", said, re.I)]
    covered += [m.span() for m in _RENDER.finditer(said)]
    covered += [m.span() for m in _FEATURE_RE.finditer(said)]
    for pat in _PARTS.values():
        covered += [m.span() for m in re.finditer(rf"\b(?:{pat})\b", said, re.I)]
    out = []
    for m in re.finditer(r"[A-Za-z][\w'-]+", said):
        w = m.group(0).lower()
        if w in _STOP or w in _STYLE or w in _SIZE or w in world_library.COLORS or w in _NUMBER or w.isdigit():
            continue
        if any(a <= m.start() < b for a, b in covered):
            continue
        if re.fullmatch(r"\w+(?:ing|ed|ly|s)", w) and len(w) > 5 and w[:-1] in _STOP:
            continue
        out.append(w)
    return out


# ---------- what counts as a scene request ----------

def is_scene_request(text, scene_plan=None):
    """Whether `text` is something the planner should take: it names an environment, a library object, a
    character, an action, weather, a camera or a video — anything beyond the one-object commands and the single
    building ("create a villa" keeps going to the villa builder, "make the cube red" to the object commands)."""
    said = _clean(text)
    if _PLACE_EDIT.match(said) or _QUESTION.match(said):
        return False
    plan = parse(text, scene_plan)
    if not plan:
        return False
    # something nothing here knows, on its own ("create a cube", "build a rocket"), stays with the object commands
    # and the free-form AI; it joins a scene only alongside things the planner does know
    tasks = [t for t in plan["tasks"] if t.get("asset") != "unknown"]
    kinds = [t["kind"] for t in tasks]
    things = [k for k in kinds if k in ("environment", "building", "object", "character", "motion", "action")]
    if not things:
        # weather or light alone ("show me the weather", "make it dark green glass") only as an explicit change of
        # the scene's ("make it rain", "add fog", "make it night")
        return bool(_WEATHER_CHANGE.search(said) or _TIME_CHANGE.search(said)) and bool(_SCENE_VERB.match(said))
    if kinds == ["building"]:
        return False   # a lone house: blender_build's own path, unchanged
    if set(kinds) <= {"object"} and len(kinds) == 1:
        # one object: only when it is asked for as something new to model ("add a sofa", "create two chairs"), not
        # "make me a sandwich" (said to Jarvis) or "put the ball on the floor" (the ball that's there)
        t = tasks[0]
        word = t.get("word") or ""
        intro = re.search(rf"\b(?:a|an|another|one|two|three|four|five|six|some|several|\d+)\s+(?:[\w-]+\s+){{0,3}}"
                          rf"{re.escape(word)}", said, re.I)
        return bool(_STRICT_CREATE.match(said) and intro)
    return True


_QUESTION = re.compile(r"^(?:what|what's|whats|how|why|when|where|who|which|is|are|was|were|does|do|did|will|would|"
                       r"should|tell me|explain)\b(?!.*\b(?:create|build|make|animate|add)\b)", re.I)
_SCENE_VERB = re.compile(r"^(?:please |now |also |can you |could you )*(?:make|add|start|bring|change|switch|turn|set|"
                         r"let it|give it|put)\b", re.I)
_STRICT_CREATE = re.compile(r"^(?:please |can you |could you |now |also |let's |i want you to )*(?:create|build|model|"
                            r"generate|design|construct|add|put|place|spawn|insert)\b", re.I)


_CREATE_RE = re.compile(rf"^(?:please |can you |could you |now |also |let's )*(?:{_CREATE})\b", re.I)
# "move the car to the left", "rotate it 45 degrees": an edit of an object's place, for the object commands
_PLACE_EDIT = re.compile(r"^(?:please |now |also )*(?:move|shift|push|slide|put|place|set|rotate|turn|scale|resize|"
                         r"raise|lower|drag)\b.*\b(?:left|right|up|down|higher|lower|forward|forwards|backward|backwards|"
                         r"aside|closer|further|away|\d+(?:\.\d+)?\s*(?:m|cm|metres?|meters?|degrees?|°))\b", re.I)


def might_be_followup(text):
    """Whether `text` reads like a change to a scene's plan ("make it faster", "change the weather to snow"):
    worth reading the scene's stored plan for. Nothing is decided here."""
    t = _clean(text)
    return bool(_FASTER.search(t) or _SLOWER.search(t) or _MORE.search(t) or _FEWER.search(t) or
                _WEATHER_CHANGE.search(t) or _TIME_CHANGE.search(t) or _CAMERA_CHANGE.search(t) or
                (_REFINE.search(t) and re.search(r"\b(?:animation|motion|movement|walk)", t, re.I)))


# ---------- follow-ups: edits of the scene's plan ----------
_FASTER = re.compile(r"\b(?:faster|quicker|speed (?:it|him|her|them|\w+) up|more quickly|hurry)\b", re.I)
_SLOWER = re.compile(r"\b(?:slower|slow (?:it|him|her|them|\w+) down|more slowly)\b", re.I)
_MORE = re.compile(r"\b(?:add|put|make|give (?:it|me)|i want|with)?\s*(?:more|extra|additional|a few more|"
                   r"some more|lots more|many more)\s+(?P<what>[\w ]+?)(?=$|[,.;]|\s+(?:and|to|in|on|around)\b)", re.I)
_FEWER = re.compile(r"\b(?:fewer|less|remove some|not so many)\s+(?P<what>[\w ]+?)(?=$|[,.;]|\s+(?:and|from)\b)", re.I)
_WEATHER_CHANGE = re.compile(r"\b(?:change|switch|turn|make)\s+(?:the )?weather\s+(?:to|into)\s+(?P<w>\w+)|"
                             r"\bmake it (?P<w2>rain|snow|stormy|foggy|misty|windy|sunny|clear)\w*|"
                             r"\b(?:add|start|bring)\s+(?:some |a |the )?(?P<w3>rain|snow|fog|mist|wind|storm)\w*|"
                             r"\b(?:stop|remove|no more|get rid of|turn off)\s+(?:the )?(?P<off>rain|snow|fog|mist|"
                             r"wind|storm|weather)\w*", re.I)
_TIME_CHANGE = re.compile(r"\bmake it (?P<t>night|nighttime|day|daytime|sunset|sunrise|dawn|dusk|evening|morning)\b|"
                          r"\b(?:change|switch|set)\s+(?:the )?(?:time|lighting)\s+(?:of day )?to\s+(?P<t2>\w+)", re.I)
_CAMERA_CHANGE = re.compile(r"\b(?:make |have |let )?the camera\s+(?P<how>follow|track|chase|orbit|circle|zoom|"
                            r"get closer|move closer|go wider|pull back|stay still|stop moving)\w*(?:\s+(?:the )?"
                            r"(?P<what>[\w ]+?))?$|\b(?:switch|change)\s+(?:to )?(?:the |a )?(?P<shot>wide|close[- ]?up|"
                            r"orbit|follow|tracking|static)\s*(?:shot|camera|view)?", re.I)
_REFINE = re.compile(r"\b(?:improve|refine|polish|fix|smooth(?:en)?|make)\s+(?:the |his |her )?(?:animation|motion|"
                     r"movement|walk(?:ing)?|it)\s*(?:more )?(?:natural|realistic|better|smoother|look natural|"
                     r"until .*natural)?|look(?:s)? more natural|more natural(?:ly)?\b", re.I)
_RERENDER = re.compile(r"^(?:please |now |ok(?:ay)? )*(?:render|re-?render|make the video|export)\b(?P<rest>.*)$",
                       re.I)


def parse_followup(text, scene_plan):
    """Edits of the stored plan that `text` asks for, or None: [{"edit": ..., ...}]."""
    if not scene_plan or not scene_plan.get("tasks"):
        return None
    t = _clean(text)
    tasks = scene_plan["tasks"]
    edits = []
    motions = [x for x in tasks if x["kind"] in ("motion", "action")]
    if _FASTER.search(t) or _SLOWER.search(t):
        target = _target_motion(t, tasks) or (motions[-1] if motions else None)
        if target:
            edits.append({"edit": "speed", "task": target["id"], "factor": 1.5 if _FASTER.search(t) else 0.67})
    m = _MORE.search(t) or _FEWER.search(t)
    if m and not re.search(r"\b(?:natural|realistic|faster|slower)\b", m.group("what"), re.I):
        what = m.group("what").strip()
        ref = _ref(what, tasks)
        factor = 1.6 if _MORE.search(t) else 0.6
        if ref and ref.get("task"):
            edits.append({"edit": "more", "task": ref["task"], "items": ref.get("items"), "factor": factor,
                          "what": what})
        elif ref and ref.get("asset"):
            edits.append({"edit": "more", "asset": ref["asset"], "factor": factor, "what": what})
    m = _WEATHER_CHANGE.search(t)
    if m:
        off = m.group("off")
        w = (m.group("w") or m.group("w2") or m.group("w3") or "").lower()
        kind = next((k for pattern, k in _WEATHER if re.fullmatch(rf"(?:{pattern})", w, re.I)), None)
        if off:
            edits.append({"edit": "weather", "type": None if off == "weather" else next(
                (k for pattern, k in _WEATHER if re.fullmatch(rf"(?:{pattern})", off, re.I)), off), "remove": True})
        elif w in ("sunny", "clear", "nice"):
            edits.append({"edit": "weather", "type": None, "remove": True, "all": True})
        elif kind:
            edits.append({"edit": "weather", "type": kind, "intensity": "heavy" if _HEAVY.search(t) else None,
                          "replace": bool(m.group("w"))})
    m = _TIME_CHANGE.search(t)
    if m:
        word = (m.group("t") or m.group("t2") or "").lower()
        time = next((k for pattern, k in _TIME if re.search(rf"\b(?:{pattern})\b", word)), None)
        if time:
            edits.append({"edit": "lighting", "time": time})
    m = _CAMERA_CHANGE.search(t)
    if m:
        how = (m.group("how") or m.group("shot") or "").lower()
        shot = {"follow": "follow", "track": "follow", "chase": "follow", "tracking": "follow", "orbit": "orbit",
                "circle": "orbit", "wide": "establishing", "pull back": "establishing", "go wider": "establishing",
                "close-up": "closeup", "closeup": "closeup", "close up": "closeup", "zoom": "closeup",
                "get closer": "closeup", "move closer": "closeup", "static": "static", "stay still": "static",
                "stop moving": "static"}.get(how, "follow")
        subject = None
        if m.group("what"):
            ref = _ref(m.group("what"), tasks)
            subject = ref.get("task") if ref else None
            if subject is None and re.search(r"\b(?:character|person|man|woman|him|her)\b", m.group("what"), re.I):
                subject = next((x["id"] for x in reversed(tasks) if x["kind"] == "character"), None)
        edits.append({"edit": "camera", "shot": shot, "subject": subject})
    if _REFINE.search(t) and motions and not edits:
        edits.append({"edit": "refine", "task": motions[-1]["id"]})
    m = _RERENDER.match(t)
    if m:
        edits.append({"edit": "render", "quality": "final" if _FINAL.search(t) else "preview"})
    return edits or None


def _target_motion(text, tasks):
    for x in reversed(tasks):
        if x["kind"] not in ("motion", "action"):
            continue
        subject = next((s for s in tasks if s["id"] == x.get("subject")), None)
        if subject and re.search(rf"\b{re.escape((subject.get('word') or subject.get('asset') or '').replace('_', ' '))}",
                                 text, re.I):
            return x
    return None


def apply_edits(scene_plan, edits):
    """The plan after `edits`, and which kinds of stage they touch (only those are redone)."""
    plan = copy.deepcopy(scene_plan)
    tasks = plan["tasks"]
    touched = set()
    n = len(tasks)

    def new(kind, **kw):
        nonlocal n
        n += 1
        t = {"id": f"t{n}", "kind": kind}
        t.update({k: v for k, v in kw.items() if v is not None})
        tasks.append(t)
        return t

    for e in edits:
        kind = e["edit"]
        if kind == "speed":
            t = next(x for x in tasks if x["id"] == e["task"])
            t["speed"] = round((t.get("speed") or 1.0) * e["factor"], 3)
            touched |= {"motion", "camera", "render"}
        elif kind == "more":
            t = next((x for x in tasks if x["id"] == e.get("task")), None)
            if t and t["kind"] == "environment":
                key = "density"
                t[key] = round((t.get(key) or 1.0) * e["factor"], 3)
                touched |= {"environment", "object", "motion", "camera", "render"}
            elif t and t["kind"] == "object":
                t["count"] = max(1, int(round(t.get("count", 1) * e["factor"] + (1 if e["factor"] > 1 else 0))))
                touched |= {"object", "camera", "render"}
            elif e.get("asset"):
                new("object", asset=e["asset"], count=3, word=e.get("what"))
                touched |= {"object", "camera", "render"}
        elif kind == "weather":
            if e.get("remove"):
                tasks[:] = [x for x in tasks if not (x["kind"] == "weather" and (e.get("all") or x["type"] == e["type"]))]
            else:
                if e.get("replace") or e["type"] in ("snow", "rain"):
                    tasks[:] = [x for x in tasks if not (x["kind"] == "weather" and x["type"] in ("rain", "snow",
                                                                                                    "storm"))]
                new("weather", type=e["type"], intensity=e.get("intensity"))
            touched |= {"weather", "render"}
        elif kind == "lighting":
            tasks[:] = [x for x in tasks if x["kind"] != "lighting"]
            new("lighting", time=e["time"])
            touched |= {"lighting", "render"}
        elif kind == "camera":
            subject = e.get("subject") or next((x.get("subject") for x in tasks if x["kind"] == "camera"), None)
            tasks[:] = [x for x in tasks if x["kind"] != "camera"]
            new("camera", shot=e["shot"], subject=subject)
            touched |= {"camera", "render"}
        elif kind == "refine":
            t = next(x for x in tasks if x["id"] == e["task"])
            t["refine"] = (t.get("refine") or 0) + 1
            touched |= {"motion", "camera", "render"}
        elif kind == "render":
            tasks[:] = [x for x in tasks if x["kind"] != "render"]
            new("render", quality=e.get("quality", "preview"), video=True)
            touched |= {"render"}
    return plan, touched


def merge(scene_plan, plan):
    """A new request said to a scene that already has a plan: its tasks join the scene's (ids kept unique)."""
    if not scene_plan:
        return plan
    out = copy.deepcopy(scene_plan)
    out["tasks"] += copy.deepcopy(plan["tasks"])
    # one camera, one render, one time of day: the newest wins
    for kind in ("camera", "render", "lighting"):
        same = [t for t in out["tasks"] if t["kind"] == kind]
        for t in same[:-1]:
            out["tasks"].remove(t)
    out["said"] = plan["said"]
    return out


# ---------- the local AI, for what the vocabularies don't read ----------
SCHEMA = """Answer with ONLY a JSON object {"tasks": [...]}. Each task has "id" ("t1", "t2"...) and "kind":
- {"kind":"environment","type": one of %(envs)s, "style": "futuristic"|"modern"|"old"|null}
- {"kind":"building","noun":"villa"|"house"|"mansion"|"cottage"}
- {"kind":"object","asset": one of %(assets)s, "count": n, "color": colour name or null}
- {"kind":"object","asset":"composite","name": what it is, "parts":[{"shape":"box"|"cyl"|"sphere","size":[x,y,z] metres,
   "at":[x,y,z] centre of its bottom, "mat": one of %(mats)s}]}   (for anything not in the asset list)
- {"kind":"character","template":"man"|"woman"}
- {"kind":"action","subject": id of a character,"steps":[{"do": one of %(acts)s, "target": {"task": id} or null}]}
- {"kind":"motion","subject": id of an object,"steps":[{"do":"fly"|"drive"|"move"|"orbit"|"spin"|"hover"|"bounce",
   "rel":"between"|"around"|"to"|"across"|"along"|"over", "target": {"task": id} or {"asset": name}}]}
- {"kind":"weather","type":"rain"|"snow"|"fog"|"storm"|"wind"} {"kind":"lighting","time":"day"|"night"|"sunset"|"sunrise"}
- {"kind":"camera","shot":"follow"|"orbit"|"establishing"|"closeup"|"static","subject": id}
- {"kind":"render","quality":"preview"|"final","video": true}"""


def ai_prompt(text):
    return SCHEMA % {"envs": sorted(world_library.ENVIRONMENTS), "assets": sorted(world_library.RECIPES),
                     "mats": sorted(world_library.MATERIALS), "acts": [
                         "walk", "run", "jump", "sit", "stand", "eat", "drink", "dance", "wave", "talk", "phone", "point",
                         "pick_up", "put_down", "carry", "open_door", "enter", "close_door", "fight", "work", "wait"]} + \
        f"\n\nRequest: {text}"


def ai_plan(text, ask, known=None):
    """The local AI's plan for `text` (`ask(messages) -> str`), checked field by field; `known` (the vocabulary's
    own plan, if any) is kept and the AI's adds only what it lacks. None when the answer can't be used."""
    try:
        answer = ask([{"role": "system", "content": "You turn requests for 3D scenes into JSON plans."},
                      {"role": "user", "content": ai_prompt(text)}])
    except Exception:
        return None
    m = re.search(r"\{.*\}", answer or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    tasks = validate(data.get("tasks") if isinstance(data, dict) else None)
    if not tasks:
        return None
    if known:
        have = {(t["kind"], t.get("asset") or t.get("type") or t.get("template")) for t in known["tasks"]}
        extra = [t for t in tasks if (t["kind"], t.get("asset") or t.get("type") or t.get("template")) not in have
                 and t["kind"] in ("object", "environment")]
        base = len(known["tasks"])
        for i, t in enumerate(extra, 1):
            t["id"] = f"t{base + i}"
        out = Plan(tasks=known["tasks"] + extra, said=known["said"], unknown=[])
        return out
    return Plan(tasks=tasks, said=text, unknown=[])


_ALLOWED = {"environment": {"type": set(world_library.ENVIRONMENTS)}, "weather": {"type": {"rain", "snow", "fog", "storm",
                                                                                          "wind", "wet"}},
            "lighting": {"time": {"day", "night", "sunset", "sunrise", "overcast", None}},
            "camera": {"shot": {"follow", "track", "orbit", "establishing", "closeup", "static", "cinematic"}},
            "character": {"template": set(anim_library.CHARACTERS)}}


def validate(tasks):
    """Only tasks Jarvis can do, with only fields of the right kind: an AI's answer is data, never trusted."""
    if not isinstance(tasks, list):
        return []
    out = []
    ids = set()
    for t in tasks[:40]:
        if not isinstance(t, dict) or t.get("kind") not in ("environment", "building", "object", "character", "action",
                                                            "motion", "weather", "lighting", "camera", "render"):
            continue
        t = {k: v for k, v in t.items() if isinstance(k, str) and len(k) < 20}
        ok = True
        for field, allowed in _ALLOWED.get(t["kind"], {}).items():
            if t.get(field) not in allowed:
                ok = False
        if t["kind"] == "object":
            if t.get("asset") == "composite":
                parts = [p for p in (t.get("parts") or [])[:40] if isinstance(p, dict) and p.get("shape") in (
                    "box", "cyl", "sphere") and _vec(p.get("size")) and _vec(p.get("at"))]
                if not parts:
                    ok = False
                for p in parts:
                    p["mat"] = p.get("mat") if p.get("mat") in world_library.MATERIALS else "plastic"
                    p["size"] = [max(0.01, min(50.0, float(v))) for v in p["size"]]
                    p["at"] = [max(-50.0, min(50.0, float(v))) for v in p["at"]]
                t["parts"] = parts
                t["name"] = str(t.get("name") or "object")[:40]
            elif t.get("asset") not in world_library.RECIPES:
                ok = False
            t["count"] = max(1, min(60, int(t.get("count") or 1))) if str(t.get("count", 1)).isdigit() or isinstance(
                t.get("count"), int) else 1
        if t["kind"] in ("action", "motion"):
            t["steps"] = [s for s in (t.get("steps") or []) if isinstance(s, dict) and isinstance(s.get("do"), str)][:20]
            if not t["steps"]:
                ok = False
        if not ok:
            continue
        t["id"] = str(t.get("id") or f"t{len(out) + 1}")
        if t["id"] in ids:
            t["id"] = f"t{len(out) + 1}x"
        ids.add(t["id"])
        out.append(t)
    return out


def _vec(v):
    return isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v)


# ---------- the order things are done in ----------
STAGE_ORDER = ["environment", "building", "object", "character", "lighting", "weather", "motion", "camera", "render"]


def stage_of(task):
    return {"action": "motion"}.get(task["kind"], task["kind"])


def with_defaults(plan):
    """What a scene needs that wasn't said: a camera when something moves (following it), a video of what moves,
    something to stand on for characters, daylight when no time was said."""
    plan = copy.deepcopy(plan)
    tasks = plan["tasks"]
    kinds = {t["kind"] for t in tasks}
    n = max([int(re.sub(r"\D", "", t["id"]) or 0) for t in tasks] + [0])

    def new(kind, **kw):
        nonlocal n
        n += 1
        t = {"id": f"t{n}", "kind": kind, "default": True}
        t.update(kw)
        tasks.append(t)
        return t

    moving = [t for t in tasks if t["kind"] in ("motion", "action")]
    if "lighting" not in kinds:
        new("lighting", time="day")
    if moving and "camera" not in kinds:
        # a person is watched from the front three-quarters (what they do shows); a vehicle is chased
        person = moving[0]["kind"] == "action"
        new("camera", shot="track" if person else "follow", subject=moving[0]["subject"])
    if "camera" not in kinds and not moving:
        new("camera", shot="establishing", subject=None)
    if moving and "render" not in kinds:
        new("render", quality="preview", video=True)
    if not ({"environment", "building"} & kinds) and ({"character", "object"} & kinds):
        tasks.insert(0, {"id": "t0", "kind": "environment", "type": "ground", "default": True})
    return plan


def _plural(word):
    if re.search(r"(?:s|x|z|ch|sh)$", word):
        return word + "es"
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    return word + "s"


def describe(plan):
    """The plan in a sentence, for the first thing Jarvis says."""
    parts = []
    for t in plan["tasks"]:
        k = t["kind"]
        if t.get("default"):
            continue
        if k == "environment":
            parts.append(f"a {(t.get('style') + ' ') if t.get('style') else ''}{t.get('room') or t['type']}")
        elif k == "building":
            parts.append(f"a {t['noun']}")
        elif k == "object":
            name = t.get("name") or t["asset"].replace("_", " ")
            parts.append(f"{t['count']} {_plural(name)}" if t.get("count", 1) > 1 else f"a {name}")
        elif k == "character":
            parts.append(f"a {t['template']}")
        elif k in ("action", "motion"):
            parts.append(" then ".join(s["do"].replace("_", " ") for s in t["steps"]))
        elif k == "weather":
            parts.append(t["type"])
        elif k == "lighting" and t.get("time"):
            parts.append(t["time"])
        elif k == "camera":
            parts.append(f"a {t['shot']} camera")
        elif k == "render":
            parts.append(f"a {t['quality']} video" if t.get("video") else "a picture")
    return ", ".join(parts)
