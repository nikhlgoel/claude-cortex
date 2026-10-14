# Graphify, the palace and the 1M context window

How three different kinds of memory share one conversation without drowning it, and what keeps what
Claude says tied to what actually exists.

This page separates three things on purpose: **facts taken from Anthropic's documentation**, **numbers I
measured here**, and **design judgement**. Where something was not verified, it says so.

## The short version

- The context window is **working memory**: what Claude is looking at right now. Graphify is the **map**
  of the code. The palace is the **notebook** of what you decided and learned. They are not interchangeable.
- A bigger window does not mean "put more in it". Anthropic's own documentation says accuracy and recall
  *degrade* as the window fills ("context rot"), so *what* is in it matters as much as how much fits.
- So each gets only what it is best at, and they meet at a few small, defined points (below). Nothing is
  copied wholesale into the window.
- Answers stay tied to the code through checks that look a name up instead of trusting it. That removes
  one family of mistakes (invented files and functions). It does not make a model correct.

## What this rests on (from the documentation, read in this session)

| Fact | Source |
|---|---|
| Sonnet 5.5, Opus 5.5 and the other current models run with a **1M-token window by default** in Claude Code (no `[1m]` suffix needed for Sonnet 5 and later, Opus 4.7 and later, Fable 5/5.1, Haiku 5.5) | [Model configuration](https://code.claude.com/docs/en/model-config) |
| Those models **auto-compact at about 967K tokens** by default; `autoCompactWindow`, `/autocompact` or `CLAUDE_CODE_AUTO_COMPACT_WINDOW` make it earlier | same page |
| "More context isn't automatically better. As token count grows, accuracy and recall degrade ... curating what's in context is just as important as how much space is available" | [Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows) |
| Sonnet 5.5 and Opus 4.7+ do **not** receive the injected "tokens remaining" tags; older Sonnets do | same page |
| `SessionStart` reports why it ran: `startup`, `resume`, `clear`, `compact` or `fork`; hooks can add context, capped at 10,000 characters per field | [Hooks](https://code.claude.com/docs/en/hooks) |
| A `Stop` hook can block the stop so Claude continues. **The documentation names no protection against a Stop hook that blocks forever**, and does not list a `stop_hook_active` field | same page (checked twice) |

## Three stores, three lifetimes

| | **Graphify** (the map) | **The palace** (the notebook) | **The window** (working memory) |
|---|---|---|---|
| Holds | what the code *is*: files, functions, who calls whom, the areas it falls into | what we *decided, learned, want*: decisions, failures, rules, how-tos | what is being worked on *now*: files read, tool output, the conversation |
| Lasts | until the code changes; rebuilt offline in seconds (`graphify update .`) | months; kept with history, never silently overwritten | one conversation, then summarised at compaction or gone at `/clear` |
| Size | megabytes (3.7 MB for this repository) | kilobytes to megabytes | up to 1M tokens |
| Reaches Claude | when asked (Graphify's own tools), and as *pointers* | injected only when relevant, a few hundred tokens at most | everything Claude reads or does |
| Goes wrong by | being out of date after code changes | being out of date, or noisy if over-injected | context rot; detail lost in a summary |
| Cortex's answer | notes are anchored to it, so out-of-date notes can be *seen* | the abstain rule, freshness flags, history, a hard token budget | keep it small; reset the palace's "already shown" list when it is summarised |

The rule that makes this work: **Graphify and the palace stay outside the window until a specific piece
is worth its place there.** Pouring either in wholesale would spend the very attention the larger window
was supposed to give you.

## One request, start to finish

1. **A session starts.** A hook records it (so the project-map button can appear) and, if the
   conversation was just compacted or cleared, tells the palace so (step 5).
2. **You send a prompt.** The prompt hook asks the palace one question: is there strong evidence that a
   stored note answers *this*? Usually the answer is no, and **nothing is added** (0% of unrelated
   prompts got a note in the evaluation, against 76% for the old scorer). When the answer is yes, up to 700
   tokens go in: the best notes, shortest form that does the job. Notes about files you named, or files
   the code graph says sit next to them, rank higher. A note whose code changed since it was written is
   marked "verify". Nothing is shown twice in a session.
3. **Claude works.** It reads the files it needs - this is what the window is for. It can ask for a note
   (`recall_memory`), ask Graphify about structure, or check a name it is about to rely on (`verify_refs`).
4. **Claude answers.** Optionally (`cc palace ground on`), the names in the answer are checked once and
   anything that does not exist is pointed out, with the closest real name.
5. **The conversation is compacted.** What the palace showed earlier has just been summarised away, so the
   palace is told and may show it again. The notes themselves, the graph and the usage history are
   untouched: they were never in the window to lose.
6. **The code changes.** After `graphify update .`, notes about the changed code turn amber on the map and
   say "verify" when injected. If the code is gone they turn red and rank low.

## What it costs (measured on this machine)

| | Measured | Share of a 1M window |
|---|---|---|
| A note retrieved for a prompt that has one (average) | **134 tokens** (157 on the held-out cases) | 0.013% |
| The most the prompt hook will ever add | **700 tokens** (a setting, `CORTEX_PALACE_BUDGET`) | 0.07% |
| The always-on core, shown once a session | at most 40% of that budget | under 0.03% |
| Graphify's `GRAPH_REPORT.md` for this repository (230 files, 1,857 functions) | 40,919 bytes, **about 10,200 tokens** by the 4-characters-per-token rule of thumb | about 1% |
| The prompt hook, every prompt | **about 100 ms** (28 ms of that is Python starting) | n/a |
| The session hook / the Stop hook | about 100 ms / about 96 ms | n/a |
| Checking a 6,000-character answer's names | **2 ms** | n/a |

For scale: the evaluation's 38 notes come to 1,739 tokens, so pasting them all in would be cheap *there*.
The case for retrieval is growth. At that average of about 46 tokens a note, 5,000 notes would be around
230,000 tokens - roughly a quarter of the window - against about 134 for a retrieval. That last comparison
is arithmetic from the average, not a measurement of anyone's real notes.

The report is the only sizeable thing here, and it is not added by Cortex: your own `~/.claude/CLAUDE.md`
tells Claude to read it first in a Graphify project. At 1% of a 1M window that is reasonable; it would not
be at 200K, and it is worth knowing.

## What keeps answers tied to the code

| Mechanism | What it prevents | How well it is checked |
|---|---|---|
| **Abstain unless the evidence is strong** | an irrelevant note nudging a prompt it has nothing to do with | 0% false injection on 25 prompts that should get nothing (old scorer: 76%) - *on a corpus written by one person* |
| **Anchors and freshness** | acting on a note about code that has since changed or vanished | tested on constructed graphs and by hand on a real 3,572-node Graphify graph of this repository |
| **Newer replaces older, history kept** | two versions of a fact shown side by side | 100% of changed facts correct (old scorer: 0%) |
| **Notes are labelled as data, not instructions; web and tool text has lower trust** | text in a note being obeyed as if you had written it | by design and tests of the labelling; not adversarially red-teamed |
| **`verify_refs` / `cc palace verify`** | Claude stating that a file or function exists when it does not | unit-tested on constructed projects and by hand on the real graph; typos and renames come with the real name |
| **The Stop check (opt-in)** | the same, automatically, once per prompt | tested with simulated hook payloads; **never observed in a live Claude session** |
| **Reset after compaction or `/clear`** | the palace staying silent about things Claude can no longer see | tested with simulated payloads; the real `compact` event was **not** observed live |

What the name check will and will not call wrong, so it stays trustworthy:

- A file is wrong if it exists nowhere (disk or graph), or the graph lists it but the disk does not.
- A function is wrong only when it is in backticks **and** a similarly named real one exists (a likely
  typo or rename). A name unlike anything in the project is reported as "not in this project's graph (may
  be library code)" - never as wrong. `os.path.join`, generic words like `main`, and anything checked
  without a graph are "not checked".
- Absolute paths are matched whole (`C:\\...` or `/...`); a path outside the project is not judged.

## What none of this does

- **It does not stop a model reasoning badly.** It catches one kind of mistake, the invented name. It says
  nothing about whether a plan is right, whether a described behaviour is true, or whether code works.
- **It is only as current as the graph.** Graphify does not rebuild itself. Stale graph, stale checks.
- **The numbers are from a corpus I wrote.** 43 questions, 25 that should get nothing, 38 notes. They are
  a regression guard and a fair comparison with the old scorer, not a promise about your notes. Two of the
  43 are still missed (one needs meaning-based search, which is off by default).
- **No end-to-end test of answer quality.** I did not run real coding tasks with and without these features
  and compare the results. Nothing here claims "N% fewer hallucinations".

## Using the large window well

These are suggestions from the above, not measured recommendations for your work:

- Let Claude read what it needs; do not pre-load notes or reports to "give it context". The palace adds
  what is relevant by itself.
- Run `graphify update .` after large changes, so the map, the notes' health colours and the name checks
  describe the code as it is.
- If you see drift late in very long sessions, an earlier compaction (`/autocompact`, for example 400k)
  trades some history for a fresher window. I have not measured whether that helps in your work.
- If invented names bite you, `cc palace ground on` makes the check automatic. It is off by default
  because a note that cries wolf gets ignored; it speaks only on a missing file or a near-miss name, once
  per prompt, and says so if the "missing" thing is something Claude is about to create.

## What I did not verify

- That your Desktop app or terminal is using a 1M window for the model you pick: the documentation says it
  is the default for Sonnet 5.5, but I have not observed your session's actual window.
- Any of the hooks inside a live Claude session. They are exercised by tests that send the documented
  payloads; the first real compaction on your machine is the first real run.
- Whether the Claude Desktop app's Code tab runs hooks from your `settings.json` the way the terminal does.
- On macOS or Linux: everything in `cc graph` and the button.
