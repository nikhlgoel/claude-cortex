# What should Claude Cortex be? Five options

Cortex today is a launcher, a few hooks and a grab-bag of tools. This page is the result of
surveying the landscape (SuperClaude, BMAD, Superpowers, Spec Kit, Ruflo, ECC, claude-code-router,
Aider, OpenHands, Cline and others) and asking what is *missing* rather than what is crowded.
Eight candidates were scored by three independent judges on market fit, feasibility, value to
you and hardware fit (each out of 10, so a maximum of 40 per option).

The scores are a rough ordering, not a measurement: the gap between the leader and the rest is
meaningful, but options 2-5 are within the noise of three judges and should be treated as a
rough tie.

| # | Option | Score /40 | One line |
|---|---|---|---|
| 1 | **Evidence Gate** | 31.7 | "Done" cannot be claimed without deterministic receipts |
| 2 | **Budget Governor** | 27.3 | A real spending / usage-window cap for interactive sessions |
| 3 | **Cortex Shield** | 27.0 | Offline scanner for skills, hooks and MCP servers, with drift alerts |
| 4 | **Decision Memory** | 26.3 | A project that remembers *why*, with evidence, across compactions |
| 5 | **Cortex Sidecar** | 25.3 | A small local model as a citation-verified, token-saving reader |

Also considered and ranked lower: Honest Bench (23.3), Cortex RE (21.3), and full local
Claude Code on a 6 GB GPU (20.0). The last of those is not a framework goal - it is a
capability, and it is now built (see [LOCAL_MODELS.md](LOCAL_MODELS.md)). It ranked last
because of model-quality risk, not poor engineering, and it combines well with option 1.

The recurring weakness in this category is credibility. One popular project's own audit found
most of its 300+ tools were stubs with fabricated savings figures. Whatever you pick, the
design rule that follows is the one this repository already holds: *unknown stays unknown, and
every claim has a receipt.*

---

## 1. Evidence Gate - "done means proven"  (31.7)

**Goal.** A `Stop` hook that stops Claude Code from ending a turn with a "fixed / passing /
done" claim unless receipts show the tests actually ran **after the last edit**, the diff stayed
inside the declared scope, and no vacuous tests or placeholder bodies were added.

**The pain it targets.** The agent says "all tests pass" and you learn an hour later that it
never ran them, ran them before its final edit, or wrote a test that asserts nothing.

**What you get.** Receipts (command, exit code, output hash, git HEAD, diff hash) stored under
`.cc/receipts`; a block that names the exact missing receipt; a two-strike release so it can
never loop; honest "unverifiable" when no test command can be found; AST detectors for
assertion-free tests, skipped tests, `pass`/`TODO` bodies and weakened assertions; an optional
scope contract. Standard library only, no GPU, no model.

**First milestone (~1-2 weeks).** Day one is a logging-only spike to record the *real* Stop
payload and transcript format on your installed Claude Code - neither is verified on that build.
Then: transcript parser, "tests ran after last edit" check, receipt store, two-strike release.
Demo on a toy repo, then replay 10 seeded false completions against 10 honest transcripts and
publish the confusion matrix before building anything else.

**Risks.** False blocks erode trust - the target is at most 5%, and that matters more than the
90% catch target, because a gate that blocks honest work gets switched off. Phrase-matching on
claims can be evaded; this is a safety net against honest over-claiming, not an adversarial
guarantee. Test-command discovery differs by ecosystem.

**Local models.** Needs none, but it is the multiplier for them: small models are expected to
over-claim more (a hypothesis to measure, not a finding), and receipts give any local-model
experiment deterministic graders.

**Choose this if** you want the most defensible payoff for the least hardware and model risk and
you are tired of unproven "done" claims. It improves trust in output; it does not give you a
free local tier.

## 2. Budget Governor - never hit the wall mid-task  (27.3)

**Goal.** An interactive per-task cap, in dollars (API) or percent of the 5-hour / 7-day window
(subscription), enforced by hooks: warn at 70%, checkpoint and stop at 100%.

**Why it is a gap.** Claude Code's own `--max-budget-usd` only works in print mode. The
documented status-line JSON carries cost, context % and, for claude.ai plans, rate limits.

**First milestone (~1-2 weeks).** A status-line collector that writes usage to disk and works
under a profile's config directory; `cc budget start/status`; the 70% warning and 100% block;
reconcile one real session's cost against the status line. First find out which fields *your*
account actually reports - without a claude.ai Pro/Max plan, rate limits are absent.

**Risks.** Anthropic could ship native interactive budgets and erase the point - compete on
enforcement and handoff, not reporting (ccusage exists). Costs are client-side estimates. With
one account today, the multi-profile routing has little to do.

**Local models.** Weakest fit: a local model costs $0, so a dollar cap is moot.

**Choose this if** your pain is surprise cost or the usage window you recently hit.

## 3. Cortex Shield - offline supply-chain scanner  (27.0)

**Goal.** Scan third-party skills, plugins, hooks and MCP servers offline for hidden Unicode,
injection phrasing, credential reads, base64-to-shell and auto-exec surface; pin a baseline and
warn at session start on drift. It never says "safe" - its output is a lower bound with
`file:line:mechanism` evidence.

**Why now.** This machine runs a large plugin with hundreds of skills that nobody has read.
Strong reuse: `integrity.py`, the AST analyzer, the Ghidra baseline/audit/watch pattern.

**First milestone (~1 week, no signing).** `cc audit --installed` over the installed plugin and
every profile, with JSON output and a stored baseline whose diff shows next run; each rule ships
with a benign and a malicious fixture written from public descriptions (no malware downloaded).

**Risks.** The category is crowded (ECC AgentShield, Snyk, academic tools), so the differentiator
must be offline operation, drift alerts and *measured* recall. False positives on hundreds of
skills are a real cost. Static scanning is evadable.

**Local models.** None involved. The one option that makes later local-model work safer
(vet wrappers and MCP servers before trusting them).

**Choose this if** you want the lowest-risk, quickest win and are uneasy about third-party
skills running with your permissions.

## 4. Decision Memory - a project that remembers why  (26.3)

**Goal.** Store decisions and failed approaches with verifiable evidence, inject a
token-capped (~1,500) digest at session start and after compaction, and flag stale or
contradictory entries so the agent stops re-litigating rejected ideas.

**What exists.** A memory palace, instinct store and recall tools - but recall is never
injected and the pre-compact hook prints five fixed lines. This closes that loop.

**First milestone (~2 weeks).** Starts with the Windows fixes (UTF-8 everywhere, a real lock;
both were done in the recent audit), then schema, injector, pre-compact writer and a
simulated-compaction test (5 seeded decisions and 2 failed approaches must survive).

**Risks.** Incumbents: claude-mem (~99k stars) and Claude Code's own memory occupy this space,
so it only justifies itself if a benchmark against them shows a win. The benchmark can cost
more than the build.

**Local models.** CPU-only; the capped injection suits the small contexts a 6 GB GPU forces.

**Choose this if** your recurring annoyance is the agent forgetting why something was decided.

## 5. Cortex Sidecar - a small local model as a reader  (25.3)

**Goal.** The cloud model stays the driver; persistent MCP tools backed by a small local model
digest large logs and files, every line **cited and mechanically verified** (path:line-range
checked against the file; unverifiable lines dropped; "verified N of M citations").

**Why it is different.** The only option that puts your GPU to work, and because the local
model only *summarises*, its weak tool-calling does not matter.

**Built-in kill switch.** It must beat Claude Code's own ranged Read plus a cheap Explore
subagent on tokens at equal correctness, or the feature is dropped. First milestone (~2 weeks)
is a go/no-go answer, not a finished feature.

**Risks.** The built-in baseline may already deliver most of the benefit. Latency on a 3050
may exceed simply reading the file. Everything about model speed must be measured here - and
the local runtime now exists (`cc local`), so this is no longer blocked on installing one.

**Choose this if** you want a real local-model component with bounded risk and prefer a
measured go/no-go over an open-ended build.

---

## The panel's recommendation

> Build **Evidence Gate** first. It is the clear leader, has the best risk profile for your
> machine (no GPU, no installs, no model), and addresses your stated problem of tools
> overstating results. Then **Cortex Sidecar** as the experiment that tells you what your
> hardware can really do - Evidence Gate's receipts supply deterministic graders for any later
> local-model attempt.

Two caveats before committing: the Stop payload and transcript format on your installed Claude
Code are not verified (so day one is a logging spike, and the estimate can change), and the
false-block rate is the metric that decides whether the gate survives.

## Verification status of this research

* Hook, status-line and CLI facts came through a summarising tool from documentation pages that
  were undated; the market statistics (stars, forks) are single-source and approximate.
* Scores come from three judges; treat gaps below ~5 points as ties.
* No local-model speed is claimed anywhere: it is unmeasured until `cc local doctor --smoke`.

This document is a choice for **you**. Nothing here has been started for options 1-5; pick one
and say so.
