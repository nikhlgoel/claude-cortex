---
name: recall
description: Search and recall relevant memories, past solutions, and architectural patterns from the Memory Palace.
command: true
---

# Recall from the Memory Palace

Search across all rooms (or a specific room) in the Memory Palace for past bug fixes, architectural guidelines, decision records, or verified procedures.

## Instructions for Claude

1. Extract the query or search topic from the user's input.
   Add `--explain` if the user wants to know why a memory was chosen, `--history` to include replaced (older) versions, and `--file <path>` for a file they are working on.
2. Execute the recall search via Bash:
   ```bash
   cc palace recall "<query>"
   ```
3. Synthesize the findings and explain how past project experiences directly apply to the current task.
