---
name: docs
description: View documentation for Claude Cortex (multi-account management, capacity failover, Memory Palace, Dream Simulation, models/reasoning, live pairing, and API providers).
command: true
---

# Claude Cortex Documentation

Display the complete operational reference for all features added to this installation.

## Action

Run the local documentation viewer:

```bash
claude docs
```

## Summary of Custom Features
- **Multi-Account Switching**: Use `claude -ws` or `claude -vl` from terminal, or `/switch [prof]` in-session.
- **Failover on Rate Limits**: Run `claude continue` in terminal or `/continue` in-session; automatically checks all accounts and selects one with remaining capacity.
- **Quota & Limits**: Run `claude quota` in terminal or `/quota` in-session to inspect live utilization and reset countdowns across accounts.
- **Cognitive Memory Palace v2**: Run `claude palace` / `/palace` to view rooms, `claude remember` / `/remember` to store breakthrough lessons, and `claude recall` / `/recall` to search past patterns.
- **Cognitive Dream Engine**: Run `claude dream` / `/dream` to simulate counterfactual edge cases across Technical/Security, Business/Economics, UX Friction, and Creative innovation.
- **Latest Models & Reasoning**: Shortcuts `claude -s` (Sonnet 5), `claude -o` (Opus 5), `claude -h` (Haiku 4.5), and reasoning control with `claude -e <lvl>` or `/reasoning <lvl>`.
- **Live Pairing & Discussion**: Use `/pair` or `/discuss` to collaboratively explore decisions before implementation and automatically prompt for follow-up amendments.
- **External API Providers & Gemini Proxy**: Run `claude provider` or `/provider` to fallback onto Anthropic API keys, OpenRouter.ai, or Google Gemini AI Studio.
- **Interactive Menu**: Run `claude menu` from terminal for visual account selection and tools.
- **Token Efficiency**: Use `/compact-smart` to preserve architectural decisions in `memory/MEMORY.md` before compacting. Use `/clean` for cache pruning.
