# Handover - installing Claude Cortex on your machine

Everything below was developed and verified inside containers. **Nothing has been
installed on your system.** This document is what you follow when you decide to
install it yourself.

Read the *Before you start* section first. It includes one thing you need to fix
by hand.

---

## Before you start

### 1. Your Windows `claude` command is currently broken

An earlier version of this repository's installer moved the official binary aside
and left `~/.local/bin/claude.real` pointing at an npm path that no longer
exists:

```
$ claude --help
claude.real: line 12: .../claude-code/bin/claude.exe: No such file or directory
```

This is pre-existing and unrelated to the new code. Two ways to fix it:

**Option A - let Cortex find a working binary** (it resolves IDE-bundled binaries
as a last resort):

```bash
cc doctor
```

**Option B - repair it directly.** Check whether the old installer left a backup:

```bash
ls "$LOCALAPPDATA/Programs/claude/claude.exe.bak"
```

If present, restore it:

```bash
mv "$LOCALAPPDATA/Programs/claude/claude.exe.bak" "$LOCALAPPDATA/Programs/claude/claude.exe"
```

Otherwise reinstall Claude Code from <https://claude.ai/download>. The new
`install.ps1` restores such a backup automatically and never moves the binary
again.

### 2. Close the session you are working in

Installing replaces the `claude` command on your PATH. Do not install from
inside a Claude Code session you care about.

### 3. Back up (optional but cheap)

```bash
cp -r ~/.claude ~/.claude.backup-$(date +%F)
cp ~/.claude.json ~/.claude.json.backup-$(date +%F)
```

---

## Install

### Step 1 - see what it will do

```bash
cd /path/to/cc
./install.sh --dry-run
```

This prints every path it would write and exits. It changes nothing.

### Step 2 - install

```bash
./install.sh
```

You will be asked to type `INSTALL`. The installer will not proceed
non-interactively without `--yes`.

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### Step 3 - verify

```bash
cc doctor
```

Expect: a working binary, a valid `autoCompactWindow` (or none), and no
profile warnings. Then:

```bash
cc profile add main
cc login main
cc status
```

### Step 4 - confirm the fix that mattered most

Launch a session and give it a real task:

```bash
cc
```

It should **not** compact at startup, and should not compact again a few tool
calls later. That symptom was caused by `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=0.45`
combined with an invalid 85000 window; both are gone.

Then exit and relaunch:

```bash
cc -main
```

It should go straight to a session - no theme picker, no login prompt. That was
the re-login bug.

---

## IDE integration

```bash
cc ide check
```

Reports which IDEs have the Claude Code extension, where their settings live,
and what would change. It writes nothing.

```bash
cc ide apply           # dry run
cc ide apply --yes     # write
```

This sets `claudeCode.environmentVariables` so the extension launches under your
profile. **No extension files are modified.** Your themes, keybindings, and other
settings are preserved; a `.bak` is written before any change.

### Verify per IDE

**VS Code** - restart, open the Claude panel, run `/status`. The config directory
should be your profile path, and the account should match `cc status`.

**Antigravity** - same check. This one could not be covered by automated tests
(Windows-only app), so it is worth doing deliberately.

One thing `cc ide check` will flag: you have **two** Claude Code extension
versions in VS Code (2.1.269 and 2.1.273). Each bundles its own binary and
settings apply to whichever loads. Remove the older one from the Extensions view.

---

## If something goes wrong

```bash
cc doctor --repair
```

Repairs only unambiguous, reversible problems: an out-of-range
`autoCompactWindow`, unseeded profile onboarding, and a linked `settings.json`
converted back to a real file. Every write is backed up.

### Full uninstall

```bash
./uninstall.sh                        # dry run - shows what would go
./uninstall.sh --yes
./uninstall.sh --yes --purge-profiles # also removes saved logins
```

It removes only files Cortex installed. It will **not** touch your official
Claude Code binary, IDE extensions, Claude Desktop, `~/.claude.json`, or your own
`~/.claude` content. The previous version of this script deleted all of those -
that is fixed, and the uninstaller now also removes a launcher-masking file the
old one left behind.

---

## What changed, and why

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| Compacts immediately and repeatedly | `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=0.45` + `autoCompactWindow: 85000` (below the CLI's 100k floor) | Both removed; the CLI default applies and `/config` is controllable again |
| Asks to log in after logging in | Onboarding state never seeded; credentials namespaced by `sha256(config-dir string)`, and Git Bash vs PowerShell produced different strings | Identity seeded from `auth status`; every path canonicalized by one function |
| "Failed to load usage data" | Same root cause - profile had no `oauthAccount`, so no account context | Fixed by the seeding above |
| Ordinary prompts vanished | Hook intercepted bare keywords; exit 2 on `UserPromptSubmit` erases the prompt | Explicit `/cc` prefix only |
| `cc continue` picked exhausted accounts | Missing usage cache reported as "100% capacity free" | Unknown reported as unknown and never auto-selected |
| Windows missing most commands | PowerShell wrapper was a separate 565-line reimplementation | One Python core; shells are ~40-line shims |
| Uninstall removed Claude Code itself | `rm -rf ~/.local/share/claude`, IDE extensions, `~/.config/Claude` | Scoped to Cortex artifacts; dry-run by default |
| `cc update` could re-break the install | `curl … | bash` plus an `install.sh` re-entry | Uses the CLI's own `claude update`; never re-runs the installer |
| Wrapper unusable on Linux | `bin/claude` shipped with CRLF endings | `.gitattributes` enforces LF; files normalized |
| 655 lines of contradictory always-on rules | Mandated a header card while banning preambles, etc. | 105 lines total; domain rules became on-demand Skills |
| `cc docs`, `cc palace` etc. started a real session | Legacy subcommands fell through to the launcher and became the prompt | Commands dispatch to tools; unknown commands are refused, not forwarded |
| Windows installers produced a broken install | `install.ps1` and `install.py` never copied the core | All three installers deploy it; covered by a test |
| Two capacity implementations disagreed | The standalone script still called unknown capacity "100% free" | It now delegates to the core |

## Known limitations

- `cc dream` and `cc think` print fixed checklists. They do no analysis.
  (`cc research` and `cc palace`, by contrast, are real - arXiv retrieval and
  tag-indexed storage respectively.)
- `cc model` pricing is a static snapshot.
- `cc status` reads Claude Code's local cache, not a usage API.
- Antigravity integration is generated and statically validated, not CI-tested.

## Re-running the tests yourself

```bash
make sandbox          # Fedora
make sandbox-ubuntu   # Ubuntu
make sandbox-pwsh     # with PowerShell, to exercise the Windows shim
make sandbox-all      # everything
```

Both run entirely in containers and end with a leak check that fails on any
change outside the declared set.
