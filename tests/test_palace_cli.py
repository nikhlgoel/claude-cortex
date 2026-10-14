#!/usr/bin/env python3
"""
The palace as a person (and Claude) actually uses it: ``cc palace ...``, the dispatcher, the MCP
tools, and the real prompt-hook script run the way Claude Code runs it.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from palace_testkit import PROJECT_DIR, PalaceCase, write_files, write_graph  # noqa: E402

from cortex import tools  # noqa: E402
from cortex.palace import cli, write  # noqa: E402
from cortex.palace import store as store_mod  # noqa: E402

HOOK = os.path.join(PROJECT_DIR, "scripts", "cortex-prompt-hook.py")
MCP = os.path.join(PROJECT_DIR, "scripts", "cortex-mcp.py")


class CliCase(PalaceCase):
    """Runs ``cli.main`` in-process, inside a throwaway project, against a throwaway palace home."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.root, ".git"))
        self.previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.previous)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def ok(self, *args):
        rc, out, err = self.run_cli(*args)
        self.assertEqual(rc, 0, "%s -> %s %s" % (args, out, err))
        return out

    def memory_id(self, out):
        return out.split("[")[1].split("]")[0]


class TestSetupAndStatus(CliCase):
    def test_recalling_before_any_setup_explains_and_creates_nothing(self):
        before = os.listdir(self.home)
        out = self.ok("recall", "anything")
        self.assertIn("cc palace init", out)
        self.assertEqual(os.listdir(self.home), before)

    def test_status_before_setup_says_what_to_run(self):
        rc, _out, err = self.run_cli("status")
        self.assertEqual(rc, 1)
        self.assertIn("cc palace init", err)

    def test_init_is_one_command_and_says_what_to_try_next(self):
        out = self.ok("init")
        self.assertIn("Palace:", out)
        self.assertIn("cc palace remember", out)
        self.assertIn("cc palace recall", out)
        self.assertIn("Graphify", out)                         # tells how to add the optional graph
        self.assertTrue(os.path.isfile(store_mod.db_path("project", self.root)))

    def test_init_twice_is_harmless(self):
        self.ok("init")
        self.ok("remember", "A decision", "We decided something important here.")
        self.ok("init")
        self.assertIn("1 active", self.ok("status"))

    def test_init_links_a_graph_when_there_is_one(self):
        write_files(self.root, {"a.py": "x = 1\n"})
        write_graph(self.root, {"a.py": {"symbols": ["go"]}})
        self.assertIn("Graphify graph linked: 1 files, 1 symbols", self.ok("init"))

    def test_init_imports_an_old_palace_without_touching_it(self):
        old = os.path.join(self.root, ".claude", "palace")
        os.makedirs(os.path.join(old, "rooms"))
        with open(os.path.join(old, "index.json"), "w", encoding="utf-8") as fh:
            json.dump({"memories": {"deci_aaaaaa": {"id": "deci_aaaaaa", "room": "decisions", "title": "Old decision",
                                                    "tags": ["db"], "summary": "Use WAL.",
                                                    "created_at": "2026-09-01T10:00:00+00:00"}}}, fh)
        with open(os.path.join(old, "rooms", "decisions.md"), "w", encoding="utf-8") as fh:
            fh.write("### [2026-09-01 10:00 UTC] Old decision <!-- id:deci_aaaaaa -->\n**Tags:** `#db`\n\nUse WAL.\n")
        with open(os.path.join(old, "index.json"), encoding="utf-8") as fh:
            before = fh.read()
        out = self.ok("init")
        self.assertIn("imported 1 of 1 memories", out)
        self.assertIn("were not changed or deleted", out)
        with open(os.path.join(old, "index.json"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)
        self.assertIn("Old decision", self.ok("list"))
        self.assertIn("already imported", self.ok("init"))

    def test_a_finished_command_leaves_no_database_open(self):
        # Python reports an unclosed connection as an ignored warning, never as a failure, so check directly:
        # nothing is left registered, and on Windows the file can be deleted (an open connection locks it).
        self.ok("init")
        self.ok("remember", "A note", "Something worth remembering about the project.")
        self.assertEqual(cli._OPENED, [])
        os.remove(store_mod.db_path("project", self.root))

    def test_no_arguments_shows_the_status(self):
        self.ok("init")
        self.assertIn("Palace:", self.ok())

    def test_a_typo_is_refused_not_ignored(self):
        self.ok("init")
        rc, _out, err = self.run_cli("status", "--nonsense")
        self.assertEqual(rc, 2)
        self.assertIn("unrecognised", err)


class TestRememberAndRecall(CliCase):
    def setUp(self):
        super().setUp()
        self.ok("init")

    def test_title_and_content_as_two_arguments(self):
        out = self.ok("remember", "Cache eviction policy", "The cache evicts the least recently used entries.")
        self.assertIn("Stored", out)
        self.assertIn("least recently used", self.ok("recall", "how does cache eviction work"))

    def test_a_single_argument_is_the_content_and_the_title_is_derived(self):
        self.ok("remember", "The deploy script needs the VPN to be connected first.")
        self.assertIn("deploy script", self.ok("list"))

    def test_the_old_room_form_still_works(self):
        out = self.ok("remember", "decisions", "Use WAL", "Because of concurrent writers in sessions.")
        self.assertIn("decision", out)
        out = self.ok("remember", "--room", "graveyard", "--title", "Fixed it", "--content", "KeyError on a missing key")
        self.assertIn("failure", out)

    def test_an_unknown_room_is_an_error_that_lists_the_real_ones(self):
        rc, _out, err = self.run_cli("remember", "--room", "attic", "--title", "x", "--content", "y body")
        self.assertEqual(rc, 1)
        self.assertIn("blueprint", err)

    def test_nothing_to_remember_is_refused(self):
        rc, _out, err = self.run_cli("remember")
        self.assertEqual(rc, 1)
        self.assertIn("Nothing to remember", err)

    def test_replacing_a_decision_says_so_and_recall_shows_only_the_new_one(self):
        self.ok("remember", "Pool size", "The pool holds ten connections.", "--kind", "fact")
        out = self.ok("remember", "Pool size", "The pool holds fifty connections after the outage.", "--kind", "fact")
        self.assertIn("replaces", out)
        got = self.ok("recall", "pool connections")
        self.assertIn("fifty", got)
        self.assertNotIn("ten connections", got)
        self.assertIn("ten connections", self.ok("recall", "pool connections", "--history"))

    def test_an_unrelated_question_gets_silence_not_filler(self):
        self.ok("remember", "Cache eviction policy", "The cache evicts the least recently used entries.")
        self.assertIn("Nothing relevant", self.ok("recall", "write a haiku about spring"))

    def test_auto_recall_is_completely_silent_when_there_is_nothing(self):
        self.assertEqual(self.ok("auto-recall", "write a haiku about spring"), "")
        self.assertEqual(self.ok("auto-recall"), "")

    def test_recall_explains_itself_on_request(self):
        self.ok("remember", "Cache eviction policy", "The cache evicts the least recently used entries.")
        out = self.ok("recall", "cache eviction", "--explain")
        self.assertIn("bm25", out)
        self.assertIn("coverage", out)

    def test_recall_can_emit_json(self):
        self.ok("remember", "Cache eviction policy", "The cache evicts the least recently used entries.")
        data = json.loads(self.ok("recall", "cache eviction", "--json"))
        self.assertEqual(len(data["items"]), 1)
        self.assertGreater(data["tokens"], 0)

    def test_recall_counts_as_a_use_unless_told_not_to(self):
        self.ok("remember", "Cache eviction policy", "The cache evicts the least recently used entries.")
        self.ok("recall", "cache eviction", "--no-record")
        mid = self.ok("list").split()[0]
        self.assertIn("used 0 time", self.ok("expand", mid))
        self.ok("recall", "cache eviction")
        self.assertIn("used 1 time", self.ok("expand", mid))

    def test_the_old_search_options_are_accepted(self):
        self.ok("remember", "Cache eviction policy", "The cache evicts the least recently used entries.")
        self.assertIn("least recently used", self.ok("search", "--room", "decisions", "cache", "eviction"))

    def test_secrets_are_reported_as_redacted_and_never_echoed(self):
        out = self.ok("remember", "Key note", "We used sk-ant-abcdefghijklmnopqrstuvwxyz123456 in the script today.")
        self.assertIn("redacted", out)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", out)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", self.ok("list"))


class TestManaging(CliCase):
    def setUp(self):
        super().setUp()
        self.ok("init")
        self.a = self.memory_id(self.ok("remember", "First topic", "The first topic body is about widgets."))
        self.b = self.memory_id(self.ok("remember", "Second topic", "The second topic body is about gadgets."))

    def test_expand_shows_everything_about_one_memory(self):
        out = self.ok("expand", self.a[:6])
        self.assertIn("First topic", out)
        self.assertIn("widgets", out)
        self.assertIn("trust agent", out)

    def test_expand_an_unknown_id_is_a_clear_error(self):
        rc, _out, err = self.run_cli("expand", "m_nothere")
        self.assertEqual(rc, 1)
        self.assertIn("No memory with id", err)

    def test_list_filters_and_shows_status(self):
        st = store_mod.open_store(cwd=self.root)
        self.addCleanup(st.close)
        write.archive(st, self.b)
        self.assertNotIn("Second topic", self.ok("list"))
        self.assertIn("Second topic", self.ok("list", "--all"))
        self.assertIn("[archived]", self.ok("list", "--all"))

    def test_pin_unpin_and_tier(self):
        self.assertIn("Pinned", self.ok("pin", self.a))
        self.assertIn("pinned", self.ok("expand", self.a))
        self.assertIn("Unpinned", self.ok("unpin", self.a))
        self.assertIn("shown at the start of every session", self.ok("tier", self.a, "1"))

    def test_archive_and_restore_are_reversible(self):
        self.assertIn("reversible", self.ok("archive", self.a))
        self.assertNotIn("First topic", self.ok("list"))
        self.ok("restore", self.a)
        self.assertIn("First topic", self.ok("list"))

    def test_the_old_prune_option_form_still_archives(self):
        self.ok("prune", "--id", self.a)
        self.assertNotIn("First topic", self.ok("list"))

    def test_archive_without_an_id_explains(self):
        rc, _out, err = self.run_cli("archive")
        self.assertEqual(rc, 2)
        self.assertIn("Usage", err)

    def test_supersede_marks_the_old_one_as_history(self):
        self.ok("supersede", self.a, self.b)
        self.assertNotIn("First topic", self.ok("list"))
        self.assertIn("superseded by", self.ok("expand", self.a))

    def test_forget_asks_first_and_then_really_deletes(self):
        rc, out, _err = self.run_cli("forget", self.a)
        self.assertEqual(rc, 1)
        self.assertIn("permanently deletes", out)
        self.assertIn("First topic", self.ok("list"))
        self.assertIn("Deleted", self.ok("forget", self.a, "--yes"))
        self.assertNotIn("First topic", self.ok("list", "--all"))

    def test_status_counts_what_is_there(self):
        out = self.ok("status")
        self.assertIn("2 active", out)
        self.assertIn("by tier", out)
        self.assertIn("last consolidated: never", out)

    def test_export_writes_readable_markdown(self):
        target = os.path.join(self.tmp, "export")
        self.ok("export", target)
        files = os.listdir(target)
        self.assertTrue(files)
        combined = ""
        for name in files:
            with open(os.path.join(target, name), encoding="utf-8") as fh:
                combined += fh.read()
        self.assertIn("Generated from the palace database", combined)
        self.assertIn("widgets", combined)

    def test_doctor_reports_a_healthy_palace_and_a_stale_index_is_repaired_on_open(self):
        out = self.ok("doctor")
        self.assertIn("[ok] database integrity", out)
        self.assertIn("keyword index is current", out)
        st = store_mod.open_store(cwd=self.root)
        st.meta_set("analyzer", "1")
        st.close()
        self.assertIn("keyword index is current", self.ok("doctor"))

    def test_the_automatic_injection_switch(self):
        self.assertIn("ON", self.ok("inject"))
        self.assertIn("OFF", self.ok("inject", "off"))
        self.assertIn("OFF", self.ok("inject", "status"))
        self.assertIn("ON", self.ok("inject", "on"))

    def test_the_environment_override_is_called_out(self):
        os.environ["CORTEX_PALACE"] = "off"
        self.addCleanup(os.environ.pop, "CORTEX_PALACE", None)
        self.assertIn("overrides this", self.ok("inject"))

    def test_the_global_palace_is_separate_from_the_project_one(self):
        self.ok("--scope", "global", "init")
        self.ok("--scope", "global", "remember", "Personal habit", "I like short commit messages in every project.")
        self.assertIn("Personal habit", self.ok("--scope", "global", "list"))
        self.assertNotIn("Personal habit", self.ok("list"))

    def test_an_explicit_palace_file_or_folder_can_be_named(self):
        folder = os.path.join(self.tmp, "elsewhere")
        self.ok("--path", folder, "init")
        self.assertTrue(os.path.isfile(os.path.join(folder, "palace.db")))
        self.ok("--path", folder, "remember", "Elsewhere note", "Stored in a palace somewhere else entirely.")
        self.assertIn("Elsewhere note", self.ok("--path", os.path.join(folder, "palace.db"), "list"))

    def test_the_evaluation_runs_from_the_command_line(self):
        out = self.ok("eval")
        self.assertIn("false injection", out)
        self.assertIn("HELD-OUT", out)


class TestGraphCommands(CliCase):
    def setUp(self):
        super().setUp()
        write_files(self.root, {"cortex/guard.py": "g = 1\n", "cortex/paths.py": "p = 1\n"})
        self.links = [("cortex/guard.py", "cortex/paths.py", "calls", "EXTRACTED")]
        write_graph(self.root, {"cortex/guard.py": {"symbols": ["compare_keys"], "community": 0},
                                "cortex/paths.py": {"symbols": ["profile_dir"], "community": 0}}, links=self.links)
        self.ok("init")

    def test_about_lists_memories_anchored_to_a_file_or_symbol(self):
        self.ok("remember", "Guard behaviour", "Compares stable keys; see cortex/guard.py.")
        self.assertIn("Guard behaviour", self.ok("about", "guard.py"))
        self.assertIn("Guard behaviour", self.ok("about", "compare_keys"))
        self.assertIn("No memories are anchored", self.ok("about", "paths.py"))

    def test_the_graph_command_reports_and_resyncs(self):
        self.assertIn("linked: 2 files, 2 symbols", self.ok("graph"))
        self.assertIn("Graph synced", self.ok("graph", "--sync"))

    def test_recalling_a_named_file_finds_its_memories(self):
        self.ok("remember", "Guard behaviour", "Hashes the keys that matter and nothing else.",
                "--file", "cortex/guard.py")
        self.assertIn("Guard behaviour", self.ok("recall", "what do we know about cortex/guard.py"))

    def test_consolidate_notices_changed_code_and_applies_only_on_request(self):
        self.ok("remember", "Guard behaviour", "Hashes the keys that matter.", "--file", "cortex/guard.py")
        write_files(self.root, {"cortex/guard.py": "g = 2  # edited\n"})
        write_graph(self.root, {"cortex/guard.py": {"symbols": ["compare_keys"], "community": 0, "ast_hash": "new"},
                                "cortex/paths.py": {"symbols": ["profile_dir"], "community": 0}}, links=self.links)
        dry = self.ok("consolidate")
        self.assertIn("dry run", dry)
        self.assertIn("fresh -> verify", dry)
        self.assertIn("freshness: fresh 1", self.ok("status"))
        self.ok("consolidate", "--apply")
        self.assertIn("freshness: verify 1", self.ok("status"))
        self.assertIn("code changed", self.ok("expand", self.ok("list").split()[0]))


class TestDispatch(CliCase):
    def test_cc_palace_remember_and_recall_run_the_new_engine_in_process(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(tools.run("palace", ["init"]), 0)
            self.assertEqual(tools.run("remember", ["Cache policy", "Evict the least recently used entries first."]), 0)
            self.assertEqual(tools.run("recall", ["cache", "policy"]), 0)
            self.assertEqual(tools.run("palace", ["status"]), 0)
        self.assertIn("Evict the least recently used", out.getvalue())
        self.assertIn("Palace:", out.getvalue())

    def test_the_commands_are_still_registered_for_the_did_you_mean_hint(self):
        for command in ("palace", "remember", "recall"):
            self.assertTrue(tools.is_tool(command))

    def test_the_old_script_is_marked_legacy_and_no_longer_routed(self):
        with open(os.path.join(PROJECT_DIR, "scripts", "claude-palace.py"), encoding="utf-8") as fh:
            head = fh.read(600)
        self.assertIn("LEGACY (v2.5)", head)
        self.assertEqual(set(tools.PALACE_COMMANDS), {"palace", "remember", "recall"})


def _load_mcp():
    spec = importlib.util.spec_from_file_location("cortex_mcp_under_test", MCP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMcpTools(CliCase):
    @classmethod
    def setUpClass(cls):
        cls.mcp = _load_mcp()

    def test_remember_then_recall_through_the_mcp_tools_in_the_project_folder(self):
        self.ok("init")
        said = self.mcp.tool_remember({"title": "Cache policy", "content": "Evict the least recently used entries.",
                                       "kind": "decision", "project_dir": self.root})
        self.assertIn("Stored", said)
        got = self.mcp.tool_recall({"query": "how does the cache decide what to evict", "project_dir": self.root})
        self.assertIn("least recently used", got)

    def test_the_mcp_recall_does_not_count_as_an_injection(self):
        self.ok("init")
        self.mcp.tool_remember({"title": "Cache policy", "content": "Evict the least recently used entries.",
                                "project_dir": self.root})
        self.mcp.tool_recall({"query": "cache policy", "project_dir": self.root})
        self.assertIn("used 0 time", self.ok("expand", self.ok("list").split()[0]))

    def test_a_missing_field_is_refused_in_plain_words(self):
        self.assertIn("Provide 'title' and 'content'", self.mcp.tool_remember({"title": "only a title"}))
        self.assertIn("Provide a 'query'", self.mcp.tool_recall({"query": "  "}))

    def test_a_failed_store_never_claims_it_stored(self):
        self.ok("init")
        said = self.mcp.tool_remember({"title": "x", "content": "some content here", "kind": "not-a-kind",
                                       "project_dir": self.root})
        self.assertTrue(said.startswith("NOT stored"), said)

    def test_the_tools_describe_themselves_in_the_new_vocabulary(self):
        schema = self.mcp.TOOLS["remember"]["inputSchema"]["properties"]
        for field in ("title", "content", "kind", "files", "supersedes", "project_dir"):
            self.assertIn(field, schema)
        self.assertIn("files", self.mcp.TOOLS["recall_memory"]["inputSchema"]["properties"])


class TestPromptHookScript(CliCase):
    """The real script, run the way Claude Code runs it: a JSON payload on stdin."""

    def setUp(self):
        super().setUp()
        self.ok("init")
        self.ok("remember", "Cache eviction policy", "The cache evicts the least recently used entries.")
        for i, topic in enumerate(("invoice", "router", "kernel", "camera", "robot", "audio", "sensor", "linker")):
            self.ok("remember", "%s notes" % topic.title(), "Details about the %s subsystem item %d." % (topic, i))

    def run_hook(self, prompt, session="s1", cwd=None, extra_env=None, raw=None):
        payload = raw if raw is not None else json.dumps(
            {"prompt": prompt, "cwd": cwd or self.root, "session_id": session})
        env = dict(os.environ, PYTHONUTF8="1", CORTEX_DATA_DIR=self.home)
        env.update(extra_env or {})
        return subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True,
                              encoding="utf-8", env=env, timeout=60)

    def context(self, proc):
        if not proc.stdout.strip():
            return ""
        return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_a_relevant_prompt_gets_memory_in_the_shape_claude_code_expects(self):
        proc = self.run_hook("how does cache eviction work")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("least recently used", data["hookSpecificOutput"]["additionalContext"])

    def test_the_same_memory_is_not_repeated_within_a_session(self):
        self.assertIn("least recently used", self.context(self.run_hook("how does cache eviction work")))
        self.assertEqual(self.context(self.run_hook("how does cache eviction work")), "")
        self.assertIn("least recently used", self.context(self.run_hook("how does cache eviction work", session="s2")))

    def test_an_unrelated_prompt_gets_nothing_and_exits_cleanly(self):
        proc = self.run_hook("write a haiku about spring")
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, ""))

    def test_the_kill_switch_works_in_the_real_script(self):
        proc = self.run_hook("how does cache eviction work", extra_env={"CORTEX_PALACE": "off"})
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, ""))

    def test_a_project_without_a_palace_is_left_alone(self):
        other = os.path.join(self.tmp, "other-project")
        os.makedirs(os.path.join(other, ".git"))
        projects = os.path.join(self.home, "palace", "projects")
        before = sorted(os.listdir(projects))
        proc = self.run_hook("how does cache eviction work", cwd=other)
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, ""))
        self.assertEqual(sorted(os.listdir(projects)), before)

    def test_garbage_on_stdin_never_breaks_the_prompt(self):
        for raw in ("", "not json at all", "{", "[]", "null", '{"prompt": 5}'):
            proc = self.run_hook("", raw=raw)
            self.assertEqual(proc.returncode, 0, repr(raw))

    def test_a_cortex_command_is_still_intercepted_and_not_given_memory(self):
        proc = self.run_hook("/cc version")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Claude Cortex", proc.stderr)

    def test_a_plain_prompt_is_never_blocked(self):
        self.assertEqual(self.run_hook("how does cache eviction work").returncode, 0)


if __name__ == "__main__":
    unittest.main()
