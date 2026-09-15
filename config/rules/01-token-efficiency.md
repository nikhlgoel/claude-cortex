---
name: token-efficiency
description: Strictly enforces minimal verbose explanations, targeted file inspections, and token conservation.
---

# Token Efficiency & Precision Rule

1. **Concise Explanations**:
   - Provide minimal, precise, high-density explanations.
   - Do not summarize what the user just said or describe code line-by-line unless explicitly requested.
   - State the problem, fix, and verification result directly.

2. **Targeted Inspections**:
   - Do NOT read full files over 200 lines if only a specific function or section is needed.
   - Use line-range reads, `sed -n`, `grep -n`, or ast-grep to inspect exact locations.
   - Avoid dumping large command outputs or build logs into context.

3. **Incremental Execution**:
   - Make edits, run tests, and check results as you proceed.
   - Avoid sprawling multi-file speculative edits without interim verification.

4. **Strategic Compaction**:
   - If a conversation turn crosses 100k tokens, advise or run `/compact-smart` to extract key learnings into `memory/MEMORY.md` and keep the session lean.
