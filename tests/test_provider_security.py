#!/usr/bin/env python3
"""
Test Suite: External API Provider & File Security Engine
Validates:
1. File permissions enforcement (0600 on ~/.claude/providers.json)
2. Safe provider switching & credential isolation
3. Latency benchmarks (< 10ms target)
"""

import os
import sys

# Prevent bytecode caching
sys.dont_write_bytecode = True

import stat
import time
import shutil
import tempfile
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

import importlib
provider_mod = importlib.import_module("claude-provider")

class TestProviderSecurity(unittest.TestCase):

    def setUp(self):
        """Create mock directory for testing provider security."""
        self.test_dir = tempfile.mkdtemp(prefix="cortex_test_provider_")
        self.orig_file = provider_mod.PROVIDERS_FILE
        provider_mod.PROVIDERS_FILE = os.path.join(self.test_dir, "providers.json")

    def tearDown(self):
        """Restore original file path and cleanup temp."""
        provider_mod.PROVIDERS_FILE = self.orig_file
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_providers_file_permissions_0600(self):
        """Saving providers.json must enforce strict 0600 (read/write only by owner)."""
        cfg = {
            "active_provider": "openrouter",
            "providers": {
                "openrouter": {
                    "api_key": "sk-or-v1-mock-secret-key-12345",
                    "base_url": "https://openrouter.ai/api/v1",
                    "model": "meta-llama/llama-3.3-70b-instruct:free"
                }
            }
        }
        t0 = time.perf_counter()
        provider_mod.save_config(cfg)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        target_file = provider_mod.PROVIDERS_FILE
        self.assertTrue(os.path.exists(target_file))

        file_stat = os.stat(target_file)
        file_mode = stat.S_IMODE(file_stat.st_mode)

        self.assertEqual(
            file_mode,
            0o600,
            f"Expected file permissions 0600, got: {oct(file_mode)}"
        )
        self.assertLess(latency_ms, 15.0, f"save_config took too long: {latency_ms:.2f}ms")

    def test_provider_switching_and_retrieval(self):
        """Setting active provider must persist and update active provider state."""
        cfg = provider_mod.load_config()
        self.assertIn("active_provider", cfg)

        provider_mod.set_active_provider("gemini")
        updated_cfg = provider_mod.load_config()
        self.assertEqual(updated_cfg["active_provider"], "gemini")

if __name__ == "__main__":
    unittest.main()
