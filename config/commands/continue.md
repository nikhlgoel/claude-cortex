---
name: continue
description: Auto-check all configured accounts for remaining capacity (or target specific profile), switch account, sync session memory, and prepare for instant continuation.
command: true
---

# Auto-Capacity Continue & Account Failover

Inspect configured accounts for rate limits and available capacity. Switch the active profile to the best available account (or specified target profile) and checkpoint project memory so the user can continue immediately on the new quota.

## Instructions for Claude

1. If the user provided a target profile (e.g. `vl`, `ws`, `1`, `2`):
   Execute via Bash:
   ```bash
   python3 ~/.claude/scripts/claude-capacity-check.py --switch $ARGUMENTS
   ```
   Otherwise, execute capacity-aware auto-switch:
   ```bash
   python3 ~/.claude/scripts/claude-capacity-check.py --switch-best
   ```

2. Display the live capacity scan across all accounts:
   ```bash
   python3 ~/.claude/scripts/claude-capacity-check.py
   ```

3. Checkpoint project memory:
   - Identify or create `memory/MEMORY.md` in the project root or `~/.claude/projects/<current-project-key>/memory/MEMORY.md`.
   - Record current task progress, files modified, and next immediate steps.

4. Present a clear handoff instruction to the user:
   "✓ Switched active profile. Project state has been checkpointed.
   To continue with the new account's quota without losing any context:
   1. Type `/exit` (or press `Ctrl+C`).
   2. In your terminal, run:
      `claude continue`
   Claude Code will resume the exact conversation using the new account's capacity!"
