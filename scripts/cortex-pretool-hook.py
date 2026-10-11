#!/usr/bin/env python3
"""
Claude Cortex - PreToolUse Lifecycle Hook
Intercepts tool commands before execution to prevent catastrophic token dumps
(e.g., massive file cat, unpaged git logs, recursive scans, runaway test logs)
that poison and permanently bloat the conversational context.

The decision logic lives in :func:`check_command` so it can be tested directly;
``main`` only does the stdin/exit-code plumbing. A hook must fail open: an
internal error never blocks the user's command.
"""

import json
import os
import re
import sys

LOCKFILES = [
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "composer.lock", "Pipfile.lock", "poetry.lock",
]

# Tools whose command string this hook inspects. PowerShell matters: on Windows
# it is often the only shell in use, and `Get-Content` dumps a file as readily as
# `cat` does.
SHELL_TOOLS = ("bash", "bashtool", "powershell")

SIZE_CEILING_KB = 100

# A pipe into one of these bounds the output, so the producer is harmless.
BOUNDED = re.compile(r"\|\s*(?:head|tail|wc|grep|rg|less|more|"
                     r"Select-Object|Select-String|Measure-Object)\b", re.IGNORECASE)

# A command word, not just the letters: start of the command, or right after a
# separator / `sudo`. This is what stops `git ls-tree`, `cargo tree`, and a path
# like `src/tree/` from being mistaken for the `tree` command.
_CMD_START = r"(?:^|[;&|(]\s*|\bsudo\s+)"

_GIT_LOG = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?log\b")
_GIT_LOG_BOUNDED = re.compile(r"(?:\s-n\s*\d|\s-\d+\b|--max-count|--oneline|--stat)")
_TREE = re.compile(_CMD_START + r"tree\b")
_TREE_BOUNDED = re.compile(r"(?:\s-L\s*\d|--level|\s-d\b)")
_FIND_ALL = re.compile(r"\bfind\s+\.\s+-type\s+f\s*$")

# File readers: POSIX cat, and PowerShell's Get-Content and its aliases.
_READER = re.compile(r"(?:^|[;&|(]\s*)(cat|type|gc|get-content)\s+([^\s|><;]+)",
                     re.IGNORECASE)
_READER_BOUNDED = re.compile(r"-(?:TotalCount|Head|First|Tail|Last)\b", re.IGNORECASE)


def _resolve(target, cwd):
    """Resolve a path against the session's cwd, not this process's."""
    target = os.path.expanduser(target.strip("'\""))
    if not os.path.isabs(target) and cwd:
        target = os.path.join(cwd, target)
    return target


def check_command(command, cwd=None):
    """Return a human-readable reason to block ``command``, or None to allow it."""
    cmd = (command or "").strip()
    if not cmd:
        return None
    piped_bounded = bool(BOUNDED.search(cmd))

    for match in _READER.finditer(cmd):
        verb, target = match.group(1), match.group(2)
        base = os.path.basename(target.strip("'\"").replace("\\", "/"))
        if base in LOCKFILES and not piped_bounded:
            return (f"Blocked '{verb} {base}'. Reading lockfiles dumps 20,000+ tokens "
                    f"into context. Use 'grep', 'jq', or targeted inspection instead.")

    if _GIT_LOG.search(cmd) and not _GIT_LOG_BOUNDED.search(cmd) and not piped_bounded:
        return "Unpaged 'git log' dumps entire commit history. Use 'git log -n 10 --oneline'."

    if _TREE.search(cmd) and not _TREE_BOUNDED.search(cmd) and not piped_bounded:
        return ("Unbounded 'tree' command dumps thousands of paths. "
                "Use 'tree -L 2' or 'tree -L 3'.")

    if _FIND_ALL.search(cmd):
        return ("Unbounded recursive find dumps every file in the directory tree. "
                "Use targeted find or fd.")

    if not piped_bounded and not _READER_BOUNDED.search(cmd):
        for match in _READER.finditer(cmd):
            path = _resolve(match.group(2), cwd)
            if os.path.isfile(path):
                size_kb = os.path.getsize(path) / 1024
                if size_kb > SIZE_CEILING_KB:
                    return (f"Blocked '{match.group(1)} {match.group(2)}' ({size_kb:.1f} KB). "
                            f"File exceeds the {SIZE_CEILING_KB}KB token safety ceiling. "
                            f"Use head/tail/grep or a line-bounded read.")
    return None


def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            sys.exit(0)

        data = json.loads(raw_input)
        if str(data.get("tool_name", "")).lower() not in SHELL_TOOLS:
            sys.exit(0)

        tool_input = data.get("tool_input") or {}
        reason = check_command(tool_input.get("command", ""), data.get("cwd"))
    except Exception:
        # Fail open: never break execution on internal hook error
        sys.exit(0)

    if reason:
        print(f"[Claude Cortex Guard] {reason}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
