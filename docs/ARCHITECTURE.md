# Claude Cortex — how it works

This is the document to read before changing anything. It covers the shape of the
system, the decisions that are load-bearing, what it genuinely cannot do, and
where it should go next.

---

## 1. What Cortex is

A **profile manager and launcher for Claude Code**. It does not replace Claude
Code, wrap its protocol, or proxy its API. It decides *which account and
configuration* a session runs under, then gets out of the way.

Everything else — the memory palace, the analysis tools, the hooks — is a
periphery around that core job.

```
  cc ─┬─ profiles ── which account, which config dir
      ├─ launcher ── flag translation, environment, exec
      ├─ hooks ───── lifecycle guards inside a session
      └─ tools ───── palace, research, ghidra, provider
```

---

## 2. Architecture

### One core, thin shells

```
bin/claude      (48 lines)  bash shim   ─┐
bin/claude.ps1  (55 lines)  pwsh shim   ─┼─► cortex/  (the implementation)
bin/claude.cmd   (3 lines)  cmd shim    ─┘
```

This is the single most important structural decision. The previous version had a
1223-line bash wrapper and a 565-line PowerShell wrapper that had drifted into
**different products** — the PowerShell one had no login, no profile management,
and no diagnostics, because nothing ever ran it. Almost every platform bug came
from that gap.

The shims locate the core and hand over. They contain no logic worth testing.

### Module map

| Module | Responsibility |
| :--- | :--- |
| `paths.py` | Canonical path form. **Load-bearing — see §3.** |
| `profiles.py` | Profile CRUD, auth via `claude auth status`, identity seeding |
| `launcher.py` | Flag translation, session environment, `execve` |
| `binary.py` | Ordered, verified Claude Code binary resolution |
| `capacity.py` | Account capacity; unknown stays unknown |
| `doctor.py` | Diagnose and repair known failure modes; surface integrity |
| `ide.py` | Settings-only IDE integration |
| `ghidra.py` | Isolated binary analysis (decompile + capability report) |
| `mcp.py` | Register the MCP server per profile (auth untouched) |
| `integrity.py` | Manifest generate/verify; runnable standalone |
| `tools.py` | Dispatch to standalone tools (checkout wins over installed) |
| `jsonfile.py` | Atomic, backed-up JSON writes; `write_text` for small files |

Standalone tools under `scripts/` (invoked via `tools.py` or the MCP server):
`claude-palace.py` (memory), `claude-dream.py` (risk analysis), `instinct-cli.py`
(learned patterns), `claude-research.py` (arXiv), `cortex-mcp.py` (the MCP server),
plus the lifecycle hooks.

### Profiles

A profile is a directory under `~/.claude-profiles/<name>` used as
`CLAUDE_CONFIG_DIR`. Claude Code then keeps that profile's credentials, history,
and settings there.

- **synced** — shares `projects`, `skills`, `commands`, `rules` with other
  profiles by symlink. Only credentials and usage are separate.
- **isolated** — shares nothing.

`settings.json` is **copied, never linked**, in both modes. Claude Code writes
that file itself when you change something in `/config` or save a default with
`/model`; a link either leaks those writes into every other profile or loses them.

---

## 3. The decisions that carry weight

### Path canonicalization is not cosmetic

Claude Code namespaces stored credentials by a hash of the config-directory
**string**:

```
suffix = sha256(CLAUDE_SECURESTORAGE_CONFIG_DIR)[:8]
```

Normalized NFC and nothing else — no case folding, no separator normalization, no
symlink resolution. So these are **three different accounts**:

```
C:\Users\me\.claude-profiles\main
/c/Users/me/.claude-profiles/main
C:/Users/me/.claude-profiles/main/
```

Git Bash and PowerShell naturally produce different spellings for the same
directory. That is why a profile signed in from one shell appeared signed out in
the other. Every config-dir string in Cortex comes from `paths.canonical_dir()`.

**If you change that function, you change which credentials every profile sees.**

### Authentication is asked, not inferred

`claude auth status` is authoritative. It **exits 0 whether or not you are signed
in**, so the `loggedIn` field is read and the exit code ignored. Probing for
`.credentials.json` does not work — on Windows credentials can live in Credential
Manager.

Onboarding state (`hasCompletedOnboarding`, `oauthAccount`) is seeded into the
profile's `.claude.json` after login. Without it, every launch re-runs first-run
onboarding.

### Missing data is not good news

A profile with no usage cache is reported **unknown**, never "free", and is never
auto-selected. The previous behaviour called it "100% capacity free" and ranked it
best, so failover could switch to an exhausted account.

### A command is never a prompt

Exit code 2 on `UserPromptSubmit` blocks **and erases** the prompt. Interception
therefore requires an explicit `/cc` prefix. An unrecognized command is refused
with a suggestion rather than sent to Claude — twelve legacy subcommands used to
start a real API session to answer their own name.

### Isolation over trust

Ghidra analysis runs `--network none`. The audit found nothing, but the audit is a
review of 15,000 files, not a proof. A control that does not depend on the audit
being complete is worth more than one that does.

---

## 4. What it can do

- Run several Claude accounts with genuinely isolated credentials, subscription
  auth intact (Cortex runs Claude's real binary; it never touches how you sign in)
- Share project context across profiles while keeping quota separate
- Keep terminal, PowerShell, and IDE sessions on one credential namespace
- Diagnose and repair the known failure modes (`cc doctor --repair`)
- Verify the install is byte-for-byte the reviewed source (`cc integrity verify`)
- Configure IDEs without touching extension files
- Store and recall project lessons (`cc palace` — real, tag-indexed)
- Track learned behavioural patterns with confidence (`instinct-cli`, real store)
- Retrieve real arXiv papers (`cc research` — real, live API)
- **Analyze binaries** with no network route out: decompile to C and produce a
  capability report from imports (`cc ghidra` — verified against known binaries)
- **Static risk analysis of source** with file/line/mechanism findings
  (`cc dream` — real AST + shell analysis; found real bugs in its own codebase)
- **Give Claude these as tools** via MCP (`cc mcp add`), callable mid-session

## 5. What it cannot do

Stated plainly, because a tool that overstates itself is worse than a limited one.
(`cc dream` and `cc think` used to be listed here as fakes; `dream` was rewritten
into a real analyzer and `think` was removed rather than left pretending.)

| Limitation | Detail |
| :--- | :--- |
| **`cc model` pricing is a snapshot** | Static table of 22 models. Honestly labelled; confirm against the provider. Not yet a live feed. |
| **`cc status` is not a usage API** | Reads Claude Code's local cache. No cache → unknown (never guessed). |
| **`cc dream` is not a full linter** | Real, but pattern/AST-based: it finds the failure classes it knows (swallowed errors, non-atomic writes, missing timeouts, injection), not everything. |
| **Ghidra loses inlined functions** | A `static` the compiler inlined has no boundary in the output; type inference near varargs can be confidently wrong. |
| **Ghidra audit is not a proof** | Pattern matching misses obfuscation and reflection. The C++ decompiler is not source-audited. |
| **Antigravity is not CI-tested** | Windows-only app. Config generated and statically validated; verify by launching. |
| **No real-credential testing** | The suite uses a stub binary. Profile isolation is verified structurally, never against a live account. |
| **Windows `.cmd` shims untested in CI** | No Windows container in the harness. |
| **The integrity manifest is unsigned** | It detects tampering after install, but a determined attacker who replaces both the files and the manifest is not stopped by it alone. Signing is the remaining step. |

---

## 6. Testing, and why it is shaped this way

Three layers, because the first two are not enough on their own.

**Scenarios** (`tests/sandbox/scenarios.sh`) — one per real defect. These pass by
construction: each was written after its bug was fixed. They prove regressions do
not return; they cannot find anything new.

**Adversarial** (`fuzz.py`, `chaos_env.py`) — explores rather than confirms.
Generated argument vectors, random profile-operation sequences, hostile on-disk
and environment states, concurrency. Checks *invariants*, not expected output. Its
first run found four real defects.

**Mutation** (`mutate.py`) — reintroduces each fixed bug and checks something
notices. This measures whether the **suite** works. Its first run caught 8 of 10;
one test genuinely protected nothing, and one "miss" was a bad mutation.

> A suite that only ever reports zero failures is not evidence the code is
> understood — it may simply be unable to fail. That is what the third layer is
> for.

Everything runs in containers, and every scenario ends with a **filesystem leak
check** that fails on any change it did not declare.

### Lessons that cost real time

- A test that cannot establish its preconditions must **fail**, not pass. The
  argument fuzzer reported 274 passing checks while testing nothing; asserting the
  precondition exposed a genuine product bug.
- The scenario runner re-copied the work tree from a read-only mount, silently
  undoing every mutation and reporting false passes.
- Scenarios that leave scaffolding behind make later scenarios test the wrong
  thing. Clean up.
- A test that fails intermittently teaches people to ignore failures. Poll with a
  deadline; never sleep a fixed interval.

---

## 7. Next steps

Done since the first draft: `dream` rewritten into a real analyzer, `think`
removed, command files triaged (130 → 74), MCP server built, integrity
verification added, the instinct store made to work standalone.

**Near term**
1. Verify the Windows `.cmd` shims — no container covers them today.
2. Manual Antigravity verification at install time (checklist in `HANDOVER.md`).
3. Replace the static model catalog with a live fetch, or drop the prices.
4. Sign the integrity manifest, so replacing files *and* the manifest is caught.

**Medium term**
5. Per-profile **usage history**, so capacity reporting stops depending on a cache
   Claude Code may not have written.
6. `cc doctor --explain <symptom>` — map a symptom to its cause and fix.
7. Extend mutation coverage to the hooks and installers, which have none.
8. More MCP tools: expose `cc doctor`, `cc integrity`, and profile capacity so a
   session can reason about its own environment.

**Longer term**
9. A real Windows CI lane.
10. Treat Ghidra as the first of several isolated analysis tools — the
    audit → pin → isolate → report-only-update pattern generalizes into
    `cc audit <repo>`.
11. Close the analysis loop: feed the Ghidra capability report and decompiled C
    back through MCP so Claude reasons over a binary automatically.

---

## 8. Ideas worth considering

Noted while working, not committed to.

- **Profile templates.** `cc profile add work --template client` to preset model,
  effort, and permission rules. Most multi-account use is really multi-*context*.
- **`cc doctor --export`.** A redacted diagnostic bundle for asking someone else
  for help, with paths and emails scrubbed.
- **Session provenance.** Record which profile, model, and effort produced a piece
  of work. Useful when accounts have different quotas and capabilities.
- **The leak check is reusable.** It is a general "did this change anything it
  shouldn't" harness and would suit any installer, not just this one.
- **Audit-as-a-pattern.** `cc audit <repo>` generalizing the Ghidra work: enumerate
  egress, classify, baseline, diff on update. Most of that logic is not Ghidra-specific.
- **Make the analysis loop closed.** Ghidra headless emits JSON; feeding that back
  so Claude can reason over decompiled output is the actual value, and it is not
  built yet.
- **Drop `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`.** It gates plugin downloads,
  `/bug`, `/feedback`, and DesignSync — none of which is telemetry. It costs
  features and buys nothing.
- **Reconsider the memory palace's place.** It works, but it competes with Claude
  Code's own memory. One of them should win.
