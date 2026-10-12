#!/usr/bin/env python3
"""
Tests for tool routing hints, MCP registration of third-party servers, and the
native-default config folder rule.

Nothing here runs a real tool: availability is injected, subprocesses are faked, and every
folder is a temp directory.
"""

import importlib.util
import io
import json
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

from cortex import launcher, mcp, paths, profiles, routing  # noqa: E402


def load_module(relpath):
    path = os.path.join(PROJECT_DIR, relpath)
    spec = importlib.util.spec_from_file_location(
        os.path.basename(relpath).replace("-", "_").replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ALL_TOOLS = {"scrapling-mcp", "scrapling", "graphify-mcp", "graphify", "specify"}


def route(prompt, tools=ALL_TOOLS, ecc=True, graph=False, env=None):
    def which(name):
        return f"/bin/{name}" if name in tools else None

    def exists(path):
        if path.endswith("graph.json"):
            return graph
        return ecc and path.endswith("ecc")
    return routing.hint_for(prompt, "/work", which=which, exists=exists, env=env or {})


class TestRouting(unittest.TestCase):
    def test_scraping_prompts_point_at_scrapling(self):
        for prompt in ("scrape the product prices from this website into a CSV",
                       "write a crawler that follows every link on the docs site",
                       "extract the data from the page at that url using css selectors"):
            hint = route(prompt)
            self.assertIsNotNone(hint, prompt)
            self.assertIn("Scrapling", hint)

    def test_code_structure_questions_point_at_graphify(self):
        for prompt in ("who calls load_config across the whole repo",
                       "show me the dependency graph for the payments module",
                       "what is the impact of renaming the User class"):
            self.assertIn("Graphify", route(prompt) or "", prompt)

    def test_the_hint_says_whether_a_graph_already_exists(self):
        prompt = "who calls load_config across the whole repo"
        self.assertIn("no Graphify graph", route(prompt, graph=False))
        self.assertIn("graphify-out/graph.json", route(prompt, graph=True))
        self.assertNotIn("no Graphify graph", route(prompt, graph=True))

    def test_spec_kit_is_only_suggested_when_asked_for(self):
        self.assertIn("Spec Kit", route("use spec kit to plan the notification feature") or "")
        self.assertIsNone(route("add a new feature that sends notifications to users"))

    def test_review_and_security_use_the_ecc_agents(self):
        self.assertIn("ecc:code-reviewer", route("please do a code review of my changes in this branch"))
        self.assertIn("ecc:security-reviewer", route("run a security audit on the upload handler code"))

    def test_a_hint_is_never_given_for_a_tool_that_is_not_there(self):
        self.assertIsNone(route("scrape the prices from this website please", tools=set()))
        self.assertIsNone(route("who calls load_config across the whole repo", tools=set()))
        self.assertIsNone(route("please do a code review of my changes", ecc=False))

    def test_ordinary_prompts_get_nothing(self):
        for prompt in ("refactor the login function to use async await",
                       "explain how python decorators work with an example",
                       "fix the failing test in the utils module",
                       "rename this variable everywhere it is used in this file",
                       "write a function that sorts a list of dictionaries by date",
                       "why is my docker container exiting immediately"):
            self.assertIsNone(route(prompt), prompt)

    def test_short_and_slash_prompts_are_left_alone(self):
        self.assertIsNone(route("scrape this"))
        self.assertIsNone(route("/scrape the prices from this website into a file"))
        self.assertIsNone(route("!scrape the prices from this website into a file"))
        self.assertIsNone(route(""))
        self.assertIsNone(routing.hint_for(None))

    def test_the_first_matching_route_wins_and_only_one_hint_is_given(self):
        hint = route("scrape the review pages and do a code review of my changes too")
        self.assertIn("Scrapling", hint)
        self.assertNotIn("ecc:code-reviewer", hint)

    def test_it_can_be_switched_off(self):
        self.assertIsNone(route("scrape the prices from this website into a file",
                                env={"CORTEX_ROUTING": "off"}))

    def test_a_hint_is_short(self):
        for prompt in ("scrape the prices from this website into a file",
                       "who calls load_config across the whole repo"):
            self.assertLess(len(route(prompt)), 420, "hints cost tokens on every match")


class TestPromptHookIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hook = load_module("scripts/cortex-prompt-hook.py")

    def run_hook(self, payload, hint="HINT", raises=None):
        out = io.StringIO()
        patch = mock.patch.object(routing, "hint_for", side_effect=raises) if raises \
            else mock.patch.object(routing, "hint_for", return_value=hint)
        with patch, mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), mock.patch("sys.stdout", out):
            rc = self.hook.main()
        return rc, out.getvalue()

    def test_a_hint_is_added_as_context_and_the_prompt_is_never_blocked(self):
        rc, out = self.run_hook({"prompt": "scrape the prices from this website", "cwd": "/work"})
        self.assertEqual(rc, 0)
        data = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(data["hookEventName"], "UserPromptSubmit")
        self.assertEqual(data["additionalContext"], "HINT")

    def test_no_match_means_no_output_at_all(self):
        rc, out = self.run_hook({"prompt": "refactor this function to be shorter"}, hint=None)
        self.assertEqual((rc, out), (0, ""))

    def test_a_failure_inside_routing_never_breaks_the_prompt(self):
        rc, out = self.run_hook({"prompt": "scrape the prices from this website"}, raises=RuntimeError("boom"))
        self.assertEqual((rc, out), (0, ""))

    def test_cc_commands_are_still_intercepted_not_routed(self):
        with mock.patch.object(routing, "hint_for", side_effect=AssertionError("routed a /cc command")), \
                mock.patch.object(self.hook, "run_cortex", return_value="ok"), \
                mock.patch("sys.stdin", io.StringIO(json.dumps({"prompt": "/cc status"}))), \
                mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(self.hook.main(), 2)

    def test_the_hint_receives_the_working_folder(self):
        payload = json.dumps({"prompt": "who calls load_config here", "cwd": "/proj"})
        with mock.patch.object(routing, "hint_for", return_value=None) as hint, \
                mock.patch("sys.stdin", io.StringIO(payload)):
            self.hook.main()
        self.assertEqual(hint.call_args[0][1], "/proj")


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cortex-route-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".claude"))
        env = {"HOME": self.home, "USERPROFILE": self.home,
               "CORTEX_PROFILES_DIR": os.path.join(self.tmp, "profiles")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("CLAUDE_CONFIG_DIR", "CLAUDE_SECURESTORAGE_CONFIG_DIR", "CLAUDE_PROFILE", "CLAUDECODE"):
            os.environ.pop(name, None)
        profiles._AUTH_CACHE.clear()


class TestNativeDefaultFolder(Sandbox):
    def native(self):
        return os.path.join(self.home, ".claude")

    def test_the_default_folder_is_recognised_however_it_is_spelled(self):
        self.assertTrue(paths.is_native_default(self.native()))
        self.assertTrue(paths.is_native_default(self.native().replace(os.sep, "/")))
        self.assertTrue(paths.is_native_default(self.native() + os.sep + "." + os.sep))
        self.assertFalse(paths.is_native_default(os.path.join(self.home, ".claude-other")))
        self.assertFalse(paths.is_native_default(os.path.join(self.tmp, "accounts", "work")))
        self.assertFalse(paths.is_native_default(""))

    def test_the_default_account_runs_with_config_dir_unset(self):
        """With it set, Claude Code reads <dir>/.claude.json - a different file, no MCP servers."""
        env = {"CLAUDE_CONFIG_DIR": "stale", "CLAUDE_SECURESTORAGE_CONFIG_DIR": "stale", "KEEP": "1"}
        paths.apply_config_env(env, self.native())
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)
        self.assertNotIn("CLAUDE_SECURESTORAGE_CONFIG_DIR", env)
        self.assertEqual(env["KEEP"], "1")

    def test_any_other_folder_gets_both_variables_with_the_identical_string(self):
        other = os.path.join(self.tmp, "accounts", "work")
        env = paths.apply_config_env({}, other)
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], other)
        self.assertEqual(env["CLAUDE_SECURESTORAGE_CONFIG_DIR"], other)

    def test_a_session_for_the_default_account_does_not_inherit_a_config_dir(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/some/other"}):
            env = launcher.session_env(self.native())
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)
        other = launcher.session_env(os.path.join(self.tmp, "accounts", "work"))
        self.assertIn("CLAUDE_CONFIG_DIR", other)


class TestMcpExternalServers(Sandbox):
    def setUp(self):
        super().setUp()
        self.work = os.path.join(self.tmp, "accounts", "work")
        os.makedirs(self.work)
        from cortex import registry
        self.registry = registry
        registry.adopt("work", self.work)

    def fake_run(self, rc=0):
        return mock.patch.object(mcp.proc, "run",
                                 return_value=subprocess.CompletedProcess([], rc, "added", ""))

    def test_a_missing_tool_prints_the_install_command_and_runs_nothing(self):
        err = io.StringIO()
        with mock.patch.object(mcp.shutil, "which", return_value=None), self.fake_run() as run, \
                mock.patch("sys.stderr", err):
            self.assertEqual(mcp.cmd_add_external("graphify", "work"), 1)
        run.assert_not_called()
        self.assertIn("uv tool install graphifyy", err.getvalue())

    def test_registration_goes_through_claude_mcp_add_in_user_scope(self):
        with mock.patch.object(mcp.shutil, "which", return_value="/bin/graphify-mcp"), \
                mock.patch.object(mcp.binary, "find", return_value="/bin/claude"), \
                self.fake_run() as run, mock.patch("builtins.print"):
            self.assertEqual(mcp.cmd_add_external("graphify", "work"), 0)
        command = run.call_args[0][0]
        self.assertEqual(command, ["/bin/claude", "mcp", "add", "--scope", "user", "graphify", "--",
                                   "/bin/graphify-mcp"])
        self.assertEqual(run.call_args.kwargs["env"]["CLAUDE_CONFIG_DIR"], self.work)

    def test_the_default_account_is_registered_without_a_config_dir(self):
        self.registry.adopt("main", self.home + os.sep + ".claude")
        with mock.patch.object(mcp.shutil, "which", return_value="/bin/scrapling-mcp"), \
                mock.patch.object(mcp.binary, "find", return_value="/bin/claude"), \
                self.fake_run() as run, mock.patch("builtins.print"):
            mcp.cmd_add_external("scrapling", "main")
        self.assertNotIn("CLAUDE_CONFIG_DIR", run.call_args.kwargs["env"])

    def test_the_default_accounts_servers_are_read_from_the_file_next_to_the_folder(self):
        self.registry.adopt("main", self.home + os.sep + ".claude")
        with open(os.path.join(self.home, ".claude.json"), "w", encoding="utf-8") as fh:
            json.dump({"mcpServers": {"aws-mcp": {}, "graphify": {}}}, fh)
        self.assertEqual(mcp._registered_servers("main"), {"aws-mcp", "graphify"})

    def test_an_already_registered_server_is_not_registered_twice(self):
        with open(os.path.join(self.work, ".claude.json"), "w", encoding="utf-8") as fh:
            json.dump({"mcpServers": {"graphify": {}}}, fh)
        with mock.patch.object(mcp.shutil, "which", return_value="/bin/graphify-mcp"), \
                self.fake_run() as run, mock.patch("builtins.print"):
            self.assertEqual(mcp.cmd_add_external("graphify", "work"), 0)
        run.assert_not_called()

    def test_dry_run_changes_nothing(self):
        out = io.StringIO()
        with mock.patch.object(mcp.shutil, "which", return_value="/bin/graphify-mcp"), \
                mock.patch.object(mcp.binary, "find", return_value="/bin/claude"), \
                self.fake_run() as run, mock.patch("sys.stdout", out):
            self.assertEqual(mcp.cmd_add_external("graphify", "work", dry_run=True), 0)
        run.assert_not_called()
        self.assertIn("dry-run", out.getvalue())

    def test_a_failed_registration_is_reported_not_swallowed(self):
        with mock.patch.object(mcp.shutil, "which", return_value="/bin/graphify-mcp"), \
                mock.patch.object(mcp.binary, "find", return_value="/bin/claude"), \
                self.fake_run(rc=1), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(mcp.cmd_add_external("graphify", "work"), 1)

    def test_the_command_line_reaches_the_external_path(self):
        with mock.patch.object(mcp, "cmd_add_external", return_value=0) as add:
            self.assertEqual(mcp.main(["add", "graphify", "work", "--dry-run"]), 0)
        add.assert_called_once_with("graphify", "work", dry_run=True)

    def test_a_profile_named_like_a_server_is_refused_as_ambiguous(self):
        other = os.path.join(self.tmp, "accounts", "g")
        os.makedirs(other)
        self.registry.adopt("graphify", other)
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(mcp.main(["add", "graphify"]), 2)

    def test_the_cortex_server_registration_is_unchanged(self):
        with mock.patch.object(mcp, "cmd_add", return_value=0) as add:
            mcp.main(["add", "work"])
        add.assert_called_once_with("work", dry_run=False)


if __name__ == "__main__":
    unittest.main()
