---
name: live-pairing
description: Behavioral rules for interactive pairing, live discussion checkpoints, and amendment prompts.
---

# Live Pairing & Discussion Rules

1. **Discuss Before Disruptive Changes**:
   - When the user activates pairing (`/pair`, `/discuss`, or asks to "discuss before changing"), present the proposed strategy and pause for feedback before writing or modifying code.

2. **Auto-Start on User Input**:
   - As soon as the user gives feedback or greenlights a step, immediately execute the implementation.
   - Do not require secondary confirmation prompts.

3. **Proactive Amendment Prompting**:
   - Upon finishing and verifying any code changes, always ask:
     *"Are there any extra amendments, edge cases, or adjustments you'd like to make to this part before we continue?"*
