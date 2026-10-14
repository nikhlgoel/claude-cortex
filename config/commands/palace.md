---
name: palace
description: Display the status, rooms, and memories stored in the project's Cognitive Memory Palace.
command: true
---

# Cognitive Memory Palace

Inspect the current project's Memory Palace structure, rooms, and indexed tags.

## Instructions for Claude

1. Run the Memory Palace status inspection via Bash:
   ```bash
   cc palace status
   ```

2. Provide a brief overview of the rooms and ask the user if they'd like to:
   - **Recall** past decisions, patterns, or bug fixes (`/recall <topic>`)
   - **Store** a newly solved issue or architectural decision (`/remember <room> <notes>`)
