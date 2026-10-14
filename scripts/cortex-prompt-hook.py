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


# Read-only subcommands of commands that otherwise start servers, windows or downloads.
SAFE_SUBCOMMANDS = {
    "graph": frozenset({"status"}),
    "local": frozenset({"status", "list", "ls", "doctor", "env"}),
}


def core_explains(name):
    """True when the core answers ``name`` with a one-line explanation (retired or session-only command)."""
    try:
        command, base = cortex_command()
        if not command:
            return False
        if base not in sys.path:
            sys.path.insert(0, base)
        from cortex import tools
        return tools.is_retired(name) or tools.is_in_session_only(name)
    except Exception:
        return False


def route(args):
    """Return ``(args, None)`` to run, or ``(None, message)`` to refuse."""
    head = args[0].lower() if args else ""
    if head in NON_INTERACTIVE or core_explains(head):
        return args, None
    safe = SAFE_SUBCOMMANDS.get(head)
    if safe and len(args) > 1 and args[1].lower() in safe and "--smoke" not in args:
        return args, None
    if safe:
        return None, (f"cc: 'cc {head} {' '.join(args[1:])}' can start a server, window or download, "
                      f"so it runs in a terminal, not here.\n"
                      f"    Allowed here: cc {head} " + " | ".join(sorted(safe)) +
                      f"\n    Terminal:  cc {' '.join(args)}")
    return None, (f"cc: '{head}' cannot run inside a prompt (it may start a login or a session, "
                  f"or it is not a cc command).\n"
                  f"    Run it in a terminal:  cc {' '.join(args)}".rstrip())


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


def memory_context(prompt, payload):
    """Relevant project memory for ``prompt``, or None. Any failure means "no memory", never an error."""
    try:
        command, base = cortex_command()
        if not command:
            return None
        if base not in sys.path:
            sys.path.insert(0, base)
        from cortex.palace import hook
        data = payload if isinstance(payload, dict) else {}
        return hook.context_for(prompt, cwd=data.get("cwd"), session=data.get("session_id"))
    except Exception:
        return None


def touch_session(payload):
    """Tell the project-map button this session is still alive. Failure means nothing."""
    try:
        data = payload if isinstance(payload, dict) else {}
        if not data.get("session_id"):
            return
        command, base = cortex_command()
        if not command:
            return
        if base not in sys.path:
            sys.path.insert(0, base)
        from cortex.atlas import sessions
        sessions.touch_session(data["session_id"])
    except Exception:
        pass


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
        return f"cc: {exc}", 1
    return (result.stdout or "") + (result.stderr or ""), result.returncode


def banner(args, code):
    """First line of the result. Claude Code labels every exit-2 hook "blocked your prompt", so say what really happened."""
    ran = "cc " + " ".join(args)
    if code == 0:
        return f"[{ran}: done - ran locally, no tokens used]"
    return f"[{ran}: FAILED (exit {code}) - ran locally, no tokens used]"


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
        if refusal:
            output = refusal
        else:
            text, code = run_cortex(runnable)
            output = banner(runnable, code) + "\n" + text.strip()
        # Exit 2 blocks the model and shows stderr to the user, at no token cost.
        print(output.strip(), file=sys.stderr)
        return 2

    # Anything else is a real prompt. Never block or rewrite it; at most add one short
    # line of context pointing at a specialised tool the prompt clearly calls for.
    hint = routing_hint(prompt, payload.get("cwd") if isinstance(payload, dict) else None)
    touch_session(payload)
    memory = memory_context(prompt, payload)
    extra = "\n\n".join(part for part in (hint, memory) if part)
    if extra:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": extra}}))
    return 0


if __name__ == "__main__":
    # A hook must fail open: never let an internal error block a user's prompt.
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        sys.exit(0)
