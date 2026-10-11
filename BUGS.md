# Bug triage - verified against the code

An earlier automated sweep listed ~350 "bugs" without checking them. Each claim
below was checked against the source. **Fixed** means changed and covered by a
test in `tests/test_core_fixes.py`; **False positive** means the code is already
correct; **Not audited** means this pass did not look, so it is neither confirmed
nor dismissed.

## Claims from the earlier sweep

| Claim | Verdict | Detail |
| :--- | :--- | :--- |
| 3 "critical" unguarded `rm -rf` in `install.sh` / `uninstall.sh` | **False positive** | `set -euo pipefail` is on and every target is `${VAR}/suffix`. `fix_batch_1.py` "fixed" it by replacing a string with itself. Added a guard for an *empty* `HOME`, which `set -u` does not catch. |
| 40 swallowed exceptions | **Mostly intentional** | Hooks must fail open and cleanup is best-effort. The harmful ones were fixed individually (see below). Not mass-edited. |
| 15 subprocess calls without a timeout | **Partly** | `claude auth login` is interactive by design. `cortex/ghidra.py` was **not audited**. |
| Ghost command `think.md` | **Fixed (and 4 more)** | `think`, `menu`, `test`, `bench`, `docs` slash commands ran removed commands or a missing script. Removed; a test now checks every command file. |
| Skills require manual prompting; add an indexer | **Not a bug** | Skills have `name`/`description` frontmatter and Claude Code discovers them natively. A hook indexer would add tokens to every prompt. Not built. |
| 40+ flake8 F-class issues | **Not audited** | `pyflakes` is not installed here. |
| 15 unmanaged `open()` / file-lock PermissionErrors | **Not substantiated** | `with open(...)` is used throughout. |
| Zombie `Popen` in `claude-provider.py` | **Misdiagnosed, related bug fixed** | The gateway is meant to outlive the command. But `start_new_session` is ignored on Windows, so it stayed attached to the console; now detached explicitly. |
| JSON read without validation | **Fixed where it loses data** | Type checks added in `providers.json` loading and the Desktop-config installer. |
| Blocking `input()` | **Fixed (a different bug)** | `isatty()` is True for NUL on Windows, so `cc profile add x < NUL` crashed with EOFError. Prompts now treat "no answer" as a decline. A timeout on an interactive prompt would be wrong. |
| `profile remove` deletes without confirmation | **Fixed** | It skipped the prompt whenever stdin was not a TTY. `--yes` is now required there. |
| `claude-update.py` updates extensions blindly | **Not audited** | |
| Graphify map building / AST timeouts | **Out of scope** | Graphify is not part of this repository. |
| 453 unflushed `print()` | **Not a bug** | stdout is line-buffered on a terminal and flushed at exit; the MCP server flushes explicitly where it matters. |
| 53 concurrency risks (`open(..., "w")` without locks) | **Fixed where it matters** | The real hazard is read-modify-write of `.claude.json` / settings, now under `jsonfile.file_lock` (stale-lock recovery). Append-only logs and caches do not need it. |
| 26 hardcoded `~/.claude` paths | **By design** | `shared_claude_dir()` *is* the shared directory profiles link to. Per-profile data uses `CLAUDE_CONFIG_DIR`. |
| No retry/backoff on 429/5xx (gateway, gemini-proxy) | **Fixed** | `open_with_retry`: 3 attempts, honours `Retry-After`, never retries a read timeout or a started stream. |
| `claude-analyze.py` reads huge files into RAM | **Fixed** | 5 MB cap; the skipped file is reported, not silently ignored. |
| Windows Ctrl+C leaks / kills the child | **Fixed** | Parent ignores SIGINT while the child runs. |
| No `schema_version` in profiles | **Not needed** | Cortex owns no schema there; `settings.json` belongs to Claude Code. |
| Opus 5.5 / Fable not supported | **Fixed** | `--opus-5-5` / `-o55`, `--sonnet-5-5`, `--fable` (= `claude-fable-5-1`), `--fable-5`. IDs verified. The proxies never 400 on unknown names; they fall back to the configured model. |
| 200k context assumption in `precompact` hook | **False positive** | The hook is 45 lines of static directives; it assumes no window size. |
| "Objective" confidence score | **Reimplemented honestly** | The first version returned constants. `evaluate_impact` now measures complexity delta vs. git HEAD, test references, recoverability, destructive patterns and dependents, and lists what it could not measure. |

## Found in this audit (not on the earlier list)

| Defect | Impact | Status |
| :--- | :--- | :--- |
| `capacity.py` parsed flat key names, not Claude Code's nested `utilization.five_hour / seven_day / limits[]` | Every profile with real data reported "unreadable"; free-account failover could never choose anything | **Fixed** |
| `cc -r` rewritten into an effort flag | Broke Claude Code's `--resume` | **Fixed** |
| Removing a synced profile could follow a link/junction | Could delete the user's shared projects | **Fixed** (links detached first; refuses if it cannot) |
| `_link` fell back to an *empty directory* | "Synced" mode silently synced nothing on Windows without symlink rights | **Fixed** (junctions) |
| Corrupt `providers.json` -> defaults -> next save overwrote it | One bad byte destroyed every stored API key | **Fixed** |
| `providers.json` "0600" is a no-op on Windows | API keys kept the folder's default ACL | **Fixed** (owner-only ACL via `icacls`) |
| `install.py` treated an unparseable Desktop config as empty and rewrote it | Wiped the user's other MCP servers/settings | **Fixed** |
| `file_lock` (earlier draft) never broke a stale lock | One crash blocked every later write for 10 s, then raised | **Fixed** |
| Pre-tool guard: `\btree\b` matched `git ls-tree`, `cargo tree`, `src/tree/`; `Bash` matcher only | False blocks; PowerShell unguarded; relative paths resolved against the wrong cwd | **Fixed** |
| `/cc login`, `/cc continue` ran inside the prompt hook | Hung until the 120 s timeout | **Fixed** |
| Non-UTF-8 console / `text=True` decoding in hook and test runner | Hook failed open (prompt sent to the model); runner crashed | **Fixed** |
| `run_all_tests.py` printed fixed latencies and PASS regardless of results | Fabricated evidence, including a "0600 PASS" on a failing run | **Fixed** (measured values only) |
| 4 stale test modules; 14 of 33 tests failing at baseline | Suite could not be trusted | **Fixed** (now 100 tests, 99 pass, 1 platform skip) |
| `install.sh`, `uninstall.sh`, `launcher.py`... had CRLF in the working tree | `install.sh` fails on Linux/macOS (`$'\r': command not found`) | **Fixed**; a test guards it |
| `cc model` footer advised a command that does not exist | Dead advice | **Fixed** |

## Known and not changed

- The hook commands in `config/settings.json` call `python3`, which may not exist
  on a Windows machine. Not verified on a clean Windows install; `cc doctor` does
  not check it yet.
- `install.py` sets `claudeCode.claudeProcessWrapper`, while the README recommends
  environment variables and warns that a wrapper disables permission-mode
  resolution. The two installers disagree with the documented approach.
- Version strings disagree: `install.sh` says 1.2.0, `cortex` says 2.0.0, releases
  are 1.1.0.
- `fix_batch_1.py` .. `fix_batch_4.py` are one-shot patch scripts from the earlier
  session. Re-running them would duplicate the code they injected. Safe to delete.
