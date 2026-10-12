#!/usr/bin/env python3
"""
Claude Cortex - PreToolUse Lifecycle Hook
Intercepts tool commands before execution to prevent catastrophic token dumps
(e.g., massive file cat, unpaged git logs, recursive scans, runaway test logs)
that poison and permanently bloat the conversational context.

The decision logic lives in :func:`check_command` so it can be tested directly;
``main`` only does the stdin/exit-code plumbing. A hook must fail open: an
internal error never blocks the user's command.

Every block message names a form that WILL pass, because a block the model cannot
act on makes it retry the same shape in a loop.
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

# A pipe into one of these bounds or reduces the output, so the producer is
# harmless. jq / ConvertFrom-Json are here because the lockfile message itself
# recommends jq - blocking `cat package-lock.json | jq .name` while telling the
# model to use jq sent it round in circles.
BOUNDED = re.compile(r"\|\s*(?:head|tail|wc|grep|rg|less|more|jq|awk|sed|cut|"
                     r"Select-Object|Select-String|Measure-Object|Where-Object|"
                     r"ConvertFrom-Json)\b", re.IGNORECASE)

# A command word, not just the letters: start of the command, or right after a
# separator / `sudo`. This is what stops `git ls-tree`, `cargo tree`, and a path
# like `src/tree/` from being mistaken for the `tree` command.
_CMD_START = r"(?:^|[;&|(]\s*|\bsudo\s+)"

_GIT_LOG = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?log\b")
_GIT_LOG_BOUNDED = re.compile(r"(?:\s-n\s*\d|\s-\d+\b|--max-count|--oneline|--stat)")
_TREE = re.compile(_CMD_START + r"tree\b")
_TREE_BOUNDED = re.compile(r"(?:\s-L\s*\d|--level|\s-d\b)")
_FIND_ALL = re.compile(r"\bfind\s+\.\s+-type\s+f\s*$")

# File readers: POSIX cat/type, and PowerShell's Get-Content and its aliases. The
# verb is matched on the quote-masked command; the target is then read from the
# ORIGINAL text so a quoted path with spaces is seen whole.
_READER_VERB = re.compile(_CMD_START + r"(cat|type|gc|get-content)\s+", re.IGNORECASE)
_TARGET = re.compile(r"""(?:-(?:Literal)?Path[ \t]+)?(?:-Raw[ \t]+)?"""
                     r"""(?:"([^"]*)"|'([^']*)'|([^\s|><;]+))""", re.IGNORECASE)
_READER_BOUNDED = re.compile(r"-(?:TotalCount|Head|First|Tail|Last)\b", re.IGNORECASE)


def _mask_quotes(cmd):
    """Blank out everything inside quotes, keeping the length.

    `git commit -m "tweak git log handling"` and `grep "git log" docs` contain the
    text "git log" without running it. Matching on the masked string means prose in
    a commit message or a search pattern can no longer trigger a block whose advice
    ("use git log -n 10") the model could not follow.
    """
    out, quote = [], None
    for ch in cmd:
        if quote:
            if ch == quote:
                quote = None
                out.append(ch)
            else:
                out.append("_")
        else:
            if ch in "\"'":
                quote = ch
            out.append(ch)
    return "".join(out)


def _resolve(target, cwd):
    """Resolve a path against the session's cwd, not this process's."""
    target = os.path.expanduser(target.strip("'\""))
    if not os.path.isabs(target) and cwd:
        target = os.path.join(cwd, target)
    return target


def _read_targets(cmd, masked):
    """Yield (verb, target) for each file-reading command in ``cmd``."""
    for verb_match in _READER_VERB.finditer(masked):
        found = _TARGET.match(cmd, verb_match.end())
        if found:
            target = next((g for g in found.groups() if g), "")
            if target:
                yield verb_match.group(1), target


def check_command(command, cwd=None):
    """Return a human-readable reason to block ``command``, or None to allow it."""
    cmd = (command or "").strip()
    if not cmd:
        return None
    masked = _mask_quotes(cmd)
    piped_bounded = bool(BOUNDED.search(masked))
    read_bounded = bool(_READER_BOUNDED.search(masked))

    targets = list(_read_targets(cmd, masked))

    for verb, target in targets:
        base = os.path.basename(target.replace("\\", "/"))
        if base in LOCKFILES and not piped_bounded and not read_bounded:
            return (f"Blocked '{verb} {base}'. Reading lockfiles dumps 20,000+ tokens "
                    f"into context. Query it instead: jq '.name' {base}, or "
                    f"grep -n '<package>' {base}.")

    if _GIT_LOG.search(masked) and not _GIT_LOG_BOUNDED.search(masked) and not piped_bounded:
        return "Unpaged 'git log' dumps entire commit history. Use 'git log -n 10 --oneline'."

    if _TREE.search(masked) and not _TREE_BOUNDED.search(masked) and not piped_bounded:
        return ("Unbounded 'tree' command dumps thousands of paths. "
                "Use 'tree -L 2' or 'tree -L 3'.")

    if _FIND_ALL.search(masked):
        return ("Unbounded recursive find dumps every file in the directory tree. "
                "Use targeted find or fd.")

    if not piped_bounded and not read_bounded:
        for verb, target in targets:
            path = _resolve(target, cwd)
            if os.path.isfile(path):
                size_kb = os.path.getsize(path) / 1024
                if size_kb > SIZE_CEILING_KB:
                    return (f"Blocked '{verb} {target}' ({size_kb:.1f} KB). "
                            f"File exceeds the {SIZE_CEILING_KB}KB token safety ceiling. "
                            f"Use head/tail/grep, pipe it through a filter such as "
                            f"'| jq ...', or do a line-bounded read.")
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
