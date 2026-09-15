#!/usr/bin/env python3
"""
Claude Cortex - PreToolUse Lifecycle Hook
Intercepts tool commands before execution to prevent catastrophic token dumps
(e.g., massive file cat, unpaged git logs, recursive scans) that poison context.
"""

import sys
import os
import json
import re

CATASTROPHIC_PATTERNS = [
    (r"\bcat\s+([^\s|><]+)", "cat on file"),
    (r"\bgit\s+log(?!\s+-n|\s+--oneline|\s+-1|\s+-2|\s+-3|\s+-5|\s+-10|\s+-20|\s+--stat)\b", "unpaged git log"),
    (r"\btree\b(?!\s+-L|\s+--level)", "unbounded tree command"),
    (r"\bfind\s+\.\s+-type\s+f\s*$", "unbounded recursive find"),
]

BLOCKED_FILES = [
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "composer.lock", "Pipfile.lock", "poetry.lock"
]

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            sys.exit(0)
        
        data = json.loads(raw_input)
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        
        if tool_name.lower() in ("bash", "bashtool"):
            cmd = tool_input.get("command", "")
            
            # Check for cat on lockfiles or huge known artifacts
            for lockfile in BLOCKED_FILES:
                if f"cat {lockfile}" in cmd or f"cat ./{lockfile}" in cmd:
                    print(
                        f"[Claude Cortex Guard] Blocked execution of 'cat {lockfile}'. "
                        f"Reading lockfiles dumps 20,000+ tokens into context. "
                        f"Use 'grep', 'jq', or targeted inspection instead.",
                        file=sys.stderr
                    )
                    sys.exit(2)
            
            # Check for cat on files larger than 150KB
            cat_match = re.search(r"\bcat\s+([^\s|><;]+)", cmd)
            if cat_match:
                target_file = cat_match.group(1).strip("'\"")
                if os.path.exists(target_file) and os.path.isfile(target_file):
                    size_kb = os.path.getsize(target_file) / 1024
                    if size_kb > 150:
                        print(
                            f"[Claude Cortex Guard] Blocked 'cat {target_file}' ({size_kb:.1f} KB). "
                            f"Use 'head -n 50', 'tail', 'grep', or the Read tool with offset/limit to avoid token bloat.",
                            file=sys.stderr
                        )
                        sys.exit(2)

    except Exception:
        # Never break execution on internal hook error
        sys.exit(0)

    sys.exit(0)

if __name__ == "__main__":
    main()
