#!/usr/bin/env python3
"""
Claude Cortex - MCP server.

This is the supported way to give Claude new abilities: MCP is Anthropic's own
plugin protocol, so a tool exposed here can be called by Claude mid-conversation,
under your real subscription, and it survives every Claude Code update. Nothing
about Claude's own binary is touched.

It exposes only capabilities that are actually real. The earlier version of this
file advertised a "dream simulation" that printed a fixed template and a model
catalog that was a static snapshot; those are gone. What remains does something:

    decompile_binary     - run the isolated Ghidra pipeline on an executable and
                           return its capability report. The payoff of the binary
                           work: Claude reasons over the result instead of you
                           reading a file.
    analyze_code_risks   - the real static analyser (cortex/dream), which reports
                           findings with a file, a line, and the failure mechanism
    recall / remember    - the memory palace, which genuinely stores and retrieves
    account_status       - real per-profile capacity, unknown reported as unknown

Protocol notes
--------------
STDOUT CARRIES ONLY JSON-RPC. One message per line, nothing else - a single stray
print to stdout corrupts the stream and the client drops the server. All
diagnostics go to stderr. This is the most common way to break an MCP server, so
the code routes every human-readable message through log().
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "claude-cortex"
SERVER_VERSION = "2.1.0"

HOME = Path.home()
REPO = Path(__file__).resolve().parent.parent


def log(message):
    """Human-readable output - stderr only, never stdout."""
    sys.stderr.write(f"[cortex-mcp] {message}\n")
    sys.stderr.flush()


def send(message):
    """Write one JSON-RPC message. The only thing allowed on stdout."""
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def cortex_module_dir():
    """Where the cortex package lives, for tools that call into it."""
    for candidate in (HOME / ".claude" / "cortex-core", REPO):
        if (candidate / "cortex").is_dir():
            return str(candidate)
    return str(REPO)


def scripts_dir():
    for candidate in (HOME / ".claude" / "scripts", REPO / "scripts"):
        if candidate.is_dir():
            return candidate
    return REPO / "scripts"


def run_child(args, timeout, env=None):
    """Run a child process with a real time bound and UTF-8 decoding.

    Two Windows problems this avoids, both reproduced: (1) subprocess's timeout
    does not bound a captured call when a grandchild holds the pipe (docker, git,
    node shims), so a hung tool could hold the MCP server far past its timeout;
    (2) ``text=True`` decodes with the console code page, so the palace's emoji
    output raised UnicodeDecodeError and the remember/recall tools failed. The
    child is also told to emit UTF-8 (PYTHONUTF8). Raises TimeoutExpired/OSError.
    """
    base = cortex_module_dir()
    if base not in sys.path:
        sys.path.insert(0, base)
    from cortex import proc
    child_env = dict(os.environ, PYTHONUTF8="1")
    child_env.update(env or {})
    return proc.run(args, timeout=timeout, env=child_env)


def child_failed(exc, what):
    """One consistent message for a child that timed out or could not start."""
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"{what} did not finish within {int(exc.timeout)}s and was stopped."
    return f"{what} could not run: {exc}"


# ---------------------------------------------------------------------------
# Tools. Each returns a plain string; the protocol wrapping happens in
# handle_call, so a tool never has to know about JSON-RPC.
# ---------------------------------------------------------------------------

def tool_account_status(_args):
    """Real capacity via the core, not a fabricated number."""
    core = cortex_module_dir()
    try:
        result = run_child(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, sys.argv[1]); "
             "from cortex import capacity; print(capacity.render())",
             core],
            timeout=120, env={"PYTHONPATH": core})
    except (OSError, subprocess.SubprocessError) as exc:
        return child_failed(exc, "Capacity check")
    return result.stdout or result.stderr or "no output"


def tool_recall(args):
    query = (args.get("query") or "").strip()
    if not query:
        return "Provide a 'query' to search the memory palace."
    script = scripts_dir() / "claude-palace.py"
    if not script.is_file():
        return "Memory palace is not installed."
    try:
        result = run_child([sys.executable, str(script), "recall", query], timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return child_failed(exc, "Memory recall")
    return result.stdout or result.stderr or f"No memories matching '{query}'."


def tool_remember(args):
    room = (args.get("room") or "working").strip()
    title = (args.get("title") or "").strip()
    content = (args.get("content") or "").strip()
    if not title or not content:
        return "Provide 'title' and 'content' to store a memory."
    script = scripts_dir() / "claude-palace.py"
    if not script.is_file():
        return "Memory palace is not installed."
    try:
        result = run_child([sys.executable, str(script), "remember", "--room", room,
                            "--title", title, "--content", content], timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return child_failed(exc, "Memory store")
    if result.returncode != 0:
        # Do not tell the model "stored" when the palace refused or crashed.
        return "NOT stored: " + (result.stderr or result.stdout or "the palace reported an error").strip()
    return result.stdout or "stored"


def tool_analyze_code_risks(args):
    """The real static analyser - findings with file, line and mechanism."""
    path = (args.get("path") or "").strip()
    if not path:
        return "Provide a 'path' (a file or directory) to analyse."
    if not os.path.exists(path):
        return f"Path not found: {path}"
    script = scripts_dir() / "claude-analyze.py"
    if not script.is_file():
        return "The analyser is not installed."
    try:
        result = run_child([sys.executable, str(script), "--path", path], timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        return child_failed(exc, "Code analysis")
    return result.stdout or result.stderr or "no findings"


def tool_decompile_binary(args):
    """The payoff: isolated Ghidra analysis, capability report back to Claude."""
    binary = (args.get("path") or "").strip()
    if not binary:
        return ("Provide a 'path' to an executable. It is analysed with no "
                "network access and never run.")
    if not os.path.isfile(binary):
        return f"Not a file: {binary}"

    core = cortex_module_dir()
    # Delegate to the same code path `cc ghidra analyze` uses, so there is one
    # implementation and the isolation guarantees are identical.
    try:
        result = run_child(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, sys.argv[1]); "
             "from cortex import ghidra; sys.exit(ghidra.main(['analyze', sys.argv[2]]))",
             core, os.path.abspath(binary)],
            timeout=1200, env={"PYTHONPATH": core})
    except (OSError, subprocess.SubprocessError) as exc:
        return child_failed(exc, "Binary analysis")

    output = result.stdout or ""
    combined = ((result.stdout or "") + (result.stderr or "")).lower()
    if result.returncode != 0 and "docker" in combined:
        # Say what is actually wrong. "Build the image" was returned for every
        # docker-related failure, including a stopped daemon, which sent the model
        # off to run a 15-minute build that could not help.
        if "cannot connect to the docker daemon" in combined or "daemon" in combined and "running" in combined:
            return ("Docker is installed but its daemon is not reachable. Start Docker "
                    "Desktop and retry.\n\n" + (result.stderr or "")[-300:])
        if "unable to find image" in combined or "no such image" in combined:
            return ("Ghidra analysis needs the isolated image. Build it once with "
                    "'cc ghidra build' (about 15 minutes), then retry.\n\n"
                    + (result.stderr or "")[-400:])
        return "Ghidra analysis failed:\n" + ((result.stderr or result.stdout or "")[-600:])
    # Return the capability report, which is the part worth reasoning over.
    marker = "capability report"
    index = output.find(marker)
    if index > 0:
        start = output.rfind("=", 0, index)
        return output[start if start > 0 else index:].strip()
    return output or result.stderr or "analysis produced no output"


def tool_evaluate_impact(args):
    """Heuristic risk score for a change to one file (see cortex-scorer.py)."""
    path = (args.get("path") or "").strip()
    if not path:
        return "Provide a 'path' to evaluate."
    root = (args.get("root") or "").strip() or os.getcwd()
    script = scripts_dir() / "cortex-scorer.py"
    if not script.is_file():
        return "The scorer is not installed. Reinstall Cortex."
    try:
        result = run_child([sys.executable, str(script), "--path", path, "--root", root],
                           timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return child_failed(exc, "The scorer")

    try:
        data = json.loads(result.stdout)
    except ValueError:
        return result.stderr.strip() or result.stdout.strip() or "scorer produced no output"
    if "error" in data:
        return f"Cannot score: {data['error']}"

    headline = f"OAS {data['score']}/100 -> {data['recommendation']}"
    if data["unmeasured"]:
        headline += f" (unmeasured: {', '.join(sorted(data['unmeasured']))})"
    return headline + "\n" + json.dumps(data, indent=2)


TOOLS = {
    "account_status": {
        "description": "Show Claude account capacity per profile. Unknown "
                       "capacity is reported as unknown, never guessed.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_account_status,
    },
    "recall_memory": {
        "description": "Search the project memory palace for past lessons, "
                       "decisions, and solved bugs.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string",
                                     "description": "what to search for"}},
            "required": ["query"],
        },
        "handler": tool_recall,
    },
    "remember": {
        "description": "Store a lesson, decision, or fix in the memory palace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "room": {"type": "string",
                         "description": "blueprint|procedures|graveyard|decisions|working"},
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["title", "content"],
        },
        "handler": tool_remember,
    },
    "analyze_code_risks": {
        "description": "Static risk analysis of source code. Reports findings "
                       "with a file, a line, and the mechanism by which each one "
                       "fails - swallowed errors, non-atomic writes, missing "
                       "timeouts, shell injection.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string",
                                    "description": "a file or directory"}},
            "required": ["path"],
        },
        "handler": tool_analyze_code_risks,
    },
    "decompile_binary": {
        "description": "Analyse a compiled executable with Ghidra in a "
                       "network-isolated container and return a capability "
                       "report: what the binary can do (from its imports), "
                       "notable strings, and the functions worth reading. The "
                       "binary is never executed. Slow (tens of seconds).",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string",
                                    "description": "path to the executable"}},
            "required": ["path"],
        },
        "handler": tool_decompile_binary,
    },
    "evaluate_impact": {
        "description": "Heuristic risk score (0-100, higher is safer) for a change "
                       "to one file: complexity change vs. git HEAD, whether tests "
                       "reference it, whether a committed copy exists to restore, "
                       "destructive patterns, and how many files depend on it. "
                       "Metrics it cannot measure are listed, never guessed. A "
                       "score below 50 means stop and ask the user. It is a risk "
                       "indicator, not a proof of correctness.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "the file that was or "
                                                          "will be changed"},
                "root": {"type": "string", "description": "project root "
                                                          "(default: working dir)"},
            },
            "required": ["path"],
        },
        "handler": tool_evaluate_impact,
    },
}


# ---------------------------------------------------------------------------
# JSON-RPC dispatch
# ---------------------------------------------------------------------------

def handle_initialize(request):
    return {
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        },
    }


def handle_tools_list(request):
    tools = [{
        "name": name,
        "description": spec["description"],
        "inputSchema": spec["inputSchema"],
    } for name, spec in TOOLS.items()]
    return {"jsonrpc": "2.0", "id": request["id"], "result": {"tools": tools}}


def handle_tools_call(request):
    params = request.get("params") or {}
    name = params.get("name")
    args = params.get("arguments") or {}

    spec = TOOLS.get(name)
    if not spec:
        return {
            "jsonrpc": "2.0", "id": request["id"],
            "error": {"code": -32602, "message": f"Unknown tool: {name}"},
        }

    try:
        text = spec["handler"](args)
    except subprocess.TimeoutExpired:
        text = f"'{name}' timed out. For decompile_binary this can mean the " \
               f"image is still building; try again shortly."
    except Exception as exc:  # a tool failure must not kill the server
        log(f"tool {name} raised: {exc}")
        text = f"'{name}' failed: {exc}"

    return {
        "jsonrpc": "2.0", "id": request["id"],
        "result": {"content": [{"type": "text", "text": text}]},
    }


HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}


def main():
    log(f"starting ({len(TOOLS)} tools: {', '.join(TOOLS)})")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            log(f"dropping unparseable line: {line[:80]}")
            continue

        method = request.get("method")

        # A notification has no id and expects no response.
        if "id" not in request:
            if method == "notifications/initialized":
                log("client initialized")
            continue

        handler = HANDLERS.get(method)
        if handler:
            send(handler(request))
        else:
            send({
                "jsonrpc": "2.0", "id": request["id"],
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })

    log("stdin closed, exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
