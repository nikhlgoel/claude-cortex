---
name: token-status
description: Audit token consumption in the current session and provide proactive recommendations to save tokens.
command: true
---

# Token Status & Optimization Audit

Audit context size, turn usage, and identify high-consumption sources.

## Instructions for Claude

1. Check the session token usage using `node ~/.claude/scripts/hooks/ecc-statusline.js` or by examining the latest turn's usage tokens.
2. Provide a breakdown:
   - Estimated context tokens used vs. limit.
   - Whether the session has passed the recommended compact threshold (100k tokens).
3. Offer actionable token-saving steps:
   - Run `/compact-smart` if context exceeds 100k tokens.
   - Use targeted tools (e.g. `sed`, `grep`, `head -n 50`) instead of dumping large files into context.
   - Avoid repetitive build logs in context by piping output through filters (e.g., `command 2>&1 | tail -n 25`).
