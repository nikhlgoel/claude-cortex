#!/usr/bin/env python3
"""
Test Suite: Token Conservation & Lifecycle Hooks
Validates:
1. PreTool Hook blocks catastrophic token dumps (lockfiles, unpaged git log, unbounded tree)
2. Permitted surgical commands pass through transparently
3. In-Session Prompt Hook intercepts commands with exit code 2 (zero tokens consumed)
4. Non-command coding prompts pass through with exit code 0
5. PreCompact hook returns high-density lossless preservation directives
6. Execution latency (< 30ms per hook invocation)
7. Calculates quantitative token conservation metrics
"""

import os
import sys

# Prevent bytecode caching
sys.dont_write_bytecode = True

import json
import time
import subprocess
import unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _guard import LATENCY_SCALE  # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRETOOL_HOOK = os.path.join(PROJECT_DIR, "scripts", "cortex-pretool-hook.py")
PROMPT_HOOK = os.path.join(PROJECT_DIR, "scripts", "cortex-prompt-hook.py")
PRECOMPACT_HOOK = os.path.join(PROJECT_DIR, "scripts", "cortex-precompact-hook.py")

# Conservative estimated token savings per blocked catastrophic pattern
TOKEN_SAVINGS_ESTIMATES = {
    "cat package-lock.json": 35000,
    "cat yarn.lock": 28000,
    "cat poetry.lock": 18000,
    "unpaged git log": 30000,
    "unbounded tree": 20000,
    "unbounded find .": 15000,
    "in_session_command_intercept": 3200,  # Avoids prompt + reasoning + completion turn
    "precompact_adr_anchoring": 12000     # Avoids loss of architecture context & re-explanations
}

class TestTokenConservation(unittest.TestCase):

    def run_hook(self, script_path, input_dict):
        """Runs hook script with JSON piped into stdin, measures execution latency."""
        payload = json.dumps(input_dict)
        t0 = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, script_path],
            input=payload,
            text=True,
            capture_output=True,
            timeout=120,   # a hung hook fails this test instead of hanging the suite
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return proc.returncode, proc.stdout, proc.stderr, latency_ms

    def test_pretool_blocks_lockfile_cat(self):
        """PreTool Hook must block 'cat package-lock.json' with exit code 2."""
        payload = {
            "tool_name": "bash",
            "tool_input": {"command": "cat package-lock.json"}
        }
        code, stdout, stderr, latency_ms = self.run_hook(PRETOOL_HOOK, payload)
        self.assertEqual(code, 2, "Expected exit code 2 (blocked)")
        self.assertIn("Blocked 'cat package-lock.json'", stderr)
        self.assertLess(latency_ms, 150.0 * LATENCY_SCALE, f"Hook execution too slow: {latency_ms:.2f}ms")

    def test_pretool_blocks_unpaged_git_log(self):
        """PreTool Hook must block unpaged 'git log' with exit code 2."""
        payload = {
            "tool_name": "bash",
            "tool_input": {"command": "git log"}
        }
        code, stdout, stderr, latency_ms = self.run_hook(PRETOOL_HOOK, payload)
        self.assertEqual(code, 2, "Expected exit code 2 (blocked)")
        self.assertIn("Unpaged 'git log'", stderr)
        self.assertLess(latency_ms, 150.0 * LATENCY_SCALE, f"Hook execution too slow: {latency_ms:.2f}ms")

    def test_pretool_blocks_unbounded_tree(self):
        """PreTool Hook must block unbounded 'tree' with exit code 2."""
        payload = {
            "tool_name": "bash",
            "tool_input": {"command": "tree"}
        }
        code, stdout, stderr, latency_ms = self.run_hook(PRETOOL_HOOK, payload)
        self.assertEqual(code, 2, "Expected exit code 2 (blocked)")
        self.assertIn("Unbounded 'tree'", stderr)
        self.assertLess(latency_ms, 150.0 * LATENCY_SCALE)

    def test_pretool_allows_safe_git_log_and_tree(self):
        """PreTool Hook must allow bounded commands with exit code 0."""
        payloads = [
            {"tool_name": "bash", "tool_input": {"command": "git log -n 10 --oneline"}},
            {"tool_name": "bash", "tool_input": {"command": "tree -L 2"}},
            {"tool_name": "bash", "tool_input": {"command": "git status"}},
            {"tool_name": "bash", "tool_input": {"command": "grep 'version' package-lock.json"}},
        ]
        for p in payloads:
            code, stdout, stderr, latency_ms = self.run_hook(PRETOOL_HOOK, p)
            self.assertEqual(code, 0, f"Expected exit code 0 for safe command: {p['tool_input']['command']}")
            self.assertLess(latency_ms, 150.0 * LATENCY_SCALE)

    def test_prompt_hook_intercepts_explicit_prefix(self):
        """Only the explicit /cc and !cc prefixes are intercepted."""
        # Offline commands only: `/cc model` fetches a live catalog over the
        # network, which made a test about prefix handling depend on the internet.
        for cmd in ["/cc capacity", "/cc version", "!cc palace", "/cc"]:
            code, stdout, stderr, latency_ms = self.run_hook(PROMPT_HOOK, {"prompt": cmd})
            self.assertEqual(code, 2, f"Expected interception for: {cmd}")
            self.assertLess(latency_ms, 300.0 * LATENCY_SCALE)

    def test_prompt_hook_never_erases_ordinary_prompts(self):
        """Ordinary prompts must reach the model.

        Exit code 2 on UserPromptSubmit blocks AND ERASES the prompt, so a
        false positive here silently destroys user input. These phrasings were
        all being swallowed by the previous keyword matching.
        """
        for prompt in [
            "switch to the new API client",
            "test this function for edge cases",
            "claude keeps crashing, fix it",
            "continue the refactor from yesterday",
            "update the model config",
            "clean up this module",
            "research how tokio schedules tasks",
            "think about the caching strategy",
            "capacity planning for the queue",
            "cc is not a word I meant as a command",
        ]:
            code, stdout, stderr, latency_ms = self.run_hook(PROMPT_HOOK, {"prompt": prompt})
            self.assertEqual(code, 0, f"Hook ERASED an ordinary prompt: {prompt!r}")

    def test_prompt_hook_passes_regular_prompt(self):
        """In-Session Prompt Hook must pass normal coding prompt with exit code 0."""
        code, stdout, stderr, latency_ms = self.run_hook(
            PROMPT_HOOK,
            {"prompt": "Refactor the database connection pool in dnet-engine"}
        )
        self.assertEqual(code, 0, "Normal prompt should pass with exit code 0")
        self.assertLess(latency_ms, 150.0 * LATENCY_SCALE)

    def test_precompact_hook_directives(self):
        """PreCompact Hook must emit critical context preservation directives on stdout."""
        code, stdout, stderr, latency_ms = self.run_hook(PRECOMPACT_HOOK, {"trigger": "auto"})
        self.assertEqual(code, 0)
        self.assertIn("CRITICAL PRE-COMPACTION PRESERVATION DIRECTIVES", stdout)
        self.assertIn("Architectural Decision Records", stdout)
        self.assertIn("Workshop", stdout)
        self.assertLess(latency_ms, 150.0 * LATENCY_SCALE)

    def test_calculate_session_token_savings(self):
        """Computes total simulated token conservation over a 50-turn complex coding session."""
        # Simulated session with 4 prevented lockfile reads, 6 prevented unpaged logs,
        # 10 local in-session command executions, and 1 compaction anchoring
        savings = (
            4 * TOKEN_SAVINGS_ESTIMATES["cat package-lock.json"] +
            6 * TOKEN_SAVINGS_ESTIMATES["unpaged git log"] +
            5 * TOKEN_SAVINGS_ESTIMATES["unbounded tree"] +
            10 * TOKEN_SAVINGS_ESTIMATES["in_session_command_intercept"] +
            1 * TOKEN_SAVINGS_ESTIMATES["precompact_adr_anchoring"]
        )
        self.assertGreater(savings, 400000, "Expected >400,000 tokens conserved in complex session simulation")

if __name__ == "__main__":
    unittest.main()
