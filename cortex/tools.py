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
    # Static risk analysis of source code (file/line/mechanism). Formerly named
    # "dream"; renamed because dream is now the in-session concept explorer and
    # this is a linter, which is a different thing.
    "analyze":  ("claude-analyze.py", []),
    # The dream exploration archive. dream itself runs in a session (it needs a
    # model), but persisting and recalling its output is plain file work, so the
    # save/list/show side is a real terminal tool the framework calls automatically.
    "dream-doc": ("dream-doc.py", []),
    # Real: queries the arXiv API and returns actual papers.
    "research": ("claude-research.py", []),
    "provider": ("claude-provider.py", []),
    "update":   ("claude-update.py", []),
}

# Commands that existed in older versions and no longer do. Naming them
# explicitly produces a useful message instead of a confusing one.
# dream is not a terminal command: exploring a concept requires a model, which
# lives in a session, not in the shell. Point the user at the in-session form.
IN_SESSION_ONLY = {
    "dream": "dream explores a concept in depth and needs a model to reason. "
             "In a Claude Code session, type:  /dream <your concept>",
    "think": "concept reasoning happens in a session: /dream <your concept>",
}

RETIRED = {
    # Cut rather than rewritten. It printed a fixed scaffold that varied only by
    # the echoed prompt - no analysis, no model call. The honest options were to
    # make it call a model or to remove it, and `cc dream` now covers the
    # "what breaks" case with real findings, so a second scaffold earns nothing.
    "smart": "concept reasoning happens in a session: /dream <your concept>",
    "cognition": "concept reasoning happens in a session: /dream <your concept>",

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
    """Where the tool scripts might live.

    A REPOSITORY CHECKOUT WINS over the installed copy.

    The order used to be the other way round, and the effect was nasty during
    development: `cc dream` from a checkout silently ran the copy installed at
    ~/.claude/scripts instead of the file being edited. The symptom was a
    rewritten tool appearing not to have changed - or worse, crashing in code
    that no longer existed. You should run the code you are looking at.

    Outside a checkout there is no repo directory, so the installed copy is used
    exactly as before.
    """
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_scripts = os.path.join(repo, "scripts")
    # Treat it as a checkout only if it really looks like one, so an installed
    # layout that happens to have a sibling directory is not mistaken for source.
    if os.path.isdir(repo_scripts) and os.path.isfile(os.path.join(repo, "install.sh")):
        yield repo_scripts
    yield os.path.join(shared_claude_dir(), "scripts")
    yield repo_scripts


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


def is_in_session_only(command):
    return command in IN_SESSION_ONLY


def explain_in_session(command):
    import sys as _sys
    print(f"cc: '{command}' runs inside a Claude Code session, not the terminal.",
          file=_sys.stderr)
    print(f"    {IN_SESSION_ONLY[command]}", file=_sys.stderr)
    return 0


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
