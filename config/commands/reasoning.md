---
name: reasoning
description: Configure or view the reasoning/thinking effort level (low, medium, high, xhigh, max) for deep architecture or fast coding.
command: true
---

# Reasoning & Thinking Effort

Adjust the thinking token budget and reasoning effort for Claude Code.

## Valid Levels
- `low`: Quick responses, fast token turnaround, light thinking.
- `medium`: Balanced reasoning for typical feature development.
- `high`: Deep reasoning for refactors, complex bugs, and algorithms.
- `xhigh` / `max`: Maximum reasoning effort for difficult architectural problems.
- `off`: Disables thinking tokens entirely for minimal latency.

## Instructions for Claude

1. If the user specified a level (e.g. `/reasoning high`, `/reasoning max`, `/effort low`):
   - Update the configuration in `~/.claude/settings.json` via python:
     ```bash
     python3 -c "
     import json, os
     p = os.path.expanduser('~/.claude/settings.json')
     with open(p) as f: d = json.load(f)
     d['effortLevel'] = '<level>'
     with open(p, 'w') as f: json.dump(d, f, indent=2)
     print('Effort set to <level>')
     "
     ```
   - Inform the user that the reasoning effort level is now active.
2. If no argument is passed:
   - Read current effort from `~/.claude/settings.json` and display the available choices.
