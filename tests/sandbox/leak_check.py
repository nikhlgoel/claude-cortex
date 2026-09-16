#!/usr/bin/env python3
"""
Filesystem leak detector for Cortex sandbox runs.

Takes a content snapshot of a directory tree before a scenario runs and compares
it afterwards. Any change outside an explicit allowlist fails the run.

This is the gate that proves a change to the installer, wrapper, or hooks does
not touch anything it was not supposed to - which matters because the failure
mode we are guarding against (clobbering a live Claude Code install) is silent
and only noticed much later.

Usage:
    leak_check.py snapshot <root> <snapshot.json>
    leak_check.py compare  <root> <snapshot.json> [--allow GLOB]... [--quiet]

Exit codes:
    0  no unexpected changes
    1  unexpected changes detected
    2  usage error
"""

import argparse
import fnmatch
import hashlib
import json
import os
import sys

# Paths that churn on their own and would otherwise produce constant false
# positives. These are noise, not evidence of a leak.
DEFAULT_IGNORES = [
    "**/.git/**",
    "**/__pycache__/**",
    "**/*.pyc",
    "**/.cache/**",
    "**/shell-snapshots/**",
    "**/session-env/**",
    "**/statsig/**",
    "**/.last-cleanup",
]

MAX_HASH_BYTES = 2 * 1024 * 1024  # files larger than this are tracked by size only


def _variants(pattern):
    """Pattern forms to try, so root-level paths match too.

    fnmatch has no notion of path segments, so "**/.cache/**" will not match
    ".cache/junk" - there is no leading segment for "**/" to consume. Anchored
    patterns are therefore also tried with that prefix stripped.
    """
    forms = [pattern]
    if pattern.startswith("**/"):
        forms.append(pattern[3:])
    return forms


def matches_any(rel_path, patterns):
    # Normalize to forward slashes so the same patterns work on Windows.
    candidate = rel_path.replace(os.sep, "/")
    for pattern in patterns:
        for form in _variants(pattern):
            if fnmatch.fnmatch(candidate, form):
                return True
            # Let "foo/**" also match "foo" itself and everything beneath it.
            if form.endswith("/**") and (
                candidate == form[:-3] or candidate.startswith(form[:-2])
            ):
                return True
    return False


def digest(path):
    try:
        size = os.path.getsize(path)
    except OSError:
        return "unreadable"
    if size > MAX_HASH_BYTES:
        return f"size:{size}"
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return "unreadable"
    return h.hexdigest()


def snapshot(root, ignores):
    """Map of relative path -> content digest."""
    entries = {}
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""
        # Prune ignored directories so we never descend into them.
        dirnames[:] = [
            d for d in dirnames
            if not matches_any(os.path.join(rel_dir, d), ignores)
        ]
        for name in filenames:
            rel = os.path.join(rel_dir, name) if rel_dir else name
            if matches_any(rel, ignores):
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                try:
                    entries[rel.replace(os.sep, "/")] = "link:" + os.readlink(full)
                except OSError:
                    entries[rel.replace(os.sep, "/")] = "link:unreadable"
            else:
                entries[rel.replace(os.sep, "/")] = digest(full)
    return entries


def compare(before, after, allow):
    added, removed, modified = [], [], []
    for path, dig in after.items():
        if path not in before:
            added.append(path)
        elif before[path] != dig:
            modified.append(path)
    for path in before:
        if path not in after:
            removed.append(path)

    def keep(paths):
        return sorted(p for p in paths if not matches_any(p, allow))

    return keep(added), keep(removed), keep(modified)


def main():
    parser = argparse.ArgumentParser(description="Cortex sandbox leak detector")
    parser.add_argument("action", choices=["snapshot", "compare"])
    parser.add_argument("root")
    parser.add_argument("snapshot_file")
    parser.add_argument("--allow", action="append", default=[],
                        help="glob of paths permitted to change (repeatable)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    ignores = list(DEFAULT_IGNORES)

    if args.action == "snapshot":
        data = snapshot(args.root, ignores)
        with open(args.snapshot_file, "w", encoding="utf-8") as fh:
            json.dump({"root": os.path.abspath(args.root), "entries": data}, fh)
        if not args.quiet:
            print(f"leak-check: snapshotted {len(data)} file(s) under {args.root}")
        return 0

    try:
        with open(args.snapshot_file, encoding="utf-8") as fh:
            saved = json.load(fh)
    except OSError as exc:
        print(f"leak-check: cannot read snapshot: {exc}", file=sys.stderr)
        return 2

    after = snapshot(args.root, ignores)
    added, removed, modified = compare(saved["entries"], after, args.allow)

    if not (added or removed or modified):
        if not args.quiet:
            print(f"leak-check: OK - no unexpected changes under {args.root}")
        return 0

    print("=" * 70)
    print("  LEAK DETECTED - files changed outside the permitted set")
    print("=" * 70)
    for label, paths in (("ADDED", added), ("REMOVED", removed), ("MODIFIED", modified)):
        for path in paths:
            print(f"  {label:9} {path}")
    print("=" * 70)
    print(f"  {len(added)} added, {len(removed)} removed, {len(modified)} modified")
    return 1


if __name__ == "__main__":
    sys.exit(main())
