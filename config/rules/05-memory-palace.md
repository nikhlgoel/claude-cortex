---
name: memory-palace
description: Cognitive memory architecture for human-like retention of architecture, procedures, pitfalls, and decisions.
---

# Cognitive Memory Palace Rule

1. **Human-Like Dual Memory Access**:
   - **Before starting complex tasks**: Check if the project has relevant past lessons in the Memory Palace. Query `claude-palace recall "<feature or error>"` or read the relevant room (`rooms/graveyard.md` for bugs, `rooms/blueprint.md` for architecture).
   - **After resolving tricky issues or making major decisions**: Do NOT let breakthroughs evaporate in chat logs. Automatically deposit the lesson into the Palace:
     ```bash
     claude-palace remember --room <room> --title "<short-title>" --content "<concise explanation>" --tags <tag>
     ```

2. **Room Designation**:
   - `blueprint`: Architectural boundaries, models, invariants.
   - `procedures`: Workflows, verified build & test commands.
   - `graveyard`: Hard-won bugfixes, edge cases, anti-patterns to avoid repeating.
   - `decisions`: Why choice A was selected over choice B.
   - `working`: Active goals and immediate continuity context.

3. **Token Density & Optimization**:
   - Keep palace entries concise, high-signal, and bulleted.
   - Never paste giant logs or full file dumps into the Palace.
