---
name: project-memory-sync
description: Standardizes project memory storage in memory/MEMORY.md for seamless multi-account handoffs and zero context loss.
---

# Project Memory & Cross-Account Handoff Rule

1. **Memory as Source of Truth**:
   - Claude Code sessions and profiles share the global `projects/` directory.
   - When significant project findings, architectural patterns, or pending tasks are discovered, record them in `memory/MEMORY.md` within the project's memory directory (`~/.claude/projects/<project-dir>/memory/MEMORY.md`).

2. **Cross-Account Continuity & Autonomous Capacity Failover**:
   - All synced profiles share the global `projects/` and `memory/` directories.
   - When a usage limit warning appears (`[Usage limit reached...]` or `[Usage limit approaching...]`), or when the user invokes `/continue` or `/switch`:
     a. Immediately flush critical task progress, modified files, and next steps into `memory/MEMORY.md`.
     b. Run `python3 ~/.claude/scripts/claude-capacity-check.py --switch-best` via bash to scan all accounts and auto-switch the active profile to the one with free capacity.
     c. Inform the user which account was auto-selected and that they can exit (`/exit`) and resume seamlessly with `claude continue`.
   - On resume (`claude continue`), read `memory/MEMORY.md` immediately to load the exact state of work with zero context loss.

3. **Memory Maintenance**:
   - Keep `memory/MEMORY.md` concise, bulleted, and actionable.
   - Prune obsolete entries as tasks are finished to preserve token efficiency.

