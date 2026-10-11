#!/usr/bin/env python3
"""
Test Suite: live model catalog (cortex/models.py).

The catalog used to be 22 hand-typed models with prices that were wrong the day
they were written. It now fetches OpenRouter's public API, caches it, and says
what it is showing. These tests use a faked HTTP layer - no network - and pin:

1. live fetch -> cache written -> fresh cache served without touching the network
2. stale cache + network failure -> stale cache returned, clearly labelled
3. no cache + no network -> an honest "offline" message, never invented data
4. FREE filtering, search, and ordering
5. Claude subscription models carry no per-token price
"""

import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from cortex import models  # noqa: E402

FAKE_CATALOG = {"data": [
    {"id": "acme/pricey-1", "name": "Pricey One", "context_length": 128000,
     "pricing": {"prompt": "0.000010", "completion": "0.000030"}},
    {"id": "meta/llama-free:free", "name": "Llama Free", "context_length": 65536,
     "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "acme/cheap-2", "name": "Cheap Two", "context_length": 32000,
     "pricing": {"prompt": "0.0000005", "completion": "0.0000015"}},
    {"id": "acme/broken-3", "name": "Broken Pricing", "context_length": 8000,
     "pricing": {"prompt": "n/a", "completion": None}},
]}


def fake_response(payload):
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


class TestModelCatalog(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="cortex_test_models_")
        self.env = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def _live(self):
        return mock.patch("urllib.request.urlopen",
                          side_effect=lambda *a, **k: fake_response(FAKE_CATALOG))

    @staticmethod
    def _offline():
        return mock.patch("urllib.request.urlopen", side_effect=OSError("network is down"))

    def test_live_fetch_writes_cache_then_cache_serves_without_network(self):
        with self._live():
            data, source = models.fetch()
        self.assertEqual((len(data), source), (4, "live"))
        self.assertTrue(os.path.exists(models._cache_path()))

        with self._offline() as net:
            data, source = models.fetch()
        self.assertEqual((len(data), source), (4, "cache"))
        net.assert_not_called()                 # fresh cache: no request at all

    def test_stale_cache_is_used_when_the_network_fails(self):
        with self._live():
            models.fetch()
        stale = time.time() - models.CACHE_TTL_SECONDS - 60
        with open(models._cache_path(), encoding="utf-8") as fh:
            blob = json.load(fh)
        blob["fetched_at"] = int(stale)
        with open(models._cache_path(), "w", encoding="utf-8") as fh:
            json.dump(blob, fh)

        with self._offline():
            data, source = models.fetch()
        self.assertEqual((len(data), source), (4, "cache"))

    def test_no_cache_and_no_network_says_so_instead_of_inventing_data(self):
        with self._offline():
            report, _ = models.render()
        self.assertIn("offline and no cached catalog", report)
        self.assertNotIn("acme/", report)

    def test_free_filter_returns_only_zero_priced_models(self):
        with self._live():
            report, _ = models.render(free_only=True)
        self.assertIn("meta/llama-free:free", report)
        self.assertNotIn("acme/pricey-1", report)
        self.assertNotIn("acme/cheap-2", report)

    def test_search_matches_id_and_name_case_insensitively(self):
        with self._live():
            by_id, _ = models.render(query="CHEAP")
            by_name, _ = models.render(query="llama free")
        self.assertIn("acme/cheap-2", by_id)
        self.assertNotIn("acme/pricey-1", by_id)
        self.assertIn("meta/llama-free:free", by_name)

    def test_free_models_sort_first_then_by_price(self):
        with self._live():
            report, _ = models.render()
        order = [report.index(m) for m in
                 ("meta/llama-free:free", "acme/cheap-2", "acme/pricey-1")]
        self.assertEqual(order, sorted(order))

    def test_prices_are_shown_per_million_tokens(self):
        with self._live():
            report, _ = models.render(query="pricey")
        self.assertIn("$10.00", report)         # 0.000010 per token -> $10 per 1M
        self.assertIn("$30.00", report)

    def test_unparseable_pricing_does_not_crash_the_listing(self):
        with self._live():
            report, _ = models.render(query="broken")
        self.assertIn("acme/broken-3", report)

    def test_claude_subscription_models_show_no_per_token_price(self):
        """On a subscription there is no per-token price; printing one would be invented."""
        ids = [m[0] for m in models.SUBSCRIPTION_MODELS]
        self.assertEqual(len(ids), len(set(ids)), "duplicate model ids")
        for model_id, name, note in models.SUBSCRIPTION_MODELS:
            self.assertTrue(model_id.startswith("claude-"), model_id)
            self.assertNotIn("$", note, f"{name} note quotes a price")

    def test_main_reports_refresh_failure_with_a_nonzero_exit(self):
        with self._offline():
            self.assertEqual(models.main(["refresh"]), 1)

    def test_catalog_lookup_is_fast_once_cached(self):
        with self._live():
            models.fetch()
        start = time.perf_counter()
        for _ in range(20):
            models.fetch()
        per_call_ms = (time.perf_counter() - start) * 1000.0 / 20
        self.assertLess(per_call_ms, 50.0, f"cached fetch too slow: {per_call_ms:.1f}ms")


if __name__ == "__main__":
    unittest.main()
