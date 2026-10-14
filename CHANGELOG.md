# Changelog

## Unreleased

### Fixed - `install.exe` and `bin/claude.exe` did not work (shipped broken in 2.1.0)

- Double-clicking the 2.1.0 `install.exe` printed `& : The term 'C' is not recognized...`. The old stub
  pasted a UTF-16 path into a PowerShell command with `printf("%s")`, which prints one character - so it
  asked PowerShell to run a program called `C`. It also hung when started from a script. No test ever ran
  the `.exe` files; that is how it shipped.
- Both are rebuilt from source that is now in the repository (`native/launcher.c`, built by
  `scripts/build-launchers.py`, reproducibly). They start no shell at all: Python is found and started
  directly, with arguments quoted by the Windows rules, so a path or argument with spaces, `& ( ) ' % ^ !`
  or accents arrives intact whatever started them (double-click, cmd, PowerShell, Git Bash, a script).
  Double-clicked, the window waits for Enter so a message can be read; from a terminal it never waits.
- New tests start every launcher (`.exe`, `.cmd`, `.ps1`, `.sh`) from a folder named
  `we ird & (name) 'q' 100%x% ^ !g! ünï` and check the arguments and exit code come through unchanged. A test
  also fails if the committed `.exe` files stop matching `native/launcher.c`.
- `install.sh` run by Git Bash with a Windows path (`bash C:\x\install.sh`) used the current folder
  instead of its own.
- `CORTEX_HOME` meant "where the Cortex code is" to the shims but "where the data is" to the new palace;
  the palace now uses its own `CORTEX_DATA_DIR`.

### Added - the project map and floating button (`cc graph`, see docs/ATLAS.md)

- **A floating button** that appears while a Claude session is open in a project with a Graphify graph or
  a palace; click to open the map in its own window, click again to close it. Drag it, right-click it,
  hover for a summary; a badge counts notes whose code changed. `cc graph button off` removes it.
- **The map**: the project's files as a force-directed graph grouped by Graphify's areas, with the palace's
  notes pinned to the files they are about (green = code unchanged, amber = code changed since, red = code
  gone), functions on demand, search, and a side panel. Local, read-only, no network.
- A session hook (`SessionStart`, `SessionEnd`, `Stop`) feeds the button and does the two jobs below.

### Added - keeping Graphify, the palace and the context window honest (docs/CONTEXT.md)

- **After a compaction or `/clear` the palace may show memory again** (and the always-on core). It used to
  keep refusing to repeat anything it had shown earlier in the session, even after that text had been
  summarised away.
- **`cc palace verify`** and the **`verify_refs`** MCP tool check the files and `backticked` names in a
  piece of text against the project and its code graph: a wrong name is reported with the closest real one
  ("did you mean `cortex/guard.py`"); library code and generic words are never called wrong.
- **`cc palace ground on`** (off by default) makes that check automatic on Claude's final answer, once.

### Fixed - found by the new tests

- The Graphify bridge did not resolve methods: Graphify writes them as `.name()` and the leading dot stayed.
  Existing caches rebuild on first use.
- The map's local server could share its port with another program on Windows (`SO_REUSEADDR`); the bind
  is now exclusive.

### Added - the layered memory palace (`cortex/palace`, see docs/PALACE.md)

- **`cc palace init`**: one command, no questions - creates the project's palace, imports an old (v2.5)
  one without touching it, links a Graphify graph if present.
- **Layers, not a pile**: scratch / core / episodic / semantic / procedural / archive tiers; every memory
  has a kind, trust, importance, confidence, validity dates and three sizes (headline, gist, full).
- **Facts keep their history**: a same-titled decision replaces the old one, which is kept, dated and linked.
  (The old palace discarded "pool size 10 -> 50 after the outage" as a duplicate.)
- **Graphify integration** (read-only, optional): memories are anchored to files/symbols; memories about
  neighbouring code rank up; a memory whose code changed is flagged and demoted.
- **Automatic, careful delivery**: the prompt hook adds relevant memory (never repeated within a session, never
  for commands, silent when evidence is thin, off with `CORTEX_PALACE=off` or `cc palace inject off`).
- **Measured**: `cc palace eval` scores retrieval on paraphrased questions, knowledge updates and prompts that
  must get nothing, against the old scorer: false injection 0% vs 76%, changed facts 100% vs 0%.
- MCP tools `remember` / `recall_memory` use the new engine (`kind`, `files`, `supersedes`, `project_dir`).

### Changed

- `scripts/claude-palace.py` is now legacy (the import source and the baseline); `cc palace`, the MCP tools,
  the slash commands and the hook no longer use it.

## 2.1.0

Your own accounts first: adopt the Claude folders you already have, use them from the
terminal, IDE extensions and Claude Desktop, and test the installer without risking them.

### Added

- **Adopt existing accounts in place** (`cc profile detect | adopt | surfaces | verify`).
  Folders are registered at their exact existing path and are never moved, copied, edited,
  repaired or deleted; `remove` only unregisters.
- **Surfaces** - terminal, IDE extensions, Claude Desktop - chosen at install time
  (`--surfaces`) or added later, all on the same account data. `cc desktop <name>` opens
  Claude Desktop on a profile's own data folder.
- **`cc guard snapshot | verify`** - proves a change touched no settings, configs or
  credentials, including the account, MCP servers and onboarding state in `~/.claude.json`.
- **Automatic tool routing** - one short hint per prompt toward Scrapling, Graphify, Spec Kit
  or ECC when (and only when) the tool is installed and the prompt clearly calls for it.
  Measured: 0 false positives on a 91-prompt quiet corpus. `CORTEX_ROUTING=off` disables it.
- **`cc mcp add graphify | scrapling`** - registered through `claude mcp add`, never by
  editing `.claude.json` behind Claude Code's back.
- **Local models** (`cc local ...`, `cc offline`) - Hugging Face GGUFs on llama.cpp behind the
  Cortex gateway, with a consent gate, resumable verified downloads, hardware-aware planning,
  per-level reasoning budgets, and sleep/wake of the model when idle.
- Installer launchers (`install.sh`, `install.ps1`, `install.cmd`) now share one tested
  implementation, `install.py`, and run in a throwaway home for safe testing.

### Fixed

- **The default account lost its MCP servers.** With `CLAUDE_CONFIG_DIR` unset Claude Code uses
  `~/.claude.json`; with it set, even to `~/.claude`, it uses a different file. Cortex now
  leaves the variable unset for the default folder (launcher, IDE settings, doctor, capacity).
- `cc ide apply` replaced all of a person's `claudeCode.environmentVariables`; it now changes
  only Cortex's own entries.
- `cc mcp add` rewrote `.claude.json` directly; it now goes through `claude mcp`.
- `install.ps1` overwrote top-level settings keys (hooks, permissions), rewrote IDE
  `settings.json` through a JSON round-trip that drops comments, and created
  `Claude-profile-1/2` folders unasked. It is now a launcher for `install.py`.
- The installer **downloaded and installed an executable** from a hard-coded URL with no
  checksum when Claude Code was not found (a 404 today, and a network request in every test
  run). Removed: it explains how to install Claude Code instead.
- Declining the installer's prompt exited 0, so a wrapper reported success; it exits 3 now.
  Unrecognised options are refused (exit 2) instead of silently ignored.
- `install.cmd` hung for ~30 s at the end of every automated run (an unconditional `pause`).
- The gateway exited when idle and left a dead local session; it now stays up and wakes the
  model on demand. Client disconnects no longer log tracebacks, and unread request bodies no
  longer cause connection resets on Windows.
- Download edge cases: a 416 reply or an already-complete partial file was a dead end; finished
  shards were fetched again; Ctrl-C printed a traceback.
- `llama-server` flags that a given build does not know no longer stop the model from starting.
- Two Python files were CRLF in an LF project.

### Known limits (stated, not hidden)

- The Desktop app's Code tab honouring `CLAUDE_CONFIG_DIR` is unverified.
- A real `llama-server` + model + Claude Code session has not been run by the author;
  tokens/second is unmeasured until `cc local doctor --smoke`.
- `install.exe` and `bin/claude.exe` are small prebuilt launcher stubs with no source in this
  repository; they only call the scripts next to them. Prefer `install.cmd` or `install.py`.

## 2.0.0

A correctness release. The previous version had a working shape but several
defects that made it unusable in practice, and a few features that did less than
they claimed. Both are addressed.

### Fixed - sessions

- **Compaction loop.** `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=0.45` lowered the
  compaction threshold to a fraction of the window, and `autoCompactWindow` was
  set to `85000` - below the CLI's documented 100k floor. Sessions compacted at
  roughly 38k tokens, immediately and then repeatedly. Both settings are gone;
  the per-model default applies. Setting the environment variable also locked the
  value out of `/config`, so removing it restores that control.
- The launcher now strips inherited compaction overrides, so a stale export in a
  shell profile cannot reintroduce the loop.
- Removed `COMPACT_CONTEXT_THRESHOLD` and `COMPACT_CONTEXT_INTERVAL`, which
  Claude Code does not read.
- `bashOutputMaxChars` is no longer pinned to `6000` against a default of
  `30000`. Truncating output that aggressively caused commands to be re-run,
  costing more tokens than it saved.

### Fixed - authentication

- **Signing in did not persist.** Onboarding is driven by
  `hasCompletedOnboarding` in the profile's `.claude.json`, which was never
  written, so every launch re-ran the theme picker and login prompt. Identity is
  now seeded from `claude auth status` after login.
- **Credentials were namespaced by path spelling.** Claude Code derives the
  credential namespace from `sha256` of the config-directory *string*, normalized
  NFC and nothing else. Git Bash (`/c/Users/...`) and PowerShell
  (`C:\Users\...`) produced different strings for the same directory, so a
  profile signed in from one shell appeared signed out in the other. All paths
  now come from a single canonicalizer.
- Authentication is checked with `claude auth status` rather than by looking for
  `.credentials.json`. That file is not authoritative - on Windows credentials
  can live in Credential Manager. Note the CLI exits 0 whether or not you are
  signed in, so the `loggedIn` field is read, not the exit code.
- "Failed to load usage data" shared the same root cause and is fixed with it.

### Fixed - safety

- **The uninstaller removed Claude Code itself**: `~/.local/share/claude`, IDE
  extensions, `~/.config/Claude`, `~/.claude.json`, and all of `~/.claude`. It
  now removes only files Cortex installed, defaults to a dry run, and requires
  `--yes`. It also deletes a `NoDisplay=true` launcher file the old version left
  behind, which had been hiding Claude Desktop from the application menu.
- **`cc update` could re-break the installation.** It piped a remote script into
  a shell (`curl … | bash`) and re-ran `install.sh`. It now uses the CLI's own
  `claude update` and never re-runs the installer.
- **The installer relocated the official binary**, leaving shims pointing at a
  path that no longer existed. It no longer moves it, and restores one a previous
  version moved aside.
- All installers require explicit confirmation, support `--dry-run`, and refuse
  to run non-interactively without `--yes` or `CORTEX_SANDBOX=1`.
- Removed the silent `npm install -g`.

### Fixed - commands

- **Ordinary prompts were being erased.** The `UserPromptSubmit` hook matched
  bare keywords, and exit code 2 on that event blocks *and erases* the prompt.
  "switch to the new API client", "test this function", and "claude keeps
  crashing" never reached the model. Interception now requires an explicit
  `/cc` or `!cc` prefix.
- **Twelve legacy subcommands were sent to Claude as prompts.** `cc docs`,
  `cc palace`, `cc menu` and others fell through to the session launcher,
  starting a real API session to answer the command word. Commands now dispatch
  to their tools, retired commands explain their replacement, and an unrecognized
  command is refused rather than becoming a prompt. Use `cc -- <text>` to send
  something that looks like a command.
- A profile can no longer be created with a name that shadows a command, since
  such a profile would be unreachable.
- Hook configuration corrected: `UserPromptSubmit` does not support `matcher`,
  and `PreCompact` filters on `manual|auto`.
- `-h` is no longer bound to `--haiku` ahead of `--help`; Haiku is `-H`.
- Turbo uses the documented `--effort low` rather than the undocumented
  `--thinking disabled`.

### Fixed - platform

- **`bin/claude` shipped with CRLF line endings** and could not execute on Linux
  at all. Added `.gitattributes` enforcing LF and normalized the tree.
- The 1223-line bash wrapper and 565-line PowerShell wrapper - which had drifted
  into different products, the latter missing login, profile management, and
  diagnostics entirely - are replaced by one Python core with ~50-line shims.
- Sessions are launched with `execve` on POSIX so signal and terminal-resize
  handling are the CLI's own.

### Changed

- **Capacity: unknown is no longer reported as free.** A profile with no usage
  cache was reported as "100% capacity free" and scored best, so failover could
  route to an exhausted account. Unknown is reported as unknown and never
  auto-selected.
- **Always-on prompt reduced from 719 to 105 lines.** The old ruleset
  contradicted itself - mandating a header card while banning preambles, and
  mandating a closing question while banning concluding fluff. Terse wins.
  Six domain rulesets became on-demand Skills. Removed rules referencing
  `C:\Claude\Tools` paths that do not exist and MCP tools that are not installed.
- IDE integration uses `claudeCode.environmentVariables` and modifies no
  extension files, so Anthropic's updates cannot break it. `cortex-ide-wrapper`
  now implements the extension's real calling convention
  (`wrapper <real-binary> [args...]`); the previous wrapper treated the binary
  path as a subcommand and would have broken the extension.
- Added `cc doctor [--repair]` and `cc ide check|apply`.

### Documentation honesty

- `cc dream` and `cc think` are relabelled as what they are: fixed checklists
  with no model calls. `dream` produces identical output for any topic; `think`
  varies only by the echoed prompt. `/dream` now directs the analysis to Claude
  with a quality bar requiring a named file and mechanism.
- Audited the rest rather than assuming: `cc research` genuinely queries the
  arXiv API and returns real papers, and `cc palace` genuinely stores,
  tag-indexes, and retrieves. Both are documented as working.
- `cc model` pricing is labelled a static snapshot.
- `cc status` is described as reading Claude Code's local cache, not a usage API.
- README carries an explicit "Honest limitations" section.

### Testing

- Replaced the suite, which asserted that bare keywords *must* be intercepted -
  certifying the prompt-erasure bug - and read and wrote the live `~/.claude`.
  It now refuses to run outside a sandbox.
- Added a container harness: Fedora, Ubuntu, and a PowerShell-enabled image, a
  stub binary that mirrors verified CLI behavior, and a filesystem leak check
  that fails on any undeclared change. 32 scenarios, 128 assertions.
- Windows parity is executed rather than assumed: the PowerShell shim is run
  under `pwsh` and asserted to resolve a config directory identical to bash.
