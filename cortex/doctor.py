"""
Diagnostics and repair.

``cc doctor`` answers the question "why is this not working", which previously
required reading source. ``cc doctor --repair`` fixes only what is unambiguous
and reversible.
"""

from __future__ import annotations

import os
import shutil

from . import binary, jsonfile, profiles
from .paths import (profile_dir, profiles_dir,
                    securestorage_suffix, shared_claude_dir, user_config_path)

OK = "ok"
WARN = "warn"
BAD = "FAIL"


def _check_binary():
    rows = binary.describe()
    working = [p for p, s in rows if s == "OK"]
    if working:
        return OK, f"Claude Code binary: {working[0]}", rows
    present = [p for p, s in rows if s != "missing"]
    if present:
        return BAD, "A Claude Code binary exists but none of them run", rows
    return BAD, "No Claude Code binary found", rows


def _check_settings(path=None, label=""):
    """Catch the compaction-loop settings in one settings file.

    Checked for the shared file *and* every profile file: profiles get a copy of
    the shared settings at creation, so a bad value propagates and then persists
    in each profile even after the shared file is fixed.
    """
    issues = []
    path = path or os.path.join(shared_claude_dir(), "settings.json")
    prefix = f"{label}: " if label else ""
    cfg = jsonfile.read(path, {})

    window = cfg.get("autoCompactWindow")
    if isinstance(window, (int, float)) and not (100_000 <= window <= 1_000_000):
        issues.append(f"{prefix}autoCompactWindow={window} is outside the valid 100k-1M range; "
                      f"sessions will compact far too early (remove the key)")

    for var in ("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "CLAUDE_CODE_AUTO_COMPACT_WINDOW"):
        if os.environ.get(var):
            issues.append(f"{prefix}{var} is set in the environment ({os.environ[var]}); "
                          f"it lowers the compaction threshold and locks /config")

    bash_max = cfg.get("bashOutputMaxChars")
    if isinstance(bash_max, int) and bash_max < 15000:
        issues.append(f"{prefix}bashOutputMaxChars={bash_max} is well below the 30000 default; "
                      f"output gets truncated and commands get re-run")

    hooks = cfg.get("hooks")
    if isinstance(hooks, dict):
        for entry in hooks.get("UserPromptSubmit") or []:
            if isinstance(entry, dict) and "matcher" in entry:
                issues.append(f"{prefix}" + "UserPromptSubmit hook declares a 'matcher', which that "
                              "event does not support; the entry may be skipped")
    return issues


def _check_profiles():
    issues = []
    for name in profiles.list_profiles():
        target = profile_dir(name)
        cfg = jsonfile.read(user_config_path(target), {})
        if not cfg.get("hasCompletedOnboarding"):
            issues.append((name, "will re-run first-run onboarding "
                                 f"(fix: cc login {name})"))
        settings = os.path.join(target, "settings.json")
        if os.path.islink(settings):
            issues.append((name, "settings.json is a link; /config and /model "
                                 "changes may be lost or leak across profiles"))
    return issues


def report(repair=False):
    print("=" * 74)
    print("  Claude Cortex - doctor")
    print("=" * 74)
    problems = 0

    status, message, rows = _check_binary()
    print(f"\n[binary] {status}: {message}")
    if status != OK:
        problems += 1
        for path, state in rows:
            print(f"    {state:<28} {path}")

    print("\n[paths]")
    print(f"    profiles root : {profiles_dir()}")
    print(f"    shared config : {shared_claude_dir()}")
    print(f"    active profile: {profiles.active_profile()}")

    print("\n[settings]")
    issues = _check_settings()
    for name in profiles.list_profiles():
        issues += _check_settings(
            os.path.join(profile_dir(name), "settings.json"),
            label=f"profile '{name}'")
    if issues:
        problems += len(issues)
        for issue in issues:
            print(f"    {WARN}: {issue}")
    else:
        print("    ok: no compaction or output-limit problems found")

    print("\n[profiles]")
    names = profiles.list_profiles()
    if not names:
        print("    (none configured - run: cc profile add)")
    for name in names:
        target = profile_dir(name)
        suffix = securestorage_suffix(target)
        email = profiles.profile_email(name) or "-"
        print(f"    {name:<12} {email:<28} creds-namespace {suffix}")

    prof_issues = _check_profiles()
    if prof_issues:
        problems += len(prof_issues)
        for name, issue in prof_issues:
            print(f"    {WARN}: {name}: {issue}")

    if repair:
        print("\n[repair]")
        problems -= _repair()

    print("\n" + "=" * 74)
    print(f"  {problems} problem(s) found" if problems else "  No problems found")
    print("=" * 74)
    return 1 if problems > 0 else 0


def _repair():
    """Fix only what is unambiguous. Returns the number of fixes applied."""
    fixed = 0
    # Repair writes into profile folders, so it only touches ones Cortex created. An
    # adopted folder holds a real account's data; it is reported on, never rewritten.
    from . import registry
    managed = [n for n in profiles.list_profiles() if not registry.is_adopted(n)]
    skipped = [n for n in profiles.list_profiles() if registry.is_adopted(n)]
    if skipped:
        print(f"    leaving adopted profile(s) untouched: {', '.join(skipped)}")

    # Remove an out-of-range autoCompactWindow: there is no valid reason for it
    # and it is the direct cause of the compaction loop.
    path = os.path.join(shared_claude_dir(), "settings.json")
    cfg = jsonfile.read(path, {})
    window = cfg.get("autoCompactWindow")
    if isinstance(window, (int, float)) and not (100_000 <= window <= 1_000_000):
        cfg.pop("autoCompactWindow", None)
        jsonfile.write(path, cfg)
        print(f"    removed invalid autoCompactWindow={window} (backup written)")
        fixed += 1

    for name in managed:
        prof_settings = os.path.join(profile_dir(name), "settings.json")
        pcfg = jsonfile.read(prof_settings, {})
        pwin = pcfg.get("autoCompactWindow")
        if isinstance(pwin, (int, float)) and not (100_000 <= pwin <= 1_000_000):
            pcfg.pop("autoCompactWindow", None)
            jsonfile.write(prof_settings, pcfg)
            print(f"    removed invalid autoCompactWindow={pwin} from profile '{name}'")
            fixed += 1

    # Re-seed onboarding for profiles that are signed in but would re-onboard.
    for name in managed:
        cfgp = os.path.join(profile_dir(name), ".claude.json")
        if not jsonfile.read(cfgp, {}).get("hasCompletedOnboarding"):
            if profiles.seed_identity(name):
                print(f"    seeded onboarding state for profile '{name}'")
                fixed += 1

    # Replace a linked settings.json with a real copy.
    for name in managed:
        settings = os.path.join(profile_dir(name), "settings.json")
        if os.path.islink(settings):
            try:
                real = os.path.realpath(settings)
                os.unlink(settings)
                shutil.copy2(real, settings)
                print(f"    converted '{name}' settings.json from link to copy")
                fixed += 1
            except OSError as exc:
                print(f"    could not convert '{name}' settings.json: {exc}")

    if not fixed:
        print("    nothing to repair")
    return fixed
