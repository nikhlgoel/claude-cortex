#!/usr/bin/env python3
"""
Objective Action Scorer (OAS)

A heuristic *risk indicator* for a change to one file, built only from things that
can be checked mechanically:

  complexity   cyclomatic complexity of the file now vs. at git HEAD (Python only)
  tests        whether any test file in the project references the module
  recovery     whether a committed copy exists to restore, and whether the change
               adds destructive patterns (rm -rf, DROP TABLE, force-push, ...)
  ripple       how many other source files mention the module
  size         lines added + deleted against HEAD

Higher is safer. It is not a proof of correctness and it does not replace running
the tests. Its one real property is that it never invents a number: a metric that
cannot be measured (not a git repo, not Python, unreadable) contributes 0 and is
listed under ``unmeasured`` instead of being guessed.

Usage:
    cortex-scorer.py --path src/foo.py [--root /repo]
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys

BASE_SCORE = 50
HALT_BELOW = 50
MAX_FILE_BYTES = 1_000_000          # never read a file larger than this
MAX_SCANNED_FILES = 5000            # bounds the ripple/test search on huge trees
GIT_TIMEOUT = 10

# Only used outside a git repository, where there is no .gitignore to ask.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
             ".mypy_cache", ".pytest_cache"}
CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".ps1", ".go", ".rs", ".java"}

DESTRUCTIVE = [
    (re.compile(r"\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\b"), "recursive delete (rm -rf)"),
    (re.compile(r"\bshutil\.rmtree\b|\bRemove-Item\b.*-Recurse"), "recursive delete (rmtree)"),
    (re.compile(r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b|\bTRUNCATE\s+TABLE\b", re.I),
     "schema/data drop"),
    (re.compile(r"\bgit\s+push\b.*--force|\bgit\s+reset\s+--hard\b"), "history rewrite"),
]
SENSITIVE_NAMES = ("install", "uninstall", "migrat", "settings.json", ".env")


# --------------------------------------------------------------------------- git

def _git(args, root):
    """Run git in ``root``; return stdout, or None when git/repo is unavailable."""
    try:
        res = subprocess.run(["git"] + args, cwd=root, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def _read(path):
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


# ------------------------------------------------------------------- complexity

_BRANCHES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
             ast.IfExp, ast.Assert, ast.comprehension)


def complexity(source):
    """McCabe-style complexity of Python source, or None if it does not parse."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    total = 1
    for node in ast.walk(tree):
        if isinstance(node, _BRANCHES):
            total += 1
        elif isinstance(node, ast.BoolOp):
            total += len(node.values) - 1
        elif hasattr(ast, "match_case") and isinstance(node, ast.match_case):
            total += 1
    return total


# ---------------------------------------------------------------------- metrics

def measure_complexity(abspath, rel, root):
    if not abspath.endswith(".py"):
        return None, "complexity is measured for Python files only"
    now = complexity(_read(abspath) or "")
    if now is None:
        return None, "file did not parse"
    old_src = _git(["show", f"HEAD:{rel}"], root)
    if old_src is None:
        return {"now": now, "before": None, "delta": now}, "new or untracked file"
    before = complexity(old_src)
    if before is None:
        return None, "committed version did not parse"
    return {"now": now, "before": before, "delta": now - before}, ""


def measure_size(rel, root):
    out = _git(["diff", "--numstat", "HEAD", "--", rel], root)
    if out is None:
        return None, "not a git repository"
    lines = 0
    for row in out.splitlines():
        parts = row.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            lines += int(parts[0]) + int(parts[1])
    return {"lines_changed": lines}, ""


def _iter_files(root):
    """Yield ``(path, name)`` for the project's source files.

    Inside a git repository this asks git, which already knows what is ignored
    (node_modules, build output, vendored trees) and includes new untracked
    files. Outside git it falls back to a directory walk with a skip list.
    """
    listed = _git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], root)
    if listed is not None:
        for rel in listed.split("\0"):
            if rel:
                yield os.path.join(root, rel), os.path.basename(rel)
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield os.path.join(dirpath, name), name


def _is_test(path, name):
    parts = {p.lower() for p in path.replace("\\", "/").split("/")}
    low = name.lower()
    return bool(parts & {"tests", "test", "__tests__"}) or low.startswith("test_") \
        or "_test." in low or ".test." in low or ".spec." in low


def _name_pattern(stem):
    """Match the module name however it is spelled: foo_bar, foo-bar, foo.bar."""
    variants = {stem, stem.replace("-", "_"), stem.replace("_", "-")}
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(v) for v in variants)
                      + r")(?![A-Za-z0-9])")


def measure_tests_and_ripple(abspath, root):
    stem = os.path.splitext(os.path.basename(abspath))[0]
    if len(stem) < 3:
        return None, None, "module name too short to search for reliably"
    pattern = _name_pattern(stem)
    tests, dependents, test_files_exist = [], 0, False
    scanned, truncated = 0, False
    for path, name in _iter_files(root):
        if os.path.splitext(name)[1] not in CODE_EXTS:
            continue
        scanned += 1
        if scanned > MAX_SCANNED_FILES:
            truncated = True        # say so in the result; never imply a full search
            break
        is_test = _is_test(path, name)
        test_files_exist = test_files_exist or is_test
        if os.path.abspath(path) == os.path.abspath(abspath):
            continue
        text = _read(path)
        if text is None or not pattern.search(text):
            continue
        if is_test:
            tests.append(os.path.relpath(path, root))
        else:
            dependents += 1
    return ({"referenced_by": tests[:5], "count": len(tests),
             "project_has_tests": test_files_exist, "search_truncated": truncated},
            {"dependent_files": dependents, "search_truncated": truncated}, "")


def measure_recovery(abspath, rel, root):
    tracked = _git(["ls-files", "--error-unmatch", "--", rel], root) is not None
    in_git = _git(["rev-parse", "--is-inside-work-tree"], root) is not None
    text = _read(abspath) or ""
    flags = [label for rx, label in DESTRUCTIVE if rx.search(text)]
    sensitive = any(s in rel.lower() for s in SENSITIVE_NAMES)
    return {"git_repo": in_git, "committed": tracked,
            "destructive_patterns": flags, "sensitive_path": sensitive}, ""


# ----------------------------------------------------------------------- policy

def combine(metrics):
    """Turn measured metrics into a 0-100 score. Higher is safer.

    Returns ``(score, breakdown)`` where breakdown maps each metric name to the
    points it added or removed. Metrics that were not measured are absent from
    ``metrics`` and therefore contribute nothing.

    TODO(human): this is the policy. The defaults below are a starting point -
    decide how much each signal should cost or earn. For example: is a missing
    test worth -20, or should it dominate? Should a destructive pattern ever be
    allowed to be outweighed by good test coverage?
    """
    parts = {}

    cx = metrics.get("complexity")
    if cx:
        parts["complexity"] = -max(-20, min(20, cx["delta"]))

    tests = metrics.get("tests")
    if tests:
        parts["tests"] = 20 if tests["count"] else -20

    rec = metrics.get("recovery")
    if rec:
        pts = 0
        if rec["git_repo"] and not rec["committed"]:
            pts -= 10                       # nothing committed to restore
        pts -= 15 * min(2, len(rec["destructive_patterns"]))
        if rec["sensitive_path"]:
            pts -= 10
        parts["recovery"] = pts

    ripple = metrics.get("ripple")
    if ripple:
        parts["ripple"] = -min(20, ripple["dependent_files"])

    size = metrics.get("size")
    if size:
        parts["size"] = -min(15, size["lines_changed"] // 20)

    score = max(0, min(100, BASE_SCORE + sum(parts.values())))
    return score, parts


# ------------------------------------------------------------------------- main

def evaluate_impact(path, root=None):
    root = os.path.abspath(root or os.getcwd())
    abspath = path if os.path.isabs(path) else os.path.join(root, path)
    abspath = os.path.abspath(abspath)
    if not os.path.isfile(abspath):
        return {"error": f"{path} is not a file"}

    try:
        rel = os.path.relpath(abspath, root).replace("\\", "/")
    except ValueError:                      # different drive on Windows
        rel = os.path.basename(abspath)
    if rel.startswith(".."):
        return {"error": f"{path} is outside the project root {root}"}

    metrics, unmeasured = {}, {}

    def record(name, value, why):
        if value is None:
            unmeasured[name] = why
        else:
            metrics[name] = value

    value, why = measure_complexity(abspath, rel, root)
    record("complexity", value, why)
    value, why = measure_size(rel, root)
    record("size", value, why)
    tests, ripple, why = measure_tests_and_ripple(abspath, root)
    record("tests", tests, why)
    record("ripple", ripple, why)
    value, why = measure_recovery(abspath, rel, root)
    record("recovery", value, why)

    score, breakdown = combine(metrics)
    return {
        "path": rel,
        "score": score,
        "recommendation": "PROCEED" if score >= HALT_BELOW else "HALT_AND_PROMPT_HUMAN",
        "points": breakdown,
        "metrics": metrics,
        "unmeasured": unmeasured,
        "note": "Heuristic risk indicator, not proof of correctness. Run the tests.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Objective Action Scorer")
    parser.add_argument("--path", required=True, help="file that was or will be changed")
    parser.add_argument("--root", default=None, help="project root (default: cwd)")
    args = parser.parse_args(argv)

    result = evaluate_impact(args.path, args.root)
    print(json.dumps(result, indent=2))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
