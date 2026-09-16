---
name: dream
description: Explore a concept, idea, or decision in depth before acting on it - branching paths, viability, what persists and why, gains and losses, creative reframings. Domain-agnostic; grounds itself in real research first.
argument-hint: <concept or decision> [--lens business,technical,strategic,creative,...]
command: true
---

# Dream — explore a concept before it becomes action

The purpose is to map an idea's full space **before you commit**, so the action you
finally take is the best one available. The output is not a verdict — it is a map
of the decision, honest enough that *you* can pick the path with the most suitable
outcome.

`$ARGUMENTS` is the concept, idea, or decision to explore, optionally followed by
`--lens <names>` to fix which angles to use. If no lens is given, infer the ones
that actually apply — most concepts need several, some need one.

This is not a template. A finding that would read the same for any concept has
failed. Everything below must be specific to *this* concept or it does not belong
on the page.

## Phase 0 — Frame it precisely

Ambiguity here poisons everything after it.

1. Restate the concept in one sharp sentence. If you cannot, that is the first
   finding: the idea is not yet clear enough to evaluate.
2. Name the decision this exploration informs, if there is one ("should I build
   X", "is Y worth pursuing", "which of A/B"). If it is pure exploration, say so.
3. Select the lenses that genuinely apply and say why each is in or out. The
   lenses are tools, not a checklist:
   - **mechanism** — how it actually works, from first principles
   - **viability** — is it sound, or does it collapse under its own assumptions
   - **persistence** — can it last, and under what conditions
   - **branching** — the genuinely different paths it opens
   - **trade-offs** — what each path gains and costs
   - **human / adoption** — who uses it, why, what friction stops them
   - **creative** — the reframing, the 10x-simpler version, the adjacent idea

## Phase 1 — Ground it in reality (research first)

Do this *before* reasoning, so the analysis rests on what is known rather than on
speculation. Speculating about things that are knowable is the failure mode.

- Find prior art and comparable cases. Has this, or something close, been tried?
  What happened to it, and why? Use `cc research <topic>` for technical or
  scientific concepts (real arXiv retrieval), and web search for market,
  competitor, adoption, and precedent signals.
- Pull the numbers that matter if the concept is quantitative — market size,
  unit costs, adoption rates, failure rates of the category.
- Cite what you find. Separate **fact** (with a source) from **inference** (your
  reasoning) explicitly, and never dress one as the other.
- If research turns up little, say so — an absence of prior art is itself
  information (novel, or nobody found it worth doing — and which one matters).

## Phase 2 — Explore across the selected lenses

For each lens in scope, go deep on *this* concept:

- **Mechanism** — walk how it works step by step. Locate the load-bearing
  assumption: the one thing that, if false, sinks it. Most ideas die here.
- **Viability** — build the strongest case FOR it, then the strongest case
  AGAINST. Steelman before you red-team; a red-team of a strawman is worthless.
- **Persistence** — if it lasts, *why* and *where*: what market, what moat, what
  conditions must hold, what compounds in its favour. If it does not, *what
  specifically kills it* and *when* — a competitor, the unit economics, a
  platform it depends on, churn, a shifting regulation. Conditional, not a verdict.
- **Branching** — the two or three genuinely different paths this opens. Real
  forks, not variations of one plan. Where does each lead in a year, in five?
- **Trade-offs** — for each path: what you gain, what you lose, and what you
  cannot undo. Make the cost explicit *before* it is paid.
- **Human / adoption** — who actually adopts it and why; the friction that stops
  the ones who don't. An idea nobody adopts persists at zero.
- **Creative** — the reframing that changes the game, the version with half the
  moving parts, the adjacent concept you would never reach by grinding forward.
  This is where genuinely new value tends to hide.

## Phase 3 — Synthesize into a decision map

Not a recommendation dressed as analysis. A map:

- **The paths**, each with what it costs, what it yields, and what must be true
  for it to work.
- **The crux** — the single question that most determines whether this is worth
  pursuing. Name it, because everything else is secondary to it.
- **Strongest and weakest points** of the whole idea, plainly.
- **What you don't know** that you'd need to, and the cheapest way to find out
  (an experiment, a customer conversation, a prototype) — because the best next
  action is often not "commit" or "drop" but "resolve the crux cheaply."

If a recommendation is genuinely warranted, give it *with* its reasoning and its
conditions. But the goal is to enable your decision, not replace it.

## Phase 4 — Persist

Save the map so the thinking is not lost. Deposit the crux, the paths, and the
conclusion into the memory palace:

```bash
cc remember decisions "<concept>: <one-line crux and direction>"
```

so a later session can recall and revisit it — and reinforce or revise it as
reality comes in.

## The bar

- Specific to this concept, always. Generic observations are noise.
- Grounded where factual; cite, don't speculate about the knowable.
- Honest about uncertainty — name what you don't know rather than confabulate.
- Non-obvious — if the whole output is what the user already knew walking in, it
  failed. The value is in what they could not see from where they stood.
