---
name: cortex-in-session-commands
description: Guarantees instant in-session execution of Claude Cortex management commands (cc continue, cc switch, cc model, cc provider, cc update, cc status, cc palace, cc dream) directly inside an active Claude Code prompt.
---

# In-Session Cortex Command Execution Rule (`cc` Protocol)

1. **Immediate Execution of Management Commands**:
   When the user inputs ANY of the following commands in the prompt (whether prefixed with `cc `, `claude `, with `/`, or typed as plain keywords):
   - `cc continue` / `continue` / `claude continue [profile]` / `/continue`
   - `cc switch` / `switch` / `claude switch [profile]` / `/switch`
   - `cc model` / `model` / `model list` / `model set <id>` / `model free`
   - `cc provider` / `provider` / `provider set <name>` / `provider key <name> <key>`
   - `cc update` / `update` / `update check` / `update apply`
   - `cc palace` / `palace` / `remember` / `recall`
   - `cc dream` / `dream`
   - `cc turbo` / `turbo` / `cc effort <level>` / `effort <level>`
   - `cc status` / `cc capacity` / `quota`

2. **Mandatory Action (Zero Chat Lag)**:
   - Claude MUST NEVER treat these commands as casual conversational questions.
   - Claude MUST NEVER state "I cannot execute terminal commands" or ask the user to leave the session to run them.
   - If not already intercepted by the `UserPromptSubmit` hook, Claude MUST IMMEDIATELY invoke the `Bash` tool to execute:
     ```bash
     ~/.local/bin/cc <command> <args>
     ```

3. **Account Switching / Failover Handoff Behavior**:
   - If the user runs `cc continue [profile]` or `cc switch [profile]`:
     a. Claude MUST first append current progress and task status into `memory/MEMORY.md` within the project directory.
     b. Claude runs `~/.local/bin/cc switch <profile>` or `python3 ~/.claude/scripts/claude-capacity-check.py --switch <profile>` via Bash.
     c. Claude displays the output and tells the user:
        "✓ Switched active profile to **[PROFILE]**. Project memory has been checkpointed.
        To resume with the new account's quota, simply type `/exit` (or press `Ctrl+C`) and run:
        `cc continue`
        Your session will resume immediately under the new account with 100% context preserved!"

4. **Model & Provider Commands Inside Session**:
   - If user asks for `cc model`, `model list`, `model free`, or `model set <id>`:
     Execute `python3 ~/.claude/scripts/claude-models.py <action> <args>` via Bash tool and render the benchmark table.
   - If user asks for `cc provider`, `provider key <provider> <key>`, or `provider set <provider>`:
     Execute `python3 ~/.claude/scripts/claude-provider.py <action> <args>` via Bash tool and render the status table.
   - If user asks for `cc update`:
     Execute `python3 ~/.claude/scripts/claude-update.py <args>` via Bash tool and render the unified update status table.
