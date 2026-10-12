"""Tool routing: nudge the model toward the specialised tool a prompt clearly calls for.

Claude's built-in skills are general; Scrapling (web fetching), Graphify (code knowledge
graph), Spec Kit (spec-driven features) and ECC's reviewer agents each do one job well,
but a model only reaches for them if something reminds it they exist. This module is that
reminder - and it is deliberately dull:

* **Deterministic.** Regular expressions over the prompt text. No model call, no network,
  no learning. The same prompt always yields the same answer, and the table below is the
  whole behaviour.
* **Only when it fits.** A hint needs both a clear match AND the tool actually being
  present (on PATH, or its plugin installed). A hint for a tool that is not there would
  send the model chasing something unusable.
* **Cheap.** At most one hint of a couple of sentences, and nothing at all when nothing
  matches - so the cost scales with relevance, not with every request, unlike an
  always-on rules file.
* **Never in the way.** The caller adds it as context; it can never block or alter the
  prompt. ``CORTEX_ROUTING=off`` disables it.

False positives cost ~40 tokens, so the patterns lean toward precision: phrases that
unambiguously name the job, not single common words.
"""

from __future__ import annotations

import os
import re
import shutil

FLAGS = re.IGNORECASE
MIN_WORDS = 4

_SCRAPE = re.compile(
    r"\b(scrap(e|es|ed|ing|er)|crawl(s|ed|er|ers|ing)?|web ?spider|headless browser|"
    r"extract (the |all |some )?(data|text|links|prices?|tables?|emails?) from (a |an |the |this |that )?"
    r"(web ?)?(site|page|url|html)|(fetch|download|grab|pull) (the |this |that )?(web ?)?(page|site|url|html)|"
    r"css selectors?|xpath|parse (the |this )?html)\b", FLAGS)

_GRAPH = re.compile(
    r"\b(who calls|what calls|callers? of|callees? of|call graph|dependency graph|dependents? of|"
    r"what depends on|depends on|architecture (overview|of)|how (do|does) .{3,60} (fit|connect|relate)|"
    r"impact of (changing|modifying|removing|renaming)|where is .{2,50} (used|called|referenced)|"
    r"(shortest )?path between|trace (the )?(flow|path|calls?))\b", FLAGS)

_SPEC = re.compile(
    r"\b(spec[- ]?kit|speckit|write (a |the )?spec\b|spec(ification)? for|constitution for|"
    r"spec[- ]driven)\b", FLAGS)

_SECURITY = re.compile(
    r"\b(security (review|audit)|audit .{2,40} (for )?(security|vulnerabilit)|vulnerabilit(y|ies)|"
    r"owasp|sql injection|xss|csrf|path traversal)\b", FLAGS)

_REVIEW = re.compile(
    r"\b(code review|review (my|this|the|these|that) (code|changes?|diff|pr|pull request|commit))\b", FLAGS)


def _config_root(env):
    return env.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def _has_ecc(env, exists):
    root = _config_root(env)
    return exists(os.path.join(root, "plugins", "cache", "ecc")) \
        or exists(os.path.join(os.path.expanduser("~"), ".claude", "plugins", "cache", "ecc"))


def _scrape_hint(_ctx):
    return ("Web fetching/scraping: use the Scrapling skill (scrapling-official) or its MCP tools "
            "if registered, not ad-hoc curl or BeautifulSoup scripts. Try the plain fetcher "
            "first and escalate to the dynamic or stealth fetchers only if the page needs it.")


def _graph_hint(ctx):
    if ctx["exists"](os.path.join(ctx["cwd"] or ".", "graphify-out", "graph.json")):
        return ("Code-structure question: query the Graphify graph (the graphify MCP tools, e.g. "
                "query / path / explain; graph at graphify-out/graph.json) before grepping or "
                "reading many files.")
    return ("Code-structure question: no Graphify graph exists in this folder yet. Build it once "
            "with the /graphify command, then query it (graphify MCP tools) instead of grepping "
            "across many files.")


def _spec_hint(_ctx):
    return ("Spec-driven work: use Spec Kit - /speckit-specify, then /speckit-plan, "
            "/speckit-tasks and /speckit-implement - rather than free-form planning.")


def _security_hint(_ctx):
    return "Security review: delegate to the ecc:security-reviewer agent rather than reviewing inline."


def _review_hint(_ctx):
    return "Code review: delegate to the ecc:code-reviewer agent rather than reviewing inline."


def _which_any(*names):
    return lambda ctx: any(ctx["which"](n) for n in names)


def _ecc(ctx):
    return _has_ecc(ctx["env"], ctx["exists"])


# Order is priority: the first route that matches AND is available wins.
ROUTES = (
    ("scrape", _SCRAPE, _which_any("scrapling-mcp", "scrapling"), _scrape_hint),
    ("graph", _GRAPH, _which_any("graphify-mcp", "graphify"), _graph_hint),
    ("spec", _SPEC, _which_any("specify"), _spec_hint),
    ("security", _SECURITY, _ecc, _security_hint),
    ("review", _REVIEW, _ecc, _review_hint),
)


def match(prompt, cwd=None, which=shutil.which, exists=os.path.exists, env=None):
    """``(route_name, hint)`` for the first matching, available route, else ``(None, None)``."""
    env = os.environ if env is None else env
    if env.get("CORTEX_ROUTING", "").lower() in ("off", "0", "false", "no"):
        return None, None
    text = (prompt or "").strip()
    # Slash/bang commands are the user's own routing; very short prompts carry no signal.
    if not text or text[0] in "/!" or len(text.split()) < MIN_WORDS:
        return None, None
    ctx = {"which": which, "exists": exists, "cwd": cwd, "env": env}
    for name, pattern, available, hint in ROUTES:
        if pattern.search(text) and available(ctx):
            return name, hint(ctx)
    return None, None


def hint_for(prompt, cwd=None, **kwargs):
    """The one-line context to add for ``prompt``, or None."""
    name, hint = match(prompt, cwd, **kwargs)
    return f"[Cortex route: {name}] {hint}" if name else None
