# Claude Cortex (`cc`)

Multi-account profile manager and launcher for [Claude Code](https://claude.ai/code).

Run several Claude accounts side by side with fully isolated credentials, switch
between them, and keep IDE and terminal sessions on the same profile.

---

## What it does

- **Multi-account profiles.** Each profile is an isolated `CLAUDE_CONFIG_DIR`
  with its own credentials, quota, and session history. `cc -work`, `cc -personal`.
- **Shared project context.** In *synced* mode profiles share projects, skills,
  commands, and rules; only credentials and usage are separate.
- **Consistent identity across entry points.** Terminal, PowerShell, and IDE
  sessions all resolve the same canonical config-dir string, so they share one
  credential namespace. This matters more than it sounds - see *Why paths matter*.
- **Capacity reporting.** `cc status` shows per-account usage where Claude Code
  has recorded it, and says *unknown* where it has not.
- **Diagnostics.** `cc doctor` explains why a setup is misbehaving and
  `--repair` fixes the unambiguous cases.
- **IDE integration.** Configures VS Code, Antigravity, Cursor, Windsurf, and
  VSCodium to launch under a chosen profile, without modifying the extension.
- **Lifecycle hooks.** Guards against tool calls that dump huge output into
  context, and preserves architectural context across compaction.
- **On-demand Skills.** Domain guidance (C++, algorithms, design, architecture,
  hardware) loads when relevant instead of on every request.
- **Isolated binary analysis.** Ghidra, audited and run with no network route out
  (`cc ghidra`). See [the audit](tools/ghidra/AUDIT.md).

## Requirements

- Claude Code installed ([claude.ai/download](https://claude.ai/download))
- Python 3.8+
- bash or zsh (Linux/macOS), PowerShell (Windows)

## Install

```bash
./install.sh --dry-run    # see exactly what it will change
./install.sh              # asks for confirmation before touching anything
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The installer will not run non-interactively without `--yes` or
`CORTEX_SANDBOX=1`, because it replaces the `claude` command on your PATH and
writes lifecycle hooks. It never moves or deletes your official Claude Code
installation.

## Usage

```bash
cc                          # launch the active profile
cc -work                    # launch a specific profile
cc profile add work         # create a profile
cc profile remove work      # delete it (asks first; scripts must pass --yes)
cc login work               # sign in
cc switch work              # change the active profile
cc status                   # account capacity
cc continue                 # resume the last conversation
cc doctor                   # diagnose problems
cc doctor --repair          # fix the unambiguous ones

cc -s | -o | -H             # Sonnet 5 | Opus 5 | Haiku 4.5
cc --opus-5-5               # Opus 5.5   (also -o55)
cc --sonnet-5-5             # Sonnet 5.5
cc --fable                  # Fable 5.1  (--fable-5 for the previous one)
cc -e high                  # reasoning effort: low medium high xhigh max
cc -t                       # turbo: Haiku at low effort
cc -y                       # skip permission prompts
cc -- <prompt>              # send a prompt even if it looks like a command
```

Tools:

```bash
cc palace | remember | recall    # memory palace (stores and retrieves)
cc model | provider | update     # live model catalog, API providers, updates
cc research <topic>              # live arXiv retrieval (real)
cc analyze <path>                # static risk analysis of source (file, line, mechanism)
cc mcp add                       # expose Cortex's tools to Claude (incl. evaluate_impact)
/dream <concept>                 # in a session: research-backed concept explorer
```

Local models (Claude Code on a model running on this machine - see
[docs/LOCAL_MODELS.md](docs/LOCAL_MODELS.md)):

```bash
cc local status                  # hardware, runtime, which models fit
cc local install --runtime       # llama.cpp - asks first, shows size + sha256
cc local install qwen3.5-4b      # a Hugging Face GGUF - asks first, resumable, verified
cc local doctor --smoke          # checks every link and MEASURES your speed
cc offline                       # Claude Code against the local model
```

An unrecognized command is refused with a suggestion rather than being sent to
Claude as a prompt. An earlier version forwarded twelve legacy subcommands
(`docs`, `menu`, `palace`, ...) straight into a session, spending tokens to
answer the command word.

In-session, Cortex commands use an explicit `/cc` prefix:

```
/cc status
/cc switch work
```

Only that prefix is intercepted. Ordinary prompts containing words like
"switch", "test", or "continue" are never treated as commands.

## IDE integration

```bash
cc ide check          # report what is installed and what would change
cc ide apply          # dry run
cc ide apply --yes    # write the settings
```

This sets `claudeCode.environmentVariables` so the extension launches under your
chosen profile. **No extension files are modified**, so Anthropic's updates never
break it.

Cortex also ships `cortex-ide-wrapper` for the `claudeCode.claudeProcessWrapper`
setting, which correctly implements the extension's calling convention
(`wrapper <real-binary> [args...]`). Prefer environment variables: setting a
process wrapper disables the extension's permission-mode resolution and its
`CLAUDE_CONFIG_DIR` watching.

## Why paths matter

Claude Code namespaces stored credentials by a hash of the config-directory
*string*, normalized NFC and nothing else. These are three different accounts:

```
C:\Users\me\.claude-profiles\main
/c/Users/me/.claude-profiles/main
C:/Users/me/.claude-profiles/main/
```

Git Bash and PowerShell naturally produce different spellings for the same
directory, which is why a profile could be signed in from one shell and appear
signed out from the other. Cortex derives every config-dir string from a single
canonicalizer so all entry points agree.

## Uninstall

```bash
./uninstall.sh                        # dry run
./uninstall.sh --yes                  # remove Cortex
./uninstall.sh --yes --purge-profiles # also remove saved logins
```

It removes only files Cortex installed. Your official Claude Code binary, IDE
extensions, Claude Desktop, `~/.claude.json`, and your own `~/.claude` content
are left alone.

## Testing

All testing runs in containers; nothing touches a real installation.

```bash
make sandbox          # full suite on Fedora
make sandbox-ubuntu   # full suite on Ubuntu
make sandbox-pwsh     # adds PowerShell, so the Windows shim is executed
make sandbox-all      # every scenario on every image
make sandbox-list     # available scenarios
```

The Python unit and integration suite (`tests/`) can also run directly. It
refuses to start unless it is sandboxed, because some tests exercise paths under
`~/.claude`; point `HOME` at a throwaway directory:

```bash
CORTEX_SANDBOX=1 HOME="$(mktemp -d)" python tests/run_all_tests.py
```

The report it writes lists only what was measured: tests run, failures with their
reasons, and duration. Millisecond budgets are scaled up on Windows (override with
`CORTEX_TEST_LATENCY_SCALE`), since process creation there is several times slower.

Windows parity is executed, not assumed: the PowerShell shim runs under `pwsh`
and is asserted to resolve a config directory byte-identical to bash. That is
the property the credential-namespace bug turned on.

Every scenario ends with a filesystem leak check that fails on any change it did
not declare. See [tests/sandbox/README.md](tests/sandbox/README.md).

## Honest limitations

- **`dream` is not a terminal command.** Exploring a concept needs a model, so it
  lives in a session (`/dream <concept>`); the terminal refuses it and says so.
  `think` was removed rather than left pretending to analyze. The terminal-side
  code analyzer is `cc analyze`, which is real but pattern/AST-based: it finds the
  failure classes it knows, not everything.
- **`evaluate_impact` is a heuristic, not a verdict.** It scores one file from
  measurable signals (complexity change vs. git HEAD, whether tests reference it,
  whether a committed copy exists, destructive patterns, dependents). It reports
  what it could not measure instead of guessing, and does not replace running tests.

### What is real, audited rather than assumed

| Feature | Verdict |
| :--- | :--- |
| `cc research` | **Real** - queries the arXiv API, returns actual papers |
| `cc palace` / `remember` / `recall` | **Real** - stores, tag-indexes, retrieves |
| `cc provider` | **Real** - key file is owner-only (0600; ACL-restricted on Windows), masked in output |
| Cortex gateway | **Real** - serves HTTP, binds loopback only, retries transient upstream errors |
| `cc analyze` | **Real** - AST + shell analysis; limited to the failure classes it knows |
| `cc model` | **Real** - live OpenRouter catalog with real pricing; cached, labelled when stale |
| `evaluate_impact` | Heuristic risk score; unmeasurable inputs are listed, never invented |
- **Claude's own models carry no per-token price in `cc model`.** On a subscription
  there isn't one that means anything; OpenRouter models show real $/1M-token
  prices, cached for six hours.
- **`cc status` reports what Claude Code has cached locally.** It does not query
  a usage API. Profiles with no recorded usage show *unknown*, and `cc continue`
  will not auto-select them - missing data is not evidence of free capacity.
- **Antigravity integration cannot be tested in CI** (Windows-only app). Its
  settings are generated and statically validated; verify by launching it.
- **Local models are tested with fakes, not yet with a real model.** The consent gate,
  downloads, gateway shaping and process handling are covered by tests; a real
  `llama-server` + model + Claude Code session has not been run by the code's author, and
  tokens/second on your machine is unknown until `cc local doctor --smoke` measures it.
  Small local models are far weaker than Claude at long agent runs, and Anthropic does not
  support non-Claude models behind a gateway.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - how it works, what it cannot do, next steps
- [Local models](docs/LOCAL_MODELS.md) - Hugging Face GGUFs, llama.cpp, reasoning levels
- [Framework options](docs/FRAMEWORK_OPTIONS.md) - five directions for what Cortex becomes
- [Handover](HANDOVER.md) - installing it yourself, with verification steps
- [Ghidra audit](tools/ghidra/AUDIT.md) - supply-chain findings and residual risk
- [Test harness](tests/sandbox/README.md) - scenarios, fuzzing, mutation testing

## Layout

```
bin/                Thin shims (bash / PowerShell / cmd) + IDE wrappers
cortex/             The implementation - one core, shared by all platforms
config/
  CLAUDE.md         Global instructions (entry point, precedence)
  rules/00-core.md  The only always-on rule
  commands/         Slash commands
  settings.json     Hooks and defaults
scripts/            Hooks and standalone tools
skills/             On-demand domain guidance
tools/ghidra/       Audited, network-isolated binary analysis
docs/               Architecture and design notes
tests/sandbox/      Container test harness
```
