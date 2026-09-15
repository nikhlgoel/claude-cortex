#!/usr/bin/env python3
"""
Claude Cortex - Model Context Protocol (MCP) Server
Exposes Cortex multi-account failover, dynamic model switching, fallback providers,
Cognitive Memory Palace, and neuroscience dream simulation directly to
Claude Desktop App, VS Code, and MCP-compatible environments.
"""

import sys
import os
import json
import subprocess
from pathlib import Path

# Paths
HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
SCRIPTS_DIR = CLAUDE_DIR / "scripts"
PROFILES_DIR = HOME / ".claude-profiles"
PROVIDERS_FILE = CLAUDE_DIR / "providers.json"

def get_status():
    """Returns comprehensive Cortex operational status."""
    lines = []
    lines.append("⚡ CLAUDE CORTEX OPERATIONAL STATUS")
    lines.append("=" * 50)

    # Profile
    curr_prof_file = PROFILES_DIR / "current_profile"
    cur_prof = curr_prof_file.read_text().strip() if curr_prof_file.exists() else "main"
    lines.append(f"• Active Profile: {cur_prof}")

    # Available profiles
    if PROFILES_DIR.exists():
        profs = [p.name for p in PROFILES_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")]
        lines.append(f"• Configured Profiles: {', '.join(profs)}")

    # Provider & Model
    prov_cfg = {}
    if PROVIDERS_FILE.exists():
        try:
            with open(PROVIDERS_FILE) as f:
                prov_cfg = json.load(f)
        except Exception:
            pass

    act_prov = prov_cfg.get("active_provider", "oauth")
    pinfo = prov_cfg.get("providers", {}).get(act_prov, {})
    act_model = pinfo.get("model", "claude-sonnet-5")
    lines.append(f"• Fallback Provider: {act_prov.upper()}")
    lines.append(f"• Active Model: {act_model}")

    # Memory Palace summary
    palace_dir = CLAUDE_DIR / "palace"
    if palace_dir.exists():
        rooms = ["blueprint.md", "procedures.md", "graveyard.md", "decisions.md", "working.md"]
        existing = [r.replace(".md", "") for r in rooms if (palace_dir / r).exists()]
        lines.append(f"• Memory Palace Rooms: {', '.join(existing) if existing else 'Initialized'}")

    return "\n".join(lines)

def switch_profile(target_profile):
    """Switches the active profile."""
    if not target_profile:
        # Toggle between 1 and 2 / ws and vl
        curr_prof_file = PROFILES_DIR / "current_profile"
        cur = curr_prof_file.read_text().strip() if curr_prof_file.exists() else "1"
        target_profile = "2" if cur in ["1", "ws"] else "1"

    script = SCRIPTS_DIR / "claude-capacity-check.py"
    if script.exists():
        res = subprocess.run([sys.executable, str(script), "switch", target_profile],
                             capture_output=True, text=True)
        return res.stdout.strip() or f"Switched to profile: {target_profile}"
    
    # Fallback manual switch
    target_dir = PROFILES_DIR / target_profile
    if not target_dir.exists():
        # Alias resolution
        if target_profile == "1" and (PROFILES_DIR / "ws").exists():
            target_profile = "ws"
        elif target_profile == "2" and (PROFILES_DIR / "vl").exists():
            target_profile = "vl"
    
    (PROFILES_DIR / "current_profile").write_text(target_profile)
    return f"✓ Active profile set to: {target_profile}"

def handle_model(action, model_id=None):
    """Interacts with claude-models.py."""
    script = SCRIPTS_DIR / "claude-models.py"
    if not script.exists():
        # Look in temp dir if running from repo
        alt = Path(__file__).resolve().parent / "claude-models.py"
        if alt.exists(): script = alt

    args = [sys.executable, str(script), action]
    if model_id:
        args.append(model_id)

    res = subprocess.run(args, capture_output=True, text=True)
    out = res.stdout.strip()
    # Strip ANSI escape codes for clean display in desktop app
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean_out = ansi_escape.sub('', out)
    return clean_out or f"Completed model {action}"

def handle_provider(action, provider=None):
    """Interacts with claude-provider.py."""
    script = SCRIPTS_DIR / "claude-provider.py"
    if not script.exists():
        alt = Path(__file__).resolve().parent / "claude-provider.py"
        if alt.exists(): script = alt

    args = [sys.executable, str(script), action]
    if provider:
        args.append(provider)

    res = subprocess.run(args, capture_output=True, text=True)
    return res.stdout.strip() or f"Completed provider {action}"

def handle_palace(action="status", query=None, room=None):
    """Interacts with claude-palace.py."""
    script = SCRIPTS_DIR / "claude-palace.py"
    if not script.exists():
        alt = Path(__file__).resolve().parent / "claude-palace.py"
        if alt.exists(): script = alt

    cmd_action = "status"
    args = [sys.executable, str(script)]

    if action in ["query", "recall", "search"]:
        cmd_action = "recall"
        args.append(cmd_action)
        if room:
            args.extend(["--room", room])
        args.append(query or "architecture")
    elif action in ["status", "rooms"]:
        cmd_action = "status"
        args.append(cmd_action)
    elif action == "view" and room:
        room_file = CLAUDE_DIR / "palace" / f"{room}.md"
        if room_file.exists():
            return room_file.read_text(encoding="utf-8")
        else:
            cmd_action = "status"
            args.append(cmd_action)
    else:
        args.append(cmd_action)

    res = subprocess.run(args, capture_output=True, text=True)
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    out = ansi_escape.sub('', res.stdout.strip())
    if not out and res.stderr:
        out = res.stderr.strip()
    return out or f"Memory Palace {action} completed"

def handle_dream(focus=None):
    """Interacts with claude-dream.py."""
    script = SCRIPTS_DIR / "claude-dream.py"
    if not script.exists():
        alt = Path(__file__).resolve().parent / "claude-dream.py"
        if alt.exists(): script = alt

    args = [sys.executable, str(script)]
    if focus:
        args.extend(["--topic", focus, "--quick"])
    else:
        args.append("--quick")

    res = subprocess.run(args, capture_output=True, text=True)
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    out = ansi_escape.sub('', res.stdout.strip())
    if not out and res.stderr:
        out = res.stderr.strip()
    return out or "Dream simulation completed"

# ==============================================================================
# MCP TOOL DEFINITIONS
# ==============================================================================
TOOLS = [
    {
        "name": "cortex_status",
        "description": "Returns operational status of Claude Cortex: active profile, account failover status, fallback provider, active LLM model, and Memory Palace state.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "cortex_switch",
        "description": "Switch active Claude account profile (toggle or switch between Profile 1 Work and Profile 2 Personal).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "Target profile name or number (e.g. '1', '2', 'ws', 'vl', 'main'). Leave blank to toggle."
                }
            }
        }
    },
    {
        "name": "cortex_model",
        "description": "Explore, inspect, or set the active LLM model. Access 100% free models (0 credit cost) or frontier paid models.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "free", "paid", "set", "info"],
                    "description": "Action to perform: 'free' (list free models), 'list' (all models), 'set' (activate model), 'info' (dossier specifications)"
                },
                "model_id": {
                    "type": "string",
                    "description": "Model ID to activate or inspect (e.g. 'deepseek/deepseek-r1:free', 'nvidia/nemotron-3-ultra-550b-a55b:free')"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "cortex_provider",
        "description": "Inspect or switch the active API provider fallback (oauth, openrouter, gemini, anthropic).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "list"],
                    "description": "Action: 'get' active provider, 'set' active provider, 'list' providers"
                },
                "provider": {
                    "type": "string",
                    "enum": ["oauth", "openrouter", "gemini", "anthropic"],
                    "description": "Target provider name"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "cortex_palace",
        "description": "Query or view the Cognitive Memory Palace for persistent project architecture invariants, learned conventions, ADR decisions, or bugfix graveyards.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "query", "view", "rooms"],
                    "description": "Action: 'query' (search concepts), 'status' (summary), 'rooms' (list rooms)"
                },
                "query": {
                    "type": "string",
                    "description": "Search term or concept to recall from Memory Palace"
                },
                "room": {
                    "type": "string",
                    "enum": ["blueprint", "procedures", "graveyard", "decisions", "working"],
                    "description": "Specific memory room"
                }
            }
        }
    },
    {
        "name": "cortex_dream",
        "description": "Trigger a neuroscience-inspired counterfactual simulation to stress-test architectural invariants and uncover latent failure modes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "Optional domain or code component to simulate stress tests for"
                }
            }
        }
    }
]

def dispatch_tool(name, args):
    """Executes the requested tool and returns text string."""
    try:
        if name == "cortex_status":
            return get_status()
        elif name == "cortex_switch":
            return switch_profile(args.get("profile"))
        elif name == "cortex_model":
            action = args.get("action", "list")
            mid = args.get("model_id")
            return handle_model(action, mid)
        elif name == "cortex_provider":
            action = args.get("action", "get")
            prov = args.get("provider")
            return handle_provider(action, prov)
        elif name == "cortex_palace":
            action = args.get("action", "status")
            query = args.get("query")
            room = args.get("room")
            return handle_palace(action, query, room)
        elif name == "cortex_dream":
            focus = args.get("focus")
            return handle_dream(focus)
        else:
            return f"Error: Unknown tool '{name}'"
    except Exception as e:
        return f"Tool execution failed: {str(e)}"

# ==============================================================================
# JSON-RPC MCP PROTOCOL ENGINE (STDIO)
# ==============================================================================
def send_response(resp):
    payload = json.dumps(resp)
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except Exception:
            continue

        req_id = req.get("id")
        method = req.get("method")

        # Handle notifications (no id)
        if req_id is None:
            continue

        if method == "initialize":
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "claude-cortex",
                        "version": "2.0.0"
                    }
                }
            })
        elif method == "ping":
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {}
            })
        elif method == "tools/list":
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": TOOLS
                }
            })
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            result_text = dispatch_tool(name, arguments)
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": result_text
                        }
                    ],
                    "isError": False
                }
            })
        else:
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found"
                }
            })

if __name__ == "__main__":
    main()
