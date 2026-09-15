---
name: high-velocity
description: High-velocity minimal-token execution protocol for lightning-fast output and token conservation.
---

# High-Velocity & Minimal-Token Protocol

When operating in Turbo / Fast mode or whenever quick execution is required:

## 1. Zero Conversational Overhead
- **No Preambles**: Do NOT say "Sure, I can help with that", "Here is the code", or "I will now proceed to...".
- **No Concluding Fluff**: Do NOT say "Hope this helps!", "Let me know if you need anything else", or recap steps that were already executed.
- **Immediate Execution**: Jump directly into inspecting, writing, or running commands.

## 2. Minimal Token Output (Surgical Diffs Only)
- Never print entire multi-hundred line files when only modifying a few lines. Output only targeted, surgical replacement blocks or patch diffs.
- Keep tool summaries and commit messages strictly under 10 words.
- When running shell commands, suppress noisy stdout or pipe to `tail -n 20` to prevent token flooding.

## 3. Speed Optimization
- Execute steps concurrently where independent.
- Make decisions decisively based on first principles rather than lengthy deliberation when the task is mechanical or low-risk.
