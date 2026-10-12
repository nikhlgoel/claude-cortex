"""Pure request/response shaping between Claude Code and a local llama-server.

llama-server speaks the Anthropic Messages API natively, but not faithfully enough
for Claude Code. Each function here fixes one verified gap and is deterministic and
free of I/O, so it is unit-tested without a model. The gateway
(``scripts/cortex-gateway.py``) is the only caller.

Gaps handled (observed against llama.cpp b11xxx, see docs/LOCAL_MODELS.md):

* Anthropic-only request fields that a local server rejects or ignores.
* ``tool_result`` blocks must precede text in a user message (llama.cpp PR #29482).
* Several chat templates (Qwen3.5/3.6) assert "System message must be at the
  beginning" - Claude Code injects ``system`` role messages mid-conversation.
* Claude Code sends ``temperature=1``; code models want a low one.
* There is no adaptive thinking locally, so Claude Code's effort level is translated
  into an explicit thinking-token budget.
* A context overflow comes back as a generic 400; Claude Code only compacts when it
  sees "Prompt is too long".
"""

from __future__ import annotations

import json
import math

#: Top-level request fields that exist only on Anthropic's API.
ANTHROPIC_ONLY_FIELDS = ("output_config", "context_management", "container", "mcp_servers",
                         "service_tier", "betas", "speed", "inference_geo")

#: Per-tool / per-block fields a local server does not understand.
TOOL_ONLY_FIELDS = ("defer_loading", "strict", "cache_control", "eager_input_streaming",
                    "allowed_callers", "input_examples")

#: Effort levels Claude Code can send, lowest first. "ultracode" is NOT one of them:
#: it is a client-side orchestration mode, not a request parameter.
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")

#: Spellings people use for a level. "ultracode" maps to the highest real level.
EFFORT_ALIASES = {"ultracode": "max", "ultra": "max", "off": "low", "none": "low",
                  "minimal": "low"}

OVERFLOW_MARKERS = ("exceeds the available context", "context size", "n_ctx",
                    "exceed_context_size", "prompt is too long", "too many tokens")

THINKING_HEADROOM = 1024     # always leave this many tokens for the visible answer


# ------------------------------------------------------------------- field hygiene

def strip_anthropic_fields(req):
    """Return a copy of ``req`` with Anthropic-only fields removed.

    Also drops ``cache_control`` (and friends) from system blocks, message content
    blocks and tool definitions. The caller's dict is not modified.
    """
    out = {k: v for k, v in req.items() if k not in ANTHROPIC_ONLY_FIELDS}

    def clean(node):
        if isinstance(node, dict):
            return {k: clean(v) for k, v in node.items() if k not in TOOL_ONLY_FIELDS}
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    for key in ("system", "messages", "tools"):
        if key in out:
            out[key] = clean(out[key])
    return out


# -------------------------------------------------------------- message normalising

def _as_blocks(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    return list(content or [])


def _system_text(msg):
    return "\n".join(b.get("text", "") for b in _as_blocks(msg.get("content"))
                     if isinstance(b, dict) and b.get("type") == "text").strip()


def _reminder(texts):
    return {"type": "text", "text": "<system-reminder>\n" + "\n\n".join(texts) + "\n</system-reminder>"}


def fold_system_messages(messages):
    """Fold ``role: system`` messages into the neighbouring user message.

    They must NOT be hoisted to the start: that rewrites the prompt prefix and the
    server's prompt cache misses on every turn, turning each step into a full
    prefill. Folding keeps everything before the message byte-identical.
    """
    out = []
    pending = []
    for msg in messages:
        if msg.get("role") == "system":
            text = _system_text(msg)
            if text:
                pending.append(text)
            continue
        if pending and msg.get("role") == "user":
            msg = {**msg, "content": _as_blocks(msg.get("content")) + [_reminder(pending)]}
            pending = []
        out.append(msg)
    if pending:
        # Trailing system text with no user message after it: attach to the last user turn.
        for i in range(len(out) - 1, -1, -1):
            if out[i].get("role") == "user":
                out[i] = {**out[i], "content": _as_blocks(out[i].get("content")) + [_reminder(pending)]}
                break
        else:
            out.append({"role": "user", "content": [_reminder(pending)]})
    return out


def reorder_tool_results(messages):
    """In every user message put ``tool_result`` blocks before any other block.

    Anthropic's API requires it and llama.cpp's converter assumes it; Claude Code can
    emit a text block (a system reminder) ahead of the results.
    """
    out = []
    for msg in messages:
        content = msg.get("content")
        if msg.get("role") == "user" and isinstance(content, list):
            results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
            if results and content[:len(results)] != results:
                rest = [b for b in content if not (isinstance(b, dict) and b.get("type") == "tool_result")]
                msg = {**msg, "content": results + rest}
        out.append(msg)
    return out


def normalise_messages(messages):
    return reorder_tool_results(fold_system_messages(messages))


# ---------------------------------------------------------------------- sampling

def apply_sampling(req, sampling):
    """Override client sampling with the model's recommended values.

    Claude Code sends ``temperature=1``. For a local code model that is much too
    hot; the values come from the catalog entry, never a guess here.
    """
    out = dict(req)
    for key, value in (sampling or {}).items():
        if value is not None:
            out[key] = value
    return out


def pick_sampling(sampling, thinking):
    """Choose the sampling set for this request.

    ``sampling`` is either flat (``{"temperature": ...}``) or split into ``think`` and
    ``plain`` sets, which model vendors publish separately.
    """
    if sampling and ("think" in sampling or "plain" in sampling):
        return sampling.get("think" if thinking else "plain") or {}
    return sampling or {}


# ---------------------------------------------------------------------- reasoning

def normalise_effort(value):
    """Map whatever the client sent onto one of EFFORT_ORDER, or None if absent/unknown."""
    if not value:
        return None
    value = str(value).strip().lower()
    value = EFFORT_ALIASES.get(value, value)
    return value if value in EFFORT_ORDER else None


def request_effort(req, default=None):
    """The effort a request asks for, from ``output_config.effort``, else ``default``."""
    cfg = req.get("output_config")
    if isinstance(cfg, dict):
        found = normalise_effort(cfg.get("effort"))
        if found:
            return found
    return normalise_effort(default)


def _is_reminder(block):
    return (block.get("text") or "").lstrip().startswith("<system-reminder>")


def classify_turn(messages):
    """Return ``"start"``, ``"cont"`` or ``"on_error"`` for the request about to run.

    * start    - the last user message carries real text from the person.
    * cont     - it is only ``tool_result`` blocks (the model is mid-task).
    * on_error - as ``cont`` but at least one result has ``is_error`` set.

    System reminders do not count as person-authored text.
    """
    last = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if last is None or not isinstance(last.get("content"), list):
        return "start"
    blocks = [b for b in last["content"] if isinstance(b, dict)]
    results = [b for b in blocks if b.get("type") == "tool_result"]
    others = [b for b in blocks if b.get("type") != "tool_result"
              and not (b.get("type") == "text" and _is_reminder(b))]
    if results and not others:
        return "on_error" if any(b.get("is_error") for b in results) else "cont"
    return "start"


def thinking_budget(effort, turn, levels, max_tokens):
    """Tokens of thinking to allow, or 0 for none. Always leaves THINKING_HEADROOM.

    ``levels`` is the ``reasoning.levels`` table from the config. An unknown effort
    means no thinking - an unrecognised level is never silently upgraded.
    """
    if effort is None:
        return 0
    budget = int(((levels or {}).get(effort) or {}).get(turn, 0) or 0)
    if budget <= 0:
        return 0
    if isinstance(max_tokens, int) and max_tokens > 0:
        budget = min(budget, max_tokens - THINKING_HEADROOM)
    return max(0, budget)


def apply_reasoning(req, effort, levels, template_kind):
    """Rewrite thinking-related request fields for a local model.

    ``template_kind`` comes from the catalog:

    * ``"qwen3"``   - the chat template honours ``enable_thinking``; sent explicitly on
      EVERY request because the server default is "on" and an absent field would make
      the low levels think anyway.
    * ``"gpt-oss"`` - reasoning level is a template variable (low/medium/high).
    * ``"always"``  - always-thinking model (R1 style); only a budget cap applies.
    * ``"none"``    - non-thinking model; everything thinking-related is removed.

    Returns ``(new_request, info)``; ``info`` describes the decision (logged).
    """
    out = {k: v for k, v in req.items() if k != "thinking"}
    turn = classify_turn(req.get("messages", []))
    budget = thinking_budget(effort, turn, levels, req.get("max_tokens")) if template_kind != "none" else 0
    info = {"effort": effort, "turn": turn, "budget": budget, "template": template_kind}

    kwargs = dict(out.get("chat_template_kwargs") or {})
    if template_kind == "qwen3":
        kwargs["enable_thinking"] = budget > 0
    elif template_kind == "gpt-oss":
        kwargs["reasoning_effort"] = ("high" if budget > 8192 else "medium" if budget > 2048
                                      else "low")
    if kwargs:
        out["chat_template_kwargs"] = kwargs

    if budget > 0:
        out["thinking"] = {"type": "enabled", "budget_tokens": budget}
        # The budget counts against max_tokens; make sure an answer still fits.
        if isinstance(out.get("max_tokens"), int):
            out["max_tokens"] = max(out["max_tokens"], budget + THINKING_HEADROOM)
    return out, info


# ---------------------------------------------------------------- token counting

def estimate_tokens(req):
    """A conservative token estimate for ``/v1/messages/count_tokens``.

    Used only when the server cannot tokenise. It over-counts on purpose (3 chars
    per token): under-counting lets a request run past the context window,
    over-counting merely compacts a little early.
    """
    chars = len(json.dumps({k: req.get(k) for k in ("system", "messages", "tools")},
                           ensure_ascii=False, default=str))
    return max(1, math.ceil(chars / 3))


# ---------------------------------------------------------------------- overflow

def is_overflow(status, body_text):
    """True when an upstream error means "the prompt did not fit"."""
    if status not in (400, 413, 500):
        return False
    low = (body_text or "").lower()
    return any(marker in low for marker in OVERFLOW_MARKERS)


def overflow_error(n_ctx=None):
    """The Anthropic-shaped error Claude Code recognises as a context overflow."""
    detail = f" (the local model's context is {n_ctx} tokens)" if n_ctx else ""
    return {"type": "error",
            "error": {"type": "invalid_request_error",
                      "message": f"Prompt is too long{detail}"}}


# ------------------------------------------------------------------------- driver

def shape_request(req, model_entry, levels, default_effort=None):
    """Apply every request-side fix. Returns ``(request, info)``.

    ``model_entry`` is the model's config/catalog entry; only ``template`` (reasoning
    kind), ``sampling`` and ``alias_target`` are read.
    """
    entry = model_entry or {}
    effort = request_effort(req, default_effort)
    out = strip_anthropic_fields(req)
    out["messages"] = normalise_messages(out.get("messages", []))
    out, info = apply_reasoning(out, effort, levels, entry.get("template", "none"))
    out = apply_sampling(out, pick_sampling(entry.get("sampling"), info["budget"] > 0))
    if entry.get("alias_target"):
        out["model"] = entry["alias_target"]
    return out, info
