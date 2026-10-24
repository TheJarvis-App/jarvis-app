"""The 3D projector's decisions and safety checks (projector.py): when a model is asked for, what the AI's plan may
contain, and the facts computed rather than guessed."""
import time

import projector


def test_asks_for_a_model_only_when_a_shape_helps():
    yes = ["show me a sunflower", "what does DNA look like", "what's inside a computer", "how does a car engine work",
           "show me a carbon atom in 3d", "explain a black hole", "show me a 3D model of a heart", "show me z = sin(x)*cos(y) in 3d"]
    no = ["what is the capital of france", "show me a picture of a cat", "what time is it", "show me the weather",
          "tell me about saturn", "show me my files", "play some music", "how far is tokyo from paris"]
    for t in yes:
        assert projector.wants_model(t), t
    for t in no:
        assert not projector.wants_model(t), t


def test_follow_ups_refer_to_the_last_model():
    previous = {"title": "Rose", "generator": "flower", "part_names": ["Petal"], "at": time.time()}
    assert projector.wants_model("show me its internal structure", previous)
    assert projector.wants_model("explain how pollination works", previous)
    assert not projector.wants_model("show me its internal structure", {**previous, "at": time.time() - 3600})
    assert "Rose" in projector.build_messages("show me its inside", previous)[1]["content"]


def test_the_plan_is_read_from_the_ai_reply():
    assert projector.parse_reply('Sure! ```json\n{"visual": true, "a": {"b": 1}}\n```') == {"visual": True, "a": {"b": 1}}
    assert projector.parse_reply("no json here") is None
    assert projector.parse_reply('{"visual": tru') is None


def test_only_allowed_builders_shapes_colours_and_sizes_reach_the_window():
    assert projector.sanitize({"visual": False}) is None
    assert projector.sanitize({"visual": True, "generator": "javascript"}) is None
    spec = projector.sanitize({"visual": True, "title": "Chair", "generator": "parts", "parts": [
        {"name": "Seat<script>", "shape": "box", "size": [99, -5, "x"], "at": [100, 0, 0], "color": "red", "material": "lava"},
        {"name": "Bad", "shape": "teapot"}]})
    assert len(spec["parts"]) == 1
    seat = spec["parts"][0]
    assert seat["name"] == "Seatscript" and seat["size"] == [3, 0.01, 0.4] and seat["at"][0] == 2.5
    assert seat["color"] == "#9fb3c8" and seat["material"] == "matte"
    assert spec["honesty"] and spec["kicker"] == "3D illustration"


def test_surface_formulas_are_checked():
    assert projector.clean_expression("z = sin(x)*cos(y)") == "sin(x)*cos(y)"
    assert projector.clean_expression("x**2 - y^2") == "x^2 - y^2"
    for bad in ["alert(1)", "x; fetch()", "constructor", "process.exit()", "(x"]:
        assert projector.clean_expression(bad) is None, bad
    assert projector.sanitize({"visual": True, "generator": "surface", "params": {"expr": "window.close()"}}) is None


def test_atoms_are_counted_not_guessed():
    assert projector.element("C")["shells"] == [2, 4]
    assert projector.element("iron")["shells"] == [2, 8, 14, 2]
    assert projector.element("Cu")["shells"] == [2, 8, 18, 1]
    assert projector.element("Cr")["shells"] == [2, 8, 13, 1]
    assert projector.element("aluminum")["z"] == 13
    assert projector.element("Kr")["neutrons"] == 48
    assert projector.element("Unobtainium") is None
    for z in range(1, 37):
        assert sum(projector.shells(z)) == z
    spec = projector.sanitize({"visual": True, "title": "Carbon", "generator": "atom", "params": {"element": "C"}})
    assert spec["exact"] and "6 protons, 6 neutrons" in spec["facts"][0]


def test_gear_ratios_and_known_molecules_are_exact():
    spec = projector.sanitize({"visual": True, "title": "Gears", "generator": "gears", "params": {"teeth": [12, 36]}})
    assert "36:12 = 3.00" in spec["facts"][0] and "the other way round" in spec["facts"][0]
    assert "0.33 times" in spec["info"]["Gear 2"]
    water = projector.sanitize({"visual": True, "title": "Water", "generator": "molecule", "params": {"name": "water"}})
    assert water["exact"] and "104.5" in water["facts"][0]
    assert set(water["part_names"]) == {"Hydrogen", "Oxygen", "Bonds"} and all(water["info"].values())


def test_builders_use_their_own_checked_words():
    spec = projector.sanitize({"visual": True, "title": "Engine", "generator": "engine", "info": {"Piston": "made up"}})
    assert spec["info"]["Piston"].startswith("Pushed down")
    assert set(spec["part_names"]) == set(projector.CURATED["engine"])
    rose = projector.sanitize({"visual": True, "title": "Rose", "generator": "flower", "params": {"petals": 24, "composite": True, "cutaway": True}})
    assert rose["params"]["composite"] and not rose["params"]["cutaway"]   # a composite head has no single pistil to open


def test_what_jarvis_says():
    spec = projector.sanitize({"visual": True, "title": "DNA", "generator": "helix", "explanation": "Two strands twisted together."})
    assert projector.spoken(spec).startswith("Two strands twisted together.")


def test_two_subjects_side_by_side():
    assert projector.wants_model("compare a rose and a sunflower") and projector.wants_model("what's the difference between dna and rna")
    assert not projector.wants_model("compare the price of two phones")
    rose = {"title": "Rose", "generator": "flower", "params": {"petals": 30, "cutaway": True}, "info": {"Petal": "AI words"}}
    spec = projector.sanitize({"visual": True, "title": "Rose vs Carbon", "explanation": "One grows, one bonds.",
                               "compare": [rose, {"title": "Carbon", "generator": "atom", "params": {"element": "C"}}],
                               "focus": ["Rose: Stamen"]}, "compare a rose and carbon")
    assert spec["generator"] == "compare" and [m["generator"] for m in spec["models"]] == ["flower", "atom"]
    assert "Rose: Petal" in spec["part_names"] and "Carbon: Nucleus" in spec["part_names"]
    assert spec["info"]["Rose: Petal"] == projector.CURATED["flower"]["Petal"]   # the checked words, as for one model
    assert spec["params"]["cutaway"] and spec["focus"] == ["Rose: Stamen"]
    assert any(f.startswith("Carbon: Atomic number 6") for f in spec["facts"])
    assert spec["kicker"] == "3D comparison" and spec["honesty"]   # the flower is an illustration
    # one that can't be drawn: the other is shown alone, with the comparison's words
    one = projector.sanitize({"visual": True, "explanation": "Words.", "compare": [rose, {"generator": "warp drive"}]}, "q")
    assert one["generator"] == "flower" and one["explanation"] == "Words."
    same = projector.sanitize({"visual": True, "compare": [rose, rose]})
    assert [m["title"] for m in same["models"]] == ["Rose", "Rose 2"]


def test_everyday_subjects_have_their_own_builders():
    for text, gen, key, value in [("show me tv", "device", "kind", "tv"), ("show me dog", "animal", "kind", "dog"),
                                  ("show me iron man", "humanoid", "preset", "ironman"), ("show me spiderman", "humanoid", "preset", "spiderman"),
                                  ("show me a house", "building", "kind", "house"), ("show me a shoe", "shoe", None, None),
                                  ("what's inside a laptop", "device", "kind", "laptop"), ("show me the eiffel tower", "building", "kind", "eiffel"),
                                  ("how does a car engine work", "engine", None, None), ("show me a heart", "heart", None, None)]:
        assert projector.wants_model(text), text
        title, g, params = projector.catalog(text)[0]
        assert g == gen and (key is None or params[key] == value), text
    # the AI is told which builder to use, and that a "show me" must be drawn
    msg = projector.build_messages("show me dog", None)[1]["content"]
    assert '"kind": "dog"' in msg and "visual true" in msg
    assert [t for t, _, _ in projector.catalog("compare a dog and a cat")] == ["Dog", "Cat"]


def test_a_known_subject_is_drawn_even_when_the_ai_declines():
    spec = projector.fallback("show me iron man")
    assert spec["generator"] == "humanoid" and spec["params"]["preset"] == "ironman"
    assert "Arc Reactor" in spec["part_names"] and spec["info"]["Arc Reactor"] and spec["explanation"]
    both = projector.fallback("compare a dog and a cat")
    assert both["generator"] == "compare" and [m["title"] for m in both["models"]] == ["Dog", "Cat"]
    assert projector.fallback("show me my feelings") is None
    assert projector.explicit("show me a dog") and not projector.explicit("explain a black hole")


def test_new_builders_only_get_allowed_variants_and_colours():
    s = projector.sanitize({"visual": True, "generator": "animal", "params": {"kind": "dragon", "color": "red; drop"}})
    assert s["params"]["kind"] == "dog" and s["params"]["color"] == "#9fb3c8"
    s = projector.sanitize({"visual": True, "generator": "humanoid", "params": {"preset": "Captain America", "color": "#123456"}})
    assert s["params"] == {"preset": "captain_america", "color": "#123456"}
    s = projector.sanitize({"visual": True, "generator": "building", "params": {"kind": "house", "floors": 9}})
    assert s["params"]["floors"] == 3 and "Chimney" in s["part_names"]
    s = projector.sanitize({"visual": True, "generator": "parts", "parts": [
        {"name": "Vase", "shape": "lathe", "profile": [[0.2, 0], [0.4, 0.5], [0.1, 1]], "material": "gloss"},
        {"name": "Wing", "shape": "extrude", "size": [0.05], "outline": [[0, 0], [1, 0], [0.5, 0.4]]},
        {"name": "Bad", "shape": "lathe", "profile": [[1, 1]]}]})
    assert [p["name"] for p in s["parts"]] == ["Vase", "Wing"] and s["parts"][0]["material"] == "gloss"


def test_the_shipped_library_matches_this_file():
    import json, os
    lib = projector.library()
    with open(os.path.join(os.path.dirname(projector.__file__), "projector", "library.json"), encoding="utf-8") as f:
        assert json.load(f) == json.loads(json.dumps(lib)), "run projector.write_library()"
    assert len(lib) >= 50 and all(s["explanation"] and s["part_names"] for s in lib)
    for s in lib:   # every part has words, so picking one always explains something
        missing = [n for n in s["part_names"] if not s["info"].get(n)]
        assert not missing, (s["title"], missing)
