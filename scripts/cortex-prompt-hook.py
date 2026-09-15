#!/usr/bin/env python3
"""
Claude Cortex - UserPromptSubmit Lifecycle Hook (JIT Palace Injector)
Scans the user prompt for domain keywords and injects only relevant Memory Palace
guidelines just-in-time, avoiding permanent prompt bloat and preserving prefix cache.
"""

import sys
import os
import re

PALACE_RULES_FILE = os.path.expanduser("~/.claude/palace/rules.md")

DOMAIN_KEYWORDS = {
    "git": ["git", "commit", "branch", "rebase", "merge", "pr", "stash", "checkout"],
    "database": ["sql", "postgres", "sqlite", "query", "migration", "schema", "table"],
    "dnet": ["dnet", "dotnet", "c#", "nuget", "solution", "csproj"],
    "react": ["react", "component", "hook", "state", "props", "frontend", "jsx", "tsx"],
    "test": ["test", "unit test", "coverage", "mock", "spec", "pytest", "jest"],
    "build": ["build", "compile", "docker", "deploy", "ci", "cd", "makefile"],
    "token": ["token", "tokens", "quota", "buffer", "stream", "streaming", "memory", "cache"],
}

def main():
    try:
        raw_prompt = sys.stdin.read().strip()
        if not raw_prompt:
            sys.exit(0)

        prompt_lower = raw_prompt.lower()
        matched_domains = set()

        for domain, keywords in DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", prompt_lower):
                    matched_domains.add(domain)
                    break

        if not matched_domains:
            sys.exit(0)

        # Search palace rules file or palace room markdown files
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
            # Emit concise JIT instruction block
            print("\n[Cortex Working Memory]")
            for r in relevant_rules:
                print(f"- {r}")

    except Exception:
        # Failsafe: never interrupt prompt submission
        sys.exit(0)

    sys.exit(0)

if __name__ == "__main__":
    main()
