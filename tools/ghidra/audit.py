#!/usr/bin/env python3
"""
Supply-chain audit for a Ghidra checkout.

Purpose and limits
------------------
This does NOT prove the absence of a backdoor. Nothing short of a full review of
~15,000 Java files plus a native C++ decompiler could attempt that, and even then
the claim would be weak. What it does instead is answer the question that
actually determines exposure:

    By what routes could this code send data outward, and are any of them
    reachable without the operator asking for it?

Every finding is evidence with a file and line, so it can be checked. Counts and
verdicts are derived, never asserted.

The audit is deliberately re-runnable. It is the mechanism by which an upstream
update is judged: run it before and after, and a new network path, a new
telemetry identifier, or a new build-time execution point shows up as a diff.

Usage:
    audit.py <ghidra-checkout> [--json] [--baseline FILE] [--write-baseline FILE]

Exit codes:
    0  no findings above the configured severity
    1  findings that warrant review
    2  usage error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# What we look for, and why each one matters.
# ---------------------------------------------------------------------------

#: Anything that could open an outbound connection.
NETWORK_PATTERNS = [
    (r"new\s+Socket\s*\(", "raw TCP socket"),
    (r"new\s+ServerSocket\s*\(", "listening socket"),
    (r"HttpURLConnection", "HTTP client"),
    (r"HttpClient", "HTTP client"),
    (r"\.openConnection\s*\(", "URL connection"),
    (r"new\s+URL\s*\(", "URL construction"),
    (r"InetAddress\.", "host resolution"),
    (r"DatagramSocket", "UDP socket"),
    (r"SSLSocket", "TLS socket"),
]

#: Identifiers that would indicate usage reporting. Absence is meaningful;
#: presence is a finding to investigate, not proof of wrongdoing.
TELEMETRY_TOKENS = [
    "telemetry", "analytics", "beacon", "phonehome", "phone_home",
    "usagestats", "trackevent", "sendmetrics", "crashreport",
    "io.sentry", "mixpanel", "google-analytics", "amplitude",
    "segment.io", "datadog", "newrelic",
]

#: Domains that would be unexpected in an open-source RE tool.
SUSPICIOUS_DOMAIN = re.compile(
    r"https?://[a-zA-Z0-9.-]*\.(gov|mil)\b|\bnsa\.gov\b", re.IGNORECASE)

#: Build-time execution is a supply-chain surface: a build script that downloads
#: and runs something can do anything the operator can.
BUILD_EXEC_PATTERNS = [
    (r"Runtime\.getRuntime\(\)\.exec", "runtime exec"),
    (r"commandLine\b", "gradle exec commandLine"),
    (r"\bdownload\s*\(", "build-time download"),
]

#: Schemes that are NOT network egress. "ghidra://" is Ghidra's own internal
#: project-URL scheme and "file://"/"jar://" are local. Counting these as
#: potential egress produced 85 false positives on the first run, which is worse
#: than useless: an audit that cries wolf gets ignored.
NON_NETWORK_URL = re.compile(
    r'new\s+URL\s*\(\s*"(ghidra|file|jar|classpath|resource)://', re.IGNORECASE)

#: Test sources describe behaviour under test, not shipped behaviour.
TEST_PATH = re.compile(r"/src/test[^/]*/|/test/|Test\.java$|TestUtils?\.java$")

#: Loopback connections cannot exfiltrate. This is the single most important
#: distinction for this threat model: a socket to 127.0.0.1 reaches a debugger
#: or an IDE on the same machine, and lumping it in with external egress buries
#: the findings that actually matter.
LOOPBACK = re.compile(
    r"getLocalHost|127\.0\.0\.1|\blocalhost\b|InetAddress\.getLoopback|::1\b",
    re.IGNORECASE)

SOURCE_EXTS = (".java",)
BUILD_EXTS = (".gradle", ".sh", ".bat", ".py")

#: Paths whose network use is expected and explainable. Listed so the report can
#: separate "expected, by design" from "unexplained", rather than hiding them.
EXPECTED_NETWORK_MODULES = {
    "Features/GhidraServer": "opt-in multi-user server; only runs if you start it",
    "Features/BSim": "function-similarity DB; connects to a database you configure",
    "Debug/Debugger-rmi-trace": "debugger connection the operator initiates",
    "Debug/Debugger-agent": "debugger agent the operator initiates",
    "Debug/Debugger-isf": "debug symbol format service",
    "Features/PDB": "Microsoft symbol server, opt-in",
    "Framework/Help": "opens documentation links in a browser",
    "Test/": "test code, not shipped behaviour",
    "EclipsePlugins": "connects to a local Eclipse instance",
    "loopback": "connects to 127.0.0.1 only - cannot exfiltrate",
    # ghidra.net is a TRANSPORT LIBRARY, not a caller. It builds HTTP clients,
    # SSL contexts, key and trust managers for whichever feature asks. Counting
    # its internals as egress sites overstates the surface: the question that
    # matters is who CALLS it, which the module breakdown above answers.
    "Framework/Generic/src/main/java/ghidra/net": "shared HTTP/TLS plumbing; provides transport, initiates nothing on its own",
    "Framework/FileSystem/src/main/java/ghidra/framework/client": "Ghidra Server client; only used against a server you configure",
    "Framework/Project/src/main/java/ghidra/framework/protocol": "ghidra:// URL scheme handling",
    "Framework/Docking/src/main/java/docking/help": "help system; opens documentation",
    "translate/libretranslate": "string translation via a LibreTranslate instance you configure; no default endpoint",
    "core/eclipse": "connects to a local Eclipse instance",
    "LoggingInitialization": "locates the log4j configuration file",
    # Verified by reading it: opens a GhidraURLConnection for a ghidra:// project
    # URL. Reaches the network only for a Ghidra Server the operator configured.
    "project/DefaultProject": "opens a ghidra:// project view; local unless you configured a server",
}


def walk_files(root, exts):
    skip = {".git", "build", "bin", "dist", "out"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            if name.endswith(exts):
                yield os.path.join(dirpath, name)


def rel(root, path):
    return os.path.relpath(path, root).replace(os.sep, "/")


def module_of(relpath):
    # Test code first: it is the largest category and never ships.
    if TEST_PATH.search(relpath):
        return "Test/"
    parts = relpath.split("/")
    for i in range(len(parts), 1, -1):
        candidate = "/".join(parts[:i])
        for known in EXPECTED_NETWORK_MODULES:
            if known in candidate:
                return known
    return None


def scan(root):
    findings = {
        "network": [],
        "telemetry": [],
        "suspicious_domains": [],
        "build_exec": [],
        "binaries": [],
        "dependencies": [],
    }

    compiled_net = [(re.compile(p), why) for p, why in NETWORK_PATTERNS]
    compiled_build = [(re.compile(p), why) for p, why in BUILD_EXEC_PATTERNS]

    for path in walk_files(root, SOURCE_EXTS):
        relpath = rel(root, path)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue

        for number, line in enumerate(lines, 1):
            lowered = line.lower()

            for pattern, why in compiled_net:
                if pattern.search(line):
                    # Skip Ghidra's own URL schemes - not egress.
                    if why == "URL construction" and NON_NETWORK_URL.search(line):
                        break
                    # The address is often bound a line or two above the call,
                    # so judge loopback on a small window rather than one line.
                    window = "".join(lines[max(0, number - 4):number + 1])
                    module = module_of(relpath)
                    if module is None and LOOPBACK.search(window):
                        module = "loopback"
                    findings["network"].append({
                        "file": relpath, "line": number, "kind": why,
                        "module": module,
                        "text": line.strip()[:160],
                    })
                    break

            for token in TELEMETRY_TOKENS:
                if token in lowered:
                    findings["telemetry"].append({
                        "file": relpath, "line": number, "token": token,
                        "text": line.strip()[:160],
                    })

            match = SUSPICIOUS_DOMAIN.search(line)
            if match:
                findings["suspicious_domains"].append({
                    "file": relpath, "line": number, "match": match.group(0),
                    "text": line.strip()[:160],
                })

    for path in walk_files(root, BUILD_EXTS):
        relpath = rel(root, path)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            for pattern, why in compiled_build:
                if pattern.search(line):
                    findings["build_exec"].append({
                        "file": relpath, "line": number, "kind": why,
                        "text": line.strip()[:160],
                    })
                    break

    # Binaries cannot be source-audited, so they are always reported.
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            if name.endswith((".so", ".dll", ".exe", ".dylib", ".jar")):
                full = os.path.join(dirpath, name)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = -1
                findings["binaries"].append({
                    "file": rel(root, full), "bytes": size})

    # Declared third-party dependencies: a malicious dependency needs no change
    # to Ghidra's own source.
    dep_re = re.compile(
        r"""(?:api|implementation|compileOnly|runtimeOnly|testImplementation)\s+"""
        r"""['"]([a-z0-9._-]+):([A-Za-z0-9._-]+):([0-9][^'"]*)['"]""")
    for path in walk_files(root, (".gradle",)):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            continue
        for group, artifact, version in dep_re.findall(content):
            findings["dependencies"].append(
                {"coordinate": f"{group}:{artifact}", "version": version})

    return findings


def summarize(findings):
    net_by_module = defaultdict(int)
    unexplained = []
    for item in findings["network"]:
        key = item["module"] or "UNEXPLAINED"
        net_by_module[key] += 1
        if item["module"] is None:
            unexplained.append(item)

    deps = sorted({(d["coordinate"], d["version"]) for d in findings["dependencies"]})

    return {
        "network_sites": len(findings["network"]),
        "network_by_module": dict(sorted(net_by_module.items(),
                                         key=lambda kv: -kv[1])),
        "network_unexplained": unexplained,
        "telemetry_hits": len(findings["telemetry"]),
        "suspicious_domain_hits": len(findings["suspicious_domains"]),
        "build_exec_sites": len(findings["build_exec"]),
        "binaries": len(findings["binaries"]),
        "dependencies": len(deps),
        "dependency_list": [f"{c}:{v}" for c, v in deps],
    }


def render(findings, summary, root):
    out = []
    add = out.append
    add("=" * 74)
    add("  Ghidra supply-chain audit")
    add("=" * 74)
    add(f"  checkout: {root}")
    add("")
    add("  This does not prove the absence of a backdoor. It enumerates the")
    add("  routes by which data could leave, so they can be judged individually")
    add("  and re-checked on every update.")
    add("")

    add("-" * 74)
    add("  NETWORK EGRESS")
    add("-" * 74)
    add(f"  {summary['network_sites']} call site(s) that could open a connection.")
    add("")
    for module, count in summary["network_by_module"].items():
        why = EXPECTED_NETWORK_MODULES.get(module, "")
        label = module if module != "UNEXPLAINED" else "*** UNEXPLAINED ***"
        add(f"    {count:4d}  {label}")
        if why:
            add(f"          {why}")
    if summary["network_unexplained"]:
        add("")
        add("  Sites outside any expected module - review each:")
        for item in summary["network_unexplained"][:25]:
            add(f"    {item['file']}:{item['line']}  ({item['kind']})")
            add(f"        {item['text']}")

    add("")
    add("-" * 74)
    add("  TELEMETRY / USAGE REPORTING")
    add("-" * 74)
    if summary["telemetry_hits"] == 0:
        add("  No telemetry, analytics, or crash-reporting identifiers found.")
    else:
        add(f"  {summary['telemetry_hits']} hit(s) - review each:")
        for item in findings["telemetry"][:25]:
            add(f"    {item['file']}:{item['line']}  [{item['token']}]")
            add(f"        {item['text']}")

    add("")
    add("-" * 74)
    add("  GOVERNMENT / UNEXPECTED DOMAINS")
    add("-" * 74)
    if summary["suspicious_domain_hits"] == 0:
        add("  No .gov, .mil, or nsa.gov references in source or configuration.")
    else:
        for item in findings["suspicious_domains"][:25]:
            add(f"    {item['file']}:{item['line']}  {item['match']}")

    add("")
    add("-" * 74)
    add("  BUILD-TIME EXECUTION")
    add("-" * 74)
    add(f"  {summary['build_exec_sites']} site(s) where the build runs a command.")
    add("  Build scripts execute with your privileges, so a change here matters")
    add("  as much as a change to the application itself.")

    add("")
    add("-" * 74)
    add("  UNAUDITABLE ARTIFACTS")
    add("-" * 74)
    add(f"  {summary['binaries']} binary file(s) committed in-tree.")
    for item in findings["binaries"][:20]:
        add(f"    {item['file']}  ({item['bytes']} bytes)")

    add("")
    add("-" * 74)
    add("  THIRD-PARTY DEPENDENCIES")
    add("-" * 74)
    add(f"  {summary['dependencies']} distinct coordinate(s). A malicious")
    add("  dependency needs no change to Ghidra's own source.")
    for coordinate in summary["dependency_list"][:40]:
        add(f"    {coordinate}")

    add("")
    add("=" * 74)
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="Ghidra supply-chain audit")
    parser.add_argument("checkout")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--baseline", help="compare against a previous baseline")
    parser.add_argument("--write-baseline", help="write findings as a baseline")
    args = parser.parse_args()

    root = os.path.abspath(args.checkout)
    if not os.path.isdir(root):
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    findings = scan(root)
    summary = summarize(findings)

    if args.write_baseline:
        with open(args.write_baseline, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, sort_keys=True)
        print(f"baseline written: {args.write_baseline}")

    if args.json:
        print(json.dumps({"summary": summary, "findings": findings},
                         indent=2, sort_keys=True))
    else:
        print(render(findings, summary, root))

    if args.baseline:
        try:
            with open(args.baseline, encoding="utf-8") as fh:
                previous = json.load(fh)
        except OSError as exc:
            print(f"cannot read baseline: {exc}", file=sys.stderr)
            return 2

        print("\n" + "=" * 74)
        print("  CHANGE SINCE BASELINE")
        print("=" * 74)
        regressed = False
        for key in ("network_sites", "telemetry_hits", "suspicious_domain_hits",
                    "build_exec_sites", "binaries"):
            before, after = previous.get(key, 0), summary.get(key, 0)
            arrow = "=" if before == after else ("UP" if after > before else "down")
            print(f"  {key:26} {before:5} -> {after:5}  [{arrow}]")
            if after > before:
                regressed = True

        new_deps = set(summary["dependency_list"]) - set(previous.get("dependency_list", []))
        if new_deps:
            regressed = True
            print("\n  NEW DEPENDENCIES:")
            for dep in sorted(new_deps):
                print(f"    + {dep}")

        print("=" * 74)
        if regressed:
            print("  Review required: the attack surface grew.")
            return 1
        print("  No growth in attack surface.")
        return 0

    # Without a baseline, only unambiguous findings fail the run.
    if summary["telemetry_hits"] or summary["suspicious_domain_hits"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
