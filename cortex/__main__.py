"""
Claude Cortex - command dispatch.

Single implementation shared by the bash, PowerShell, and cmd shims. Having one
core rather than parallel shell implementations is what keeps the two platforms
from drifting apart, which is where most of the previous bugs came from.
"""

from __future__ import annotations

import os
import sys

from . import capacity, doctor, ghidra, ide, integrity, launcher, mcp, models, profiles, tools
from .profiles import CortexError
from .paths import profile_dir

VERSION = "2.0.0"

# Recognized top-level commands, used for the "did you mean" hint.
TOP_LEVEL_COMMANDS = (
    "profile", "profiles", "login", "switch", "status", "quota", "capacity",
    "limits", "continue", "doctor", "ide", "ghidra", "mcp", "integrity",
    "model", "models", "version", "help",
) + tuple(tools.TOOLS)

USAGE = """\
Claude Cortex (cc) - multi-account Claude Code launcher

  cc [profile] [claude args...]   Launch a session (default: active profile)
  cc -<profile>                   Launch a specific profile, e.g. cc -work

Profiles
  cc profile list                 Show profiles and auth state
  cc profile add [name]           Create a profile
  cc profile remove <name> [--yes]  Delete a profile (--yes required in scripts)
  cc login [name]                 Sign in to a profile
  cc switch [name]                Set the active profile
  cc status | cc quota            Account capacity

Session
  cc continue [name]              Resume the last conversation
  cc -s | -o | -H                 Sonnet 5 | Opus 5 | Haiku 4.5
  cc --opus-5-5 | --sonnet-5-5 | --fable   Opus 5.5 | Sonnet 5.5 | Fable 5.1
  cc -e <low|medium|high|xhigh|max>   Reasoning effort
  cc -t                           Turbo (Haiku, low effort)
  cc -y                           Skip permission prompts

Diagnostics
  cc doctor [--repair]            Diagnose configuration problems
  cc integrity verify             Check the install matches the reviewed source
  cc ide check                    Inspect IDE integration
  cc ide apply [--yes]            Configure IDEs for the active profile
  cc version

Analysis
  cc ghidra status                Isolated binary analysis (see `cc ghidra help`)
  cc mcp add                      Give Claude Cortex's tools via MCP

Tools
  cc palace | remember | recall   Memory palace
  cc model [free|<search>]        Live model catalog with real pricing
  cc provider | update            API providers, updates
  cc analyze <path>               Static risk analysis of source code
  (dream is in-session: /dream <concept>)
  cc research <topic>             Live arXiv retrieval

Prompts
  cc -- <prompt>                  Send a prompt, even if it looks like a command
"""


def _ask(prompt):
    """Read one answer, or return None when none can be read.

    ``sys.stdin.isatty()`` is not a dependable "a person is here": on Windows it
    is True for the NUL device, so ``cc profile add x < NUL`` took the
    interactive path and died with an EOFError traceback at ``input()``. Callers
    treat None as "declined", which is the safe reading for every prompt here.
    """
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def cmd_profile(args):
    action = args[0] if args else "list"
    rest = args[1:]

    if action in ("list", "ls", "status"):
        print(capacity.render())
        return 0

    if action in ("add", "new", "create"):
        raw = rest[0] if rest else ""
        if not raw and sys.stdin.isatty():
            raw = _ask("New profile name: ") or ""
        name = profiles.normalize_name(raw)

        if not name:
            if raw.strip():
                # e.g. a name that is entirely non-ASCII. Say why, rather than
                # claiming no name was supplied.
                print(f"'{raw.strip()}' contains no usable characters for a "
                      f"profile name.", file=sys.stderr)
                print("    Use letters, digits, '-' or '_'.", file=sys.stderr)
            else:
                print("A profile name is required.", file=sys.stderr)
            return 2

        # Names are sanitized (which is also what stops path traversal such as
        # "../../etc"). Say so, rather than silently creating something the user
        # did not type and will later fail to find.
        if name != raw.strip():
            print(f"Note: using '{name}' (adjusted from '{raw.strip()}').")

        # A profile sharing a command's name can never be launched as `cc <name>`,
        # because dispatch checks commands first. Reject it at creation rather
        # than leaving a profile that appears to work but is unreachable.
        if name in TOP_LEVEL_COMMANDS or tools.is_retired(name):
            print(f"'{name}' is a Cortex command and cannot be a profile name.",
                  file=sys.stderr)
            print(f"    Pick another name, e.g. '{name}-acct'.", file=sys.stderr)
            return 2

        if os.path.isdir(profile_dir(name)):
            print(f"Profile '{name}' already exists.")
            return 0

        mode = "synced"
        if "--isolated" in rest:
            mode = "isolated"
        profiles.ensure_structure(name, mode)
        print(f"Created profile '{name}' ({mode}).")

        if sys.stdin.isatty():
            answer = _ask(f"Sign in to '{name}' now? [Y/n]: ")
            # No answer at all (None) is a decline, not the default "yes": opening
            # a browser login nobody asked for is the worse mistake.
            if answer is not None and answer.lower() in ("", "y", "yes"):
                return profiles.login(name)
        print(f"Run 'cc login {name}' when you are ready to sign in.")
        return 0

    if action in ("remove", "rm", "delete"):
        name = next((a for a in rest if not a.startswith("-")), "")
        if not name:
            print("Usage: cc profile remove <name> [--yes]", file=sys.stderr)
            return 2
        # Deleting a profile deletes its saved sign-in. Never do that silently:
        # ask when a person is present, and demand --yes when nobody is (a script
        # or a hook), where an accidental call would otherwise just succeed.
        if "--yes" not in rest and "-y" not in rest:
            if not sys.stdin.isatty():
                print(f"Refusing to remove '{name}' without confirmation. "
                      f"Re-run with --yes to delete it and its credentials.",
                      file=sys.stderr)
                return 2
            confirm = _ask(f"Remove profile '{name}' and its credentials? [y/N]: ")
            if confirm is None:
                print("No confirmation received; nothing was removed. "
                      "Re-run with --yes to skip the prompt.", file=sys.stderr)
                return 2
            if confirm.lower() not in ("y", "yes"):
                print("Aborted.")
                return 0
        return profiles.remove(name)

    print(f"Unknown profile action: {action}", file=sys.stderr)
    return 2


def cmd_switch(args):
    names = profiles.list_profiles()
    if not names:
        print("No profiles configured. Run: cc profile add", file=sys.stderr)
        return 1

    target = profiles.normalize_name(args[0]) if args else ""

    if not target:
        # Pick a profile with evidence of free capacity. If none has evidence,
        # say so rather than guessing - the old code treated "no data" as "free".
        target = capacity.best()
        if not target:
            print(capacity.render())
            print("\nNo profile has confirmed free capacity. Choose one explicitly:")
            print("  cc switch <name>")
            return 1

    if target.isdigit():
        index = int(target) - 1
        if 0 <= index < len(names):
            target = names[index]

    if target not in names:
        print(f"Profile '{target}' not found. Available: {', '.join(names)}",
              file=sys.stderr)
        return 1

    profiles.set_active(target)
    print(f"Active profile: {target} ({profiles.profile_email(target) or 'no email'})")
    return 0


def cmd_continue(args):
    names = profiles.list_profiles()
    target = ""
    rest = list(args)

    if rest and profiles.normalize_name(rest[0]) in names:
        target = profiles.normalize_name(rest[0])
        rest = rest[1:]

    if not target:
        target = capacity.best() or profiles.active_profile()

    target, rc = require_profile(target)
    if rc is not None:
        return rc

    profiles.set_active(target)
    print(f"Resuming under '{target}'...")
    return launcher.launch(target, rest, continue_session=True)


def require_profile(name=None):
    """Resolve a usable profile, or explain why there isn't one.

    Returns ``(name, None)`` on success or ``(None, exit_code)`` when the caller
    should stop. Every path that launches a session goes through this. Without
    it, `cc -- <prompt>` and `cc continue` skipped the no-profile check, silently
    created an unauthenticated 'main', and either launched into it or opened a
    browser login the user never asked for.
    """
    if not profiles.list_profiles():
        print("No profiles configured yet.", file=sys.stderr)
        print("Create one with:  cc profile add", file=sys.stderr)
        return None, 1

    name = profiles.normalize_name(name or "") or profiles.active_profile()

    if name not in profiles.list_profiles():
        available = ", ".join(profiles.list_profiles())
        print(f"Profile '{name}' does not exist. Available: {available}",
              file=sys.stderr)
        print("    Set one with: cc switch <name>", file=sys.stderr)
        return None, 1

    if not profiles.is_authenticated(name):
        print(f"Profile '{name}' is not signed in.")
        if profiles.login(name) != 0:
            return None, 1

    return name, None


def cmd_ide(args):
    action = args[0] if args else "check"
    rest = args[1:]
    if action == "check":
        return ide.check(rest[0] if rest else None)
    if action == "apply":
        yes = "--yes" in rest or "-y" in rest
        profile = next((a for a in rest if not a.startswith("-")), None)
        return ide.apply(profile, dry_run=not yes)
    print(f"Unknown ide action: {action}", file=sys.stderr)
    return 2


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv:
        head = argv[0]
        rest = argv[1:]

        if head in ("--help", "help"):
            print(USAGE)
            return 0
        if head in ("version", "--cc-version"):
            print(f"Claude Cortex {VERSION}")
            return 0
        if head in ("profile", "profiles"):
            return cmd_profile(rest)
        if head == "login":
            return profiles.login(rest[0] if rest else profiles.active_profile())
        if head == "switch":
            return cmd_switch(rest)
        if head in ("status", "quota", "capacity", "limits"):
            print(capacity.render())
            return 0
        if head == "continue":
            return cmd_continue(rest)
        if head == "doctor":
            return doctor.report(repair="--repair" in rest)
        if head == "ide":
            return cmd_ide(rest)
        if head == "ghidra":
            return ghidra.main(rest)
        if head == "mcp":
            return mcp.main(rest)
        if head == "integrity":
            return integrity.main(rest)
        if head in ("model", "models"):
            return models.main(rest)
        if tools.is_tool(head):
            return tools.run(head, rest)
        if tools.is_in_session_only(head):
            return tools.explain_in_session(head)
        if tools.is_retired(head):
            return tools.explain_retired(head)

        # Explicit prompt separator: everything after "--" goes to the CLI
        # untouched, so a prompt can never collide with a command name.
        if head == "--":
            name, rc = require_profile()
            if rc is not None:
                return rc
            return launcher.launch(name, rest)

        # -<profile> selects a profile, e.g. cc -work
        if head.startswith("-") and not head.startswith("--"):
            candidate = profiles.normalize_name(head.lstrip("-"))
            if candidate and candidate in profiles.list_profiles():
                name, rc = require_profile(candidate)
                if rc is not None:
                    return rc
                return launcher.launch(name, rest)

            # Claude Code's own single-dash flags are all one character, and ours
            # are listed above. So a multi-character -token that matched no
            # profile is a mistyped profile name. Forwarding it starts a session
            # that immediately dies on "unknown option" - having already signed
            # in and spent a session start. Refuse here instead.
            if len(head) > 2 and head not in launcher.MODEL_ALIASES \
                    and head not in launcher.EFFORT_FLAGS \
                    and head not in ("-t", "-y", "-e", "-s", "-o", "-H"):
                available = ", ".join(profiles.list_profiles()) or "(none)"
                print(f"cc: no profile named '{candidate}'.", file=sys.stderr)
                print(f"    Available profiles: {available}", file=sys.stderr)
                print(f"    To pass this to Claude instead: cc -- {head}",
                      file=sys.stderr)
                return 1

        # bare profile name as the first argument
        candidate = profiles.normalize_name(head)
        if candidate and candidate in profiles.list_profiles() and not head.startswith("-"):
            name, rc = require_profile(candidate)
            if rc is not None:
                return rc
            return launcher.launch(name, rest)

        # A bare word that is neither a command nor a profile is almost always a
        # mistyped command, not a prompt. Launching a session for it spends real
        # tokens answering a typo, so refuse and explain instead.
        #
        # This deliberately does NOT depend on what follows. An earlier version
        # only refused when every remaining argument was a flag, so
        # `cc nonsensecmd --- check bogus` still started a session with the typo
        # as the prompt. Trailing arguments make a typo more likely, not less.
        # A genuine prompt goes through `--` or is quoted as one argument.
        if not head.startswith("-") and " " not in head:
            print(f"cc: unknown command '{head}'.", file=sys.stderr)
            close = [c for c in list(TOP_LEVEL_COMMANDS) + profiles.list_profiles()
                     if c.startswith(head[:3])]
            if close:
                print(f"    Did you mean: {', '.join(sorted(set(close))[:5])}?",
                      file=sys.stderr)
            print(f"    To send it to Claude as a prompt: cc -- {head}",
                  file=sys.stderr)
            print("    To see available commands:        cc --help", file=sys.stderr)
            return 2

    name, rc = require_profile()
    if rc is not None:
        return rc

    return launcher.launch(name, argv)


def _run():
    """Entry point with a last-resort guard.

    Specific failures are reported where they happen; this catches whatever is
    left so an unexpected filesystem or environment problem still produces one
    actionable line rather than a stack trace. A traceback tells the operator
    nothing they can act on, and makes a routine problem look like corruption.
    """
    # A legacy console code page cannot encode every character a command may print
    # (profile names, paths, tool output). Replace rather than crash: a '?' in the
    # output is better than a traceback that discards the whole result.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        return main()
    except CortexError as exc:
        print(f"cc: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    except OSError as exc:
        location = getattr(exc, "filename", None)
        where = f" ({location})" if location else ""
        print(f"cc: {exc.strerror or exc}{where}", file=sys.stderr)
        print("    Run 'cc doctor' for a fuller picture.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_run())
