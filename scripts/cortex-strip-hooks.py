#!/usr/bin/env python3
"""
Claude Cortex - settings.json hook stripper.

Removes only the hook entries whose command references a Cortex script
(``cortex-*``), leaving every other key, hook, and user customization intact.

Used by uninstall.sh. Kept as a separate file so the uninstaller contains no
embedded Python heredoc, which makes both easier to test in isolation.

Usage:
    cortex-strip-hooks.py <path-to-settings.json>

Exits non-zero only on unusable input; a settings file that cannot be parsed is
reported and left untouched (exit 0) so an uninstall never corrupts it.
"""

import json
import sys


def is_cortex_entry(entry: dict) -> bool:
    """True when any command in this hook entry points at a Cortex script."""
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks") or []:
        if not isinstance(hook, dict):
            continue
        if "cortex-" in str(hook.get("command", "")):
            return True
    return False


def strip_cortex_hooks(cfg: dict) -> int:
    """Remove Cortex hook entries in place. Returns the number removed."""
    hooks = cfg.get("hooks")
    if not isinstance(hooks, dict):
        return 0

    removed = 0
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue

        kept = [e for e in entries if not is_cortex_entry(e)]
        removed += len(entries) - len(kept)

        if kept:
            hooks[event] = kept
        else:
            del hooks[event]

    if not hooks:
        cfg.pop("hooks", None)
    return removed


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: cortex-strip-hooks.py <path-to-settings.json>", file=sys.stderr)
        return 2

    path = sys.argv[1]
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception as exc:
        # Never corrupt a settings file we cannot understand.
        print(f"  ! could not parse settings.json ({exc}); left untouched")
        return 0

    if not isinstance(cfg, dict):
        print("  ! settings.json is not a JSON object; left untouched")
        return 0

    removed = strip_cortex_hooks(cfg)
    if removed == 0:
        print("  no Cortex hook entries found")
        return 0

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")

    print(f"  stripped {removed} Cortex hook entr{'y' if removed == 1 else 'ies'} "
          f"(backup: settings.json.cortex-uninstall.bak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
