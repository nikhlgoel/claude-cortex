# Changelog

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
