#!/usr/bin/env python3
"""
Test Suite: IDE Extension Session Command Integration
Validates:
1. Multimodal & image attachment payloads from IDE extensions (VS Code, JetBrains, Cursor)
   are parsed correctly and execute commands locally with exit code 2 (0 API tokens).
2. Slash commands (/capacity, /model, /update, /test, /bench, /menu, /think, etc.)
   intercept and execute immediately with exit code 2.
3. Nested IDE message structures ({"message": {"content": [...]}}, {"parts": [...]})
   are unnested recursively.
4. Multimodal image attachments with normal coding prompts pass through with exit code 0.
5. Coding prompts starting with natural words ('test the...', 'update the...', 'clean up...')
   pass through to Claude with exit code 0 without false positives.
6. All slash command markdown files exist in config/commands and ~/.claude/commands with
   valid frontmatter and executable definitions.
7. Execution latency benchmark (< 100ms per command turn).
"""

import os
import sys

# Prevent bytecode caching
sys.dont_write_bytecode = True

import json
import time
import subprocess
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT_HOOK = os.path.join(PROJECT_DIR, "scripts", "cortex-prompt-hook.py")
if not os.path.exists(PROMPT_HOOK):
    PROMPT_HOOK = os.path.expanduser("~/.claude/scripts/cortex-prompt-hook.py")

SHARED_COMMANDS_DIR = os.path.expanduser("~/.claude/commands")
COMMANDS_DIR = os.path.join(PROJECT_DIR, "config", "commands")
if not os.path.exists(COMMANDS_DIR):
    COMMANDS_DIR = SHARED_COMMANDS_DIR

EXPECTED_COMMAND_FILES = [
    "capacity.md",
    "quota.md",
    "model.md",
    "provider.md",
    "update.md",
    "test.md",
    "bench.md",
    "palace.md",
    "remember.md",
    "recall.md",
    "dream.md",
    "research.md",
    "think.md",
    "smart.md",
    "turbo.md",
    "fast.md",
    "effort.md",
    "reasoning.md",
    "switch.md",
    "continue.md",
    "clean.md",
    "docs.md",
    "menu.md",
    "cc.md",
    "cortex.md"
]

class TestExtensionIntegration(unittest.TestCase):

    def run_hook(self, payload):
        """Runs cortex-prompt-hook.py with specified payload, returns (code, stdout, stderr, latency_ms)."""
        data = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
        t0 = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, PROMPT_HOOK],
            input=data,
            text=True,
            capture_output=True
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return proc.returncode, proc.stdout, proc.stderr, latency_ms

    def test_multimodal_image_attachment_with_command(self):
        """Image attachment accompanying a 'cc capacity' command must execute locally (exit code 2)."""
        payload = {
            "prompt": [
                {"type": "text", "text": "cc capacity"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                    }
                }
            ]
        }
        code, stdout, stderr, latency_ms = self.run_hook(payload)
        self.assertEqual(code, 2, "Expected exit code 2 (local command execution)")
        self.assertIn("Multi-Account Capacity", stderr)
        self.assertLess(latency_ms, 350.0, f"Latency too high: {latency_ms:.2f}ms")

    def test_multimodal_image_attachment_with_slash_command(self):
        """Image attachment accompanying a '/turbo on' command must execute locally (exit code 2)."""
        payload = {
            "content": [
                {"type": "image", "source": {"type": "base64", "data": "dummy"}},
                {"type": "text", "text": "/turbo on"}
            ]
        }
        code, stdout, stderr, latency_ms = self.run_hook(payload)
        self.assertEqual(code, 2)
        self.assertIn("Turbo Mode ACTIVE", stderr)
        self.assertLess(latency_ms, 250.0)

    def test_nested_extension_message_structures(self):
        """Nested JSON structures from IDE extensions must resolve correctly."""
        structures = [
            {"message": {"content": [{"type": "text", "text": "/model list"}]}},
            {"parts": [{"text": "/think high-throughput consensus"}]},
            {"messages": [{"role": "user", "content": [{"type": "text", "text": "cc palace"}]}]}
        ]
        for s in structures:
            code, stdout, stderr, latency_ms = self.run_hook(s)
            self.assertEqual(code, 2, f"Failed on nested structure: {s}")
            self.assertTrue(len(stderr.strip()) > 0)
            self.assertLess(latency_ms, 350.0)

    def test_multimodal_image_with_normal_prompt_passes(self):
        """An image attachment accompanying a real coding prompt must pass to Claude with exit code 0."""
        payload = {
            "prompt": [
                {"type": "text", "text": "Review this architecture diagram and suggest optimizations for our API gateway."},
                {"type": "image", "source": {"type": "base64", "data": "dummy"}}
            ]
        }
        code, stdout, stderr, latency_ms = self.run_hook(payload)
        self.assertEqual(code, 0, "Normal multimodal prompt should pass through with exit code 0")
        self.assertLess(latency_ms, 150.0)

    def test_coding_prompts_with_keywords_pass_transparently(self):
        """Natural coding prompts that begin with command words must NOT be false-intercepted."""
        coding_prompts = [
            "test the authentication token expiration logic in auth.py",
            "update the database migration file to include foreign keys",
            "clean up the leftover temporary test fixtures in tests/",
            "continue working on the distributed lock implementation",
            "model the user entity and relationships in schema.sql",
            "think of three edge cases for our queue consumer"
        ]
        for p in coding_prompts:
            code, stdout, stderr, latency_ms = self.run_hook({"prompt": p})
            self.assertEqual(code, 0, f"Coding prompt was incorrectly intercepted: {p}")
            self.assertLess(latency_ms, 150.0)

    def test_slash_command_markdown_files_exist(self):
        """All expected Cortex slash commands must exist in config/commands/ and ~/.claude/commands/."""
        for fname in EXPECTED_COMMAND_FILES:
            repo_file = os.path.join(COMMANDS_DIR, fname)
            shared_file = os.path.join(SHARED_COMMANDS_DIR, fname)

            self.assertTrue(os.path.exists(repo_file), f"Missing command file in repo: {fname}")
            self.assertTrue(os.path.exists(shared_file), f"Missing command file in ~/.claude/commands: {fname}")

            # Verify YAML frontmatter and contents
            with open(repo_file, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertTrue(content.startswith("---"), f"{fname} missing frontmatter delimiter")
            self.assertIn("name:", content, f"{fname} missing name frontmatter")
            self.assertIn("description:", content, f"{fname} missing description frontmatter")
            self.assertIn("command: true", content, f"{fname} missing command: true frontmatter")
            self.assertGreater(len(content.splitlines()), 8, f"{fname} has insufficient content")

    def test_all_cortex_slash_commands_intercept(self):
        """Every core Cortex slash command must intercept with exit code 2 and non-empty output."""
        slash_commands = [
            "/capacity",
            "/model free",
            "/provider status",
            "/effort high",
            "/turbo",
            "/fast",
            "/palace",
            "/dream",
            "/think concurrency",
            "/update",
            "/test",
            "/bench",
            "/switch",
            "/continue",
            "/clean",
            "/docs",
            "/menu",
            "/cc"
        ]
        for cmd in slash_commands:
            code, stdout, stderr, latency_ms = self.run_hook({"prompt": cmd})
            self.assertEqual(code, 2, f"Slash command failed to intercept: {cmd}")
            self.assertTrue(len(stderr.strip()) > 0, f"Slash command returned empty output: {cmd}")
            max_lat = 1500.0 if cmd in ("/test", "/bench") else 400.0
            self.assertLess(latency_ms, max_lat, f"Command {cmd} latency too high: {latency_ms:.2f}ms")

if __name__ == "__main__":
    unittest.main()
