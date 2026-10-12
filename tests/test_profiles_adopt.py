#!/usr/bin/env python3
"""
Tests for adopting existing Claude folders in place, and for the guard that proves a
change left real data alone.

The promise being tested: registering a folder never moves, copies, links, rewrites or
deletes anything in it. Every test runs against temp directories.
"""

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from cortex import __main__ as cli  # noqa: E402
from cortex import desktop, doctor, guard, paths, profiles, registry  # noqa: E402
from cortex.profiles import CortexError  # noqa: E402

WINDOWS = os.name == "nt"


def tree_hash(root):
    """Hash of every file's relative path and content: any change alters it."""
    digest = hashlib.sha256()
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(base, name)
            digest.update(os.path.relpath(path, root).encode("utf-8"))
            with open(path, "rb") as fh:
                digest.update(fh.read())
    return digest.hexdigest()


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cortex-adopt-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.profiles_root = os.path.join(self.tmp, "profiles")
        os.makedirs(os.path.join(self.home, ".claude"))
        env = {"HOME": self.home, "USERPROFILE": self.home, "CORTEX_PROFILES_DIR": self.profiles_root,
               "APPDATA": os.path.join(self.tmp, "roaming"), "LOCALAPPDATA": os.path.join(self.tmp, "local")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("CLAUDE_PROFILE", "CLAUDECODE", "CLAUDE_CONFIG_DIR"):
            os.environ.pop(name, None)
        profiles._AUTH_CACHE.clear()

    def make_account(self, name, *, login=True):
        """A folder shaped like a real account: login, settings, history, projects."""
        folder = os.path.join(self.tmp, "accounts", name)
        os.makedirs(os.path.join(folder, "projects", "p1"))
        os.makedirs(os.path.join(folder, "skills"))
        files = {"settings.json": '{"theme": "dark", "hooks": {}}', "history.jsonl": "{}\n",
                 ".claude.json": '{"hasCompletedOnboarding": true}',
                 os.path.join("projects", "p1", "t.jsonl"): "{}\n",
                 os.path.join("skills", "s.md"): "# skill"}
        if login:
            files[".credentials.json"] = '{"token": "SECRET-DO-NOT-READ"}'
        for rel, text in files.items():
            with open(os.path.join(folder, rel), "w", encoding="utf-8") as fh:
                fh.write(text)
        return folder


# =============================================================================
# the registry
# =============================================================================

class TestRegistry(Sandbox):
    def test_adopting_records_the_path_and_changes_nothing_in_the_folder(self):
        folder = self.make_account("a")
        before = tree_hash(folder)
        registry.adopt("alpha", folder)
        self.assertEqual(tree_hash(folder), before)
        self.assertTrue(registry.is_adopted("alpha"))

    def test_the_path_is_stored_verbatim_not_re_canonicalised(self):
        folder = self.make_account("a")
        # A spelling that canonicalisation WOULD rewrite (a '..' hop); the registry must not.
        os.makedirs(os.path.join(os.path.dirname(folder), "hop"), exist_ok=True)
        odd = os.path.join(os.path.dirname(folder), "hop", "..", os.path.basename(folder))
        self.assertNotEqual(paths.canonical_dir(odd), odd)
        registry.adopt("alpha", odd)
        self.assertEqual(paths.profile_dir("alpha"), odd,
                         "the login is tied to the exact path string; it must not be rewritten")

    def test_a_missing_folder_is_refused_and_never_created(self):
        ghost = os.path.join(self.tmp, "nope")
        with self.assertRaises(CortexError):
            registry.adopt("alpha", ghost)
        self.assertFalse(os.path.exists(ghost))

    def test_relative_paths_are_refused(self):
        with self.assertRaises(CortexError):
            registry.adopt("alpha", "relative/dir")

    def test_a_pasted_trailing_slash_is_cleaned_not_stored(self):
        folder = self.make_account("a")
        registry.adopt("alpha", folder + os.sep)
        self.assertEqual(paths.profile_dir("alpha"), folder)

    def test_a_folder_inside_the_cortex_profiles_root_is_refused(self):
        os.makedirs(os.path.join(self.profiles_root, "managed"))
        with self.assertRaises(CortexError):
            registry.adopt("alpha", os.path.join(self.profiles_root, "managed"))

    def test_one_folder_cannot_be_registered_twice_or_a_name_reused(self):
        folder, other = self.make_account("a"), self.make_account("b")
        registry.adopt("alpha", folder)
        with self.assertRaises(CortexError):
            registry.adopt("beta", folder)
        with self.assertRaises(CortexError):
            registry.adopt("alpha", other)

    def test_forgetting_unregisters_without_touching_the_folder(self):
        folder = self.make_account("a")
        registry.adopt("alpha", folder)
        before = tree_hash(folder)
        self.assertTrue(registry.forget("alpha"))
        self.assertFalse(registry.is_adopted("alpha"))
        self.assertEqual(tree_hash(folder), before)

    def test_a_damaged_registry_raises_instead_of_silently_forgetting_profiles(self):
        os.makedirs(self.profiles_root)
        path = os.path.join(self.profiles_root, "registry.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        with self.assertRaises(CortexError):
            registry.load()
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{ not json")

    def test_a_desktop_only_entry_leaves_the_cli_side_managed(self):
        desktop_dir = self.make_account("studio-desktop", login=False)
        registry.adopt("studio", None, desktop_dir)
        self.assertFalse(registry.is_adopted("studio"))
        self.assertEqual(paths.profile_dir("studio"),
                         paths.canonical_dir(os.path.join(self.profiles_root, "studio")))
        self.assertIn("studio", profiles.list_profiles())

    def test_unknown_surfaces_are_refused(self):
        with self.assertRaises(CortexError):
            registry.adopt("alpha", self.make_account("a"), surfaces=["toaster"])


# =============================================================================
# nothing writes into an adopted folder
# =============================================================================

class TestAdoptedFoldersAreLeftAlone(Sandbox):
    def setUp(self):
        super().setUp()
        self.folder = self.make_account("a")
        registry.adopt("alpha", self.folder)
        self.before = tree_hash(self.folder)
        # a shared settings file that ensure_structure would normally copy in
        with open(os.path.join(self.home, ".claude", "settings.json"), "w", encoding="utf-8") as fh:
            fh.write('{"shared": true}')

    def test_listing_includes_adopted_and_managed_profiles(self):
        os.makedirs(os.path.join(self.profiles_root, "managed"))
        self.assertEqual(profiles.list_profiles(), ["alpha", "managed"])

    def test_ensure_structure_creates_links_and_copies_nothing(self):
        self.assertEqual(profiles.ensure_structure("alpha", "synced"), self.folder)
        self.assertEqual(tree_hash(self.folder), self.before)

    def test_the_mode_of_an_adopted_profile_is_adopted(self):
        self.assertEqual(profiles.profile_mode("alpha"), "adopted")

    def test_seeding_identity_never_rewrites_an_adopted_dot_claude_json(self):
        with mock.patch.object(profiles, "auth_status",
                               return_value={"loggedIn": True, "email": "me@example.com"}):
            self.assertTrue(profiles.seed_identity("alpha"))
        self.assertEqual(tree_hash(self.folder), self.before)

    def test_removing_an_adopted_profile_only_unregisters_it(self):
        with mock.patch("builtins.print"):
            self.assertEqual(profiles.remove("alpha"), 0)
        self.assertEqual(tree_hash(self.folder), self.before)
        self.assertTrue(os.path.isfile(os.path.join(self.folder, ".credentials.json")))
        self.assertFalse(registry.is_adopted("alpha"))

    def test_doctor_repair_does_not_rewrite_an_adopted_profiles_settings(self):
        with open(os.path.join(self.folder, "settings.json"), "w", encoding="utf-8") as fh:
            fh.write('{"autoCompactWindow": 5}')           # exactly what repair would "fix"
        before = tree_hash(self.folder)
        with mock.patch("builtins.print"):
            doctor._repair()
        self.assertEqual(tree_hash(self.folder), before)

    def test_launch_and_status_resolve_to_the_adopted_folder(self):
        self.assertEqual(paths.profile_dir("alpha"), self.folder)

    def test_verify_reports_a_login_without_writing(self):
        out = io.StringIO()
        with mock.patch.object(profiles, "auth_status",
                               return_value={"loggedIn": True, "email": "me@example.com"}), \
                mock.patch("sys.stdout", out):
            self.assertEqual(cli.main(["profile", "verify", "alpha"]), 0)
        self.assertIn("me@example.com", out.getvalue())
        self.assertEqual(tree_hash(self.folder), self.before)


# =============================================================================
# the guard
# =============================================================================

class TestGuard(Sandbox):
    def setUp(self):
        super().setUp()
        self.folder = self.make_account("a")

    def snap(self):
        return guard.snapshot("t", roots=[self.folder])

    def test_an_untouched_folder_verifies_clean(self):
        self.snap()
        ok, result = guard.verify("t")
        self.assertTrue(ok, result)

    def test_a_changed_protected_file_is_a_failure(self):
        self.snap()
        with open(os.path.join(self.folder, "settings.json"), "w", encoding="utf-8") as fh:
            fh.write('{"theme": "light"}')
        ok, result = guard.verify("t")
        self.assertFalse(ok)
        self.assertTrue(any(p.endswith("settings.json") for p in result["changed"]))

    def test_added_and_removed_protected_files_are_failures(self):
        self.snap()
        os.unlink(os.path.join(self.folder, "skills", "s.md"))
        with open(os.path.join(self.folder, "new-setting.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        ok, result = guard.verify("t")
        self.assertFalse(ok)
        self.assertTrue(any(p.endswith("s.md") for p in result["removed"]))
        self.assertTrue(any(p.endswith("new-setting.json") for p in result["added"]))

    def test_normal_use_of_claude_does_not_fail_the_check(self):
        self.snap()
        with open(os.path.join(self.folder, "history.jsonl"), "a", encoding="utf-8") as fh:
            fh.write('{"more": 1}\n')
        with open(os.path.join(self.folder, "projects", "p1", "new.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        ok, result = guard.verify("t")
        self.assertTrue(ok, result)

    def test_a_replaced_credential_file_is_detected_without_reading_it(self):
        opened = []
        real_open = open

        def spy(path, *args, **kwargs):
            opened.append(os.fspath(path))
            return real_open(path, *args, **kwargs)

        with mock.patch("builtins.open", spy):
            self.snap()
        self.assertFalse(any(p.endswith(".credentials.json") for p in opened),
                         "the guard opened a credential file")
        with open(os.path.join(self.folder, ".credentials.json"), "w", encoding="utf-8") as fh:
            fh.write('{"token": "a-much-longer-replacement-token-value"}')
        ok, result = guard.verify("t")
        self.assertFalse(ok)
        self.assertTrue(any(p.endswith(".credentials.json") for p in result["changed"]))

    def test_a_vanished_folder_is_reported(self):
        self.snap()
        shutil.rmtree(self.folder)
        ok, result = guard.verify("t")
        self.assertFalse(ok)
        self.assertTrue(result["missing_roots"])

    def test_the_snapshot_is_stored_outside_the_watched_folder(self):
        self.assertFalse(self.snap()["path"].startswith(self.folder))

    def test_default_roots_include_registered_profile_folders(self):
        registry.adopt("alpha", self.folder)
        self.assertIn(self.folder, guard.default_roots())

    def test_cli_exit_codes(self):
        registry.adopt("alpha", self.folder)
        with mock.patch("builtins.print"):
            self.assertEqual(cli.main(["guard", "verify", "never-taken"]), 2)
            self.assertEqual(cli.main(["guard", "snapshot", "x"]), 0)
            self.assertEqual(cli.main(["guard", "verify", "x"]), 0)
            with open(os.path.join(self.folder, "settings.json"), "w", encoding="utf-8") as fh:
                fh.write("{}")
            self.assertEqual(cli.main(["guard", "verify", "x"]), 1)


# =============================================================================
# the Desktop surface
# =============================================================================

class TestDesktop(Sandbox):
    def test_the_user_data_dir_is_parsed_from_shortcut_arguments(self):
        quoted = desktop._USER_DATA.search('--user-data-dir="C:\\My Profiles\\Studio" --x')
        plain = desktop._USER_DATA.search("--user-data-dir=C:\\Claude\\Profiles\\Studio")
        self.assertEqual(quoted.group(2), "C:\\My Profiles\\Studio")
        self.assertEqual(plain.group(3), "C:\\Claude\\Profiles\\Studio")

    @unittest.skipUnless(WINDOWS, "Windows install layout")
    def test_the_newest_installed_version_is_used_numerically_not_alphabetically(self):
        base = os.path.join(os.environ["LOCALAPPDATA"], "AnthropicClaude")
        for version in ("app-1.9.0", "app-1.10.0", "app-1.2.0"):
            os.makedirs(os.path.join(base, version))
            with open(os.path.join(base, version, "claude.exe"), "w", encoding="utf-8") as fh:
                fh.write("")
        self.assertTrue(desktop.find_exe().endswith(os.path.join("app-1.10.0", "claude.exe")))

    def test_detection_finds_default_and_shortcut_folders_without_reading_them(self):
        default = os.path.join(os.environ["APPDATA"], "Claude")
        os.makedirs(default)
        studio = self.make_account("studio", login=False)
        veilabs = self.make_account("veilabs")
        fake = subprocess.CompletedProcess([], 0, f"Claude (Studio)|x.exe|--user-data-dir={studio}\n"
                                                  f'Claude (Veilabs)|x.exe|--user-data-dir="{veilabs}"\n'
                                                  "Claude|x.exe|\n", "")
        with mock.patch.object(desktop.os, "name", "nt"):
            found = {c["label"]: c for c in desktop.detect(lambda *a, **k: fake)}
        native = desktop._native
        self.assertEqual(found["Claude (Veilabs)"]["config_dir"], native(veilabs))   # has a CLI login
        self.assertIsNone(found["Claude (Studio)"]["config_dir"])                    # does not
        self.assertEqual(found["default"]["desktop_dir"], native(default))

    def test_suggested_names_drop_the_brand_word(self):
        self.assertEqual(desktop.suggest_name("Claude (Studio)"), "studio")
        self.assertEqual(desktop.suggest_name("Claude (Veilabs)"), "veilabs")
        self.assertEqual(desktop.suggest_name("default"), "default")
        self.assertEqual(desktop.suggest_name("Claude"), "profile")

    def test_launch_uses_the_profiles_own_data_folder_and_config_dir(self):
        folder = self.make_account("studio", login=False)
        cfg = self.make_account("studio-cli")
        registry.adopt("studio", cfg, folder)
        spawned = {}

        def fake_spawn(cmd, **kwargs):
            spawned.update(cmd=cmd, env=kwargs["env"])
            return mock.Mock(pid=4321)
        with mock.patch.object(desktop, "find_exe", return_value="C:\\app\\claude.exe"):
            pid = desktop.launch("studio", registry.lookup("studio"), spawn=fake_spawn)
        self.assertEqual(pid, 4321)
        self.assertEqual(spawned["cmd"], ["C:\\app\\claude.exe", f"--user-data-dir={folder}"])
        self.assertEqual(spawned["env"]["CLAUDE_CONFIG_DIR"], cfg)

    def test_the_config_dir_can_be_left_out(self):
        folder = self.make_account("studio", login=False)
        registry.adopt("studio", None, folder)
        os.makedirs(paths.profile_dir("studio"))     # the config folder EXISTS: only the opt-out can explain its absence
        spawned = {}
        with mock.patch.object(desktop, "find_exe", return_value="x"):
            desktop.launch("studio", registry.lookup("studio"), share_config=False,
                           spawn=lambda cmd, **kw: spawned.update(env=kw["env"]) or mock.Mock(pid=1))
        self.assertNotIn("CLAUDE_CONFIG_DIR", spawned["env"])

    def test_launch_explains_a_missing_app_or_folder(self):
        with mock.patch.object(desktop, "find_exe", return_value=None):
            with self.assertRaises(RuntimeError):
                desktop.launch("x", {"desktop_dir": self.tmp})
        with mock.patch.object(desktop, "find_exe", return_value="x"):
            with self.assertRaises(RuntimeError):
                desktop.launch("x", {"desktop_dir": os.path.join(self.tmp, "gone")})


# =============================================================================
# the commands
# =============================================================================

class TestCommands(Sandbox):
    def test_adopt_then_list_then_remove_leaves_the_folder_exactly_as_it_was(self):
        folder = self.make_account("a")
        before = tree_hash(folder)
        with mock.patch("builtins.print"):
            self.assertEqual(cli.main(["profile", "adopt", "alpha", "--config", folder]), 0)
            self.assertIn("alpha", profiles.list_profiles())
            self.assertEqual(cli.main(["profile", "remove", "alpha", "--yes"]), 0)
        self.assertEqual(tree_hash(folder), before)

    def test_a_command_name_cannot_be_adopted_as_a_profile(self):
        with mock.patch("builtins.print"):
            self.assertEqual(cli.main(["profile", "adopt", "local", "--config", self.make_account("a")]), 2)

    def test_adopt_needs_a_folder(self):
        with mock.patch("builtins.print"):
            self.assertEqual(cli.main(["profile", "adopt", "alpha"]), 2)

    def test_detect_prints_adopt_commands_and_changes_nothing(self):
        studio = self.make_account("studio", login=False)
        out = io.StringIO()
        before = tree_hash(studio)
        with mock.patch.object(desktop, "_shortcuts", return_value=[("Claude (Studio)", studio)]), \
                mock.patch("sys.stdout", out):
            self.assertEqual(cli.main(["profile", "detect"]), 0)
        self.assertIn("cc profile adopt", out.getvalue())
        self.assertEqual(tree_hash(studio), before)
        self.assertEqual(registry.load(), {})

    def test_surfaces_can_be_added_later_without_touching_the_account_data(self):
        folder = self.make_account("a")
        desktop_dir = self.make_account("a-desktop", login=False)
        before = (tree_hash(folder), tree_hash(desktop_dir))
        registry.adopt("alpha", folder, desktop_dir, surfaces=["terminal"])
        with mock.patch("builtins.print"):
            self.assertEqual(cli.main(["profile", "surfaces", "alpha", "terminal,desktop"]), 0)
        entry = registry.lookup("alpha")
        self.assertEqual(entry["surfaces"], ["terminal", "desktop"])
        # only the Desktop MCP config was added; nothing else in either folder changed
        self.assertTrue(os.path.isfile(os.path.join(desktop_dir, "claude_desktop_config.json")))
        os.unlink(os.path.join(desktop_dir, "claude_desktop_config.json"))
        self.assertEqual((tree_hash(folder), tree_hash(desktop_dir)), before)

    def test_surfaces_dry_run_records_and_writes_nothing(self):
        folder = self.make_account("a")
        desktop_dir = self.make_account("a-desktop", login=False)
        registry.adopt("alpha", folder, desktop_dir, surfaces=["terminal"])
        with mock.patch("builtins.print"):
            self.assertEqual(cli.main(["profile", "surfaces", "alpha", "desktop", "--dry-run"]), 0)
        self.assertEqual(registry.lookup("alpha")["surfaces"], ["terminal"])
        self.assertFalse(os.path.exists(os.path.join(desktop_dir, "claude_desktop_config.json")))

    def test_surfaces_rejects_unknown_names_and_unknown_profiles(self):
        registry.adopt("alpha", self.make_account("a"))
        with mock.patch("builtins.print"), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(cli.main(["profile", "surfaces", "alpha", "toaster"]), 2)
            self.assertEqual(cli.main(["profile", "surfaces", "ghost", "desktop"]), 2)

    def test_surfaces_are_shown_when_no_change_is_asked_for(self):
        registry.adopt("alpha", self.make_account("a"))
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(cli.main(["profile", "surfaces", "alpha"]), 0)
        self.assertIn("terminal", out.getvalue())

    def test_a_cortex_managed_profile_can_have_surfaces_too(self):
        os.makedirs(os.path.join(self.profiles_root, "managed"))
        with mock.patch("builtins.print"):
            self.assertEqual(cli.main(["profile", "surfaces", "managed", "terminal,ide"]), 0)
        self.assertEqual(registry.lookup("managed")["surfaces"], ["terminal", "ide"])
        self.assertFalse(registry.is_adopted("managed"))

    def test_desktop_and_guard_are_reserved_command_names(self):
        self.assertIn("desktop", cli.TOP_LEVEL_COMMANDS)
        self.assertIn("guard", cli.TOP_LEVEL_COMMANDS)

    def test_the_desktop_command_launches_a_registered_profile(self):
        folder = self.make_account("studio", login=False)
        registry.adopt("studio", None, folder)
        with mock.patch.object(desktop, "launch", return_value=99) as launch, mock.patch("builtins.print"):
            self.assertEqual(cli.main(["desktop", "studio", "--no-config-dir"]), 0)
        self.assertFalse(launch.call_args.kwargs["share_config"])
        with mock.patch("builtins.print"):
            self.assertEqual(cli.main(["desktop", "ghost"]), 1)


if __name__ == "__main__":
    unittest.main()
