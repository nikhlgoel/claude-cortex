#!/usr/bin/env python3
"""
Stub Claude Code binary for sandbox testing.

Stands in for the real ``claude`` executable so the Cortex wrapper can be tested
without network access, credentials, or quota. Every invocation is appended to
``$CORTEX_STUB_LOG`` as one JSON object per line, which is what the test suite
asserts against: it can check the exact argv and environment the wrapper
produced, rather than inferring behavior from side effects.

Behaviors mirrored from the real CLI (verified against 2.1.273):

* ``--autocompact`` accepts ``auto`` or 100k-1M only; anything else is an error.
  This is what catches a regression reintroducing the invalid 85000 window.
* ``auth status`` prints JSON and exits 0 **even when logged out** - callers must
  read the ``loggedIn`` field, never the exit code.
* ``auth status`` creates ``.claude.json`` in the config dir as a side effect.
* Unknown options are rejected, the way commander does.

Environment:
    CORTEX_STUB_LOG      path to the JSONL invocation log (required for asserts)
    CORTEX_STUB_VERSION  version string to report (default 2.1.273)
    CORTEX_STUB_EMAIL    account email used by auth login/status
"""

import json
import os
import sys
from datetime import datetime, timezone

VERSION = os.environ.get("CORTEX_STUB_VERSION", "2.1.273")
EMAIL = os.environ.get("CORTEX_STUB_EMAIL", "sandbox@example.test")

# Environment variables worth recording: everything the wrapper is supposed to
# set, plus the ones whose absence is itself a bug.
TRACKED_ENV = [
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_SECURESTORAGE_CONFIG_DIR",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE",
    "CLAUDE_CODE_EFFORT_LEVEL",
    "MAX_THINKING_TOKENS",
    "BASH_MAX_OUTPUT_LENGTH",
    "TASK_MAX_OUTPUT_LENGTH",
    "MAX_MCP_OUTPUT_TOKENS",
    "CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "COMPACT_CONTEXT_THRESHOLD",
    "COMPACT_CONTEXT_INTERVAL",
]

# Options the real CLI accepts that take a value. Used for unknown-flag checking.
VALUE_OPTS = {
    "--model", "--effort", "--autocompact", "--settings", "--agent",
    "--permission-mode", "--add-dir", "--system-prompt", "--append-system-prompt",
    "--fallback-model", "--session-id", "--thinking", "-n", "--name",
}
BOOL_OPTS = {
    "--continue", "-c", "--resume", "-r", "--print", "-p", "--version", "-v",
    "--help", "-h", "--debug", "-d", "--verbose", "--ide", "--bare",
    "--dangerously-skip-permissions", "--safe-mode", "--restricted",
    "--fork-session",
}


def log_invocation(argv, extra=None):
    path = os.environ.get("CORTEX_STUB_LOG")
    if not path:
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "argv": argv,
        "cwd": os.getcwd(),
        "env": {k: os.environ[k] for k in TRACKED_ENV if k in os.environ},
    }
    if extra:
        record.update(extra)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def creds_path():
    return os.path.join(config_dir(), ".credentials.json")


def claude_json_path():
    return os.path.join(config_dir(), ".claude.json")


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def is_logged_in():
    forced = os.environ.get("CORTEX_STUB_LOGGED_IN")
    if forced is not None:
        return forced == "1"
    data = read_json(creds_path())
    return bool(data.get("claudeAiOauth", {}).get("accessToken"))


def parse_autocompact(value):
    """Mirror the real CLI's validation: 'auto', or 100k-1M."""
    if value == "auto":
        return True
    raw = value.strip().lower()
    try:
        if raw.endswith("k"):
            tokens = int(float(raw[:-1]) * 1000)
        elif raw.endswith("m"):
            tokens = int(float(raw[:-1]) * 1_000_000)
        else:
            tokens = int(raw)
            # Bare numbers under 1000 are shorthand: 200 -> 200k
            if tokens < 1000:
                tokens *= 1000
    except ValueError:
        return False
    return 100_000 <= tokens <= 1_000_000


def cmd_auth(args):
    sub = args[0] if args else "status"

    if sub == "status":
        # The real CLI creates .claude.json here as a side effect.
        cfg = read_json(claude_json_path())
        if not cfg:
            write_json(claude_json_path(), {"firstStartVersion": VERSION})

        logged_in = is_logged_in()
        payload = {
            "loggedIn": logged_in,
            "authMethod": "claude.ai" if logged_in else "none",
            "apiProvider": "firstParty",
            "analyticsDisabled": False,
            "projectsDirectory": os.path.join(config_dir(), "projects"),
            "configDirectory": config_dir(),
        }
        if logged_in:
            payload["email"] = EMAIL
            payload["subscriptionType"] = "pro"
        print(json.dumps(payload, indent=2))
        # Exit 0 in BOTH states, exactly like the real CLI.
        return 0

    if sub == "login":
        write_json(creds_path(), {
            "claudeAiOauth": {
                "accessToken": "sandbox-token",
                "subscriptionType": "pro",
                "rateLimitTier": "default",
            }
        })
        cfg = read_json(claude_json_path())
        cfg["oauthAccount"] = {"emailAddress": EMAIL, "accountUuid": "sandbox-uuid"}
        cfg["hasCompletedOnboarding"] = True
        write_json(claude_json_path(), cfg)
        print(f"Logged in as {EMAIL}")
        return 0

    if sub == "logout":
        try:
            os.unlink(creds_path())
        except OSError:
            pass
        print("Logged out")
        return 0

    print(f"error: unknown auth subcommand '{sub}'", file=sys.stderr)
    return 1


def main():
    argv = sys.argv[1:]
    log_invocation(argv)

    if not argv:
        # Interactive launch. Report onboarding state so tests can assert that a
        # correctly seeded profile does not re-prompt.
        cfg = read_json(claude_json_path())
        if not cfg.get("hasCompletedOnboarding"):
            print("STUB: onboarding required (theme + login prompt)")
            return 0
        if not is_logged_in():
            print("STUB: login required")
            return 0
        print(f"STUB: interactive session ready ({EMAIL})")
        return 0

    head = argv[0]

    if head == "auth":
        return cmd_auth(argv[1:])

    if head in ("--version", "-v"):
        print(f"{VERSION} (Claude Code)")
        return 0

    if head in ("update", "upgrade"):
        print("Claude Code is up to date.")
        return 0

    if head in ("doctor", "install", "mcp", "plugin", "agents", "project"):
        print(f"STUB: {head} ok")
        return 0

    # Flag validation over the remaining argv.
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--autocompact":
            value = argv[i + 1] if i + 1 < len(argv) else ""
            if not parse_autocompact(value):
                print(
                    f"error: option '--autocompact <auto|tokens>' argument "
                    f"'{value}' is invalid. It must be 'auto', or between 100k "
                    f"and 1M (e.g. 500k, 200000, or 200 as shorthand)",
                    file=sys.stderr,
                )
                return 1
            i += 2
            continue
        if arg.startswith("-") and arg not in VALUE_OPTS and arg not in BOOL_OPTS:
            print(f"error: unknown option '{arg}'", file=sys.stderr)
            return 1
        i += 2 if arg in VALUE_OPTS else 1

    print("STUB: session started")
    return 0


if __name__ == "__main__":
    sys.exit(main())
