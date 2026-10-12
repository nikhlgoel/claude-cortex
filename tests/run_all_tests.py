#!/usr/bin/env python3
"""
Claude Cortex - master test runner.

Runs every unit/integration suite and reports exactly what happened: how many
tests ran, which failed and why, and how long it took. Nothing in the report is
asserted in advance. An earlier version printed fixed latency and token-savings
figures with a PASS next to each regardless of the outcome - including a
"0600 permissions" PASS on a run where that very test had failed. A report that
cannot say FAIL is not evidence of anything, so every number here is measured.
"""

import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone

# Prevent bytecode caching to keep repository 100% clean and sanitized
sys.dont_write_bytecode = True

# Windows consoles default to a legacy code page; printing a non-ASCII character
# there raises UnicodeEncodeError and the whole run dies before reporting.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(TESTS_DIR)

# These tests touch real paths under ~/.claude, so refuse to run outside a
# sandbox. See tests/_guard.py.
sys.path.insert(0, TESTS_DIR)
from _guard import require_sandbox  # noqa: E402

require_sandbox()

REPORT_JSON = os.path.join(TESTS_DIR, "METRICS_REPORT.json")
REPORT_MD = os.path.join(TESTS_DIR, "METRICS_REPORT.md")

TEST_MODULES = [
    "test_core_fixes",
    "test_audit_batch2",
    "test_local",
    "test_profiles_adopt",
    "test_routing",
    "test_installer_surfaces",
    "test_token_conservation",
    "test_memory_palace",
    "test_capacity_engine",
    "test_model_explorer",
    "test_update_manager",
    "test_provider_security",
    "test_extension_integration",
]


def _first_line(text):
    lines = [line for line in str(text).strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def run_suite():
    os.environ["CLAUDE_CORTEX_TEST_MODE"] = "1"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print("=" * 70)
    print("  CLAUDE CORTEX - TEST RUN")
    print("=" * 70)
    print(f"Timestamp: {stamp}")
    print(f"Directory: {PROJECT_DIR}\n")

    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    load_errors = []
    for mod_name in TEST_MODULES:
        try:
            suite.addTests(loader.loadTestsFromModule(__import__(mod_name)))
        except Exception as exc:  # a module that cannot load is a failure, not a skip
            load_errors.append((mod_name, f"{type(exc).__name__}: {exc}"))
            print(f"ERROR loading {mod_name}: {exc}")

    start = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    duration_ms = (time.perf_counter() - start) * 1000.0

    failed = [(str(t), _first_line(tb)) for t, tb in result.failures]
    errored = [(str(t), _first_line(tb)) for t, tb in result.errors]
    passed = result.testsRun - len(failed) - len(errored) - len(result.skipped)
    ok = result.wasSuccessful() and not load_errors

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": ok,
        "summary": {
            "tests_run": result.testsRun,
            "passed": passed,
            "failures": len(failed),
            "errors": len(errored),
            "skipped": len(result.skipped),
            "modules_that_failed_to_load": len(load_errors),
            "duration_ms": round(duration_ms, 2),
        },
        "failures": [{"test": t, "reason": r} for t, r in failed],
        "errors": [{"test": t, "reason": r} for t, r in errored],
        "skipped": [{"test": str(t), "reason": r} for t, r in result.skipped],
        "load_errors": [{"module": m, "reason": r} for m, r in load_errors],
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    md = [
        "# Claude Cortex - test report",
        f"**Generated:** {stamp}  ",
        f"**Result:** {'PASS' if ok else 'FAIL'}  ",
        f"**Tests:** {result.testsRun} run, {passed} passed, {len(failed)} failed, "
        f"{len(errored)} errors, {len(result.skipped)} skipped  ",
        f"**Duration:** {duration_ms:.0f} ms",
        "",
    ]
    for title, rows in (("Failures", failed), ("Errors", errored),
                        ("Skipped", [(str(t), r) for t, r in result.skipped]),
                        ("Modules that failed to load", load_errors)):
        if rows:
            md += [f"## {title}", ""] + [f"- `{name}` - {why}" for name, why in rows] + [""]
    with open(REPORT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    print("\n" + "=" * 70)
    print(f"  {'PASS' if ok else 'FAIL'}: {result.testsRun} run, {passed} passed, "
          f"{len(failed)} failed, {len(errored)} errors, {len(result.skipped)} skipped "
          f"({duration_ms:.0f} ms)")
    print("=" * 70)
    for name, why in failed + errored:
        print(f"  - {name}\n      {why}")
    print(f"\n  Reports: {REPORT_JSON}\n           {REPORT_MD}")

    # Clean up any transient __pycache__ to maintain 100% distribution sanitization
    import shutil
    for root, dirs, _ in os.walk(PROJECT_DIR):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run_suite())
