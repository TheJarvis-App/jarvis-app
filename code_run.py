"""How to run a Coding Mode project, worked out from its real files, and starting it when the user says yes.

guide(root) reads the folder (index.html, package.json, requirements.txt, Cargo.toml, a .csproj, Package.swift, …) and
returns what a beginner needs: what it is, what must be installed (and whether it is installed on this computer, by
asking the tool for its version), numbered steps with the exact commands for this operating system, what should
happen, how to stop it, and the usual problems. Nothing here comes from the AI's own description of the project, so
the steps can't name a file that isn't there; the AI's RUN line is used only to pick between entry points that exist,
and a project of a kind not recognized here says so instead of guessing.

launch(root, guide) starts it: a web page opens in the browser, anything else opens in a Terminal window running the
guide's command, where the user sees its real output. app.py calls it only after the user confirmed in the chat.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import webbrowser

import coder

MAC, WINDOWS = sys.platform == "darwin", sys.platform.startswith("win")
TERMINAL = "Terminal" if MAC else "Command Prompt" if WINDOWS else "a terminal"
OPEN_TERMINAL = ("Open Terminal: press ⌘ Space, type Terminal and press Return." if MAC else
                 "Open Command Prompt: press the Windows key, type cmd and press Enter." if WINDOWS else "Open a terminal window.")

_versions = {}


def tool_version(*names) -> str:
    """The installed version of the first tool found ("" if none). Asked once per tool per session."""
    for name in names:
        if name in _versions:
            if _versions[name]:
                return _versions[name]
            continue
        path = shutil.which(name)
        version = ""
        if path:
            try:
                out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=8)
                text = (out.stdout or out.stderr or "").strip()
                if out.returncode == 0 and text:
                    found = re.search(r"\d+\.\d+(?:\.\d+)?", text)
                    version = found.group(0) if found else text.splitlines()[0][:40]
            except (OSError, subprocess.SubprocessError):
                version = ""
        _versions[name] = version
        if version:
            return version
    return ""


def _need(name: str, tools: tuple, get: str, why: str) -> dict:
    version = tool_version(*tools) if tools else ""
    return {"name": name, "why": why, "installed": bool(version) if tools else None, "version": version, "get": get}


def _cd(root: str) -> dict:
    command = f'cd /d "{root}"' if WINDOWS else f"cd {shlex.quote(root)}"
    return {"text": f"Go to the project folder in {TERMINAL}.", "command": command,
            "where": f"In {TERMINAL}. This moves the terminal into the project folder, so the next commands work on these files."}


def _python() -> str:
    return "py" if WINDOWS else "python3"


def _read(root: str, rel: str) -> str:
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            return f.read(200_000)
    except (OSError, UnicodeDecodeError):
        return ""


def _port(text: str, default: int = 0) -> int:
    found = re.search(r"(?:listen|port\s*[=:(]|PORT\s*\|\|\s*|\.run\([^)]*port\s*=\s*)\(?\s*(\d{4,5})", text)
    return int(found.group(1)) if found else default


PYTHON_GET = "https://www.python.org/downloads/"
DEV_TOOLS = {"pytest", "pytest-cov", "pytest-mock", "pytest-asyncio", "coverage", "black", "flake8", "ruff", "mypy", "isort", "pylint", "tox",
             "pre-commit", "hypothesis", "freezegun", "responses"}
NODE_GET = "https://nodejs.org/"


def guide(root: str, run_hint: str = "") -> dict:
    """{"kind", "stack", "requirements": [...], "steps": [{"text", "command"?, "where"?}], "expect", "stop",
    "problems": [{"problem", "fix"}], "launch": {"type": "browser" | "terminal" | None, "command", "url", "installs"},
    "known": bool}. Paths and commands are for this computer's operating system."""
    if not root or not os.path.isdir(root):
        return {"kind": "missing", "stack": "", "requirements": [], "steps": [], "expect": "", "stop": "", "problems": [],
                "launch": None, "known": False}
    tree = coder.read_project(root)["tree"]
    top = {p for p in tree if "/" not in p}
    has = lambda *names: any(n in top for n in names)
    ext = lambda *exts: [p for p in tree if p.lower().endswith(exts)]
    hint = (run_hint or "").strip()
    for maker in (_node, _static_web, _python_project, _dotnet, _rust, _go, _swift, _java, _c_family, _shell, _sql):
        found = maker(root, tree, top, has, ext, hint)
        if found:
            found.setdefault("problems", [])
            found.setdefault("known", True)
            return found
    return {"kind": "unknown", "stack": "Project", "requirements": [], "known": False,
            "steps": [{"text": "I couldn't work out how this kind of project starts from its files."}]
            + ([{"text": "The AI that wrote it suggested this command (not checked against the files):", "command": hint, "where": f"In {TERMINAL}, in the project folder."}] if hint and hint.lower() != "none" else [])
            + [{"text": "The project's README.md may say more; ask me \"how do I run it?\" and I'll read the files and explain."}],
            "expect": "", "stop": "", "problems": [], "launch": None}


# ---------- each kind of project ----------
def _static_web(root, tree, top, has, ext, hint):
    pages = [p for p in tree if p.lower().endswith((".html", ".htm"))]
    if not pages or has("package.json"):
        return None
    page = next((p for p in pages if os.path.basename(p).lower() == "index.html" and p.count("/") == 0), None) or \
        next((p for p in pages if os.path.basename(p).lower() == "index.html"), pages[0])
    texts = "\n".join(_read(root, p) for p in tree if p.lower().endswith((".html", ".htm", ".js", ".mjs")))
    needs_server = bool(re.search(r"""<script[^>]+type\s*=\s*["']module["']|\bfetch\(\s*["'`](?!https?:)|\bimport\s+[^;]*from\s+["']\.""", texts))
    full = os.path.join(root, page)
    if not needs_server:
        return {"kind": "web", "stack": "Website (HTML, CSS, JavaScript)",
                "requirements": [{"name": "A web browser", "why": "Safari, Chrome, Edge or Firefox; nothing else to install.", "installed": None, "version": "", "get": ""}],
                "steps": [{"text": f"Open the project folder and double-click **{page}**. It opens in your web browser."},
                          {"text": "Or press **Run** here, and Jarvis opens it for you."}],
                "expect": f"The site appears in your browser. Every page works from the files in the folder, with no internet needed except for anything it loads from the web.",
                "stop": "Close the browser tab.",
                "problems": [{"problem": "The page is blank or looks unstyled.", "fix": "Keep all the project's files together in their folder: the page loads its CSS and scripts from next to it."},
                             {"problem": "Something doesn't react.", "fix": "Ask me: \"the button doesn't work, fix it\" — I'll read the files and fix them."}],
                "launch": {"type": "browser", "path": full, "url": "", "command": "", "installs": False}}
    command = f"{_python()} -m http.server 8000"
    return {"kind": "web-server", "stack": "Website (HTML, CSS, JavaScript modules)",
            "requirements": [_need("Python 3", ("python3", "python", "py"), PYTHON_GET, "Only to serve the files: browsers don't run these scripts straight from a file."),
                             {"name": "A web browser", "why": "", "installed": None, "version": "", "get": ""}],
            "steps": [{"text": OPEN_TERMINAL}, _cd(root),
                      {"text": "Start a small local web server.", "command": command, "where": f"In {TERMINAL}, in the project folder. Leave this window open while you use the site."},
                      {"text": f"Open **http://localhost:8000/{page if page != 'index.html' else ''}** in your browser.", "command": f"http://localhost:8000/{page if page != 'index.html' else ''}"}],
            "expect": "The terminal says \"Serving HTTP on … port 8000\", and the site appears at that address.",
            "stop": f"Press Control + C in {TERMINAL}.",
            "problems": [{"problem": "\"Address already in use\".", "fix": "Something else uses port 8000: change 8000 to 8001 in the command and in the address."}],
            "launch": {"type": "terminal", "command": command, "url": f"http://localhost:8000/{page if page != 'index.html' else ''}", "installs": False}}


def _node(root, tree, top, has, ext, hint):
    if not has("package.json"):
        return None
    try:
        package = json.loads(_read(root, "package.json") or "{}")
    except ValueError:
        package = {}
    scripts = package.get("scripts") or {}
    deps = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
    names = set(deps)
    engines = (package.get("engines") or {}).get("node", "")
    framework = ("Next.js" if "next" in names else "React" if "react" in names else "Vue" if "vue" in names else "Svelte" if "svelte" in names
                 else "Electron" if "electron" in names else "Express" if "express" in names else "")
    vite = "vite" in names or "vite" in json.dumps(scripts)
    typescript = "typescript" in names or any(p.endswith((".ts", ".tsx")) for p in tree)
    stack = " + ".join(x for x in (framework, "Vite" if vite else "", "TypeScript" if typescript else "JavaScript") if x) + " (Node.js)"
    script = next((s for s in ("dev", "start", "serve") if s in scripts), "")
    main = package.get("main") or next((p for p in ("server.js", "index.js", "app.js", "src/index.js", "src/server.js") if p in tree), "")
    command = (f"npm run {script}" if script not in ("", "start") else "npm start") if script else (f"node {main}" if main else "")
    text = "\n".join(_read(root, p) for p in tree if re.search(r"\.(?:m|c)?[jt]sx?$", p) and "/node_modules/" not in p)[:400_000]
    url = ""
    if vite and script == "dev":
        url = "http://localhost:5173"
    elif "next" in names:
        url = "http://localhost:3000"
    elif "react-scripts" in names:
        url = "http://localhost:3000"
    elif framework in ("Express", "") and (port := _port(text)):
        url = f"http://localhost:{port}"
    installs = bool(deps)
    steps = [{"text": OPEN_TERMINAL}, _cd(root)]
    if installs:
        steps.append({"text": "Install the packages it uses (once). This downloads them from the internet into a node_modules folder.",
                      "command": "npm install", "where": f"In {TERMINAL}, in the project folder. It can take a minute."})
    if command:
        steps.append({"text": "Start it.", "command": command, "where": f"In {TERMINAL}, in the project folder." + (" Leave it open while you use it." if url else "")})
    if url:
        steps.append({"text": f"Open **{url}** in your browser (the terminal also prints the address).", "command": url})
    if "electron" in names:
        expect = "A desktop window opens."
    elif url:
        expect = f"The terminal shows that it is running, and the app appears at {url}."
    else:
        expect = "The program runs in the terminal and prints its output there."
    if not command:
        steps.append({"text": "package.json has no start script, so I can't say which command starts it; ask me and I'll add one."})
    return {"kind": "node", "stack": stack,
            "requirements": [_need("Node.js" + (f" {engines}" if engines else " 18 or newer"), ("node",), NODE_GET, "Runs JavaScript outside the browser; npm comes with it.")],
            "steps": steps, "expect": expect, "stop": f"Press Control + C in {TERMINAL}." if url or "electron" in names else "",
            "problems": [{"problem": "\"npm: command not found\" or \"'npm' is not recognized\".", "fix": f"Install Node.js from {NODE_GET}, then open a new {TERMINAL} window."},
                         {"problem": "\"Cannot find module …\".", "fix": "Run npm install first, in the project folder."},
                         {"problem": "\"Port … is already in use\".", "fix": "Another copy is still running: stop it with Control + C, or close that terminal."}],
            "launch": {"type": "terminal", "command": " && ".join(c for c in ("npm install" if installs and not os.path.isdir(os.path.join(root, "node_modules")) else "", command) if c),
                       "url": url, "installs": installs and not os.path.isdir(os.path.join(root, "node_modules"))} if command else None}


def _python_project(root, tree, top, has, ext, hint):
    py = ext(".py")
    if not py:
        return None
    # only a project that really lists packages gets the install steps (a requirements.txt of comments needs none)
    listed = {re.split(r"[<>=!~\[; ]", ln.strip())[0].lower() for ln in _read(root, "requirements.txt").splitlines() if re.match(r"^\s*[A-Za-z0-9]", ln)}
    requirements = bool(listed - DEV_TOOLS)   # pytest alone is for the tests: running the program needs nothing installed
    pyproject = has("pyproject.toml") and bool(re.search(r"^\s*dependencies\s*=\s*\[\s*[\"']", _read(root, "pyproject.toml"), re.M))
    text_of = {p: _read(root, p) for p in py if "/tests/" not in f"/{p}" and not os.path.basename(p).startswith("test_")}
    everything = "\n".join(text_of.values())
    req_text = _read(root, "requirements.txt").lower() + _read(root, "pyproject.toml").lower()
    framework = ("Flask" if re.search(r"\bflask\b", req_text + everything, re.I) else "FastAPI" if "fastapi" in req_text else
                 "Django" if "django" in req_text else "Streamlit" if "streamlit" in req_text else "Pygame" if "pygame" in req_text else
                 "Tkinter" if re.search(r"^\s*(?:import tkinter|from tkinter)", everything, re.M) else "")
    entry = ""
    hinted = re.search(r"([\w./-]+\.py)\b", hint)
    if hinted and hinted.group(1) in tree:
        entry = hinted.group(1)
    module = re.search(r"-m\s+([\w.]+)", hint)
    if not entry and module and any(p.startswith(module.group(1).replace(".", "/") + "/__main__.py") or p == module.group(1).replace(".", "/") + ".py" for p in tree):
        entry = "-m " + module.group(1)
    if not entry:
        entry = next((p for p in ("main.py", "app.py", "run.py", "manage.py", "server.py", "game.py", "cli.py", "src/main.py") if p in tree), "")
    if not entry:
        package = next((p.split("/")[0] for p in tree if p.endswith("/__main__.py") and p.count("/") == 1), "")
        entry = f"-m {package}" if package else next((p for p, t in text_of.items() if "__main__" in t), "")
    if not entry and len(text_of) == 1:
        entry = next(iter(text_of))
    if entry.endswith(".py") and "/" in entry and f"{os.path.dirname(entry)}/__init__.py" in tree:
        # a module inside a package runs as one (python -m pkg.mod), or its "from . import" lines fail; from the folder holding the package
        top_pkg = entry.split("/")[0]
        if f"{top_pkg}/__init__.py" in tree:
            entry = "-m " + entry[:-3].replace("/", ".")
        elif top_pkg == "src" and entry.count("/") >= 2:   # the src layout: the package lives in src/
            entry = "src:-m " + entry[4:-3].replace("/", ".")
    py_cmd = _python()
    venv_py = ".venv\\Scripts\\python" if WINDOWS else ".venv/bin/python"
    runner = venv_py if requirements or pyproject else py_cmd
    if entry == "manage.py":
        command, url = f"{runner} manage.py runserver", "http://127.0.0.1:8000"
    elif framework == "Streamlit":
        command, url = f"{runner} -m streamlit run {entry or 'app.py'}", "http://localhost:8501"
    elif framework == "FastAPI" and entry and not re.search(r"uvicorn\.run", everything):
        command, url = f"{runner} -m uvicorn {entry[:-3].replace('/', '.')}:app --reload", "http://127.0.0.1:8000"
    elif entry.startswith("src:"):
        inner = ("..\\" if WINDOWS else "../") + runner if runner == venv_py else runner
        command = f"cd src && {inner} {entry[4:]}"
        url = f"http://127.0.0.1:{_port(everything, 5000 if framework == 'Flask' else 8000)}" if framework in ("Flask", "FastAPI") else ""
    else:
        command = f"{runner} {entry}" if entry else ""
        url = f"http://127.0.0.1:{_port(everything, 5000 if framework == 'Flask' else 8000)}" if framework in ("Flask", "FastAPI") else ""
    steps = [{"text": OPEN_TERMINAL}, _cd(root)]
    install = (f"{venv_py} -m pip install -r requirements.txt" if requirements else f"{venv_py} -m pip install -e .") if requirements or pyproject else ""
    if install:
        steps.append({"text": "Make a private Python environment for this project (once), so its packages don't mix with anything else on the computer.",
                      "command": f"{py_cmd} -m venv .venv", "where": f"In {TERMINAL}, in the project folder."})
        steps.append({"text": "Install the packages it needs into that environment (once). This downloads them from the internet.",
                      "command": install,
                      "where": f"In {TERMINAL}, in the project folder."})
    if command:
        steps.append({"text": "Start it.", "command": command, "where": f"In {TERMINAL}, in the project folder."})
    else:
        steps.append({"text": "I couldn't tell which file starts it (there is no main.py or app.py); ask me and I'll explain or add one."})
    if url:
        steps.append({"text": f"Open **{url}** in your browser.", "command": url})
    expect = ("A window opens." if framework in ("Tkinter", "Pygame") else f"The terminal shows it is running; open {url}." if url
              else "It runs in the terminal and prints its output there.")
    needs_tk = framework == "Tkinter"
    problems = [{"problem": "\"command not found: python3\" or \"Python was not found\".", "fix": f"Install Python 3 from {PYTHON_GET}, then open a new {TERMINAL} window."},
                {"problem": "\"ModuleNotFoundError: No module named …\".", "fix": "Run the install step again, and start it with the command above (it uses the project's own environment)."}]
    if needs_tk and MAC:
        problems.append({"problem": "\"No module named '_tkinter'\".", "fix": "Your Python has no window toolkit. Install Python from python.org (it includes it), or with Homebrew: brew install python-tk."})
    installs = bool(requirements or pyproject)
    declared = re.search(r"requires-python\s*=\s*[\"']\s*>=?\s*(3\.\d+)", _read(root, "pyproject.toml"))
    uses = 10 if re.search(r"^\s*match\s+.+:\s*$|slots\s*=\s*True|\w\s*\|\s*None\b", everything, re.M) else 8
    minimum = max(declared.group(1) if declared else "3.8", f"3.{uses}", key=lambda v: int(v.split(".")[1]))   # what the code really needs wins
    launch_cmd = " && ".join(c for c in ((f"{py_cmd} -m venv .venv" if installs and not os.path.isdir(os.path.join(root, ".venv")) else ""),
                                         install, command) if c)
    return {"kind": "python", "stack": "Python" + (f" + {framework}" if framework else ""),
            "requirements": [_need(f"Python {minimum} or newer", ("python3", "python", "py"), PYTHON_GET, "Runs Python programs.")],
            "steps": steps, "expect": expect, "stop": f"Press Control + C in {TERMINAL}" + (", or close the window." if framework in ("Tkinter", "Pygame") else "."),
            "problems": problems,
            "launch": {"type": "terminal", "command": launch_cmd, "url": url, "installs": installs} if command else None}


def _dotnet(root, tree, top, has, ext, hint):
    project = next(iter(ext(".csproj", ".fsproj")), "")
    if not project:
        return None
    where = os.path.dirname(project)
    command = "dotnet run" + (f" --project {project}" if where else "")
    return {"kind": "dotnet", "stack": "C# (.NET)",
            "requirements": [_need(".NET SDK 8 or newer", ("dotnet",), "https://dotnet.microsoft.com/download", "Builds and runs C# programs.")],
            "steps": [{"text": OPEN_TERMINAL}, _cd(root),
                      {"text": "Build and run it (the first time it also downloads the packages it lists).", "command": command, "where": f"In {TERMINAL}, in the project folder."}],
            "expect": "It compiles (a few seconds the first time) and then runs.", "stop": f"Press Control + C in {TERMINAL} if it keeps running.",
            "problems": [{"problem": "\"dotnet: command not found\".", "fix": "Install the .NET SDK from https://dotnet.microsoft.com/download."}],
            "launch": {"type": "terminal", "command": command, "url": "", "installs": False}}


def _rust(root, tree, top, has, ext, hint):
    if not has("Cargo.toml"):
        return None
    return {"kind": "rust", "stack": "Rust (Cargo)",
            "requirements": [_need("Rust (with Cargo)", ("cargo",), "https://rustup.rs", "Builds and runs Rust programs.")],
            "steps": [{"text": OPEN_TERMINAL}, _cd(root),
                      {"text": "Build and run it (the first build downloads its crates and takes a while).", "command": "cargo run", "where": f"In {TERMINAL}, in the project folder."}],
            "expect": "Cargo compiles it, then it runs.", "stop": f"Press Control + C in {TERMINAL} if it keeps running.",
            "problems": [{"problem": "\"cargo: command not found\".", "fix": "Install Rust from https://rustup.rs, then open a new terminal."}],
            "launch": {"type": "terminal", "command": "cargo run", "url": "", "installs": True}}


def _go(root, tree, top, has, ext, hint):
    if not has("go.mod"):
        return None
    return {"kind": "go", "stack": "Go",
            "requirements": [_need("Go", ("go",), "https://go.dev/dl/", "Builds and runs Go programs.")],
            "steps": [{"text": OPEN_TERMINAL}, _cd(root), {"text": "Run it.", "command": "go run .", "where": f"In {TERMINAL}, in the project folder."}],
            "expect": "Go compiles it, then it runs.", "stop": f"Press Control + C in {TERMINAL} if it keeps running.",
            "problems": [{"problem": "\"go: command not found\".", "fix": "Install Go from https://go.dev/dl/."}],
            "launch": {"type": "terminal", "command": "go run .", "url": "", "installs": False}}


def _swift(root, tree, top, has, ext, hint):
    if has("Package.swift"):
        command, what = "swift run", "Builds and runs it."
    elif len(ext(".swift")) == 1:
        command, what = f"swift {ext('.swift')[0]}", "Runs the script."
    else:
        return None
    return {"kind": "swift", "stack": "Swift",
            "requirements": [_need("Swift (Xcode or the Command Line Tools)", ("swift",), "https://www.swift.org/install/", "Builds and runs Swift code.")],
            "steps": [{"text": OPEN_TERMINAL}, _cd(root), {"text": what, "command": command, "where": f"In {TERMINAL}, in the project folder."}],
            "expect": "It compiles, then runs.", "stop": f"Press Control + C in {TERMINAL} if it keeps running.",
            "problems": [{"problem": "\"xcrun: error: invalid active developer path\".", "fix": "Install Apple's Command Line Tools: run xcode-select --install."}],
            "launch": {"type": "terminal", "command": command, "url": "", "installs": False}}


def _java(root, tree, top, has, ext, hint):
    java = ext(".java")
    if has("pom.xml"):
        command, tools, name = "mvn -q compile exec:java", ("mvn",), "Maven"
    elif has("build.gradle", "build.gradle.kts"):
        command, tools, name = ("gradlew.bat run" if WINDOWS else "./gradlew run") if has("gradlew") else "gradle run", ("gradle",), "Gradle"
    elif java:
        main = next((p for p in java if re.search(r"public\s+static\s+void\s+main\s*\(", _read(root, p))), java[0])
        package = re.search(r"^\s*package\s+([\w.]+)\s*;", _read(root, main), re.M)
        cls = (package.group(1) + "." if package else "") + os.path.splitext(os.path.basename(main))[0]
        sources = " ".join(java) if len(java) <= 12 else ("(Get-ChildItem -Recurse -Filter *.java).FullName" if WINDOWS else "$(find . -name '*.java')")
        command, tools, name = f"javac -d out {sources} && java -cp out {cls}", (), ""
    else:
        return None
    requirements = [_need("Java JDK 17 or newer", ("javac",), "https://adoptium.net", "Compiles and runs Java.")]
    if tools:
        requirements.append(_need(name, tools, "https://maven.apache.org/install.html" if name == "Maven" else "https://gradle.org/install/", f"Builds the project ({name})."))
    return {"kind": "java", "stack": "Java" + (f" ({name})" if name else ""), "requirements": requirements,
            "steps": [{"text": OPEN_TERMINAL}, _cd(root), {"text": "Compile and run it.", "command": command, "where": f"In {TERMINAL}, in the project folder."}],
            "expect": "It compiles, then runs.", "stop": f"Press Control + C in {TERMINAL} if it keeps running.",
            "problems": [{"problem": "\"Unable to locate a Java Runtime\" or \"javac: command not found\".", "fix": "Install a JDK (for example Temurin from https://adoptium.net)."}],
            "launch": {"type": "terminal", "command": command, "url": "", "installs": bool(tools)}}


def _c_family(root, tree, top, has, ext, hint):
    cpp, c = ext(".cpp", ".cc", ".cxx"), ext(".c")
    if not (cpp or c or has("CMakeLists.txt", "Makefile")):
        return None
    run = ".\\app.exe" if WINDOWS else "./app"
    compiler = (shutil.which("clang++") or shutil.which("g++")) if cpp else (shutil.which("clang") or shutil.which("gcc") or shutil.which("cc"))
    if has("CMakeLists.txt") and not tool_version("cmake") and compiler and len(cpp or c) <= 40:
        # CMake isn't installed here but a compiler is: build it directly, so it runs on this computer as it is
        target = re.search(r"add_executable\s*\(\s*([\w-]+)", _read(root, "CMakeLists.txt"))
        target = target.group(1) if target else "app"
        includes = " ".join(f"-I{d}" for d in sorted({os.path.dirname(h) or "." for h in ext(".h", ".hpp", ".hh")}))
        files = " ".join(p for p in (cpp or c) if not re.search(r"(?:^|/)tests?/|_test\.|test_", p))
        name = target + (".exe" if WINDOWS else "")
        here = ".\\" if WINDOWS else "./"
        command = f"{os.path.basename(compiler)} {'-std=c++17 ' if cpp else ''}{includes + ' ' if includes else ''}{files} -o {name} && {here}{name}"
        needs = [_need("A C/C++ compiler", ("clang++", "g++") if cpp else ("clang", "gcc", "cc"), "https://code.visualstudio.com/docs/languages/cpp", "Compiles the code.")]
        return {"kind": "c", "stack": ("C++" if cpp else "C") + " (CMake project)", "requirements": needs,
                "steps": [{"text": OPEN_TERMINAL}, _cd(root),
                          {"text": "Compile it with the compiler on this computer, then run the program it makes. (The project also has a CMake build; "
                                   "CMake isn't installed here, and this command doesn't need it.)", "command": command, "where": f"In {TERMINAL}, in the project folder."}],
                "expect": "It compiles in a few seconds, then runs.", "stop": f"Press Control + C in {TERMINAL} if it keeps running.",
                "problems": [{"problem": "\"command not found\" for the compiler.", "fix": "Install a compiler: on a Mac run xcode-select --install."}],
                "launch": {"type": "terminal", "command": command, "url": "", "installs": False}}
    if has("CMakeLists.txt"):
        target = re.search(r"add_executable\s*\(\s*([\w-]+)", _read(root, "CMakeLists.txt"))
        target = target.group(1) if target else "app"
        built = "build\\Debug\\" + target + ".exe" if WINDOWS else "./build/" + target
        command = f"cmake -S . -B build && cmake --build build && {built}"
        needs = [_need("CMake", ("cmake",), "https://cmake.org/download/", "Configures the build."), _need("A C/C++ compiler", ("c++", "g++", "clang++", "cl"), "https://code.visualstudio.com/docs/languages/cpp", "Compiles the code.")]
    elif has("Makefile"):
        target = re.search(r"^(?:TARGET|BIN|PROGRAM|NAME|EXEC|OUT)\s*:?=\s*(\S+)", _read(root, "Makefile"), re.M)
        command = "make" + (f" && ./{target.group(1)}" if target else "")
        needs = [_need("make and a C/C++ compiler", ("make",), "https://code.visualstudio.com/docs/languages/cpp", "Builds the project.")]
    else:
        compiler = ("g++" if not shutil.which("clang++") else "clang++") if cpp else ("gcc" if not shutil.which("clang") else "clang")
        files = " ".join(cpp or c)
        command = f"{compiler} {'-std=c++17 ' if cpp else ''}{files} -o app && {run}"
        needs = [_need("A C/C++ compiler", ("clang++", "g++", "c++") if cpp else ("clang", "gcc", "cc"),
                       "Apple's Command Line Tools: xcode-select --install" if MAC else "https://code.visualstudio.com/docs/languages/cpp", "Compiles the code.")]
    return {"kind": "c", "stack": "C++" if cpp else "C", "requirements": needs,
            "steps": [{"text": OPEN_TERMINAL}, _cd(root), {"text": "Compile it, then run the program it makes.", "command": command, "where": f"In {TERMINAL}, in the project folder."}],
            "expect": "It compiles in a moment, then runs.", "stop": f"Press Control + C in {TERMINAL} if it keeps running.",
            "problems": [{"problem": "\"command not found\" for the compiler.", "fix": "Install a compiler: on a Mac run xcode-select --install."}],
            "launch": {"type": "terminal", "command": command, "url": "", "installs": False}}


def _shell(root, tree, top, has, ext, hint):
    scripts = ext(".sh", ".bash", ".zsh", ".ps1")
    if not scripts:
        return None
    script = next((s for s in scripts if "/" not in s), scripts[0])
    command = f"powershell -ExecutionPolicy Bypass -File {script}" if script.endswith(".ps1") else f"bash {script}"
    return {"kind": "shell", "stack": "PowerShell script" if script.endswith(".ps1") else "Shell script",
            "requirements": [{"name": "Nothing to install", "why": "The terminal that comes with the computer runs it.", "installed": None, "version": "", "get": ""}],
            "steps": [{"text": OPEN_TERMINAL}, _cd(root), {"text": "Run the script.", "command": command, "where": f"In {TERMINAL}, in the project folder."}],
            "expect": "It runs and prints what it does.", "stop": f"Press Control + C in {TERMINAL}.",
            "problems": [{"problem": "\"Permission denied\".", "fix": "Run it with bash as shown (no need to make it executable)."}],
            "launch": {"type": "terminal", "command": command, "url": "", "installs": False}}


def _sql(root, tree, top, has, ext, hint):
    sql = ext(".sql")
    if not sql:
        return None
    first = next((s for s in sql if re.search(r"schema|create|init|setup", s, re.I)), sql[0])
    rest = [s for s in sql if s != first]
    command = f"sqlite3 project.db < {first}" + "".join(f" && sqlite3 project.db < {s}" for s in rest[:4])
    return {"kind": "sql", "stack": "SQL (SQLite)",
            "requirements": [_need("SQLite", ("sqlite3",), "https://www.sqlite.org/download.html", "A small database that keeps everything in one file.")],
            "steps": [{"text": OPEN_TERMINAL}, _cd(root),
                      {"text": f"Create the database file and run {', '.join(sql[:5])} in it.", "command": command, "where": f"In {TERMINAL}, in the project folder."},
                      {"text": "Look inside it.", "command": "sqlite3 project.db", "where": "Then type .tables to list the tables, or any SQL query; .quit leaves."}],
            "expect": "A project.db file appears in the folder with the tables (and data) from the SQL files.", "stop": "Type .quit.",
            "problems": [{"problem": "A syntax error near a word.", "fix": "These files may be written for another database (PostgreSQL, MySQL); ask me to convert them to SQLite."}],
            "launch": {"type": "terminal", "command": command, "url": "", "installs": False}}


def as_text(root: str, plan: dict) -> str:
    """The guide as plain text, for the AI answering "how do I run it?" (so its answer matches the How to run panel)."""
    lines = [f"Project folder: {root}", f"Kind: {plan.get('stack', '')}"]
    for r in plan.get("requirements") or []:
        state = {True: f"installed here ({r.get('version')})", False: "NOT installed here", None: ""}[r.get("installed")]
        lines.append(f"Needs: {r['name']} {state}".rstrip())
    for i, step in enumerate(plan.get("steps") or [], 1):
        lines.append(f"{i}. {step['text'].replace('**', '')}" + (f"  Command: {step['command']}" if step.get("command") else ""))
    if plan.get("expect"):
        lines.append(f"What happens: {plan['expect']}")
    if plan.get("stop"):
        lines.append(f"To stop: {plan['stop']}")
    if not plan.get("known"):
        lines.append("(Jarvis doesn't recognise this kind of project: these steps were not worked out from its files.)")
    return "\n".join(lines)


def move_to_trash(folder: str) -> None:
    """Moves a folder to the Trash (the Recycle Bin on Windows), where it can be put back. Never a permanent delete:
    if the Trash can't take it, this raises and nothing is removed."""
    if MAC:
        escaped = folder.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'tell application "Finder" to delete (POSIX file "{escaped}" as alias)'],
                       check=True, capture_output=True, timeout=30)
    elif WINDOWS:
        quoted = folder.replace("'", "''")
        subprocess.run(["powershell", "-NoProfile", "-Command", "Add-Type -AssemblyName Microsoft.VisualBasic; "
                        f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory('{quoted}', 'OnlyErrorDialogs', 'SendToRecycleBin')"],
                       check=True, capture_output=True, timeout=60)
    elif shutil.which("gio"):
        subprocess.run(["gio", "trash", folder], check=True, capture_output=True, timeout=30)
    else:
        raise RuntimeError("this computer has no Trash Jarvis can use")
    if os.path.exists(folder):
        raise RuntimeError("the Trash didn't take it")


def installed_tools() -> str:
    """What this computer can build and run, for the AI choosing a project's technology (so it doesn't pick a build tool
    the user doesn't have). Each tool is asked for its version once per session."""
    tools = [("Python", ("python3", "python", "py")), ("Node.js", ("node",)), ("a C/C++ compiler", ("clang++", "g++", "cl")), ("CMake", ("cmake",)),
             ("make", ("make",)), ("Swift", ("swift",)), (".NET", ("dotnet",)), ("Java (javac)", ("javac",)), ("Go", ("go",)), ("Rust (cargo)", ("cargo",)),
             ("SQLite", ("sqlite3",))]
    have = [f"{name} {tool_version(*names)}" for name, names in tools if tool_version(*names)]
    missing = [name for name, names in tools if not tool_version(*names)]
    return f"Installed on the user's computer: {', '.join(have) or 'nothing found'}. Not installed: {', '.join(missing) or 'none of the usual ones missing'}."


# ---------- starting it, after the user said yes ----------
def launch(root: str, plan: dict) -> str:
    """Start the project as the guide describes. Returns what happened, said truthfully (a Terminal that opened is not
    a program that worked: its output is in that window)."""
    how = (plan or {}).get("launch") or {}
    if how.get("type") == "browser":
        path = how.get("path", "")
        if not os.path.isfile(path):
            raise RuntimeError(f"{os.path.basename(path) or 'The page'} isn't in the project any more.")
        webbrowser.open("file://" + path.replace("\\", "/") if not WINDOWS else path)
        return f"Opened {os.path.relpath(path, root)} in your browser."
    command = how.get("command", "")
    if not command:
        raise RuntimeError("I don't know which command starts this project, so I didn't start anything.")
    if MAC:
        script = f"cd {shlex.quote(root)} && {command}"
        escaped = script.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'tell application "Terminal" to do script "{escaped}"', "-e", 'tell application "Terminal" to activate'],
                       check=True, capture_output=True, timeout=15)
    elif WINDOWS:
        subprocess.Popen(f'start "Jarvis project" cmd /k "cd /d "{root}" && {command}"', shell=True)
    else:
        terminal = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal") or shutil.which("konsole")
        if not terminal:
            raise RuntimeError("I couldn't find a terminal program to run it in.")
        subprocess.Popen([terminal, "-e", "bash", "-c", f"cd {shlex.quote(root)} && {command}; exec bash"])
    said = f"Started it in a {TERMINAL} window: {command}."
    if how.get("url"):
        said += f" When it says it's ready, open {how['url']}."
    return said + " Its output, and any error, is in that window."
