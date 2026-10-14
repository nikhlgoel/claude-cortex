#!/usr/bin/env python3
"""
The installer, run for real against a throwaway home.

This is the answer to "how do I test an installer on the machine that is running Claude?":
every variable that decides where it writes (HOME, USERPROFILE, APPDATA, LOCALAPPDATA) points
at a temp folder, the sandbox flag is on, and - on Windows - the REAL user PATH in the
registry is read before and after to prove it was not touched.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(PROJECT_DIR, "install.py")
WINDOWS = os.name == "nt"


def real_user_path():
    """The real HKCU Environment PATH (read-only), or None off Windows."""
    if not WINDOWS:
        return None
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as key:
        return winreg.QueryValueEx(key, "Path")[0]


class InstallerSandbox(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cortex-inst-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.home = os.path.join(self.root, "home")
        self.roaming = os.path.join(self.root, "roaming")
        self.local = os.path.join(self.root, "local")
        for folder in (self.home, self.roaming, self.local):
            os.makedirs(folder)
        self.path_before = real_user_path()

    def env(self):
        env = dict(os.environ, HOME=self.home, USERPROFILE=self.home, APPDATA=self.roaming,
                   LOCALAPPDATA=self.local, CORTEX_SANDBOX="1", PYTHONUTF8="1",
                   PYTHONDONTWRITEBYTECODE="1")
        for name in ("CLAUDECODE", "CLAUDE_CONFIG_DIR", "CLAUDE_PROFILE", "CORTEX_PROFILES_DIR"):
            env.pop(name, None)
        return env

    def install(self, *args):
        return subprocess.run([sys.executable, INSTALL, *args], env=self.env(), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=240,
                              stdin=subprocess.DEVNULL)

    def desktop_config(self, folder="Claude"):
        return os.path.join(self.roaming, folder, "claude_desktop_config.json")

    def make_desktop_folder(self, folder="Claude"):
        os.makedirs(os.path.join(self.roaming, folder), exist_ok=True)

    def adopt_desktop(self, name, folder):
        os.makedirs(folder, exist_ok=True)
        profiles = os.path.join(self.home, ".claude-profiles")
        os.makedirs(profiles, exist_ok=True)
        path = os.path.join(profiles, "registry.json")
        data = {"schema": 1, "profiles": {}}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        data["profiles"][name] = {"config_dir": None, "desktop_dir": folder, "surfaces": ["desktop"],
                                  "adopted": "2026-10-12"}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def tearDown(self):
        if WINDOWS:
            self.assertEqual(real_user_path(), self.path_before,
                             "the installer changed the REAL user PATH in the registry")


class TestSurfaceChoice(InstallerSandbox):
    def test_a_dry_run_writes_nothing(self):
        result = self.install("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.listdir(self.home), [])

    def test_the_default_is_terminal_only_and_leaves_desktop_alone(self):
        self.make_desktop_folder()
        result = self.install("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.exists(self.desktop_config()),
                         "Desktop config was written although Desktop was not chosen")
        self.assertTrue(os.path.isdir(os.path.join(self.home, ".claude", "cortex-core", "cortex")))

    def test_choosing_desktop_registers_the_tools_in_an_existing_folder_only(self):
        self.make_desktop_folder()
        result = self.install("--yes", "--surfaces", "terminal,desktop")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(self.desktop_config(), encoding="utf-8") as fh:
            servers = json.load(fh)["mcpServers"]
        self.assertIn("claude-cortex", servers)

    def test_no_desktop_folder_is_ever_invented(self):
        """The old installer created Claude-profile-1 and -2 and wrote config into them."""
        result = self.install("--yes", "--surfaces", "desktop")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(os.listdir(self.roaming), [])

    def test_an_adopted_desktop_folder_is_found_through_the_registry(self):
        studio = os.path.join(self.root, "Claude", "Profiles", "Studio")
        self.adopt_desktop("studio", studio)
        result = self.install("--yes", "--surfaces", "desktop")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(os.path.join(studio, "claude_desktop_config.json"), encoding="utf-8") as fh:
            self.assertIn("claude-cortex", json.load(fh)["mcpServers"])

    def test_an_existing_desktop_config_keeps_everything_else(self):
        self.make_desktop_folder()
        with open(self.desktop_config(), "w", encoding="utf-8") as fh:
            json.dump({"theme": "dark", "mcpServers": {"mine": {"command": "x"}}}, fh)
        self.install("--yes", "--surfaces", "desktop")
        with open(self.desktop_config(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["theme"], "dark")
        self.assertIn("mine", data["mcpServers"])
        self.assertIn("claude-cortex", data["mcpServers"])
        self.assertTrue(os.path.exists(self.desktop_config() + ".bak"))

    def test_an_unparseable_desktop_config_is_left_exactly_as_it_was(self):
        self.make_desktop_folder()
        with open(self.desktop_config(), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        self.install("--yes", "--surfaces", "desktop")
        with open(self.desktop_config(), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{ not json")

    def test_installing_twice_does_not_rewrite_an_up_to_date_desktop_config(self):
        self.make_desktop_folder()
        self.install("--yes", "--surfaces", "desktop")
        first = os.stat(self.desktop_config()).st_mtime_ns
        self.install("--yes", "--surfaces", "desktop")
        self.assertEqual(os.stat(self.desktop_config()).st_mtime_ns, first)

    def test_an_unknown_surface_is_refused_before_anything_is_installed(self):
        result = self.install("--yes", "--surfaces", "toaster")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(os.listdir(self.home), [])

    def test_ide_is_a_pointer_not_a_silent_settings_rewrite(self):
        result = self.install("--yes", "--surfaces", "ide")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("cc ide apply", result.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.roaming, "Code")))


class TestNoNetwork(unittest.TestCase):
    def test_the_installer_never_downloads_anything(self):
        """An installer that fetches and runs an executable unasked is a supply-chain hole,
        and it made every test run hit the network. Keep the capability out of the source."""
        with open(INSTALL, encoding="utf-8") as fh:
            source = fh.read()
        for needle in ("urllib", "urlretrieve", "urlopen", "requests", "curl ", "wget"):
            self.assertNotIn(needle, source, needle)

    def test_a_missing_claude_is_explained_not_downloaded(self):
        with tempfile.TemporaryDirectory(prefix="cortex-nodl-") as root:
            home = os.path.join(root, "home")
            os.makedirs(home)
            env = dict(os.environ, HOME=home, USERPROFILE=home, APPDATA=os.path.join(root, "r"),
                       LOCALAPPDATA=os.path.join(root, "l"), CORTEX_SANDBOX="1",
                       PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
            env["PATH"] = os.path.dirname(sys.executable)   # no claude anywhere on PATH
            proc = subprocess.run([sys.executable, INSTALL, "--yes", "--surfaces", "terminal"],
                                  env=env, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120, stdin=subprocess.DEVNULL)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("Cortex does not download programs", proc.stdout)
            self.assertFalse(os.path.exists(os.path.join(home, ".local", "bin", "claude.real.exe")))
            self.assertFalse(os.path.exists(os.path.join(home, ".local", "bin", "claude.real")))


class TestTypedPrompt(unittest.TestCase):
    """The typed confirmation needs a terminal, which a subprocess test cannot provide."""

    def run_prompt(self, answer):
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location("cortex_install_under_test", INSTALL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        env = {k: v for k, v in os.environ.items() if k != "CORTEX_SANDBOX"}
        fake_stdin = mock.Mock()
        fake_stdin.isatty.return_value = True
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True),                 mock.patch.object(sys, "argv", ["install.py"]),                 mock.patch.object(sys, "stdin", fake_stdin),                 mock.patch("builtins.input", return_value=answer),                 mock.patch("sys.stdout", out):
            try:
                result = module.confirm_install(__import__("pathlib").Path("b"),
                                                __import__("pathlib").Path("c"),
                                                __import__("pathlib").Path("p"))
            except SystemExit as stop:
                return stop.code, out.getvalue()
        return result, out.getvalue()

    def test_a_wrong_answer_stops_with_the_guard_code_not_success(self):
        code, text = self.run_prompt("yes please")
        self.assertEqual(code, 3, text)
        self.assertIn("Nothing was changed", text)

    def test_the_exact_word_continues(self):
        result, _ = self.run_prompt("INSTALL")
        self.assertIs(result, True)


class TestArguments(InstallerSandbox):
    def test_an_unknown_flag_is_refused_and_nothing_is_installed(self):
        for flag in ("--profiles=work", "--dry_run", "--surface"):
            result = self.install("--yes", flag)
            self.assertEqual(result.returncode, 2, flag)
            self.assertIn("Unknown option", result.stdout)
        self.assertEqual(os.listdir(self.home), [])

    def test_surfaces_without_a_value_is_refused(self):
        result = self.install("--yes", "--surfaces")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(os.listdir(self.home), [])

    def test_help_prints_usage_and_changes_nothing(self):
        result = self.install("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: install.py", result.stdout)
        self.assertEqual(os.listdir(self.home), [])

    def test_the_equals_form_of_surfaces_is_accepted(self):
        result = self.install("--yes", "--surfaces=terminal")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_without_an_operator_or_opt_in_it_stops_with_the_guard_exit_code(self):
        env = self.env()
        env.pop("CORTEX_SANDBOX")
        proc = subprocess.run([sys.executable, INSTALL], env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60,
                              stdin=subprocess.DEVNULL)
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertEqual(os.listdir(self.home), [])


class TestInteractiveChoice(unittest.TestCase):
    """The question the installer asks when --surfaces is not given."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cortex_install_under_test", INSTALL)
        cls.install = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.install)

    def ask(self, answer, argv=("install.py",), tty=True, sandbox=False):
        from unittest import mock
        import io
        env = {"CORTEX_SANDBOX": "1"} if sandbox else {}
        out = io.StringIO()
        with mock.patch.object(sys, "argv", list(argv)), mock.patch.dict(os.environ, env), \
                mock.patch.object(sys.stdin, "isatty", return_value=tty), \
                mock.patch("builtins.input", return_value=answer), mock.patch("sys.stdout", out):
            if not sandbox:
                os.environ.pop("CORTEX_SANDBOX", None)
            return self.install.choose_surfaces(), out.getvalue()

    def test_numbers_pick_surfaces(self):
        self.assertEqual(self.ask("1,3")[0], ["terminal", "desktop"])
        self.assertEqual(self.ask("2")[0], ["ide"])
        self.assertEqual(self.ask("1 2 3")[0], ["terminal", "ide", "desktop"])

    def test_pressing_enter_means_terminal_only(self):
        self.assertEqual(self.ask("")[0], ["terminal"])

    def test_an_answer_that_is_not_understood_says_so_instead_of_silently_choosing(self):
        surfaces, out = self.ask("desktop please")
        self.assertEqual(surfaces, ["terminal"])
        self.assertIn("Did not understand", out)
        self.assertIn("cc profile surfaces", out)

    def test_a_partly_understood_answer_keeps_what_it_understood_and_says_what_it_ignored(self):
        surfaces, out = self.ask("3 9")
        self.assertEqual(surfaces, ["desktop"])
        self.assertIn("Did not understand", out)

    def test_no_terminal_means_no_question(self):
        self.assertEqual(self.ask("1,2,3", tty=False)[0], ["terminal"])

    def test_the_flag_wins_over_asking(self):
        self.assertEqual(self.ask("1", argv=("install.py", "--surfaces", "desktop,ide"))[0],
                         ["ide", "desktop"])

    def test_yes_and_sandbox_never_ask(self):
        self.assertEqual(self.ask("3", argv=("install.py", "--yes"))[0], ["terminal"])
        self.assertEqual(self.ask("3", sandbox=True)[0], ["terminal"])


class TestPrimaryProfile(InstallerSandbox):
    def test_the_main_profile_is_still_created_for_a_fresh_install(self):
        self.install("--yes")
        self.assertTrue(os.path.isdir(os.path.join(self.home, ".claude-profiles", "main")))

    def test_it_can_be_declined(self):
        self.install("--yes", "--no-primary-profile")
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude-profiles", "main")))

    def test_it_is_skipped_once_real_profiles_are_adopted(self):
        self.adopt_desktop("studio", os.path.join(self.root, "studio"))
        result = self.install("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude-profiles", "main")))
        self.assertIn("Skipped the primary", result.stdout)


class TestBackupIsBounded(InstallerSandbox):
    """The first real run on a real machine zipped the whole of ~/.claude (3.5 GB, 13,000 files: conversation
    history and plugin caches the installer never touches), staged it a second time, and had not finished
    after 11 minutes. The backup now keeps what the installer can change and measures the rest."""

    def make_claude_home(self, big_mb=0):
        claude = os.path.join(self.home, ".claude")
        for rel, text in {"settings.json": '{"model": "opus"}', "CLAUDE.md": "# mine",
                          os.path.join("commands", "mine.md"): "my command",
                          os.path.join("rules", "r.md"): "my rule",
                          os.path.join("plugins", "cache", "junk.js"): "x" * 100,
                          os.path.join("commands", "node_modules", "dep.js"): "x" * 100,
                          os.path.join("projects", "p1", "small.jsonl"): "{}\n"}.items():
            full = os.path.join(claude, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(text)
        if big_mb:
            with open(os.path.join(claude, "projects", "p1", "big.jsonl"), "wb") as fh:
                fh.write(b"\0" * (big_mb * 1048576))
        with open(os.path.join(self.home, ".claude.json"), "w", encoding="utf-8") as fh:
            fh.write('{"oauthAccount": {"emailAddress": "synthetic@example.invalid"}}')
        return claude

    def backups(self):
        folder = os.path.join(self.home, ".claude-backups")
        archives = [n for n in os.listdir(folder) if n.startswith("claude-backup-")]
        staged = [n for n in os.listdir(folder) if n.startswith("staged_user_data_")]
        return folder, archives, staged

    def archive_names(self, folder, archive):
        import tarfile
        import zipfile
        path = os.path.join(folder, archive)
        if archive.endswith(".zip"):
            with zipfile.ZipFile(path) as zf:
                return [n.replace("\\", "/") for n in zf.namelist()]
        with tarfile.open(path) as tf:
            return tf.getnames()

    def test_the_archive_holds_what_the_installer_can_change_and_skips_caches(self):
        self.make_claude_home()
        result = self.install("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        folder, archives, _staged = self.backups()
        names = self.archive_names(folder, archives[0])
        for wanted in (".claude.json", ".claude/settings.json", ".claude/CLAUDE.md", ".claude/commands/mine.md",
                       ".claude/rules/r.md"):
            self.assertIn(wanted, names)
        self.assertFalse([n for n in names if "plugins/cache" in n or "node_modules" in n or "/projects/" in n], names)

    def test_a_small_history_is_still_staged(self):
        self.make_claude_home()
        self.install("--yes")
        folder, _archives, staged = self.backups()
        self.assertTrue(os.path.exists(os.path.join(folder, staged[0], "projects", "p1", "small.jsonl")))
        self.assertTrue(os.path.exists(os.path.join(folder, staged[0], ".claude.json")))

    def test_a_history_over_the_limit_is_left_in_place_and_says_so(self):
        claude = self.make_claude_home(big_mb=3)
        env = self.env()
        env["CORTEX_BACKUP_LIMIT_MB"] = "1"
        result = subprocess.run([sys.executable, INSTALL, "--yes"], env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=240, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Left projects in place", result.stdout)
        folder, archives, staged = self.backups()
        self.assertFalse(os.path.exists(os.path.join(folder, staged[0], "projects")))
        self.assertTrue(os.path.exists(os.path.join(claude, "projects", "p1", "big.jsonl")), "the original must be untouched")
        self.assertLess(os.path.getsize(os.path.join(folder, archives[0])), 1048576)

    def test_a_garbled_limit_falls_back_to_the_default(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cortex_install_under_test", INSTALL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for value, expected in (("abc", 300), ("", 300), ("0", 1), ("-5", 1), ("50", 50)):
            os.environ["CORTEX_BACKUP_LIMIT_MB"] = value
            self.addCleanup(os.environ.pop, "CORTEX_BACKUP_LIMIT_MB", None)
            self.assertEqual(module._backup_limit_mb(), expected, value)

    def test_measuring_a_folder_stops_early_instead_of_walking_all_of_it(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cortex_install_under_test2", INSTALL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        folder = os.path.join(self.root, "many")
        os.makedirs(folder)
        for i in range(50):
            with open(os.path.join(folder, "f%d.bin" % i), "wb") as fh:
                fh.write(b"\0" * 1048576)
        self.assertGreater(module._tree_size_mb(folder, 2), 2)
        self.assertLess(module._tree_size_mb(folder, 2), 50)       # it gave up long before counting them all


if __name__ == "__main__":
    unittest.main()
