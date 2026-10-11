# Master Task List

Status after the verified audit. See `BUGS.md` for the evidence behind each line.

## Done
- [x] Fix the swallowed exceptions that lose data (`providers.json`, `install.py` Desktop config); the rest are intentional fail-open/cleanup paths
- [x] Shell safety: scripts were already guarded; added an empty-`HOME` guard
- [x] Confirmation before destructive actions (`cc profile remove` needs `--yes` without a person present)
- [x] Cross-process safety for `.claude.json` / settings writes (`jsonfile.file_lock`, stale-lock recovery)
- [x] Network resilience: bounded retry/backoff for the gateway and Gemini proxy
- [x] Bounded reads in `claude-analyze.py` (5 MB cap, reported not skipped silently)
- [x] Windows: Ctrl+C handling, junction fallback for synced profiles, owner-only ACL for API keys, detached gateway
- [x] Model support: Opus 5.5, Sonnet 5.5, Fable 5.1 / 5 (IDs verified)
- [x] `evaluate_impact` MCP tool - a heuristic risk score that reports what it could not measure
- [x] Capacity parsing fixed for the real usage-cache shape
- [x] Test suite repaired and honest: 100 tests, no fabricated metrics, mutation-checked
- [x] Ghost slash commands removed; a test now guards against new ones

## Decided against
- [ ] ~~Lazy Skills auto-indexer in the prompt hook~~ - Claude Code already discovers skills from their frontmatter; an indexer would add tokens to every prompt
- [ ] ~~Graphify AST map~~ - not part of this repository
- [ ] ~~Flush every `print()`~~ - not a defect (see `BUGS.md`)

## Open
- [ ] Audit `cortex/ghidra.py` for subprocess timeouts and `claude-update.py` for unprompted extension updates
- [ ] Run `pyflakes` / `ruff` once available and clean the unused imports
- [ ] Verify the `python3` hook commands on a clean Windows install (and have `cc doctor` check it)
- [ ] Reconcile `install.py`'s `claudeProcessWrapper` with the README's environment-variable approach
- [ ] Make the version strings agree (`install.sh` 1.2.0, `cortex` 2.0.0, releases 1.1.0)
- [ ] Delete `fix_batch_1..4.py` (one-shot patch scripts; re-running them duplicates code)
