"""Coding Mode's conversations: one chat per project, kept on disk, and what each new message asks for.

A thread is {"id", "title", "path", "created", "updated", "messages": [...]}, saved as DATA_DIR/coding_chats/<id>.json.
"path" is the folder of the project the chat works on (each change adds a history record, the folder stays), empty
until the first build. Messages
are {"id", "role": "user" | "jarvis", "kind": "text" | "work" | "confirm" | "error", "text", "at", ...}; a "work"
message carries the job it shows (updated in place while the job runs) and a "confirm" message the action it asks
about ("run"), with "answer" once the user chose.

route() decides what a message wants. Plain commands ("run it", "open it in VS Code", "run the tests") are recognized
directly; anything else is decided by a short question to the AI, with the conversation and the project's files in
view. If the AI can't be asked, the safe guess is used: with no project, build one; with one, a question is answered
(it changes nothing) and anything else changes the project.
"""
import json
import os
import re
import threading
import time
import uuid

import coder
import paths

CHATS_DIR = os.path.join(paths.DATA_DIR, "coding_chats")
MAX_MESSAGES = 400
_lock = threading.Lock()

ACTIONS = ("create", "change", "answer", "run", "open", "tests", "deliver", "new")


def _path(thread_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", thread_id or ""):
        raise ValueError("not a thread id")
    return os.path.join(CHATS_DIR, f"{thread_id}.json")


def new_thread(path: str = "", title: str = "") -> dict:
    now = time.time()
    thread = {"id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6], "title": title, "path": path,
              "created": now, "updated": now, "messages": []}
    save(thread)
    return thread


def load(thread_id: str):
    try:
        with open(_path(thread_id), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and isinstance(data.get("messages"), list) else None
    except (OSError, ValueError):
        return None


def save(thread: dict) -> None:
    thread["messages"] = thread["messages"][-MAX_MESSAGES:]
    with _lock:
        os.makedirs(CHATS_DIR, exist_ok=True)
        target = _path(thread["id"])
        temp = target + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(thread, f, ensure_ascii=False, indent=0)
        os.replace(temp, target)   # never a half-written chat, even if Jarvis stops mid-save


def delete(thread_id: str) -> None:
    try:
        os.remove(_path(thread_id))
    except OSError:
        pass


def threads() -> list:
    """Every saved chat, newest first, without its messages."""
    found = []
    try:
        names = os.listdir(CHATS_DIR)
    except OSError:
        return []
    for name in names:
        if name.endswith(".json"):
            thread = load(name[:-5])
            if thread:
                found.append({k: v for k, v in thread.items() if k != "messages"} | {"count": len(thread["messages"])})
    return sorted(found, key=lambda t: t.get("updated", 0), reverse=True)


def for_path(path: str):
    """The chat of the project in that folder (the newest, if there are several)."""
    found = next((t for t in threads() if path and t.get("path") == path), None)
    return load(found["id"]) if found else None


def add(thread: dict, role: str, text: str = "", kind: str = "text", **extra) -> dict:
    message = {"id": extra.pop("id", None) or uuid.uuid4().hex[:10], "role": role, "kind": kind, "text": text, "at": time.time(), **extra}
    thread["messages"].append(message)
    thread["updated"] = message["at"]
    if role == "user" and not thread.get("title"):
        thread["title"] = title_from(text)
    save(thread)
    return message


def update(thread: dict, message_id: str, **fields):
    for message in thread["messages"]:
        if message["id"] == message_id:
            message.update(fields)
            thread["updated"] = time.time()
            save(thread)
            return message
    return None


def title_from(text: str) -> str:
    words = re.sub(r"\s+", " ", (text or "").strip()).split(" ")
    title = " ".join(words[:8])
    return (title[:60].rstrip() + "…") if len(title) > 60 or len(words) > 8 else title


def history(thread: dict, last: int = 10, chars: int = 2400) -> str:
    """The recent conversation as the AI is shown it (newest last), within `chars` characters."""
    lines = []
    for m in thread["messages"][-last:]:
        if m["kind"] == "work":
            job = m.get("job") or {}
            text = f"[{job.get('action', 'work')} {job.get('phase', '')}] {m.get('text') or job.get('summary') or ''}"
        else:
            text = m.get("text", "")
        who = "User" if m["role"] == "user" else "Jarvis"
        lines.append(f"{who}: {re.sub(r'\s+', ' ', text).strip()[:600]}")
    out = "\n".join(lines)
    return out[-chars:]


# ---------- what a message asks for ----------
_LEAD = r"^(?:(?:hey |ok |okay )?jarvis[, ]+)?(?:(?:please|now|ok|okay|and|then|can you|could you|would you)[ ,]+)*"
_RUN = re.compile(_LEAD + r"(?:run|start|launch|execute|play|open|show)(?: me)?(?: it| this| that| the (?:app|project|program|game|site|website|page|calc\w*|script|server))?"
                  r"(?: again| now| for me| please)*[.!]?$", re.I)
_TESTS = re.compile(_LEAD + r"(?:run|execute|do)(?: all)?(?: the| its| my)? (?:unit |automated )?tests?(?: again| now| please)*[.!]?$", re.I)
_OPEN = re.compile(r"\b(?:open|show|put|send|reveal)\b.{0,40}\b(?P<where>vs ?code|visual studio code|code editor|finder|explorer|folder|browser)\b", re.I)
_DELIVER = re.compile(r"\b(?:make|create|export|save|send|put|copy|give)\b.{0,40}\b(?P<where>word(?: document)?|docx|notes?(?: app)?|google drive|drive|zip)\b", re.I)


def quick_route(text: str, have_project: bool):
    """The unmistakable commands, without asking the AI: {"action", ...} or None."""
    n = " ".join((text or "").strip().split())
    if not have_project:
        return None
    if _TESTS.match(n):
        return {"action": "tests"}
    if _RUN.match(n):
        return {"action": "run"}
    opening = _OPEN.search(n)
    if opening and len(n.split()) <= 12 and not re.search(r"\b(?:add|change|make it|fix|build|create)\b", n, re.I):
        where = opening.group("where").lower()
        return {"action": "open", "where": "vscode" if re.search(r"code", where) else "browser" if "browser" in where else "folder"}
    delivering = _DELIVER.search(n)
    if delivering and len(n.split()) <= 14:
        where = delivering.group("where").lower()
        return {"action": "deliver", "where": "word" if re.search(r"word|docx", where) else "notes" if "note" in where else "gdrive" if "drive" in where else "zip"}
    return None


ROUTE_PROMPT = """You route messages in a coding assistant's chat. Decide what the user's newest message asks for. Reply with one JSON object and nothing else:
{{"action": "<one of: create, change, answer, run, open, tests, deliver, new>", "where": "<for open: vscode, folder or browser; for deliver: word, notes, gdrive or zip; else empty>"}}

create  = build something new and there is no project in this chat yet
new     = build something new and unrelated to the current project (a separate project)
change  = modify the current project in any way: add features or files, fix bugs or errors, redesign, refactor, write tests, convert it
answer  = a question or a request for explanation that needs no files changed ("how do I run it?", "why didn't X work?", "what does main.py do?", "how can I see it?")
run     = start or open the finished project now so they can use or see it
open    = open the project in VS Code, the folder, or the browser
tests   = run the project's existing tests now
deliver = put it in a Word document, Notes, Google Drive or a zip

The project in this chat: {project}
The conversation so far (newest last):
{history}

The user's newest message: {message}"""


def route(text: str, thread: dict, project, ask) -> dict:
    """{"action", "where"}. ask(prompt) -> the AI's reply text, or raises."""
    quick = quick_route(text, bool(project))
    if quick:
        return quick
    describe = "none yet" if not project else (f"{project.get('name')} ({project.get('language') or 'unknown language'}), "
                                               f"files: {', '.join(f['path'] for f in (project.get('files') or [])[:30])}")
    fallback = {"action": ("answer" if re.search(r"\?\s*$|^(?:how|why|what|where|when|which|who|can|could|does|do|is|are|should|explain)\b", text.strip(), re.I)
                           else "change") if project else "create", "where": ""}
    try:
        reply = ask(ROUTE_PROMPT.format(project=describe, history=history(thread, last=8, chars=1600) or "(nothing yet)", message=text.strip()[:2000]))
        found = re.search(r"\{.*\}", reply or "", re.S)
        data = json.loads(found.group(0)) if found else {}
    except Exception as e:
        print(f"Coding Mode: couldn't ask the AI what that message wants ({e!r}); guessing {fallback['action']}.", flush=True)
        return fallback
    action = str(data.get("action") or "").lower().strip()
    if action not in ACTIONS:
        return fallback
    if not project and action in ("change", "run", "open", "tests", "deliver", "new"):
        action = "create" if action in ("change", "new") else "answer"
    if project and action == "create":
        action = "change"
    where = str(data.get("where") or "").lower().strip()
    return {"action": action, "where": where}


# ---------- the sidebar's own settings: hidden projects, the earlier-projects section, the sort order ----------
PREFS_FILE = os.path.join(paths.DATA_DIR, "coding_prefs.json")
SORTS = ("recent", "created", "name")


def prefs() -> dict:
    try:
        with open(PREFS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    hidden = [k for k in data.get("hidden", []) if isinstance(k, str)] if isinstance(data, dict) else []
    sort = data.get("sort") if isinstance(data, dict) and data.get("sort") in SORTS else "recent"
    show = data.get("showEarlier") if isinstance(data, dict) and isinstance(data.get("showEarlier"), bool) else True
    return {"hidden": hidden, "sort": sort, "showEarlier": show}


def save_prefs(**changes) -> dict:
    current = prefs()
    if changes.get("sort") in SORTS:
        current["sort"] = changes["sort"]
    if isinstance(changes.get("showEarlier"), bool):
        current["showEarlier"] = changes["showEarlier"]
    if isinstance(changes.get("hidden"), list):
        current["hidden"] = list(dict.fromkeys(k for k in changes["hidden"] if isinstance(k, str)))
    with _lock:
        os.makedirs(os.path.dirname(PREFS_FILE), exist_ok=True)
        temp = PREFS_FILE + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=1)
        os.replace(temp, PREFS_FILE)
    return current


def set_hidden(key: str, hidden: bool) -> dict:
    keys = [k for k in prefs()["hidden"] if k != key] + ([key] if hidden else [])
    return save_prefs(hidden=keys)


def rename(thread_id: str, title: str):
    """The chat's (and so the project's) name in Jarvis; the folder on disk keeps its name."""
    thread = load(thread_id)
    title = " ".join((title or "").split())[:80]
    if not thread or not title:
        return None
    thread["title"] = title
    save(thread)
    return thread


def set_aside(thread_id: str) -> bool:
    """Removes a chat from Jarvis's lists without destroying it: it moves to coding_chats/removed/ (recoverable)."""
    source = _path(thread_id)
    if not os.path.exists(source):
        return False
    target_dir = os.path.join(CHATS_DIR, "removed")
    os.makedirs(target_dir, exist_ok=True)
    os.replace(source, os.path.join(target_dir, f"{thread_id}-{int(time.time())}.json"))
    return True


# ---------- an auditable record of what Coding Mode did on this computer (never a secret, never file contents) ----------
AUDIT_FILE = os.path.join(paths.DATA_DIR, "coding_audit.log")
_SECRETISH = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|passwd|authorization)\s*[=:]\s*\S+")


def audit(action: str, **details) -> None:
    line = json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action,
                       **{k: _SECRETISH.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=…", str(v))[:400] for k, v in details.items()}},
                      ensure_ascii=False)
    try:
        with _lock:
            os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
            if os.path.exists(AUDIT_FILE) and os.path.getsize(AUDIT_FILE) > 2_000_000:   # bounded: the older half goes
                os.replace(AUDIT_FILE, AUDIT_FILE + ".1")
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError:
        pass
