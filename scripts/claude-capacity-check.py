#!/usr/bin/env python3
"""
Account capacity check - thin delegator to the Cortex core.

This was previously a second, independent implementation of capacity reporting,
and the two disagreed in a way that mattered: this script treated a profile with
no recorded usage as **"Ready (100% capacity free)"** and ranked it best, so
automatic failover could switch to an account that was in fact exhausted. The
core treats unknown as unknown and refuses to auto-select on it.

Rather than keep two implementations in sync, this forwards to the core.

Usage:
    claude-capacity-check.py            human-readable table
    claude-capacity-check.py --json     machine-readable records
    claude-capacity-check.py --best     name of a profile with free capacity,
                                        or nothing (exit 1) when none is known
    claude-capacity-check.py --switch N set the active profile
"""

import json
import os
import sys

# Prefer the installed core, then a sibling checkout.
for _candidate in (os.path.expanduser("~/.claude/cortex-core"),
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
    if os.path.isdir(os.path.join(_candidate, "cortex")):
        sys.path.insert(0, _candidate)
        break

try:
    from cortex import capacity, profiles
except ImportError:
    sys.stderr.write(
        "claude-capacity-check: the Cortex core is not installed.\n"
        "  Reinstall Cortex, or run this from a repository checkout.\n")
    sys.exit(1)


def main():
    args = sys.argv[1:]

    if "--best" in args:
        # Print a profile only when there is positive evidence of free capacity.
        # Printing nothing is meaningful: callers must not fall back to a guess.
        best = capacity.best()
        if not best:
            return 1
        print(best)
        return 0

    if "--switch" in args:
        index = args.index("--switch")
        target = args[index + 1] if index + 1 < len(args) else ""
        target = profiles.normalize_name(target)
        if not target or target not in profiles.list_profiles():
            sys.stderr.write(f"Unknown profile: {target or '(none given)'}\n")
            return 1
        profiles.set_active(target)
        print(f"Active profile: {target}")
        return 0

    records = capacity.survey()

    if "--json" in args:
        print(json.dumps(records, indent=2))
        return 0

    print(capacity.render(records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
