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

from . import binary, jsonfile, proc, profiles
from .paths import apply_config_env, profile_dir

SERVER_NAME = "cortex"

# Third-party MCP servers Cortex knows how to register. They are registered through
# Claude Code's own `claude mcp add --scope user` - the supported write path - rather than
# by editing .claude.json, which Claude Code itself rewrites constantly. Cortex never
# installs them: if one is missing it says how, and you run that.
EXTERNAL = {
    "graphify": {
        "command": "graphify-mcp", "package": "graphifyy",
        "about": "code knowledge graph: callers, paths, architecture. Needs a graph built "
                 "per project first (graphify's /graphify command).",
    },
    "scrapling": {
        "command": "scrapling-mcp", "package": "scrapling",
        "about": "web fetching and scraping. Its browser-based fetchers need "
                 "`scrapling install`, which downloads browsers - run that yourself.",
    },
}

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


def _registered_servers(profile):
    """Names registered in the profile's user config (read-only)."""
    from .paths import is_native_default
    folder = profile_dir(profile)
    # The native default keeps its user config next to the folder, not inside it.
    config = os.path.join(os.path.dirname(folder), ".claude.json") if is_native_default(folder) \
        else os.path.join(folder, ".claude.json")
    servers = jsonfile.read(config, {}).get("mcpServers")
    return set(servers) if isinstance(servers, dict) else set()


def cmd_add_external(server, profile, dry_run=False):
    """Register a known third-party MCP server for a profile via `claude mcp add`."""
    spec = EXTERNAL[server]
    exe = shutil.which(spec["command"])
    if not exe:
        print(f"cc mcp: '{spec['command']}' is not installed.\n"
              f"    Install it yourself with:  uv tool install {spec['package']}", file=sys.stderr)
        return 1
    if server in _registered_servers(profile):
        print(f"'{server}' is already registered for profile '{profile}'.")
        return 0
    claude = binary.find()
    if not claude:
        print("cc mcp: no working Claude Code binary found (run: cc doctor).", file=sys.stderr)
        return 1

    command = [claude, "mcp", "add", "--scope", "user", server, "--", exe]
    if dry_run:
        print(f"[dry-run] would run: {' '.join(command)}")
        print(f"          with the config folder of profile '{profile}'")
        return 0
    env = apply_config_env(dict(os.environ), profile_dir(profile))
    try:
        result = proc.run(command, timeout=90, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"cc mcp: could not run claude: {exc}", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(f"cc mcp: registering '{server}' failed:\n{(result.stderr or result.stdout).strip()}",
              file=sys.stderr)
        return 1
    print(f"Registered '{server}' for profile '{profile}' ({spec['about']})")
    print("Start a new session under that profile to use it.")
    return 0


def cmd_remove_external(server, profile):
    claude = binary.find()
    if not claude:
        print("cc mcp: no working Claude Code binary found.", file=sys.stderr)
        return 1
    env = apply_config_env(dict(os.environ), profile_dir(profile))
    result = proc.run([claude, "mcp", "remove", "--scope", "user", server], timeout=60, env=env)
    print((result.stdout or result.stderr).strip() or f"Removed '{server}'.")
    return result.returncode


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

  cc mcp add graphify [profile]    code knowledge graph tools (graphify-mcp)
  cc mcp add scrapling [profile]   web fetching/scraping tools (scrapling-mcp)
      Registered through `claude mcp add --scope user`. Cortex never installs
      them; if missing it prints the `uv tool install` command for you to run.

Registration only tells Claude Code to launch a local process; it does not
change how you authenticate. Your subscription is unaffected.
"""


def main(args):
    if not args or args[0] in ("--help", "help"):
        print(USAGE)
        return 0

    action = args[0]
    rest = args[1:]

    # `cc mcp add graphify [profile]` - a known third-party server name first. A profile
    # that happens to share a server's name is ambiguous, so refuse rather than guess.
    server = None
    if action in ("add", "remove") and rest and rest[0] in EXTERNAL:
        if rest[0] in profiles.list_profiles():
            print(f"cc mcp: '{rest[0]}' is both a server and a profile name; rename the profile "
                  f"or pass the profile with --profile.", file=sys.stderr)
            return 2
        server, rest = rest[0], rest[1:]
    explicit = None
    if "--profile" in rest:
        i = rest.index("--profile")
        explicit = rest[i + 1] if i + 1 < len(rest) else None
        rest = rest[:i] + rest[i + 2:]
    positional = [a for a in rest if not a.startswith("-")]
    profile = profiles.normalize_name(explicit or (positional[0] if positional else "")) \
        or profiles.active_profile()

    if server and action == "add":
        return cmd_add_external(server, profile, dry_run="--dry-run" in rest)
    if server and action == "remove":
        return cmd_remove_external(server, profile)
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
