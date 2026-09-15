---
name: dream-simulation
description: Neuroscience-grounded cognitive dream simulation for rapid stress-testing, bug hunting, and creative divergence.
---

# Cognitive Dream Simulation & Stress Testing Rule

1. **Neuroscience Rationale**:
   - The human brain's REM sleep and Default Mode Network (DMN) rehearse worst-case scenarios, synthesize disjoint ideas, and consolidate memory without real-world risk.
   - Claude uses the Dream Engine (`claude-dream`) to simulate counterfactual edge cases before code hits production.

2. **Triggering Simulation**:
   - **Post-Implementation & Pre-Release**: When finishing critical features, security-sensitive logic, multi-account orchestration, or complex distributed systems.
   - **User Trigger**: On commands `/dream`, `claude dream`, or requests to "stress-test", "bug hunt", "find loopholes", "think like an attacker", or "generate creative ideas".

3. **Chambers & Domains**:
   - `technical`: Concurrency race conditions, OOM leaks, rate limit thrashing, silent failures.
   - `security`: Token extraction, path traversal, injection, unauthorized state mutation.
   - `business`: Unit economics collapse, quota exhaustion loops, subscriber churn.
   - `psychology`: Cognitive friction, confusing CLI errors, misleading prompts.
   - `creative`: Divergent cross-pollination, architectural 10x simplifications.

4. **Autonomous Memory Consolidation**:
   - When a dream scenario reveals a plausible high-risk failure mode, do not leave it in ephemeral chat logs:
     - Automatically record prevention rules into the Cognitive Memory Palace (`rooms/graveyard.md`).
     - Record high-value architectural ideas into `rooms/decisions.md` or `rooms/blueprint.md`.
     - Command: `claude-palace remember --room graveyard --title "Discovered Edge Case: <Name>" --content "<Risk & Prevention>" --tags dream,risk,<domain>`
