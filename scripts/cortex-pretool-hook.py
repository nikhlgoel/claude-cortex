#!/usr/bin/env python3
"""
Claude Cortex - PreToolUse Lifecycle Hook
Intercepts tool commands before execution to prevent catastrophic token dumps
(e.g., massive file cat, unpaged git logs, recursive scans, runaway test logs)
that poison and permanently bloat the conversational context.
"""

import sys
import os
import json
import re

CATASTROPHIC_PATTERNS = [
    (r"\bgit\s+log(?!\s+-n|\s+--oneline|\s+-[0-9]|\s+--stat)\b",
     "Unpaged 'git log' dumps entire commit history. Use 'git log -n 10 --oneline'."),
    (r"\btree\b(?!\s+-L|\s+--level|\s+-d)",
     "Unbounded 'tree' command dumps thousands of paths. Use 'tree -L 2' or 'tree -L 3'."),
    (r"\bfind\s+\.\s+-type\s+f\s*$",
     "Unbounded recursive find dumps every file in the directory tree. Use targeted find or fd."),
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
            cmd = tool_input.get("command", "").strip()
            
            # Check for cat on lockfiles or huge known artifacts
            for lockfile in BLOCKED_FILES:
                if re.search(rf"\bcat\s+.*?{re.escape(lockfile)}\b", cmd):
                    print(
                        f"[Claude Cortex Guard] Blocked 'cat {lockfile}'. "
                        f"Reading lockfiles dumps 20,000+ tokens into context. "
                        f"Use 'grep', 'jq', or targeted inspection instead.",
                        file=sys.stderr
                    )
                    sys.exit(2)
            
            # Check catastrophic command patterns
            for pattern, reason in CATASTROPHIC_PATTERNS:
                if re.search(pattern, cmd):
                    print(
                        f"[Claude Cortex Guard] Blocked command: {reason}",
                        file=sys.stderr
                    )
                    sys.exit(2)

            # Check for cat on files larger than 100KB
            cat_match = re.search(r"\bcat\s+([^\s|><;]+)", cmd)
            if cat_match:
                target_file = cat_match.group(1).strip("'\"")
                if os.path.exists(target_file) and os.path.isfile(target_file):
                    size_kb = os.path.getsize(target_file) / 1024
                    if size_kb > 100:
                        print(
                            f"[Claude Cortex Guard] Blocked 'cat {target_file}' ({size_kb:.1f} KB). "
                            f"File exceeds 100KB token safety ceiling. "
                            f"Use 'head -n 50', 'tail', 'grep', or line-bounded inspection.",
                            file=sys.stderr
                        )
                        sys.exit(2)

    except Exception:
        # Fail open: never break execution on internal hook error
        sys.exit(0)

    sys.exit(0)

if __name__ == "__main__":
    main()
