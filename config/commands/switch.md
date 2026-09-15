---
name: switch
description: Switch active Claude Code account between configured profiles (e.g. WS, VL, work) and prepare for seamless continuation.
command: true
---

# Switch Account Command

Switch the active Claude Code account for subsequent runs, ensuring current project understanding and memory are synced.

## Usage

```bash
# Switch to a specific profile
/switch ws
/switch vl
/switch work

# Or simply toggle / check best capacity
/switch
```

## Instructions for Claude

1. If the user specified an account target (e.g. `ws`, `vl`, `work`, or index `1`, `2`):
   - Execute bash command:
     ```bash
     claude switch <target>
     ```
   If no target was specified, execute capacity-aware auto-switch:
     ```bash
     python3 ~/.claude/scripts/claude-capacity-check.py --switch-best
     ```

2. Before the user exits or switches sessions:
   - Ensure any essential task progress, architectural notes, or pending commands are saved into the project's memory file:
     `~/.claude/projects/<current-project-key>/memory/MEMORY.md` or local `CLAUDE.md`.
3. Inform the user:
   - "Default account has been switched to **<TARGET>**. Because both accounts share the same projects and memory directories, you can exit (`/exit`) and immediately run `claude continue` to resume right where you left off with the new account's quota."
