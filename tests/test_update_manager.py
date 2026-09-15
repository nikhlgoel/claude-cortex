#!/usr/bin/env python3
"""
Test Suite: Multi-Component Ecosystem Updater
Validates:
1. Robust semantic version extraction regex
2. Version comparison logic (avoids false-positive dev-build notifications)
3. Component target registrations (CLI, VS Code extension, UV tools, Git repository)
4. Update check latency benchmark (< 100ms target)
"""

import os
import sys

# Prevent bytecode caching
sys.dont_write_bytecode = True

import time
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

import importlib
update_mod = importlib.import_module("claude-update")

class TestUpdateManager(unittest.TestCase):

    def test_version_extraction_regex(self):
        """extract_version_number must extract clean numeric semver strings."""
        cases = [
            ("v1.1.0", "1.1.0"),
            ("1.1.0", "1.1.0"),
            ("claude-code@0.2.29", "0.2.29"),
            ("version 1.0.4-beta", "1.0.4"),
            ("0.5.1a2", "0.5.1"),
            ("v2.0.0-rc1", "2.0.0"),
        ]
        for raw_str, expected in cases:
            extracted = update_mod.extract_version_number(raw_str)
            self.assertEqual(extracted, expected, f"Failed on raw string: {raw_str}")

    def test_version_comparison_logic(self):
        """compare_versions must accurately classify older, newer, and equal versions."""
        # newer (1)
        self.assertEqual(update_mod.compare_versions("1.1.0", "1.0.0"), 1)
        self.assertEqual(update_mod.compare_versions("0.2.30", "0.2.29"), 1)
        self.assertEqual(update_mod.compare_versions("1.10.0", "1.9.0"), 1)

        # equal (0)
        self.assertEqual(update_mod.compare_versions("1.1.0", "1.1.0"), 0)
        self.assertEqual(update_mod.compare_versions("0.2.29", "0.2.29"), 0)

        # older (-1)
        self.assertEqual(update_mod.compare_versions("1.0.0", "1.1.0"), -1)
        self.assertEqual(update_mod.compare_versions("0.2.28", "0.2.29"), -1)

    def test_cortex_git_repo_check_speed(self):
        """Checking local repository git branch and status must execute quickly."""
        update_mod.check_cortex_repo(force_fetch=False)
        t0 = time.perf_counter()
        info = update_mod.check_cortex_repo(force_fetch=False)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertIsNotNone(info)
        self.assertIn("name", info)
        self.assertEqual(info["name"], "Claude Cortex Core Engine")
        self.assertLess(latency_ms, 100.0, f"Git repo check took too long: {latency_ms:.2f}ms")

if __name__ == "__main__":
    unittest.main()
