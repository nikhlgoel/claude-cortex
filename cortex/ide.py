"""
IDE integration (settings-only).

How the Claude Code extension actually launches the CLI, from ``extension.js``::

    if (wrapper) return { pathToClaudeCodeExecutable: wrapper,
                          executableArgs: [bundledBinary], viaProcessWrapper: true }

Two consequences drive the design here:

1. When ``claudeCode.claudeProcessWrapper`` is set, the extension passes **its own
   bundled binary as argv[1]**. A wrapper must therefore accept
   ``wrapper <real-claude> [args...]``. The old Cortex wrapper treated ``$1`` as a
   subcommand, so pointing the extension at it would have broken the extension
   rather than enhancing it.

2. Setting a wrapper also turns off ``resolvePermissionModeInCli`` and the
   extension's ``CLAUDE_CONFIG_DIR`` watching. That is a real cost.

So profile selection is done with ``claudeCode.environmentVariables`` instead,
which the extension applies *after* ``process.env`` and which costs nothing:

    for (let X of Q) if (X.name) J[X.name] = X.value || ""

The config-dir string written here comes from the same canonicalizer the
terminal uses, so an IDE session and a terminal session share one credential
namespace.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import jsonfile, profiles
from .paths import home, is_native_default, profile_dir

# Directory name -> human label. Only IDEs that actually host the extension.
KNOWN_IDES = {
    ".vscode": "VS Code",
    ".vscode-insiders": "VS Code Insiders",
    ".vscode-oss": "VSCodium",
    ".antigravity-ide": "Antigravity",
    ".cursor": "Cursor",
    ".windsurf": "Windsurf",
}

# Where each IDE keeps user settings.json, relative to the OS config root.
#
# Several candidates per IDE, tried in order, because the extensions directory
# name does not reliably predict the settings directory name. Antigravity is the
# case in point: its extensions live in ``~/.antigravity-ide`` but its settings
# are under ``Antigravity IDE/User`` - and a separate ``Antigravity/`` directory
# also exists, so guessing the obvious name finds the wrong place or nothing.
SETTINGS_SUBDIR = {
    ".vscode": ["Code"],
    ".vscode-insiders": ["Code - Insiders"],
    ".vscode-oss": ["VSCodium", "Code - OSS"],
    ".antigravity-ide": ["Antigravity IDE", "Antigravity"],
    ".cursor": ["Cursor"],
    ".windsurf": ["Windsurf"],
}

MANAGED_KEYS = ("claudeCode.environmentVariables", "claudeCode.disableLoginPrompt")


def _settings_roots():
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        return [Path(appdata)] if appdata else []
    mac = Path(home()) / "Library" / "Application Support"
    if mac.is_dir():
        return [mac]
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home(), ".config")
    return [Path(xdg)]


def detect():
    """Find installed IDEs that host the Claude Code extension."""
    found = []
    h = Path(home())
    for dirname, label in KNOWN_IDES.items():
        ext_root = h / dirname / "extensions"
        if not ext_root.is_dir():
            continue
        versions = []
        try:
            for entry in sorted(ext_root.iterdir()):
                if entry.name.startswith("anthropic.claude-code-"):
                    versions.append(entry.name.replace("anthropic.claude-code-", ""))
        except OSError:
            continue
        if not versions:
            continue

        # Prefer a directory that already contains a settings.json, then any
        # existing User directory, so we never point at a plausible-looking path
        # that the IDE does not actually use.
        settings = None
        fallback = None
        for root in _settings_roots():
            for subdir in SETTINGS_SUBDIR.get(dirname, [label]):
                candidate = root / subdir / "User" / "settings.json"
                if candidate.is_file():
                    settings = str(candidate)
                    break
                if fallback is None and candidate.parent.is_dir():
                    fallback = str(candidate)
            if settings:
                break
        settings = settings or fallback

        found.append({
            "id": dirname,
            "label": label,
            "extensions": versions,
            "settings_path": settings,
            "stale": len(versions) > 1,
        })
    return found


MANAGED_ENV = ("CLAUDE_CONFIG_DIR", "CLAUDE_SECURESTORAGE_CONFIG_DIR")


def plan(profile: str):
    """The settings block Cortex would write, for a given profile.

    For the native default folder (~/.claude) the variables are deliberately NOT set: with
    CLAUDE_CONFIG_DIR set, Claude Code reads a different .claude.json and the default
    account loses its MCP servers and project state (see paths.is_native_default).
    """
    config_dir = profile_dir(profiles.normalize_name(profile))
    env = [] if is_native_default(config_dir) else [
        {"name": "CLAUDE_CONFIG_DIR", "value": config_dir},
        {"name": "CLAUDE_SECURESTORAGE_CONFIG_DIR", "value": config_dir},
    ]
    return {"claudeCode.environmentVariables": env, "claudeCode.disableLoginPrompt": True}


def merged(current: dict, desired: dict) -> dict:
    """What to write: the desired keys, but KEEPING the person's own environment variables.

    ``claudeCode.environmentVariables`` is a list shared with whatever the person already
    put there (API proxies, feature flags...). Only Cortex's own two entries are replaced.
    """
    out = dict(desired)
    existing = current.get("claudeCode.environmentVariables")
    kept = [entry for entry in (existing if isinstance(existing, list) else [])
            if not (isinstance(entry, dict) and entry.get("name") in MANAGED_ENV)]
    out["claudeCode.environmentVariables"] = kept + desired["claudeCode.environmentVariables"]
    return out


def _unknown_profile(profile):
    available = ", ".join(profiles.list_profiles()) or "none yet"
    print(f"cc: profile '{profile}' does not exist. Available: {available}", file=sys.stderr)
    return 1


def check(profile=None):
    """Report IDE state and what would be written. Never modifies anything."""
    profile = profile or profiles.active_profile()
    if profiles.normalize_name(profile) not in profiles.list_profiles():
        return _unknown_profile(profile)
    ides = detect()

    print("=" * 74)
    print("  Claude Cortex - IDE integration check")
    print("=" * 74)

    if not ides:
        print("\n  No IDEs with the Claude Code extension were found.")
        print("=" * 74)
        return 0

    desired = plan(profile)
    problems = 0

    for ide in ides:
        print(f"\n  {ide['label']}")
        print(f"    extension(s) : {', '.join(ide['extensions'])}")
        if ide["stale"]:
            problems += 1
            print("    WARN: multiple extension versions installed. Each bundles its own")
            print("          binary, and settings apply to whichever loads. Remove the")
            print("          older one from the IDE's extensions view.")

        if not ide["settings_path"]:
            problems += 1
            print("    WARN: could not locate this IDE's user settings.json")
            continue

        print(f"    settings     : {ide['settings_path']}")
        status, current = jsonfile.read_status(ide["settings_path"])
        if status == jsonfile.UNPARSEABLE:
            problems += 1
            print("    WARN: settings.json is not strict JSON (comments or trailing")
            print("          commas). Cortex will not rewrite it; 'ide apply' will")
            print("          print the keys for you to add by hand.")
            continue

        if current.get("claudeCode.claudeProcessWrapper"):
            problems += 1
            print("    WARN: claudeCode.claudeProcessWrapper is set. The extension passes")
            print("          its bundled binary as the first argument; a wrapper that does")
            print("          not expect that will fail. It also disables CLAUDE_CONFIG_DIR")
            print("          watching. Prefer environmentVariables unless you need it.")

        target = merged(current, desired)
        matches = all(current.get(k) == v for k, v in target.items())
        print(f"    configured   : {'yes' if matches else 'no'}")
        if not matches:
            env = desired["claudeCode.environmentVariables"]
            if env:
                print(f"    would set    : CLAUDE_CONFIG_DIR = {env[0]['value']}")
            else:
                print("    would clear  : Cortex's CLAUDE_CONFIG_DIR setting (the default account runs")
                print("                   with it unset, as plain `claude` does)")

    print("\n" + "=" * 74)
    print(f"  {problems} warning(s)" if problems else "  No warnings")
    print("  This command never modifies IDE settings. Use 'cc ide apply' for that.")
    print("=" * 74)
    return 0


def apply(profile=None, dry_run=True):
    """Write the Cortex block into each IDE's user settings.json.

    Additive and atomic: only the Cortex-managed keys are touched, every other
    setting (themes, keybindings, extensions) is preserved, and a backup is
    written before any change.
    """
    profile = profile or profiles.active_profile()
    if profiles.normalize_name(profile) not in profiles.list_profiles():
        return _unknown_profile(profile)
    desired = plan(profile)
    ides = detect()

    if not ides:
        print("No IDEs with the Claude Code extension were found.")
        return 0

    for ide in ides:
        if not ide["settings_path"]:
            print(f"  skip {ide['label']}: settings.json location unknown")
            continue

        status, current = jsonfile.read_status(ide["settings_path"])

        # A settings.json we cannot parse must never be rewritten. VS Code's
        # format is JSONC: comments and trailing commas are normal and perfectly
        # valid there, but json.load rejects them. Rewriting on a parse failure
        # would replace the user's entire configuration with just our two keys.
        if status == jsonfile.UNPARSEABLE:
            print(f"  {ide['label']}: settings.json could not be parsed as strict JSON")
            print("    This is normal - VS Code allows comments and trailing commas.")
            print("    Refusing to rewrite it, which would discard your settings.")
            print("    Add these keys by hand instead:")
            # Print the inner lines verbatim. Stripping trailing commas here
            # would produce a snippet that is not valid JSON to paste.
            body = json.dumps(desired, indent=2).splitlines()[1:-1]
            for line in body:
                print(f"      {line}")
            print("    (add a comma after the preceding entry when pasting)")
            continue

        target = merged(current, desired)
        if all(current.get(k) == v for k, v in target.items()):
            print(f"  {ide['label']}: already configured")
            continue

        if dry_run:
            print(f"  [dry-run] {ide['label']}: would set {', '.join(MANAGED_KEYS)}")
            continue

        current.update(target)
        jsonfile.write(ide["settings_path"], current)
        print(f"  {ide['label']}: configured for profile '{profile}' "
              f"(backup: settings.json.bak)")

    if dry_run:
        print("\n  Dry run - nothing was written. Re-run with --yes to apply.")
    return 0
