# Profiles, surfaces and testing safely on your own machine

Cortex lets you use several Claude accounts from the terminal, IDE extensions and Claude
Desktop, with the same account, chats and sessions everywhere. This page explains how, and
how to install and test it **without risking the accounts you already have**.

## The model

* A **profile** is a name for one account.
* A **surface** is a way of launching it: `terminal`, `ide`, or `desktop`.
* Your existing accounts are **adopted in place**. Cortex remembers where their folders
  already are; it never moves, copies or edits them. Their logins, chats and history stay
  byte-for-byte as they are.

On a typical machine that means three Desktop folders (the default one, plus any made by a
multi-profile tool) and one or two folders that also hold a Claude Code login:

```
cc profile detect          # read-only: finds them and prints the exact adopt commands
cc profile adopt studio --desktop "C:\Claude\Profiles\Studio"
cc profile adopt veilabs --desktop "C:\Claude\Profiles\Veilabs" --config "C:\Claude\Profiles\Veilabs"
cc profile adopt default --desktop "%APPDATA%\Claude" --config "%USERPROFILE%\.claude"
cc profile verify veilabs  # is it still signed in? (changes nothing)
```

A profile with a Desktop folder but no terminal login (like `studio` above) is fine: sign it
in once for the terminal with `cc login studio`. That creates a normal Cortex-managed config
folder for the terminal, and the Desktop folder stays yours.

## Adding surfaces any time

```
cc profile surfaces studio                    # show where it is used
cc profile surfaces studio terminal,desktop   # add Desktop; chats/sessions are unchanged
cc profile surfaces studio terminal,ide,desktop --dry-run
cc desktop studio                             # open Claude Desktop on its own data folder
```

* **terminal** - `cc studio` or `cc -studio`.
* **ide** - the extensions take one profile at a time, so this is your choice:
  `cc ide check`, then `cc ide apply studio --yes`.
* **desktop** - registers the Cortex tools in the Desktop folders that already exist. It never
  creates a Desktop folder.

The installer asks the same question (or take it from `--surfaces terminal,ide,desktop`).

### What is and is not shared

Your **account** is the same everywhere, so claude.ai conversations are the same in every
surface automatically (they live on Anthropic's side). Claude **Code sessions** are local
files: they are shared between terminal and IDE because both use the profile's config
folder. Whether the Desktop app's own Code tab uses that same folder is **not verified** -
`cc desktop` passes the folder to it, and `--no-config-dir` opts out. Check it once: start
a Code session from the app and see whether it shows up in `cc` for that profile.

## One trap this design avoids

With `CLAUDE_CONFIG_DIR` **unset**, Claude Code keeps its user config (MCP servers, project
trust, onboarding) in `~/.claude.json`. With it set - even to `~/.claude` - it reads
`~/.claude/.claude.json` instead: a different file. So launching your default account with the
variable set silently loses its MCP servers. Cortex therefore leaves the variable **unset**
for the default folder and sets it for every other profile.

## What adoption guarantees

For an adopted folder, Cortex will not link shared items into it, copy settings into it,
rewrite its `.claude.json`, repair it (`cc doctor --repair` skips it) or delete it
(`cc profile remove` only unregisters). Registered paths are stored exactly as given, because
the login is tied to the exact path string; give them without a trailing slash.

## Installers

`install.sh`, `install.ps1` and `install.cmd` are thin launchers: each finds Python 3.8+ (or uses
`CORTEX_PYTHON`) and runs the one tested `install.py`, passing every option through and returning
its exit code (0 done, 2 unrecognised option, 3 stopped at the safety prompt). They never download
anything; if Claude Code is not installed they tell you how to install it.

## Testing safely when Claude is the thing being changed

You cannot reinstall Claude while it is running, and an installer that misbehaves could damage
the accounts you are using to run it. So test in layers, and let the machine prove each one:

1. **Tests run against a throwaway home.** `python tests/run_all_tests.py` refuses to run
   against your real home unless you declare a sandbox (`CORTEX_SANDBOX=1` plus a temp
   `HOME`/`USERPROFILE`). The installer tests run the *real installer* this way and assert
   your real Windows `PATH` registry value is unchanged.
2. **Dry run:** `python install.py --dry-run` prints what it would write and writes nothing.
3. **Take a snapshot, then do the risky thing, then verify.**
   ```
   cc guard snapshot before
   ... run the installer / a script / anything ...
   cc guard verify before
   ```
   It fails if any *protected* file (settings, configs, credentials, plugins, skills) was
   added, removed or changed - including your account, MCP servers and onboarding state in
   `~/.claude.json` (compared by what they say, not by timestamps, since Claude Code rewrites that
   file constantly). Normal activity (history, sessions, caches) is only summarised.
   Credential files are compared by size and time; their contents are never read. Close
   Claude Desktop first for a clean verdict - it rewrites its own config while running.
4. **For a stronger wall,** use a separate Windows user account or a virtual machine. (Windows
   11 Home has no Windows Sandbox; Docker only covers the Linux code paths.)
5. **The first real install** is the one you do after steps 1-3 passed:
   `python install.py --surfaces terminal` (add `desktop`/`ide` later), with a guard snapshot
   taken first.

The sandbox flag also makes the installer skip the registry `PATH` edit, because the registry
belongs to the real user whatever `HOME` says.
