---
name: update
description: Check for and apply updates across Claude Code CLI, IDE extension, UV tools, and Cortex repository.
command: true
---

# Claude Cortex Ecosystem Update Manager

Inspect and upgrade all Claude Cortex ecosystem components: CLI binary, VS Code extension, uv tools, and local repository.

## Instructions for Claude

1. If arguments are passed (e.g. `apply`, `upgrade`, `sync`):
   Execute via Bash:
   ```bash
   python3 ~/.claude/scripts/claude-update.py apply
   ```
2. If no arguments are passed or `check` is requested:
   Execute via Bash:
   ```bash
   python3 ~/.claude/scripts/claude-update.py check
   ```

3. Display the component status table clearly to the user.
