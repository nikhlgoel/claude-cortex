---
name: model
description: Browse, inspect benchmarks, filter (Free vs Paid), and set the active model for the active API provider.
command: true
---

# Model Selector & Benchmark Inspector

View benchmarks, compare free vs paid models, and switch models for the active provider.

## Instructions for Claude

1. If the user passed arguments (e.g. `set <model>`, `free`, `paid`, `info <model>`, `search <query>`):
   Execute via Bash:
   ```bash
   cc model $ARGUMENTS   # live OpenRouter catalog, real pricing
   ```
2. If no arguments were passed, list all available models and benchmarks for the active provider:
   ```bash
   cc model list
   ```
3. Present the table clearly, noting:
   - Which models are 100% **FREE** (0 credit cost)
   - Benchmark ratings (Coding score, Reasoning score, Latency)
   - How to switch models (`/model set <model_id>` or `claude model set <model_id>`).
