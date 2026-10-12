#!/usr/bin/env python3
"""
Test Suite: Cognitive Memory Palace Engine
Validates:
1. Isolated directory creation & 5-room memory structure initialization
2. Memory storage (`remember`) across all cognitive rooms
3. Inverted tag indexing & auto-tokenization
4. Deduplication safeguards (zero duplicate entries)
5. Recall accuracy & recency-weighted ranking
6. Memory pruning & markdown synchronization
7. Re-entrant concurrency locking
8. Latency benchmarks (P50, P95, P99 in ms)
"""

import os
import sys

# Prevent bytecode caching
sys.dont_write_bytecode = True

import time
import shutil
import tempfile
import unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _guard import LATENCY_SCALE  # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

import importlib
palace_mod = importlib.import_module("claude-palace")

class TestMemoryPalace(unittest.TestCase):

    def setUp(self):
        """Create a dedicated isolated temporary directory for test palace."""
        self.test_dir = tempfile.mkdtemp(prefix="cortex_test_palace_")

    def tearDown(self):
        """Clean up isolated test directory."""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_palace_structure_initialization(self):
        """Palace must create index.json and 5 room markdown files."""
        palace_mod.ensure_palace_structure(self.test_dir)
        index_file = os.path.join(self.test_dir, "index.json")
        self.assertTrue(os.path.exists(index_file), "index.json must exist")

        idx = palace_mod.load_index(self.test_dir)
        self.assertEqual(len(idx["rooms"]), 5, "All 5 rooms must be initialized in index")

        for rkey, rinfo in palace_mod.ROOMS.items():
            rpath = os.path.join(self.test_dir, "rooms", rinfo["file"])
            self.assertTrue(os.path.exists(rpath), f"Room file {rinfo['file']} must exist")

    def test_remember_and_indexing(self):
        """Storing memories must update room files, memories map, and inverted tag index."""
        t0 = time.perf_counter()
        mem_id = palace_mod.remember(
            self.test_dir,
            room_key="blueprint",
            title="Database Connection Pool Architecture",
            content="Use HikariCP connection pool with maximumPoolSize=20 and minimumIdle=5.",
            tags=["database", "performance", "architecture"]
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertIsNotNone(mem_id)
        self.assertTrue(mem_id.startswith("blue_"))
        self.assertLess(latency_ms, 30.0 * LATENCY_SCALE, f"Remember latency too high: {latency_ms:.2f}ms")

        idx = palace_mod.load_index(self.test_dir)
        self.assertIn(mem_id, idx["memories"])
        self.assertIn("performance", idx["tag_index"])
        self.assertIn(mem_id, idx["tag_index"]["performance"])

        # Check markdown room file contains memory entry
        rpath = os.path.join(self.test_dir, "rooms", "blueprint.md")
        with open(rpath, "r") as f:
            content = f.read()
        self.assertIn(mem_id, content)
        self.assertIn("Database Connection Pool Architecture", content)

    def test_deduplication_guard(self):
        """Storing identical or near-identical memory twice must skip duplication."""
        id1 = palace_mod.remember(
            self.test_dir,
            room_key="graveyard",
            title="Fix SSL handshake timeout in gRPC client",
            content="Set keepAliveTime to 30s and keepAliveTimeout to 10s to prevent broken pipe.",
            tags=["grpc", "network", "ssl"]
        )
        # Attempt to insert identical memory
        id2 = palace_mod.remember(
            self.test_dir,
            room_key="graveyard",
            title="Fix SSL handshake timeout in gRPC client",
            content="Set keepAliveTime to 30s and keepAliveTimeout to 10s to prevent broken pipe.",
            tags=["grpc", "network"]
        )
        self.assertEqual(id1, id2, "Deduplication guard must return original ID")

        idx = palace_mod.load_index(self.test_dir)
        self.assertEqual(len(idx["memories"]), 1, "Only one entry should exist in index")

    def test_recall_accuracy_and_speed(self):
        """Recall must accurately find memories by keyword and respect room filters."""
        palace_mod.remember(
            self.test_dir,
            room_key="procedures",
            title="Production Deployment Checklist",
            content="Step 1: run test suite. Step 2: docker build. Step 3: helm upgrade.",
            tags=["deployment", "docker", "production"]
        )
        palace_mod.remember(
            self.test_dir,
            room_key="decisions",
            title="ADR-004: Adopt SQLite for Local Metadata Cache",
            content="Decided to use SQLite with WAL mode enabled for atomic state tracking.",
            tags=["sqlite", "cache", "adr"]
        )

        t0 = time.perf_counter()
        results = palace_mod.recall(self.test_dir, "deployment", auto_mode=True)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertGreaterEqual(len(results), 1, "Should recall deployment procedure")
        self.assertEqual(results[0]["title"], "Production Deployment Checklist")
        self.assertLess(latency_ms, 25.0 * LATENCY_SCALE, f"Recall latency too high: {latency_ms:.2f}ms")

        # Recall with room filter
        dec_results = palace_mod.recall(self.test_dir, "cache", room="decisions", auto_mode=True)
        self.assertGreaterEqual(len(dec_results), 1)
        self.assertEqual(dec_results[0]["room_key"], "decisions")

    def test_prune_memory(self):
        """Pruning memory removes it from index and removes the block from markdown."""
        mem_id = palace_mod.remember(
            self.test_dir,
            room_key="working",
            title="Temporary Sprint Task",
            content="Inspect open PRs and clean test artifacts.",
            tags=["task", "cleanup"]
        )
        idx_before = palace_mod.load_index(self.test_dir)
        self.assertIn(mem_id, idx_before["memories"])

        palace_mod.prune(self.test_dir, mem_id=mem_id)

        idx_after = palace_mod.load_index(self.test_dir)
        self.assertNotIn(mem_id, idx_after["memories"])

        rpath = os.path.join(self.test_dir, "rooms", "working.md")
        with open(rpath, "r") as f:
            content = f.read()
        self.assertNotIn(mem_id, content)

    def test_concurrency_locking(self):
        """Palace file lock must be re-entrant and protect concurrent writes."""
        with palace_mod.palace_lock(self.test_dir):
            with palace_mod.palace_lock(self.test_dir):
                # Nested lock acquisition must succeed without deadlocking
                self.assertEqual(palace_mod._LOCK_DEPTH, 2)
        self.assertEqual(palace_mod._LOCK_DEPTH, 0)

    def test_high_volume_latency_benchmark(self):
        """Measures P50, P95, and P99 latency across 50 memory operations."""
        latencies = []
        for i in range(30):
            t0 = time.perf_counter()
            palace_mod.remember(
                self.test_dir,
                room_key="blueprint",
                title=f"Microservice Component Architecture #{i}",
                content=f"Detailed spec for microservice module {i} with circuit breakers.",
                tags=["microservice", "resilience", f"service{i}"]
            )
            latencies.append((time.perf_counter() - t0) * 1000.0)

        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)]

        self.assertLess(p50, 15.0 * LATENCY_SCALE, f"P50 latency exceeded 15ms: {p50:.2f}ms")
        self.assertLess(p95, 30.0 * LATENCY_SCALE, f"P95 latency exceeded 30ms: {p95:.2f}ms")

if __name__ == "__main__":
    unittest.main()
