#!/usr/bin/env python3
"""
The Graphify bridge and the palace's maintenance.

The bridge is tested two ways on purpose: against graphs built here in the real node-link shape
(so every edge case can be constructed), and against ``tests/fixtures/graphify_real_sample`` - a
trimmed copy of what Graphify actually wrote for this repository - so the tests fail if the bridge
stops understanding the genuine format.
"""

import json
import os
import shutil
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from palace_testkit import NOW, PROJECT_DIR, PalaceCase, days_ago, touch_graph, write_files, write_graph  # noqa: E402

from cortex.palace import PalaceError, graph, lifecycle, text, write  # noqa: E402
from cortex.palace import store as store_mod  # noqa: E402

FIXTURE = os.path.join(PROJECT_DIR, "tests", "fixtures", "graphify_real_sample")


def small_project(case, extra=None):
    files = {"a.py": {"symbols": ["load_config", "Loader"], "community": 0, "ast_hash": "h-a"},
             "b.py": {"symbols": ["parse"], "community": 0, "ast_hash": "h-b"},
             "c.py": {"symbols": ["render"], "community": 1, "ast_hash": "h-c"}}
    files.update(extra or {})
    write_files(case.root, {name: "# %s\n" % name for name in files})
    return write_graph(case.root, files, links=[("a.py", "b.py", "calls", "EXTRACTED"),
                                                ("b.py", "c.py", "calls", "INFERRED")])


class TestFindAndSync(PalaceCase):
    def test_graphs_are_found_at_the_project_root_and_one_level_below(self):
        self.assertEqual(graph.find_graphs(self.root), [])
        small_project(self)
        sub = os.path.join(self.root, "svc")
        os.makedirs(sub)
        write_files(sub, {"x.py": "x = 1\n"})
        write_graph(sub, {"x.py": {"symbols": ["go"]}})
        hidden = os.path.join(self.root, ".hidden")
        os.makedirs(hidden)
        write_graph(hidden, {"y.py": {"symbols": []}})
        found = [os.path.relpath(p, self.root).replace("\\", "/") for p in graph.find_graphs(self.root)]
        self.assertEqual(found, ["graphify-out/graph.json", "svc/graphify-out/graph.json"])

    def test_syncing_builds_a_file_level_view_and_ignores_structural_edges(self):
        small_project(self)
        rep = graph.sync(self.store, self.root)
        # 3 files; symbols are the 4 functions/classes, not the per-file nodes Graphify also writes
        self.assertEqual((rep["graph"], rep["changed"], rep["files"], rep["symbols"]), (True, True, 3, 4))
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM gedge").fetchone()[0], 2)  # not 'contains'
        self.assertEqual(self.store.conn.execute("SELECT ast_hash FROM gfile WHERE file = 'a.py'").fetchone()[0], "h-a")

    def test_a_containment_or_rationale_link_between_files_is_not_a_dependency(self):
        path = small_project(self)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["links"].append({"source": "a_file", "target": "render", "relation": "rationale_for",
                              "confidence": "EXTRACTED", "confidence_score": 1.0})
        data["links"].append({"source": "c_file", "target": "load_a_file_placeholder", "relation": "contains",
                              "confidence": "EXTRACTED", "confidence_score": 1.0})
        data["links"].append({"source": "a_file", "target": "c_file", "relation": "contains",
                              "confidence": "EXTRACTED", "confidence_score": 1.0})
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        graph.sync(self.store, self.root)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM gedge").fetchone()[0], 2)
        self.assertNotIn("c.py", graph.GraphIndex(self.store).neighbors(["a.py"], hops=1))

    def test_syncing_again_without_a_change_does_nothing(self):
        path = small_project(self)
        graph.sync(self.store, self.root)
        stamp = self.store.meta_get("graph_synced")
        rep = graph.sync(self.store, self.root)
        self.assertEqual((rep["graph"], rep["changed"]), (True, False))
        self.assertEqual(self.store.meta_get("graph_synced"), stamp)
        touch_graph(path)
        self.assertTrue(graph.sync(self.store, self.root)["changed"])

    def test_removing_the_graph_clears_the_derived_view(self):
        small_project(self)
        graph.sync(self.store, self.root)
        shutil.rmtree(os.path.join(self.root, "graphify-out"))
        rep = graph.sync(self.store, self.root)
        self.assertEqual((rep["graph"], rep["changed"]), (False, True))
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM gfile").fetchone()[0], 0)
        self.assertFalse(graph.GraphIndex(self.store).available)

    def test_no_graph_at_all_is_a_normal_state(self):
        self.assertEqual(graph.sync(self.store, self.root)["graph"], False)
        self.assertFalse(graph.GraphIndex(self.store).available)

    def test_something_that_is_not_a_graph_is_refused_and_the_old_view_survives(self):
        path = small_project(self)
        graph.sync(self.store, self.root)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"hello": "world"}')
        with self.assertRaises(PalaceError) as ctx:
            graph.sync(self.store, self.root)
        self.assertIn("does not look like a Graphify graph", str(ctx.exception))
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM gfile").fetchone()[0], 3)

    def test_unreadable_json_is_a_clear_error(self):
        path = small_project(self)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ broken")
        with self.assertRaises(PalaceError):
            graph.sync(self.store, self.root)

    def test_bad_nodes_and_links_are_skipped_and_edges_is_accepted_for_links(self):
        path = small_project(self)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["nodes"].append({"label": "no id here", "source_file": "a.py"})
        data["links"].append({"source": "ghost", "target": "a_file", "relation": "calls", "confidence": "EXTRACTED"})
        data["links"].append("not even a dict")
        data["edges"] = data.pop("links")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        rep = graph.sync(self.store, self.root)
        self.assertEqual((rep["files"], rep["edges"]), (3, 2))

    def test_a_graph_built_in_a_subfolder_maps_to_project_relative_paths(self):
        sub = os.path.join(self.root, "svc")
        os.makedirs(sub)
        write_files(sub, {"x.py": "x = 1\n"})
        write_graph(sub, {"x.py": {"symbols": ["go"]}})
        graph.sync(self.store, self.root)
        self.assertIsNotNone(graph.GraphIndex(self.store).info("svc/x.py"))
        self.assertIsNone(graph.GraphIndex(self.store).info("x.py"))

    def test_nodes_outside_the_project_and_external_concepts_are_ignored(self):
        path = small_project(self)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["nodes"].append({"id": "stdlib_os", "label": "os", "file_type": "concept", "source_file": "",
                              "community": 0})
        data["nodes"].append({"id": "far", "label": "far()", "file_type": "code", "norm_label": "far()",
                              "source_file": "../elsewhere/far.py", "community": 0})
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        graph.sync(self.store, self.root)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM gfile").fetchone()[0], 3)
        self.assertIsNone(graph.GraphIndex(self.store).resolve_symbol("far"))


class TestGraphQueries(PalaceCase):
    def setUp(self):
        super().setUp()
        small_project(self, extra={"load_config.py": {"symbols": ["parse"], "community": 2},
                                   "sub/load_config.py": {"symbols": [], "community": 2}})
        graph.sync(self.store, self.root)
        self.g = graph.GraphIndex(self.store)

    def test_symbols_resolve_when_unique_and_not_when_ambiguous(self):
        self.assertEqual(self.g.resolve_symbol("render")["file"], "c.py")
        self.assertEqual(self.g.resolve_symbol("Loader")["kind"], "class")
        self.assertIsNone(self.g.resolve_symbol("parse"))              # defined in two files
        self.assertIsNone(self.g.resolve_symbol("nothing_like_this"))

    def test_symbol_lookup_ignores_case_and_graphifys_call_parentheses(self):
        for spelling in ("load_config", "LOAD_CONFIG", "load_config()"):
            self.assertEqual(self.g.resolve_symbol(spelling)["file"], "a.py", spelling)
        self.assertTrue(self.g.symbol_present("load_config()", "a.py"))
        self.assertFalse(self.g.symbol_present("load_config", "c.py"))

    def test_a_base_name_resolves_only_when_one_file_has_it(self):
        self.assertEqual(self.g.resolve_basename("a.py"), "a.py")
        self.assertIsNone(self.g.resolve_basename("load_config.py"))   # two files share it
        self.assertIsNone(self.g.resolve_basename("missing.py"))

    def test_an_underscore_in_a_file_name_is_not_a_wildcard(self):
        write_files(self.root, {"xx_yy.py": "1\n", "xxzyy.py": "2\n"})
        write_graph(self.root, {"xx_yy.py": {"symbols": []}, "xxzyy.py": {"symbols": []}})
        graph.sync(self.store, self.root, force=True)
        self.assertEqual(graph.GraphIndex(self.store).resolve_basename("xx_yy.py"), "xx_yy.py")

    def test_neighbours_are_weighted_by_certainty_and_distance(self):
        near = self.g.neighbors(["a.py"], hops=1)
        self.assertEqual(set(near), {"b.py"})
        far = self.g.neighbors(["a.py"], hops=2)
        self.assertEqual(set(far), {"b.py", "c.py"})
        self.assertGreater(far["b.py"], far["c.py"])                    # one hop beats two
        around_b = self.g.neighbors(["b.py"])
        self.assertGreater(around_b["a.py"], around_b["c.py"])          # EXTRACTED beats INFERRED
        self.assertNotIn("a.py", far)                                   # the start is never its own neighbour
        self.assertTrue(all(0 < w < 1 for w in far.values()))

    def test_distance_alone_lowers_a_files_weight(self):
        write_files(self.root, {"p.py": "# p\n", "q.py": "# q\n", "r.py": "# r\n"})
        write_graph(self.root, {"p.py": {"symbols": []}, "q.py": {"symbols": []}, "r.py": {"symbols": []}},
                    links=[("p.py", "q.py", "calls", "EXTRACTED"), ("q.py", "r.py", "calls", "EXTRACTED")])
        graph.sync(self.store, self.root, force=True)
        far = graph.GraphIndex(self.store).neighbors(["p.py"], hops=2)
        self.assertGreater(far["q.py"], far["r.py"] * 1.5)       # equally certain edges: only distance differs

    def test_files_in_the_same_community_are_reported(self):
        self.assertEqual(self.g.same_community(["a.py"]), {"b.py"})
        self.assertEqual(self.g.same_community(["nothing.py"]), set())
        self.assertEqual(self.g.community_names()[0][2], 2)


class TestRealGraphifyFormat(PalaceCase):
    """The same checks against what the real tool wrote for this repository."""

    def setUp(self):
        super().setUp()
        folder = os.path.join(self.root, "cortex")
        out = os.path.join(folder, "graphify-out")
        os.makedirs(out)
        for name in ("graph.json", "manifest.json"):
            shutil.copy(os.path.join(FIXTURE, name), os.path.join(out, name))
        write_files(folder, {n: "# stand-in\n" for n in ("guard.py", "paths.py", "registry.py")})
        graph.sync(self.store, self.root)
        self.g = graph.GraphIndex(self.store)

    def test_the_fixture_really_has_the_shape_this_bridge_depends_on(self):
        with open(os.path.join(FIXTURE, "graph.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(set(data), {"directed", "multigraph", "graph", "nodes", "links", "hyperedges"})
        node = next(n for n in data["nodes"] if n["file_type"] == "code")
        for field in ("id", "label", "norm_label", "source_file", "source_location", "community"):
            self.assertIn(field, node)
        link = next(l for l in data["links"] if l["relation"] == "calls")
        for field in ("source", "target", "relation", "confidence", "confidence_score"):
            self.assertIn(field, link)
        self.assertTrue(any(n["label"].endswith("()") for n in data["nodes"]))     # functions carry parentheses

    def test_files_symbols_and_hashes_are_read_from_the_real_format(self):
        for rel in ("cortex/guard.py", "cortex/paths.py", "cortex/registry.py"):
            info = self.g.info(rel)
            self.assertIsNotNone(info, rel)
            self.assertEqual(len(info["ast_hash"]), 32)
        self.assertEqual(self.g.resolve_symbol("profile_dir")["file"], "cortex/paths.py")

    def test_real_dependency_edges_make_neighbours(self):
        self.assertIn("cortex/paths.py", self.g.neighbors(["cortex/guard.py"]))

    def test_a_memory_anchored_here_is_fresh_then_flagged_when_the_real_hash_changes(self):
        r = write.remember(self.store, "Guard notes", "How `profile_dir` is used by cortex/guard.py.",
                           project_root=self.root)
        self.assertEqual(self.store.get(r["id"])["freshness"], "fresh")
        anchors = {a["file"] for a in self.store.anchors_of(r["id"])}
        self.assertEqual(anchors, {"cortex/guard.py", "cortex/paths.py"})
        self.assertEqual(graph.memory_freshness(self.store, self.root, r["id"]), "fresh")
        manifest_path = os.path.join(self.root, "cortex", "graphify-out", "manifest.json")
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        manifest["guard.py"]["ast_hash"] = "0" * 32                # Graphify noticed the file's syntax changed
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        touch_graph(os.path.join(self.root, "cortex", "graphify-out", "graph.json"))
        graph.sync(self.store, self.root)
        self.assertEqual(graph.memory_freshness(self.store, self.root, r["id"]), "verify")


class TestAnchorState(PalaceCase):
    def setUp(self):
        super().setUp()
        small_project(self)
        graph.sync(self.store, self.root)

    def anchor(self, rel, **kw):
        a = graph.make_anchor(self.store, self.root, rel)
        a["kind"] = kw.pop("kind", "file")
        a.update(kw)
        return a

    def test_an_unchanged_file_is_fresh(self):
        self.assertEqual(graph.anchor_state(self.store, self.root, self.anchor("a.py")), "fresh")

    def test_a_changed_syntax_tree_hash_means_verify(self):
        a = self.anchor("a.py", ast_hash="something-older")
        self.assertEqual(graph.anchor_state(self.store, self.root, a), "verify")

    def test_a_deleted_file_is_orphaned(self):
        a = self.anchor("a.py")
        os.remove(os.path.join(self.root, "a.py"))
        shutil.rmtree(os.path.join(self.root, "graphify-out"))
        graph.sync(self.store, self.root)
        self.assertEqual(graph.anchor_state(self.store, self.root, a), "orphaned")

    def test_a_symbol_that_no_longer_exists_is_orphaned(self):
        a = self.anchor("a.py", kind="symbol", label="load_config")
        self.assertEqual(graph.anchor_state(self.store, self.root, a), "fresh")
        a["label"] = "renamed_away"
        self.assertEqual(graph.anchor_state(self.store, self.root, a), "orphaned")

    def test_without_a_graph_the_file_content_hash_is_used(self):
        shutil.rmtree(os.path.join(self.root, "graphify-out"))
        graph.sync(self.store, self.root)
        a = self.anchor("b.py")
        self.assertIsNone(a["ast_hash"])
        self.assertEqual(graph.anchor_state(self.store, self.root, a), "fresh")
        write_files(self.root, {"b.py": "# edited\n"})
        self.assertEqual(graph.anchor_state(self.store, self.root, a), "verify")

    def test_nothing_to_compare_against_is_unknown_not_fresh(self):
        self.assertEqual(graph.anchor_state(self.store, None, self.anchor("a.py")), "unknown")
        bare = {"file": "a.py", "kind": "file", "ast_hash": None, "sha": None}
        self.assertEqual(graph.anchor_state(self.store, self.root, bare), "unknown")

    def test_the_worst_anchor_decides_the_memory(self):
        r = write.remember(self.store, "Mixed", "Touches a.py and b.py together.", project_root=self.root)
        self.assertEqual(graph.memory_freshness(self.store, self.root, r["id"]), "fresh")
        write_files(self.root, {"b.py": "# changed under it\n"})
        shutil.rmtree(os.path.join(self.root, "graphify-out"))
        graph.sync(self.store, self.root)
        self.assertEqual(graph.memory_freshness(self.store, self.root, r["id"]), "verify")
        os.remove(os.path.join(self.root, "a.py"))
        self.assertEqual(graph.memory_freshness(self.store, self.root, r["id"]), "orphaned")

    def test_status_lines_explain_the_state_in_plain_words(self):
        lines = graph.status_lines(self.store, self.root)
        self.assertTrue(lines[0].startswith("Graphify graph:"))
        self.assertIn("3 files", lines[1])
        shutil.rmtree(os.path.join(self.root, "graphify-out"))
        self.assertIn("graphify update .", " ".join(graph.status_lines(self.store, self.root)))


class TestLifecycle(PalaceCase):
    def R(self, title, body, age_days=0, **kw):
        kw.setdefault("project_root", self.root)
        return write.remember(self.store, title, body, created_at=store_mod.iso(days_ago(age_days)), **kw)["id"]

    def snapshot(self):
        return [tuple(r) for r in self.store.conn.execute(
            "SELECT id, status, freshness, tier, pinned FROM memory ORDER BY id")]

    def _clone(self, memory_id, new_title):
        """A near-copy that bypasses the write path's own duplicate check (as old data could)."""
        row = self.store.get(memory_id)
        row["id"] = store_mod.new_id()
        row["title"], row["content_hash"] = new_title, "different-" + row["id"]
        row["recorded_at"] = store_mod.iso(NOW)
        self.store.insert_memory(row)
        self.store.index_memory(row["id"], {"title": text.terms(new_title), "tags": [],
                                            "body": text.terms(row["body"]), "anchor": []})
        return row["id"]

    def test_a_dry_run_reports_but_changes_nothing(self):
        write_files(self.root, {"a.py": "x = 1\n"})
        self.R("Old episode", "Something that happened long ago in a.py.", age_days=300, kind="failure",
               importance=0.2, paths=["a.py"])
        write_files(self.root, {"a.py": "x = 2\n"})
        before = self.snapshot()
        report = lifecycle.consolidate(self.store, self.root, now=NOW)
        self.assertFalse(report["applied"])
        self.assertTrue(report["stale"] or report["freshness"])
        self.assertEqual(self.snapshot(), before)
        self.assertIn("dry run: nothing changed", lifecycle.format_report(report, self.store))

    def test_freshness_is_recorded_on_apply_and_only_once(self):
        write_files(self.root, {"a.py": "x = 1\n"})
        mid = self.R("About a", "Notes about a.py behaviour.")
        write_files(self.root, {"a.py": "x = 2  # edited\n"})
        first = lifecycle.consolidate(self.store, self.root, now=NOW, apply=True)
        self.assertEqual(first["freshness"], {mid: ("fresh", "verify")})
        self.assertEqual(self.store.get(mid)["freshness"], "verify")
        self.assertTrue(self.store.conn.execute(
            "SELECT 1 FROM event WHERE op = 'freshness' AND memory = ?", (mid,)).fetchone())
        self.assertEqual(lifecycle.consolidate(self.store, self.root, now=NOW, apply=True)["freshness"], {})
        self.assertEqual(self.store.meta_get("last_consolidated"), store_mod.iso(NOW))

    def test_near_duplicates_are_found_and_the_newer_one_is_archived_with_a_link(self):
        body = " ".join("fact%d" % i for i in range(30))
        older = self.R("Original note", body, age_days=10)
        newer = self._clone(older, "Original note")
        report = lifecycle.consolidate(self.store, self.root, now=NOW, apply=True)
        self.assertEqual([(a, b) for a, b, _ in report["duplicates"]], [(older, newer)])
        self.assertEqual((self.store.get(older)["status"], self.store.get(newer)["status"]), ("active", "archived"))
        self.assertTrue(any(l["rel"] == "duplicate_of" for l in self.store.links_of(newer)))

    def test_reordered_words_are_not_called_duplicates(self):
        a = self.R("Direction one", "the auth service depends on the cache layer for sessions and tokens")
        b = self._clone(a, "Direction one")
        swapped = "the cache layer depends on the auth service for sessions and tokens"
        self.store.conn.execute("UPDATE memory SET body = ? WHERE id = ?", (swapped, b))
        self.store.index_memory(b, {"title": text.terms("Direction one"), "tags": [], "body": text.terms(swapped),
                                    "anchor": []})
        self.assertEqual(lifecycle.find_duplicates(self.store), [])

    def test_only_old_unused_unimportant_unconfirmed_episodes_are_archived(self):
        old_junk = self.R("Old junk", "Some minor thing from long ago.", age_days=300, kind="note", importance=0.2)
        recent = self.R("Recent junk", "Some minor thing from last week.", age_days=7, kind="note", importance=0.2)
        important = self.R("Old but important", "A serious failure from long ago.", age_days=300, kind="failure",
                           importance=0.9)
        pinned = self.R("Old pinned", "Pinned on purpose long ago.", age_days=300, kind="note", importance=0.2,
                        pinned=True)
        used = self.R("Old but used", "Used again recently somewhere.", age_days=300, kind="note", importance=0.2)
        self.store.conn.execute("UPDATE memory SET uses = 4 WHERE id = ?", (used,))
        write_files(self.root, {"keep.py": "x = 1\n"})
        confirmed = self.R("Old but confirmed", "About keep.py which is unchanged.", age_days=300, kind="note",
                           importance=0.2, paths=["keep.py"])
        report = lifecycle.consolidate(self.store, self.root, now=NOW, apply=True)
        self.assertEqual(report["stale"], [old_junk])
        for kept in (recent, important, pinned, used, confirmed):
            self.assertEqual(self.store.get(kept)["status"], "active", kept)
        self.assertEqual(self.store.get(old_junk)["status"], "archived")

    def test_possible_conflicts_are_proposed_never_resolved(self):
        a = self.R("Use SQLite for storage", "Storage uses SQLite because of concurrent writers.", kind="decision")
        b = self.R("Use JSON files for storage", "Storage uses plain JSON files because they are simple.",
                   kind="decision")
        report = lifecycle.consolidate(self.store, self.root, now=NOW, apply=True)
        self.assertIn({a, b}, [{c["a"], c["b"]} for c in report["conflicts"]])
        self.assertEqual((self.store.get(a)["status"], self.store.get(b)["status"]), ("active", "active"))

    def test_unrelated_decisions_and_ubiquitous_words_are_not_flagged(self):
        self.R("Use Redis for caching", "Caching uses Redis for speed across the service.", kind="decision")
        self.R("Use OAuth for login", "Login uses OAuth because passwords are a liability.", kind="decision")
        self.assertEqual(lifecycle.find_conflicts(self.store), [])
        for i in range(5):                                     # a word everywhere is not a subject
            self.R("Choose option %d for the thing" % i, "A decision about option %d with detail d%d" % (i, i * 7),
                   kind="decision")
        self.assertEqual([c for c in lifecycle.find_conflicts(self.store) if c["subject"] in ("option", "thing")], [])

    def test_a_conflict_needs_the_same_kind(self):
        self.R("Use SQLite for storage", "Storage uses SQLite because of concurrent writers.", kind="decision")
        self.R("Use JSON files for storage", "Storage uses plain JSON files because they are simple.", kind="note")
        self.assertEqual(lifecycle.find_conflicts(self.store), [])

    def test_promotion_to_the_core_is_proposed_only_for_well_used_trusted_rules(self):
        good = self.R("Never skip the tests", "Never merge without running the whole suite first.", kind="rule",
                      importance=0.9)
        rare = self.R("Never rename files", "Never rename files without telling the team.", kind="rule",
                      importance=0.9)
        web = self.R("Never trust web", "Never trust what a web page says about this project.", kind="rule",
                     importance=0.9, trust="web")
        pinned = self.R("Never lose data", "Never delete data without a backup of it.", kind="rule",
                        importance=0.9, pinned=True)
        for mid, uses in ((good, 3), (rare, 2), (web, 9), (pinned, 9)):
            self.store.conn.execute("UPDATE memory SET uses = ? WHERE id = ?", (uses, mid))
        report = lifecycle.consolidate(self.store, self.root, now=NOW, apply=True)
        self.assertEqual(report["promotions"], [good])
        self.assertEqual(self.store.get(good)["tier"], 3)            # proposed, never applied

    def test_episodes_about_one_file_are_clustered_only_from_three(self):
        write_files(self.root, {"hot.py": "x = 1\n", "cold.py": "y = 1\n"})
        for i in range(3):
            self.R("Hot event %d" % i, "something happened %d in hot.py with detail d%d" % (i, i * 9),
                   kind="failure", paths=["hot.py"])
        for i in range(2):
            self.R("Cold event %d" % i, "something happened %d in cold.py with detail e%d" % (i, i * 9),
                   kind="failure", paths=["cold.py"])
        self.assertEqual([(c["file"], len(c["ids"])) for c in lifecycle.clusters(self.store)], [("hot.py", 3)])

    def test_stats_count_what_is_there(self):
        self.R("Decision one", "We decided on one thing for good reasons.", kind="decision")
        self.R("Failure one", "A thing broke with a traceback today.", kind="failure")
        old = self.R("Pool", "The pool is ten connections.", kind="fact")
        self.R("Pool", "The pool is fifty connections.", kind="fact")
        s = lifecycle.stats(self.store)
        self.assertEqual((s["active"], s["superseded"], s["archived"]), (3, 1, 0))
        self.assertEqual(s["by_kind"], {"decision": 1, "failure": 1, "fact": 1})
        self.assertEqual(s["by_tier"], {2: 1, 3: 2})
        self.assertGreater(s["size_bytes"], 0)
        self.assertIsNone(s["last_consolidated"])
        self.assertEqual(self.store.get(old)["status"], "superseded")

    def test_applying_is_all_or_nothing(self):
        write_files(self.root, {"a.py": "x = 1\n"})
        mid = self.R("About a", "Notes about a.py behaviour.")
        write_files(self.root, {"a.py": "x = 2\n"})
        body = " ".join("f%d" % i for i in range(30))
        older = self.R("Dup", body)
        self._clone(older, "Dup")

        def boom(*a, **k):
            raise RuntimeError("disk full")
        self.store.add_link = boom
        with self.assertRaises(RuntimeError):
            lifecycle.consolidate(self.store, self.root, now=NOW, apply=True)
        del self.store.add_link
        self.assertEqual(self.store.get(mid)["freshness"], "fresh")        # nothing was half applied
        self.assertIsNone(self.store.meta_get("last_consolidated"))


if __name__ == "__main__":
    unittest.main()
