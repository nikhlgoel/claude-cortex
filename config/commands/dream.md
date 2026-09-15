---
name: dream
description: Cognitive Dream Engine - Simulate counterfactual edge cases, chaos vectors, UX friction, and creative leaps.
command: true
---

# Cognitive Dream Engine Simulation

Simulate reality-stressing counterfactual scenarios across Technical/Security, Business/Economic, Psychological/UX, and Creative domains to stress-test your design and code before production.

## Instructions for Claude

1. When the user requests a dream simulation (`/dream [topic]` or `/dream --quick`):
   - Determine the target topic or use the current working context/recent diffs.
   - Run the Dream Simulation Engine via Bash:
     ```bash
     claude-dream run --topic "<topic or current project context>"
     ```
   - If `--quick` is specified, use:
     ```bash
     claude-dream run --quick --topic "<topic>"
     ```
   - To target specific chambers:
     ```bash
     claude-dream run --chambers tech,security,ux --topic "<topic>"
     ```

2. **Chamber Domains**:
   - **Technical/Security Crucible**: Memory leaks, race conditions, concurrency collapse, API rate limit crashes, malicious inputs.
   - **Business/Economic Stress**: Churn spikes, pricing perception, unit economic decay, API overuse costs.
   - **Psychological/UX Friction**: Cognitive overload, ambiguous errors, onboarding cliffs, friction points.
   - **Creative & Divergent Leaps**: Non-obvious synergy, 10x architectural simplifications, paradigm shifts.

3. **Cognitive Consolidation**:
   - Present the Nightmare Failure Vectors and Daybreak Insights clearly.
   - Ask the user if they'd like to harden code against any discovered vulnerability or commit actionable insights into the Memory Palace (`/remember`).
