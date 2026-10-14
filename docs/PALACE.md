# The memory palace

A project's memory for Claude: what was decided and why, what broke and how it was fixed, how things
are done here. It is stored on your machine, found by keyword search that understands code names,
checked against the code it describes, and handed to Claude only when it is relevant.

Everything in this page describes what is built and tested. Where something is a limit, it says so.

## Set it up (one command)

```
cc palace init
```

No questions. In the project folder you are in, it:

1. creates the palace for that project (one SQLite file, in `~/.cortex/palace/projects/<name>-<id>/`,
   **outside your repository**, so it is never committed by accident);
2. finds an old (v2.5) palace and imports it - **the old files are not changed or deleted**;
3. links a Graphify graph if there is one (see below) - optional;
4. prints what it did and what to try next.

The defaults, so you do not have to choose:

| Setting | Default | Change it |
|---|---|---|
| Where it lives | `~/.cortex/palace/` - shared by all your profiles and surfaces (terminal, IDE, Desktop) | `CORTEX_DATA_DIR=<folder>` |
| One palace per | project (git worktrees of one repo share it) | `--scope global` for a personal one |
| Memory added to prompts | on, ~700 tokens at most, only when relevant, never repeated in a session | `cc palace inject off`, or `CORTEX_PALACE=off` |
| Embeddings | off (see "What are embeddings?") | not needed |
| Graphify | used if a graph exists | `graphify update .` builds one, offline |

## Day to day

You mostly do not need to do anything: when a prompt is clearly about something the palace knows, the
relevant notes are added to it automatically, and Claude can store and look things up itself through
two tools (`remember`, `recall_memory`). By hand:

```
cc palace remember "Connection pool size" "The pool is 50 connections after the outage."
cc palace recall "how many db connections do we use"
cc palace about cortex/guard.py          # what do we know about this file or function
cc palace status                         # counts and health
```

If you record a decision that has the same title as an earlier one, the new one **replaces** it and
the old one is kept as history (`cc palace recall ... --history`). A fact that changed is never
silently lost, and never shown alongside its replacement.

## How the data is organised

Memories live in layers, because "everything in one pile with an index" is how a memory ends up either
useless (too little comes back) or noisy (too much does):

| Layer | Holds | How it is used |
|---|---|---|
| 0 scratch | the current task's working notes | for the task |
| **1 core** | a few standing rules and preferences (you choose: `cc palace tier <id> 1`) | shown once at the start of each session |
| 2 episodic | things that happened: a bug found, a command that worked | searched on demand; old unused ones are archived |
| **3 semantic** | decisions, facts, structure - the knowledge | the main thing recalled |
| 4 procedural | recipes: how to build, test, release | recalled by task |
| 5 archive | retired memories | only if asked for |

Each memory also records its **kind** (decision, fact, failure, fix, recipe, rule, preference...),
**trust** (user, agent, tool, web - web and tool text is never promoted automatically), **importance**,
**confidence**, and the **time range** it was true. Every memory is stored at three sizes - a headline,
a two-sentence gist, and the full text - and each prompt gets the right size for how relevant it is,
inside a token budget.

## How a memory is found

1. Your question becomes terms. Code names are understood: `loadConfig`, `load_config` and `paths.py`
   match by their parts and as a whole; `settings`/`setting` and `inject`/`injection` meet.
2. Candidates come from two independent signals: keyword scoring (BM25 over title, tags, code anchors
   and body), and files/symbols the question names, with memories about *neighbouring* code ranked up.
3. Scores are combined and adjusted: newer beats older (important ones fade slowly, pinned ones never),
   trusted beats untrusted, and **a memory whose code has changed is demoted and flagged**.
4. **If the evidence is thin it returns nothing.** A word that is in most of your memories is not
   evidence. This is the most important rule for something that adds text to your prompts.
5. What survives is packed into the token budget.

## Graphify: how the two fit together

> **Graphify knows what the code *is*. The palace knows what we *decided, learned and want*.**

The palace never copies code structure. Instead each memory is **anchored** to the files and symbols it
is about, and the Graphify graph is used for three things:

| Use | What happens |
|---|---|
| **Anchoring** | "`profile_dir` is called from guard.py" in a memory becomes a link to the real function and file |
| **Neighbours** | when you work on `a.py`, memories about the files it calls rank up, weighted by how sure Graphify is about the link |
| **Freshness** | Graphify keeps a hash of each file's syntax tree. If it differs from when the memory was written, the memory is shown as *"code it refers to changed since this was written - verify"*; if the file or function is gone, as *"likely outdated"* and dropped when ranked low |

How it is wired, and what it deliberately does not do:

- It reads `graphify-out/graph.json` and `manifest.json` **read-only**. It never imports Graphify, never
  runs it, never writes into its folder.
- It recognises the graph by its **shape**, not a version number (this Graphify release writes none),
  and refuses anything that does not look like a graph, leaving what it had intact.
- It keeps a small **file-level summary** in the palace (files, symbols, who-calls-whom), refreshed only
  when the graph file changes - so a prompt never waits on parsing a big JSON file.
- **No graph? Everything still works.** Anchors then use plain file-content hashes.
- To build a graph with no model and no network: `graphify update .` in the project.

`cc palace graph` shows the link; `cc palace about <file or function>` lists the memories anchored there.

## What are embeddings?

**In one sentence:** an embedding turns a piece of text into a list of numbers so that texts with
*similar meaning* get *similar numbers* - letting a search find "shut down when nobody is using it" when
the note says "idle timeout", even though they share no words.

**What it would cost:** a small model file to download (hundreds of MB), time to run it on every note and
every question, and more storage. It also makes results harder to explain ("why did this come back?").

**Why the palace does not use them by default:**
- project notes are full of exact names - `guard.py`, `CLAUDE_CONFIG_DIR`, `416` - where plain
  keyword search is *better* than meaning-search;
- Graphify itself deliberately uses no vector store, and the two work well together as they are;
- the common "same idea, different words" cases (login/authentication, db/database, error/failure...)
  are covered by a small **synonym list** that you can extend per project and that needs no model.

**The honest cost of that choice:** the evaluation has one clear miss of this kind - the question
"gateway shuts down when nobody is using it" does not find the note titled "idle timeout". If misses like
that start to matter in your own use, embeddings (through the local model you already have set up) are
the planned add-on, off unless you turn them on. You do not need to decide now.

## Safety and privacy

- **Local only.** No network access anywhere in the palace.
- **Secrets are scrubbed before anything is stored** - API keys, tokens, `password=...`, private-key
  blocks - and the audit trail never contains content. (Pattern-based: it catches well-known formats,
  not every possible secret. Do not rely on it for anything you would not paste into a notes file.)
- **Injected memory is labelled as data, not instructions**, and text that came from tool output or the
  web is stored with lower trust and is never promoted to the always-on layer automatically.
- **Nothing is deleted behind your back.** Superseding and archiving keep the old text; `cc palace forget
  <id> --yes` is the one command that really erases a memory and everything derived from it.
- **Controls:** `cc palace inject off` (this project), `CORTEX_PALACE=off` (everywhere),
  `CORTEX_PALACE_BUDGET=<tokens>` (smaller or larger).

## What was measured

A test corpus of 38 real facts from this project and 70 questions (paraphrased, so they avoid the notes'
own wording; knowledge updates; and prompts that should get nothing), a third held out from tuning:

| | new palace | old palace (v2.5) |
|---|---|---|
| right memory ranked first | **86%** (held-out 92%) | 81% (75%) |
| right memory in the top 3 | 95% (held-out 100%) | 98% (100%) |
| unrelated prompts that wrongly got memory | **0%** | **76%** |
| a changed fact replaces the old one | **100%** | 0% |

So the gain is **safety and correctness**, not a dramatic jump in finding things - the old scorer was
already decent at that on this corpus, partly because it always returns something. The corpus was written
by one person, so treat the numbers as a regression guard and a relative comparison, not a promise about
your notes. Two of the 43 "find this memory" questions are still missed: one needs meaning-search (above),
and one shares only one of its three words with its note, which keywords cannot tell apart from noise.

Speed on a synthetic palace (words taken from this repo's docs), median:

| memories | write | recall | maintenance (dry run) | file size |
|---|---|---|---|---|
| 500 | 3 ms | 2 ms | 0.8 s | 2.7 MB |
| 2,000 | 5 ms | 9 ms | 5 s | 10 MB |
| 5,000 | 7 ms | 35 ms (p95 110 ms) | 23 s | 26 MB |

Added to each prompt by the hook: about 70 ms over bare Python start-up (~100 ms in total).

The code is covered by 229 tests, and **every one of 38 deliberate breakages of it is caught** by at
least one test (mutation checking). The Graphify bridge is also tested against a trimmed copy of the
real output Graphify wrote for this repository.

## Command reference

| Command | Does |
|---|---|
| `cc palace init` | set up this project's palace (and import the old one) |
| `cc palace remember [TITLE] CONTENT` | store a memory (`--kind`, `--file`, `--supersedes`, `--pin`; the old `--room` still works) |
| `cc palace recall QUESTION` | find memories (`--explain` shows why, `--history`, `--file`, `--budget`, `--json`) |
| `cc palace about FILE-OR-FUNCTION` | memories anchored to it |
| `cc palace expand ID` / `list` / `status` | look at what is stored |
| `cc palace pin / unpin / tier / archive / restore / supersede ID` | manage (all reversible) |
| `cc palace forget ID --yes` | really delete one memory |
| `cc palace consolidate [--apply]` | maintenance: freshness, duplicates, stale episodes, and *proposals* |
| `cc palace graph [--sync]` | the Graphify link |
| `cc palace inject on/off` | automatic memory in prompts, for this project |
| `cc palace migrate [--apply]` | import an old palace (init already does) |
| `cc palace export FOLDER` | readable Markdown copy |
| `cc palace verify TEXT` | check the files and `backticked` names in some text against the project and its code graph ([how](CONTEXT.md)) |
| `cc palace ground on/off` | check each of Claude's final answers the same way, once, automatically (off by default) |
| `cc palace doctor` | health check |
| `cc palace eval` | re-run the accuracy measurement |

`consolidate` only ever *proposes* the judgement calls - possible conflicts between decisions, rules worth
promoting to the always-on layer, groups of episodes that deserve one distilled fact. With `--apply` it
does only the safe, reversible things.

## When something looks wrong

| You see | Likely cause |
|---|---|
| nothing is ever added to prompts | no palace yet (`cc palace init`), `inject` is off, or the question is not about anything stored - try `cc palace recall "..." --explain` |
| a note says "code ... changed" | the file it is about changed since it was written; check it, then re-record or `supersede` it |
| `recall` finds nothing for a one-word question | a word that is in most of your notes is not evidence by itself; use more words |
| "newer Cortex" error | the palace was written by a newer version; update Cortex - the file is left untouched |
| anything else | `cc palace doctor` |
