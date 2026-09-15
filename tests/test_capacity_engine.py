#!/usr/bin/env python3
"""
Test Suite: Multi-Account Capacity & Rate-Limit Engine
Validates:
1. Utilization parsing for 5-hour and 7-day rolling windows
2. Reset countdown calculation & ISO/epoch parsing
3. Account ranking & scoring formula (available < blocked < unauthenticated)
4. Automatic failover selection of healthiest account
5. Visual progress bar rendering & ANSI color thresholds
6. Execution speed / latency benchmarks (< 15ms target)
"""

import os
import sys

# Prevent bytecode caching
sys.dont_write_bytecode = True

import time
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

import importlib
capacity_mod = importlib.import_module("claude-capacity-check")

class TestCapacityEngine(unittest.TestCase):

    def setUp(self):
        """Create mock profiles directory for testing."""
        self.test_dir = tempfile.mkdtemp(prefix="cortex_test_capacity_")
        self.orig_profiles_dir = capacity_mod.PROFILES_DIR
        capacity_mod.PROFILES_DIR = self.test_dir

    def tearDown(self):
        """Restore original profiles directory and cleanup temp."""
        capacity_mod.PROFILES_DIR = self.orig_profiles_dir
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def create_mock_profile(self, name, email, sub_type="pro", five_hour_util=0, seven_day_util=0, blocked=False, reset_in_seconds=3600):
        """Creates a mock profile directory with credentials and cached usage data."""
        p_dir = os.path.join(self.test_dir, name)
        os.makedirs(p_dir, exist_ok=True)

        # .credentials.json
        creds = {
            "claudeAiOauth": {
                "accessToken": "mock_token_" + name,
                "subscriptionType": sub_type,
                "rateLimitTier": "default"
            }
        }
        with open(os.path.join(p_dir, ".credentials.json"), "w") as f:
            json.dump(creds, f)

        # .claude.json
        now = datetime.now(timezone.utc)
        reset_time_iso = (now + timedelta(seconds=reset_in_seconds)).isoformat()

        claude_data = {
            "oauthAccount": {"emailAddress": email},
            "cachedUsageUtilization": {
                "utilization": {
                    "five_hour": {
                        "utilization": five_hour_util,
                        "resets_at": reset_time_iso if five_hour_util >= 100 else None
                    },
                    "seven_day": {
                        "utilization": seven_day_util,
                        "resets_at": reset_time_iso if seven_day_util >= 100 else None
                    },
                    "limits": [
                        {
                            "kind": "weekly_all" if blocked else "session",
                            "percent": 100 if blocked else 0,
                            "severity": "critical" if blocked else "normal",
                            "resets_at": reset_time_iso if blocked else None,
                            "is_active": blocked
                        }
                    ]
                }
            }
        }
        with open(os.path.join(p_dir, ".claude.json"), "w") as f:
            json.dump(claude_data, f)

    def test_healthy_account_detection(self):
        """Healthy account with 0% utilization must be reported available with score 0."""
        self.create_mock_profile("alpha", "alpha@example.com", five_hour_util=0, seven_day_util=0)
        t0 = time.perf_counter()
        info = capacity_mod.check_profile("alpha")
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertTrue(info["available"])
        self.assertEqual(info["score"], 0)
        self.assertEqual(info["five_hour_util"], 0)
        self.assertEqual(info["seven_day_util"], 0)
        self.assertLess(latency_ms, 15.0, f"check_profile took too long: {latency_ms:.2f}ms")

    def test_rate_limited_account_detection(self):
        """Account with 100% utilization must be marked unavailable with countdown calculated."""
        self.create_mock_profile("beta", "beta@example.com", five_hour_util=0, seven_day_util=100, blocked=True, reset_in_seconds=7200)
        info = capacity_mod.check_profile("beta")

        self.assertFalse(info["available"])
        self.assertEqual(info["seven_day_util"], 100)
        self.assertGreater(info["score"], 100000, "Blocked account score must be >= 100000")
        self.assertIsNotNone(info["reset_seconds"])
        self.assertIn("resets in", info["status_detail"])

    def test_best_account_selection_logic(self):
        """Engine must automatically rank available account above rate-limited account."""
        # Profile 1: Blocked
        self.create_mock_profile("p1_blocked", "p1@example.com", seven_day_util=100, blocked=True, reset_in_seconds=3600)
        # Profile 2: 30% utilized
        self.create_mock_profile("p2_busy", "p2@example.com", five_hour_util=30, seven_day_util=30)
        # Profile 3: 0% utilized (optimal)
        self.create_mock_profile("p3_free", "p3@example.com", five_hour_util=0, seven_day_util=0)

        profs = ["p1_blocked", "p2_busy", "p3_free"]
        results = [capacity_mod.check_profile(p) for p in profs]
        sorted_res = sorted(results, key=lambda x: x["score"])

        self.assertEqual(sorted_res[0]["name"], "p3_free", "P3 with 0% utilization must rank 1st")
        self.assertEqual(sorted_res[1]["name"], "p2_busy", "P2 with 30% utilization must rank 2nd")
        self.assertEqual(sorted_res[2]["name"], "p1_blocked", "P1 (blocked) must rank last")

    def test_render_bar_visual_formatting(self):
        """render_bar must render exact block characters and color thresholds."""
        # 0% utilization -> Green
        bar_0 = capacity_mod.render_bar(0, width=10, use_color=True)
        self.assertIn("░░░░░░░░░░", bar_0)
        self.assertIn("\033[1;32m", bar_0)  # Green

        # 60% utilization -> Yellow
        bar_60 = capacity_mod.render_bar(60, width=10, use_color=True)
        self.assertIn("██████░░░░", bar_60)
        self.assertIn("\033[1;33m", bar_60)  # Yellow

        # 100% utilization -> Red
        bar_100 = capacity_mod.render_bar(100, width=10, use_color=True)
        self.assertIn("██████████", bar_100)
        self.assertIn("\033[1;31m", bar_100)  # Red

        # Colorless fallback
        bar_no_color = capacity_mod.render_bar(50, width=10, use_color=False)
        self.assertEqual(bar_no_color, "[█████░░░░░]  50%")

    def test_capacity_check_speed_benchmark(self):
        """Multi-account check across 5 simulated accounts must execute in < 25ms."""
        for i in range(5):
            self.create_mock_profile(f"user_{i}", f"user_{i}@test.com", five_hour_util=i*10)

        t0 = time.perf_counter()
        results = [capacity_mod.check_profile(f"user_{i}") for i in range(5)]
        total_time_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(len(results), 5)
        self.assertLess(total_time_ms, 25.0, f"Total multi-account check took too long: {total_time_ms:.2f}ms")

if __name__ == "__main__":
    unittest.main()
