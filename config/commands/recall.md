---
name: recall
description: Search and recall relevant memories, past solutions, and architectural patterns from the Memory Palace.
command: true
---

# Recall from the Memory Palace

Search across all rooms (or a specific room) in the Memory Palace for past bug fixes, architectural guidelines, decision records, or verified procedures.

## Instructions for Claude

1. Extract the query or search topic from the user's input.
   If the user specifies a room (e.g., "in graveyard", "blueprint", "procedures", "decisions", "study"), pass `--room <room>`.
2. Execute the recall search via Bash:
   ```bash
   claude-palace recall [--room <room>] "<query>"
   ```
3. Synthesize the findings and explain how past project experiences directly apply to the current task.
