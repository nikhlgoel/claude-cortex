"""
MCP server management.

Registers the Cortex MCP server with Claude Code so its tools are callable
inside a session - under your real subscription, because registration only tells
Claude Code to launch a local process; it changes nothing about how Claude
authenticates.

Registration is written to the profile's config, so it follows the same
per-profile isolation as everything else: register once per profile you want the
tools in.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from . import jsonfile, profiles
from .paths import profile_dir

SERVER_NAME = "cortex"

# The tools scripts/cortex-mcp.py exposes. Kept in step with its TOOLS table by
# tests/test_core_fixes.py, so this list cannot silently go stale.
TOOL_NAMES = ("account_status", "recall_memory", "remember",
              "analyze_code_risks", "decompile_binary", "evaluate_impact")


def _server_path():
    """The MCP server script: installed copy first, then the checkout."""
    for candidate in (os.path.expanduser("~/.claude/scripts/cortex-mcp.py"),
                      os.path.join(os.path.dirname(os.path.dirname(
                          os.path.abspath(__file__))), "scripts", "cortex-mcp.py")):
        if os.path.isfile(candidate):
            return candidate
    return None


def _python():
    return shutil.which("python3") or shutil.which("python") or sys.executable


def cmd_status(profile):
    """Show whether the server is registered for a profile."""
    config = os.path.join(profile_dir(profile), ".claude.json")
    data = jsonfile.read(config, {})
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}

    print("=" * 70)
    print(f"  Cortex MCP - profile '{profile}'")
    print("=" * 70)
    server_path = _server_path()
    print(f"  server script : {server_path or 'NOT FOUND'}")
    print(f"  registered    : {'yes' if SERVER_NAME in servers else 'no'}")
    if servers:
        print(f"  all MCP servers here: {', '.join(sorted(servers))}")
    print()
    print("  Tools exposed: " + ", ".join(TOOL_NAMES))
    print()
    if SERVER_NAME not in servers:
        print(f"  Register with:  cc mcp add [{profile}]")
    print("=" * 70)
    return 0


def cmd_add(profile, dry_run=False):
    """Register the server in a profile's config."""
    server_path = _server_path()
    if not server_path:
        print("cc mcp: cortex-mcp.py not found. Reinstall Cortex.", file=sys.stderr)
        return 1

    config = os.path.join(profile_dir(profile), ".claude.json")
    entry = {
        "type": "stdio",
        "command": _python(),
        "args": [server_path],
        "env": {},
    }

    with jsonfile.file_lock(config):
        data = jsonfile.read(config, {})
        servers = data.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}

        if servers.get(SERVER_NAME) == entry:
            print(f"Already registered for profile '{profile}'.")
            return 0

        if dry_run:
            print(f"[dry-run] would register '{SERVER_NAME}' for profile '{profile}':")
            print(f"    command: {entry['command']} {server_path}")
            return 0

        servers[SERVER_NAME] = entry
        data["mcpServers"] = servers
        jsonfile.write(config, data)

    print(f"Registered '{SERVER_NAME}' MCP server for profile '{profile}'.")
    print("Start a new session under that profile and the tools are available:")
    print("  " + ", ".join(TOOL_NAMES))
    return 0


def cmd_remove(profile):
    config = os.path.join(profile_dir(profile), ".claude.json")
    with jsonfile.file_lock(config):
        data = jsonfile.read(config, {})
        servers = data.get("mcpServers")
        if not isinstance(servers, dict) or SERVER_NAME not in servers:
            print(f"Not registered for profile '{profile}'.")
            return 0
        del servers[SERVER_NAME]
        if servers:
            data["mcpServers"] = servers
        else:
            data.pop("mcpServers", None)
        jsonfile.write(config, data)
    print(f"Removed '{SERVER_NAME}' MCP server from profile '{profile}'.")
    return 0


def cmd_test(_profile):
    """Verify the server speaks the protocol, without a live Claude session."""
    server_path = _server_path()
    if not server_path:
        print("cc mcp: cortex-mcp.py not found.", file=sys.stderr)
        return 1

    import json
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    stdin = "\n".join(json.dumps(r) for r in requests) + "\n"

    try:
        result = subprocess.run([_python(), server_path], input=stdin,
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"cc mcp: server did not run: {exc}", file=sys.stderr)
        return 1

    tools = None
    corrupt = 0
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            corrupt += 1
            continue
        if message.get("id") == 2:
            tools = [t["name"] for t in message["result"]["tools"]]

    print("=" * 70)
    print("  Cortex MCP - protocol self-test")
    print("=" * 70)
    print(f"  server exits cleanly : {'yes' if result.returncode == 0 else 'no'}")
    print(f"  stdout is clean JSON : {'yes' if corrupt == 0 else f'NO ({corrupt} bad lines)'}")
    print(f"  tools advertised     : {', '.join(tools) if tools else 'NONE - FAILED'}")
    print("=" * 70)
    # A corrupt stdout is the failure that silently breaks a real session, so it
    # is the one that fails the self-test.
    return 0 if (tools and corrupt == 0) else 1


USAGE = """\
cc mcp - manage the Cortex MCP server

  cc mcp status [profile]     is it registered for a profile
  cc mcp add [profile]        register it (per profile)
  cc mcp remove [profile]     unregister it
  cc mcp test                 protocol self-test, no session needed

Registration only tells Claude Code to launch a local process; it does not
change how you authenticate. Your subscription is unaffected.
"""


def main(args):
    if not args or args[0] in ("--help", "help"):
        print(USAGE)
        return 0

    action = args[0]
    rest = args[1:]
    profile = profiles.normalize_name(rest[0]) if rest and not rest[0].startswith("-") \
        else profiles.active_profile()

    if action == "status":
        return cmd_status(profile)
    if action == "add":
        return cmd_add(profile, dry_run="--dry-run" in rest)
    if action == "remove":
        return cmd_remove(profile)
    if action == "test":
        return cmd_test(profile)

    print(f"cc mcp: unknown action '{action}'", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2
