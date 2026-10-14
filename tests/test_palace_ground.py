#!/usr/bin/env python3
"""
Grounding (does this file / function actually exist?) and keeping the palace honest across compaction.

Two promises are tested here, both about not misleading Claude:

* a name is only called wrong when the project can tell - library code, generic words and anything
  without a code graph are "not checked", never "wrong"; and a typo or rename comes with the real name;
* after a conversation is compacted or cleared, the palace may show memory again, because what it
  showed before is no longer in front of the model.
"""

import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from palace_testkit import PROJECT_DIR, PalaceCase, touch_graph, write_files, write_graph  # noqa: E402

from cortex.palace import cli, graph, ground, hook, write  # noqa: E402
from cortex.palace import store as store_mod  # noqa: E402

MCP = os.path.join(PROJECT_DIR, "scripts", "cortex-mcp.py")

FILES = {"cortex/guard.py": {"symbols": ["profile_dir", "check_write", "Guard"], "community": 0},
         "cortex/paths.py": {"symbols": ["canonical_dir", "home"], "community": 0},
         "cortex/store.py": {"symbols": ["Store", "open_store"], "community": 1},
         "tests/_guard.py": {"symbols": ["helper_for_guard"], "community": 2},
         "a/util.py": {"symbols": ["slugify"], "community": 3},
         "b/util.py": {"symbols": ["slugify_text"], "community": 3}}


def add_method(graph_path, source_file, name, node_id=None):
    """Add a node labelled the way Graphify labels a method: with a leading dot, ".name()"."""
    with open(graph_path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["nodes"].append({"id": node_id or "method_" + name, "label": ".%s()" % name, "norm_label": ".%s()" % name,
                          "file_type": "code", "source_file": source_file, "source_location": "L50",
                          "community": 1, "community_name": "store", "_callable": True})
    with open(graph_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    touch_graph(graph_path)


class GroundCase(PalaceCase):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.root, ".git"))
        write_files(self.root, {name: "# %s\n" % name for name in FILES})
        self.graph_path = write_graph(self.root, FILES)
        add_method(self.graph_path, "cortex/store.py", "insert_memory")
        graph.sync(self.store, self.root)
        self.previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.previous)

    def check(self, text):
        return ground.verify(self.store, self.root, text)

    def status_of(self, result, key, name):
        return [x for x in result[key] if x.get("path", x.get("name")) == name][0]


class TestFiles(GroundCase):
    def test_a_real_file_exists(self):
        r = self.check("See cortex/guard.py")
        self.assertEqual(r["files"][0]["status"], "exists")
        self.assertEqual(r["problems"], 0)

    def test_a_typo_is_not_found_and_the_real_name_is_offered(self):
        f = self.status_of(self.check("It is in cortex/gaurd.py"), "files", "cortex/gaurd.py")
        self.assertEqual(f["status"], "missing")
        self.assertEqual(f["suggest"][0], "cortex/guard.py")

    def test_a_file_that_never_existed_has_no_misleading_suggestion(self):
        f = self.check("See cortex/zebra_migration.py")["files"][0]
        self.assertEqual(f["status"], "missing")
        self.assertNotIn("suggest", f)

    def test_a_file_the_graph_lists_but_the_disk_lacks_was_deleted_since(self):
        os.remove(os.path.join(self.root, "cortex", "paths.py"))
        f = self.check("cortex/paths.py")["files"][0]
        self.assertEqual(f["status"], "stale")

    def test_a_bare_name_resolves_when_unique_and_is_ambiguous_when_not(self):
        self.assertEqual(self.check("guard.py")["files"][0]["status"], "exists")
        self.assertEqual(self.check("guard.py")["files"][0]["resolved"], "cortex/guard.py")
        amb = self.check("util.py")["files"][0]
        self.assertEqual(amb["status"], "ambiguous")
        self.assertEqual(sorted(amb["suggest"]), ["a/util.py", "b/util.py"])

    def test_paths_outside_the_project_are_not_judged(self):
        for p in ("/etc/passwd.conf", "~/notes.md", "C:/Windows/system32/x.dll"):
            self.assertEqual(self.check(p)["files"][0]["status"], "outside", p)

    def test_an_absolute_path_inside_the_project_is_checked(self):
        inside = os.path.join(self.root, "cortex", "guard.py").replace("\\", "/")
        self.assertEqual(self.check("see " + inside)["files"][0]["status"], "exists")
        nope = os.path.join(self.root, "cortex", "nope.py").replace("\\", "/")
        self.assertEqual(self.check("see " + nope)["files"][0]["status"], "missing")

    def test_a_web_address_is_not_a_file_claim(self):
        self.assertEqual(self.check("Docs at https://example.com/a/b/page.html and http://x.org/y.py")["files"], [])

    def test_works_without_a_graph_using_the_disk_alone(self):
        os.remove(self.graph_path)
        graph.sync(self.store, self.root)
        r = self.check("cortex/guard.py and cortex/nope.py")
        self.assertEqual([f["status"] for f in r["files"]], ["exists", "missing"])
        self.assertFalse(r["graph"])


class TestSymbols(GroundCase):
    def test_a_real_function_is_found_with_where(self):
        s = self.status_of(self.check("It calls `profile_dir`."), "symbols", "profile_dir")
        self.assertEqual((s["status"], s["where"]), ("found", ["cortex/guard.py"]))

    def test_call_parentheses_and_case_do_not_matter(self):
        self.assertEqual(self.check("`profile_dir()` and `PROFILE_DIR`")["symbols"][0]["status"], "found")
        self.assertEqual(self.check("`Guard`")["symbols"][0]["status"], "found")

    def test_a_near_miss_is_flagged_with_the_real_name(self):
        s = self.status_of(self.check("It calls `profil_dir`."), "symbols", "profil_dir")
        self.assertEqual(s["status"], "missing")
        self.assertEqual(s["suggest"], ["profile_dir"])

    def test_a_name_unlike_anything_here_is_unknown_not_wrong(self):
        s = self.check("Use `frobnicate_widgets`.")["symbols"][0]
        self.assertEqual(s["status"], "unknown")
        self.assertEqual(self.check("Use `frobnicate_widgets`.")["problems"], 0)

    def test_library_calls_are_never_called_wrong_even_when_the_project_has_the_same_last_word(self):
        # `home` is this project's function; os.path.expanduser / pathlib.Path.home are not.
        for name in ("os.path.join", "pathlib.Path.home", "subprocess.run", "np.array"):
            self.assertEqual(self.check("`%s`" % name)["symbols"][0]["status"], "external", name)

    def test_a_dotted_name_from_this_project_is_checked_on_its_last_part(self):
        self.assertEqual(self.check("`Store.insert_memory`")["symbols"][0]["status"], "found")
        s = self.check("`Store.insert_memry`")["symbols"][0]
        self.assertEqual((s["status"], s["suggest"]), ("missing", ["insert_memory"]))

    def test_methods_labelled_with_a_leading_dot_are_found_and_shown_without_it(self):
        # Regression: Graphify writes methods as ".name()"; the dot used to make every method "not found".
        s = self.check("`insert_memory`")["symbols"][0]
        self.assertEqual(s["status"], "found")
        row = self.store.conn.execute("SELECT label, norm_label FROM gsym WHERE node_id = 'method_insert_memory'").fetchone()
        self.assertEqual((row["label"], row["norm_label"]), ("insert_memory", "insert_memory"))

    def test_generic_and_tiny_names_are_not_checked(self):
        for name in ("main", "run", "get", "set", "x1", "id"):
            self.assertEqual(self.check("`%s`" % name)["symbols"][0]["status"], "unchecked", name)

    def test_bare_words_in_prose_are_not_claims(self):
        r = self.check("The profile_dir helper and CheckWrite logic, plus load_config, are used.")
        self.assertEqual(r["symbols"], [])

    def test_without_a_graph_names_are_not_checked_and_the_report_says_so(self):
        os.remove(self.graph_path)
        graph.sync(self.store, self.root)
        r = self.check("`profile_dir` in cortex/guard.py")
        self.assertEqual(r["symbols"][0]["status"], "unchecked")
        self.assertIn("no code graph", ground.format_report(r))

    def test_file_names_in_backticks_are_files_not_symbols(self):
        r = self.check("`cortex/guard.py` and `guard.py` and `README.md`")
        self.assertEqual(r["symbols"], [])
        self.assertGreaterEqual(len(r["files"]), 2)

    def test_odd_input_never_raises(self):
        for text in ("", None, "`", "``", "` `", "`" * 500, "x" * 100000, "\x00`a\x00`", "`a.`", "`.a`", "`a..b`"):
            ground.verify(self.store, self.root, text)


class TestReport(GroundCase):
    def test_the_report_is_plain_ascii_and_says_what_to_do(self):
        text = ground.format_report(self.check("`profil_dir` in cortex/gaurd.py and `os.path.join`"))
        text.encode("ascii")
        self.assertIn("did you mean: cortex/guard.py", text)
        self.assertIn("did you mean: profile_dir", text)
        self.assertIn("library code", text)

    def test_nothing_to_check_and_all_good_are_distinct_messages(self):
        self.assertIn("Nothing to check", ground.format_report(self.check("just words")))
        self.assertIn("Every file and name that could be checked exists", ground.format_report(self.check("cortex/guard.py")))


class TestCommand(GroundCase):
    def setUp(self):
        super().setUp()
        store_mod.open_store("project", cwd=self.root).close()           # `cc palace init` would do this

    def run_cli(self, *args, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with mock.patch("sys.stdin", io.StringIO(stdin or "")):
                rc = cli.main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def test_exit_code_tells_a_script_whether_anything_was_wrong(self):
        self.assertEqual(self.run_cli("verify", "cortex/guard.py")[0], 0)
        rc, out, _err = self.run_cli("verify", "cortex/gaurd.py")
        self.assertEqual(rc, 1)
        self.assertIn("NOT FOUND", out)

    def test_text_from_stdin_a_file_and_json(self):
        self.assertEqual(self.run_cli("verify", "-", stdin="see cortex/gaurd.py")[0], 1)
        path = os.path.join(self.root, "answer.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("see cortex/guard.py")
        self.assertEqual(self.run_cli("verify", "--file", path)[0], 0)
        rc, out, _ = self.run_cli("verify", "--json", "`profil_dir`")
        data = json.loads(out)
        self.assertEqual((rc, data["problems"], data["symbols"][0]["status"]), (1, 1, "missing"))

    def test_an_unreadable_file_is_an_error_not_a_crash(self):
        rc, _out, err = self.run_cli("verify", "--file", os.path.join(self.root, "nope.txt"))
        self.assertEqual(rc, 2)
        self.assertIn("cannot read", err)

    def test_text_that_starts_with_a_dash_is_still_text(self):
        self.assertEqual(self.run_cli("verify", "--", "- cortex/gaurd.py is where")[0], 1)

    def test_the_ground_switch_defaults_off_and_persists(self):
        self.assertIn("OFF", self.run_cli("ground")[1])
        self.assertIn("ON", self.run_cli("ground", "on")[1])
        st = store_mod.open_store("project", cwd=self.root)
        self.assertEqual(st.meta_get("ground"), "on")
        st.close()
        self.assertIn("OFF", self.run_cli("ground", "off")[1])

    def test_the_mcp_tool_returns_the_same_report(self):
        spec = importlib.util.spec_from_file_location("cortex_mcp_ground_test", MCP)
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        self.assertIn("verify_refs", server.TOOLS)
        out = server.TOOLS["verify_refs"]["handler"]({"text": "see `cortex/gaurd.py` now", "project_dir": self.root})
        self.assertIn("NOT FOUND", out)
        self.assertIn("cortex/guard.py", out)
        self.assertIn("Provide", server.TOOLS["verify_refs"]["handler"]({"text": "  "}))


class TestSessionLedger(GroundCase):
    """What the palace has shown is forgotten when the conversation is compacted or cleared."""

    def setUp(self):
        super().setUp()
        self.palace = store_mod.open_store("project", cwd=self.root)
        self.addCleanup(self.palace.close)
        self.rule = write.remember(self.palace, "Never write outside the profile",
                                   "Guard blocks every write outside the active profile folder.",
                                   kind="rule", tier=1, project_root=self.root)["id"]
        self.fact = write.remember(self.palace, "Guard checks writes first",
                                   "check_write in guard.py runs before every tool call that writes.",
                                   kind="decision", paths=["cortex/guard.py"], project_root=self.root)["id"]
        self.prompt = "How does check_write in guard.py decide what to block?"

    def ask(self, session="s1"):
        return hook.context_for(self.prompt, cwd=self.root, session=session)

    def test_it_shows_once_then_stays_quiet_then_shows_again_after_a_reset(self):
        first = self.ask()
        self.assertIn("Guard checks writes first", first)
        self.assertIn("Never write outside the profile", first, "the always-on core comes with the first answer")
        self.assertIsNone(self.ask(), "nothing is repeated inside one conversation")
        self.assertGreater(hook.reset_session(self.root, "s1"), 0)
        again = self.ask()
        self.assertIn("Guard checks writes first", again)
        self.assertIn("Never write outside the profile", again, "the core is re-shown after the context was summarised away")

    def test_a_reset_touches_only_that_session(self):
        self.ask("s1")
        self.ask("s2")
        hook.reset_session(self.root, "s1")
        self.assertIsNotNone(self.ask("s1"))
        self.assertIsNone(self.ask("s2"))

    def test_resetting_twice_or_with_nothing_to_reset_is_harmless(self):
        self.assertEqual(hook.reset_session(self.root, "never-used"), 0)
        self.ask()
        self.assertGreater(hook.reset_session(self.root, "s1"), 0)
        self.assertEqual(hook.reset_session(self.root, "s1"), 0)
        self.assertEqual(hook.reset_session(self.root, ""), 0)
        self.assertEqual(hook.reset_session(self.root, None), 0)

    def test_the_usage_history_is_kept(self):
        self.ask()
        before = self.palace.conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        hook.reset_session(self.root, "s1")
        self.assertEqual(self.palace.conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0], before)
        self.assertEqual(self.palace.injected_in_session("s1"), set())

    def test_a_reset_with_no_palace_is_fine(self):
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(os.path.join(elsewhere, ".git"))
        self.assertEqual(hook.reset_session(elsewhere, "s1"), 0)


class TestGroundingNote(GroundCase):
    BAD = "The fix is in `cortex/gaurd.py`, which calls `profil_dir`."

    def setUp(self):
        super().setUp()
        self.palace = store_mod.open_store("project", cwd=self.root)
        self.addCleanup(self.palace.close)

    def note(self, text=None, env=None):
        return hook.grounding_note(self.BAD if text is None else text, cwd=self.root, env=env or {})

    def test_it_is_off_until_asked_for(self):
        self.assertIsNone(self.note())

    def test_on_for_the_project_it_names_what_is_wrong_and_what_was_probably_meant(self):
        self.palace.meta_set("ground", "on")
        note = self.note()
        self.assertIn("cortex/gaurd.py", note)
        self.assertIn("cortex/guard.py", note)
        self.assertIn("profil_dir", note)
        self.assertIn("profile_dir", note)
        self.assertIn("about to create", note, "it must leave room for files that are meant to be new")

    def test_the_environment_can_turn_it_on_or_force_it_off(self):
        self.assertIsNotNone(self.note(env={"CORTEX_GROUND": "on"}))
        self.palace.meta_set("ground", "on")
        self.assertIsNone(self.note(env={"CORTEX_GROUND": "off"}))
        self.assertIsNone(self.note(env={"CORTEX_PALACE": "off"}))

    def test_it_stays_silent_when_everything_checks_out_or_cannot_be_checked(self):
        self.palace.meta_set("ground", "on")
        for text in ("Edit `cortex/guard.py`, calling `profile_dir`.", "Use `frobnicate_widgets` and `os.path.join`.",
                     "A `main` function.", "No names at all here.", ""):
            self.assertIsNone(self.note(text), text)

    def test_it_reports_a_deleted_file_but_not_an_outside_one(self):
        self.palace.meta_set("ground", "on")
        os.remove(os.path.join(self.root, "cortex", "paths.py"))
        self.assertIn("cortex/paths.py", self.note("Open cortex/paths.py"))
        self.assertIsNone(self.note("Open ~/notes.md and /etc/hosts.conf"))

    def test_it_is_short_however_much_is_wrong(self):
        self.palace.meta_set("ground", "on")
        many = " ".join("nofile%d.py" % i for i in range(60))
        note = self.note(many)
        self.assertLess(len(note), 1200)

    def test_it_fails_open_with_no_palace_or_a_damaged_one(self):
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(os.path.join(elsewhere, ".git"))
        self.assertIsNone(hook.grounding_note(self.BAD, cwd=elsewhere, env={"CORTEX_GROUND": "on"}))
        with mock.patch.object(ground, "verify", side_effect=RuntimeError("boom")):
            self.palace.meta_set("ground", "on")
            self.assertIsNone(self.note())


class TestBridgeFormat(GroundCase):
    def test_names_are_normalised_without_the_method_dot(self):
        self.assertEqual(graph.symbol_key(".insert_memory()"), "insert_memory")
        self.assertEqual(graph.symbol_key("Store()"), "store")
        self.assertEqual(graph.symbol_label(".insert_memory()"), "insert_memory")
        self.assertEqual(graph.symbol_label("  load_config() "), "load_config")

    def test_a_cache_written_by_an_older_format_is_rebuilt(self):
        self.assertFalse(graph.sync(self.store, self.root)["changed"])
        old = self.store.meta_get("graph_fp").rsplit(";fmt=", 1)[0]       # what an older version stored
        self.store.meta_set("graph_fp", old)
        self.assertTrue(graph.sync(self.store, self.root)["changed"])
        self.assertFalse(graph.sync(self.store, self.root)["changed"])


class TestDataDirVariable(PalaceCase):
    def test_the_data_dir_has_its_own_variable_and_ignores_the_shims_cortex_home(self):
        # CORTEX_HOME is where the Cortex *code* lives (bin/claude, claude.ps1, claude.exe). The palace
        # must not read it as a data folder, or setting either one would break the other.
        with mock.patch.dict(os.environ, {"CORTEX_HOME": os.path.join(self.tmp, "code")}):
            self.assertEqual(store_mod.home(), os.path.join(self.home, "palace"))
        with mock.patch.dict(os.environ, {"CORTEX_DATA_DIR": ""}):
            self.assertTrue(store_mod.home().startswith(os.path.join(self.fake_user_home, ".cortex")))


if __name__ == "__main__":
    unittest.main()
