#!/usr/bin/env python3
"""
The palace's foundations: the text analyzer, the SQLite store, and the write path.

Several of these tests pin a bug that was actually found while building it:

* ``settings`` and ``setting`` stemmed to different terms, so a query silently missed the memory;
* ``SQLite`` was split into ``sq`` + ``lite``, so the synonym "database ~ sqlite" could never match;
* "pool size 10" followed by "pool size 50 after the outage" was discarded as a duplicate by the
  old palace, losing the one fact that mattered.
"""

import json
import os
import sys
import threading
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from palace_testkit import NOW, PalaceCase, write_files  # noqa: E402

from cortex.palace import PalaceError, text, write  # noqa: E402
from cortex.palace import store as store_mod  # noqa: E402


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class TestAnalyzer(unittest.TestCase):
    def test_code_identifiers_are_findable_by_whole_name_and_by_part(self):
        self.assertEqual(text.terms("load_config"), ["load_config", "load", "config"])
        self.assertEqual(text.terms("loadConfig"), ["loadconfig", "load", "config"])
        self.assertEqual(text.terms("src/cortex/paths.py"), ["src", "cortex", "path", "py"])

    def test_brand_names_are_not_split_but_real_acronym_boundaries_are(self):
        self.assertEqual(text.terms("SQLite"), ["sqlit"])          # not "sq" + "lite"
        self.assertEqual(text.terms("HTTPServer"), ["httpserver", "http", "server"])

    def test_stopwords_and_weak_words_are_not_terms(self):
        self.assertEqual(text.terms("the and of should instead using"), [])
        self.assertEqual(text.terms(""), [])
        self.assertEqual(text.terms(None), [])

    def test_word_families_meet_on_one_stem(self):
        families = [["setting", "settings"], ["fail", "failed", "failing", "fails"],
                    ["test", "tests", "tested", "testing"], ["cache", "caching", "cached", "caches"],
                    ["create", "created", "creating", "creates", "creation"],
                    ["update", "updates", "updated", "updating"], ["query", "queries"],
                    ["process", "processes", "processing"], ["load", "loaded", "loading"],
                    ["inject", "injecting", "injection"], ["memory", "memories"]]
        for family in families:
            self.assertEqual(len({text.stem(w) for w in family}), 1, family)

    def test_the_settings_setting_split_stays_fixed(self):
        # A single stemming pass left these one step apart, so a query for one missed the other.
        self.assertEqual(text.stem("settings"), text.stem("setting"))

    def test_unrelated_words_are_not_merged(self):
        self.assertNotEqual(text.stem("set"), text.stem("setting"))
        self.assertEqual(text.stem("string"), "string")
        self.assertNotEqual(text.stem("status"), text.stem("state"))

    def test_stemming_is_idempotent(self):
        for word in ("running", "settings", "classes", "queries", "embedded", "injection", "caching"):
            self.assertEqual(text.stem(text.stem(word)), text.stem(word), word)

    def test_a_question_and_a_note_about_the_same_thing_share_terms(self):
        shared = set(text.terms("Injecting memories")) & set(text.terms("memory injection"))
        self.assertEqual(shared, {"inject", "memory"})

    def test_secrets_are_scrubbed_by_kind(self):
        samples = {
            "anthropic-key": "key sk-ant-abcdefghijklmnopqrstuvwxyz123456",
            "github-token": "token ghp_" + "a1B2c3D4e5" * 4,
            "aws-key": "id AKIAABCDEFGHIJKLMNOP here",
            "jwt": "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop",
            "bearer": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123",
            "assignment": "password=hunter2hunter",
        }
        for kind, sample in samples.items():
            clean, kinds = text.scrub_secrets(sample)
            self.assertIn(kind, kinds, sample)
            self.assertIn("[REDACTED:%s]" % kind, clean)
        clean, _ = text.scrub_secrets("-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----")
        self.assertEqual(clean, "[REDACTED:private-key]")

    def test_an_assignment_keeps_the_name_and_hides_only_the_value(self):
        clean, _ = text.scrub_secrets("set api_key: abc123def456 now")
        self.assertIn("api_key: [REDACTED:assignment]", clean)
        self.assertNotIn("abc123def456", clean)

    def test_ordinary_text_is_untouched(self):
        sample = "We decided to use SQLite; see guard.py. Version 2.1.287 and the token budget of 800."
        self.assertEqual(text.scrub_secrets(sample), (sample, []))

    def test_paths_in_text(self):
        self.assertEqual(text.paths_in("see cortex/paths.py and guard.py"), ["cortex/paths.py", "guard.py"])
        self.assertEqual(text.paths_in("src\\cortex\\guard.py"), ["src/cortex/guard.py"])
        self.assertEqual(text.paths_in("version 2.1.287, e.g. nothing, and i.e. here"), [])

    def test_headline_and_gist_are_short_and_deterministic(self):
        self.assertLessEqual(len(text.make_headline("word " * 60)), 93)
        body = "```\ncode block\n```\n\nFirst real sentence. Second one here. Third one is dropped."
        self.assertEqual(text.make_gist(body), "First real sentence. Second one here.")
        self.assertEqual(text.make_gist(body), text.make_gist(body))

    def test_content_hash_ignores_case_and_spacing_but_not_words(self):
        self.assertEqual(text.content_hash("A  Title", "Some   body"), text.content_hash("a title", "some body"))
        self.assertNotEqual(text.content_hash("A", "pool is 10"), text.content_hash("A", "pool is 50"))

    def test_token_estimate_is_about_four_characters_each(self):
        self.assertEqual(text.estimate_tokens(""), 0)
        self.assertEqual(text.estimate_tokens("x" * 400), 100)


class TestStore(PalaceCase):
    def test_a_new_store_has_the_schema_and_reopens(self):
        self.assertEqual(self.store.conn.execute("PRAGMA user_version").fetchone()[0], store_mod.SCHEMA_VERSION)
        names = {r[0] for r in self.store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in ("memory", "posting", "anchor", "link", "event", "feedback", "gfile", "gedge", "gsym"):
            self.assertIn(table, names)
        again = store_mod.Store(self.store.path)
        self.addCleanup(again.close)
        self.assertEqual(again.count(None), 0)

    def test_a_palace_from_a_newer_cortex_is_refused_and_left_alone(self):
        self.store.conn.execute("PRAGMA user_version = 99")
        self.store.close()
        before = _read_bytes(self.store.path)
        with self.assertRaises(PalaceError) as ctx:
            store_mod.Store(self.store.path)
        self.assertIn("newer Cortex", str(ctx.exception))
        self.assertEqual(_read_bytes(self.store.path), before)

    def test_a_refused_palace_does_not_stay_locked(self):
        self.store.conn.execute("PRAGMA user_version = 99")
        self.store.close()
        with self.assertRaises(PalaceError):
            store_mod.Store(self.store.path)
        os.remove(self.store.path)                          # fails on Windows if a connection leaked
        self.assertFalse(os.path.exists(self.store.path))

    def test_a_file_that_is_not_a_database_is_refused_and_left_alone(self):
        path = os.path.join(self.tmp, "garbage.db")
        with open(path, "wb") as fh:
            fh.write(b"this is not a database " * 40)
        with self.assertRaises(PalaceError) as ctx:
            store_mod.Store(path)
        self.assertIn("left untouched", str(ctx.exception))
        self.assertEqual(_read_bytes(path), b"this is not a database " * 40)

    def test_opening_a_missing_palace_without_create_says_what_to_do(self):
        with self.assertRaises(PalaceError) as ctx:
            store_mod.Store(os.path.join(self.tmp, "nope", "palace.db"), create=False)
        self.assertIn("cc palace init", str(ctx.exception))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "nope")))

    def test_a_failed_transaction_leaves_nothing_behind(self):
        with self.assertRaises(RuntimeError):
            with self.store.tx():
                self.store.meta_set("k", "v")
                raise RuntimeError("boom")
        self.assertIsNone(self.store.meta_get("k"))

    def test_nested_transactions_join_the_outer_one(self):
        with self.assertRaises(RuntimeError):
            with self.store.tx():
                with self.store.tx():
                    self.store.meta_set("inner", "1")
                self.store.meta_set("outer", "1")
                raise RuntimeError("boom")
        self.assertIsNone(self.store.meta_get("inner"))
        self.assertIsNone(self.store.meta_get("outer"))

    def test_two_connections_see_each_others_writes(self):
        other = store_mod.Store(self.store.path)
        self.addCleanup(other.close)
        write.remember(self.store, "From the first", "written through connection one")
        self.assertEqual(other.count("active"), 1)

    def test_several_writers_at_once_lose_nothing(self):
        errors = []

        def worker(n):
            st = None
            try:
                st = store_mod.Store(self.store.path)
                for i in range(8):
                    write.remember(st, "Worker %d note %d" % (n, i), "unique body number %d from worker %d" % (i, n))
            except Exception as exc:                       # noqa: BLE001 - the test reports it
                errors.append(repr(exc))
            finally:
                if st is not None:
                    st.close()

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.store.count("active"), 32)

    def test_ids_resolve_by_unique_prefix_only(self):
        a = write.remember(self.store, "First", "alpha body text")["id"]
        self.assertEqual(self.store.resolve_id(a[:6]), a)
        with self.assertRaises(PalaceError):
            self.store.resolve_id("zzzz")
        with self.assertRaises(PalaceError):
            self.store.resolve_id("")
        write.remember(self.store, "Second", "beta body text")
        with self.assertRaises(PalaceError) as ctx:
            self.store.resolve_id("m_")                    # every id starts with this: ambiguous
        self.assertIn("matches 2", str(ctx.exception))

    def test_percent_and_underscore_are_not_wildcards_in_an_id_lookup(self):
        write.remember(self.store, "One", "body one is here")
        for pattern in ("%", "_"):
            with self.assertRaises(PalaceError):
                self.store.resolve_id(pattern)

    def test_purge_removes_the_memory_and_everything_derived_from_it(self):
        write_files(self.root, {"cortex/guard.py": "x = 1\n"})
        r = write.remember(self.store, "Secret-ish topic", "about cortex/guard.py quirks", project_root=self.root)
        self.store.record_injection(r["id"], "s1", "gist")
        other = write.remember(self.store, "Replacement topic", "newer take on the topic", supersedes=[r["id"]])
        self.store.purge(r["id"])
        for table, col in (("memory", "id"), ("posting", "memory"), ("fieldlen", "memory"),
                           ("anchor", "memory"), ("feedback", "memory")):
            n = self.store.conn.execute("SELECT COUNT(*) FROM %s WHERE %s = ?" % (table, col), (r["id"],)).fetchone()[0]
            self.assertEqual(n, 0, table)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM link WHERE src = ? OR dst = ?",
                                                 (r["id"], r["id"])).fetchone()[0], 0)
        self.assertIsNotNone(self.store.get(other["id"]))
        events = [dict(e) for e in self.store.conn.execute("SELECT op, detail FROM event WHERE op = 'purge'")]
        self.assertEqual(len(events), 1)
        self.assertNotIn("Secret-ish", json.dumps(events))   # the audit trail keeps no content

    def test_update_refuses_unknown_or_protected_fields(self):
        r = write.remember(self.store, "T", "some body here")
        with self.assertRaises(PalaceError):
            self.store.update(r["id"], bogus=1)
        with self.assertRaises(PalaceError):
            self.store.update(r["id"], id="other")

    def test_timestamps_round_trip(self):
        self.assertEqual(store_mod.parse_iso(store_mod.iso(NOW)), NOW)
        self.assertIsNone(store_mod.parse_iso(None))
        self.assertIsNone(store_mod.parse_iso("not a date"))
        self.assertEqual(store_mod.parse_iso("2026-10-12T12:00:00+00:00"), NOW)

    def test_default_synonyms_and_project_synonyms(self):
        al = self.store.aliases()
        self.assertIn(text.stem("authentication"), al[text.stem("login")])
        self.store.conn.execute("INSERT INTO alias(term, grp) VALUES('profile','a'), ('account','a')")
        al = self.store.aliases()
        self.assertIn(text.stem("account"), al[text.stem("profile")])


class TestProjectIdentity(PalaceCase):
    def _repo(self, name):
        repo = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(repo, ".git"))
        os.makedirs(os.path.join(repo, "src", "deep"))
        return repo

    def test_subfolders_of_a_repository_share_one_palace(self):
        repo = self._repo("alpha")
        key, root = store_mod.project_identity(os.path.join(repo, "src", "deep"))
        self.assertEqual(key, store_mod.project_identity(repo)[0])
        self.assertEqual(os.path.normcase(root), os.path.normcase(repo))

    def test_different_repositories_get_different_palaces(self):
        self.assertNotEqual(store_mod.project_identity(self._repo("alpha"))[0],
                            store_mod.project_identity(self._repo("beta"))[0])

    def test_a_worktree_shares_the_palace_of_its_repository(self):
        repo = self._repo("gamma")
        wt_git = os.path.join(repo, ".git", "worktrees", "wt")
        os.makedirs(wt_git)
        with open(os.path.join(wt_git, "commondir"), "w", encoding="utf-8") as fh:
            fh.write("../..\n")
        worktree = os.path.join(self.tmp, "gamma-wt")
        os.makedirs(worktree)
        with open(os.path.join(worktree, ".git"), "w", encoding="utf-8") as fh:
            fh.write("gitdir: %s\n" % wt_git)
        self.assertEqual(store_mod.project_identity(worktree)[0], store_mod.project_identity(repo)[0])

    def test_outside_git_the_folder_itself_is_the_project(self):
        a, b = os.path.join(self.tmp, "plain-a"), os.path.join(self.tmp, "plain-b")
        os.makedirs(a)
        os.makedirs(b)
        self.assertNotEqual(store_mod.project_identity(a)[0], store_mod.project_identity(b)[0])

    def test_the_palace_lives_under_cortex_home_not_in_the_repository(self):
        repo = self._repo("delta")
        path = store_mod.db_path("project", repo)
        self.assertTrue(path.startswith(self.home), path)
        self.assertNotIn(repo, path)
        self.assertEqual(store_mod.db_path("global"), os.path.join(self.home, "palace", "global", "palace.db"))


class TestWrite(PalaceCase):
    def R(self, title, body, **kw):
        kw.setdefault("project_root", self.root)
        return write.remember(self.store, title, body, **kw)

    def test_a_memory_is_stored_with_three_resolutions_and_the_right_tier(self):
        r = self.R("Why we chose SQLite", "We decided on SQLite instead of JSON files. Several sessions write at once.")
        row = self.store.get(r["id"])
        self.assertEqual((r["action"], row["kind"], row["tier"], row["status"]), ("created", "decision", 3, "active"))
        self.assertTrue(row["headline"] and row["gist"] and row["body"])
        self.assertEqual(row["recorded_at"], store_mod.iso(NOW))

    def test_nothing_to_remember_is_an_error_not_an_empty_memory(self):
        for args in (("", ""), ("  ", "\n")):
            with self.assertRaises(PalaceError):
                self.R(*args)
        self.assertEqual(self.store.count(None), 0)

    def test_a_title_is_derived_from_the_body_and_a_body_from_the_title(self):
        a = self.R("", "First line becomes the title\nand the rest follows")
        self.assertEqual(self.store.get(a["id"])["title"], "First line becomes the title")
        b = self.R("Only a title", "")
        self.assertEqual(self.store.get(b["id"])["body"], "Only a title")

    def test_invalid_choices_are_refused_before_anything_is_written(self):
        for kw in ({"kind": "bogus"}, {"trust": "nobody"}, {"tier": 9}, {"importance": 1.5}, {"confidence": -0.1}):
            with self.assertRaises(PalaceError):
                self.R("Title", "some body text", **kw)
        self.assertEqual(self.store.count(None), 0)

    def test_an_identical_memory_is_not_stored_twice(self):
        a = self.R("Same", "exactly the same words in the body")
        b = self.R("same", "Exactly   the same words in the body")
        self.assertEqual((b["action"], b["id"]), ("duplicate", a["id"]))
        self.assertEqual(self.store.count("active"), 1)

    def test_a_duplicate_can_still_pin_the_original(self):
        a = self.R("Same", "exactly the same words in the body")
        self.R("Same", "exactly the same words in the body", pinned=True)
        self.assertEqual(self.store.get(a["id"])["pinned"], 1)

    def test_a_changed_number_is_not_mistaken_for_a_duplicate(self):
        # The old palace discarded the second of these as "already recorded".
        a = self.R("Connection pool", "The pool size is 10 connections for the api service during normal load.")
        b = self.R("Database pool config", "The pool size is 50 connections for the api service during normal load.")
        self.assertEqual(b["action"], "created")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(self.store.count("active"), 2)

    def test_a_same_titled_decision_replaces_the_old_one_and_keeps_it_as_history(self):
        a = self.R("Connection pool size", "The pool size is 10 connections.", kind="fact")
        b = self.R("Connection pool size", "The pool size is 50 connections after the outage.", kind="fact")
        self.assertEqual((b["action"], b["superseded"]), ("updated", [a["id"]]))
        old = self.store.get(a["id"])
        self.assertEqual((old["status"], old["superseded_by"], old["valid_to"]),
                         ("superseded", b["id"], store_mod.iso(NOW)))
        self.assertEqual(self.store.count("active"), 1)
        self.assertEqual(self.store.count("superseded"), 1)
        self.assertTrue(any(l["rel"] == "supersedes" and l["src"] == b["id"] for l in self.store.links_of(a["id"])))

    def test_episodes_with_the_same_title_are_both_kept(self):
        # A failure that recurs is two events, not one updated fact.
        self.R("Test failed", "The suite failed on friday with a timeout error", kind="failure")
        self.R("Test failed", "The suite failed on monday with a disk full error", kind="failure")
        self.assertEqual(self.store.count("active"), 2)

    def test_explicit_supersession_by_id_prefix(self):
        a = self.R("Old approach", "We used polling to check the status of jobs")
        b = self.R("New approach", "We now use push notifications for the status of jobs", supersedes=[a["id"][:7]])
        self.assertEqual(b["superseded"], [a["id"]])
        self.assertEqual(self.store.get(a["id"])["status"], "superseded")

    def test_a_near_identical_rewording_is_a_duplicate(self):
        base = " ".join("word%d" % i for i in range(40))
        a = self.R("Long note", base + " end")
        b = self.R("Long note", base + " finish")
        self.assertEqual((b["action"], b["id"]), ("duplicate", a["id"]))

    def test_a_long_text_that_differs_only_by_one_number_is_not_a_duplicate(self):
        # Everything else (word set, word order) is >90% identical, so only the number rule can tell them apart.
        words = " ".join("detail%s" % chr(97 + i) for i in range(26))
        a = self.R("Service limits", "The service listens on port 8080 and handles " + words + " requests.")
        b = self.R("Service limits", "The service listens on port 9090 and handles " + words + " requests.",
                   kind="note")
        self.assertEqual(b["action"], "created")
        self.assertNotEqual(a["id"], b["id"])

    def test_a_memory_that_adds_substantial_new_content_is_not_a_duplicate_of_the_shorter_one(self):
        base = " ".join("alpha%s" % chr(97 + i) for i in range(20))
        a = self.R("Growing note", base)
        b = self.R("Growing note", base + " " + " ".join("beta%s" % chr(97 + i) for i in range(5)), kind="note")
        self.assertEqual(b["action"], "created")                  # 80% alike: related, not the same
        self.assertEqual(self.store.count("active"), 2)
        self.assertIn(a["id"], b["related"])

    def test_the_same_words_in_a_different_order_are_not_a_duplicate(self):
        # Opposite meanings, identical word sets: a bag-of-words check would merge them.
        a = self.R("Dependency direction", "The auth service depends on the cache layer for sessions and tokens.")
        b = self.R("Dependency direction", "The cache layer depends on the auth service for sessions and tokens.",
                   kind="note")
        self.assertEqual(b["action"], "created")
        self.assertNotEqual(a["id"], b["id"])

    def test_single_digit_numbers_count_as_differences_too(self):
        # Lone digits used to be dropped from the index terms, so "5" and "8" looked identical.
        a = self.R("Retry policy", "The client retries 5 times with a short pause between each request attempt.")
        b = self.R("Retry settings", "The client retries 8 times with a short pause between each request attempt.")
        self.assertEqual(b["action"], "created")
        self.assertNotEqual(a["id"], b["id"])

    def test_a_similar_but_distinct_memory_is_linked_as_related(self):
        a = self.R("Cache eviction", "The cache evicts the least recently used entries when it is full of data.",
                   kind="fact")
        b = self.R("Cache sizing", "The cache evicts the least recently used entries when memory is full, "
                                   "sized by budget.", kind="fact")
        self.assertEqual(b["action"], "created")
        self.assertIn(a["id"], b["related"])

    def test_secrets_never_reach_the_database_or_the_audit_trail(self):
        key = "sk-ant-abcdefghijklmnopqrstuvwxyz123456"
        r = self.R("Config note " + key, "We used password=hunter2hunter and " + key + " in the script")
        self.assertEqual(sorted(r["redacted"]), ["anthropic-key", "assignment"])
        dump = json.dumps([dict(x) for x in self.store.conn.execute("SELECT * FROM memory")]) + \
            json.dumps([dict(x) for x in self.store.conn.execute("SELECT * FROM event")]) + \
            json.dumps([dict(x) for x in self.store.conn.execute("SELECT * FROM posting")])
        self.assertNotIn("hunter2hunter", dump)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", dump)

    def test_kind_is_inferred_from_the_wording(self):
        cases = [("Always gate risky features", "Always put them behind a flag.", "rule"),
                 ("Prefer small commits", "Prefer small commits over large ones.", "preference"),
                 ("We decided to use SQLite", "Decision: SQLite instead of JSON files.", "decision"),
                 ("Bug in the importer", "Traceback: KeyError. The root cause was a missing key.", "failure"),
                 ("Typo", "Fixed the typo in the importer by adding a default value.", "fix"),
                 ("How to run tests", "steps: run `python tests/run_all_tests.py`", "recipe"),
                 ("Module layout", "The component depends on the schema layer.", "structure"),
                 ("Random thought", "Nothing special here at all.", "note")]
        for title, body, expected in cases:
            self.assertEqual(write.infer_kind(title, body), expected, title)

    def test_default_tiers_follow_kind_and_core_is_never_a_default(self):
        for kind, tier in write.KIND_TIER.items():
            self.assertNotEqual(tier, 1, kind)
        self.assertEqual(self.R("A rule of thumb", "Always keep it small and clear.", kind="rule")["tier"], 3)
        self.assertEqual(self.R("Chosen core", "Explicitly core content here", tier=1)["tier"], 1)

    def test_tags_are_cleaned_and_searchable(self):
        r = self.R("Tagged", "plain body words only", tags="#Cache, perf  #Cache")
        self.assertEqual(json.loads(self.store.get(r["id"])["tags"]), ["cache", "perf"])
        self.assertTrue(self.store.conn.execute(
            "SELECT 1 FROM posting WHERE memory = ? AND field = 'tags' AND term = ?",
            (r["id"], text.stem("cache"))).fetchone())

    def test_importing_the_same_source_twice_stores_it_once(self):
        a = self.R("Imported", "from somewhere else entirely", source_ref="legacy:abc:1")
        b = self.R("Imported", "from somewhere else entirely", source_ref="legacy:abc:1")
        self.assertEqual((b["action"], b["id"]), ("duplicate", a["id"]))

    def test_files_in_the_text_become_anchors_only_when_they_exist(self):
        write_files(self.root, {"cortex/guard.py": "x = 1\n"})
        outside = os.path.join(self.tmp, "elsewhere", "other.py")
        r = self.R("About guards", "See cortex/guard.py, missing/file.py and %s" % outside)
        self.assertEqual([a["file"] for a in self.store.anchors_of(r["id"])], ["cortex/guard.py"])
        self.assertEqual(self.store.get(r["id"])["freshness"], "fresh")

    def test_an_absolute_path_inside_the_project_is_stored_relative(self):
        write_files(self.root, {"cortex/guard.py": "x = 1\n"})
        r = self.R("About guards", "notes", paths=[os.path.join(self.root, "cortex", "guard.py")])
        self.assertEqual([a["file"] for a in self.store.anchors_of(r["id"])], ["cortex/guard.py"])

    def test_no_project_means_no_anchors(self):
        r = write.remember(self.store, "About guards", "See cortex/guard.py", project_root=None)
        self.assertEqual((r["anchors"], self.store.anchors_of(r["id"])), (0, []))

    def test_a_failure_while_indexing_leaves_no_half_written_memory(self):
        def boom(*a, **k):
            raise RuntimeError("disk full")
        self.store.index_memory = boom
        with self.assertRaises(RuntimeError):
            self.R("Doomed", "never fully stored")
        del self.store.index_memory
        self.assertEqual(self.store.count(None), 0)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM posting").fetchone()[0], 0)

    def test_an_index_from_an_older_analyzer_is_rebuilt_once(self):
        r = self.R("Settings for caching", "The cache settings live in the config file.")
        self.store.meta_set("analyzer", "1")                      # as if built by the old analyzer
        self.store.conn.execute("DELETE FROM posting")
        self.assertEqual(write.ensure_index_current(self.store), 1)
        self.assertEqual(write.ensure_index_current(self.store), 0)
        self.assertTrue(self.store.conn.execute("SELECT 1 FROM posting WHERE memory = ?", (r["id"],)).fetchone())
        self.assertEqual(str(self.store.meta_get("analyzer")), str(text.ANALYZER_VERSION))

    def test_archive_restore_pin_and_tier(self):
        a = self.R("Note", "an ordinary note about nothing in particular")["id"]
        write.archive(self.store, a)
        self.assertEqual(self.store.get(a)["status"], "archived")
        write.archive(self.store, a, restore=True)
        self.assertEqual(self.store.get(a)["status"], "active")
        write.set_pinned(self.store, a)
        self.assertEqual(self.store.get(a)["pinned"], 1)
        write.set_pinned(self.store, a, False)
        self.assertEqual(self.store.get(a)["pinned"], 0)
        write.set_tier(self.store, a, 1)
        self.assertEqual(self.store.get(a)["tier"], 1)
        with self.assertRaises(PalaceError):
            write.set_tier(self.store, a, 7)

    def test_a_superseded_memory_cannot_be_restored_over_its_replacement(self):
        a = self.R("Thing", "first version of the thing is described here", kind="fact")["id"]
        self.R("Thing", "second version of the thing replaces it entirely", kind="fact")
        with self.assertRaises(PalaceError):
            write.archive(self.store, a, restore=True)

    def test_a_memory_cannot_replace_itself(self):
        a = self.R("Thing", "some content about the thing")["id"]
        with self.assertRaises(PalaceError):
            write.supersede(self.store, a, a)


class TestScaling(PalaceCase):
    """Finding similar memories must not slow down as the palace grows.

    Measured in SQLite virtual-machine steps (deterministic, unlike wall-clock time). The first version
    let SQLite scan every memory for every comparison, so maintenance went from seconds to minutes.
    """

    def _populate(self, store, n, seed):
        import random
        rnd = random.Random(seed)
        pool = ["term%d" % i for i in range(600)]
        weights = [1.0 / (i + 1) ** 0.8 for i in range(len(pool))]
        for i in range(n):
            title = " ".join(rnd.choices(pool, weights, k=4))
            body = " ".join(rnd.choices(pool, weights, k=40)) + " item%d" % i
            write.remember(store, title, body)

    def _steps(self, store, probes):
        steps = [0]

        def tick():
            steps[0] += 1
            return 0
        store.conn.set_progress_handler(tick, 100)
        try:
            for tset in probes:
                write._similar(store, tset, "note")
        finally:
            store.conn.set_progress_handler(None, 0)
        return steps[0]

    def test_work_per_comparison_does_not_grow_with_the_palace(self):
        import random
        rnd = random.Random(99)
        pool = ["term%d" % i for i in range(600)]
        probes = [set(text.terms(" ".join(rnd.choices(pool, k=30)))) for _ in range(25)]
        small, large = self.open_store("small.db"), self.open_store("large.db")
        self._populate(small, 150, seed=1)
        self._populate(large, 900, seed=1)
        small_steps, large_steps = self._steps(small, probes), self._steps(large, probes)
        # Six times as many memories; per-call work may grow a little (longer posting lists) but nowhere near 6x.
        self.assertLess(large_steps, small_steps * 3.0, (small_steps, large_steps))


if __name__ == "__main__":
    unittest.main()
