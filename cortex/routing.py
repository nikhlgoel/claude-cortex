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

# Patterns are intent phrases, not topic words. "depends on", "architecture", "css selector",
# "xss" and "crawls" all appear in ordinary work far more often than in the cases they were
# meant to catch; an earlier, looser version put a wrong hint on 12 of 25 everyday prompts.
_ARTICLE = r"(?:the |this |that |a |an |all |every |these |those |my |our |some )?"

_SCRAPE = re.compile(
    r"\bscrap(?:e|ing)\b"
    r"|\bcrawl(?:ing)?\s+" + _ARTICLE + r"(?:\w+\s+)?(?:web ?sites?|sites?|pages?|domains?|urls?|links?)\b"
    r"|\b(?:write|build|create|need|want|implement|make)\s+(?:a|an)\s+(?:web ?)?(?:scraper|crawler|spider)\b"
    r"|\bextract\s+(?:the |all |some )?[\w ]{1,30}?\s+from\s+" + _ARTICLE +
    r"(?:web ?site|web ?page|url|https?://)"
    r"|\b(?:fetch|download|grab)\s+" + _ARTICLE + r"(?:html (?:of|from) )?" + _ARTICLE +
    r"(?:web ?page|web ?site|https?://\S+)", FLAGS)

_GRAPH = re.compile(
    r"\b(?:who|what)\s+calls\b"
    r"|\b(?:who|what)\s+invokes\b"
    r"|\bcall(?:er|ee)s?\s+of\b"
    r"|\bcall[- ]graph\b|\bcall\s+(?:chain|tree|hierarchy)\b"
    r"|\b(?:dependency|import|dependent|inheritance|class)\s+graph\b"
    r"|\b(?:find|list|show|get)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?(?:usages|callers|references|dependents|call ?sites)\s+(?:of|for|to)\b"
    r"|\bwhere\s+is\s+[`'\"]?[A-Za-z_][\w.]*[`'\"]?\s+(?:called|referenced|imported)\b"
    r"|\bwhat\s+(?:modules|files|classes|functions|packages)\s+(?:depend|import|call|use)\b"
    r"|\b(?:impact|blast radius)\s+of\s+(?:renaming|removing|deleting|changing)\s+(?:the\s+)?"
    r"(?:[\w.]+\s+)?(?:function|class|method|module|package|api|symbol|interface)\b", FLAGS)

# A "dependency graph" in package-manager context is about versions, not code structure.
_GRAPH_VETO = re.compile(
    r"package(?:-lock)?\.json|requirements\.txt|pyproject|lockfile|lock file|version conflict|"
    r"\b(?:npm|pip|yarn|pnpm|cargo|gradle|maven|composer)\b|pom\.xml|go\.mod", FLAGS)

# Search engines "crawling" a site is SEO, not the person asking for a scraper.
_SCRAPE_VETO = re.compile(r"search engines?|googlebot|\bseo\b|robots\.txt|sitemap|\bindex(?:ed|ing)\b", FLAGS)

_SPEC = re.compile(r"\bspec[- ]?kit\b|\bspeckit\b|\bspec[- ]driven\b", FLAGS)

_SECURITY = re.compile(
    r"\bsecurity\s+(?:review|audit|assessment|scan)\b"
    r"|\b(?:review|audit|scan|check)\b.{0,40}\bfor\s+(?:security|vulnerabilit(?:y|ies)|injection|xss|csrf)\b"
    r"|\bthreat\s+model\b|\bpen[- ]?test\b", FLAGS)

_REVIEW = re.compile(
    r"\bcode review\b|\breview (?:my|this|the|these|that) (?:code|changes?|diff|pr|pull request|commit)\b", FLAGS)

#: Only the start and end of a long prompt are read: the ask is almost always there, and a
#: long prompt is usually pasted logs or code whose words must not trigger anything.
WINDOW = 300
LONG_PROMPT = 1200


def _window(text):
    """The part of a prompt worth reading. Short prompts are read whole.

    A long prompt is usually an ask plus pasted logs or code. The ask is its first or its
    last line, so only those are read - a middle full of pasted words must not trigger anything.
    """
    if len(text) <= LONG_PROMPT:
        return text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 3:
        return lines[0][:WINDOW] + " " + lines[-1][:WINDOW]
    return text[:WINDOW] + " " + text[-WINDOW:]


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
    # (name, pattern, veto pattern or None, is the tool available, hint)
    ("scrape", _SCRAPE, _SCRAPE_VETO, _which_any("scrapling-mcp", "scrapling"), _scrape_hint),
    ("graph", _GRAPH, _GRAPH_VETO, _which_any("graphify-mcp", "graphify"), _graph_hint),
    ("spec", _SPEC, None, _which_any("specify"), _spec_hint),
    ("security", _SECURITY, None, _ecc, _security_hint),
    ("review", _REVIEW, None, _ecc, _review_hint),
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
    scanned = _window(text)
    ctx = {"which": which, "exists": exists, "cwd": cwd, "env": env}
    for name, pattern, veto, available, hint in ROUTES:
        if pattern.search(scanned) and not (veto and veto.search(scanned)) and available(ctx):
            return name, hint(ctx)
    return None, None


def hint_for(prompt, cwd=None, **kwargs):
    """The one-line context to add for ``prompt``, or None."""
    name, hint = match(prompt, cwd, **kwargs)
    return f"[Cortex route: {name}] {hint}" if name else None
