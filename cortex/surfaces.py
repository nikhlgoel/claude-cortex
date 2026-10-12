"""Surfaces: where a profile is used - terminal, IDE extensions, Claude Desktop.

A person can pick any mix at install time and add another later; the account, its chats
and its sessions are the same either way because a surface is only a *way of launching*
against the profile's existing folders. Applying a surface never moves or copies data.

* terminal - nothing to apply here: the ``cc`` shim and PATH are installed with the core.
* ide      - needs a profile choice (the extension takes one), so this only points at
             ``cc ide apply`` instead of rewriting editor settings on its own.
* desktop  - registers the Cortex MCP tools in the ``claude_desktop_config.json`` of each
             Desktop folder that ALREADY exists (the default one and any registered with
             ``cc profile adopt``). It never creates a Desktop folder.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from . import registry

ALL = registry.SURFACES
SERVER_KEY = "claude-cortex"


def parse(value, default=("terminal",)):
    """``"terminal,desktop"`` -> ``["terminal", "desktop"]``; raises ValueError on an unknown name."""
    if value is None or not str(value).strip():
        return list(default)
    chosen = [part.strip().lower() for part in str(value).replace(" ", ",").split(",") if part.strip()]
    bad = [s for s in chosen if s not in ALL]
    if bad:
        raise ValueError(f"unknown surface {', '.join(bad)}; choose from {', '.join(ALL)}")
    return sorted(set(chosen), key=ALL.index)


def register_desktop_mcp(cfg_path, command, script):
    """Add the Cortex MCP server to a Claude Desktop config without losing anything.

    A config that exists but is not valid JSON is left exactly as it is (the old installer
    treated "could not parse" as "empty" and replaced a user's whole config). Otherwise a
    ``.bak`` is kept and the write is atomic. Returns True if the file was written.
    """
    cfg_path = Path(cfg_path)
    cfg = {}
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            if not isinstance(cfg, dict):
                raise ValueError("top level is not an object")
        except (OSError, ValueError):
            print(f"  ! Left {cfg_path} untouched: it is not valid JSON, so it was not rewritten.")
            print(f"    Add an mcpServers entry named '{SERVER_KEY}' "
                  f"(command: {command}, args: [{script}]) by hand.")
            return False

    servers = cfg.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        print(f"  ! Left {cfg_path} untouched: 'mcpServers' is not an object.")
        return False
    entry = {"command": command, "args": [script]}
    if servers.get(SERVER_KEY) == entry:
        return False                                 # already exactly this: write nothing
    servers[SERVER_KEY] = entry

    try:
        if cfg_path.exists():
            shutil.copy2(cfg_path, str(cfg_path) + ".bak")
        tmp = str(cfg_path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        os.replace(tmp, cfg_path)
    except OSError as exc:
        print(f"  ! Could not update {cfg_path}: {exc}")
        return False
    return True


def desktop_targets(env=None):
    """Existing Desktop folders worth registering in: the default one plus adopted ones."""
    env = os.environ if env is None else env
    found = []
    appdata = env.get("APPDATA")
    if appdata:
        found.append(os.path.join(appdata, "Claude"))
    else:
        home = os.path.expanduser("~")
        found += [os.path.join(home, ".config", "Claude"),
                  os.path.join(home, "Library", "Application Support", "Claude")]
    try:
        found += [e["desktop_dir"] for e in registry.load().values() if e.get("desktop_dir")]
    except Exception:                         # a damaged registry must not block an install
        pass
    unique, seen = [], set()
    for folder in found:
        key = os.path.normcase(os.path.abspath(folder))
        if key not in seen and os.path.isdir(folder):
            seen.add(key)
            unique.append(folder)
    return unique


def apply(surfaces, mcp_script, python_command=None, dry_run=False, env=None):
    """Apply the chosen surfaces. Returns a list of human-readable result lines."""
    python_command = python_command or ("python" if os.name == "nt" else "python3")
    lines = []
    for surface in surfaces:
        if surface == "terminal":
            lines.append("terminal: ready (use `cc`; profiles via `cc profile detect` / `adopt`)")
        elif surface == "ide":
            lines.append("ide: run `cc ide check`, then `cc ide apply <profile> --yes` "
                         "(the extension takes one profile, so this is your choice)")
        elif surface == "desktop":
            targets = desktop_targets(env)
            if not targets:
                lines.append("desktop: no Desktop folder found; adopt yours with `cc profile detect`")
            for folder in targets:
                cfg = os.path.join(folder, "claude_desktop_config.json")
                if dry_run:
                    lines.append(f"desktop: [dry-run] would register Cortex MCP tools in {cfg}")
                elif register_desktop_mcp(cfg, python_command, mcp_script):
                    lines.append(f"desktop: registered Cortex MCP tools in {cfg}")
                else:
                    lines.append(f"desktop: {cfg} already up to date or left untouched")
    return lines


def mcp_script_path():
    """The installed MCP server script, falling back to the checkout."""
    for candidate in (os.path.expanduser("~/.claude/scripts/cortex-mcp.py"),
                      os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "scripts", "cortex-mcp.py")):
        if os.path.isfile(candidate):
            return candidate
    return os.path.expanduser("~/.claude/scripts/cortex-mcp.py")


def python_for_desktop():
    return "python" if os.name == "nt" else (shutil.which("python3") or sys.executable)
