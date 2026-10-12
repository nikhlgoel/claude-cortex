# Cortex 3: a layered Memory Palace, a Studio mod, and a Swarm

Status: **design and research only - nothing in this document is built yet.** Facts taken from
Anthropic's documentation are marked **[verified]** with the page; everything else is a
proposal, and anything I could not confirm is marked **[unverified]**. Researched 2026-10-12.

## 0. The straight answer

*"Are those actual frameworks?"* No. What exists today is a **kit**: a profile launcher, a
change guard, tool routing, a local-model gateway, a flat memory palace and some hooks. The five
"framework options" were *directions*, not built frameworks. This plan is the concrete design
that replaces them, and it is built from three parts that share one data layer:

```
                 +-------------------------------------------------+
                 |   PALACE  (the data layer - one SQLite store)    |
                 |   tiers: core / episodic / semantic / procedural |
                 +-------------------+-----------------------------+
                                     |  read through one small MCP server
        +----------------------------+------------------------------+
        |                            |                              |
  +-----v------+              +------v------+               +-------v------+
  |  INJECTION |              |   STUDIO    |               |    SWARM     |
  |  right     |              |  a Claude   |               |  subagents + |
  |  memory,   |              |  Code MOD:  |               |  sessions    |
  |  right     |              |  panes, live|               |  sharing the |
  |  moment    |              |  display,   |               |  same palace |
  |  (hooks)   |              |  themes     |               |              |
  +------------+              +-------------+               +--------------+
```

It maps onto the earlier options: Palace = "Decision Memory" grown up; Swarm absorbs
"Budget Governor"; Studio is new. "Evidence Gate", "Shield" and "Sidecar" remain optional later.

## 1. What Claude Code already gives us (so we do not rebuild it)

| Capability | Fact | Source |
|---|---|---|
| **Mods** | JS/TS event handlers shipped in a plugin; hook tool calls, prompts, turns, commands and *every UI draw*. Need **CLI 2.1.287+ / Desktop 2.1.286+**. On by default; not sandboxed. | mods/overview **[verified]** |
| Your install | Desktop has Claude Code **2.1.293 and 2.1.295** downloaded, so mods are available to you. They are invisible until one is installed. `/plugin` > Installed > *Built-in* lists the ones that ship. There is no `claude` on your shell PATH; the Desktop bundles its own. | local check **[verified]** |
| Where mods draw | A **pane** (sidebar beside the transcript in a wide fullscreen terminal, else a framed region above the prompt), a **band above the prompt**, a toast, a status line, and restyled built-in rows (spinner, tool rows, messages). Not the permission prompt. Terminal and Desktop Code tab only (not WSL sessions; VS Code chat panel runs hooks but draws nothing). | mods/interface **[verified]** |
| Animation | `$.clock.every`, `$.ui.invalidate` (throttled to 10/s, 30/s for the visible pane), `Raster` (grid of coloured cells, up to 512x256, terminal) with `$.ui.blit` to repaint without re-rendering, `Svg` (Desktop) and `Client` (own animation + pointer input). | mods/reference **[verified]** |
| Live data | `$.session.usage()` (context tokens/window/percent, plan limits, cost), `$.agent.list()` (subagents/teammates with status), events for every tool call, turn and compaction. | mods/reference **[verified]** |
| Memory hooks | `prompt.context` (context sent with the first message), `prompt.submit` with `context`, `prompt.section`/`prompt.compose` (system prompt), `session.compact` (can skip), `session.append`. `$.store` is a JSON key-value store shared by all sessions (4 MiB cap). | mods/reference **[verified]** |
| Model calls | `$.model.complete / fork / classify` with prompt caching; bills to the user's plan. | mods/api **[verified]** |
| Sessions talking | **Already native**: Claude lists and messages your other local sessions (`ListAgents`, `SendMessage`); v2.1.224+, **native Windows v2.1.234+**. Plain text, over a per-session socket, never through Anthropic for same-machine. Inbound control `crossSessionInbound`: accept / hold / refuse. Loop-throttled. A message can never approve a permission or change config. | cross-session-messaging **[verified]** |
| Subagents | Markdown + frontmatter (`model`, `tools`, `memory`, `effort`, `isolation: worktree`, `background`, `hooks`, `skills`, `maxTurns`, `color`). 20 concurrent, depth 3. Non-fork subagents **do not inherit conversation, output style or auto memory**. Mods can choose a subagent's model (`agent.spawn`) or withhold a type (`agent.offer`). | sub-agents, mods/reference **[verified]** |
| Themes | Custom theme = JSON in `~/.claude/themes/` (`base` + colour `overrides`; ~60 tokens incl. spinner shimmer, subagent colours, diff colours). Plugins can ship themes. Live reload. | terminal-config **[verified]** |
| Native memory | `CLAUDE.md` hierarchy + auto memory (first 200 lines / 25 KB of `MEMORY.md` loaded each session). | memory **[verified]** |

**Consequence.** Cross-session messaging, themes, subagent definitions and the UI surfaces
exist. Cortex should *extend and coordinate* them, never re-implement them. The one thing
Claude Code does **not** have is a real layered, queryable, self-maintaining memory - and that
is where your criticism lands.

## 2. Memory Palace v3 - the core

### 2.1 What is wrong with today's palace (read from the code)

`scripts/claude-palace.py`, 666 lines:

| Today | Problem |
|---|---|
| Five flat Markdown files ("rooms") + one `index.json` | A room is a *category*, not a layer. Everything in a room has equal standing. |
| Recall scores **word overlap** (tag 4, title 3, summary 1) + a 3-bucket recency bonus | No meaning, no synonyms: "auth" never finds "login". The score is a hand-set constant. |
| Summary = first line, 150 chars | Cannot show a short form for many and a long form for few. |
| Returns top **3** results, full text, no token budget | Either too little or too much; never packed to fit. |
| Whole `index.json` loaded on every call; entry found by regex over the room file | O(N) per query; will slow as it grows. |
| No supersession: a changed decision is a *new* entry next to the old one | The model can be handed two contradicting facts with no way to know which is current. |
| No confidence, source, or validity dates | Cannot tell a verified fix from a guess, or a stale fact from a live one. |
| `last_consolidated` is a timestamp that nothing acts on | No consolidation, decay, merging or promotion exists. |
| Pull only: used when Claude *chooses* to call `recall` (or you run the command) | The right memory is not there at the moment it matters. |
| `PreCompact` hook prints five static sentences | Compaction does not actually save or restore anything. |

### 2.2 Design principles (from the research)

1. **Tiers by purpose and lifetime**, like an OS (hot context vs paged archive) - MemGPT/Letta.
2. **Raw episodes are kept; knowledge is distilled from them** - Generative Agents' memory stream
   plus periodic reflection; Zep/Graphiti's episodic -> semantic -> community subgraphs.
3. **Facts have time, not just text.** Never delete a fact that changed; mark it invalid and
   link its replacement (Zep's bi-temporal `valid_at / invalid_at`). Asking "what is true now"
   and "what did we believe in March" must both work.
4. **Retrieval is a pipeline, not a lookup.** Keyword **and** meaning **and** structure, fused,
   then ranked, then packed to a token budget. Anthropic's own contextual-retrieval result:
   embeddings + BM25 cut failed retrievals by 49%, and adding a reranker by 67% (top-20, their
   benchmark) **[verified]** - so no single signal is enough.
5. **Progressive disclosure.** Every memory stored at three resolutions (headline / gist /
   full); show headlines for many, expand only the few that earn it.
6. **Write is gated, read is measured.** Memory poisoning and noise are the main failure modes,
   so entry into the always-on tier needs evidence, and every retrieval is evaluated.

### 2.3 The tiers

| Tier | Holds | Size | How it is used | Lifetime |
|---|---|---|---|---|
| **L0 Scratch** | Current task: goal, plan, files touched, open questions, decisions-in-progress | ~1-2 K tok | Re-injected after compaction and into subagents; shared between sessions of one task | Task |
| **L1 Core** | Project identity, hard rules/invariants, your standing preferences, current objective | **<= ~600 tok, always injected** | Pinned; changes only via promotion or your approval; versioned | Long |
| **L2 Episodic** | Time-stamped events: bug found/fixed, decision made, command that worked/failed - append-only, with source (session, files, commit) | Unbounded | Searched on demand; raw material for consolidation | Decays, then archived |
| **L3 Semantic** | Distilled facts, entities and relations ("X depends on Y", "D2 supersedes D1"), each with validity dates, confidence and links to the episodes that support it | Grows slowly | The main thing retrieved; auto-linked to files/paths | Until invalidated |
| **L4 Procedural** | Verified recipes: build/test/deploy steps, with success counts. Promoted to a real skill/command once proven | Small | Matched by task type | Until it fails repeatedly |
| **L5 Archive** | Compressed old episodes | Unbounded | Only on explicit deep recall | Permanent, cold |

Scopes: **session -> project -> global (you)**, each its own store; queries merge them with the
narrower scope winning. The existing "rooms" become *views*: Blueprint = L3 where kind=structure,
Council Chamber = L3 where kind=decision, Workshop = L4, Graveyard = L2/L3 where kind=failure,
Study = L0. Nothing you see in the UI has to change on day one.

### 2.4 Storage

One **SQLite** file per scope (WAL mode, busy timeout) - transactional, concurrent-safe across
the several sessions you run at once, and it ships with Python. Full-text search via **FTS5**
(BM25). Vectors are **optional** (a local embedding model through the llama.cpp already
integrated); the system must be good without them.

```
memory(id, scope, tier, kind, title, headline, gist, body, status[active|superseded|archived],
       valid_from, valid_to, recorded_at, superseded_by, confidence, importance, pinned,
       uses, last_used, content_hash, source_session, source_commit, trust[user|agent|tool|web])
link(src, dst, rel[supports|supersedes|about|depends_on|contradicts], weight)
entity(id, name, type, aliases)      memory_entity(memory, entity)
memory_path(memory, path)            -- ties a memory to files it concerns
feedback(memory, injected_at, session, used[0|1|unknown])
event(ts, op, memory, who)           -- audit trail of every write
embedding(memory, vector)            -- optional
```

Human-readable **Markdown export** stays (git-diffable, greppable), generated from the database.
The database is the source of truth. Migration from `index.json` + room files is non-destructive
(originals kept) and shows a dry run first.

### 2.5 Write path

```
event (you / Claude / tool)
  -> scrub secrets  -> classify (rules first; small model optional)  -> dedupe (hash + similarity)
  -> contradiction check against L3 (supersede, never overwrite)
  -> score importance (rules: touched files, failure, your explicit "remember", repetition)
  -> link entities + paths  -> store in L2 (or L3/L4 if it is already a clean fact/recipe)
  -> promotion to L1 only if: pinned by you, OR used >= N times with positive feedback AND approved
```

Capture is **asynchronous** (a background scribe after the turn; never delays your prompt) and
**provenance-tagged**: anything that came from tool output or the web is `trust=tool|web` and is
never promoted automatically - this is the defence against memory poisoning.

### 2.6 Consolidation ("sleep") - what the old `last_consolidated` never did

A periodic, resumable job (`cc palace consolidate`, also run when idle):
1. cluster recent episodes -> write **reflections** into L3 with links to their sources;
2. merge duplicates; detect contradictions -> mark the older fact `superseded`, keep it;
3. **decay**: importance-adaptive half-life - important/often-used memories fade slowly;
   unused ones are demoted, then archived (never silently deleted);
4. extract repeated successful sequences -> candidate L4 recipes (and, when proven, a skill);
5. propose L1 changes as a **diff you approve**, not an automatic edit.

### 2.7 Read path

```
prompt + context (cwd, branch, files touched this session, recent tool calls)
  1. understand : entities, intent (fix / design / explain / run), paths
  2. candidates : BM25 (FTS5)  +  entity-graph expansion (1-2 hops)  +  path match
                  +  recent/frequent  +  [optional] vector similarity
  3. fuse       : Reciprocal Rank Fusion across the lists
  4. score      : relevance x recency(decay by importance) x confidence x trust
                  (superseded/expired excluded; memories tied to files you are touching boosted)
  5. rerank     : only when the top candidates are close - a small model reads the top ~20
  6. pack       : fixed L1  +  L3/L4/L2 slices by value-per-token, choosing headline/gist/full
                  per memory, to a hard budget (default ~800 tok; configurable)
  7. deliver    : see 2.8            8. log what was injected -> feedback table
```

### 2.8 Delivery - getting the memory there without being asked

| Surface | Mechanism | Works for |
|---|---|---|
| Any | A settings hook on prompt submit adds the packed context (this already exists as Cortex's prompt hook, extended) | terminal, Desktop, VS Code, `claude -p` |
| Mod present | `prompt.context` for the conversation start + per-turn `prompt.submit` context; `agent.spawn` injects a **role-scoped slice** into each subagent (they do not inherit memory) | terminal, Desktop |
| On demand | MCP tools `recall`, `remember`, `expand` for deep dives | everywhere |
| Compaction | Save L0 before compaction, re-inject after (replaces the static PreCompact sentences) | everywhere |

Injected text is framed as **reference data, not instructions**, and is never executed.
It sits at a stable position so prompt caching keeps working.

### 2.9 How we will know it is "more accurate" - an evaluation harness

Built **first**, before the engine, from your own memories and replayed sessions:
- a corpus of (query/situation -> memory ids that should surface), plus "knowledge-update"
  cases (decision changed -> only the latest may surface) and "irrelevant" cases (nothing should);
- metrics: recall@k, MRR, **tokens injected per useful memory**, and false-injection rate;
- a regression gate in the test suite, exactly like the routing corpus (0 false positives on the
  quiet set was the standard that fixed routing). The old keyword scorer is the baseline to beat.

## 3. Cortex Studio - a Claude Code mod + themes + status line

Delivered as **one plugin** (`cortex-studio`): the mod, a theme pack, subagent definitions,
skills, and Cortex's existing MCP server. The mod reads the palace through that MCP server
(`$.mcp.call`), not by spawning Python each turn.

### 3.1 What you asked for vs what is actually possible

| You asked for | Possible? | How / honest limit |
|---|---|---|
| Themes | **Yes, fully** | Theme pack as JSON + `cc theme` generator. Bonus: each profile has its own config folder, so **one colour scheme per account** (you can tell your three accounts apart at a glance) |
| Animated background | **Partly** | A mod cannot paint behind the transcript. It *can* draw an animated scene in a **pane** (terminal `Raster`, up to 512x256 cells, repainted with `blit`; Desktop `Svg`/`Client`). Idle-aware and FPS-capped so it costs almost no CPU |
| Live display of work | **Yes** | A "Console" pane: current step, tool-call stream, elapsed time, context %, cost, plan-limit meter, subagent board, inbox of messages from other sessions, "memories injected this turn" |
| Choose where things go | **Partly** | A pane docks beside the transcript (wide) or above the prompt (narrow); size is yours (`columns`/`rows`, Ctrl+X arrows). Presets `/layout focus \| watch \| wide \| zen`. Claude Code controls the rest of the screen |
| Terminal / background processes anywhere | **Yes, outside Claude Code** | `cc layout` opens **Windows Terminal split panes** running `cc watch` dashboards that read the shared event log - place them on any monitor. A mod cannot rearrange your terminal windows **[verified limit]** |
| Restyle the spinner / tool rows | **Yes** | `ui.render` on `Spinner`, `ToolUse`, `ToolResult`, `AssistantMessage`; per-phase spinners (reading / editing / testing) |
| Status line | **Yes, and works without mods** | Native `statusLine` command: profile, model, context %, branch, palace tier counts |

### 3.2 Features (in priority order)

1. **Palace pane** - browse tiers, see exactly what was injected and why, pin/unpin, approve L1 diffs.
2. **Band above the prompt** - context forecast (like Anthropic's "token weather" sample), profile name, injected-memory count.
3. **Console pane** (live work) and **Agents board** (colour-coded statuses from `$.agent.list()`).
4. **Theme pack + per-profile themes**, status line.
5. **Scene pane** (animated ambient art), layout presets, `cc layout` for external panels.

### 3.3 Safety of mods (a real risk, and our own to manage)

A mod "runs with the same access to your machine as Claude Code itself" - it sees every prompt,
every tool call and your environment variables, can approve tool calls, and can spend your usage.
The public directory lists 1,432 community builds, classed by an L0-L3 access scale
(read / write / execute / network) **[verified: claudemods.dev, Oct 2026]**. So:
- Studio asks for the **minimum**: no network, `$.fs` limited to the palace folder, one MCP server.
- `cc mods audit <dir>` wraps `claude plugin validate` and lists every event, `$` call, env and
  network use **before** you install anything - useful for third-party mods too.
- We install nothing without your explicit yes; `claude --plugin-dir` loads it for one session first.
- Degrades cleanly: Studio checks `$.session.version()` and `$.session.surfaces()`.

## 4. Swarm - subagents and sessions

### 4.1 Sessions talking to each other
Native and available to you **now** (Windows needs v2.1.234+; you have 2.1.29x). Cortex adds:
- **a shared blackboard in L0** - sessions coordinate through *data* ("task 7 claimed", "schema
  changed, see memory M-482") rather than free chat, because plain-text messaging is
  loop-throttled and can be held for approval; a message can point to a memory id instead of
  pasting context;
- **handoff packets** (goal, state, files, pointers) written to the palace and referenced in a message;
- a safe default: `crossSessionInbound: hold` for sessions that bypass permissions (Claude Code's
  own default already does this for bypass sessions);
- an **inbox feed** in the Console pane (`session.receive` events);
- cross-account messaging between your three profiles on one machine - **[unverified]**: the
  socket is per OS user, so it should work, but it needs a real two-profile test.

### 4.2 Subagent improvements that are genuinely available
1. **Memory-aware subagents.** Today they inherit no memory. At `agent.spawn`, inject a slice
   chosen by role (reviewer: rules + past failures; implementer: blueprint + recipes; scout: nothing).
2. **Model routing policy** enforced at `agent.spawn`: cheap model for search/exploration, strong
   model for design/review, with your overrides and a running "tokens saved" counter.
3. **Result contracts**: shipped subagent definitions (explorer, implementer, verifier, scribe,
   red-team) with strict, short output formats so results return as digests, not transcripts.
4. **Scribe agent**: after a turn, a small/local model distils the episode into L2 in the background.
5. **Board + guard**: live status, per-agent token cap, and a stop button; respects the native
   limits (20 concurrent, depth 3).

## 5. Phased plan

| Phase | Deliverable | Done when |
|---|---|---|
| **P0** Evidence | Evaluation harness + corpus + baseline score of today's palace | Baseline recall@k / false-injection recorded; test gate in suite |
| **P1** Store | SQLite schema, FTS5, non-destructive migration, `cc palace` parity, Markdown export | All current commands work on the new store; migration dry-run clean; old files untouched |
| **P2** Retrieval | Fusion + scoring + token-budget packing + feedback log; extended prompt hook | Beats the baseline on the corpus, with fewer injected tokens |
| **P3** Memory lifecycle | Supersession, decay, consolidation, scribe, compaction save/restore | Knowledge-update cases pass; nothing deleted silently |
| **P4** Studio v1 | Plugin: palace pane, band, theme pack, status line, `cc mods audit` | Loads under `--plugin-dir`; `claude plugin validate` clean; tests via `claude plugin test` |
| **P5** Studio v2 | Console + agents board, layout presets, `cc layout`, scene pane | Idle CPU near zero; works on terminal and Desktop |
| **P6** Swarm | Role-scoped injection, routing policy, agent set, blackboard, handoff | Two-profile message test passes; routing shows measured savings |
| **P7** Optional | Local embeddings; entity graph views; Evidence Gate / Sidecar | Only if P2 shows keyword + graph is not enough |

Order is deliberate: **measurement first** (P0), because the previous palace "worked" only in
the sense that it ran.

## 6. Decisions I need from you

1. **SQLite as the source of truth** (Markdown becomes an export). Recommended yes.
2. **Embeddings**: off by default, optional later through your local llama.cpp. OK?
3. **Studio first or Palace first?** Recommended Palace P0-P3, because Studio's pane has little
   to show until the data layer is real; but a theme pack + status line are a quick win we can
   ship first if you want visible progress today.
4. Which surface is primary for you - **Desktop Code tab** or the terminal? It changes which
   mod elements (`Svg`/`Client` vs `Raster`) we build first.

## 7. Not verified / risks

- Whether the Desktop Code tab draws every pane/band exactly like the terminal - docs say yes
  except terminal-only elements; needs a real look.
- Latency of `$.mcp.call` per turn - must be measured against the 10 s hook budget.
- Cross-account messaging (4.1) and reading Claude's own background-task list from a mod.
- Local small models as the scribe/reranker: quality unmeasured on your 6 GB GPU.
- Mods are new (Anthropic shipped 2.1.287 on 2026-10-01) and the API "can change between
  releases"; Studio must pin a tested version range and use the generated type files.

## Sources

- Mods: https://code.claude.com/docs/en/plugins/mods/overview , /create , /interface , /api , /reference
- Cross-session messaging: https://code.claude.com/docs/en/cross-session-messaging
- Subagents: https://code.claude.com/docs/en/sub-agents
- Themes & terminal: https://code.claude.com/docs/en/terminal-config
- Native memory: https://code.claude.com/docs/en/memory
- Mod directory (community, unvetted): https://claudemods.dev/en/
- Anthropic, Contextual Retrieval: https://anthropic.com/news/contextual-retrieval
- Zep / Graphiti temporal knowledge graph: https://arxiv.org/abs/2501.13956
- Generative Agents (recency/importance/relevance, reflection): https://arxiv.org/abs/2304.03442
- A-MEM (Zettelkasten-style linked memory): https://arxiv.org/abs/2502.12110
- Letta / MemGPT (tiered memory): https://www.letta.com
