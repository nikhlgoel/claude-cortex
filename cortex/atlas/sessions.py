"""
Which Claude sessions are open, and keeping one floating button alive per project.

A session hook (``scripts/cortex-session-hook.py``) calls ``register_session`` when a Claude session
starts and ``end_session`` when it ends, in every surface that runs hooks (terminal, IDE, Desktop's
Code tab). The button follows those records: it appears when a session is open in a project that has a
map, and quits itself a little after the last one closes.

Everything is plain small files under ``<cortex data dir>/studio/``:

    sessions/<session>.json    {session, cwd, root, key, started, touched}
    button-<key>.json          {pid, port, beat}  - written every few seconds by the running button
    button-<key>.lock          created exclusively, so two sessions starting together start one button
    settings.json              {"button": true}

No daemon, no database, nothing to migrate; deleting the folder resets everything.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time

from ..palace import graph as graph_mod
from ..palace import store as store_mod

SESSION_MAX_AGE = 24 * 3600     # a session with no sign of life for a day is treated as gone (a crash)
BEAT_TTL = 25.0                 # seconds without a heartbeat and the button is considered dead
_OFF = {"off", "0", "false", "no", "disable", "disabled"}


# --------------------------------------------------------------------------- locations

def studio_dir():
    return os.path.join(os.path.dirname(store_mod.home()), "studio")


def _sessions_dir():
    return os.path.join(studio_dir(), "sessions")


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(name))[:96] or "unknown"


def _session_path(session_id):
    # The "s-" prefix keeps ids such as "nul" or "con" from becoming Windows device names.
    return os.path.join(_sessions_dir(), "s-" + _safe(session_id) + ".json")


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- settings

def settings():
    data = _read_json(os.path.join(studio_dir(), "settings.json")) or {}
    return {"button": data.get("button", True) is not False}


def set_button_enabled(enabled):
    path = os.path.join(studio_dir(), "settings.json")
    data = _read_json(path) or {}
    data["button"] = bool(enabled)
    _write_json(path, data)


def button_enabled(env=None):
    """On by default. ``CORTEX_BUTTON=off`` or ``cc graph button off`` turns it off."""
    if str((env or os.environ).get("CORTEX_BUTTON", "")).strip().lower() in _OFF:
        return False
    return settings()["button"]


# --------------------------------------------------------------------------- sessions

def register_session(session_id, cwd, now=None):
    """Record (or refresh) an open session. Returns the record."""
    key, root = store_mod.project_identity(cwd or os.getcwd())
    now = now if now is not None else time.time()
    path = _session_path(session_id)
    previous = _read_json(path) or {}
    record = {"session": str(session_id), "cwd": os.path.abspath(cwd or os.getcwd()), "root": root, "key": key,
              "started": previous.get("started", now), "touched": now}
    _write_json(path, record)
    return record


def touch_session(session_id, now=None):
    """Cheap proof of life, called from the prompt hook. Does nothing for an unknown session."""
    path = _session_path(session_id)
    record = _read_json(path)
    if record:
        record["touched"] = now if now is not None else time.time()
        _write_json(path, record)


def end_session(session_id):
    for path in (_session_path(session_id), _ground_path(session_id)):
        try:
            os.remove(path)
        except OSError:
            pass


def _ground_path(session_id):
    return os.path.join(studio_dir(), "ground", "s-" + _safe(session_id) + ".json")


def claim_correction(session_id, prompt_id, now=None, cooldown=45.0):
    """The Stop check may speak **once per user prompt**; this is the guard. True the first time.

    Why it exists: a Stop hook that blocks makes Claude continue, and then the Stop hook runs again on the
    new answer. Claude Code's documentation names no protection against that loop, and a field that would
    say "you are already continuing" is not documented either - so the guard is ours and does not depend on
    one. The documented ``prompt_id`` identifies the turn; with no id the guard falls back to a cooldown.
    """
    now = now if now is not None else time.time()
    path = _ground_path(session_id)
    record = _read_json(path) or {}
    if prompt_id:
        if record.get("prompt_id") == prompt_id:
            return False
    elif now - float(record.get("at", 0)) < cooldown:
        return False
    _write_json(path, {"prompt_id": prompt_id, "at": now})
    return True


def live_sessions(key=None, now=None):
    """Open sessions (optionally one project's). Stale records are removed as they are found."""
    now = now if now is not None else time.time()
    out = []
    try:
        names = os.listdir(_sessions_dir())
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(_sessions_dir(), name)
        record = _read_json(path)
        if not record or now - float(record.get("touched", 0)) > SESSION_MAX_AGE:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        if key is None or record.get("key") == key:
            out.append(record)
    return out


# --------------------------------------------------------------------------- the button's process

def _button_path(key):
    return os.path.join(studio_dir(), "button-%s.json" % _safe(key))


def button_alive(key, now=None):
    record = _read_json(_button_path(key))
    now = now if now is not None else time.time()
    return bool(record) and now - float(record.get("beat", 0)) < BEAT_TTL


def write_beat(key, pid, port, now=None):
    _write_json(_button_path(key), {"pid": pid, "port": port, "beat": now if now is not None else time.time()})


def clear_button(key):
    for suffix in (".json", ".lock"):
        try:
            os.remove(_button_path(key)[:-5] + suffix)
        except OSError:
            pass


def button_pid(key):
    record = _read_json(_button_path(key))
    return int(record["pid"]) if record and record.get("pid") else None


def try_lock(key, now=None):
    """Become *the* button for this project. False when a live one already owns it."""
    lock = _button_path(key)[:-5] + ".lock"
    now = now if now is not None else time.time()
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    for _attempt in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if button_alive(key, now):
                return False
            try:                                            # a dead owner left its lock behind
                if now - os.path.getmtime(lock) < BEAT_TTL:
                    return False                            # it is only just starting
                os.remove(lock)
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        return True
    return False


# --------------------------------------------------------------------------- should one appear?

def gui_available():
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def tkinter_available():
    try:
        return importlib.util.find_spec("_tkinter") is not None
    except (ImportError, ValueError):
        return False


def has_something_to_show(root):
    """A project gets a button only if it has a map or a palace to open."""
    if graph_mod.find_graphs(root):
        return True
    try:
        return os.path.isfile(store_mod.db_path("project", root))
    except Exception:
        return False


def _python_for_gui():
    """pythonw.exe on Windows: the same interpreter, without a console window."""
    exe = sys.executable or "python"
    if sys.platform.startswith("win"):
        candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(candidate):
            return candidate
    return exe


def launch_command(args, python=None):
    """``(argv, cwd)`` that runs ``cc graph <args>`` in a fresh interpreter.

    Deliberately not ``python -m cortex`` run from the project: Python puts the current directory first,
    so a project that has a top-level ``cortex`` folder of its own (this very repository, or a copy of an
    older one) would be imported instead of the real core, and the button would die silently - it runs
    without a console, so nobody would see why. Here the interpreter starts in a neutral folder and the
    real core is put first on the path explicitly.
    """
    core = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = "import sys; sys.path.insert(0, sys.argv[1]); from cortex.atlas import cli; sys.exit(cli.main(sys.argv[2:]))"
    cwd = studio_dir()
    os.makedirs(cwd, exist_ok=True)
    return [python or _python_for_gui(), "-c", code, core] + list(args), cwd


def spawn_button(root):
    """Start the button as a detached background process. Returns the Popen."""
    command, cwd = launch_command(["button", "start", "--project", root, "--follow-sessions"])
    env = dict(os.environ, PYTHONUTF8="1")
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "close_fds": True, "env": env, "cwd": cwd}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000     # DETACHED | NEW_GROUP | NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def ensure_button(root, spawn=None, env=None, now=None):
    """Make sure a button is running for ``root``. Returns what happened, as a short word:

    ``disabled`` | ``no-screen`` | ``no-tk`` | ``nothing-to-show`` | ``running`` | ``started`` | ``failed``
    """
    if not button_enabled(env):
        return "disabled"
    if not gui_available():
        return "no-screen"
    if not tkinter_available():
        return "no-tk"
    if not has_something_to_show(root):
        return "nothing-to-show"
    key, _ = store_mod.project_identity(root)
    if button_alive(key, now):
        return "running"
    try:
        (spawn or spawn_button)(root)
    except Exception:
        return "failed"
    return "started"
