---
name: compact-smart
description: Save critical context and project memory before compacting conversation to preserve maximum intelligence with minimum tokens.
command: true
---

# Smart Compaction Command

Perform a high-accuracy, zero-loss compaction:
1. Extract and write architectural decisions, active bug status, and key findings to the project's `memory/MEMORY.md`.
2. Summarize pending tasks and next steps.
3. Trigger `/compact` to clear conversational bloat while keeping all critical context permanently accessible in memory.

## Instructions for Claude

1. Identify the active project directory:
   Check `~/.claude/projects/` corresponding to the current working directory.
2. If `memory/MEMORY.md` exists or can be created in the project's memory directory:
   - Summarize:
     - What was accomplished in this session.
     - Key decisions, modified files, and conventions learned.
     - Unresolved questions or pending tasks.
   - Append or update `memory/MEMORY.md`.
3. Inform the user:
   - "✓ Key project insights, decisions, and pending tasks have been preserved in `memory/MEMORY.md`."
   - "Proceeding with context compaction..."
4. Run `/compact`.
