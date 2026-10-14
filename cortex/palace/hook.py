"""
Prompt-time delivery: put the right memory in front of Claude without being asked.

Called by the UserPromptSubmit hook for every prompt, so the rules are strict:

* **Never create anything.** No palace for this project means no injection, not an empty database.
* **Never block, never raise.** Any problem returns ``None`` and the prompt goes through untouched.
* **Stay silent on thin evidence** (see ``retrieve.py``): most prompts get nothing.
* **Never repeat** a memory within one session; the always-on core appears once, on the first
  injection of a session. Repeating text every turn would cost tokens and break prompt caching.
* **Controllable**: ``CORTEX_PALACE=off`` turns it off everywhere; ``cc palace inject off`` turns it
  off for one project.
"""

from __future__ import annotations

import os

from . import graph, ground, retrieve, write
from . import store as store_mod

DEFAULT_BUDGET = 700
_OFF = {"off", "0", "false", "no", "disable", "disabled"}


def enabled_by_env(env=None):
    return str((env or os.environ).get("CORTEX_PALACE", "")).strip().lower() not in _OFF


def _window(prompt):
    """Long prompts are mostly pasted logs and code; only their opening describes the request."""
    prompt = prompt.strip()
    return prompt if len(prompt) <= 1200 else prompt[:600]


def grounding_note(text, cwd=None, env=None):
    """For the Stop hook: a short note naming files and functions in Claude's last answer that do not
    exist in the project, or None. Opt-in per project (``cc palace ground on``) or by ``CORTEX_GROUND=on``.

    Built to be right when it speaks: only a file that is missing/deleted, or a name with a close
    match (a likely typo or rename), is reported. Library names, generic words and anything it cannot
    check are never reported. Never raises.
    """
    try:
        env = env or os.environ
        if not text or not enabled_by_env(env):
            return None
        cwd = cwd or os.getcwd()
        path = store_mod.db_path("project", cwd)
        if not os.path.isfile(path):
            return None
        _key, root = store_mod.project_identity(cwd)
        st = store_mod.Store(path, create=False)
        try:
            forced = str(env.get("CORTEX_GROUND", "")).strip().lower()
            if forced in _OFF or (forced != "on" and st.meta_get("ground", "off") != "on"):
                return None
            graph.sync(st, root)
            result = ground.verify(st, root, text)
        finally:
            st.close()
        lines = []
        for f in result["files"]:
            if f["status"] in ("missing", "stale"):
                hint = " (closest real file: %s)" % f["suggest"][0] if f.get("suggest") else ""
                lines.append("file %s%s" % (f["path"], hint if f["status"] == "missing" else " (deleted since the graph was built)"))
        for s in result["symbols"]:
            if s["status"] == "missing":
                lines.append("`%s` (closest real name: %s)" % (s["name"], s["suggest"][0]))
        if not lines:
            return None
        return ("Cortex check: these names in your last answer were not found in the project: " + "; ".join(lines[:6]) +
                ". If they are things you are about to create, say so. Otherwise correct them before the user relies on them.")
    except Exception:
        return None


def reset_session(cwd=None, session=None):
    """Called when a session's context was compacted or cleared (the SessionStart hook, source
    ``compact`` / ``clear``). What the palace showed earlier was summarised away or dropped, so the
    next prompt may show it again - including the always-on core, which is otherwise shown once.

    Never raises; returns how many injections were marked, or 0 (also when there is no palace).
    """
    try:
        if not session:
            return 0
        total = 0
        for scope, path in (("project", store_mod.db_path("project", cwd or os.getcwd())),
                            ("global", store_mod.db_path("global"))):
            if not os.path.isfile(path):
                continue
            st = store_mod.Store(path, scope=scope, create=False)
            try:
                total += st.forget_injections(session)
            finally:
                st.close()
        return total
    except Exception:
        return 0


def context_for(prompt, cwd=None, session=None, env=None):
    """The memory block to add to this prompt, or None. Never raises."""
    try:
        return _context_for(prompt, cwd, session, env)
    except Exception:                                   # a hook must fail open, whatever happens
        return None


def _context_for(prompt, cwd, session, env):
    if not enabled_by_env(env) or not prompt:
        return None
    prompt = prompt.strip()
    if not prompt or prompt[0] in "/!":                 # commands are not questions
        return None
    cwd = cwd or os.getcwd()
    _key, root = store_mod.project_identity(cwd)
    for scope, path, project_root in (("project", store_mod.db_path("project", cwd), root),
                                      ("global", store_mod.db_path("global"), None)):
        if not os.path.isfile(path):
            continue
        st = store_mod.Store(path, scope=scope, create=False)
        try:
            if st.meta_get("inject", "on") == "off":
                continue
            write.ensure_index_current(st)
            if project_root:
                graph.sync(st, project_root)
            seen = st.injected_in_session(session) if session else set()
            first = bool(session) and not seen
            budget = int((env or os.environ).get("CORTEX_PALACE_BUDGET") or DEFAULT_BUDGET)
            result = retrieve.recall(st, _window(prompt), budget=budget, project_root=project_root,
                                     skip_ids=seen, include_core=first)
            if result["text"]:
                retrieve.record_injection(st, result, session=session)
                return result["text"]
        finally:
            st.close()
    return None
