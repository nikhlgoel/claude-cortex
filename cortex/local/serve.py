"""Start, stop and health-check the local ``llama-server`` and the local gateway.

Two processes, both bound to 127.0.0.1 only:

* ``llama-server`` - the model, behind a bearer token (``--api-key-file``).
* the Cortex gateway in ``local`` mode - fixes the Anthropic-compatibility gaps
  (see ``shaping.py``) between Claude Code and ``llama-server``.

Each records ``{pid, port, model, started}`` in ``state/``. Before anything is
stopped the pid's image name is checked: a recycled pid belonging to an unrelated
program must never be killed because an old state file mentions it.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .. import jsonfile, proc, tools
from ..profiles import CortexError
from . import catalog, plan, runtime, store

HEALTH_TIMEOUT_S = 240          # a 13 GB model can take minutes to map in
GATEWAY_TIMEOUT_S = 20
EXPECTED_IMAGES = {"server": ("llama-server",), "gateway": ("python", "py")}


class ServeError(CortexError):
    pass


# -------------------------------------------------------------------------- state

def _state_path(name):
    return os.path.join(store.state_dir(), f"{name}.json")


def read_state(name):
    return jsonfile.read(_state_path(name), {})


def _write_state(name, pid, port, model):
    os.makedirs(store.state_dir(), exist_ok=True)
    jsonfile.write(_state_path(name),
                   {"pid": pid, "port": port, "model": model,
                    "started": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                   backup=False)


def _clear_state(name):
    try:
        os.unlink(_state_path(name))
    except OSError:
        pass


def _image_name(pid):
    """Lower-case executable name of ``pid``, or None if it is not running / unknown."""
    try:
        if os.name == "nt":
            result = proc.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], timeout=15)
            line = (result.stdout or "").strip().splitlines()[:1]
            if not line or not line[0].startswith('"'):
                return None
            return line[0].split('","')[0].strip('"').lower()
        with open(f"/proc/{pid}/comm", encoding="utf-8") as fh:
            return fh.read().strip().lower()
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def is_ours(name):
    """True when the recorded pid is alive AND looks like the process we started."""
    pid = read_state(name).get("pid")
    if not isinstance(pid, int):
        return False
    image = _image_name(pid)
    return bool(image) and any(token in image for token in EXPECTED_IMAGES[name])


class _Pid:
    """``proc.kill_tree`` only needs ``.pid`` and ``.kill()``."""

    def __init__(self, pid):
        self.pid = pid

    def kill(self):
        pass


def stop(name):
    """Stop one managed process. Returns True if something was stopped."""
    pid = read_state(name).get("pid")
    stopped = False
    if isinstance(pid, int) and is_ours(name):
        proc.kill_tree(_Pid(pid))
        stopped = True
    _clear_state(name)
    return stopped


def stop_all():
    return {name: stop(name) for name in ("gateway", "server")}


# ------------------------------------------------------------------------ helpers

def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def http_ok(url, headers=None, timeout=3):
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        exc.close()                       # a 503 while the model loads must not leak a socket per poll
        return False
    except (urllib.error.URLError, OSError, ValueError):
        return False


def log_path(name):
    return os.path.join(store.logs_dir(), f"{name}.log")


def tail(path, lines=15):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-lines:]).strip()
    except OSError:
        return ""


def _spawn(command, log_file, env=None):
    """Start a detached child whose output goes to ``log_file``. Returns the Popen."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    kwargs = {"stdin": subprocess.DEVNULL, "stderr": subprocess.STDOUT, "env": env, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kwargs["start_new_session"] = True
    with open(log_file, "ab") as log:            # the child keeps its own inherited handle
        return subprocess.Popen(proc.resolve(command), stdout=log, **kwargs)


# --------------------------------------------------------------------- model entry

def entry_for(model_id, cfg):
    """Catalog entry for ``model_id``, or a conservative one for an arbitrary GGUF.

    A model that is not in the catalog has no known chat template or sampling, so it
    is treated as a plain non-thinking model: the gateway then removes every
    thinking-related field rather than guessing at a template it has not seen.
    """
    known = catalog.get(model_id)
    if known:
        return known
    installed = (cfg.get("models") or {}).get(model_id) or {}
    size_gb = (installed.get("size_bytes") or 0) / plan.GIB
    return {"title": model_id, "params_b": max(1.0, round(size_gb * 1.8, 1)), "moe": False,
            "template": "none", "ctx": (16384, 32768), "tier": "custom",
            "sampling": {"plain": {"temperature": 0.7, "top_p": 0.8, "top_k": 20}},
            "min_free_ram_gb": size_gb}


# -------------------------------------------------------------------------- start

def start_server(cfg, model_id, hw=None, force=False, ctx=None):
    """Start llama-server for an installed model. Returns the port. Idempotent."""
    installed = (cfg.get("models") or {}).get(model_id)
    if not installed:
        raise ServeError(f"model '{model_id}' is not installed. See: cc local list")
    files = installed.get("files") or []
    if not files or not all(os.path.isfile(f) for f in files):
        raise ServeError(f"model files for '{model_id}' are missing from disk; reinstall with: "
                         f"cc local install {model_id}")

    port = cfg["ports"]["server"]
    if is_ours("server") and read_state("server").get("model") == model_id and port_in_use(port):
        return port
    if is_ours("server"):
        stop("server")                           # a different model is loaded
    if port_in_use(port):
        raise ServeError(f"port {port} is already in use by another program; change it in "
                         f"{store.config_path()} (ports.server)")

    exe = runtime.find(cfg)
    if not exe:
        raise ServeError("llama.cpp is not installed. Run: cc local install --runtime")

    entry = entry_for(model_id, cfg)
    hw = hw or plan.detect()
    weights_gb = (installed.get("size_bytes") or 0) / plan.GIB or entry.get("approx_gb", 0)
    parallel = max(1, int(cfg["gateway"].get("max_concurrent", 1)))
    per_slot = ctx or installed.get("ctx") or entry["ctx"][0]
    # Memory is sized for every slot's cache together; llama_args scales -c to match.
    verdict = plan.fit(entry, weights_gb, hw, per_slot * parallel)
    verdict["ctx"] = per_slot
    if verdict["verdict"] == "no" and not force:
        raise ServeError("this model does not fit right now:\n  " + "\n  ".join(verdict["notes"])
                         + "\n  (use --force to try anyway)")

    store.token()                                # ensure it exists and is restricted
    supported = runtime.supported_flags(exe)
    notes = []

    def build(minimal):
        try:
            return plan.llama_args(files[0], entry, verdict, port, cfg["claude"]["alias"],
                                   store.token_path(), parallel=parallel, minimal=minimal,
                                   supported=supported, notes=notes)
        except ValueError as exc:
            raise ServeError(str(exc)) from None

    outcome, detail = _launch_and_wait(exe, build(False), port, model_id, notes)
    if outcome == "exited":
        # The most likely cause is an optional flag this build rejects. Retry once with only
        # the essentials before giving up; the log keeps both attempts.
        notes = ["the server exited while loading; retrying with only the essential flags"]
        outcome, detail = _launch_and_wait(exe, build(True), port, model_id, notes)
    if outcome == "ok":
        return port
    if outcome == "timeout":
        stop("server")
        raise ServeError(f"llama-server did not become ready within {HEALTH_TIMEOUT_S}s. "
                         f"Last log lines:\n{detail}")
    raise ServeError(f"llama-server exited while loading (even with only the essential flags). "
                     f"Last log lines:\n{detail}")


def _launch_and_wait(exe, args, port, model_id, notes):
    """Start llama-server and wait for it. Returns ``("ok"|"exited"|"timeout", log_tail)``."""
    log = log_path("llama-server")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:             # a readable trail for `cc local logs`
        fh.write("\n=== cortex: starting llama-server ===\n")
        for note in notes:
            fh.write(f"=== cortex note: {note}\n")
    child = _spawn([exe] + args, log)
    _write_state("server", child.pid, port, model_id)
    deadline = time.time() + HEALTH_TIMEOUT_S
    while time.time() < deadline:
        if child.poll() is not None:
            _clear_state("server")
            return "exited", tail(log)
        if http_ok(f"http://127.0.0.1:{port}/health"):
            return "ok", ""
        time.sleep(1.0)
    return "timeout", tail(log)


def start_gateway(cfg, model_id):
    """Start the local-mode gateway in front of llama-server. Returns its port."""
    port = cfg["ports"]["gateway"]
    if is_ours("gateway") and read_state("gateway").get("model") == model_id and port_in_use(port):
        return port
    if is_ours("gateway"):
        stop("gateway")
    if port_in_use(port):
        raise ServeError(f"port {port} is already in use by another program; change it in "
                         f"{store.config_path()} (ports.gateway)")
    script = tools.find_script("cortex-gateway.py")
    if not script:
        raise ServeError("cortex-gateway.py was not found; run the Cortex installer again")

    env = dict(os.environ)
    env.update({"CORTEX_GATEWAY_ROUTE": "local", "CORTEX_LOCAL_HOME": store.home(),
                "CORTEX_LOCAL_MODEL": model_id, "PYTHONUTF8": "1"})
    env.pop("CLAUDECODE", None)
    # The gateway must import the same core that is running now, not whichever copy it
    # happens to find first.
    core_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env["PYTHONPATH"] = core_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    child = _spawn([sys.executable, script, "--port", str(port)], log_path("gateway"), env=env)
    _write_state("gateway", child.pid, port, model_id)

    deadline = time.time() + GATEWAY_TIMEOUT_S
    while time.time() < deadline:
        if child.poll() is not None:
            _clear_state("gateway")
            raise ServeError(f"the gateway exited with code {child.returncode}:\n{tail(log_path('gateway'))}")
        if http_ok(f"http://127.0.0.1:{port}/health"):
            return port
        time.sleep(0.5)
    stop("gateway")
    raise ServeError(f"the gateway did not start within {GATEWAY_TIMEOUT_S}s:\n{tail(log_path('gateway'))}")


def ensure(cfg, model_id, hw=None, force=False):
    """Make sure model and gateway are running. Returns the gateway's base URL."""
    start_server(cfg, model_id, hw=hw, force=force)
    port = start_gateway(cfg, model_id)
    return f"http://127.0.0.1:{port}"


def status(cfg):
    """Plain-data status for ``cc local status`` and the doctor."""
    out = {}
    for name in ("server", "gateway"):
        state = read_state(name)
        port = cfg["ports"][name]
        out[name] = {"running": is_ours(name), "port": port, "model": state.get("model"),
                     "started": state.get("started"), "listening": port_in_use(port)}
    return out
