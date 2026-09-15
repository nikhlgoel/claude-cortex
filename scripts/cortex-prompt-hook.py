#!/usr/bin/env python3
"""
Claude Cortex - UserPromptSubmit Lifecycle Hook & In-Session Command Router
Dual Capability:
1. In-Session Command Execution:
   Intercepts prompts that start with 'claude', '/', or cortex commands (model, provider,
   effort, reasoning, turbo, capacity, palace, dream), executes them immediately on the host,
   prints output to stderr, and exits with code 2 (blocking LLM dispatch and erasing prompt).
2. Just-In-Time Working Memory Injector:
   For regular development prompts, scans for domain keywords and injects at most 2 relevant
   rules from Memory Palace without bloating prefix cache.
"""

import sys
import os
import re
import json
import subprocess

SHARED_DIR = os.path.expanduser("~/.claude")
SCRIPTS_DIR = os.path.join(SHARED_DIR, "scripts")
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
    "model", "provider", "effort", "reasoning", "turbo",
    "capacity", "quota", "palace", "dream", "cortex", "docs", "menu"
)

def update_session_effort(level):
    """Updates reasoning effort level in settings.json and profile settings."""
    level = level.lower().strip()
    valid_levels = ["low", "medium", "high", "max", "auto"]
    if level not in valid_levels:
        level = "medium"

    thinking_tokens_map = {
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
        msg = update_session_effort("low")
        os.environ["CLAUDE_TURBO"] = "1"
        os.environ["BASH_MAX_OUTPUT_LENGTH"] = "4000"
        return "⚡ Claude Cortex Turbo Mode ACTIVE (Effort: low, Thinking: disabled, Fast & Token-Efficient)"
    else:
        msg = update_session_effort("medium")
        os.environ.pop("CLAUDE_TURBO", None)
        os.environ["BASH_MAX_OUTPUT_LENGTH"] = "6000"
        return "✓ Claude Cortex Turbo Mode DISABLED (Effort: medium, Thinking: 8192 tokens)"

def execute_in_session_command(tokens):
    """Executes a cortex command and returns stdout/stderr."""
    cmd = tokens[0].lower()
    sub_args = tokens[1:]

    # Strip leading slash if user typed /model, /provider, etc.
    if cmd.startswith("/"):
        cmd = cmd[1:]

    if cmd == "model":
        action = sub_args[0] if sub_args else "list"
        remaining = sub_args[1:]
        script = os.path.join(SCRIPTS_DIR, "claude-models.py")
        res = subprocess.run([sys.executable, script, action] + remaining, capture_output=True, text=True)
        return res.stdout or res.stderr

    elif cmd == "provider":
        action = sub_args[0] if sub_args else "status"
        remaining = sub_args[1:]
        script = os.path.join(SCRIPTS_DIR, "claude-provider.py")
        res = subprocess.run([sys.executable, script, action] + remaining, capture_output=True, text=True)
        return res.stdout or res.stderr

    elif cmd in ("effort", "reasoning"):
        if sub_args:
            return update_session_effort(sub_args[0])
        else:
            cur = os.environ.get("CLAUDE_CODE_EFFORT_LEVEL", "medium")
            return f"Current Reasoning Effort: {cur.upper()} (Options: low, medium, high, max, auto)"

    elif cmd == "turbo":
        if sub_args and sub_args[0].lower() in ("off", "disable", "stop"):
            return update_session_turbo(enable=False)
        return update_session_turbo(enable=True)

    elif cmd in ("capacity", "quota"):
        script = os.path.join(SCRIPTS_DIR, "claude-capacity-check.py")
        res = subprocess.run([sys.executable, script], capture_output=True, text=True)
        return res.stdout or res.stderr

    elif cmd == "palace":
        script = os.path.join(SCRIPTS_DIR, "claude-palace.py")
        res = subprocess.run([sys.executable, script] + sub_args, capture_output=True, text=True)
        return res.stdout or res.stderr

    elif cmd == "dream":
        script = os.path.join(SCRIPTS_DIR, "claude-dream.py")
        res = subprocess.run([sys.executable, script] + sub_args, capture_output=True, text=True)
        return res.stdout or res.stderr

    elif cmd == "cortex":
        return (
            "======================================================================\n"
            "                 Claude Cortex - In-Session Commands\n"
            "======================================================================\n"
            "Available commands inside interactive prompt:\n"
            "  claude model [list|free|set <id>|info <id>]   Model explorer & selector\n"
            "  claude provider [status|set <p>|key <p> <k>]  Provider manager\n"
            "  claude effort [low|medium|high|max|auto]       Adjust reasoning depth\n"
            "  claude turbo [on|off]                          Ultra-fast token saver\n"
            "  claude capacity                                Subscription & quota check\n"
            "  claude palace [status|recall <q>]              Memory Palace lookup\n"
            "  claude dream                                   Dream simulator engine\n"
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

        # Parse prompt string (handles JSON wrapper or raw text)
        prompt_text = raw_input
        try:
            parsed = json.loads(raw_input)
            if isinstance(parsed, dict):
                prompt_text = parsed.get("prompt") or parsed.get("text") or parsed.get("content") or raw_input
        except Exception:
            prompt_text = raw_input

        if not isinstance(prompt_text, str):
            prompt_text = str(prompt_text)

        clean_prompt = prompt_text.strip()
        tokens = clean_prompt.split()
        if not tokens:
            sys.exit(0)

        # ======================================================================
        # PHASE 1: IN-SESSION CORTEX COMMAND INTERCEPTION
        # ======================================================================
        is_cmd = False
        cmd_args = []

        # Case A: User typed 'claude <cmd> ...' or '!claude <cmd> ...'
        if tokens[0] in ("claude", "!claude") and len(tokens) > 1:
            is_cmd = True
            cmd_args = tokens[1:]
        # Case B: User typed '/<cmd> ...' (e.g. /model, /provider)
        elif tokens[0].startswith("/") and tokens[0][1:] in COMMAND_KEYWORDS:
            is_cmd = True
            cmd_args = [tokens[0][1:]] + tokens[1:]
        # Case C: Standalone exact keyword commands (e.g. 'model free', 'effort high', 'turbo')
        elif tokens[0] in COMMAND_KEYWORDS and (
            len(tokens) == 1
            or tokens[1] in ("list", "set", "free", "paid", "info", "status", "key",
                            "low", "medium", "high", "max", "auto", "on", "off",
                            "recall", "remember", "query", "check")
        ):
            is_cmd = True
            cmd_args = tokens

        if is_cmd:
            # Execute command directly on machine
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
