---
name: token-efficiency
description: Strictly enforces the 6-Pillar Advanced Token Conservation Protocol, cache alignment, surgical reads, and noise cancellation.
---

# Advanced Token Conservation & Precision Architecture (6-Pillar Protocol)

1. **Cache-Stabilized Static Prefix**:
   - Maintain static, deterministic prompt ordering to maximize Anthropic prompt caching hit rates (target: 90%+ hit rate for a 10x cost reduction).
   - Never inject volatile timestamps or shifting metadata into the static instruction prefix.

2. **Surgical Line-Bounded File Ingestion**:
   - Never view full files over 200 lines without explicit line limits (`StartLine`, `EndLine`).
   - Use `sed -n`, `grep -n`, or ast-grep to inspect exact locations.
   - Do not re-view files immediately after editing them when the diff is already present in the tool result.

3. **Terminal & Log Noise Cancellation**:
   - Never dump unpaged git logs or raw test suite logs into context.
   - For tests, use quiet/short modes (`pytest -q --tb=short`, `npm test -- --silent`).
   - Pipe runaway output: `command 2>&1 | tail -n 30`.

4. **Dense Signal Protocol (Zero Conversational Fluff)**:
   - Provide minimal, precise, high-density responses. Zero conversational preamble or conclusion.
   - Do not summarize what the user just said or describe code line-by-line unless explicitly requested.
   - Output diffs, code changes, and concrete test results directly.

5. **Lossless Palace-Anchored Compaction**:
   - When context reaches the auto-compaction window (~85k tokens), Claude Code triggers `PreCompact`.
   - All active architectural decisions, pending tasks, and solved bugs are preserved in the Cognitive Memory Palace (`~/.claude/palace/`), ensuring zero amnesia.

6. **Task-Tiered Model Routing**:
   - For routine coding, file exploration, and test runs, use `cc -t` / `cc turbo` or `cc effort low` to minimize reasoning token overhead.
   - Reserve deep thinking (`cc effort high` / `max`) for hard architectural decisions and algorithmic bottlenecks.
