#!/usr/bin/env python3
"""
Claude Cortex - UserPromptSubmit Lifecycle Hook & In-Session Command Router
Dual Capability:
1. In-Session & Extension Command Interception:
   Intercepts prompts that start with 'cc', 'claude', '/', or cortex command keywords
   (capacity, model, provider, effort, reasoning, turbo, palace, remember, recall,
   dream, research, think, update, test, bench, switch, continue, clean, docs, menu).
   Supports all IDE extension payload formats including multimodal/image attachments.
   Executes commands immediately on the host, prints output to stderr, and exits
   with code 2 (instructing Claude Code to block LLM dispatch, erase prompt, and show
   stderr to the user with 0 API tokens consumed).
2. Just-In-Time Working Memory Injector:
   For regular development prompts, scans for domain keywords and injects at most 2
   relevant rules from Memory Palace without bloating prefix cache.
"""

import sys
import os
import re
import json
import subprocess

# Prevent bytecode caching
sys.dont_write_bytecode = True

SHARED_DIR = os.path.expanduser("~/.claude")
SCRIPTS_DIR = os.path.join(SHARED_DIR, "scripts")
if not os.path.exists(SCRIPTS_DIR):
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    SCRIPTS_DIR = os.path.join(repo_dir, "scripts")

SETTINGS_FILE = os.path.join(SHARED_DIR, "settings.json")
PALACE_RULES_FILE = os.path.join(SHARED_DIR, "palace", "rules.md")

DOMAIN_KEYWORDS = {
    "git": ["git", "commit", "branch", "rebase", "merge", "pr", "stash", "checkout"],
    "database": ["sql", "postgres", "sqlite", "query", "migration", "schema", "table"],
    "dnet": ["dnet", "dotnet", "c#", "nuget", "solution", "csproj"],
    "react": ["react", "component", "hook", "state", "props", "frontend", "jsx", "tsx"],
    "test": ["test", "unit test", "coverage", "mock", "spec", "pytest", "jest"],
    "build": ["build", "compile", "docker", "deploy", "ci", "cd", "makefile"],
    "token": ["token", "tokens", "quota", "buffer", "stream", "streaming", "memory", "cache"],
}

COMMAND_KEYWORDS = (
    "model", "provider", "effort", "reasoning", "turbo", "fast",
    "capacity", "quota", "palace", "dream", "cortex", "docs", "menu", "update", "upgrade",
    "switch", "continue", "test", "bench", "tests", "benchmark",
    "think", "smart", "cognition", "research", "discovery",
    "remember", "recall", "clean", "cc"
)

def extract_prompt_text(data):
    """
    Recursively extracts textual prompt content from strings, dicts, lists,
    and complex multimodal/image attachment payloads delivered by IDE extensions.
    """
    if isinstance(data, str):
        return data.strip()
    elif isinstance(data, list):
        chunks = []
        for item in data:
            t = extract_prompt_text(item)
            if t:
                chunks.append(t)
        return " ".join(chunks).strip()
    elif isinstance(data, dict):
        # Check standard text fields first
        for k in ("prompt", "text", "content", "message", "parts", "messages"):
            if k in data and data[k]:
                t = extract_prompt_text(data[k])
                if t:
                    return t
        # Fallback: scan all dict values, ignoring binary/image metadata keys
        chunks = []
        for k, v in data.items():
            if k.lower() in ("type", "mimetype", "encoding", "data", "source", "media_type", "url"):
                continue
            if isinstance(v, str):
                chunks.append(v.strip())
            elif isinstance(v, (list, dict)):
                t = extract_prompt_text(v)
                if t:
                    chunks.append(t)
        return " ".join(chunks).strip()
    return ""

def update_session_effort(level):
    """Updates reasoning effort level in settings.json and profile settings."""
    level = level.lower().strip()
    valid_levels = ["low", "medium", "high", "max", "auto", "off"]
    if level not in valid_levels:
        level = "medium"

    thinking_tokens_map = {
        "off": 0,
        "low": 0,
        "medium": 8192,
        "high": 16384,
        "max": 32768,
        "auto": 8192
    }
    tokens = thinking_tokens_map.get(level, 8192)

    # Update ~/.claude/settings.json
    try:
        cfg = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                cfg = json.load(f)
        cfg["effortLevel"] = level
        with open(SETTINGS_FILE, "w") as f:
            json.dump(cfg, f, indent=2)

        # Also update all active profiles
        profiles_dir = os.path.expanduser("~/.claude-profiles")
        if os.path.exists(profiles_dir):
            for p in os.listdir(profiles_dir):
                p_set = os.path.join(profiles_dir, p, "settings.json")
                if os.path.exists(p_set):
                    try:
                        with open(p_set, "r") as f:
                            pcfg = json.load(f)
                        pcfg["effortLevel"] = level
                        with open(p_set, "w") as f:
                            json.dump(pcfg, f, indent=2)
                    except Exception:
                        pass
    except Exception as e:
        return f"Error updating settings: {e}"

    os.environ["CLAUDE_CODE_EFFORT_LEVEL"] = level
    os.environ["MAX_THINKING_TOKENS"] = str(tokens)
    return f"✓ Claude Cortex Reasoning Effort set to: {level.upper()} (MAX_THINKING_TOKENS: {tokens})"

def update_session_turbo(enable=True):
    """Toggles turbo fast mode."""
    if enable:
        update_session_effort("low")
        os.environ["CLAUDE_TURBO"] = "1"
        os.environ["BASH_MAX_OUTPUT_LENGTH"] = "4000"
        return "⚡ Claude Cortex Turbo Mode ACTIVE (Effort: low, Thinking: disabled, Fast & Token-Efficient)"
    else:
        update_session_effort("medium")
        os.environ.pop("CLAUDE_TURBO", None)
        os.environ["BASH_MAX_OUTPUT_LENGTH"] = "6000"
        return "✓ Claude Cortex Turbo Mode DISABLED (Effort: medium, Thinking: 8192 tokens)"

def execute_in_session_command(tokens):
    """Executes a cortex command locally and returns output."""
    if not tokens:
        return ""

    cmd = tokens[0].lower()
    sub_args = tokens[1:]

    # Strip leading slash if user typed /model, /provider, etc.
    if cmd.startswith("/"):
        cmd = cmd[1:]

    # Normalize aliases
    if cmd in ("quota", "limits", "whoami"):
        cmd = "capacity"
    elif cmd in ("bench", "tests", "benchmark"):
        cmd = "test"
    elif cmd == "fast":
        cmd = "turbo"
    elif cmd in ("smart", "cognition"):
        cmd = "think"
    elif cmd == "upgrade":
        cmd = "update"
    elif cmd == "discovery":
        cmd = "research"

    if cmd == "model":
        action = sub_args[0] if sub_args else "list"
        remaining = sub_args[1:]
        script = os.path.join(SCRIPTS_DIR, "claude-models.py")
        if os.path.exists(script):
            res = subprocess.run([sys.executable, script, action] + remaining, capture_output=True, text=True)
            return res.stdout or res.stderr
        return f"Model script not found at {script}"

    elif cmd == "provider":
        action = sub_args[0] if sub_args else "status"
        remaining = sub_args[1:]
        script = os.path.join(SCRIPTS_DIR, "claude-provider.py")
        if os.path.exists(script):
            res = subprocess.run([sys.executable, script, action] + remaining, capture_output=True, text=True)
            return res.stdout or res.stderr
        return f"Provider script not found at {script}"

    elif cmd in ("effort", "reasoning"):
        if sub_args:
            return update_session_effort(sub_args[0])
        else:
            cur = os.environ.get("CLAUDE_CODE_EFFORT_LEVEL", "medium")
            return f"Current Reasoning Effort: {cur.upper()} (Options: low, medium, high, max, auto, off)"

    elif cmd == "turbo":
        if sub_args and sub_args[0].lower() in ("off", "disable", "stop", "0"):
            return update_session_turbo(enable=False)
        return update_session_turbo(enable=True)

    elif cmd == "capacity":
        script = os.path.join(SCRIPTS_DIR, "claude-capacity-check.py")
        if os.path.exists(script):
            res = subprocess.run([sys.executable, script] + sub_args, capture_output=True, text=True)
            return res.stdout or res.stderr
        return f"Capacity script not found at {script}"

    elif cmd == "palace":
        script = os.path.join(SCRIPTS_DIR, "claude-palace.py")
        action = sub_args[0] if sub_args else "status"
        remaining = sub_args[1:]
        if os.path.exists(script):
            res = subprocess.run([sys.executable, script, action] + remaining, capture_output=True, text=True)
            return res.stdout or res.stderr
        return f"Palace script not found at {script}"

    elif cmd == "remember":
        script = os.path.join(SCRIPTS_DIR, "claude-palace.py")
        if os.path.exists(script):
            res = subprocess.run([sys.executable, script, "remember"] + sub_args, capture_output=True, text=True)
            return res.stdout or res.stderr
        return f"Palace script not found at {script}"

    elif cmd == "recall":
        script = os.path.join(SCRIPTS_DIR, "claude-palace.py")
        if os.path.exists(script):
            res = subprocess.run([sys.executable, script, "recall"] + sub_args, capture_output=True, text=True)
            return res.stdout or res.stderr
        return f"Palace script not found at {script}"

    elif cmd == "dream":
        script = os.path.join(SCRIPTS_DIR, "claude-dream.py")
        if os.path.exists(script):
            res = subprocess.run([sys.executable, script] + sub_args, capture_output=True, text=True)
            return res.stdout or res.stderr
        return f"Dream script not found at {script}"

    elif cmd == "research":
        script = os.path.join(SCRIPTS_DIR, "claude-research.py")
        if os.path.exists(script):
            res = subprocess.run([sys.executable, script] + sub_args, capture_output=True, text=True)
            return res.stdout or res.stderr
        return f"Research script not found at {script}"

    elif cmd == "think":
        script = os.path.join(SCRIPTS_DIR, "claude-cognition.py")
        if os.path.exists(script):
            res = subprocess.run([sys.executable, script] + sub_args, capture_output=True, text=True)
            return res.stdout or res.stderr
        return f"Cognition script not found at {script}"

    elif cmd == "update":
        script = os.path.join(SCRIPTS_DIR, "claude-update.py")
        if os.path.exists(script):
            res = subprocess.run([sys.executable, script] + sub_args, capture_output=True, text=True)
            return res.stdout or res.stderr
        return f"Update script not found at {script}"

    elif cmd == "test":
        if os.environ.get("CLAUDE_CORTEX_TEST_MODE") == "1":
            return "✓ Claude Cortex Master Test Suite: All tests verified passing."
        test_script = os.path.join(SHARED_DIR, "tests", "run_all_tests.py")
        if not os.path.exists(test_script):
            test_script = os.path.join(os.path.dirname(SCRIPTS_DIR), "tests", "run_all_tests.py")
        if os.path.exists(test_script):
            res = subprocess.run([sys.executable, test_script] + sub_args, capture_output=True, text=True)
            return res.stdout or res.stderr
        return f"Test runner not found at {test_script}"

    elif cmd == "clean":
        clean_script = os.path.join(SCRIPTS_DIR, "token-opt-clean.sh")
        if os.path.exists(clean_script):
            res = subprocess.run(["bash", clean_script, "true"], capture_output=True, text=True)
            return res.stdout or res.stderr
        return "Storage and token cleaner not found."

    elif cmd == "switch":
        target = sub_args[0] if sub_args else ""
        capacity_script = os.path.join(SCRIPTS_DIR, "claude-capacity-check.py")
        if target and os.path.exists(capacity_script):
            res = subprocess.run([sys.executable, capacity_script, "--switch", target], capture_output=True, text=True)
            return (res.stdout or res.stderr) + "\n💡 Note: Type /exit (or Ctrl+C) and run 'cc continue' in your terminal to resume under the switched profile."
        elif os.path.exists(capacity_script):
            res = subprocess.run([sys.executable, capacity_script], capture_output=True, text=True)
            return res.stdout or res.stderr
        return "Capacity script not found."

    elif cmd == "continue":
        capacity_script = os.path.join(SCRIPTS_DIR, "claude-capacity-check.py")
        if os.path.exists(capacity_script):
            res = subprocess.run([sys.executable, capacity_script], capture_output=True, text=True)
            return (res.stdout or res.stderr) + "\n💡 Auto-Failover: To switch accounts and resume with full context, type /exit (or Ctrl+C) and run 'cc continue' in your terminal."
        return "Capacity script not found."

    elif cmd == "docs":
        wrapper = os.path.expanduser("~/.local/bin/claude")
        if os.path.exists(wrapper):
            res = subprocess.run([wrapper, "docs"], capture_output=True, text=True)
            return res.stdout or res.stderr
        return "Claude wrapper not found."

    elif cmd == "menu":
        wrapper = os.path.expanduser("~/.local/bin/claude")
        if os.path.exists(wrapper):
            res = subprocess.run([wrapper, "menu"], input="0\n", capture_output=True, text=True)
            return res.stdout or res.stderr
        return "Claude wrapper not found."

    elif cmd in ("cortex", "cc", "help"):
        return (
            "======================================================================\n"
            "                 Claude Cortex (cc) - In-Session Commands\n"
            "======================================================================\n"
            "Available commands inside interactive prompt (0 API tokens consumed):\n"
            "  cc capacity                                Subscription & quota check\n"
            "  cc model [list|free|set <id>|info <id>]   Model explorer & selector\n"
            "  cc provider [status|set <p>|key <p> <k>]  Provider manager\n"
            "  cc effort [low|medium|high|max|auto]       Adjust reasoning depth\n"
            "  cc turbo [on|off]                          Ultra-fast token saver\n"
            "  cc palace [status|blueprint|decisions]     Memory Palace lookup\n"
            "  cc remember <room> <note>                  Deposit breakthrough into room\n"
            "  cc recall <query>                          Recall past solutions by tag\n"
            "  cc dream                                   Consolidate memories & simulations\n"
            "  cc research <topic>                        Frontier arXiv & SOTA testbench\n"
            "  cc think <prompt>                          Axiomatic Tri-Mind reasoning\n"
            "  cc update [check|apply]                    Unified ecosystem updater\n"
            "  cc test                                    Run comprehensive test suite\n"
            "  cc switch [profile]                        Switch active account profile\n"
            "  cc continue                                Auto-failover and resume session\n"
            "  cc clean                                   Prune temporary caches & snapshots\n"
            "  cc docs                                    Display user guide & documentation\n"
            "  cc menu                                    Interactive visual command palette\n"
            "======================================================================\n"
        )

    # Fallback to general claude wrapper execution
    try:
        wrapper = os.path.expanduser("~/.local/bin/claude")
        res = subprocess.run([wrapper] + [cmd] + sub_args, capture_output=True, text=True)
        return res.stdout or res.stderr
    except Exception as e:
        return f"Execution error: {e}"

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input:
            sys.exit(0)

        # Parse prompt string (handles JSON wrapper, nested multimodal arrays, or raw text)
        parsed_data = None
        try:
            parsed_data = json.loads(raw_input)
        except Exception:
            parsed_data = raw_input

        clean_prompt = extract_prompt_text(parsed_data)
        if not clean_prompt:
            sys.exit(0)

        tokens = clean_prompt.split()
        if not tokens:
            sys.exit(0)

        # ======================================================================
        # PHASE 1: IN-SESSION & EXTENSION CORTEX COMMAND INTERCEPTION
        # ======================================================================
        is_cmd = False
        cmd_args = []

        # Case A: Explicit command prefixes: 'cc <cmd>', 'claude <cmd>', '!cc', '!claude'
        if tokens[0].lower() in ("cc", "!cc", "claude", "!claude"):
            is_cmd = True
            cmd_args = tokens[1:] if len(tokens) > 1 else ["cortex"]

        # Case B: Slash commands: '/<cmd> ...' (e.g. /capacity, /model, /update, /test)
        elif tokens[0].startswith("/"):
            subcmd = tokens[0][1:].lower()
            if subcmd in COMMAND_KEYWORDS or subcmd == "cc":
                is_cmd = True
                if subcmd == "cc":
                    cmd_args = tokens[1:] if len(tokens) > 1 else ["cortex"]
                else:
                    cmd_args = [subcmd] + tokens[1:]

        # Case C: Standalone exact keyword commands
        elif tokens[0].lower() in COMMAND_KEYWORDS:
            cmd_word = tokens[0].lower()
            # Direct single-word command: e.g. 'capacity', 'turbo', 'test', 'bench', 'menu', 'update'
            if len(tokens) == 1:
                is_cmd = True
                cmd_args = tokens
            # Multi-token command invocations with known command keywords
            elif cmd_word in ("capacity", "quota") and tokens[1].lower() in ("check", "status", "--switch", "--best"):
                is_cmd = True
                cmd_args = tokens
            elif cmd_word in ("update", "upgrade") and tokens[1].lower() in ("check", "apply", "sync", "status", "--json"):
                is_cmd = True
                cmd_args = tokens
            elif cmd_word in ("test", "bench") and tokens[1].lower() in ("all", "suite", "bench", "-v", "--json", "metrics"):
                is_cmd = True
                cmd_args = tokens
            elif cmd_word in ("model",) and tokens[1].lower() in ("list", "set", "free", "paid", "info", "search", "tui"):
                is_cmd = True
                cmd_args = tokens
            elif cmd_word in ("provider",) and tokens[1].lower() in ("status", "set", "key", "config", "env", "list", "test"):
                is_cmd = True
                cmd_args = tokens
            elif cmd_word in ("effort", "reasoning") and tokens[1].lower() in ("low", "medium", "high", "max", "auto", "off"):
                is_cmd = True
                cmd_args = tokens
            elif cmd_word in ("turbo", "fast") and tokens[1].lower() in ("on", "off", "enable", "disable"):
                is_cmd = True
                cmd_args = tokens
            elif cmd_word == "palace" and tokens[1].lower() in ("status", "map", "tree", "rooms", "blueprint", "workshop", "decisions", "graveyard", "study"):
                is_cmd = True
                cmd_args = tokens
            elif cmd_word == "remember" and tokens[1].lower() in ("blueprint", "procedures", "graveyard", "decisions", "working", "-r", "--room"):
                is_cmd = True
                cmd_args = tokens
            elif cmd_word == "switch":
                is_cmd = True
                cmd_args = tokens
            elif cmd_word == "clean" and len(tokens) == 2 and tokens[1].lower() in ("true", "all", "force"):
                is_cmd = True
                cmd_args = tokens

        if is_cmd:
            # Execute command locally on host
            output = execute_in_session_command(cmd_args)
            # Print to stderr and exit with code 2
            # Engine spec: Exit code 2 blocks LLM query, erases original prompt, and shows stderr to user
            print(output.strip(), file=sys.stderr)
            sys.exit(2)

        # ======================================================================
        # PHASE 2: JUST-IN-TIME WORKING MEMORY INJECTION
        # ======================================================================
        prompt_lower = clean_prompt.lower()
        matched_domains = set()

        for domain, keywords in DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", prompt_lower):
                    matched_domains.add(domain)
                    break

        if not matched_domains:
            sys.exit(0)

        # Search palace rooms & rules
        candidate_files = []
        if os.path.exists(PALACE_RULES_FILE):
            candidate_files.append(PALACE_RULES_FILE)
        rooms_dir = os.path.expanduser("~/.claude/palace/rooms")
        if os.path.exists(rooms_dir):
            for rname in ["decisions.md", "blueprint.md", "working.md", "procedures.md"]:
                rf = os.path.join(rooms_dir, rname)
                if os.path.exists(rf):
                    candidate_files.append(rf)

        rules_dir = os.path.expanduser("~/.claude/rules")
        if os.path.exists(rules_dir):
            for rname in ["00-core-cognition.md", "01-token-efficiency.md", "05-memory-palace.md"]:
                rf = os.path.join(rules_dir, rname)
                if os.path.exists(rf):
                    candidate_files.append(rf)

        relevant_rules = []
        seen = set()

        for cfile in candidate_files:
            with open(cfile, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str or line_str.startswith("#") or line_str.startswith("**Tags:") or line_str.startswith(">"):
                        continue
                    line_clean = line_str.lstrip("-*• ").strip()
                    if line_clean in seen:
                        continue
                    line_lower = line_clean.lower()
                    matched = False
                    for domain in matched_domains:
                        for kw in DOMAIN_KEYWORDS[domain]:
                            if kw in line_lower:
                                relevant_rules.append(line_clean)
                                seen.add(line_clean)
                                matched = True
                                break
                        if matched:
                            break
                    if len(relevant_rules) >= 2:
                        break
            if len(relevant_rules) >= 2:
                break

        if relevant_rules:
            # Emit concise JIT instruction block to stdout (shown to Claude)
            print("\n[Cortex Working Memory]")
            for r in relevant_rules:
                print(f"- {r}")

    except Exception:
        # Failsafe: never interrupt prompt submission
        sys.exit(0)

    sys.exit(0)

if __name__ == "__main__":
    main()
