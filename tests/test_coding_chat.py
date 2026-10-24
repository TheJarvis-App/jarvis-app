"""Coding Mode as one conversation per project (code_chat.py, app.py's coding_* functions), the How to run guide worked
out from a project's real files (code_run.py), the dependency check, Stop, and the explorer's file operations.
The AI is a stand-in; nothing here runs generated code or opens a real app."""
import json
import os
import threading

import pytest

import sandbox

app = None
PLAN = ("PROJECT: racing-site\nLANGUAGE: HTML/CSS/JavaScript\nSUMMARY: A racing website.\nRUN: open index.html\nTEST: none\nNEEDS: none\n"
        "FILES:\nindex.html | the page\nstyles.css | the look\nscript.js | the behaviour\n")
SITE = ("=== FILE: index.html ===\n<!doctype html><html><head><link rel=\"stylesheet\" href=\"styles.css\"></head>"
        "<body><h1>Racing</h1><script src=\"script.js\"></script></body></html>\n=== END FILE ===\n"
        "=== FILE: styles.css ===\nbody { background: #000; }\n=== END FILE ===\n"
        "=== FILE: script.js ===\nconsole.log('go');\n=== END FILE ===\n")
DARKER = "SUMMARY: Made it darker.\n=== FILE: styles.css ===\nbody { background: #050505; color: #eee; }\n=== END FILE ===\n"


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    app.real_code_chat_for_test = imported._code_chat   # the fixture below replaces it; the limit test calls the real one
    yield
    sandbox.uninstall()


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    sandbox.reset()
    monkeypatch.setenv("CODE_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(app.coder, "HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(app.coder, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(app.code_chat, "CHATS_DIR", str(tmp_path / "chats"))
    monkeypatch.setattr(app, "ws_loop", None)
    app.code_state.update(open=False, job=None, project=None, busy=False, at=0.0, thread="", stop=None, status="")
    asked = []

    def chat(messages, max_tokens, model=""):
        user = messages[-1]["content"]
        asked.append(user)
        if "Plan the smallest" in user:
            return PLAN
        if "existing project" in user:
            return DARKER
        if "The user asks:" in user and "Answer in plain language" in user:
            return "Open **index.html** in your browser."
        return SITE
    monkeypatch.setattr(app, "_code_chat", chat)
    sent = []
    monkeypatch.setattr(app, "send_ui_update_once", sent.append)
    return {"asked": asked, "sent": sent}


def route_to(monkeypatch, *actions):
    answers = list(actions)
    monkeypatch.setattr(app, "_route_ask", lambda prompt: json.dumps({"action": answers.pop(0)}))


def chat_now():
    return app.code_chat.load(app.code_state["thread"])


# ---- one chat, many requests ----
def test_build_then_change_then_ask_all_in_the_same_chat_and_project(monkeypatch, tmp_path, fresh):
    route_to(monkeypatch, "create", "change", "answer")
    app.coding_send("", "Build me a professional website about racing")
    thread = chat_now()
    folder = tmp_path / "projects" / "racing-site"
    assert thread["path"] == str(folder) and sorted(os.listdir(folder)) == ["index.html", "script.js", "styles.css"]
    assert thread["title"] == "Build me a professional website about racing"

    app.coding_send(thread["id"], "Make the design darker and more modern")
    assert chat_now()["id"] == thread["id"]                                # the same chat
    assert (folder / "styles.css").read_text() == "body { background: #050505; color: #eee; }\n"
    assert sorted(os.listdir(tmp_path / "projects")) == ["racing-site"]    # the same project, not a new one
    change_prompt = next(p for p in fresh["asked"] if "existing project" in p)
    assert "Build me a professional website about racing" in change_prompt   # it saw the conversation

    app.coding_send(thread["id"], "How do I run it?")
    last = chat_now()["messages"][-1]
    assert last["role"] == "jarvis" and last["kind"] == "text" and "index.html" in last["text"]
    kinds = [f"{m['role']}:{m['kind']}" for m in chat_now()["messages"]]
    assert kinds == ["user:text", "jarvis:work", "jarvis:result", "user:text", "jarvis:work", "jarvis:result", "user:text", "jarvis:text"]
    assert not app.code_state["busy"]


def test_the_plan_is_told_not_to_default_to_python(monkeypatch, fresh):
    route_to(monkeypatch, "create")
    app.coding_send("", "Build a calculator I can see and click")
    plan = next(p for p in fresh["asked"] if "Plan the smallest" in p)
    assert "never the default" in plan and "user interface" in plan and "How to run" in plan


def test_a_separate_project_gets_its_own_chat(monkeypatch, tmp_path):
    route_to(monkeypatch, "create", "new")
    app.coding_send("", "Build me a racing website")
    first = chat_now()["id"]
    app.coding_send(first, "Now build me a completely different app: a recipe book")
    assert chat_now()["id"] != first
    assert "separate project" in app.code_chat.load(first)["messages"][-1]["text"]
    assert len(os.listdir(tmp_path / "projects")) == 2


def test_one_request_at_a_time(monkeypatch, fresh):
    app.code_state["busy"] = True
    app.coding_send("", "Build me a racing website")
    assert fresh["sent"][-1] == {"type": "coding_note", "message": "I'm still working on the last request. Wait for it, or press Stop."}
    assert app.code_chat.threads() == []


def test_when_the_ai_cannot_route_the_safe_guess_is_used(monkeypatch):
    def broken(prompt):
        raise RuntimeError("offline")
    monkeypatch.setattr(app, "_route_ask", broken)
    thread = {"messages": []}
    assert app.code_chat.route("Build a website", thread, None, broken)["action"] == "create"
    project = {"name": "x", "files": []}
    assert app.code_chat.route("why didn't it work?", thread, project, broken)["action"] == "answer"
    assert app.code_chat.route("add a login page", thread, project, broken)["action"] == "change"


@pytest.mark.parametrize("said, wanted", [
    ("run it", {"action": "run"}), ("open the app", {"action": "run"}), ("run the tests", {"action": "tests"}),
    ("Now open the finished project in VS Code", {"action": "open", "where": "vscode"}),
    ("show it in the folder", {"action": "open", "where": "folder"}),
    ("make a zip of it", {"action": "deliver", "where": "zip"}),
    ("put it in a Word document", {"action": "deliver", "where": "word"}),
])
def test_plain_commands_need_no_ai(said, wanted):
    assert app.code_chat.quick_route(said, have_project=True) == wanted
    assert app.code_chat.quick_route(said, have_project=False) is None


def test_routes_the_ai_cannot_misuse():
    thread, ask = {"messages": []}, lambda answer: (lambda prompt: json.dumps({"action": answer}))
    assert app.code_chat.route("make it blue", thread, None, ask("change"))["action"] == "create"     # nothing to change yet
    assert app.code_chat.route("go", thread, None, ask("run"))["action"] == "answer"
    assert app.code_chat.route("x y", thread, {"name": "p"}, ask("create"))["action"] == "change"   # a project exists
    assert app.code_chat.route("x y", thread, {"name": "p"}, ask("explode"))["action"] == "change"  # not an action: the safe guess


# ---- running it asks first ----
def test_run_asks_first_and_starts_only_after_yes(monkeypatch, tmp_path):
    route_to(monkeypatch, "create")
    app.coding_send("", "Build me a racing website")
    launched = []
    monkeypatch.setattr(app.code_run, "launch", lambda root, plan: launched.append(plan["launch"]) or "Opened index.html in your browser.")
    thread_id = app.code_state["thread"]
    app.coding_send(thread_id, "run it")
    asked = chat_now()["messages"][-1]
    assert asked["kind"] == "confirm" and "index.html" in asked["text"] and not launched
    app.coding_confirm(thread_id, asked["id"], False)
    assert not launched and chat_now()["messages"][-1]["text"] == "Okay, I didn't start it."
    app.coding_confirm(thread_id, asked["id"], True)        # already answered: a second answer does nothing
    assert not launched
    app.coding_send(thread_id, "run it")
    again = chat_now()["messages"][-1]
    app.coding_confirm(thread_id, again["id"], True)
    assert launched[0]["type"] == "browser" and launched[0]["path"].endswith("index.html")
    assert chat_now()["messages"][-1]["text"] == "Opened index.html in your browser."


# ---- Stop ----
@pytest.mark.parametrize("stop_on, said, kept", [(2, "Stopped before any file was written.", []),
                                                  (3, "Stopped. 4 files had been written to racing-site by then; the project is incomplete.",
                                                   ["a.js", "index.html", "script.js", "styles.css"])])
def test_stop_keeps_what_was_written_and_says_it_is_incomplete(monkeypatch, tmp_path, stop_on, said, kept):
    route_to(monkeypatch, "create")
    calls = {"n": 0}
    first = SITE + "=== FILE: a.js ===\nlet a;\n=== END FILE ===\n"          # the first four files
    rest = "=== FILE: b.js ===\nlet b;\n=== END FILE ===\n=== FILE: c.js ===\nlet c;\n=== END FILE ===\n"

    def chat(messages, max_tokens, model=""):
        calls["n"] += 1
        if calls["n"] == 1:
            return PLAN.replace("script.js | the behaviour\n", "script.js | the behaviour\na.js | a\nb.js | b\nc.js | c\n")
        if calls["n"] == stop_on:
            app.code_state["stop"].set()          # Stop pressed while this batch was being written
        return first if calls["n"] == 2 else rest
    monkeypatch.setattr(app, "_code_chat", chat)
    app.coding_send("", "Build me a racing website")
    result = chat_now()["messages"][-1]
    assert result["phase"] == "stopped" and result["text"] == said and calls["n"] == stop_on and not app.code_state["busy"]
    folder = tmp_path / "projects" / "racing-site"
    assert (sorted(os.listdir(folder)) if folder.exists() else []) == kept    # the answer that came back after Stop was not used


def test_stopping_a_change_changes_nothing(monkeypatch, tmp_path):
    route_to(monkeypatch, "create", "change")
    app.coding_send("", "Build me a racing website")
    css = tmp_path / "projects" / "racing-site" / "styles.css"
    before = css.read_text()

    def chat(messages, max_tokens, model=""):
        app.code_state["stop"].set()
        return DARKER
    monkeypatch.setattr(app, "_code_chat", chat)
    app.coding_send(app.code_state["thread"], "make it darker")
    assert css.read_text() == before and chat_now()["messages"][-1]["text"] == "Stopped. Nothing was changed."


# ---- the explorer ----
def test_file_operations_stay_inside_the_project_and_keep_copies(monkeypatch, tmp_path, fresh):
    route_to(monkeypatch, "create")
    app.coding_send("", "Build me a racing website")
    tid, folder = app.code_state["thread"], tmp_path / "projects" / "racing-site"
    notes = lambda: [m["data"] for m in fresh["sent"] if m["type"] == "coding_fs"]
    app.coding_file_op({"thread": tid, "op": "newfile", "path": "assets/logo.svg"})
    app.coding_file_op({"thread": tid, "op": "save", "path": "assets/logo.svg", "content": "<svg/>"})
    app.coding_file_op({"thread": tid, "op": "rename", "path": "assets/logo.svg", "to": "assets/mark.svg"})
    app.coding_file_op({"thread": tid, "op": "mkdir", "path": "pages"})
    app.coding_file_op({"thread": tid, "op": "delete", "path": "script.js"})
    assert (folder / "assets" / "mark.svg").read_text() == "<svg/>" and (folder / "pages").is_dir() and not (folder / "script.js").exists()
    assert all(n["ok"] for n in notes()), notes()
    assert any(p.endswith("script.js") for p in map(str, (tmp_path / "backups").rglob("*")))   # the deleted file was copied first
    app.coding_file_op({"thread": tid, "op": "save", "path": "../../escape.txt", "content": "x"})
    app.coding_file_op({"thread": tid, "op": "rename", "path": "index.html", "to": "/tmp/x.html"})
    assert not notes()[-1]["ok"] and not notes()[-2]["ok"] and not (tmp_path / "escape.txt").exists()
    app.code_state["busy"] = True
    app.coding_file_op({"thread": tid, "op": "delete", "path": "index.html"})
    assert (folder / "index.html").exists() and "working on this project" in notes()[-1]["message"]
    app.code_state["busy"] = False
    tree = {f["path"]: f for f in app.code_tree(app.project_by_path(str(folder)))}
    assert tree["index.html"]["mark"] == "new" and "pages/" in tree and "script.js" not in tree


def test_projects_from_before_chats_are_listed_and_get_a_chat(monkeypatch, tmp_path, fresh):
    route_to(monkeypatch, "create")
    app.coding_send("", "Build me a racing website")
    folder = str(tmp_path / "projects" / "racing-site")
    app.code_chat.delete(app.code_state["thread"])
    listed = app.code_threads_list()
    assert listed[0]["id"] == "" and listed[0]["path"] == folder and listed[0]["project"]
    app.coding_window_says({"type": "code_open_thread", "project": listed[0]["project"]})
    opened = [m for m in fresh["sent"] if m["type"] == "coding_thread"][-1]["data"]
    assert opened["thread"]["path"] == folder and opened["project"]["guide"]["kind"] == "web"


# ---- How to run, from the real files ----
def make(tmp_path, files: dict):
    root = tmp_path / "p"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return str(root)


def commands(guide):
    return [s.get("command") for s in guide["steps"] if s.get("command")]


def test_guide_static_site_opens_in_the_browser(tmp_path):
    g = app.code_run.guide(make(tmp_path, {"index.html": "<script src='a.js'></script>", "a.js": "1"}))
    assert g["kind"] == "web" and g["launch"]["type"] == "browser" and g["launch"]["path"].endswith("index.html")


def test_guide_module_site_needs_a_local_server(tmp_path):
    g = app.code_run.guide(make(tmp_path, {"index.html": "<script type='module' src='a.js'></script>", "a.js": "import x from './b.js'"}))
    assert g["kind"] == "web-server" and "-m http.server 8000" in g["launch"]["command"] and g["launch"]["url"] == "http://localhost:8000/"


def test_guide_vite_react(tmp_path):
    pkg = {"scripts": {"dev": "vite"}, "dependencies": {"react": "18"}, "devDependencies": {"vite": "5"}}
    g = app.code_run.guide(make(tmp_path, {"package.json": json.dumps(pkg), "src/main.jsx": "", "index.html": ""}))
    assert g["stack"] == "React + Vite + JavaScript (Node.js)" and commands(g)[1:4] == ["npm install", "npm run dev", "http://localhost:5173"]
    assert g["launch"]["installs"] and g["launch"]["command"] == "npm install && npm run dev"


def test_guide_express_finds_its_port(tmp_path):
    pkg = {"scripts": {"start": "node server.js"}, "dependencies": {"express": "4"}}
    g = app.code_run.guide(make(tmp_path, {"package.json": json.dumps(pkg), "server.js": "app.listen(4000)"}))
    assert "npm start" in commands(g) and g["launch"]["url"] == "http://localhost:4000"


def test_guide_python_with_packages_uses_its_own_environment(tmp_path):
    g = app.code_run.guide(make(tmp_path, {"requirements.txt": "flask>=3\n", "app.py": "from flask import Flask\napp.run(port=5050)"}))
    assert g["stack"] == "Python + Flask" and any("-m venv .venv" in c for c in commands(g))
    assert any(c.endswith("pip install -r requirements.txt") for c in commands(g)) and g["launch"]["url"] == "http://127.0.0.1:5050"


def test_guide_python_without_packages_skips_installing(tmp_path):
    g = app.code_run.guide(make(tmp_path, {"requirements.txt": "# standard library only\n", "main.py": "print(1)"}))
    assert not g["launch"]["installs"] and g["launch"]["command"].endswith("main.py")


def test_guide_python_with_only_test_tools_needs_no_install(tmp_path):
    g = app.code_run.guide(make(tmp_path, {"requirements.txt": "pytest>=8\nblack\n", "main.py": "print(1)"}))
    assert not g["launch"]["installs"] and g["launch"]["command"] == "python3 main.py"


def test_guide_python_package_and_src_layout(tmp_path):
    g = app.code_run.guide(make(tmp_path, {"calc/__init__.py": "", "calc/ui.py": "from .engine import x", "calc/engine.py": ""}), "python calc/ui.py")
    assert g["launch"]["command"].endswith("-m calc.ui")
    g = app.code_run.guide(make(tmp_path, {"src/tool/__init__.py": "", "src/tool/main.py": "import tool.core"}), "python src/tool/main.py")
    assert g["launch"]["command"].startswith("cd src && ") and g["launch"]["command"].endswith("-m tool.main")


@pytest.mark.parametrize("files, kind, needle", [
    ({"main.cpp": "int main(){}"}, "c", "-std=c++17 main.cpp -o app"),
    ({"CMakeLists.txt": "add_executable(game main.cpp)", "main.cpp": ""}, "c", "./build/game"),
    ({"App.csproj": "<Project/>", "Program.cs": ""}, "dotnet", "dotnet run"),
    ({"Cargo.toml": "[package]", "src/main.rs": ""}, "rust", "cargo run"),
    ({"go.mod": "module x", "main.go": ""}, "go", "go run ."),
    ({"Package.swift": "", "Sources/x/main.swift": ""}, "swift", "swift run"),
    ({"src/app/Main.java": "package app;\npublic class Main { public static void main(String[] a){} }"}, "java", "java -cp out app.Main"),
    ({"backup.sh": "echo hi"}, "shell", "bash backup.sh"),
    ({"schema.sql": "create table t(x);", "seed.sql": ""}, "sql", "sqlite3 project.db < schema.sql && sqlite3 project.db < seed.sql"),
])
def test_guide_other_languages(tmp_path, files, kind, needle, monkeypatch):
    monkeypatch.setitem(app.code_run._versions, "cmake", "3.30")   # CMake installed (without it, see the direct-compile test)
    g = app.code_run.guide(make(tmp_path, files))
    assert g["kind"] == kind and needle in g["launch"]["command"], g["launch"]


def test_guide_unknown_kind_says_so_instead_of_guessing(tmp_path):
    g = app.code_run.guide(make(tmp_path, {"notes.txt": "x"}), "mystery --go")
    assert g["kind"] == "unknown" and not g["known"] and g["launch"] is None and "not checked" in g["steps"][1]["text"]


def test_requirements_say_whether_the_tool_is_really_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(app.code_run, "_versions", {"cargo": ""})
    g = app.code_run.guide(make(tmp_path, {"Cargo.toml": "", "src/main.rs": ""}))
    assert g["requirements"][0]["installed"] is False and g["requirements"][0]["get"] == "https://rustup.rs"


# ---- the dependency check ----
def test_undeclared_python_and_node_packages_fail_the_check(tmp_path):
    root = make(tmp_path, {"app.py": "import os\nimport requests\nfrom PIL import Image\nimport helpers\n", "helpers.py": "",
                           "requirements.txt": "requests\n",
                           "package.json": json.dumps({"dependencies": {"express": "4"}}),
                           "server.js": "const express = require('express');\nconst fs = require('node:fs');\nimport cors from 'cors';\nimport x from './x.js';\n"})
    deps = {r["file"]: r["output"] for r in app.coder.check_project(root) if r["tool"] == "Dependencies"}
    assert deps == {"app.py": "This file imports packages the project never declares (add them to requirements.txt): pillow",
                    "server.js": "This file imports packages that package.json doesn't list: cors"}


def test_a_folder_named_after_a_library_fails_the_check(tmp_path):
    root = make(tmp_path, {"requirements.txt": "requests\n", "app.py": "import requests\n", "requests/__init__.py": "", "pytest/__init__.py": ""})
    shadow = [r["file"] for r in app.coder.check_project(root) if r["tool"] == "Dependencies" and "hides the real" in r["output"]]
    assert shadow == ["pytest", "requests"]


def test_pytest_tests_without_pytest_are_not_run_not_failed(tmp_path, monkeypatch):
    root = make(tmp_path, {"calc.py": "def add(a, b): return a + b\n", "tests/test_calc.py": "import pytest\nfrom calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"})
    real_run = app.coder._run
    monkeypatch.setattr(app.coder, "_run", lambda argv, cwd, **kw: (1, "No module named pytest") if argv[-1] == "import pytest" else real_run(argv, cwd, **kw))
    argv, said = app.coder.test_command(root)
    assert argv is None and "written for pytest, which isn't installed" in said and "python3 -m pip install pytest" in said


def test_the_python_version_asked_for_is_what_the_code_needs(tmp_path):
    g = app.code_run.guide(make(tmp_path, {"main.py": "from dataclasses import dataclass\n@dataclass(slots=True)\nclass A:\n    x: int | None = None\n"}))
    assert g["requirements"][0]["name"] == "Python 3.10 or newer"
    g = app.code_run.guide(make(tmp_path, {"pyproject.toml": 'requires-python = ">=3.12"\n', "main.py": "print(1)"}))
    assert g["requirements"][0]["name"] == "Python 3.12 or newer"


# ---- the free plan's per-request limit ----
def test_every_request_fits_the_per_request_limit_and_big_projects_are_changed_in_two_steps(tmp_path):
    coder = app.coder
    root = make(tmp_path, {f"src/module_{i}.py": f"def f{i}():\n" + "    x = 1\n" * 150 for i in range(8)})   # ~12k characters: more than fits
    asked = []

    def chat(messages, max_tokens):
        user = messages[-1]["content"]
        asked.append((user, max_tokens))
        if "Which existing files" in user:
            return "src/module_3.py\nsrc/not_there.py\n"
        return ("SUMMARY: Renamed f3.\n=== EDIT: src/module_3.py ===\n<<<<<<< FIND\ndef f3():\n=======\ndef g3():\n>>>>>>> REPLACE\n=== END EDIT ===\n"
                "=== FILE: src/module_5.py ===\nunseen = True\n=== END FILE ===\n")
    engine = coder.Engine(chat, budget=4000, projects_dir=str(tmp_path))
    job = coder.Job(id="j", request="rename f3 to g3", action="change")
    engine.change(job, {"path": root, "name": "p"})
    for user, max_tokens in asked:
        assert (len(coder.SYSTEM) + len(user)) / coder.CHARS_PER_TOKEN + max_tokens <= 4000
    assert "Which existing files" in asked[0][0] and "src/module_3.py" in asked[1][0] and "def f5" not in asked[1][0]
    assert job.phase == "done" and open(os.path.join(root, "src/module_3.py")).read().startswith("def g3():\n    x = 1\n")
    assert open(os.path.join(root, "src/module_5.py")).read().startswith("def f5")   # a file it never saw is never overwritten


def test_a_request_that_cannot_fit_is_refused_before_it_is_sent():
    engine = app.coder.Engine(lambda m, t: "x", budget=1000)
    with pytest.raises(app.coder.CodeError, match="one part or one file at a time"):
        engine._ask("x" * 4000, 500)


def test_a_too_large_refusal_teaches_the_limit_and_is_said_plainly(monkeypatch):
    class Refuse:
        def with_options(self, **kw):
            return self
        @property
        def chat(self):
            return self
        @property
        def completions(self):
            return self
        def create(self, **kw):
            raise RuntimeError("Error code: 413 - Request too large for model `openai/gpt-oss-120b` on tokens per minute (TPM): Limit 6000, Requested 8293")
    monkeypatch.setattr(app, "GROQ_KEY", "k")
    monkeypatch.setattr(app, "groq_client", Refuse())
    monkeypatch.setitem(app.code_request_limit, "tokens", 8000)
    with pytest.raises(app.coder.CodeError, match="more than the free AI plan accepts in one request"):
        app.real_code_chat_for_test([{"role": "user", "content": "x"}], 9000)
    assert app.code_request_limit["tokens"] == 6000


# ---- small edits instead of whole files ----
def test_edits_apply_only_where_they_match_exactly_once():
    text = "def a():\n    return 1\n\n\ndef b():\n    return 1\n"
    new, problems = app.coder.apply_edits(text, [("def a():\n    return 1\n", "def a():\n    return 2\n")])
    assert new == "def a():\n    return 2\n\n\ndef b():\n    return 1\n" and not problems
    same, problems = app.coder.apply_edits(text, [("    return 1\n", "    return 9\n")])
    assert same == text and problems == ["this FIND matches 2 places: 'return 1'"]
    same, problems = app.coder.apply_edits(text, [("def c():\n", "x")])
    assert same == text and "matches nowhere" in problems[0]
    loose, problems = app.coder.apply_edits("x = 1   \ny = 2\n", [("x = 1\n", "x = 3\n")])   # trailing spaces forgiven
    assert loose == "x = 3\ny = 2\n" and not problems


def test_a_change_made_of_edits_and_a_new_file(tmp_path):
    root = make(tmp_path, {"cli.py": "import argparse\n\n\ndef main():\n    print('hi')\n", "README.md": "# x\n"})
    reply = ("SUMMARY: Says hello.\n=== EDIT: cli.py ===\n<<<<<<< FIND\n    print('hi')\n=======\n    print('hello')\n>>>>>>> REPLACE\n=== END EDIT ===\n"
             "=== FILE: tests/test_cli.py ===\nimport cli\n=== END FILE ===\n")
    engine = app.coder.Engine(lambda m, t: reply, projects_dir=str(tmp_path))
    job = app.coder.Job(id="j", request="say hello", action="change")
    engine.change(job, {"path": root, "name": "p"})
    assert job.phase == "done" and open(os.path.join(root, "cli.py")).read().endswith("print('hello')\n")
    assert open(os.path.join(root, "tests/test_cli.py")).read() == "import cli\n" and sorted(job.diffs) == ["cli.py", "tests/test_cli.py"]


def test_an_edit_that_does_not_match_is_asked_for_again_then_applied(tmp_path):
    root = make(tmp_path, {"app.py": "x = 1\ny = 2\n"})
    replies = iter(["SUMMARY: y.\n=== EDIT: app.py ===\n<<<<<<< FIND\nz = 2\n=======\nz = 3\n>>>>>>> REPLACE\n=== END EDIT ===\n",
                    "=== EDIT: app.py ===\n<<<<<<< FIND\ny = 2\n=======\ny = 3\n>>>>>>> REPLACE\n=== END EDIT ===\n"])
    engine = app.coder.Engine(lambda m, t: next(replies), projects_dir=str(tmp_path))
    job = app.coder.Job(id="j", request="make y 3", action="change")
    engine.change(job, {"path": root, "name": "p"})
    assert job.phase == "done" and open(os.path.join(root, "app.py")).read() == "x = 1\ny = 3\n"


def test_a_cmake_project_compiles_directly_when_cmake_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(app.code_run, "_versions", {"cmake": ""})
    monkeypatch.setattr(app.code_run.shutil, "which", lambda name: "/usr/bin/clang++" if name == "clang++" else None)
    g = app.code_run.guide(make(tmp_path, {"CMakeLists.txt": "add_executable(conv src/main.cpp)", "src/main.cpp": "", "src/conv.cpp": "", "src/conv.h": ""}))
    assert g["launch"]["command"] == "clang++ -std=c++17 -Isrc src/conv.cpp src/main.cpp -o conv && ./conv" and "CMake isn't installed" in g["steps"][2]["text"]


def test_the_plan_is_told_what_this_computer_can_run(tmp_path):
    asked = []
    engine = app.coder.Engine(lambda m, t: asked.append(m[-1]["content"]) or "PROJECT: x\nFILES:\nmain.c | it\n", projects_dir=str(tmp_path),
                              environment="Installed on the user's computer: a C/C++ compiler 21. Not installed: CMake.")
    engine.create(app.coder.Job(id="j", request="a C program"))
    assert "Not installed: CMake" in asked[0] and "build setup the user can run" in asked[0]


# ---- the sidebar: hide, the earlier-projects setting, sort, rename, remove ----
@pytest.fixture
def two_projects(monkeypatch, tmp_path):
    monkeypatch.setattr(app.code_chat, "PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.setattr(app.code_chat, "AUDIT_FILE", str(tmp_path / "audit.log"))
    route_to(monkeypatch, "create", "create")
    app.coding_send("", "Build me a racing website")
    first = app.code_state["thread"]
    monkeypatch.setattr(app, "_code_chat", lambda m, t, model="": PLAN.replace("racing-site", "recipes") if "Plan the smallest" in m[-1]["content"] else SITE)
    app.coding_send("", "Build me a recipe site")
    return first, app.code_state["thread"], tmp_path


def listed(sent):
    last = [m for m in sent if m["type"] == "coding_threads"][-1]
    return last["data"], last["prefs"]


def test_hiding_keeps_the_project_and_survives_a_restart(two_projects, fresh):
    first, second, tmp_path = two_projects
    app.coding_window_says({"type": "code_hide", "key": first, "hidden": True})
    items, prefs = listed(fresh["sent"])
    assert {t["id"]: t["hidden"] for t in items} == {first: True, second: False} and prefs["hidden"] == [first]
    assert app.code_chat.load(first) and (tmp_path / "projects" / "racing-site" / "index.html").exists()   # nothing deleted
    assert json.loads((tmp_path / "prefs.json").read_text())["hidden"] == [first]                            # on disk: a restart keeps it
    app.coding_window_says({"type": "code_hide", "key": first, "hidden": False})
    assert not any(t["hidden"] for t in listed(fresh["sent"])[0])


def test_the_earlier_projects_setting_and_the_sort_order_persist(two_projects, fresh):
    app.coding_window_says({"type": "code_prefs", "showEarlier": False, "sort": "name"})
    assert listed(fresh["sent"])[1] == {"hidden": [], "sort": "name", "showEarlier": False}
    app.coding_window_says({"type": "code_prefs", "sort": "nonsense"})          # an unknown order is ignored
    assert app.code_chat.prefs()["sort"] == "name"


def test_renaming_changes_the_name_not_the_folder(two_projects, fresh):
    first, _, tmp_path = two_projects
    app.coding_window_says({"type": "code_rename", "key": first, "title": "  My   F1 site "})
    assert app.code_chat.load(first)["title"] == "My F1 site" and (tmp_path / "projects" / "racing-site").is_dir()


def test_remove_from_the_list_keeps_the_files_and_the_chat_is_recoverable(two_projects, fresh, monkeypatch):
    first, second, tmp_path = two_projects
    trashed = []
    monkeypatch.setattr(app.code_run, "move_to_trash", trashed.append)
    app.code_state["thread"] = first
    app.coding_remove({"key": first})
    note = [m for m in fresh["sent"] if m["type"] == "coding_removed"][-1]["data"]
    assert note["ok"] and "Its files are still in" in note["message"] and not trashed
    assert (tmp_path / "projects" / "racing-site" / "index.html").exists()
    assert app.code_chat.load(first) is None and len(os.listdir(tmp_path / "chats" / "removed")) == 1
    assert [t["id"] for t in listed(fresh["sent"])[0]] == [second]
    assert [m for m in fresh["sent"] if m["type"] == "coding_thread"][-1]["data"]["thread"] is None   # the open chat closed
    assert "remove" in (tmp_path / "audit.log").read_text()


def test_moving_the_folder_to_the_trash_is_separate_and_only_for_folders_jarvis_made(two_projects, fresh, monkeypatch):
    first, second, tmp_path = two_projects
    trashed = []
    monkeypatch.setattr(app.code_run, "move_to_trash", lambda f: trashed.append(f) or __import__("shutil").rmtree(f))
    app.coding_remove({"key": second, "files": True})
    assert trashed == [os.path.realpath(tmp_path / "projects" / "recipes")] and app.code_chat.load(second) is None
    # a folder that isn't one Jarvis made (here: the projects folder itself) is refused, and nothing is removed
    bad = app.code_chat.new_thread(path=str(tmp_path / "projects"))
    app.coding_remove({"key": bad["id"], "files": True})
    note = [m for m in fresh["sent"] if m["type"] == "coding_removed"][-1]["data"]
    assert not note["ok"] and "isn't a project folder Jarvis made" in note["message"] and app.code_chat.load(bad["id"]) and len(trashed) == 1


def test_a_project_being_worked_on_cannot_be_removed(two_projects, fresh):
    first, _, tmp_path = two_projects
    app.code_state.update(busy=True, thread=first)
    app.coding_remove({"key": first, "files": True})
    note = [m for m in fresh["sent"] if m["type"] == "coding_removed"][-1]["data"]
    assert not note["ok"] and "working on" in note["message"] and app.code_chat.load(first)
    app.code_state.update(busy=False)


def test_a_missing_folder_still_lets_the_entry_go(two_projects, fresh, monkeypatch):
    first, _, tmp_path = two_projects
    import shutil as sh
    sh.rmtree(tmp_path / "projects" / "racing-site")
    monkeypatch.setattr(app.code_run, "move_to_trash", lambda f: pytest.fail("nothing to trash"))
    app.coding_remove({"key": first, "files": True})
    note = [m for m in fresh["sent"] if m["type"] == "coding_removed"][-1]["data"]
    assert note["ok"] and "already gone" in note["message"]


def test_the_audit_log_never_records_a_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(app.code_chat, "AUDIT_FILE", str(tmp_path / "audit.log"))
    app.code_chat.audit("run", command="API_KEY=sk-live-123456 node server.js")
    assert "sk-live" not in (tmp_path / "audit.log").read_text() and "API_KEY=…" in (tmp_path / "audit.log").read_text()



# ---- editing safety ----
def test_a_whole_file_answer_that_looks_cut_off_is_not_used(tmp_path):
    root = make(tmp_path, {"app.py": "def main():\n" + "    step()\n" * 300})
    engine = app.coder.Engine(lambda m, t: "SUMMARY: x\n=== FILE: app.py ===\ndef main():\n    step()\n=== END FILE ===\n", projects_dir=str(tmp_path))
    job = app.coder.Job(id="j", request="add logging", action="change")
    engine.change(job, {"path": root, "name": "p"})
    assert job.phase == "failed" and "cut off" in job.error and open(os.path.join(root, "app.py")).read().count("step()") == 300


def test_windows_line_endings_are_kept(tmp_path):
    root = tmp_path / "p"; root.mkdir()
    (root / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    engine = app.coder.Engine(lambda m, t: "SUMMARY: x\n=== EDIT: a.txt ===\n<<<<<<< FIND\ntwo\n=======\n2\n>>>>>>> REPLACE\n=== END EDIT ===\n", projects_dir=str(tmp_path))
    job = app.coder.Job(id="j", request="change two", action="change")
    engine.change(job, {"path": str(root), "name": "p"})
    assert job.phase == "done" and (root / "a.txt").read_bytes() == b"one\r\n2\r\n"


def test_a_key_from_this_computer_is_never_written_into_code(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_SERVICE_API_KEY", "sk-test-0123456789abcdef")
    engine = app.coder.Engine(lambda m, t: "PROJECT: x\nFILES:\nconfig.js | it\n" if "Plan" in m[-1]["content"] else
                              "=== FILE: config.js ===\nconst key = 'sk-test-0123456789abcdef';\n=== END FILE ===\n", projects_dir=str(tmp_path))
    job = app.coder.Job(id="j", request="a config file")
    engine.create(job)
    assert not (tmp_path / "x" / "config.js").exists() if (tmp_path / "x").exists() else True
    assert any("SOME_SERVICE_API_KEY" in (f.get("error") or "") and "sk-test" not in (f.get("error") or "") for f in job.files)


def test_the_same_failure_twice_stops_the_repair_loop(tmp_path):
    root = make(tmp_path, {"bad.py": "def x(:\n"})
    asked = []
    engine = app.coder.Engine(lambda m, t: asked.append(1) or f"=== FILE: bad.py ===\ndef x(:\n# attempt {len(asked)}\n=== END FILE ===\n", projects_dir=str(tmp_path))
    job = app.coder.Job(id="j", request="x", action="create")
    engine._check_and_repair(job, root, "context")
    assert len(asked) == 1 and job.repairs == 1 and "same check failed again" in job.error   # one fix tried; the same error back: stop


# ---- a build interrupted by closing Jarvis, finished later ----
def test_an_interrupted_build_is_marked_and_continue_finishes_it(monkeypatch, tmp_path, fresh):
    folder = tmp_path / "projects" / "racing-site"
    folder.mkdir(parents=True)
    (folder / "index.html").write_text("<link rel=\"stylesheet\" href=\"styles.css\"><script src=\"script.js\"></script>")
    (folder / "styles.css").write_text("body { color: red; }\n")
    thread = app.code_chat.new_thread(path="")
    app.code_chat.add(thread, "user", "Build me a racing website")
    files = [{"path": "index.html", "status": "written", "purpose": "the page"}, {"path": "styles.css", "status": "written", "purpose": "the look"},
             {"path": "script.js", "status": "planned", "purpose": "the behaviour"}]
    app.code_chat.add(thread, "jarvis", "", "work", id="w-old", job={"id": "old", "action": "create", "phase": "writing", "name": "racing-site",
                                                                     "path": str(folder), "language": "HTML/CSS/JavaScript", "request": "Build me a racing website", "files": files})
    app.send_code_thread(app.code_chat.load(thread["id"]))     # opening the chat after a restart
    after = app.code_chat.load(thread["id"])
    assert after["messages"][1]["job"]["phase"] == "interrupted" and "2 of 3 files" in after["messages"][2]["text"] and after["path"] == str(folder)
    asked = []
    monkeypatch.setattr(app, "_code_chat", lambda m, t, model="": asked.append(m[-1]["content"]) or "=== FILE: script.js ===\nconsole.log('go');\n=== END FILE ===\n")
    app.coding_send(thread["id"], "continue")
    assert (folder / "script.js").read_text() == "console.log('go');\n" and (folder / "styles.css").read_text() == "body { color: red; }\n"
    assert len(asked) == 1 and "script.js" in asked[0] and "Plan the smallest" not in asked[0]   # no new plan: the old one is finished
    last = app.code_chat.load(thread["id"])["messages"][-1]
    assert last["kind"] == "result" and last["phase"] == "done" and not app.code_state["busy"]
    app.send_code_thread(app.code_chat.load(thread["id"]))     # a finished build is never marked interrupted again
    assert app.code_chat.load(thread["id"])["messages"][-1]["kind"] == "result"



# ---- repository intelligence ----
def test_names_in_a_request_are_found_where_the_code_defines_and_uses_them():
    files = {"src/cart.js": "export function addToCart(item) {\n  total += item.price;\n}\n", "src/ui.js": "import { addToCart } from './cart.js';\naddToCart(x);\n",
             "README.md": "A shop.", "src/util.py": "def format_price(p):\n    return p\n"}
    found = app.coder.find_symbols("make addToCart refuse negative prices and fix format_price", files)
    assert found["addToCart"] == {"defined": ["src/cart.js"], "used": ["src/cart.js", "src/ui.js"]}
    assert found["format_price"]["defined"] == ["src/util.py"] and "make" not in found and "prices" not in found


def test_a_big_project_change_reads_the_files_where_the_named_function_lives(tmp_path):
    files = {f"src/m{i}.js": f"export function helper{i}() {{ return {i}; }}\n" + "// filler\n" * 120 for i in range(10)}
    files["src/m7.js"] = "export function computeTotal(items) { return 0; }\n" + "// filler\n" * 120
    files["src/app.js"] = "import { computeTotal } from './m7.js';\ncomputeTotal([]);\n"
    root = make(tmp_path, files)
    asked = []

    def chat(messages, max_tokens):
        asked.append(messages[-1]["content"])
        return "src/m1.js\n" if "Which existing files" in asked[-1] else "SUMMARY: x\n=== EDIT: src/m7.js ===\n<<<<<<< FIND\nexport function computeTotal(items) { return 0; }\n=======\nexport function computeTotal(items) { return items.length; }\n>>>>>>> REPLACE\n=== END EDIT ===\n"
    engine = app.coder.Engine(chat, budget=4000, projects_dir=str(tmp_path))
    job = app.coder.Job(id="j", request="make computeTotal count the items", action="change")
    engine.change(job, {"path": root, "name": "p"}, facts="Kind: JavaScript (Node.js)")
    assert "computeTotal: defined in src/m7.js; appears in src/app.js, src/m7.js" in asked[0] and "Kind: JavaScript" in asked[0]
    assert "=== FILE: src/m7.js ===" in asked[1] and job.phase == "done"   # the AI picked m1 alone; the search added m7, where the change belongs
    assert "return items.length; }" in open(os.path.join(root, "src/m7.js")).read() and len(asked) == 2
