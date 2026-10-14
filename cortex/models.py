"""
Model catalog - live, not a hand-maintained table of guesses.

The old catalog was 22 models with prices typed into a source file. Prices and
availability change, so it was wrong the moment it was written and drifted from
there; annotating it "snapshot" made it honest but not correct.

This fetches OpenRouter's public models API (no auth, free) and caches the
result. OpenRouter carries real per-token prices for the models you can actually
switch to via the provider fallback, so those are shown as fact.

Claude's own subscription models are listed separately and WITHOUT a per-token
price, because there isn't one that means anything: on a Pro/Max subscription you
pay the subscription, not per token. Printing a per-token figure there would be
the same fabrication the old table committed.

Offline behaviour: a cached copy (six-hour TTL) is used when the network is
unavailable, and its age is shown. With no cache and no network, the command says
so rather than inventing data.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

from . import jsonfile
from .paths import shared_claude_dir

OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_SECONDS = 6 * 3600
FETCH_TIMEOUT = 12

# Claude models reachable on a subscription (OAuth), where per-token price is not
# the relevant number. Kept minimal and labelled; not a pricing claim.
#
# IDs are Anthropic's exact strings. Every one is reachable from a launcher flag
# (see launcher.MODEL_ALIASES); tests/test_core_fixes.py keeps the two in step so
# the catalog never advertises a model ``cc`` cannot select.
SUBSCRIPTION_MODELS = [
    ("claude-fable-5-1", "Fable 5.1", "most capable (cc --fable)"),
    ("claude-fable-5", "Fable 5", "previous Fable (cc --fable-5)"),
    ("claude-opus-5-5", "Opus 5.5", "current Opus (cc --opus-5-5)"),
    ("claude-opus-5", "Opus 5", "deepest reasoning (cc -o)"),
    ("claude-sonnet-5-5", "Sonnet 5.5", "current Sonnet (cc --sonnet-5-5)"),
    ("claude-sonnet-5", "Sonnet 5", "best all-round coding (cc -s)"),
    ("claude-haiku-4-5", "Haiku 4.5", "fast and cheap (cc -H)"),
]


def _cache_path():
    return os.path.join(shared_claude_dir(), "cache", "openrouter-models.json")


def _read_cache():
    try:
        with open(_cache_path(), encoding="utf-8") as fh:
            blob = json.load(fh)
        return blob.get("fetched_at", 0), blob.get("models", [])
    except (OSError, ValueError):
        return 0, []


def _write_cache(models):
    # jsonfile.write is atomic with a unique temp name, so two `cc model` runs
    # at once cannot trample one shared ".tmp" file. A cache needs no backup.
    jsonfile.write(_cache_path(),
                   {"fetched_at": int(time.time()), "models": models}, backup=False)


def fetch(force=False):
    """Return (models, source) where source is 'live', 'cache', or 'none'.

    Uses a fresh cache without hitting the network; fetches when the cache is
    stale or forced; falls back to a stale cache when the network fails.
    """
    fetched_at, cached = _read_cache()
    fresh = cached and (time.time() - fetched_at) < CACHE_TTL_SECONDS
    if fresh and not force:
        return cached, "cache"

    try:
        request = urllib.request.Request(
            OPENROUTER_URL, headers={"User-Agent": "claude-cortex"})
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as resp:
            data = json.load(resp)
        models = data.get("data", [])
        if models:
            _write_cache(models)
            return models, "live"
    except (OSError, ValueError):
        pass

    # Network failed. A stale cache still beats nothing, clearly labelled.
    if cached:
        return cached, "cache"
    return [], "none"


def _price_per_million(pricing, key):
    """OpenRouter prices are per token as strings; show $/1M for readability."""
    try:
        return float(pricing.get(key, 0)) * 1_000_000
    except (TypeError, ValueError):
        return None


def _is_free(model):
    pricing = model.get("pricing") or {}
    try:
        return float(pricing.get("prompt", 1)) == 0 and \
            float(pricing.get("completion", 1)) == 0
    except (TypeError, ValueError):
        return False


def render(free_only=False, query=None, force=False, limit=40):
    models, source = fetch(force=force)
    lines = ["=" * 78, "  Model catalog", "=" * 78]

    # Subscription models first - what most sessions actually run under.
    lines.append("")
    lines.append("  CLAUDE (via your subscription - no per-token price applies)")
    for model_id, name, note in SUBSCRIPTION_MODELS:
        lines.append(f"    {name:<12} {model_id:<20} {note}")

    lines.append("")
    if source == "none":
        lines.append("  OPENROUTER: offline and no cached catalog.")
        lines.append("  Connect once to populate it, then it works offline for 6h.")
        lines.append("=" * 78)
        return "\n".join(lines), True

    _, fetched_at = (None, _read_cache()[0])
    age = int(time.time() - fetched_at) if fetched_at else 0
    tag = "live" if source == "live" else f"cached {age // 60}m ago"
    lines.append(f"  OPENROUTER ({tag}) - real per-token pricing, $/1M tokens")

    shown = models
    if free_only:
        shown = [m for m in shown if _is_free(m)]
    if query:
        q = query.lower()
        shown = [m for m in shown
                 if q in m.get("id", "").lower() or q in m.get("name", "").lower()]

    # Free first, then by prompt price ascending.
    def sort_key(m):
        p = m.get("pricing") or {}
        try:
            return (0 if _is_free(m) else 1, float(p.get("prompt", 999)))
        except (TypeError, ValueError):
            return (1, 999)
    shown = sorted(shown, key=sort_key)

    lines.append("")
    lines.append(f"    {'MODEL':<44}{'CTX':>9}  {'IN':>8}  {'OUT':>8}")
    for model in shown[:limit]:
        pricing = model.get("pricing") or {}
        model_id = model.get("id", "?")[:43]
        ctx = model.get("context_length") or 0
        if _is_free(model):
            in_p, out_p = "free", "free"
        else:
            pin = _price_per_million(pricing, "prompt")
            pout = _price_per_million(pricing, "completion")
            # OpenRouter reports -1 for router models whose price depends on the route taken.
            in_p = "varies" if pin is not None and pin < 0 else (f"${pin:.2f}" if pin is not None else "?")
            out_p = "varies" if pout is not None and pout < 0 else (f"${pout:.2f}" if pout is not None else "?")
        ctx_str = f"{ctx // 1000}k" if ctx else "-"
        lines.append(f"    {model_id:<44}{ctx_str:>9}  {in_p:>8}  {out_p:>8}")

    total = len(shown)
    if total > limit:
        lines.append(f"    ... {total - limit} more (use a filter, e.g. 'cc model free'"
                     f" or 'cc model <search>')")
    lines.append("")
    lines.append(f"  {total} model(s){' (free only)' if free_only else ''}. "
                 f"Use one: cc provider set openrouter && "
                 f"cc provider model openrouter <id>")
    lines.append("=" * 78)
    return "\n".join(lines), True


def main(args):
    import sys

    force = "--refresh" in args or "--force" in args
    positional = [a for a in args if not a.startswith("-")]
    action = positional[0] if positional else "list"

    if action in ("list", "ls"):
        report, _ = render(force=force)
        print(report)
        return 0
    if action == "free":
        report, _ = render(free_only=True, force=force)
        print(report)
        return 0
    if action == "refresh":
        models, source = fetch(force=True)
        print(f"Fetched {len(models)} models ({source}).")
        return 0 if source == "live" else 1
    if action in ("search", "find") and len(positional) > 1:
        report, _ = render(query=positional[1], force=force)
        print(report)
        return 0
    # A bare word is treated as a search term.
    if action not in ("set", "info", "tui"):
        report, _ = render(query=action, force=force)
        print(report)
        return 0

    print("Usage: cc model [list|free|refresh|<search>]", file=sys.stderr)
    return 2
