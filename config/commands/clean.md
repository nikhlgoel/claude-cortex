---
name: clean
description: Clean temporary caches, stale snapshots, and dead sessions to optimize disk and token usage.
command: true
---

# Clean Command

Run the Claude Code token & storage optimization maintenance script.

## Usage

```bash
/clean
```

## Action

Run the cleanup script and report results:

```bash
~/.claude/scripts/token-opt-clean.sh true
```

Display the number of stale items cleaned and total storage freed.
