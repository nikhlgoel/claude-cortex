#!/usr/bin/env python3
"""
Claude Cortex - PreCompact Lifecycle Hook

Fires immediately before Claude Code compacts the conversation, and prints standing
preservation directives on stdout, which Claude Code adds to the compaction prompt.

What it does NOT do: it does not extract anything into the memory palace, and it
reads nothing from the session. (An earlier docstring said it "extracts durable
state to Cognitive Palace rooms"; the directives have always been static.) Making
compaction actually durable - writing the goal, files touched and decisions to disk
and re-injecting them afterwards - is a separate feature, not this hook.

A hook must fail open: an internal error never blocks compaction.
"""

import sys

DIRECTIVES = [
    "CRITICAL PRE-COMPACTION PRESERVATION DIRECTIVES:",
    "- Retain all Architectural Decision Records (ADRs), component boundaries, and chosen design patterns.",
    "- Retain the current active task from the Workshop, including pending steps and blockers.",
    "- Retain exact file paths, modified function/variable names, and verification test status.",
    "- Retain bug root causes and their resolved fixes (avoid re-suggesting failed hypotheses).",
    "- Drop conversational chit-chat, verbose tool outputs, and redundant read chunks to maximize token compaction.",
]


def main():
    try:
        sys.stdin.read()          # drain the JSON payload Claude Code sends; unused
    except (OSError, ValueError):
        pass
    try:
        print("\n".join(DIRECTIVES))
    except OSError:
        pass                      # fail open: never block compaction
    sys.exit(0)


if __name__ == "__main__":
    main()
