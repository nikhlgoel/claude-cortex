---
name: cortex-in-session-commands
description: Guarantees instant in-session execution of Claude Cortex management commands (continue, switch, model, provider, status, quota, palace, dream) directly inside an active Claude Code prompt.
---

# In-Session Cortex Command Execution Rule

1. **Immediate Execution of Management Commands**:
   When the user inputs ANY of the following commands in the prompt (whether prefixed with `claude `, with a slash `/`, or typed as plain keywords):
   - `continue` / `claude continue [profile]` / `/continue [profile]`
   - `switch` / `claude switch [profile]` / `/switch [profile]`
   - `status` / `quota` / `claude status` / `claude quota` / `/status` / `/quota`
   - `model` / `claude model [args]` / `/model [args]`
   - `provider` / `claude provider [args]` / `/provider [args]`
   - `palace` / `remember` / `recall` / `claude palace` / `/palace`
   - `dream` / `claude dream` / `/dream`
   - `turbo` / `fast` / `smart` / `research`

2. **Mandatory Action (Zero Chat Lag)**:
   - Claude MUST NEVER treat these commands as casual conversational questions.
   - Claude MUST NEVER state "I cannot execute terminal commands" or ask the user to leave the session to run them.
   - Claude MUST IMMEDIATELY invoke the `Bash` tool to execute the command:
     ```bash
     ~/.local/bin/claude <command> <args>
     ```
     (or on Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File ~/.local/bin/claude.ps1 <command> <args>`)

3. **Account Switching / Failover Handoff Behavior**:
   - If the user runs `continue [profile]` or `switch [profile]`:
     a. Claude MUST first append current progress and task status into `memory/MEMORY.md` within the project directory.
     b. Claude runs `~/.local/bin/claude switch <profile>` or `python3 ~/.claude/scripts/claude-capacity-check.py --switch <profile>` via Bash.
     c. Claude displays the output and tells the user:
        "✓ Switched active profile to **[PROFILE]**. Project memory has been checkpointed.
        To resume with the new account's quota, simply type `/exit` (or press `Ctrl+C`) and run:
        `claude continue`
        Your session will resume immediately under the new account with 100% context preserved!"

4. **Model & Provider Commands Inside Session**:
   - If user asks for `model`, `model list`, `model free`, or `model set <id>`:
     Execute `python3 ~/.claude/scripts/claude-models.py <action> <args>` via Bash tool and render the benchmark table.
   - If user asks for `provider`, `provider key <provider> <key>`, or `provider set <provider>`:
     Execute `python3 ~/.claude/scripts/claude-provider.py <action> <args>` via Bash tool and render the status table.
