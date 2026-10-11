#!/usr/bin/env python3
"""
Regression tests for the defects found in the full-project audit.

Each test names the failure it prevents. Everything runs against temp
directories and a throwaway HOME; nothing here touches a real ~/.claude.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from cortex import capacity, jsonfile, launcher, mcp, models, profiles  # noqa: E402


def load_script(filename):
    """Import a hyphen-named script from scripts/ as a module."""
    path = os.path.join(PROJECT_DIR, "scripts", filename)
    spec = importlib.util.spec_from_file_location(
        filename.replace("-", "_").replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TempHome(unittest.TestCase):
    """Base: a throwaway HOME so profile/shared-dir code never sees the real one."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="cortex_core_")
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.home, "USERPROFILE": self.home,
            "CORTEX_PROFILES_DIR": os.path.join(self.home, "profiles"),
        })
        self.env.start()
        profiles._AUTH_CACHE.clear()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.home, ignore_errors=True)


# --------------------------------------------------------------------------- locks

class TestFileLock(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cortex_lock_")
        self.path = os.path.join(self.dir, "cfg.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_no_lost_updates_under_contention(self):
        """Concurrent read-modify-write must not drop increments."""
        jsonfile.write(self.path, {"n": 0})

        def worker():
            for _ in range(8):
                jsonfile.update(self.path, lambda d: d.__setitem__("n", d["n"] + 1))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(jsonfile.read(self.path)["n"], 32)

    def test_stale_lock_from_a_dead_process_is_broken(self):
        """A crash while holding the lock must not block every later caller."""
        lock = self.path + ".lock"
        with open(lock, "w") as fh:
            fh.write("99999")
        old = time.time() - 600
        os.utime(lock, (old, old))
        with jsonfile.file_lock(self.path, timeout=2):
            pass                                  # acquired despite the leftover file
        self.assertFalse(os.path.exists(lock))

    def test_live_lock_times_out_instead_of_hanging(self):
        with jsonfile.file_lock(self.path):
            with self.assertRaises(TimeoutError):
                with jsonfile.file_lock(self.path, timeout=0.3):
                    pass

    def test_merge_keeps_other_keys_and_releases_lock(self):
        jsonfile.write(self.path, {"keep": 1})
        jsonfile.merge(self.path, {"add": 2})
        self.assertEqual(jsonfile.read(self.path), {"keep": 1, "add": 2})
        self.assertFalse(os.path.exists(self.path + ".lock"))


# ------------------------------------------------------------------------ launcher

class TestLauncher(unittest.TestCase):
    def test_dash_r_is_left_for_claude_resume(self):
        """-r is Claude Code's --resume; it must never become an effort flag."""
        args, err = launcher.translate_args(["-r", "abc123"])
        self.assertIsNone(err)
        self.assertEqual(args, ["-r", "abc123"])

    def test_new_model_flags_use_exact_ids(self):
        cases = {"--opus-5-5": "claude-opus-5-5", "-o55": "claude-opus-5-5",
                 "--sonnet-5-5": "claude-sonnet-5-5", "--fable": "claude-fable-5-1",
                 "--fable-5": "claude-fable-5", "-o": "claude-opus-5"}
        for flag, model in cases.items():
            args, err = launcher.translate_args([flag])
            self.assertIsNone(err)
            self.assertEqual(args, ["--model", model], flag)

    def test_no_single_letter_fable_alias(self):
        self.assertNotIn("-f", launcher.MODEL_ALIASES)

    def test_every_advertised_model_is_selectable(self):
        """cc model must not list a model that no launcher flag can select."""
        selectable = set(launcher.MODEL_ALIASES.values())
        for model_id, name, _ in models.SUBSCRIPTION_MODELS:
            self.assertIn(model_id, selectable, f"{name} ({model_id}) has no cc flag")

    def test_effort_validation(self):
        _, err = launcher.translate_args(["-e", "bogus"])
        self.assertIn("invalid effort", err)
        args, err = launcher.translate_args(["--effort=high"])
        self.assertEqual((args, err), (["--effort", "high"], None))


# ---------------------------------------------------------------------- profiles

class TestProfiles(TempHome):
    def _synced_profile_with_shared_data(self):
        shared = os.path.join(self.home, ".claude", "projects")
        os.makedirs(shared)
        marker = os.path.join(shared, "KEEP.txt")
        with open(marker, "w") as fh:
            fh.write("shared")
        target = profiles.ensure_structure("linky", "synced")
        return target, marker

    def test_removing_a_synced_profile_never_touches_shared_data(self):
        """Deleting through a link/junction would erase the user's real projects."""
        target, marker = self._synced_profile_with_shared_data()
        self.assertTrue(profiles._is_link(os.path.join(target, "projects")),
                        "precondition: projects should be a link or junction")
        self.assertEqual(profiles.remove("linky"), 0)
        self.assertFalse(os.path.exists(target))
        self.assertTrue(os.path.exists(marker), "shared data was deleted with the profile")

    def test_seed_identity_merges_instead_of_clobbering(self):
        target = profiles.ensure_structure("seed", "isolated")
        cfg = os.path.join(target, ".claude.json")
        jsonfile.write(cfg, {"theme": "dark", "oauthAccount": {"organizationUuid": "x"}})
        with mock.patch.object(profiles, "auth_status", return_value={
                "loggedIn": True, "email": "a@example.com", "subscriptionType": "max"}):
            self.assertTrue(profiles.seed_identity("seed"))
        data = jsonfile.read(cfg)
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(data["oauthAccount"]["organizationUuid"], "x")
        self.assertEqual(data["oauthAccount"]["emailAddress"], "a@example.com")
        self.assertTrue(data["hasCompletedOnboarding"])

    def test_cli_remove_without_confirmation_refuses_and_keeps_profile(self):
        """No --yes and no answer (script, hook, or NUL on Windows): do not delete."""
        profiles.ensure_structure("keepme", "isolated")
        env = dict(os.environ, PYTHONPATH=PROJECT_DIR, PYTHONUTF8="1")
        proc = subprocess.run([sys.executable, "-m", "cortex", "profile", "remove", "keepme"],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              env=env, timeout=60)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertTrue(os.path.isdir(profiles.profile_dir("keepme")))

    def test_cli_remove_with_yes_removes(self):
        profiles.ensure_structure("gone", "isolated")
        env = dict(os.environ, PYTHONPATH=PROJECT_DIR, PYTHONUTF8="1")
        proc = subprocess.run([sys.executable, "-m", "cortex", "profile", "remove",
                               "--yes", "gone"], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(os.path.exists(profiles.profile_dir("gone")))

    def test_cli_add_without_a_terminal_does_not_crash(self):
        """isatty() is True for NUL on Windows; EOF at the prompt must not traceback."""
        env = dict(os.environ, PYTHONPATH=PROJECT_DIR, PYTHONUTF8="1")
        proc = subprocess.run([sys.executable, "-m", "cortex", "profile", "add", "quiet"],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


# ---------------------------------------------------------------------- capacity

class TestCapacityParsing(TempHome):
    def _profile(self, name, usage):
        target = profiles.ensure_structure(name, "isolated")
        cfg = {"oauthAccount": {"emailAddress": f"{name}@example.com"}}
        if usage is not None:
            cfg["cachedUsageUtilization"] = usage
        jsonfile.write(os.path.join(target, ".claude.json"), cfg)

    @staticmethod
    def _iso(seconds):
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()

    def _inspect(self, name):
        return capacity.inspect(name, check_auth=False)

    def test_real_nested_usage_shape_is_understood(self):
        """The shape Claude Code records must not be reported as 'unreadable'."""
        self._profile("busy", {"utilization": {
            "five_hour": {"utilization": 30, "resets_at": self._iso(3600)},
            "seven_day": {"utilization": 10, "resets_at": self._iso(86400)}}})
        rec = self._inspect("busy")
        self.assertEqual(rec["state"], capacity.KNOWN_FREE)
        self.assertEqual(rec["utilization"], 30)

    def test_limit_reached_is_limited_with_a_reset_time(self):
        self._profile("capped", {"utilization": {
            "five_hour": {"utilization": 100, "resets_at": self._iso(7200)},
            "seven_day": {"utilization": 20, "resets_at": self._iso(86400)}}})
        rec = self._inspect("capped")
        self.assertEqual(rec["state"], capacity.KNOWN_LIMITED)
        self.assertIn("resets in", rec["detail"])

    def test_active_limits_entry_blocks(self):
        self._profile("weekly", {"utilization": {"limits": [
            {"kind": "weekly_all", "percent": 100, "severity": "critical",
             "is_active": True, "resets_at": self._iso(3600)}]}})
        self.assertEqual(self._inspect("weekly")["state"], capacity.KNOWN_LIMITED)

    def test_expired_window_is_unknown_not_free(self):
        """A window that already reset says the old numbers are void - not 'free'."""
        self._profile("old", {"utilization": {
            "five_hour": {"utilization": 100, "resets_at": self._iso(-3600)}}})
        self.assertEqual(self._inspect("old")["state"], capacity.UNKNOWN)

    def test_no_usage_data_is_unknown_and_never_chosen(self):
        self._profile("blank", None)
        self._profile("ok", {"utilization": {
            "five_hour": {"utilization": 5, "resets_at": self._iso(3600)}}})
        records = [self._inspect("blank"), self._inspect("ok")]
        self.assertEqual(records[0]["state"], capacity.UNKNOWN)
        self.assertEqual(capacity.best(records), "ok")
        self.assertIsNone(capacity.best([records[0]]))

    def test_best_prefers_least_used_and_skips_limited(self):
        self._profile("a", {"utilization": {"five_hour": {"utilization": 60, "resets_at": self._iso(900)}}})
        self._profile("b", {"utilization": {"five_hour": {"utilization": 10, "resets_at": self._iso(900)}}})
        self._profile("c", {"utilization": {"five_hour": {"utilization": 100, "resets_at": self._iso(900)}}})
        records = [self._inspect(n) for n in ("a", "b", "c")]
        self.assertEqual(capacity.best(records), "b")


# ----------------------------------------------------------------------- hooks

class TestPreToolHook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hook = load_script("cortex-pretool-hook.py")

    def blocked(self, cmd, cwd=None):
        return self.hook.check_command(cmd, cwd) is not None

    def test_blocks_the_real_hazards(self):
        for cmd in ("tree", "sudo tree /", "git log", "git log -p", "cat package-lock.json",
                    "type yarn.lock", "Get-Content Cargo.lock", "find . -type f"):
            self.assertTrue(self.blocked(cmd), cmd)

    def test_does_not_block_lookalikes(self):
        """'tree' inside another command or a path is not the tree command."""
        for cmd in ("git ls-tree HEAD", "cargo tree", "git write-tree",
                    "ls src/tree/node.py", "grep -rn tree src/", "echo a tree"):
            self.assertFalse(self.blocked(cmd), cmd)

    def test_bounded_forms_pass(self):
        for cmd in ("git log -n 5", "git log --oneline", "git log -5", "tree -L 2",
                    "git log | head -20", "cat package-lock.json | grep lodash"):
            self.assertFalse(self.blocked(cmd), cmd)

    def test_large_file_resolved_against_session_cwd_not_hook_cwd(self):
        d = tempfile.mkdtemp(prefix="cortex_hook_")
        try:
            with open(os.path.join(d, "big.log"), "wb") as fh:
                fh.write(b"x" * (200 * 1024))
            self.assertTrue(self.blocked("cat big.log", cwd=d))
            self.assertFalse(self.blocked("cat big.log | head -5", cwd=d))
            self.assertFalse(self.blocked("Get-Content big.log -TotalCount 5", cwd=d))
            self.assertFalse(self.blocked("cat small.log", cwd=d))   # missing: fail open
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_main_blocks_with_exit_2_and_covers_powershell(self):
        script = os.path.join(PROJECT_DIR, "scripts", "cortex-pretool-hook.py")
        for tool in ("Bash", "PowerShell"):
            payload = json.dumps({"tool_name": tool, "tool_input": {"command": "git log"}})
            proc = subprocess.run([sys.executable, script], input=payload, text=True,
                                  capture_output=True, timeout=30)
            self.assertEqual(proc.returncode, 2, tool)
        other = json.dumps({"tool_name": "Read", "tool_input": {"command": "git log"}})
        proc = subprocess.run([sys.executable, script], input=other, text=True,
                              capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0)

    def test_settings_routes_powershell_to_the_hook(self):
        with open(os.path.join(PROJECT_DIR, "config", "settings.json"), encoding="utf-8") as fh:
            matcher = json.load(fh)["hooks"]["PreToolUse"][0]["matcher"]
        self.assertIn("PowerShell", matcher)
        self.assertIn("Bash", matcher)


class TestPromptHookRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hook = load_script("cortex-prompt-hook.py")

    def test_safe_commands_run(self):
        for args in (["status"], ["doctor", "--repair"], ["model", "free"], ["--help"]):
            run, refusal = self.hook.route(args)
            self.assertEqual((run, refusal), (args, None), args)

    def test_session_launching_commands_are_refused_not_run(self):
        """/cc login would otherwise hang the hook until its timeout."""
        for args in (["login", "work"], ["continue"], ["--", "hello"], ["-work"],
                     ["work"], ["update"], ["ghidra", "build"]):
            run, refusal = self.hook.route(args)
            self.assertIsNone(run, args)
            self.assertIn("terminal", refusal)

    def test_plain_prompts_pass_through(self):
        script = os.path.join(PROJECT_DIR, "scripts", "cortex-prompt-hook.py")
        proc = subprocess.run([sys.executable, script],
                              input=json.dumps({"prompt": "switch the parser to a generator"}),
                              text=True, capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0)


# ---------------------------------------------------------------------- scorer

class TestScorer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oas = load_script("cortex-scorer.py")

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cortex_oas_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_complexity_counts_branches(self):
        flat = "def f(x):\n    return x\n"
        branchy = "def f(x):\n    if x:\n        for i in x:\n            if i and x:\n                return i\n    return 0\n"
        self.assertEqual(self.oas.complexity(flat), 1)
        self.assertGreater(self.oas.complexity(branchy), self.oas.complexity(flat) + 2)
        self.assertIsNone(self.oas.complexity("def ("))

    def test_unmeasurable_things_are_reported_not_invented(self):
        self._write("notes.md", "# hello\n")
        result = self.oas.evaluate_impact("notes.md", self.root)
        self.assertIn("complexity", result["unmeasured"])      # not Python
        self.assertNotIn("complexity", result["points"])
        self.assertIn("size", result["unmeasured"])            # not a git repo

    def test_test_reference_raises_score_and_missing_test_lowers_it(self):
        self._write("pkg/widget.py", "def f():\n    return 1\n")
        self._write("pkg/gadget.py", "def g():\n    return 2\n")
        self._write("tests/test_widget.py", "import widget\n")
        covered = self.oas.evaluate_impact("pkg/widget.py", self.root)
        bare = self.oas.evaluate_impact("pkg/gadget.py", self.root)
        self.assertGreater(covered["points"]["tests"], 0)
        self.assertLess(bare["points"]["tests"], 0)
        self.assertGreater(covered["score"], bare["score"])

    def test_destructive_pattern_lowers_recovery_score(self):
        self._write("tests/test_clean.py", "import clean\n")
        self._write("clean.sh", "rm -rf \"$TARGET\"\n")
        self._write("tidy.py", "print('ok')\n")
        risky = self.oas.evaluate_impact("clean.sh", self.root)
        safe = self.oas.evaluate_impact("tidy.py", self.root)
        self.assertLess(risky["points"]["recovery"], safe["points"]["recovery"])
        self.assertTrue(risky["metrics"]["recovery"]["destructive_patterns"])

    def test_path_outside_root_and_missing_file_are_errors(self):
        self.assertIn("error", self.oas.evaluate_impact("nope.py", self.root))
        other = tempfile.mkdtemp(prefix="cortex_oas_other_")
        try:
            outside = os.path.join(other, "x.py")
            with open(outside, "w") as fh:
                fh.write("x = 1\n")
            self.assertIn("error", self.oas.evaluate_impact(outside, self.root))
        finally:
            shutil.rmtree(other, ignore_errors=True)

    @unittest.skipUnless(shutil.which("git"), "git not available")
    def test_complexity_delta_against_git_head(self):
        def git(*args):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                           cwd=self.root, capture_output=True, check=True)
        git("init", "-q")
        self._write("mod.py", "def f(x):\n    return x\n")
        git("add", ".")
        git("commit", "-q", "-m", "init")
        self._write("mod.py", "def f(x):\n    if x:\n        if x > 1:\n            return 2\n    return x\n")
        result = self.oas.evaluate_impact("mod.py", self.root)
        self.assertEqual(result["metrics"]["complexity"]["before"], 1)
        self.assertGreater(result["metrics"]["complexity"]["delta"], 0)
        self.assertLess(result["points"]["complexity"], 0)
        self.assertTrue(result["metrics"]["recovery"]["committed"])


# -------------------------------------------------------- scripts & consistency

class TestScriptsAndConsistency(unittest.TestCase):
    def test_mcp_tool_list_matches_the_server(self):
        server = load_script("cortex-mcp.py")
        self.assertEqual(set(mcp.TOOL_NAMES), set(server.TOOLS))

    def test_evaluate_impact_tool_end_to_end(self):
        server = load_script("cortex-mcp.py")
        out = server.TOOLS["evaluate_impact"]["handler"](
            {"path": "cortex/jsonfile.py", "root": PROJECT_DIR})
        self.assertTrue(out.startswith("OAS "), out[:80])
        self.assertIn("/100", out)
        missing = server.TOOLS["evaluate_impact"]["handler"]({"path": "no/such.py", "root": PROJECT_DIR})
        self.assertIn("Cannot score", missing)

    def test_shell_scripts_and_python_have_lf_line_endings(self):
        """A CRLF install.sh fails on Linux/macOS with '\\r: command not found'."""
        for rel in ("install.sh", "uninstall.sh", "bin/claude", "cortex/launcher.py",
                    "scripts/cortex-prompt-hook.py"):
            with open(os.path.join(PROJECT_DIR, rel), "rb") as fh:
                self.assertNotIn(b"\r\n", fh.read(), f"{rel} has CRLF line endings")


class TestProviderFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = load_script("claude-provider.py")

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cortex_prov_")
        self.patch = mock.patch.object(self.provider, "PROVIDERS_FILE",
                                       os.path.join(self.dir, "providers.json"))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_corrupt_file_is_preserved_not_overwritten(self):
        """One bad byte must not cost the user every stored API key."""
        path = self.provider.PROVIDERS_FILE
        with open(path, "w") as fh:
            fh.write('{"providers": {"openrouter": {"api_key": "sk-secret"')   # truncated
        with mock.patch("sys.stderr"):
            cfg = self.provider.load_providers()
        self.assertEqual(cfg["active_provider"], "oauth")
        kept = [n for n in os.listdir(self.dir) if ".corrupt-" in n]
        self.assertEqual(len(kept), 1)
        with open(os.path.join(self.dir, kept[0])) as fh:
            self.assertIn("sk-secret", fh.read())

    def test_defaults_are_never_shared_between_calls(self):
        first = self.provider.load_providers()
        first["providers"]["oauth"]["model"] = "mutated"
        self.assertNotEqual(self.provider.DEFAULT_CONFIG["providers"]["oauth"].get("model"), "mutated")

    def test_save_leaves_no_temp_files_and_round_trips(self):
        self.provider.save_providers({"active_provider": "oauth", "providers": {}})
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])
        self.assertEqual(self.provider.load_providers()["active_provider"], "oauth")


class TestGatewayRetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateway = load_script("cortex-gateway.py")

    @staticmethod
    def _http_error(code, retry_after=None):
        import email.message
        msg = email.message.Message()
        if retry_after:
            msg["Retry-After"] = retry_after
        return urllib.error.HTTPError("http://x", code, "err", msg, None)

    def test_transient_status_is_retried_then_succeeds(self):
        waits = []
        calls = [self._http_error(503), self._http_error(429, "2"), "OK"]

        def fake(req, timeout):
            item = calls.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch("urllib.request.urlopen", side_effect=fake):
            result = self.gateway.open_with_retry("req", 5, sleep=waits.append)
        self.assertEqual(result, "OK")
        self.assertEqual(waits, [1.0, 2.0])      # backoff, then Retry-After honoured

    def test_client_errors_are_not_retried(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._http_error(400)) as m:
            with self.assertRaises(urllib.error.HTTPError):
                self.gateway.open_with_retry("req", 5, sleep=lambda s: None)
        self.assertEqual(m.call_count, 1)

    def test_gives_up_after_the_attempt_limit(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._http_error(503)) as m:
            with self.assertRaises(urllib.error.HTTPError):
                self.gateway.open_with_retry("req", 5, attempts=3, sleep=lambda s: None)
        self.assertEqual(m.call_count, 3)

    def test_timeouts_are_not_retried(self):
        boom = urllib.error.URLError(TimeoutError("timed out"))
        with mock.patch("urllib.request.urlopen", side_effect=boom) as m:
            with self.assertRaises(urllib.error.URLError):
                self.gateway.open_with_retry("req", 5, sleep=lambda s: None)
        self.assertEqual(m.call_count, 1)


class TestAnalyzerSizeCap(unittest.TestCase):
    def test_oversized_file_is_reported_not_silently_skipped(self):
        analyze = load_script("claude-analyze.py")
        d = tempfile.mkdtemp(prefix="cortex_big_")
        try:
            path = os.path.join(d, "huge.py")
            with open(path, "wb") as fh:
                fh.write(b"#" * (analyze.MAX_SOURCE_BYTES + 10))
            findings = analyze.analyse(path)
            self.assertEqual(len(findings), 1)
            self.assertIn("not analysed", findings[0].title)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
