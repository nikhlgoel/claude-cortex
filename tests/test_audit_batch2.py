#!/usr/bin/env python3
"""
Regression tests, second batch: the defects the Antigravity bug list pointed at,
once each was verified (and independently re-checked) against the code.

One test per defect, named for the failure it prevents. Everything runs against
temp directories; nothing touches a real ~/.claude.
"""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from cortex import proc  # noqa: E402

WINDOWS = os.name == "nt"


def load_module(relpath, name=None):
    """Import any repo file (hyphenated names, scripts, installers) as a module."""
    path = os.path.join(PROJECT_DIR, relpath)
    spec = importlib.util.spec_from_file_location(
        name or os.path.basename(relpath).replace("-", "_").replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------- process helper

class TestProc(unittest.TestCase):
    @unittest.skipUnless(WINDOWS, "the grandchild-holds-the-pipe hang is Windows-specific")
    def test_timeout_really_bounds_a_grandchild_that_holds_the_pipe(self):
        """subprocess.run(capture_output, timeout=2) took 11s here; the helper must not."""
        started = time.perf_counter()
        with self.assertRaises(subprocess.TimeoutExpired):
            proc.run(["cmd", "/c", "ping -n 20 127.0.0.1"], timeout=1)
        # 1s timeout + a prompt tree-kill is ~1.5s. A helper that failed to kill the
        # grandchild would still return, but only after waiting out DRAIN_SECONDS (~6s),
        # so the bound has to sit well below that to mean anything.
        self.assertLess(time.perf_counter() - started, 4.0)

    def test_output_is_decoded_as_utf8_whatever_the_console_code_page(self):
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        result = proc.run([sys.executable, "-c", "print('check \u2713 room \U0001F3DB')"],
                          timeout=30, env=env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("\u2713", result.stdout)

    def test_missing_program_raises_a_catchable_error(self):
        with self.assertRaises(OSError):
            proc.run(["definitely-not-a-real-program-xyz"], timeout=5)

    @unittest.skipUnless(WINDOWS, "native separators matter on Windows only")
    def test_resolved_paths_use_native_separators(self):
        """cmd.exe mis-parses an argv[0] containing '/', as an MSYS Python produces."""
        resolved = proc.resolve(["cmd", "/c", "echo hi"])
        self.assertNotIn("/", resolved[0])
        self.assertEqual(proc.run(["cmd", "/c", "echo hi"], timeout=20).stdout.strip(), "hi")

    @unittest.skipUnless(WINDOWS and shutil.which("npm"), "needs a .CMD shim on PATH")
    def test_cmd_shims_resolve_by_bare_name(self):
        self.assertEqual(proc.run(["npm", "--version"], timeout=60).returncode, 0)


# ------------------------------------------------------------------------------ palace

class TestPalace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.palace = load_module("scripts/claude-palace.py")
        cls.script = os.path.join(PROJECT_DIR, "scripts", "claude-palace.py")

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cortex_palace_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _count(self):
        return len(self.palace.load_index(self.dir)["memories"])

    def test_changed_content_under_the_same_title_is_not_discarded(self):
        """It used to print 'already recorded' and silently drop the new information."""
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            first = self.palace.remember(self.dir, "blueprint", "Database pool size", "Use pool size 10")
            second = self.palace.remember(self.dir, "blueprint", "Database pool size",
                                          "CHANGED: pool size 50 after the outage")
        self.assertNotEqual(first, second)
        self.assertEqual(self._count(), 2)

    def test_true_duplicates_are_still_skipped(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            first = self.palace.remember(self.dir, "blueprint", "Database pool size", "Use pool size 10")
            again = self.palace.remember(self.dir, "blueprint", "Database pool size", "Use pool size 10")
        self.assertEqual(first, again)
        self.assertEqual(self._count(), 1)

    def test_empty_content_is_refused_not_a_crash(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertIsNone(self.palace.remember(self.dir, "blueprint", "T", "   \n"))

    def test_cli_empty_content_prints_usage_instead_of_an_indexerror(self):
        env = dict(os.environ, PYTHONUTF8="1")
        proc_result = subprocess.run([sys.executable, self.script, "--path", self.dir,
                                      "remember", "blueprint", ""],
                                     capture_output=True, text=True, encoding="utf-8",
                                     env=env, timeout=60)
        self.assertEqual(proc_result.returncode, 1)
        self.assertNotIn("Traceback", proc_result.stderr)
        self.assertIn("Usage", proc_result.stdout)

    def test_corrupt_index_is_kept_not_wiped_by_the_next_save(self):
        self.palace.ensure_palace_structure(self.dir)
        index = os.path.join(self.dir, "index.json")
        with open(index, "w", encoding="utf-8") as fh:
            fh.write('{"memories": {"x": ')              # truncated
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            fresh = self.palace.load_index(self.dir)
        self.assertEqual(fresh["memories"], {})
        kept = [n for n in os.listdir(self.dir) if n.startswith("index.json.corrupt-")]
        self.assertEqual(len(kept), 1, "the unreadable index must be preserved")

    def test_works_under_a_legacy_console_code_page(self):
        """Under cp1252 every palace command crashed printing a room icon."""
        env = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="cp1252")
        result = subprocess.run([sys.executable, self.script, "--path", self.dir,
                                 "remember", "blueprint", "Pool", "size is 10"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("UnicodeEncodeError", result.stderr)
        self.assertIn("Deposited", result.stdout)
        recalled = subprocess.run([sys.executable, self.script, "--path", self.dir, "recall", "pool"],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  env=env, timeout=60)
        self.assertEqual(recalled.returncode, 0, recalled.stderr)

    def test_the_lock_really_excludes_another_process(self):
        """On Windows the old 'lock' imported only fcntl and silently did nothing."""
        ready = os.path.join(self.dir, "ready.flag")
        holder = (
            "import importlib.util, sys, time\n"
            f"spec = importlib.util.spec_from_file_location('p', {self.script!r})\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            f"with m.palace_lock({self.dir!r}):\n"
            f"    open({ready!r}, 'w').close()\n"
            "    time.sleep(4)\n")
        child = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        try:
            deadline = time.time() + 20
            while not os.path.exists(ready) and time.time() < deadline:
                time.sleep(0.05)
            self.assertTrue(os.path.exists(ready), "the holder never took the lock")
            with open(os.path.join(self.dir, ".palace.lock"), "a", encoding="utf-8") as fd:
                self.assertFalse(self.palace._try_lock(fd), "a second process got the lock")
        finally:
            child.wait(timeout=30)
        with open(os.path.join(self.dir, ".palace.lock"), "a", encoding="utf-8") as fd:
            self.assertTrue(self.palace._try_lock(fd), "the lock was not released")
            self.palace._unlock(fd)


# --------------------------------------------------------------------------- updater

class TestUpdater(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upd = load_module("scripts/claude-update.py")

    def test_an_uninstalled_tool_is_not_update_ready(self):
        self.assertEqual(self.upd.compare_versions("1.2.3", "Not Installed"), 0)
        self.assertEqual(self.upd.compare_versions("Unknown", "1.0.0"), 0)
        self.assertEqual(self.upd.compare_versions("1.2.3", "1.2.2"), 1)

    def test_a_failed_lookup_is_never_cached_as_an_answer(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(self.upd, "UPDATE_CACHE_FILE", os.path.join(d, "c.json")):
            calls = []

            def failing():
                calls.append(1)
                return ""

            self.upd.get_cached_or_fetch("k", failing)
            self.upd.get_cached_or_fetch("k", failing)
            self.assertEqual(len(calls), 2, "a failure was cached for the TTL")

            good = []
            self.upd.get_cached_or_fetch("g", lambda: good.append(1) or "1.0")
            self.upd.get_cached_or_fetch("g", lambda: good.append(1) or "1.0")
            self.assertEqual(len(good), 1, "a real answer should be cached")

    def test_windows_names_for_the_preserved_binary_are_found(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(self.upd, "BIN_DIR", d), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": os.path.join(d, "nowhere")}):
            open(os.path.join(d, "claude"), "w").close()        # Cortex's own wrapper
            self.assertIsNone(self.upd.find_real_claude(), "the wrapper must never be used")
            name = "claude.real.exe" if WINDOWS else "claude.real"
            open(os.path.join(d, name), "w").close()
            self.assertEqual(self.upd.find_real_claude(), os.path.join(d, name))

    def _fake_repo(self):
        d = tempfile.mkdtemp(prefix="cortex_upd_")
        os.makedirs(os.path.join(d, ".git"))
        with open(os.path.join(d, ".git", "HEAD"), "w") as fh:
            fh.write("ref: refs/heads/main\n")
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_unreachable_remote_is_not_reported_as_up_to_date(self):
        repo = self._fake_repo()
        with mock.patch.object(self.upd, "CORTEX_REPO_DIR", repo), \
                mock.patch.object(self.upd, "_run", side_effect=OSError("offline")), \
                mock.patch.object(self.upd, "run_cmd",
                                  side_effect=lambda args, timeout=20: "0" if "--count" in args else "abc1234"):
            info = self.upd.get_cortex_repo_status(force_fetch=True)
        self.assertIn("remote unreachable", info["latest"])
        self.assertNotIn("Up to date", info["latest"])
        self.assertFalse(info["fetch_ok"])

    def test_fetch_timeout_is_a_status_not_a_traceback(self):
        repo = self._fake_repo()
        with mock.patch.object(self.upd, "CORTEX_REPO_DIR", repo), \
                mock.patch.object(self.upd, "_run",
                                  side_effect=subprocess.TimeoutExpired("git", 10)), \
                mock.patch.object(self.upd, "run_cmd", return_value=""):
            info = self.upd.get_cortex_repo_status(force_fetch=True)   # must not raise
        self.assertFalse(info["fetch_ok"])

    def test_apply_does_not_claim_success_when_a_step_failed(self):
        statuses = [{"name": "Claude Code CLI", "type": "cli", "has_update": True,
                     "current": "1.0.0", "latest": "2.0.0"}]
        failed = subprocess.CompletedProcess(["claude", "update"], 1, "", "boom")
        out = io.StringIO()
        with mock.patch.object(self.upd, "find_real_claude", return_value="C:/x/claude.real.exe"), \
                mock.patch.object(self.upd, "_run", return_value=failed), \
                mock.patch.object(self.upd, "get_all_statuses", return_value=[]), \
                mock.patch("sys.stdout", out):
            problems = self.upd.apply_updates(statuses)
        text = out.getvalue()
        self.assertEqual(problems, ["Claude Code CLI"])
        self.assertIn("did not complete", text)
        self.assertNotIn("Update execution complete", text)

    def test_never_pulls_into_a_feature_branch(self):
        statuses = [{"name": "Claude Cortex Core Engine", "type": "repo", "has_update": True,
                     "current": "a", "latest": "b", "behind": 3, "branch": "fix/verified-audit"}]
        with mock.patch.object(self.upd, "_run") as run, \
                mock.patch.object(self.upd, "get_all_statuses", return_value=[]), \
                mock.patch("sys.stdout", io.StringIO()):
            self.upd.apply_updates(statuses)
        run.assert_not_called()


# -------------------------------------------------------------------------- gateway

class TestGatewayRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gw = load_module("scripts/cortex-gateway.py")
        cls.prov = load_module("scripts/claude-provider.py")

    def test_the_default_openrouter_provider_routes_to_openrouter(self):
        """Its generic type 'api_key' sent the user's OpenRouter key to api.anthropic.com."""
        entry = dict(self.prov.DEFAULT_CONFIG["providers"]["openrouter"], key_name="openrouter")
        self.assertEqual(self.gw.resolve_route(entry), ("openrouter", None))
        legacy = dict(entry, type="api_key")                 # a file written by an older version
        self.assertEqual(self.gw.resolve_route(legacy), ("openrouter", None))

    def test_each_builtin_provider_goes_to_its_own_vendor(self):
        cases = {"anthropic": "anthropic", "gemini": "gemini", "local": "local"}
        for name, expected in cases.items():
            self.assertEqual(self.gw.resolve_route({"key_name": name, "type": "api_key"}),
                             (expected, None), name)

    def test_unknown_or_unusable_providers_are_refused_not_guessed(self):
        for prov in ({"key_name": "mystery", "type": "mystery"},
                     {"key_name": "x", "type": "invalid", "error": "bad json"},
                     {"key_name": "oauth", "type": "oauth"},
                     {"key_name": "custom", "type": ""}):
            route, why = self.gw.resolve_route(prov)
            self.assertIsNone(route, prov)
            self.assertTrue(why)

    def test_a_corrupt_providers_file_is_invalid_not_oauth(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "providers.json")
            with open(path, "w") as fh:
                fh.write("{not json")
            with mock.patch.object(self.gw, "PROVIDERS_FILE", path), \
                    mock.patch("sys.stderr", io.StringIO()):
                conf = self.gw.get_active_provider_config()
        self.assertEqual(conf["type"], "invalid")
        self.assertIsNone(self.gw.resolve_route(conf)[0])

    def test_existing_provider_files_are_migrated_on_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "providers.json")
            with open(path, "w") as fh:
                json.dump({"active_provider": "openrouter",
                           "providers": {"openrouter": {"type": "api_key", "api_key": "k"}}}, fh)
            with mock.patch.object(self.prov, "PROVIDERS_FILE", path):
                loaded = self.prov.load_providers()
        self.assertEqual(loaded["providers"]["openrouter"]["type"], "openrouter")
        self.assertEqual(loaded["providers"]["openrouter"]["api_key"], "k")


class TestGatewayBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gw = load_module("scripts/cortex-gateway.py")

    def _handler(self):
        handler = object.__new__(self.gw.CortexGatewayHandler)
        handler.wfile = io.BytesIO()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        return handler

    def test_a_failed_tool_result_is_never_described_as_successful(self):
        long_text = "x" * 1000
        messages = []
        for i in range(8):
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{i}", "is_error": i == 0, "content": long_text}]})
            messages.append({"role": "assistant", "content": "ok"})
        compressed, saved = self.gw.apply_ot_acr_compression({"messages": messages})
        first = compressed["messages"][0]["content"][0]
        self.assertIn("ERROR", first["content"])
        self.assertNotIn("succeeded", first["content"])
        self.assertGreater(saved, 0)

    def test_list_form_tool_results_are_compressed_too(self):
        messages = []
        for i in range(8):
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{i}",
                 "content": [{"type": "text", "text": "y" * 800}]}]})
            messages.append({"role": "assistant", "content": "ok"})
        compressed, saved = self.gw.apply_ot_acr_compression({"messages": messages})
        self.assertGreater(saved, 0, "list-form content (what Claude Code sends) was never pruned")

    def test_gemini_finish_reasons_map_to_real_stop_reasons(self):
        self.assertEqual(self.gw.GEMINI_STOP_REASONS["MAX_TOKENS"], "max_tokens")
        self.assertEqual(self.gw.GEMINI_STOP_REASONS["SAFETY"], "refusal")
        self.assertEqual(self.gw.GEMINI_STOP_REASONS["STOP"], "end_turn")

    def test_a_mid_stream_failure_is_an_sse_error_not_a_second_http_response(self):
        class Upstream:
            status = 200
            reads = 0

            def getheaders(self):
                return [("Content-Type", "text/event-stream")]

            def read(self, _n):
                Upstream.reads += 1
                if Upstream.reads == 1:
                    return b"event: ping\n\n"
                raise OSError("upstream reset mid-body")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        handler = self._handler()
        with mock.patch.object(self.gw, "open_with_retry", return_value=Upstream()):
            handler.relay("request", "Test")
        written = handler.wfile.getvalue().decode("utf-8")
        self.assertIn("event: error", written)
        self.assertNotIn("HTTP/", written, "a second HTTP response was written into the stream")
        handler.send_response.assert_called_once()           # only the original 200

    def test_a_client_disconnect_stops_quietly(self):
        class Upstream:
            status = 200

            def getheaders(self):
                return []

            def read(self, _n):
                return b"data"

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        handler = self._handler()
        handler.wfile = mock.Mock()
        handler.wfile.write.side_effect = BrokenPipeError()
        with mock.patch.object(self.gw, "open_with_retry", return_value=Upstream()):
            handler.relay("request", "Test")          # must return, not raise or loop forever


# ---------------------------------------------------------------------- installer merge

class TestInstallerSettingsMerge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inst = load_module("install.py", "cortex_installer")

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cortex_inst_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.src = os.path.join(self.dir, "ours.json")
        self.dest = os.path.join(self.dir, "settings.json")
        self.cortex_hook = {"matcher": "Bash|PowerShell",
                            "hooks": [{"type": "command", "command": "python3 ~/.claude/scripts/cortex-pretool-hook.py"}]}
        with open(self.src, "w", encoding="utf-8") as fh:
            json.dump({"model": "opus", "theme": "dark",
                       "hooks": {"PreToolUse": [self.cortex_hook]}}, fh)

    def _merge(self):
        from pathlib import Path
        return self.inst.merge_settings(Path(self.src), Path(self.dest))

    def test_the_users_values_and_hooks_survive_a_merge(self):
        users = {"model": "sonnet", "permissions": {"allow": ["Bash(ls)"]},
                 "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "my-lint"}]}],
                           "Stop": [{"hooks": [{"type": "command", "command": "notify"}]}]}}
        with open(self.dest, "w", encoding="utf-8") as fh:
            json.dump(users, fh)
        self.assertTrue(self._merge())
        with open(self.dest, encoding="utf-8") as fh:
            merged = json.load(fh)
        self.assertEqual(merged["model"], "sonnet", "the user's model was overwritten")
        self.assertEqual(merged["theme"], "dark", "a missing default should be filled in")
        self.assertEqual(merged["permissions"], users["permissions"])
        self.assertIn("Stop", merged["hooks"], "the user's hook event was dropped")
        commands = [h["command"] for e in merged["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertIn("my-lint", commands)
        self.assertIn("python3 ~/.claude/scripts/cortex-pretool-hook.py", commands)

    def test_an_unparseable_file_is_left_exactly_as_it_was(self):
        original = b'{"model": "opus",}\n// my notes\n'                 # JSONC, which json.load rejects
        with open(self.dest, "wb") as fh:
            fh.write(original)
        self.assertFalse(self._merge())
        with open(self.dest, "rb") as fh:
            self.assertEqual(fh.read(), original, "the user's settings were rewritten")

    def test_a_byte_order_mark_does_not_block_the_merge(self):
        with open(self.dest, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" + json.dumps({"model": "haiku"}).encode())
        self.assertTrue(self._merge())

    def test_an_older_install_gets_the_new_matcher_without_duplicating(self):
        old = {"matcher": "Bash", "hooks": [self.cortex_hook["hooks"][0]]}
        with open(self.dest, "w", encoding="utf-8") as fh:
            json.dump({"hooks": {"PreToolUse": [old]}}, fh)
        self._merge()
        with open(self.dest, encoding="utf-8") as fh:
            entries = json.load(fh)["hooks"]["PreToolUse"]
        self.assertEqual(len(entries), 1, "the Cortex hook was duplicated")
        self.assertEqual(entries[0]["matcher"], "Bash|PowerShell")

    def test_a_backup_is_written(self):
        with open(self.dest, "w", encoding="utf-8") as fh:
            json.dump({"model": "haiku"}, fh)
        self._merge()
        self.assertTrue(os.path.exists(self.dest + ".cortex-install.bak"))


# ------------------------------------------------------------------------ guard hook

class TestGuardHookRefinements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hook = load_module("scripts/cortex-pretool-hook.py")

    def blocked(self, cmd, cwd=None):
        return self.hook.check_command(cmd, cwd) is not None

    def test_prose_inside_quotes_does_not_trigger_a_block(self):
        for cmd in ('git commit -m "tweak git log handling"', 'grep -rn "git log" docs',
                    'echo "run tree to see"', 'git commit -m "fix: x; cat package-lock.json"'):
            self.assertFalse(self.blocked(cmd), cmd)

    def test_the_recommended_forms_are_allowed(self):
        """The message tells the model to use jq; that form must pass."""
        for cmd in ("jq .name package-lock.json", "cat package-lock.json | jq .name",
                    "Get-Content package-lock.json -TotalCount 40",
                    "gc package-lock.json -Tail 5"):
            self.assertFalse(self.blocked(cmd), cmd)

    def test_real_unbounded_reads_are_still_blocked_in_every_spelling(self):
        for cmd in ("cat package-lock.json", "Get-Content package-lock.json",
                    "Get-Content -Path package-lock.json", "Get-Content -Raw package-lock.json",
                    'cat "package-lock.json"'):
            self.assertTrue(self.blocked(cmd), cmd)

    def test_quoted_paths_with_spaces_are_checked_against_the_size_ceiling(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "My Big File.log"), "wb") as fh:
                fh.write(b"x" * (200 * 1024))
            self.assertTrue(self.blocked('cat "My Big File.log"', cwd=d))
            self.assertTrue(self.blocked("Get-Content -Path 'My Big File.log'", cwd=d))
            self.assertFalse(self.blocked('cat "My Big File.log" | head -5', cwd=d))

    def test_a_blocked_lockfile_read_names_a_form_that_passes(self):
        reason = self.hook.check_command("cat package-lock.json")
        self.assertIn("jq", reason)
        self.assertIsNone(self.hook.check_command("jq '.name' package-lock.json"))


# -------------------------------------------------------------------------- packaging

class TestReleasePackager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.br = load_module("scripts/build-releases.py")

    def test_every_flavor_contains_the_python_core(self):
        """No flavor had it: every release installed and then failed 'Cortex core not found'."""
        for name, (items, _excludes) in self.br.FLAVORS.items():
            self.assertIn("cortex", items, name)
            self.assertIn("scripts", items, f"{name} would ship no hooks")

    def test_every_listed_item_exists_or_is_explicitly_optional(self):
        for name, (items, _excludes) in self.br.FLAVORS.items():
            self.assertEqual(self.br.missing_items(items), [], f"{name} lists items that do not exist")

    def test_a_missing_item_fails_the_build_instead_of_being_skipped(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, self.assertRaises(SystemExit):
            self.br.build_flavor("bad", ("cortex", "scripts/claude-dream.py"), (), Path(d))

    def test_the_version_comes_from_the_core(self):
        from cortex.__main__ import VERSION
        self.assertEqual(self.br.VERSION, VERSION)

    def test_a_staged_flavor_really_contains_the_core_and_no_internal_notes(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            stage = self.br.build_flavor("terminal-only", *self.br.FLAVORS["terminal-only"], Path(d))
            self.assertTrue((stage / "cortex" / "__main__.py").is_file())
            self.assertTrue((stage / "scripts" / "cortex-pretool-hook.py").is_file())
            self.assertFalse((stage / "scripts" / "cortex-mcp.py").exists(), "terminal flavor ships the MCP server")
            self.assertFalse((stage / "docs" / "management").exists(), "internal planning notes leaked")
            self.assertEqual(list(stage.rglob("__pycache__")), [])


# ------------------------------------------------------------------- audit gates

class TestAuditGates(unittest.TestCase):
    def test_sanitization_audit_fails_closed_on_an_unreadable_file(self):
        audit = load_module("scripts/audit-pack-sanitization.py")
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "ok.txt"), "w") as fh:
                fh.write("nothing to see")
            real_open = open

            def flaky_open(path, *args, **kwargs):
                if str(path).endswith("ok.txt"):
                    raise PermissionError("locked")
                return real_open(path, *args, **kwargs)

            out = io.StringIO()
            with mock.patch.object(audit, "PACK_DIR", d), mock.patch("builtins.open", flaky_open), \
                    mock.patch("sys.stdout", out), self.assertRaises(SystemExit) as ctx:
                audit.audit_pack()
        self.assertEqual(ctx.exception.code, 1, "an unscanned file must not produce a clean audit")
        self.assertIn("UNREADABLE", out.getvalue())

    def test_a_file_named_like_the_audit_script_is_still_scanned(self):
        audit = load_module("scripts/audit-pack-sanitization.py")
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "sub")
            os.makedirs(sub)
            with open(os.path.join(sub, os.path.basename(audit.__file__)), "w") as fh:
                fh.write("harmless\n")
            out = io.StringIO()
            with mock.patch.object(audit, "PACK_DIR", d), mock.patch("sys.stdout", out), \
                    self.assertRaises(SystemExit):
                audit.audit_pack()
        # The basename match used to exempt this file from scanning entirely.
        self.assertIn("Scanned 1 files", out.getvalue())

    def test_upstream_audit_that_crashed_is_reported_as_not_run(self):
        watch = load_module("tools/ghidra/update_watch.py")

        def fake_run(cmd, **kwargs):
            if cmd[0] == "git":
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return fake_run.audit_result

        cases = {
            "crash": subprocess.CompletedProcess([], 1, "partial report\n", "Traceback (most recent call last):\nValueError"),
            "bad exit": subprocess.CompletedProcess([], 2, "", "unreadable baseline"),
            "empty": subprocess.CompletedProcess([], 0, "   ", ""),
        }
        with tempfile.TemporaryDirectory() as d:
            baseline = os.path.join(d, "baseline.json")
            open(baseline, "w").close()
            for label, result in cases.items():
                fake_run.audit_result = result
                with mock.patch.object(watch, "run", fake_run):
                    report, error = watch.audit_tag("v1", baseline)
                self.assertIsNone(report, label)
                self.assertTrue(error, label)

            # With NO baseline there is no comparison section to look for, so the
            # stderr traceback is the only thing that can tell a crash from a result.
            fake_run.audit_result = cases["crash"]
            with mock.patch.object(watch, "run", fake_run):
                report, error = watch.audit_tag("v1", None)
            self.assertIsNone(report, "a crash without a baseline must not look like a clean audit")
            self.assertIn("crashed", error)

            fake_run.audit_result = subprocess.CompletedProcess(
                [], 1, "report\nCHANGE SINCE BASELINE\n  surface grew", "")
            with mock.patch.object(watch, "run", fake_run):
                report, error = watch.audit_tag("v1", baseline)
            self.assertIsNone(error, "exit 1 with a real comparison means 'surface grew', not 'failed'")
            self.assertIn("CHANGE SINCE BASELINE", report)


# --------------------------------------------------------------- Windows PowerShell shim

class TestPowerShellShim(unittest.TestCase):
    @unittest.skipUnless(WINDOWS and shutil.which("powershell"), "Windows PowerShell only")
    def test_dash_p_dash_d_dash_v_reach_the_core_untouched(self):
        """[CmdletBinding()] bound -p/-d/-v to common parameters and swallowed the prompt."""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "cortex"))
            echo = os.path.join(d, "echoargs.cmd")
            with open(echo, "w", encoding="ascii") as fh:
                fh.write('@echo off\r\n:l\r\nif "%~1"=="" goto :eof\r\necho ARG[%~1]\r\nshift\r\ngoto l\r\n')
            env = dict(os.environ, CORTEX_HOME=d, CORTEX_PYTHON=echo)
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 os.path.join(PROJECT_DIR, "bin", "claude.ps1"), "-p", "hello world", "-d", "-v", "--model", "x"],
                capture_output=True, text=True, env=env, timeout=120)
        received = [line for line in result.stdout.splitlines() if line.startswith("ARG[")]
        self.assertEqual(received, ["ARG[-m]", "ARG[cortex]", "ARG[-p]", "ARG[hello world]",
                                    "ARG[-d]", "ARG[-v]", "ARG[--model]", "ARG[x]"], result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
