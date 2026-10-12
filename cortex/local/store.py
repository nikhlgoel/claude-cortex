"""Local-model configuration, the gateway token, and the one consent gate.

Everything that downloads, installs or deletes goes through :func:`confirm`. That
function is the safety property of the whole feature: nothing is fetched from the
network, written into the models directory, or removed without a person having seen
the source, the size and the destination and said yes - and a Claude Code session
(an agent) can never say yes on a person's behalf.

Config lives in ``~/.claude/cortex-local/config.json`` (``CORTEX_LOCAL_HOME``
overrides). It holds no secrets. An unparseable file, or one written by a newer
schema, is preserved untouched and every writer refuses with the file named - the
same rule ``jsonfile.read_status`` exists for.
"""

from __future__ import annotations

import copy
import os
import secrets
import subprocess
import sys

from .. import jsonfile
from ..paths import shared_claude_dir
from ..profiles import CortexError

SCHEMA = 1

#: Status returned by :func:`load` in addition to jsonfile's own.
NEWER_SCHEMA = "newer_schema"

DEFAULTS = {
    "schema": SCHEMA,
    # Where large files go. None means "ask at first pull"; never silently C: when
    # that volume is tight (see plan.choose_data_dir).
    "data_dir": None,
    "hf": {
        "endpoint": "https://huggingface.co",
        "publishers": ["unsloth", "bartowski", "ggml-org", "lmstudio-community"],
    },
    "runtime": {"kind": "managed", "flavor": "llamacpp", "tag": None, "backend": None,
                "path": None},
    "ports": {"server": 8180, "gateway": 8189},
    "idle_stop_minutes": 30,
    "models": {},
    "active_model": None,
    "claude": {
        # Must NOT start with "claude" or contain "[1m]": Claude Code would then
        # treat it as a recognised Claude model, assume that model's context window,
        # and ignore the context cap we set.
        "alias": "local-coder",
        "tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
        "max_output": 8192,
        "lean_prompt": True,
        "env": {},
    },
    "reasoning": {
        "default_effort": "medium",
        # tokens; 0 = thinking off. start = first request after a real user message,
        # cont = tool-result follow-ups, on_error = follow-up after an is_error
        # tool_result. PROPOSED starting points - tune with a local sweep.
        "levels": {
            "low":    {"start": 0,     "cont": 0, "on_error": 0},
            "medium": {"start": 2048,  "cont": 0, "on_error": 1024},
            "high":   {"start": 4096,  "cont": 0, "on_error": 1024},
            "xhigh":  {"start": 8192,  "cont": 0, "on_error": 2048},
            "max":    {"start": 16384, "cont": 0, "on_error": 4096},
        },
    },
    "gateway": {"ping_after_s": 10, "ping_every_s": 10, "precheck": True,
                # One request at a time. Each extra slot multiplies the KV cache (memory), so
                # raise this only deliberately, e.g. for a subagent-heavy workflow.
                "log_requests": True, "max_concurrent": 1},
}


# ---------------------------------------------------------------------------- paths

def home():
    override = os.environ.get("CORTEX_LOCAL_HOME")
    return os.path.abspath(override) if override else os.path.join(shared_claude_dir(), "cortex-local")


def config_path():
    return os.path.join(home(), "config.json")


def state_dir():
    return os.path.join(home(), "state")


def logs_dir():
    return os.path.join(home(), "logs")


def token_path():
    return os.path.join(home(), "token")


# --------------------------------------------------------------------------- config

def _merge(base, over):
    """Deep-merge ``over`` onto a copy of ``base``; unknown keys in ``over`` are kept."""
    out = copy.deepcopy(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load():
    """Return ``(config, status)``. ``config`` is always usable (defaults merged in memory).

    status is MISSING / PARSED / UNPARSEABLE / NEWER_SCHEMA. For the last two the
    returned config is the defaults and MUST NOT be written back.
    """
    status, raw = jsonfile.read_status(config_path())
    if status in (jsonfile.MISSING, jsonfile.UNPARSEABLE):
        return copy.deepcopy(DEFAULTS), status
    if isinstance(raw.get("schema"), int) and raw["schema"] > SCHEMA:
        return copy.deepcopy(DEFAULTS), NEWER_SCHEMA
    return _merge(DEFAULTS, raw), status


def validate(cfg):
    """Return a list of human-readable problems with ``cfg`` (empty = fine)."""
    problems = []
    alias = str(cfg.get("claude", {}).get("alias", ""))
    if not alias or alias.lower().startswith("claude") or "[1m]" in alias.lower():
        problems.append(f"claude.alias '{alias}' must not start with 'claude' or contain "
                        f"'[1m]' (Claude Code would then assume a Claude model's context window)")
    ports = cfg.get("ports", {})
    for name in ("server", "gateway"):
        value = ports.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or not 1024 <= value <= 65535:
            problems.append(f"ports.{name} must be an integer 1024-65535")
    if ports.get("server") == ports.get("gateway"):
        problems.append("ports.server and ports.gateway must differ")
    return problems


def update(fn):
    """Locked read-modify-write of the config. Refuses (naming the file) on a file we must not touch."""
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with jsonfile.file_lock(path):
        cfg, status = load()
        if status == jsonfile.UNPARSEABLE:
            raise CortexError(f"{path} is not valid JSON, so it was not changed. Fix it by "
                              f"hand (earlier versions are kept as {path}.bak).")
        if status == NEWER_SCHEMA:
            raise CortexError(f"{path} was written by a newer Cortex (schema > {SCHEMA}); "
                              f"update Cortex instead of overwriting it.")
        fn(cfg)
        problems = validate(cfg)
        if problems:
            raise CortexError("invalid local-model config: " + "; ".join(problems))
        jsonfile.write(path, cfg)
    return cfg


# --------------------------------------------------------------------- token / ACLs

def restrict_to_owner(path):
    """Make ``path`` readable by its owner only. Returns True when enforced.

    chmod 0600 means nothing on Windows (it only toggles the read-only flag), so there
    the inherited permissions are stripped and the file is granted to the current user
    alone.
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    if os.name != "nt":
        return True
    user = os.environ.get("USERNAME")
    if not user:
        return False
    domain = os.environ.get("USERDOMAIN")
    principal = f"{domain}\\{user}" if domain else user
    try:
        result = subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", f"{principal}:F"],
                                capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def token(create=True, rotate=False):
    """The bearer token shared by llama-server, the gateway and the local profile."""
    path = token_path()
    if not rotate:
        try:
            with open(path, encoding="utf-8") as fh:
                existing = fh.read().strip()
            if existing:
                return existing
        except OSError:
            pass
    if not create:
        return ""
    value = secrets.token_hex(32)
    jsonfile.write_text(path, value)
    restrict_to_owner(path)
    return value


# --------------------------------------------------------------------------- consent

def in_agent_session():
    """True when running inside a Claude Code session (it sets CLAUDECODE for tool processes).

    An agent must never be able to approve a download or a delete on a person's
    behalf, so :func:`confirm` refuses here even with ``--yes``.
    """
    return bool(os.environ.get("CLAUDECODE"))


def confirm(question, facts, assume_yes=False, out=None):
    """Show what will happen and ask. Default is No. Returns True only on a real yes.

    * Inside a Claude Code session: always refuses, with an explanation.
    * No terminal and no ``--yes``: refuses (a script must opt in explicitly).
    * ``assume_yes`` skips only the *question*; the facts are still printed so the
      log shows what was approved.
    """
    out = out or sys.stdout
    for line in facts:
        print(f"  {line}", file=out)

    if in_agent_session():
        print("  Refused: this is a Claude Code session. Downloads, installs and deletes need "
              "a person at a terminal.\n  Run the same command yourself in a normal terminal.",
              file=sys.stderr)
        return False

    if assume_yes:
        return True

    if not sys.stdin.isatty():
        print("  Refused: no terminal to ask on. Re-run with --yes if you really mean it.",
              file=sys.stderr)
        return False

    try:
        answer = input(f"{question} [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")
