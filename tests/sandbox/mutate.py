#!/usr/bin/env python3
"""
Mutation testing: does the suite actually detect regressions?

A suite that only ever reports zero failures proves nothing on its own - it may
simply be unable to fail. This deliberately reintroduces each bug that was fixed
and checks that some test notices.

A MISSED mutation means the corresponding test is decorative: the bug could
return and nothing would catch it.

Usage:
    mutate.py            run every mutation
    mutate.py --list     show them without running
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

WORK = os.environ.get("CORTEX_WORK", "/work")

# (label, file, original snippet, replacement, command to detect it)
#
# Each entry reintroduces a real defect from the history of this repository.
MUTATIONS = [
    (
        "UnicodeDecodeError on binary current_profile",
        "cortex/profiles.py",
        'with open(current_profile_file(), encoding="utf-8", errors="replace") as fh:',
        'with open(current_profile_file(), encoding="utf-8") as fh:',
        ["fuzz"],
    ),
    (
        "unknown command reaches a session as a prompt",
        "cortex/__main__.py",
        'if not head.startswith("-") and " " not in head:',
        'if not head.startswith("-") and " " not in head and not rest:',
        ["fuzz"],
    ),
    (
        "JSONC settings.json is rewritten, destroying user settings",
        "cortex/ide.py",
        "if status == jsonfile.UNPARSEABLE:\n            print(f\"  {ide['label']}: settings.json could not be parsed as strict JSON\")",
        "if False:\n            print(f\"  {ide['label']}: settings.json could not be parsed as strict JSON\")",
        ["scenario:jsonc"],
    ),
    (
        # NOT the trailing-separator strip: Path.resolve() already removes those,
        # so mutating it is a no-op and would report a false MISSED. Unicode
        # normalization genuinely changes the hashed string.
        "credential namespace not NFC-normalized",
        "cortex/paths.py",
        'return unicodedata.normalize("NFC", result)',
        "return result",
        ["fuzz"],
    ),
    (
        "unknown capacity reported as free",
        "cortex/capacity.py",
        'record["state"] = UNKNOWN\n        record["detail"] = "no usage data recorded yet"',
        'record["state"] = KNOWN_FREE\n        record["detail"] = "no usage data recorded yet"',
        ["scenario:capacity"],
    ),
    (
        "compaction override passed through to the CLI",
        "cortex/launcher.py",
        'for stale in ("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "CLAUDE_CODE_AUTO_COMPACT_WINDOW",',
        'for stale in ("CORTEX_NOTHING_AT_ALL", "CORTEX_ALSO_NOTHING",',
        ["scenario:compaction"],
    ),
    (
        "prompt hook intercepts bare keywords again",
        "scripts/cortex-prompt-hook.py",
        'if head in ("/cc", "!cc"):',
        'if head in ("/cc", "!cc", "switch", "test", "continue", "claude"):',
        ["scenario:prompt-hook"],
    ),
    (
        "IDE settings path guessed instead of probed",
        "cortex/ide.py",
        '".antigravity-ide": ["Antigravity IDE", "Antigravity"],',
        '".antigravity-ide": ["Antigravity"],',
        ["scenario:ide-paths"],
    ),
    (
        "profile name shadowing a command is allowed",
        "cortex/__main__.py",
        "if name in TOP_LEVEL_COMMANDS or tools.is_retired(name):",
        "if False:",
        ["scenario:edge-cases"],
    ),
    (
        "removing the last profile leaves a stale pointer",
        "cortex/profiles.py",
        'set_active("")\n            print("No profiles remain. Create one with: cc profile add")',
        'print("No profiles remain. Create one with: cc profile add")',
        ["scenario:edge-cases"],
    ),
]


def run_detector(detector, env, run_id=0, tree=None):
    """Run one detector, returning True when it FAILS (i.e. caught the bug).

    Each run gets a fresh sandbox directory. Sharing one made results
    order-dependent: state left by an earlier mutation changed whether a later
    one was detected, so the same mutation was CAUGHT standalone and MISSED
    inside the full suite. A detector that depends on what ran before it is not
    measuring what it claims to.
    """
    # Start from a sanitized environment. Inheriting the caller's CLAUDE_* and
    # CORTEX_* variables made results depend on which scenario ran before this
    # one: the same mutation was CAUGHT standalone and MISSED inside the full
    # suite. A detector whose verdict depends on ambient state is not measuring
    # what it claims to.
    env = {k: v for k, v in env.items()
           if not k.startswith(("CLAUDE_", "CORTEX_"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    scratch = os.path.join(tempfile.gettempdir(), f"mutate-{run_id}-{detector.replace(':', '-')}")
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch, exist_ok=True)
    env["CORTEX_SANDBOX_DIR"] = scratch
    env["CORTEX_STUB_LOG"] = os.path.join(scratch, "stub.jsonl")

    work = tree or WORK
    env["PYTHONPATH"] = work
    env["CORTEX_WORK"] = work
    env["CORTEX_WORK_DIR"] = work

    if detector == "fuzz":
        cmd = [sys.executable, os.path.join(work, "tests/sandbox/fuzz.py"),
               "--seed", "20260916", "--arg-rounds", "25", "--state-rounds", "15"]
    elif detector.startswith("scenario:"):
        cmd = ["bash", os.path.join(work, "tests/sandbox/entrypoint.sh"),
               detector.split(":", 1)[1]]
        # Without this the scenario runner re-copies /work from the read-only
        # /repo mount, undoing the mutation and reporting a false pass.
        env["CORTEX_NO_RESET"] = "1"
    else:
        raise ValueError(detector)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=400, env=env, cwd=work,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return True, "timeout (counts as detection)"

    output = proc.stdout + proc.stderr
    caught = proc.returncode != 0 or "FAIL" in output or "FAILURE" in output
    if not caught and os.environ.get("MUTATE_DEBUG") == "1":
        print(f"      [debug] {detector} rc={proc.returncode} scratch={scratch}")
        for line in output.strip().splitlines()[-8:]:
            print(f"      [debug] {line}")
    first = ""
    for line in output.splitlines():
        if "FAIL" in line or line.strip().startswith("- "):
            first = line.strip()[:110]
            break
    return caught, first


def purge_bytecode():
    """Stale .pyc files would mask a mutation entirely."""
    for root, dirs, _ in os.walk(WORK):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)


def main():
    parser = argparse.ArgumentParser(description="Cortex mutation testing")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        for label, path, _, _, detectors in MUTATIONS:
            print(f"  {label}\n      {path}  detected by: {', '.join(detectors)}")
        return 0

    env = dict(os.environ)
    env["PYTHONPATH"] = WORK
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("CORTEX_STUB_LOG", "/tmp/mutate-stub.jsonl")

    print("=" * 74)
    print("  Mutation testing - reintroducing fixed bugs to see if tests notice")
    print("=" * 74)

    missed, caught_count, skipped = [], 0, []

    for index, (label, rel_path, old, new, detectors) in enumerate(MUTATIONS):
        # Mutate a PRIVATE COPY of the tree. Mutating the shared /work made the
        # verdict depend on which scenarios had already run against it - the same
        # mutation was CAUGHT alone and MISSED inside the full suite. Anything
        # whose answer changes with run order is not measuring what it claims to.
        tree = os.path.join(tempfile.gettempdir(), f"mutwork-{index}")
        shutil.rmtree(tree, ignore_errors=True)
        shutil.copytree(WORK, tree, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
        path = os.path.join(tree, rel_path)
        try:
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
        except OSError as exc:
            skipped.append((label, f"cannot read {rel_path}: {exc}"))
            continue

        if old not in source:
            # A mutation that does not apply is a silent no-op that would look
            # like a passing test, so report it loudly instead.
            skipped.append((label, f"snippet not found in {rel_path}"))
            continue

        try:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(source.replace(old, new, 1))
            purge_bytecode()

            detected, detail = False, ""
            for slot, detector in enumerate(detectors):
                detected, detail = run_detector(detector, env, run_id=slot, tree=tree)
                if detected:
                    break

            if detected:
                caught_count += 1
                print(f"  CAUGHT  {label}")
                if detail:
                    print(f"          by: {detail}")
            else:
                missed.append((label, rel_path, detectors))
                print(f"  MISSED  {label}")
                print(f"          {rel_path} - detectors {detectors} did not fail")
        finally:
            # The private copy is disposable, so simply discard it.
            shutil.rmtree(tree, ignore_errors=True)

    print("\n" + "=" * 74)
    total = caught_count + len(missed)
    print(f"  {caught_count}/{total} mutations caught")
    if skipped:
        print(f"  {len(skipped)} skipped (mutation no longer applies):")
        for label, why in skipped:
            print(f"    - {label}: {why}")
    if missed:
        print("\n  Tests that do not actually protect anything:")
        for label, path, detectors in missed:
            print(f"    - {label} ({path}) - claimed cover: {', '.join(detectors)}")
    print("=" * 74)
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
