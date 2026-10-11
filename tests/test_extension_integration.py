#!/usr/bin/env python3
"""
Test Suite: IDE extension / in-session command integration (cortex-prompt-hook.py)

The design this pins down, and why:

* ONLY an explicit `/cc` (or `!cc`, `/cc:`) prefix is a Cortex command. Exit code
  2 on UserPromptSubmit blocks the model AND ERASES the prompt, so a matcher that
  fires on ordinary words silently destroys user input. An earlier version matched
  bare "test"/"switch"/"continue" and prompts vanished.
* Everything else - including bare command words and plain slash commands that
  Claude Code itself handles from config/commands - passes through (exit 0).
* IDE extensions deliver prompts as nested dicts and multimodal arrays; the text
  must be found wherever it is buried.
* Commands that would start a session or login are refused with an explanation
  rather than run inside a hook, where they would hang.
* Every shipped slash command is well-formed and does not point at anything that
  no longer exists.
"""

import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

# Prevent bytecode caching
sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _guard import LATENCY_SCALE  # noqa: E402
from cortex import tools  # noqa: E402

PROMPT_HOOK = os.path.join(PROJECT_DIR, "scripts", "cortex-prompt-hook.py")
COMMANDS_DIR = os.path.join(PROJECT_DIR, "config", "commands")
SCRIPTS_DIR = os.path.join(PROJECT_DIR, "scripts")

IMAGE = {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="}}


class TestExtensionIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # The hook runs `python -m cortex`; give it a throwaway HOME so a command
        # like `/cc doctor` can never read or touch the real ~/.claude.
        cls.home = tempfile.mkdtemp(prefix="cortex_test_ext_")

    def run_hook(self, payload):
        """Run the hook; return (exit code, stdout, stderr, latency_ms)."""
        data = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
        env = dict(os.environ, HOME=self.home, USERPROFILE=self.home, PYTHONUTF8="1",
                   CORTEX_PROFILES_DIR=os.path.join(self.home, "profiles"))
        t0 = time.perf_counter()
        proc = subprocess.run([sys.executable, PROMPT_HOOK], input=data, text=True,
                              encoding="utf-8", capture_output=True, env=env, timeout=120)
        return proc.returncode, proc.stdout, proc.stderr, (time.perf_counter() - t0) * 1000.0

    # --- interception ------------------------------------------------------

    def test_cc_prefix_runs_locally_and_blocks_the_model(self):
        code, _, stderr, latency = self.run_hook({"prompt": "/cc version"})
        self.assertEqual(code, 2)
        self.assertIn("Claude Cortex", stderr)
        self.assertLess(latency, 2000.0 * LATENCY_SCALE)

    def test_alternate_prefixes_work(self):
        for prompt in ("!cc version", "/cc:version"):
            code, _, stderr, _ = self.run_hook({"prompt": prompt})
            self.assertEqual(code, 2, prompt)
            self.assertIn("Claude Cortex", stderr, prompt)

    def test_bare_cc_shows_help(self):
        code, _, stderr, _ = self.run_hook({"prompt": "/cc"})
        self.assertEqual(code, 2)
        self.assertIn("multi-account Claude Code launcher", stderr)

    def test_multimodal_image_with_command_is_intercepted(self):
        payload = {"prompt": [{"type": "text", "text": "/cc version"}, IMAGE]}
        code, _, stderr, _ = self.run_hook(payload)
        self.assertEqual(code, 2)
        self.assertIn("Claude Cortex", stderr)

    def test_nested_extension_message_structures(self):
        structures = [
            {"message": {"content": [{"type": "text", "text": "/cc version"}]}},
            {"parts": [{"text": "/cc version"}]},
            {"messages": [{"role": "user", "content": [{"type": "text", "text": "/cc version"}]}]},
            {"content": [IMAGE, {"type": "text", "text": "/cc version"}]},
        ]
        for structure in structures:
            code, _, stderr, _ = self.run_hook(structure)
            self.assertEqual(code, 2, f"not intercepted: {structure}")
            self.assertIn("Claude Cortex", stderr)

    def test_session_launching_commands_are_refused_with_an_explanation(self):
        """/cc login would start a browser flow inside a hook and hang for 120s."""
        for prompt in ("/cc login work", "/cc continue", "/cc -- hello", "/cc -work"):
            code, _, stderr, latency = self.run_hook({"prompt": prompt})
            self.assertEqual(code, 2, prompt)
            self.assertIn("terminal", stderr, prompt)
            self.assertLess(latency, 3000.0 * LATENCY_SCALE, f"{prompt} looks hung")

    # --- pass-through ------------------------------------------------------

    def test_ordinary_prompts_are_never_touched(self):
        prompts = [
            "Review this architecture diagram and suggest optimizations for our API gateway.",
            "test the authentication token expiration logic in auth.py",
            "update the database migration file to include foreign keys",
            "clean up the leftover temporary test fixtures in tests/",
            "continue working on the distributed lock implementation",
            "model the user entity and relationships in schema.sql",
            "think of three edge cases for our queue consumer",
            "switch the parser over to a generator",
        ]
        for prompt in prompts:
            code, _, stderr, _ = self.run_hook({"prompt": prompt})
            self.assertEqual(code, 0, f"ordinary prompt was intercepted: {prompt}")
            self.assertEqual(stderr.strip(), "")

    def test_bare_command_words_and_plain_slash_commands_pass_through(self):
        """No prefix, no interception: Claude Code handles /commands from config/commands."""
        for prompt in ("cc capacity", "cc status", "/capacity", "/model free", "/dream a concept"):
            code, _, _, _ = self.run_hook({"prompt": prompt})
            self.assertEqual(code, 0, prompt)

    def test_image_with_normal_prompt_passes(self):
        payload = {"prompt": [{"type": "text", "text": "What does this screenshot show?"}, IMAGE]}
        code, _, _, latency = self.run_hook(payload)
        self.assertEqual(code, 0)
        self.assertLess(latency, 1000.0 * LATENCY_SCALE)

    def test_malformed_input_fails_open(self):
        """A hook must never block a prompt because of its own problem."""
        for raw in ("", "not json at all {{{", "null", "[]"):
            code, _, _, _ = self.run_hook(raw)
            self.assertEqual(code, 0, repr(raw))

    # --- shipped slash commands --------------------------------------------

    def test_every_slash_command_file_is_well_formed(self):
        files = sorted(glob.glob(os.path.join(COMMANDS_DIR, "*.md")))
        self.assertGreater(len(files), 20)
        for path in files:
            name = os.path.basename(path)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertTrue(text.startswith("---"), f"{name}: missing frontmatter")
            front = text.split("---", 2)[1]
            self.assertRegex(front, r"(?m)^description:\s*\S", f"{name}: no description")
            self.assertGreaterEqual(len(text.splitlines()), 6, f"{name}: nearly empty")

    def test_no_slash_command_points_at_a_missing_script(self):
        """A command that runs a script that is not there fails at the moment of use."""
        for path in glob.glob(os.path.join(COMMANDS_DIR, "*.md")):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for script in set(re.findall(r"scripts/([A-Za-z0-9_.-]+\.(?:py|sh))", text)):
                self.assertTrue(os.path.isfile(os.path.join(SCRIPTS_DIR, script)),
                                f"{os.path.basename(path)} runs missing script {script}")

    def test_no_slash_command_runs_a_retired_cortex_command(self):
        """`cc menu`, `cc docs`, ... print 'no longer a Cortex command'."""
        retired = sorted(set(tools.RETIRED) | set(tools.IN_SESSION_ONLY))
        pattern = re.compile(r"^\s*(?:claude|cc)\s+(" + "|".join(map(re.escape, retired))
                             + r")(?![\w-])", re.MULTILINE)
        for path in glob.glob(os.path.join(COMMANDS_DIR, "*.md")):
            with open(path, encoding="utf-8") as fh:
                match = pattern.search(fh.read())
            self.assertIsNone(match, f"{os.path.basename(path)} runs retired command "
                                     f"'{match.group(1) if match else ''}'")


if __name__ == "__main__":
    unittest.main()
