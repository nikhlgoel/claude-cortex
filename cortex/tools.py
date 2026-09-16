"""
Dispatch to the standalone Cortex tools.

These live as separate scripts under ``~/.claude/scripts``. Routing them through
the core matters for a specific reason: before this existed, ``cc palace`` and
friends fell through to the session launcher and were sent to Claude **as the
prompt**, which silently started a real API session to answer the word "palace".
Twelve commands behaved that way. A command the core does not recognize must
never become a prompt.
"""

from __future__ import annotations

import os
import subprocess
import sys

from .paths import shared_claude_dir

# command -> (script name, leading args)
TOOLS = {
    "palace":   ("claude-palace.py", []),
    "remember": ("claude-palace.py", ["remember"]),
    "recall":   ("claude-palace.py", ["recall"]),
    # Scaffold: fixed checklist, no model calls, identical for any topic.
    "dream":    ("claude-dream.py", []),
    # Real: queries the arXiv API and returns actual papers.
    "research": ("claude-research.py", []),
    "think":    ("claude-cognition.py", []),
    "smart":    ("claude-cognition.py", []),
    "model":    ("claude-models.py", []),
    "models":   ("claude-models.py", []),
    "provider": ("claude-provider.py", []),
    "update":   ("claude-update.py", []),
}

# Commands that existed in older versions and no longer do. Naming them
# explicitly produces a useful message instead of a confusing one.
RETIRED = {
    "menu":  "the interactive menu was removed; use 'cc --help'",
    "docs":  "documentation moved to README.md and HANDOVER.md in the repository",
    "turbo": "use 'cc -t' to launch in turbo mode",
    "fast":  "use 'cc -t' to launch in turbo mode",
    "effort": "pass '-e <level>' when launching, e.g. 'cc -e high'",
    "reasoning": "pass '-e <level>' when launching, e.g. 'cc -e high'",
    "clean": "removed; Claude Code manages its own cleanup via cleanupPeriodDays",
    "test":  "run the sandbox suite from the repository: make sandbox",
    "bench": "run the sandbox suite from the repository: make sandbox",
}


def script_dirs():
    """Where the tool scripts might live: installed first, then the checkout."""
    yield os.path.join(shared_claude_dir(), "scripts")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    yield os.path.join(repo, "scripts")


def find_script(name):
    for directory in script_dirs():
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def is_tool(command):
    return command in TOOLS


def is_retired(command):
    return command in RETIRED


def run(command, args):
    """Run a tool script. Returns its exit code."""
    script_name, prefix = TOOLS[command]
    script = find_script(script_name)
    if not script:
        print(f"cc: {script_name} is not installed.", file=sys.stderr)
        print("    Reinstall Cortex, or run it from the repository checkout.",
              file=sys.stderr)
        return 1
    try:
        return subprocess.run([sys.executable, script] + prefix + list(args)).returncode
    except KeyboardInterrupt:
        return 130
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"cc: failed to run {command}: {exc}", file=sys.stderr)
        return 1


def explain_retired(command):
    print(f"cc: '{command}' is no longer a Cortex command.", file=sys.stderr)
    print(f"    {RETIRED[command]}", file=sys.stderr)
    return 2
