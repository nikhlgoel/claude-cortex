# Using the specialised tools automatically

Claude's built-in skills are general. Four tools do one job each and do it better, but a model
only reaches for them if something reminds it they exist:

| Tool | Job | Reached through |
|---|---|---|
| **Scrapling** | fetching and scraping web pages | the `scrapling-official` skill, and `scrapling-mcp` |
| **Graphify** | a code knowledge graph (callers, paths, architecture) | `graphify-mcp`; build the graph with `/graphify` |
| **Spec Kit** | spec-driven feature work | the `/speckit-*` commands, and the `specify` CLI per project |
| **ECC** | reviewer / planner / TDD agents | the ECC plugin's agents (`ecc:code-reviewer`, ...) |

## How a prompt reaches the right one

The prompt hook looks at each prompt with a handful of regular expressions - no model call, no
network. If a prompt clearly names one of these jobs **and that tool is installed**, it adds one
short line of context; otherwise it adds nothing.

| You write something like... | Hint added |
|---|---|
| "scrape the prices from this website", "write a crawler", "css selectors" | use Scrapling, plain fetcher first |
| "who calls load_config", "dependency graph", "impact of renaming X" | query the Graphify graph (or build it first) |
| "use spec kit", "write a spec for ..." | `/speckit-specify`, `-plan`, `-tasks`, `-implement` |
| "code review of my changes" | delegate to `ecc:code-reviewer` |
| "security audit", "SQL injection" | delegate to `ecc:security-reviewer` |

Design rules, all enforced by tests: one hint at most; nothing for ordinary prompts, slash
commands or prompts under four words; never a hint for a tool that is not there; it can never
block or edit your prompt; any failure inside it means "no hint". A false match costs about 40
tokens, so cost follows relevance - unlike an always-on rules file that is paid on every request.
Turn it off with `CORTEX_ROUTING=off`.

## Making the tools available

Cortex never installs anything for you. Installed already (check with `uv tool list`) means:

```
cc mcp add graphify [profile]     # registers graphify-mcp via `claude mcp add --scope user`
cc mcp add scrapling [profile]    # registers scrapling-mcp
```

If a tool is missing, the command prints the `uv tool install ...` line for you to run. Scrapling's
browser-based fetchers additionally need `scrapling install`, which downloads browsers - run that
yourself. Graphify needs a graph per project: build it once with its `/graphify` command, after
which the hint tells the model to query it instead of grepping.

Registration goes through Claude Code's own `claude mcp add` rather than editing `.claude.json`
directly, because Claude Code rewrites that file constantly and a direct edit can lose a race.
For your default account this also matters for another reason: see "One trap" in
[PROFILES.md](PROFILES.md).

## What this does not do

* It does not make a model *obey*; it reminds it. Whether it follows the hint is up to the model.
* It does not measure token savings. The claim is "cost follows relevance", not a number.
* Spec Kit and ECC overlap with some built-in behaviour; the hints are deliberately narrow so
  they do not fire on every "feature" or "review" you mention.
