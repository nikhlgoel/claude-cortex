#!/usr/bin/env python3
"""
Test Suite: capacity reporting through the standalone delegator.

scripts/claude-capacity-check.py used to be a second, independent implementation
that reported a profile with no recorded usage as "Ready (100% capacity free)" and
ranked it best, so failover could switch to an exhausted account. It now forwards
to the core (cortex/capacity.py). These tests pin the property that mattered:
**missing data is never reported - or chosen - as free capacity.**

Parsing of the usage shapes themselves is covered in test_core_fixes.py.
"""

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from cortex import jsonfile, profiles  # noqa: E402


def _load_delegator():
    path = os.path.join(PROJECT_DIR, "scripts", "claude-capacity-check.py")
    spec = importlib.util.spec_from_file_location("claude_capacity_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCapacityDelegator(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="cortex_test_capacity_")
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.home, "USERPROFILE": self.home,
            "CORTEX_PROFILES_DIR": os.path.join(self.home, "profiles"),
        })
        self.env.start()
        profiles._AUTH_CACHE.clear()
        # Every profile counts as signed in; auth itself is tested elsewhere.
        self.auth = mock.patch.object(profiles, "is_authenticated", return_value=True)
        self.auth.start()
        self.cli = _load_delegator()

    def tearDown(self):
        self.auth.stop()
        self.env.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def _profile(self, name, five_hour=None):
        target = profiles.ensure_structure(name, "isolated")
        cfg = {"oauthAccount": {"emailAddress": f"{name}@example.com"}}
        if five_hour is not None:
            reset = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            cfg["cachedUsageUtilization"] = {"utilization": {
                "five_hour": {"utilization": five_hour, "resets_at": reset}}}
        jsonfile.write(os.path.join(target, ".claude.json"), cfg)

    def _run(self, *argv):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["claude-capacity-check.py", *argv]), \
                redirect_stdout(out):
            code = self.cli.main()
        return code, out.getvalue()

    def test_no_usage_data_is_never_reported_as_free(self):
        """The original bug: no data -> 'Ready (100% capacity free)'."""
        self._profile("fresh")
        code, out = self._run("--json")
        record = json.loads(out)[0]
        self.assertEqual(record["state"], "unknown")
        self.assertNotIn("100%", record["detail"])

    def test_best_refuses_to_guess_when_nothing_is_known(self):
        self._profile("fresh")
        code, out = self._run("--best")
        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "")

    def test_best_picks_the_profile_with_evidence_of_capacity(self):
        self._profile("fresh")                 # unknown: must not win by default
        self._profile("busy", five_hour=70)
        self._profile("quiet", five_hour=5)
        code, out = self._run("--best")
        self.assertEqual((code, out.strip()), (0, "quiet"))

    def test_a_limited_profile_is_never_best(self):
        self._profile("capped", five_hour=100)
        code, _ = self._run("--best")
        self.assertEqual(code, 1)

    def test_table_explains_unknown_instead_of_hiding_it(self):
        self._profile("fresh")
        _, out = self._run()
        self.assertIn("unknown", out)
        self.assertIn("not auto-selected", out)

    def test_switch_validates_the_profile_name(self):
        self._profile("real")
        code, _ = self._run("--switch", "ghost")
        self.assertEqual(code, 1)
        code, out = self._run("--switch", "real")
        self.assertEqual(code, 0)
        self.assertEqual(profiles.active_profile(), "real")


if __name__ == "__main__":
    unittest.main()
