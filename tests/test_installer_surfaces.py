#!/usr/bin/env python3
"""
The installer, run for real against a throwaway home.

This is the answer to "how do I test an installer on the machine that is running Claude?":
every variable that decides where it writes (HOME, USERPROFILE, APPDATA, LOCALAPPDATA) points
at a temp folder, the sandbox flag is on, and - on Windows - the REAL user PATH in the
registry is read before and after to prove it was not touched.
"""

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


if __name__ == "__main__":
    unittest.main()
