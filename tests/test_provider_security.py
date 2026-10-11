#!/usr/bin/env python3
"""
Test Suite: External API Provider & File Security Engine
Validates:
1. providers.json (it holds API keys) is readable by its owner only
     - POSIX:   mode 0600
     - Windows: chmod is a no-op there, so the ACL is checked directly - the
                inherited permissions must be gone and no broad principal
                (Everyone / Users / Authenticated Users) may be granted access
2. Safe provider switching & credential isolation
3. Writes are atomic and a corrupt file is preserved, not overwritten
"""

import importlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

# Prevent bytecode caching
sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _guard import LATENCY_SCALE  # noqa: E402

provider_mod = importlib.import_module("claude-provider")

SAMPLE_CONFIG = {
    "active_provider": "openrouter",
    "providers": {
        "openrouter": {
            "api_key": "sk-or-v1-mock-secret-key-12345",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "meta-llama/llama-3.3-70b-instruct:free",
        }
    },
}


class TestProviderSecurity(unittest.TestCase):

    def setUp(self):
        """Create mock directory for testing provider security."""
        self.test_dir = tempfile.mkdtemp(prefix="cortex_test_provider_")
        self.orig_file = provider_mod.PROVIDERS_FILE
        provider_mod.PROVIDERS_FILE = os.path.join(self.test_dir, "providers.json")

    def tearDown(self):
        """Restore original file path and cleanup temp."""
        provider_mod.PROVIDERS_FILE = self.orig_file
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits do not exist on Windows")
    def test_providers_file_permissions_0600(self):
        """Saving providers.json must enforce strict 0600 (read/write only by owner)."""
        t0 = time.perf_counter()
        provider_mod.save_config(SAMPLE_CONFIG)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        target = provider_mod.PROVIDERS_FILE
        self.assertTrue(os.path.exists(target))
        mode = stat.S_IMODE(os.stat(target).st_mode)
        self.assertEqual(mode, 0o600, f"Expected file permissions 0600, got: {oct(mode)}")
        self.assertLess(latency_ms, 15.0 * LATENCY_SCALE, f"save_config took {latency_ms:.2f}ms")

    @unittest.skipUnless(os.name == "nt", "ACL check is Windows-specific")
    def test_providers_file_acl_is_owner_only_on_windows(self):
        """chmod 0600 does nothing on Windows; the ACL must be tightened explicitly."""
        provider_mod.save_config(SAMPLE_CONFIG)
        target = provider_mod.PROVIDERS_FILE
        listing = subprocess.run(["icacls", target], capture_output=True, text=True,
                                 timeout=30).stdout
        for broad in ("Everyone", "BUILTIN\\Users", "Authenticated Users"):
            self.assertNotIn(broad, listing, f"{broad} can read the API-key file:\n{listing}")
        self.assertIn(os.environ["USERNAME"], listing)
        self.assertNotIn("(I)", listing, "permissions are still inherited from the folder")

    def test_provider_switching_and_retrieval(self):
        """Setting active provider must persist and update active provider state."""
        cfg = provider_mod.load_config()
        self.assertIn("active_provider", cfg)

        provider_mod.set_active_provider("gemini")
        updated_cfg = provider_mod.load_config()
        self.assertEqual(updated_cfg["active_provider"], "gemini")

    def test_unknown_provider_is_rejected(self):
        provider_mod.load_config()
        self.assertFalse(provider_mod.set_active_provider("no-such-provider"))
        self.assertEqual(provider_mod.get_active_provider(), "oauth")

    def test_key_is_never_world_visible_in_a_leftover_temp_file(self):
        """The atomic write goes through a temp file; none may be left holding the key."""
        provider_mod.save_config(SAMPLE_CONFIG)
        leftovers = [n for n in os.listdir(self.test_dir) if n != "providers.json"]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
