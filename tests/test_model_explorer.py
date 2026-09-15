#!/usr/bin/env python3
"""
Test Suite: Model Explorer & Benchmarks Engine
Validates:
1. Catalog structure & specifications across providers (OAuth, OpenRouter, Gemini)
2. Pricing breakdowns & token cost calculations
3. FREE vs PAID tier filtering
4. Live search query matching (ID, name, best_for)
5. Cross-provider fallback search
6. Latency benchmarks (< 15ms target)
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
models_mod = importlib.import_module("claude-models")

class TestModelExplorer(unittest.TestCase):

    def test_catalog_integrity(self):
        """All models in CURATED_MODELS must possess complete specifications and pricing."""
        catalog = models_mod.CURATED_MODELS
        self.assertIn("openrouter", catalog)
        self.assertIn("oauth", catalog)
        self.assertIn("gemini", catalog)

        required_keys = ["id", "name", "tier", "context", "pricing", "benchmarks", "best_for"]
        pricing_keys = ["input", "output", "cache_read", "est_session"]

        total_models = 0
        for prov, mlist in catalog.items():
            self.assertGreater(len(mlist), 0, f"Provider '{prov}' has no models configured")
            for m in mlist:
                total_models += 1
                for k in required_keys:
                    self.assertIn(k, m, f"Model {m.get('id', 'unknown')} missing required key '{k}'")
                for pk in pricing_keys:
                    self.assertIn(pk, m["pricing"], f"Model {m['id']} missing pricing key '{pk}'")

        self.assertGreaterEqual(total_models, 15, "Catalog should have at least 15 curated models")

    def test_free_tier_filtering(self):
        """Filtering by FREE must return only models where tier contains 'FREE'."""
        openrouter_models = models_mod.CURATED_MODELS["openrouter"]
        free_models = [m for m in openrouter_models if "FREE" in m.get("tier", "").upper()]

        self.assertGreater(len(free_models), 0, "OpenRouter must have free models configured")
        for m in free_models:
            self.assertIn("FREE", m["tier"].upper())
            self.assertIn("$0.00", m["pricing"]["input"])
            self.assertIn("$0.00", m["pricing"]["output"])

    def test_search_query_filtering(self):
        """Search query must match against model id, name, and use-case tags."""
        openrouter_models = models_mod.CURATED_MODELS["openrouter"]

        # Search by id substring
        r_deepseek = [m for m in openrouter_models if "deepseek" in m["id"].lower()]
        self.assertGreaterEqual(len(r_deepseek), 1)

        # Search by name substring
        r_llama = [m for m in openrouter_models if "llama" in m["name"].lower()]
        self.assertGreaterEqual(len(r_llama), 1)

        # Search by capability / best_for
        r_math = [m for m in openrouter_models if "algorithm" in m.get("best_for", "").lower() or "math" in m.get("best_for", "").lower()]
        self.assertGreaterEqual(len(r_math), 1)

    def test_cross_provider_search(self):
        """Searching for an external model while active provider is OAuth must find matches."""
        # Querying for llama should find matches in OpenRouter
        query = "llama"
        matches = []
        for prov_name, mlist in models_mod.CURATED_MODELS.items():
            for m in mlist:
                if query in m["id"].lower() or query in m.get("name", "").lower():
                    m_copy = dict(m)
                    m_copy["_provider"] = prov_name
                    matches.append(m_copy)

        self.assertGreater(len(matches), 0, "Cross-provider search should locate Llama models")
        self.assertEqual(matches[0]["_provider"], "openrouter")

    def test_catalog_query_latency_benchmark(self):
        """Querying and filtering across all models must complete in under 5ms."""
        t0 = time.perf_counter()
        catalog = models_mod.CURATED_MODELS
        for _ in range(50):
            filtered = []
            for p, mlist in catalog.items():
                for m in mlist:
                    if "code" in m.get("best_for", "").lower() or "FREE" in m.get("tier", ""):
                        filtered.append(m)
        total_time_ms = (time.perf_counter() - t0) * 1000.0

        avg_latency_ms = total_time_ms / 50.0
        self.assertLess(avg_latency_ms, 5.0, f"Average model filter latency too high: {avg_latency_ms:.2f}ms")

if __name__ == "__main__":
    unittest.main()
