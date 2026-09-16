#!/usr/bin/env python3
"""
Upstream update watcher for Ghidra. Reports; never applies.

Why it does not auto-apply
--------------------------
The obvious design is: fetch the diff, classify it, apply it if it looks like a
bugfix. That design is worse than it sounds. Distinguishing "a refactor of the
HTTP client" from "a refactor of the HTTP client that also adds a header" is
exactly the judgement an automated classifier is least able to make, and it is
precisely the case this exists to catch. Auto-applying on a classifier's verdict
would produce confidence without the property the confidence is about.

So this produces a report with evidence, and a human decides. The report is
designed to make that decision quick rather than to make it for you:

  * the release notes upstream published
  * a re-run of the supply-chain audit against the new tag, diffed against the
    recorded baseline, so a new network path or dependency is visible as a
    change rather than buried in a file count
  * every changed file bucketed by risk, highest first
  * an explicit list of what a human must look at before accepting

Usage:
    update_watch.py check                 report on newer releases
    update_watch.py check --ref TAG       report on a specific tag
    update_watch.py baseline <checkout>   record the current audit as baseline
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

REPO = "NationalSecurityAgency/ghidra"
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "watch-state.json")
AUDIT = os.path.join(HERE, "audit.py")

# Paths whose change means the review must be manual, in descending severity.
# A file matching a higher bucket is reported there even if it also matches a
# lower one.
RISK_BUCKETS = [
    ("CRITICAL", "network, crypto or transport code", [
        r"/ghidra/net/", r"Socket", r"Http", r"SSL", r"TrustManager",
        r"KeyManager", r"Certificate",
    ]),
    ("CRITICAL", "build scripts - run with your privileges", [
        r"\.gradle$", r"gradlew", r"/gradle/", r"\.sh$", r"\.bat$",
    ]),
    ("HIGH", "dependency declarations", [
        r"dependencies", r"fetchDependencies", r"\.lock$", r"pom\.xml$",
    ]),
    ("HIGH", "binary artifacts - cannot be source-reviewed", [
        r"\.so$", r"\.dll$", r"\.exe$", r"\.dylib$", r"\.jar$", r"\.bin$",
    ]),
    ("HIGH", "server, client or remote-protocol code", [
        r"GhidraServer", r"/client/", r"/protocol/", r"rmi", r"BSim",
    ]),
    ("MEDIUM", "process execution or scripting surfaces", [
        r"Exec", r"ProcessBuilder", r"Runtime", r"/script", r"Jython", r"PyGhidra",
    ]),
    ("LOW", "analysis, decompiler, loaders, processors", [
        r"/Decompiler/", r"/Processors/", r"/Features/", r"\.slaspec$", r"\.sinc$",
    ]),
    ("INFO", "documentation and tests", [
        r"\.md$", r"\.html$", r"/docs?/", r"/src/test", r"Test\.java$",
    ]),
]

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "UNCLASSIFIED"]


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def gh_api(path, jq=None):
    cmd = ["gh", "api", path]
    if jq:
        cmd += ["--jq", jq]
    result = run(cmd, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300])
    return result.stdout


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")


def classify(path):
    for severity, reason, patterns in RISK_BUCKETS:
        for pattern in patterns:
            if re.search(pattern, path, re.IGNORECASE):
                return severity, reason
    return "UNCLASSIFIED", "not matched by any rule - review by hand"


def compare_tags(base, head):
    """Files changed between two tags, via the GitHub compare API."""
    raw = gh_api(f"repos/{REPO}/compare/{base}...{head}")
    data = json.loads(raw)
    files = []
    for entry in data.get("files", []):
        files.append({
            "path": entry.get("filename", ""),
            "status": entry.get("status", ""),
            "additions": entry.get("additions", 0),
            "deletions": entry.get("deletions", 0),
        })
    return {
        "ahead_by": data.get("ahead_by", 0),
        "total_commits": data.get("total_commits", 0),
        "files": files,
        "truncated": len(files) >= 300,
    }


def audit_tag(ref, baseline):
    """Clone a tag shallowly and re-run the supply-chain audit against it."""
    workdir = tempfile.mkdtemp(prefix="ghidra-audit-")
    checkout = os.path.join(workdir, "ghidra")
    try:
        clone = run(["git", "clone", "--depth", "1", "--branch", ref,
                     "--single-branch",
                     f"https://github.com/{REPO}.git", checkout], timeout=1800)
        if clone.returncode != 0:
            return None, f"clone failed: {clone.stderr.strip()[:200]}"

        cmd = [sys.executable, AUDIT, checkout]
        if baseline and os.path.exists(baseline):
            cmd += ["--baseline", baseline]
        result = run(cmd, timeout=1800)
        return result.stdout, None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def cmd_check(args):
    state = load_state()
    current = state.get("current_ref")

    releases = json.loads(gh_api(
        f"repos/{REPO}/releases",
        ".[0:10] | [.[] | {tag: .tag_name, published: .published_at, name: .name, body: .body}]"))

    if not releases:
        print("no releases found")
        return 1

    latest = args.ref or releases[0]["tag"]

    print("=" * 74)
    print("  Ghidra upstream update report")
    print("=" * 74)
    print(f"  generated : {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"  pinned at : {current or '(no baseline recorded)'}")
    print(f"  upstream  : {latest}")
    print()

    if current == latest:
        print("  Already at the latest release. Nothing to review.")
        print("=" * 74)
        return 0

    for release in releases[:5]:
        marker = "->" if release["tag"] == latest else "  "
        print(f"  {marker} {release['tag']:26} {release['published'][:10]}  {release['name']}")
    print()

    if not current:
        print("  No pinned baseline, so there is nothing to diff against.")
        print("  Record one with:  update_watch.py baseline <checkout>")
        print("=" * 74)
        return 1

    # ---- what changed -----------------------------------------------------
    print("-" * 74)
    print(f"  CHANGED FILES  {current} -> {latest}")
    print("-" * 74)
    try:
        comparison = compare_tags(current, latest)
    except RuntimeError as exc:
        print(f"  could not compare: {exc}")
        return 1

    buckets = {}
    for entry in comparison["files"]:
        severity, reason = classify(entry["path"])
        buckets.setdefault((severity, reason), []).append(entry)

    print(f"  {comparison['total_commits']} commit(s), "
          f"{len(comparison['files'])} file(s) changed")
    if comparison["truncated"]:
        print("  NOTE: the file list is truncated by the API. Treat the")
        print("        classification below as incomplete and review the full")
        print("        diff before accepting.")
    print()

    for severity in SEVERITY_ORDER:
        for (sev, reason), entries in sorted(buckets.items()):
            if sev != severity:
                continue
            print(f"  [{sev}] {reason}  ({len(entries)} file(s))")
            for entry in entries[:12]:
                print(f"       {entry['status'][:6]:6} +{entry['additions']:<5} "
                      f"-{entry['deletions']:<5} {entry['path']}")
            if len(entries) > 12:
                print(f"       ... and {len(entries) - 12} more")
            print()

    # ---- did the attack surface grow? -------------------------------------
    print("-" * 74)
    print("  SUPPLY-CHAIN AUDIT OF THE NEW TAG")
    print("-" * 74)
    if args.no_audit:
        print("  skipped (--no-audit)")
    else:
        print(f"  cloning {latest} and re-running the audit; this takes a few minutes")
        baseline = args.baseline or os.path.join(HERE, "baseline-current.json")
        report, error = audit_tag(latest, baseline)
        if error:
            print(f"  {error}")
        else:
            tail = report.strip().splitlines()
            start = 0
            for index, line in enumerate(tail):
                if "CHANGE SINCE BASELINE" in line:
                    start = max(0, index - 1)
                    break
            print("\n".join("  " + line for line in tail[start:start + 24]))

    # ---- what a person still has to do ------------------------------------
    print()
    print("=" * 74)
    print("  THIS REPORT DOES NOT APPLY THE UPDATE")
    print("=" * 74)
    print("  Automated classification cannot reliably tell a refactor of network")
    print("  code from a refactor that also changes what is sent. That is the")
    print("  case this exists to catch, so a person decides.")
    print()
    print("  Before accepting, read the actual diff for every CRITICAL and HIGH")
    print("  file above:")
    print(f"    https://github.com/{REPO}/compare/{current}...{latest}")
    print()
    print("  Then pin the new version:")
    print(f"    update_watch.py pin {latest}")
    print("=" * 74)
    return 1


def cmd_baseline(args):
    checkout = os.path.abspath(args.checkout)
    if not os.path.isdir(checkout):
        print(f"not a directory: {checkout}", file=sys.stderr)
        return 2
    target = args.out or os.path.join(HERE, "baseline-current.json")
    result = run([sys.executable, AUDIT, checkout, "--write-baseline", target],
                 timeout=1800)
    print(result.stdout.strip() or result.stderr.strip())
    return result.returncode if result.returncode in (0, 1) else 0


def cmd_pin(args):
    state = load_state()
    state["current_ref"] = args.ref
    state["pinned_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_state(state)
    print(f"pinned to {args.ref}")
    print("Rebuild the container so the running image matches what you reviewed:")
    print(f"  docker build -f tools/ghidra/Dockerfile --build-arg GHIDRA_REF={args.ref} "
          f"-t cortex-ghidra:{args.ref} .")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Ghidra update watcher (report only)")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="report on newer releases")
    check.add_argument("--ref", help="report on a specific tag")
    check.add_argument("--baseline", help="audit baseline to diff against")
    check.add_argument("--no-audit", action="store_true",
                       help="skip the clone-and-audit step")
    check.set_defaults(func=cmd_check)

    baseline = sub.add_parser("baseline", help="record an audit baseline")
    baseline.add_argument("checkout")
    baseline.add_argument("--out")
    baseline.set_defaults(func=cmd_baseline)

    pin = sub.add_parser("pin", help="record the reviewed version")
    pin.add_argument("ref")
    pin.set_defaults(func=cmd_pin)

    args = parser.parse_args()
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
