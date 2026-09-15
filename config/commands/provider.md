---
name: provider
description: Manage and switch API providers (OAuth, Anthropic API, OpenRouter, Google Gemini AI Studio) directly in-session.
command: true
---

# API Provider Manager

Configure API keys and switch between OAuth subscriptions, Anthropic Console API, OpenRouter.ai, or Google Gemini AI Studio.

## Instructions for Claude

1. If the user passed arguments (e.g. `set <name>`, `key <name> <key>`, `status`, `reset`):
   Execute via Bash:
   ```bash
   python3 ~/.claude/scripts/claude-provider.py $ARGUMENTS
   ```
2. If no arguments were passed, display provider status:
   ```bash
   python3 ~/.claude/scripts/claude-provider.py status
   ```
3. Inform the user of next steps:
   - To switch models: `/model` or `/model free`
   - To switch providers: `/provider set <oauth|openrouter|gemini|anthropic>`
   - To configure key: `/provider key <provider> <api_key>`
