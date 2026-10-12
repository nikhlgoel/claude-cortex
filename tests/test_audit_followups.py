#!/usr/bin/env python3
"""
Regression tests from a hands-on audit of the profile / surface / routing work.

Each test pins a defect that was REPRODUCED against real data or a real command before it was
fixed, not one imagined in advance:

* the default account's user config lives in ~/.claude.json, not ~/.claude/.claude.json;
* the IDE integration replaced the person's own environment variables, and would have set
  the very variable that must stay unset for the default account;
* `cc mcp add` rewrote the whole of a file Claude Code itself rewrites constantly;
* the guard did not watch ~/.claude.json, the most important file of the default account;
* small CLI papercuts (%VAR%, ~, trailing slash, silent renames, bad profile names).
"""

import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cortex import __main__ as cli  # noqa: E402
from cortex import capacity, guard, ide, mcp, paths, profiles, registry  # noqa: E402
from cortex.profiles import CortexError  # noqa: E402
from test_profiles_adopt import Sandbox  # noqa: E402


class DefaultAccount(Sandbox):
    """A sandbox whose ~/.claude and ~/.claude.json look like a real default account."""

    def setUp(self):
        super().setUp()
        self.native = os.path.join(self.home, ".claude")
        self.user_json = os.path.join(self.home, ".claude.json")
        with open(self.user_json, "w", encoding="utf-8") as fh:
            json.dump({"oauthAccount": {"emailAddress": "me@example.com"},
                       "mcpServers": {"aws-mcp": {"command": "x"}},
                       "cachedUsageUtilization": {"utilization": {"five_hour": {}}},
                       "numStartups": 5}, fh)
        registry.adopt("main", self.native)


class TestWhereTheUserConfigLives(DefaultAccount):
    def test_the_default_accounts_config_is_next_to_the_folder(self):
        self.assertEqual(paths.user_config_path(self.native), self.user_json)

    def test_every_other_profile_keeps_its_config_inside_its_folder(self):
        other = os.path.join(self.tmp, "accounts", "work")
        self.assertEqual(paths.user_config_path(other), os.path.join(other, ".claude.json"))

    def test_the_default_accounts_email_is_found(self):
        self.assertEqual(profiles.profile_email("main"), "me@example.com")

    def test_the_default_accounts_usage_cache_is_found(self):
        self.assertNotEqual(capacity.inspect("main", check_auth=False)["detail"],
                            "no usage data recorded yet")

    def test_the_mcp_servers_of_the_default_account_are_read_from_the_right_file(self):
        self.assertEqual(mcp._registered_servers("main"), {"aws-mcp"})

    def test_a_stray_inner_file_is_not_mistaken_for_the_real_config(self):
        with open(os.path.join(self.native, ".claude.json"), "w", encoding="utf-8") as fh:
            json.dump({"mcpServers": {"wrong": {}}}, fh)
        self.assertEqual(mcp._registered_servers("main"), {"aws-mcp"})


class TestIdeIntegration(DefaultAccount):
    def setUp(self):
        super().setUp()
        self.settings = os.path.join(self.tmp, "ide-settings.json")
        self.fake = [{"label": "Fake IDE", "extensions": ["x"], "stale": False,
                      "settings_path": self.settings}]
        work = os.path.join(self.tmp, "accounts", "work")
        os.makedirs(work)
        registry.adopt("work", work)
        self.work = work

    def write_settings(self, data):
        with open(self.settings, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def read_settings(self):
        with open(self.settings, encoding="utf-8") as fh:
            return json.load(fh)

    def apply(self, profile):
        with mock.patch.object(ide, "detect", return_value=self.fake), mock.patch("builtins.print"):
            return ide.apply(profile, dry_run=False)

    def test_the_default_account_never_gets_a_config_dir_set(self):
        self.assertEqual(ide.plan("main")["claudeCode.environmentVariables"], [])

    def test_other_profiles_get_both_variables_with_the_same_string(self):
        env = {e["name"]: e["value"] for e in ide.plan("work")["claudeCode.environmentVariables"]}
        self.assertEqual(env, {"CLAUDE_CONFIG_DIR": self.work, "CLAUDE_SECURESTORAGE_CONFIG_DIR": self.work})

    def test_the_persons_own_environment_variables_survive_an_apply(self):
        mine = {"name": "HTTPS_PROXY", "value": "http://proxy:3128"}
        self.write_settings({"editor.fontSize": 14, "claudeCode.environmentVariables": [mine]})
        self.apply("work")
        data = self.read_settings()
        self.assertEqual(data["editor.fontSize"], 14)
        self.assertIn(mine, data["claudeCode.environmentVariables"])
        self.assertIn("CLAUDE_CONFIG_DIR", [e["name"] for e in data["claudeCode.environmentVariables"]])

    def test_switching_to_the_default_account_clears_only_cortexs_entries(self):
        mine = {"name": "HTTPS_PROXY", "value": "http://proxy:3128"}
        self.write_settings({"claudeCode.environmentVariables": [mine]})
        self.apply("work")
        self.apply("main")
        self.assertEqual(self.read_settings()["claudeCode.environmentVariables"], [mine])

    def test_applying_twice_is_a_no_op(self):
        self.write_settings({})
        self.apply("work")
        first = os.stat(self.settings).st_mtime_ns
        out = io.StringIO()
        with mock.patch.object(ide, "detect", return_value=self.fake), mock.patch("sys.stdout", out):
            ide.apply("work", dry_run=False)
        self.assertIn("already configured", out.getvalue())
        self.assertEqual(os.stat(self.settings).st_mtime_ns, first)

    def test_an_unknown_profile_is_an_error_not_a_write(self):
        self.write_settings({"a": 1})
        with mock.patch.object(ide, "detect", return_value=self.fake), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(ide.apply("ghost", dry_run=False), 1)
            self.assertEqual(ide.check("ghost"), 1)
        self.assertEqual(self.read_settings(), {"a": 1})


class TestMcpRegistration(DefaultAccount):
    def fake_run(self, rc=0):
        return mock.patch.object(mcp.proc, "run",
                                 return_value=subprocess.CompletedProcess([], rc, "ok", ""))

    def test_the_cortex_server_is_registered_through_claude_not_by_rewriting_the_config(self):
        with open(self.user_json, "rb") as fh:
            before = fh.read()
        with mock.patch.object(mcp, "_server_path", return_value="/x/cortex-mcp.py"), \
                mock.patch.object(mcp.binary, "find", return_value="/bin/claude"), \
                self.fake_run() as run, mock.patch("builtins.print"):
            self.assertEqual(mcp.cmd_add("main"), 0)
        command = run.call_args[0][0]
        self.assertEqual(command[:6], ["/bin/claude", "mcp", "add", "--scope", "user", "cortex"])
        self.assertEqual(command.count("mcp"), 1, "the subcommand was doubled: claude mcp mcp add")
        with open(self.user_json, "rb") as fh:
            self.assertEqual(fh.read(), before, "Cortex rewrote ~/.claude.json itself")
        self.assertNotIn("CLAUDE_CONFIG_DIR", run.call_args.kwargs["env"])

    def test_removal_only_runs_when_it_is_registered(self):
        with self.fake_run() as run, mock.patch("builtins.print"):
            self.assertEqual(mcp.cmd_remove("main"), 0)
        run.assert_not_called()

    def test_a_profile_that_does_not_exist_is_rejected_up_front(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err), self.fake_run() as run:
            self.assertEqual(mcp.main(["add", "graphify", "ghost", "--dry-run"]), 1)
        run.assert_not_called()
        self.assertIn("does not exist", err.getvalue())

    def test_a_failed_registration_is_reported(self):
        with mock.patch.object(mcp, "_server_path", return_value="/x/cortex-mcp.py"), \
                mock.patch.object(mcp.binary, "find", return_value="/bin/claude"), \
                self.fake_run(rc=1), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(mcp.cmd_add("main"), 1)

    def test_executables_are_passed_with_native_separators(self):
        if os.name != "nt":
            self.skipTest("native separators matter on Windows")
        self.assertEqual(mcp._native("C:/tools/bin/graphify-mcp.EXE"), "C:\\tools\\bin\\graphify-mcp.EXE")
        self.assertIsNone(mcp._native(None))


class TestGuardWatchesTheDefaultAccountsConfig(DefaultAccount):
    def snap(self):
        return guard.snapshot("t", roots=[self.user_json])

    def rewrite(self, **changes):
        with open(self.user_json, encoding="utf-8") as fh:
            data = json.load(fh)
        data.update(changes)
        with open(self.user_json, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_the_file_is_watched_by_default(self):
        self.assertIn(self.user_json, guard.default_roots())

    def test_a_removed_mcp_server_is_detected_and_named(self):
        self.snap()
        self.rewrite(mcpServers={})
        ok, result = guard.verify("t")
        self.assertFalse(ok)
        self.assertIn("mcpServers", " ".join(result["changed"]))

    def test_a_changed_account_identity_is_detected(self):
        self.snap()
        self.rewrite(oauthAccount={"emailAddress": "someone@else.com"})
        self.assertFalse(guard.verify("t")[0])

    def test_everyday_churn_in_the_same_file_is_not_a_failure(self):
        self.snap()
        self.rewrite(numStartups=99, cachedUsageUtilization={"utilization": {"five_hour": {"pct": 50}}},
                     projects={"/p": {"trusted": True}})
        ok, result = guard.verify("t")
        self.assertTrue(ok, result)

    def test_neither_the_email_nor_the_server_commands_are_stored_in_the_snapshot(self):
        info = self.snap()
        with open(info["path"], encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("me@example.com", text)
        self.assertNotIn("aws-mcp", text)

    def test_a_missing_file_is_reported_rather_than_ignored(self):
        self.snap()
        os.unlink(self.user_json)
        ok, result = guard.verify("t")
        self.assertFalse(ok)
        self.assertTrue(result["missing_roots"])


class TestPastedPaths(Sandbox):
    def test_a_trailing_slash_is_removed_and_said_so(self):
        folder = self.make_account("a")
        cleaned, notes = registry.clean_path(folder + os.sep)
        self.assertEqual(cleaned, folder)
        self.assertTrue(any("trailing" in n for n in notes))

    def test_adopt_accepts_a_pasted_trailing_slash_and_stores_it_clean(self):
        folder = self.make_account("a")
        registry.adopt("alpha", folder + os.sep)
        self.assertEqual(paths.profile_dir("alpha"), folder)

    def test_a_drive_root_keeps_its_slash(self):
        if os.name != "nt":
            self.skipTest("drive roots")
        self.assertEqual(registry.clean_path("C:\\")[0], "C:\\")

    def test_environment_variables_are_expanded_once(self):
        folder = self.make_account("a")
        with mock.patch.dict(os.environ, {"CORTEX_TEST_ACCOUNT": folder}):
            token = "%CORTEX_TEST_ACCOUNT%" if os.name == "nt" else "$CORTEX_TEST_ACCOUNT"
            cleaned, notes = registry.clean_path(token)
            self.assertEqual(cleaned, folder)
            registry.adopt("alpha", token)
        self.assertEqual(paths.profile_dir("alpha"), folder)
        self.assertTrue(notes)

    def test_an_unset_variable_is_a_clear_error(self):
        os.environ.pop("CORTEX_NOT_SET_ANYWHERE", None)
        token = "%CORTEX_NOT_SET_ANYWHERE%" if os.name == "nt" else "${CORTEX_NOT_SET_ANYWHERE}"
        with self.assertRaises(CortexError):
            registry.clean_path(token + os.sep + "x")

    def test_a_tilde_is_expanded(self):
        self.assertEqual(registry.clean_path("~")[0], os.path.expanduser("~"))

    def test_quotes_pasted_around_a_path_are_dropped(self):
        folder = self.make_account("a")
        self.assertEqual(registry.clean_path(f'"{folder}"')[0], folder)

    def test_a_normal_path_is_returned_untouched(self):
        folder = self.make_account("a")
        self.assertEqual(registry.clean_path(folder), (folder, []))


class TestRepoHygiene(unittest.TestCase):
    def test_python_sources_use_one_line_ending(self):
        """Two files were all-CRLF in an otherwise LF project: git warned and patches missed."""
        crlf = []
        for top in ("cortex", "scripts", "tests"):
            for base, dirs, files in os.walk(os.path.join(PROJECT_DIR, top)):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "sandbox")]
                for name in files:
                    if name.endswith(".py"):
                        path = os.path.join(base, name)
                        with open(path, "rb") as fh:
                            if b"\r\n" in fh.read():
                                crlf.append(os.path.relpath(path, PROJECT_DIR))
        with open(os.path.join(PROJECT_DIR, "install.py"), "rb") as fh:
            if b"\r\n" in fh.read():
                crlf.append("install.py")
        self.assertEqual(crlf, [], "files with CRLF line endings")

    def test_every_version_string_agrees_and_the_changelog_covers_it(self):
        """The release script, `cc version`, the MCP server and the package all report one number."""
        import re
        found = {}
        for rel, pattern in (("cortex/__init__.py", r'^__version__\s*=\s*"([^"]+)"'),
                             ("cortex/__main__.py", r'^VERSION\s*=\s*"([^"]+)"'),
                             ("scripts/cortex-mcp.py", r'^SERVER_VERSION\s*=\s*"([^"]+)"')):
            with open(os.path.join(PROJECT_DIR, rel), encoding="utf-8") as fh:
                match = re.search(pattern, fh.read(), re.MULTILINE)
            self.assertIsNotNone(match, rel)
            found[rel] = match.group(1)
        self.assertEqual(len(set(found.values())), 1, found)
        version = next(iter(found.values()))
        with open(os.path.join(PROJECT_DIR, "CHANGELOG.md"), encoding="utf-8") as fh:
            self.assertIn("## " + version, fh.read(), "CHANGELOG has no entry for " + version)


class TestCommandMessages(Sandbox):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            rc = cli.main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def test_a_silently_adjusted_profile_name_is_announced(self):
        rc, out, _ = self.run_cli("profile", "adopt", "Work Acct", "--config", self.make_account("a"))
        self.assertEqual(rc, 0)
        self.assertIn("using 'workacct' (adjusted from 'Work Acct')", out)

    def test_a_cleaned_path_is_announced(self):
        rc, out, _ = self.run_cli("profile", "adopt", "work", "--config", self.make_account("a") + os.sep)
        self.assertEqual(rc, 0)
        self.assertIn("trailing slash", out)

    def test_showing_a_profile_that_does_not_exist_is_an_error(self):
        rc, _out, err = self.run_cli("profile", "show", "nonexistent")
        self.assertEqual(rc, 1)
        self.assertIn("does not exist", err)

    def test_verify_without_a_name_explains_the_usage(self):
        rc, _out, err = self.run_cli("profile", "verify")
        self.assertEqual(rc, 2)
        self.assertIn("Usage", err)

    def test_adopt_usage_shows_an_example(self):
        rc, _out, err = self.run_cli("profile", "adopt")
        self.assertEqual(rc, 2)
        self.assertIn("e.g.", err)

    def test_a_command_name_suggests_an_alternative(self):
        rc, _out, err = self.run_cli("profile", "adopt", "local", "--config", self.make_account("a"))
        self.assertEqual(rc, 2)
        self.assertIn("local-acct", err)


if __name__ == "__main__":
    unittest.main()
