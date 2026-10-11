#!/usr/bin/env python3
"""
Dream - counterfactual risk analysis.

This used to print a fixed checklist. Two unrelated topics produced byte-identical
output, because it did no analysis at all: it named categories of failure and left
the reader to do the work. That is not an engine, and it was documented as one.

It now reads the code and reports findings with a file, a line, and the mechanism
by which the thing fails. A finding names something that is actually there.

Design notes
------------
Every detector is written to be *quiet*. A risk scanner that reports fifty
maybes gets ignored after the second run, which is worse than having no scanner:
it trains you to skim. So each rule either has a concrete failure mode or it does
not ship. Where a rule cannot avoid false positives, it says what would make the
finding benign, so dismissing it is quick.

Findings are ranked by whether the failure is silent. A crash gets noticed; a
swallowed error or a lost write does not, so those rank higher.

Usage:
    claude-dream.py                     analyse uncommitted changes
    claude-dream.py --all               analyse the whole tree
    claude-dream.py --path DIR          analyse a directory
    claude-dream.py --since HEAD~5      analyse a commit range
    claude-dream.py --json
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys

# Severity ranks by how quietly the failure happens, not by how dramatic it is.
SILENT = "SILENT"      # wrong results, no error - the worst kind
LOUD = "LOUD"          # crashes or hangs; noticed, still bad
FRAGILE = "FRAGILE"    # works now, breaks under load, scale or concurrency
RANK = {SILENT: 0, LOUD: 1, FRAGILE: 2}


class Finding:
    def __init__(self, severity, chamber, path, line, title, mechanism,
                 code="", benign_if=""):
        self.severity = severity
        self.chamber = chamber
        self.path = path
        self.line = line
        self.title = title
        self.mechanism = mechanism
        self.code = code
        self.benign_if = benign_if

    def as_dict(self):
        return {
            "severity": self.severity, "chamber": self.chamber,
            "file": self.path, "line": self.line, "title": self.title,
            "mechanism": self.mechanism, "code": self.code,
            "benign_if": self.benign_if,
        }


# ---------------------------------------------------------------------------
# Python AST analysis. The AST is used rather than regex wherever the question
# is structural, because "is this except clause empty" is not a text question.
# ---------------------------------------------------------------------------

#: Expressions whose value originates outside this program.
EXTERNAL_SOURCES = (
    "input", "sys.argv", "os.environ", "os.getenv", "getenv",
    "request.args", "request.form", "request.json", "sys.stdin.read",
)


class PythonVisitor(ast.NodeVisitor):
    def __init__(self, path, source):
        self.path = path
        self.lines = source.splitlines()
        self.findings = []
        self.function_stack = []
        # Shallow taint tracking: names assigned from an external source.
        #
        # Without this, the path-join rule fired on every os.path.join in the
        # file - five findings, all of them joins of already-normalized internal
        # values. A rule that is wrong five times out of five is worse than
        # absent: it teaches the reader to skim past the section it lives in.
        self.tainted = set()

    def code_at(self, node):
        index = getattr(node, "lineno", 1) - 1
        if 0 <= index < len(self.lines):
            return self.lines[index].strip()[:120]
        return ""

    def add(self, severity, chamber, node, title, mechanism, benign_if=""):
        self.findings.append(Finding(
            severity, chamber, self.path, getattr(node, "lineno", 0),
            title, mechanism, self.code_at(node), benign_if))

    # -- swallowed errors ---------------------------------------------------
    def visit_ExceptHandler(self, node):
        body = node.body
        only_pass = len(body) == 1 and isinstance(body[0], ast.Pass)
        bare = node.type is None
        broad = isinstance(node.type, ast.Name) and node.type.id in (
            "Exception", "BaseException")

        if only_pass and (bare or broad):
            self.add(
                SILENT, "error handling", node,
                "Exception swallowed with no trace",
                "The failure leaves nothing behind: no log line, no re-raise, "
                "no return value change. When this fires the caller proceeds on "
                "the assumption the operation succeeded, and the first symptom "
                "appears somewhere unrelated.",
                benign_if="the operation is genuinely optional AND a comment "
                          "says so")
        elif bare:
            self.add(
                FRAGILE, "error handling", node,
                "Bare except catches everything",
                "A bare except also catches KeyboardInterrupt and SystemExit, so "
                "Ctrl+C and process shutdown get absorbed by code that meant to "
                "handle an IO error.")
        self.generic_visit(node)

    # -- mutable default arguments -----------------------------------------
    def visit_FunctionDef(self, node):
        self.function_stack.append(node.name)
        for default in node.args.defaults + node.args.kw_defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.add(
                    SILENT, "state", default,
                    f"Mutable default argument in {node.name}()",
                    "The default is created once at definition time and shared "
                    "by every call that omits the argument. One caller's "
                    "appends are visible to the next, and the bug only appears "
                    "on the second call.")
        self.generic_visit(node)
        self.function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        source = ast.unparse(node.value) if hasattr(ast, "unparse") else ""
        if any(src in source for src in EXTERNAL_SOURCES):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.tainted.add(target.id)
        self.generic_visit(node)

    # -- calls: timeouts, shells, deserialization --------------------------
    def visit_Call(self, node):
        name = self._call_name(node)
        kwargs = {kw.arg for kw in node.keywords if kw.arg}

        # Network and subprocess calls without a timeout hang forever.
        if name in ("requests.get", "requests.post", "requests.put",
                    "requests.delete", "requests.head", "requests.request",
                    "urlopen", "urllib.request.urlopen"):
            if "timeout" not in kwargs:
                self.add(
                    LOUD, "resource", node,
                    f"{name}() with no timeout",
                    "Python's default socket timeout is None, so a peer that "
                    "accepts the connection and never replies blocks this "
                    "thread indefinitely. A hung command looks like a crash "
                    "with none of the diagnostics.")

        if name in ("subprocess.run", "subprocess.call", "subprocess.check_call",
                    "subprocess.check_output", "subprocess.Popen"):
            if "timeout" not in kwargs and name != "subprocess.Popen":
                self.add(
                    FRAGILE, "resource", node,
                    f"{name}() with no timeout",
                    "A child process that never exits blocks the parent for "
                    "ever. This matters most for anything spawned in a loop or "
                    "on a code path a user waits on.")
            for keyword in node.keywords:
                if keyword.arg == "shell" and _is_true(keyword.value):
                    self.add(
                        SILENT, "security", node,
                        f"{name}(shell=True)",
                        "The command string is parsed by a shell, so any "
                        "interpolated value can inject further commands via ;, "
                        "|, $(), or backticks. Passing an argv list removes the "
                        "shell from the picture entirely.",
                        benign_if="the command is a fixed literal with no "
                                  "interpolation")

        if name in ("pickle.load", "pickle.loads", "yaml.load", "marshal.loads"):
            self.add(
                SILENT, "security", node,
                f"{name}() on possibly untrusted data",
                "These constructors execute code during deserialization. If the "
                "input can be influenced, this is arbitrary code execution "
                "rather than a parsing bug.",
                benign_if="the input is produced by this program and never "
                          "leaves the machine")

        if name in ("eval", "exec"):
            self.add(
                SILENT, "security", node, f"{name}() call",
                "Evaluates whatever string it is given. If any part of that "
                "string derives from input, this executes it.")

        # os.path.join with an EXTERNALLY-SOURCED variable is the traversal
        # shape. Joining an internal value is ordinary path building and
        # reporting it is noise.
        if name == "os.path.join" and len(node.args) >= 2:
            if any(isinstance(a, ast.Name) and a.id in self.tainted
                   for a in node.args[1:]):
                self.add(
                    FRAGILE, "security", node,
                    "Path built by joining a variable",
                    "os.path.join discards everything before an absolute "
                    "component, and does not collapse '..'. A value of "
                    "'../../etc/passwd' or '/etc/passwd' escapes the intended "
                    "directory.",
                    benign_if="the variable is validated, or comes from a fixed "
                              "set")

        self.generic_visit(node)

    def _call_name(self, node):
        func = node.func
        parts = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
        return ".".join(reversed(parts))

    # -- non-atomic writes --------------------------------------------------
    def visit_With(self, node):
        for item in node.items:
            call = item.context_expr
            if isinstance(call, ast.Call) and self._call_name(call) == "open":
                mode = ""
                if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
                    mode = str(call.args[1].value)
                for keyword in call.keywords:
                    if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                        mode = str(keyword.value.value)
                if "w" in mode or "a" in mode:
                    target = ""
                    if call.args and isinstance(call.args[0], ast.Constant):
                        target = str(call.args[0].value)
                    if _looks_like_config(target) or _looks_like_config(
                            self.code_at(call)):
                        self.add(
                            SILENT, "state", call,
                            "Config file written in place, not atomically",
                            "open(mode='w') truncates immediately. If the "
                            "process dies, the disk fills, or two processes "
                            "write at once, the file is left truncated or "
                            "interleaved - and this is a file something else "
                            "depends on. Write to a temp file and os.replace().",
                            benign_if="the file is disposable")
        self.generic_visit(node)


def _is_true(node):
    return isinstance(node, ast.Constant) and node.value is True


def _looks_like_config(text):
    return bool(re.search(r"settings|config|\.json|credential|profile|state",
                          text, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Shell analysis - regex, because shell has no usable AST here.
# ---------------------------------------------------------------------------

SHELL_RULES = [
    (SILENT, "security",
     re.compile(r'rm\s+-rf?\s+"?\$\{?[A-Za-z_][A-Za-z0-9_]*'),
     "rm -rf on an unguarded variable",
     "If the variable is empty this becomes 'rm -rf /' or 'rm -rf ' with the "
     "next argument. An unset variable under 'set -u' errors, but an EMPTY one "
     "does not.",
     "the variable is checked non-empty immediately above"),
    (SILENT, "error handling",
     re.compile(r'^\s*(?!#)[^|&\n]*\|\s*(bash|sh)\b'),
     "Piping a downloaded script into a shell",
     "Executes whatever the server returns, unreviewed, with your privileges. "
     "A compromised or redirected host owns the machine.",
     ""),
    (FRAGILE, "error handling",
     re.compile(r'^\s*cd\s+[^\s;&|]+\s*$'),
     "cd without checking it succeeded",
     "If the directory is missing, cd fails and the script continues in the "
     "previous directory - so subsequent relative paths act on the wrong tree.",
     "the script uses 'set -e'"),
]


def analyse_shell(path, source):
    findings = []
    has_set_e = bool(re.search(r"^\s*set\s+-[a-z]*e", source, re.MULTILINE))
    for number, line in enumerate(source.splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        for severity, chamber, pattern, title, mechanism, benign in SHELL_RULES:
            if pattern.search(line):
                if "cd without" in title and has_set_e:
                    continue
                findings.append(Finding(severity, chamber, path, number, title,
                                        mechanism, line.strip()[:120], benign))
    return findings


# ---------------------------------------------------------------------------
# Target selection
# ---------------------------------------------------------------------------

def git_files(since=None):
    try:
        if since:
            cmd = ["git", "diff", "--name-only", f"{since}...HEAD"]
        else:
            cmd = ["git", "diff", "--name-only", "HEAD"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        files = [f for f in result.stdout.split("\n") if f.strip()]
        if not files and not since:
            result = subprocess.run(["git", "diff", "--name-only", "HEAD~1...HEAD"],
                                    capture_output=True, text=True, timeout=60)
            files = [f for f in result.stdout.split("\n") if f.strip()]
        return [f for f in files if os.path.isfile(f)]
    except (OSError, subprocess.SubprocessError):
        return []


def walk(root):
    skip = {".git", "__pycache__", "node_modules", "build", "dist", ".venv"}
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            if name.endswith((".py", ".sh", ".bash")):
                out.append(os.path.join(dirpath, name))
    return out


#: Source files larger than this are almost always generated or minified. Reading
#: one whole into memory (and then into an AST) can exhaust RAM, and the findings
#: would be noise anyway. Skip, but say so: a silently skipped file looks clean.
MAX_SOURCE_BYTES = 5 * 1024 * 1024


def analyse(path):
    try:
        size = os.path.getsize(path)
        if size > MAX_SOURCE_BYTES:
            return [Finding(FRAGILE, "coverage", path, 0,
                            "File not analysed: too large",
                            f"{size / 1024 / 1024:.1f} MB exceeds the "
                            f"{MAX_SOURCE_BYTES // 1024 // 1024} MB limit, so it was "
                            f"skipped rather than read into memory. Absence of "
                            f"findings for this file means nothing.")]
        with open(path, encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError:
        return []

    if path.endswith(".py"):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            return [Finding(LOUD, "correctness", path, exc.lineno or 0,
                            "File does not parse",
                            f"Python cannot parse this file: {exc.msg}. "
                            f"Anything importing it fails at import time.")]
        visitor = PythonVisitor(path, source)
        visitor.visit(tree)
        return visitor.findings

    if path.endswith((".sh", ".bash")):
        return analyse_shell(path, source)
    return []


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

CHAMBER_ORDER = ["security", "state", "error handling", "resource", "correctness"]

HEADERS = {
    "security": "SECURITY - input reaching something that executes",
    "state": "STATE - data that is shared, lost, or corrupted",
    "error handling": "ERROR HANDLING - failures that leave no trace",
    "resource": "RESOURCE - unbounded waits and growth",
    "correctness": "CORRECTNESS",
}


def render(findings, scanned):
    out = []
    add = out.append
    add("=" * 74)
    add("  Dream - counterfactual risk analysis")
    add("=" * 74)
    add(f"  {scanned} file(s) analysed, {len(findings)} finding(s)")
    add("")

    if not findings:
        add("  Nothing found. The detectors here are deliberately quiet: each")
        add("  one has a concrete failure mode, so an empty report means the")
        add("  patterns it knows about are absent - not that the code is safe.")
        add("=" * 74)
        return "\n".join(out)

    by_chamber = {}
    for finding in findings:
        by_chamber.setdefault(finding.chamber, []).append(finding)

    for chamber in CHAMBER_ORDER:
        items = by_chamber.get(chamber)
        if not items:
            continue
        items.sort(key=lambda f: (RANK[f.severity], f.path, f.line))
        add("-" * 74)
        add(f"  {HEADERS.get(chamber, chamber.upper())}")
        add("-" * 74)
        for finding in items:
            add(f"  [{finding.severity}] {finding.title}")
            add(f"      {finding.path}:{finding.line}")
            if finding.code:
                add(f"      | {finding.code}")
            for chunk in _wrap(finding.mechanism, 66):
                add(f"      {chunk}")
            if finding.benign_if:
                add(f"      Benign if: {finding.benign_if}")
            add("")

    counts = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    add("=" * 74)
    add("  " + "   ".join(f"{sev}: {counts.get(sev, 0)}"
                          for sev in (SILENT, LOUD, FRAGILE)))
    add("  SILENT ranks highest: a crash gets noticed, a wrong answer does not.")
    add("=" * 74)
    return "\n".join(out)


def _wrap(text, width):
    words, line, lines = text.split(), "", []
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


def main():
    parser = argparse.ArgumentParser(description="Counterfactual risk analysis")
    parser.add_argument("--path", help="analyse a directory")
    parser.add_argument("--since", help="analyse a commit range, e.g. HEAD~5")
    parser.add_argument("--all", action="store_true", help="analyse the whole tree")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("topic", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.path:
        targets = walk(args.path)
    elif args.all:
        targets = walk(".")
    else:
        targets = git_files(args.since)
        if not targets:
            targets = walk(".")

    findings = []
    for path in targets:
        findings.extend(analyse(path))

    if args.json:
        print(json.dumps({
            "scanned": len(targets),
            "findings": [f.as_dict() for f in findings],
        }, indent=2))
    else:
        print(render(findings, len(targets)))

    return 1 if any(f.severity == SILENT for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
