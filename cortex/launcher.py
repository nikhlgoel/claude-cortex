"""
Session launching: argument translation and environment.

The environment table here is deliberately small. The previous wrapper exported
a large set of "token conservation" variables, several of which were actively
harmful:

* ``CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=0.45`` lowers the compaction threshold to a
  fraction of the window. Combined with an 85000 window it fired at roughly 38k
  tokens, so sessions compacted at startup and then repeatedly - the "it keeps
  compacting" symptom.
* ``CLAUDE_CODE_AUTO_COMPACT_WINDOW=85000`` is below the CLI's documented 100k
  floor, and setting it also locks the setting out of ``/config``.
* ``BASH_MAX_OUTPUT_LENGTH=6000`` against a default of 30000 truncates tool
  output so aggressively that commands get re-run to see what was cut, costing
  more tokens than it saves.
* ``COMPACT_CONTEXT_THRESHOLD`` / ``COMPACT_CONTEXT_INTERVAL`` are not read by
  Claude Code at all.

What remains are variables that are real, documented, and do something useful.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

from . import binary, profiles
from .paths import apply_config_env

# Model IDs are Anthropic's exact strings. The short flags (-s, -o, -H) keep their
# long-standing targets so existing habits do not change under anyone; the newer
# generations are reached by explicit flags. ``--fable`` means the newest Fable.
#
# There is deliberately no ``-f``: it is too easy to collide with a Claude Code
# flag, and a one-letter alias adds nothing over ``--fable``.
MODEL_ALIASES = {
    "-s": "claude-sonnet-5", "--sonnet": "claude-sonnet-5", "--sonnet-5": "claude-sonnet-5",
    "--sonnet-5-5": "claude-sonnet-5-5",
    "-o": "claude-opus-5", "--opus": "claude-opus-5", "--opus-5": "claude-opus-5",
    "--opus-5-5": "claude-opus-5-5", "-o55": "claude-opus-5-5",
    "--fable": "claude-fable-5-1", "--fable-5-1": "claude-fable-5-1",
    "--fable-5": "claude-fable-5",
    "-H": "claude-haiku-4-5", "--haiku": "claude-haiku-4-5", "--haiku-4-5": "claude-haiku-4-5",
    "--sonnet-4-5": "claude-sonnet-4-5", "--opus-4-5": "claude-opus-4-5",
}

EFFORT_FLAGS = {
    "--think-low": "low", "--think-med": "medium", "--think-high": "high",
    "--think-max": "max", "--think-off": "low",
}

# "ultracode" is accepted by Claude Code's own ``--effort`` flag (2.1.203+) but it is
# not a reasoning level: it is a client-side mode that fans work out across many
# subagent calls. It is passed through untouched; the local gateway never sees it as a
# level (see cortex/local/shaping.py).
VALID_EFFORT = ("low", "medium", "high", "xhigh", "max", "ultracode")


def session_env(config_dir: str, extra=None, drop=()):
    """Environment for a launched session.

    ``drop`` names variables to remove from the inherited environment before ``extra``
    is applied - used by the offline profile so a real cloud credential in the parent
    shell can never reach a local model session.
    """
    env = dict(os.environ)
    for name in drop:
        env.pop(name, None)

    # Profile isolation. Both variables must carry the identical canonical
    # string: Claude Code derives the credential namespace from a hash of it, so
    # any difference in spelling is a different account.
    apply_config_env(env, config_dir)

    # Remove settings a previous Cortex version exported that break compaction.
    for stale in ("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
                  "COMPACT_CONTEXT_THRESHOLD", "COMPACT_CONTEXT_INTERVAL",
                  "CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT"):
        env.pop(stale, None)

    # Keep long-running/proxied sessions from being torn down mid-thought.
    env.setdefault("API_TIMEOUT_MS", "300000")

    if extra:
        env.update(extra)
    return env


def translate_args(argv):
    """Map Cortex shorthand onto real CLI flags.

    Returns ``(args, error)``. Unknown arguments pass through untouched so the
    CLI can report them itself.
    """
    out = []
    i = 0
    while i < len(argv):
        arg = argv[i]

        if arg in ("-y", "--yes"):
            out.append("--dangerously-skip-permissions")
            i += 1
            continue

        if arg in MODEL_ALIASES:
            out += ["--model", MODEL_ALIASES[arg]]
            i += 1
            continue

        if arg in EFFORT_FLAGS:
            out += ["--effort", EFFORT_FLAGS[arg]]
            i += 1
            continue

        # No "-r" here: that is Claude Code's own --resume, and rewriting it into
        # an effort flag would silently break resuming a session.
        if arg in ("-e", "--effort", "--reasoning"):
            value = argv[i + 1] if i + 1 < len(argv) else "medium"
            if value not in VALID_EFFORT:
                return None, (f"invalid effort '{value}'. "
                              f"Choose one of: {', '.join(VALID_EFFORT)}")
            out += ["--effort", value]
            i += 2
            continue

        if arg.startswith(("--effort=", "--reasoning=")):
            value = arg.split("=", 1)[1]
            if value not in VALID_EFFORT:
                return None, (f"invalid effort '{value}'. "
                              f"Choose one of: {', '.join(VALID_EFFORT)}")
            out += ["--effort", value]
            i += 1
            continue

        # Turbo: a fast, cheap model at low effort. Uses --effort, the documented
        # flag, rather than the undocumented --thinking.
        if arg in ("-t", "--turbo", "--fast"):
            out += ["--model", "claude-haiku-4-5", "--effort", "low"]
            i += 1
            continue

        out.append(arg)
        i += 1

    return out, None


def launch(profile: str, argv, extra_env=None, continue_session=False):
    """Exec a Claude Code session under ``profile``."""
    exe = binary.find()
    if not exe:
        print("No working Claude Code binary found.", file=sys.stderr)
        print("Run 'cc doctor' to diagnose, or install from https://claude.ai/download",
              file=sys.stderr)
        return 1

    profile = profiles.normalize_name(profile)
    config_dir = profiles.ensure_structure(profile, profiles.profile_mode(profile))
    return launch_dir(config_dir, argv, extra_env=extra_env, continue_session=continue_session,
                      exe=exe)


def launch_dir(config_dir: str, argv, extra_env=None, continue_session=False, drop=(), exe=None):
    """Exec a Claude Code session against an explicit config directory.

    ``launch`` resolves a named cloud profile and delegates here. The offline profile
    calls this directly, because its directory deliberately lives outside the cloud
    profile namespace.
    """
    exe = exe or binary.find()
    if not exe:
        print("No working Claude Code binary found.", file=sys.stderr)
        return 1

    args, error = translate_args(list(argv))
    if error:
        print(f"cc: {error}", file=sys.stderr)
        return 2

    if continue_session:
        args = ["--continue"] + args

    env = session_env(config_dir, extra_env, drop=drop)

    # On POSIX, replace this process rather than wrapping it. Claude Code is a
    # full-screen interactive program: keeping a Python parent in between adds a
    # layer that has to forward SIGINT, SIGWINCH (terminal resize) and job-control
    # signals correctly, and getting any of that subtly wrong shows up as a
    # mis-drawn UI or a Ctrl+C that does not reach the app. execv removes the
    # question entirely.
    #
    # Windows has no execv that replaces the process image in a way the console
    # host follows, so there we do wrap it.
    if os.name != "nt":
        try:
            os.execve(exe, [exe] + args, env)
        except OSError as exc:
            print(f"cc: failed to launch Claude Code: {exc}", file=sys.stderr)
            return 1

    return _run_child([exe] + args, env)


def _run_child(command, env):
    """Run Claude Code as a child and wait, without letting Ctrl+C reach us.

    On Windows a console Ctrl+C is delivered to every process attached to the
    console, this parent included. Left alone, Python raises KeyboardInterrupt in
    ``subprocess.run`` and kills the child - so pressing Ctrl+C to interrupt a
    response in Claude Code could end the whole session. The child handles its
    own Ctrl+C; the parent's only job is to wait for it, so ignore SIGINT here
    for exactly as long as the child lives.
    """
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        return subprocess.run(command, env=env).returncode
    except KeyboardInterrupt:
        return 130
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"cc: failed to launch Claude Code: {exc}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, previous)
