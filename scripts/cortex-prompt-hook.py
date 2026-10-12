#!/usr/bin/env python3
"""
Claude Cortex - UserPromptSubmit hook.

Two jobs, both narrow on purpose.

1. In-session command interception. A prompt beginning with an explicit `/cc` or
   `!cc` prefix is a Cortex command, not a message for the model. It runs locally
   and the result is shown to the user with zero API tokens spent (exit code 2
   blocks the model and surfaces stderr).

   INTERCEPTION REQUIRES THE PREFIX. Exit code 2 on this event blocks *and
   erases* the prompt, so an over-eager matcher silently destroys user input.
   An earlier version matched bare keywords like "test" and "switch" and any
   prompt starting with "claude"; ordinary requests vanished. Never again.

2. The command is DELEGATED to the one core (`python -m cortex ...`), not routed
   here. This file used to reimplement command dispatch - ~180 lines that drifted
   from the core, so `/cc think` in-session behaved differently from `cc think`
   in the terminal. There is one command surface now, and this hook is a thin
   front for it, the same way the shell wrappers are.

Everything else - a normal development prompt - passes straight through.
"""

import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True


def cortex_command():
    """Return [python, -m, cortex] pointing at the installed core or the checkout."""
    python = sys.executable or "python3"
    for base in (os.path.expanduser("~/.claude/cortex-core"),
                 os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        if os.path.isdir(os.path.join(base, "cortex")):
            return [python, "-m", "cortex"], base
    return None, None


def extract_prompt_text(data):
    """Pull the text out of a prompt payload.

    IDE extensions deliver prompts as nested dicts and multimodal arrays, so the
    text may be buried. Binary/image metadata keys are skipped.
    """
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        parts = [extract_prompt_text(item) for item in data]
        return " ".join(p for p in parts if p).strip()
    if isinstance(data, dict):
        for key in ("prompt", "text", "content", "message", "parts", "messages"):
            if data.get(key):
                text = extract_prompt_text(data[key])
                if text:
                    return text
        chunks = []
        for key, value in data.items():
            if key.lower() in ("type", "mimetype", "encoding", "data",
                               "source", "media_type", "url"):
                continue
            if isinstance(value, str):
                chunks.append(value.strip())
            elif isinstance(value, (list, dict)):
                text = extract_prompt_text(value)
                if text:
                    chunks.append(text)
        return " ".join(chunks).strip()
    return ""


# Commands that print and finish by themselves. Anything else is refused here:
# `login`, `continue`, `--`, `-work`, or a bare profile name would start an
# interactive session or a browser login whose output this hook captures, and
# the hook would then sit waiting on it until the timeout. Those belong in a
# terminal.
NON_INTERACTIVE = frozenset({
    "status", "quota", "capacity", "limits", "switch", "profile", "profiles",
    "doctor", "ide", "integrity", "model", "models", "version", "help", "--help",
    "palace", "remember", "recall", "research", "analyze", "dream-doc", "mcp",
})


def route(args):
    """Return ``(args, None)`` to run, or ``(None, message)`` to refuse."""
    if not args or args[0].lower() not in NON_INTERACTIVE:
        shown = args[0] if args else ""
        return None, (f"cc: '{shown}' starts an interactive session or login, "
                      f"which cannot run inside a prompt hook.\n"
                      f"    Run it in a terminal:  cc {' '.join(args)}".rstrip())
    return args, None


def routing_hint(prompt, cwd):
    """A routing hint for ``prompt`` or None. Any failure means "no hint", never an error."""
    try:
        command, base = cortex_command()
        if not command:
            return None
        if base not in sys.path:
            sys.path.insert(0, base)
        from cortex import routing
        return routing.hint_for(prompt, cwd)
    except Exception:
        return None


def run_cortex(args):
    """Run a Cortex command and return its combined output."""
    command, base = cortex_command()
    if not command:
        return "Cortex core not found. Reinstall Cortex."
    env = dict(os.environ)
    env["PYTHONPATH"] = base
    # The command's output is decoded here, so pin both ends to UTF-8. With the
    # Windows default code page, one non-ASCII character in the output would
    # raise and the hook would fail open - handing the "/cc ..." text to the
    # model as an ordinary prompt and spending tokens on it.
    env["PYTHONUTF8"] = "1"
    try:
        result = subprocess.run(command + args, capture_output=True, text=True,
                                encoding="utf-8", errors="replace",
                                stdin=subprocess.DEVNULL, timeout=120, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"cc: {exc}"
    return (result.stdout or "") + (result.stderr or "")


def main():
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return 0
    if not raw:
        return 0

    try:
        payload = json.loads(raw)
    except ValueError:
        payload = raw

    prompt = extract_prompt_text(payload)
    if not prompt:
        return 0

    tokens = prompt.split()
    head = tokens[0].lower()

    # Only an explicit prefix is a command.
    args = None
    if head in ("/cc", "!cc"):
        args = tokens[1:] if len(tokens) > 1 else ["--help"]
    elif head.startswith("/cc:"):
        # "/cc:status" form
        args = [head.split(":", 1)[1]] + tokens[1:]

    if args is not None:
        runnable, refusal = route(args)
        output = refusal if refusal else run_cortex(runnable)
        # Exit 2 blocks the model and shows stderr to the user, at no token cost.
        print(output.strip(), file=sys.stderr)
        return 2

    # Anything else is a real prompt. Never block or rewrite it; at most add one short
    # line of context pointing at a specialised tool the prompt clearly calls for.
    hint = routing_hint(prompt, payload.get("cwd") if isinstance(payload, dict) else None)
    if hint:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": hint}}))
    return 0


if __name__ == "__main__":
    # A hook must fail open: never let an internal error block a user's prompt.
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        sys.exit(0)
