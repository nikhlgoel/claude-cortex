# Cortex Sandbox

A disposable container environment for testing the installer, wrapper, and hooks
without touching a real Claude Code installation.

## Why this exists

Cortex replaces the `claude` command, writes lifecycle hooks, and installs rules
that change model behavior. Testing any of that against a live installation risks
breaking the tool being used to do the work. Every failure mode we care about
(clobbered config, a wrapper pointing at a missing binary, a uninstaller removing
the official product) is silent at the time and only surfaces much later.

So: all testing happens in a container, and every scenario ends with a filesystem
leak check that fails on any change it did not declare.

## Running

```bash
make sandbox             # all scenarios on Fedora
make sandbox-ubuntu      # all scenarios on Ubuntu
make sandbox-pwsh        # adds PowerShell, exercising the Windows shim
make sandbox-all         # every scenario on every image
make sandbox-list        # list available scenarios
make sandbox-scenario S=install-dryrun
make sandbox-shell       # interactive shell inside the sandbox
```

32 scenarios, 128 assertions. Each reproduces a failure that actually happened
rather than testing a function in isolation - the previous suite passed while
the product was unusable, and in two places asserted the buggy behavior was
correct.

The repository is mounted **read-only** at `/repo` and copied to `/work`, so a
scenario cannot modify the source tree.

## Components

| File | Purpose |
| :--- | :--- |
| `Dockerfile` | Parameterized by `BASE_IMAGE`; Fedora and Ubuntu share one definition |
| `entrypoint.sh` | Prepares the environment, runs one scenario, verifies no leak |
| `stub-claude.py` | Stands in for the real `claude` binary |
| `leak_check.py` | Content-hash snapshot/compare of a directory tree |
| `scenarios.sh` | The scenarios themselves |

### The stub binary

`stub-claude.py` is installed as `~/.local/bin/claude.real` — the path the Cortex
wrapper execs. It records every invocation to `$CORTEX_STUB_LOG` as JSONL
(`argv`, `cwd`, and the tracked environment), so tests assert on exactly what the
wrapper produced rather than inferring it from side effects.

It mirrors behaviors verified against the real CLI (2.1.273):

- `--autocompact` accepts `auto` or 100k–1M only. This is what catches a
  regression reintroducing the invalid `85000` window.
- `auth status` prints JSON and **exits 0 even when logged out** — callers must
  read the `loggedIn` field, never the exit code.
- `auth status` creates `.claude.json` in the config dir as a side effect.
- Unknown options are rejected, the way commander does.

Control it with `CORTEX_STUB_VERSION`, `CORTEX_STUB_EMAIL`, and
`CORTEX_STUB_LOGGED_IN=0|1` to force an auth state.

### The leak check

`leak_check.py` snapshots `$HOME` by content hash before a scenario and compares
afterwards. Anything added, removed, or modified outside the scenario's
allowlist fails the run. Self-churning paths (`.cache`, `shell-snapshots`,
`session-env`, `__pycache__`) are ignored.

```bash
leak_check.py snapshot $HOME snap.json
leak_check.py compare  $HOME snap.json --allow '.claude/scripts/**'
```

## Line endings

`.gitattributes` forces LF on `*.sh`, `*.py`, `bin/claude`, and completions. A
bash script with CRLF endings does not run on Linux — every line fails with
`$'\r': command not found`, an error that looks nothing like its cause. The
entrypoint also strips CR defensively after copying, so a Windows editor
reintroducing CRLF cannot fail a run for an unrelated reason.

## Adding a scenario

Add a `scenario_<name>()` function in `entrypoint.sh`, register it in the
`case` dispatch and in `scenario_list`, and use the helpers:

- `snapshot_home` before the action
- `verify_no_leak [allow-globs...]` after it
- `pass` / `fail` for assertions (failures set the exit code)
- `stub_calls` to read back recorded invocations

A scenario that installs files must declare them:

```bash
verify_no_leak '.claude/**' '.local/bin/**' '.claude-profiles/**'
```
