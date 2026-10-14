#!/usr/bin/env python3
"""
Claude Cortex - session lifecycle hook (SessionStart, SessionEnd, Stop).

Three small jobs, each independent and each failing open (a hook must never get in the way):

SessionStart
  * Register the session, so the floating project-map button appears while a session is open in a
    project that has a Graphify graph or a palace (and disappears after the last one closes).
  * When the context was compacted or cleared (``source`` is "compact" or "clear"), tell the palace.
    What it showed earlier is no longer in front of the model, so it may be shown again - including
    the always-on core. Without this the palace would keep refusing to repeat itself, and a long
    session would slowly lose its memory after each compaction.

SessionEnd
  * Unregister the session.

Stop  (opt-in: ``cc palace ground on``)
  * Look for files and functions in Claude's last answer that do not exist in the project, and say so
    once, so they are corrected before anyone relies on them. High precision by design: see
    cortex/palace/ground.py for what it will and will not report.

Prints nothing unless the Stop check has something to say.
"""

import json
import os
import sys

sys.dont_write_bytecode = True


def core_dir():
    """The Cortex core: the installed copy first, then the checkout this file lives in."""
    for base in (os.path.expanduser("~/.claude/cortex-core"),
                 os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        if os.path.isdir(os.path.join(base, "cortex")):
            return base
    return None


def session_start(payload):
    from cortex.atlas import sessions
    from cortex.palace import hook as palace_hook
    from cortex.palace import store as palace_store
    sid = payload.get("session_id")
    cwd = payload.get("cwd") or os.getcwd()
    if payload.get("source") in ("compact", "clear"):
        palace_hook.reset_session(cwd, sid)
    if sid:
        sessions.register_session(sid, cwd)
    _key, root = palace_store.project_identity(cwd)
    sessions.ensure_button(root)


def session_end(payload):
    from cortex.atlas import sessions
    if payload.get("session_id"):
        sessions.end_session(payload["session_id"])


def stop(payload):
    from cortex.atlas import sessions
    from cortex.palace import hook as palace_hook
    if payload.get("stop_hook_active"):                 # if Claude Code tells us we are already continuing: stop
        return None
    note = palace_hook.grounding_note(payload.get("last_assistant_message") or "", cwd=payload.get("cwd"))
    if not note:
        return None
    # The documentation names no loop protection for Stop hooks, so ours does not rely on a field that may
    # not exist: at most one correction per user prompt (the documented prompt_id), recorded on disk.
    if payload.get("session_id") and not sessions.claim_correction(payload["session_id"], payload.get("prompt_id")):
        return None
    return {"decision": "block", "reason": note}


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0
    base = core_dir()
    if not base:
        return 0
    if base not in sys.path:
        sys.path.insert(0, base)
    event = payload.get("hook_event_name")
    try:
        if event == "SessionStart":
            session_start(payload)
        elif event == "SessionEnd":
            session_end(payload)
        elif event == "Stop":
            answer = stop(payload)
            if answer:
                print(json.dumps(answer))
    except Exception:
        pass                                            # fail open, whatever happened
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        sys.exit(0)
