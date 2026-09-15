#!/usr/bin/env python3
"""
Claude Cortex - PreCompact Lifecycle Hook
Fires immediately before Claude Code compacts conversation history.
Extracts durable state to Cognitive Palace rooms and provides custom
compaction directives on stdout so no critical architectural context is lost.
"""

import sys
import os
import json
import glob

PALACE_DIR = os.path.expanduser("~/.claude/palace")

def main():
    try:
        raw_input = sys.stdin.read()
        trigger = "auto"
        if raw_input.strip():
            try:
                data = json.loads(raw_input)
                trigger = data.get("trigger", "auto")
            except Exception:
                pass

        # PreCompact custom instructions returned on stdout are injected into the compaction prompt
        instructions = [
            "CRITICAL PRE-COMPACTION PRESERVATION DIRECTIVES:",
            "- Retain all Architectural Decision Records (ADRs), component boundaries, and chosen design patterns.",
            "- Retain the current active task from the Workshop, including pending steps and blockers.",
            "- Retain exact file paths, modified function/variable names, and verification test status.",
            "- Retain bug root causes and their resolved fixes (avoid re-suggesting failed hypotheses).",
            "- Drop conversational chit-chat, verbose tool outputs, and redundant read chunks to maximize token compaction."
        ]

        print("\n".join(instructions))
        sys.exit(0)

    except Exception:
        # Fail open: never block compaction if something fails
        sys.exit(0)

if __name__ == "__main__":
    main()
