#!/usr/bin/env python3
"""
The project map (cc graph): its data, its local server, the session registry that decides when the
floating button appears, the hook that feeds that registry, and the front-end's safety rules.

What is NOT tested here, and why: the pixels, and the tkinter button itself. A button on a real screen
is checked by hand (``cc graph button start --selftest`` opens the map, confirms its window exists,
closes it, confirms it is gone). Everything the button *decides* is in ``sessions.py`` and is tested.
"""

import http.client
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from palace_testkit import PROJECT_DIR, PalaceCase, touch_graph, write_files, write_graph  # noqa: E402

from cortex.atlas import data as atlas_data  # noqa: E402
from cortex.atlas import sessions  # noqa: E402
from cortex.atlas.data import Atlas  # noqa: E402
from cortex.atlas.server import AtlasServer  # noqa: E402
from cortex.palace import graph, write  # noqa: E402
from cortex.palace import store as store_mod  # noqa: E402

STATIC = os.path.join(PROJECT_DIR, "cortex", "atlas", "static")
HOOK = os.path.join(PROJECT_DIR, "scripts", "cortex-session-hook.py")


class AtlasCase(PalaceCase):
    """A small project with a graph, a palace holding notes, and an Atlas over both."""

    FILES = {"a.py": {"symbols": ["load_config", "Loader"], "community": 0, "ast_hash": "h-a"},
             "b.py": {"symbols": ["parse"], "community": 0, "ast_hash": "h-b"},
             "c.py": {"symbols": ["render"], "community": 1, "ast_hash": "h-c"},
             "lone.py": {"symbols": [], "community": 2, "ast_hash": "h-l"}}

    def setUp(self):
        super().setUp()
        write_files(self.root, {name: "# %s\n" % name for name in self.FILES})
        self.graph_path = write_graph(self.root, self.FILES, links=[("a.py", "b.py", "calls", "EXTRACTED"),
                                                                     ("b.py", "c.py", "calls", "INFERRED")])
        graph.sync(self.store, self.root)               # as `cc palace remember` does before it writes a note
        self.atlas = Atlas(self.root, palace_path=self.store.path)
        self.addCleanup(self.atlas.close)

    def note(self, title, body, **kw):
        return write.remember(self.store, title, body, project_root=self.root, **kw)

    def change_graph_hash(self, name="a.py", value="CHANGED"):
        files = {k: dict(v) for k, v in self.FILES.items()}
        files[name]["ast_hash"] = value
        write_graph(self.root, files, links=[("a.py", "b.py", "calls", "EXTRACTED"),
                                             ("b.py", "c.py", "calls", "INFERRED")])
        touch_graph(self.graph_path)


class TestOverview(AtlasCase):
    def test_files_links_and_the_notes_pinned_to_them(self):
        made = self.note("Config loading", "load_config in a.py reads the file once.", kind="decision", paths=["a.py"])
        o = self.atlas.overview()
        names = [f["id"] for f in o["files"]]
        self.assertEqual(names, sorted(names))
        self.assertEqual(set(names), set(self.FILES))
        pairs = {(names[a], names[b]) for a, b, _w in o["links"]}
        self.assertIn(("a.py", "b.py"), pairs)
        memory = [m for m in o["memories"] if m["id"] == made["id"]][0]
        self.assertEqual([names[i] for i in memory["files"]], ["a.py"])
        self.assertEqual(memory["fresh"], "fresh")
        self.assertEqual({f["id"]: f["health"] for f in o["files"]}["a.py"], "fresh")
        self.assertEqual(o["graph"]["files"], 4)
        self.assertTrue(o["graph"]["present"])
        self.assertTrue(o["palace"]["present"])
        json.dumps(o)                                   # everything in it is plain JSON

    def test_a_file_nothing_links_to_is_still_listed_with_no_links(self):
        o = self.atlas.overview()
        lone = [f for f in o["files"] if f["id"] == "lone.py"][0]
        self.assertEqual((lone["degree"], lone["memories"], lone["health"]), (0, 0, None))

    def test_a_changed_file_turns_its_note_to_verify_and_is_counted(self):
        self.note("Config loading", "load_config in a.py reads the file once.", kind="decision", paths=["a.py"])
        self.assertEqual(self.atlas.overview()["palace"]["attention"], 0)
        self.change_graph_hash()
        o = self.atlas.overview()
        self.assertEqual(o["palace"]["attention"], 1)
        self.assertEqual(o["memories"][0]["fresh"], "verify")
        self.assertEqual({f["id"]: f["health"] for f in o["files"]}["a.py"], "verify")

    def test_a_note_about_a_file_that_is_gone_is_orphaned(self):
        made = self.note("Old helper", "The retry helper lived in gone.py.", kind="fact")
        self.store.add_anchor(made["id"], "file", "gone.py")
        o = self.atlas.overview()
        memory = [m for m in o["memories"] if m["id"] == made["id"]][0]
        self.assertEqual(memory["fresh"], "orphaned")
        self.assertIn("gone.py", [f["id"] for f in o["files"]])      # still drawn, so the red note has a home
        self.assertGreaterEqual(o["palace"]["attention"], 1)

    def test_a_worse_note_wins_the_files_health(self):
        good = self.note("Fine", "a.py is fine.", kind="fact", paths=["a.py"])
        bad = self.note("Stale", "a.py does the thing.", kind="fact", paths=["a.py"])
        self.store.conn.execute("UPDATE anchor SET ast_hash = 'old' WHERE memory = ?", (bad["id"],))
        o = self.atlas.overview()
        self.assertEqual({f["id"]: f["health"] for f in o["files"]}["a.py"], "verify")
        self.assertEqual({m["id"]: m["fresh"] for m in o["memories"]}[good["id"]], "fresh")

    def test_without_a_graph_the_files_your_notes_mention_are_still_shown(self):
        shutil.rmtree(os.path.join(self.root, "graphify-out"))
        self.note("Config loading", "load_config in a.py reads the file once.", kind="decision", paths=["a.py"])
        o = self.atlas.overview()
        self.assertFalse(o["graph"]["present"])
        self.assertEqual([f["id"] for f in o["files"]], ["a.py"])
        self.assertEqual(o["links"], [])
        self.assertEqual(len(o["memories"]), 1)

    def test_without_a_palace_the_code_graph_alone_is_shown(self):
        atlas = Atlas(self.root, palace_path=os.path.join(self.tmp, "no-such-palace.db"))
        self.addCleanup(atlas.close)
        o = atlas.overview()
        self.assertFalse(o["palace"]["present"])
        self.assertEqual(o["memories"], [])
        self.assertEqual(len(o["files"]), 4)
        scratch = atlas._scratch
        self.assertTrue(scratch and os.path.isdir(scratch))
        atlas.close()
        self.assertFalse(os.path.exists(scratch), "the throwaway cache must be removed on close")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "no-such-palace.db")), "must not create a palace")

    def test_a_palace_from_a_newer_cortex_does_not_hide_the_map(self):
        self.store.conn.execute("PRAGMA user_version = 99")
        o = self.atlas.overview()
        self.assertFalse(o["palace"]["present"])
        self.assertIn("newer", o["palace"]["error"].lower())
        self.assertEqual(len(o["files"]), 4)

    def test_with_nothing_at_all_it_is_empty_not_an_error(self):
        empty = os.path.join(self.tmp, "empty-project")
        os.makedirs(empty)
        atlas = Atlas(empty, palace_path=os.path.join(self.tmp, "none.db"))
        self.addCleanup(atlas.close)
        o = atlas.overview()
        self.assertEqual((o["files"], o["memories"], o["links"]), ([], [], []))
        self.assertFalse(o["graph"]["present"])

    def test_too_many_files_keeps_the_best_connected_and_says_so(self):
        with mock.patch.object(atlas_data, "MAX_FILES", 3):
            o = self.atlas.overview()
        self.assertEqual(len(o["files"]), 3)
        self.assertEqual(o["truncated"]["files"], 1)
        self.assertNotIn("lone.py", [f["id"] for f in o["files"]])      # the unconnected one goes first
        indexes = {i for link in o["links"] for i in link[:2]}
        self.assertTrue(all(i < 3 for i in indexes), "no link may point at a dropped file")

    def test_the_unconnected_file_is_dropped_even_when_it_sorts_first(self):
        # An alphabetical cut would keep "aaa_lonely.py"; keeping the best connected is the whole point.
        files = {"aaa_lonely.py": {"symbols": [], "community": 5}, "b.py": {"symbols": ["f"]},
                 "c.py": {"symbols": ["g"]}, "d.py": {"symbols": ["h"]}}
        write_files(self.root, {name: "" for name in files})
        write_graph(self.root, files, links=[("b.py", "c.py", "calls", "EXTRACTED"), ("c.py", "d.py", "calls", "EXTRACTED")])
        touch_graph(self.graph_path)
        with mock.patch.object(atlas_data, "MAX_FILES", 3):
            o = self.atlas.overview()
        self.assertEqual(sorted(f["id"] for f in o["files"]), ["b.py", "c.py", "d.py"])

    def test_too_many_notes_reports_how_many_were_not_drawn(self):
        for i in range(5):
            self.note("Note %d" % i, "Something about a.py number %d." % i, kind="fact", paths=["a.py"])
        with mock.patch.object(atlas_data, "MAX_MEMORIES", 2):
            o = self.atlas.overview()
        self.assertEqual(len(o["memories"]), 2)
        self.assertEqual(o["truncated"]["memories"], 3)

    def test_status_is_small_and_never_raises_even_for_a_broken_palace(self):
        s = self.atlas.status()
        self.assertEqual((s["graph"], s["files"], s["palace"]), (True, 4, True))
        broken = os.path.join(self.tmp, "broken.db")
        with open(broken, "wb") as fh:
            fh.write(b"this is not a database at all" * 50)
        atlas = Atlas(self.root, palace_path=broken)
        self.addCleanup(atlas.close)
        s = atlas.status()                                   # must not raise
        self.assertIsInstance(s, dict)
        self.assertEqual(s["project"], atlas.name)


class TestSymbolsMemoryAndSearch(AtlasCase):
    def test_symbols_of_a_file_with_what_they_connect_to(self):
        s = self.atlas.symbols("a.py")
        self.assertEqual(sorted(x["label"] for x in s["symbols"]), ["Loader", "load_config"])
        self.assertEqual({x["kind"] for x in s["symbols"]}, {"function", "class"})
        self.assertEqual(s["symbols"][0]["line"], 10)
        self.assertEqual(self.atlas.symbols("lone.py")["symbols"], [])

    def test_symbols_of_an_unknown_file_is_empty_not_an_error(self):
        for name in ("nope.py", "", "../../etc/passwd", "a.py\x00"):
            self.assertEqual(self.atlas.symbols(name)["symbols"], [], name)

    def test_symbol_links_never_leave_the_graph_and_skip_structure(self):
        s = self.atlas.symbols("b.py")
        ids = {x["id"] for x in s["symbols"]} | {x["id"] for x in s["external"]}
        self.assertTrue(all(link["s"] in ids and link["t"] in ids for link in s["links"]))
        self.assertNotIn("contains", {link["relation"] for link in s["links"]})

    def test_memory_detail_has_anchors_with_state_and_what_it_replaced(self):
        first = self.note("Config loading", "Old: load_config reads twice.", kind="decision", paths=["a.py"])
        second = self.note("Config loading", "New: load_config reads once.", kind="decision", paths=["a.py"])
        m = self.atlas.memory(second["id"])
        self.assertEqual(m["body"], "New: load_config reads once.")
        self.assertEqual(m["anchors"][0]["file"], "a.py")
        self.assertEqual(m["anchors"][0]["state"], "fresh")
        self.assertEqual([x["id"] for x in m["supersedes"]], [first["id"]])
        self.assertEqual(m["fresh"], "fresh")
        self.assertNotIn("content_hash", m)

    def test_memory_detail_accepts_an_id_prefix_and_refuses_unknown_ids(self):
        made = self.note("Config loading", "load_config reads once.", kind="fact", paths=["a.py"])
        self.assertEqual(self.atlas.memory(made["id"][:6])["id"], made["id"])
        self.assertIsNone(self.atlas.memory("m_does_not_exist"))
        self.assertIsNone(self.atlas.memory(""))

    def test_search_finds_files_symbols_and_notes(self):
        self.note("Parser strictness", "parse rejects unknown keys.", kind="decision", paths=["b.py"])
        kinds = {(r["type"], r["label"]) for r in self.atlas.search("pars")}
        self.assertIn(("symbol", "parse"), kinds)
        self.assertIn(("memory", "Parser strictness"), kinds)
        self.assertIn(("file", "b.py"), {(r["type"], r["label"]) for r in self.atlas.search("b.py")})
        self.assertEqual(self.atlas.search("x"), [])                  # one letter is not a search
        self.assertEqual(self.atlas.search(""), [])

    def test_search_treats_percent_and_underscore_as_ordinary_characters(self):
        write_files(self.root, {"x_y.py": "", "xzy.py": ""})
        write_graph(self.root, dict(self.FILES, **{"x_y.py": {"symbols": []}, "xzy.py": {"symbols": []}}))
        touch_graph(self.graph_path)
        self.atlas.overview()                                          # sync
        hits = {r["label"] for r in self.atlas.search("x_y")}
        self.assertEqual(hits, {"x_y.py"})
        self.assertEqual(self.atlas.search("%%"), [])
        self.assertEqual(self.atlas.search("a'; DROP TABLE memory; --"), [])
        self.assertEqual(self.store.count(), 0)                        # nothing was damaged


class TestServer(AtlasCase):
    def setUp(self):
        super().setUp()
        self.note("Config loading", "load_config reads once.", kind="decision", paths=["a.py"])
        self.server = AtlasServer(self.atlas, token="test-key").start()
        self.addCleanup(self.server.stop)

    def get(self, path, key="test-key", host=None, method="GET", header_key=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=15)
        headers = {"Host": host if host is not None else "127.0.0.1:%d" % self.server.port}
        if key is not None:
            if header_key:
                headers["X-Atlas-Key"] = key
            else:
                path += ("&" if "?" in path else "?") + "k=" + key
        conn.request(method, path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        headers_out = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, headers_out, body

    def test_it_listens_on_loopback_only(self):
        self.assertEqual(self.server._httpd.server_address[0], "127.0.0.1")

    def test_the_page_and_every_api_route_need_the_key(self):
        for path in ("/", "/api/overview", "/api/status", "/api/search?q=abc", "/api/symbols?file=a.py", "/api/memory?id=x"):
            self.assertEqual(self.get(path, key=None)[0], 401, path)
            self.assertEqual(self.get(path, key="wrong")[0] in (401,), True, path)
        self.assertEqual(self.get("/")[0], 200)
        self.assertEqual(self.get("/api/status", header_key=True)[0], 200)      # header form works too

    def test_the_two_script_files_are_public_because_a_script_tag_cannot_send_a_header(self):
        for path in ("/force.js", "/app.js"):
            status, headers, body = self.get(path, key=None)
            self.assertEqual(status, 200, path)
            self.assertIn("javascript", headers["content-type"])
            self.assertGreater(len(body), 500)

    def test_a_foreign_host_header_is_refused_even_with_the_key(self):
        for host in ("evil.example", "evil.example:%d" % self.server.port, "127.0.0.1", "127.0.0.1:1", ""):
            self.assertEqual(self.get("/api/overview", host=host)[0], 403, host)
        self.assertEqual(self.get("/api/overview", host="localhost:%d" % self.server.port)[0], 200)

    def test_it_never_sends_cors_headers_and_forbids_caching_and_framing(self):
        status, headers, _body = self.get("/api/overview")
        self.assertFalse([h for h in headers if h.startswith("access-control")])
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'", headers["content-security-policy"])
        self.assertIn("default-src 'self'", headers["content-security-policy"])
        self.assertEqual(headers["x-content-type-options"], "nosniff")

    def test_overview_search_symbols_memory_and_refresh_return_json(self):
        status, headers, body = self.get("/api/overview")
        o = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(o["files"]), 4)
        self.assertEqual(json.loads(self.get("/api/search?q=load")[2])["results"][0]["type"], "symbol")
        self.assertEqual(len(json.loads(self.get("/api/symbols?file=a.py")[2])["symbols"]), 2)
        mid = o["memories"][0]["id"]
        self.assertEqual(json.loads(self.get("/api/memory?id=" + mid)[2])["id"], mid)
        self.assertEqual(self.get("/api/memory?id=nope")[0], 404)
        self.assertEqual(json.loads(self.get("/api/refresh", method="POST")[2])["project"]["name"], self.atlas.name)
        self.assertEqual(json.loads(self.get("/api/ping")[2])["ok"], True)

    def test_only_get_and_the_one_refresh_post_exist(self):
        self.assertEqual(self.get("/api/overview", method="POST")[0], 405)
        self.assertEqual(self.get("/nope")[0], 404)
        self.assertEqual(self.get("/api/refresh", method="PUT")[0], 501)
        self.assertEqual(self.get("/api/refresh", method="DELETE")[0], 501)

    def test_nothing_is_served_from_disk_by_path(self):
        for path in ("/../../etc/passwd", "/cortex/atlas/server.py", "/%2e%2e/%2e%2e/install.py", "/static/app.js",
                     "/index.html", "//etc/passwd"):
            self.assertIn(self.get(path)[0], (404, 400), path)

    def test_oversized_and_odd_query_values_are_handled(self):
        status, _h, body = self.get("/api/search?q=" + "a" * 5000)
        self.assertEqual(status, 200)
        self.assertEqual(self.get("/api/symbols?file=" + "z" * 5000)[0], 200)
        self.assertEqual(self.get("/api/symbols")[0], 200)                   # missing parameter

    def test_an_internal_error_is_reported_and_the_server_keeps_running(self):
        with mock.patch.object(self.atlas, "overview", side_effect=RuntimeError("boom")):
            status, _h, body = self.get("/api/overview")
        self.assertEqual(status, 500)
        self.assertIn("boom", json.loads(body)["error"])
        self.assertEqual(self.get("/api/ping")[0], 200)

    def test_a_port_already_in_use_is_a_clear_error(self):
        from cortex.atlas import AtlasError
        with self.assertRaises(AtlasError):
            AtlasServer(self.atlas, port=self.server.port).start()

    def test_another_program_cannot_share_our_port_even_by_asking_to_reuse_it(self):
        # The real hijack: on Windows a second socket that sets SO_REUSEADDR could bind our port and get a
        # share of our connections. Our listener must refuse that, not just refuse a copy of itself.
        # (Not covered: the extra SO_EXCLUSIVEADDRUSE option in server.py. On this machine Windows already
        # refuses the bind once our own listener does not set SO_REUSEADDR, so no test can tell the option
        # from its absence. It stays as the standard extra protection for a server.)
        import socket
        intruder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(intruder.close)
        intruder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with self.assertRaises(OSError):
            intruder.bind(("127.0.0.1", self.server.port))
            intruder.listen(1)


class TestFrontEndRules(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
            return fh.read()

    def test_project_text_is_never_inserted_as_html(self):
        # A note that contains "<script>" must be text. These are the ways it would stop being text.
        for name in ("app.js", "force.js", "index.html"):
            body = self.read(name)
            for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
                self.assertNotIn(forbidden, body, "%s uses %s" % (name, forbidden))

    def test_the_page_loads_nothing_from_the_network(self):
        body = self.read("index.html") + self.read("app.js") + self.read("force.js")
        for fragment in ("http://", "https://", "//cdn", "<link rel=\"stylesheet\"", "@import"):
            self.assertNotIn(fragment, body)

    def test_the_page_names_every_element_the_script_looks_up(self):
        import re
        page, script = self.read("index.html"), self.read("app.js")
        wanted = set(re.findall(r"\$\('([\w-]+)'\)", script))
        present = set(re.findall(r'\bid="([\w-]+)"', page))
        self.assertEqual(sorted(wanted - present), [])

    def test_scripts_are_valid_javascript(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        for name in ("app.js", "force.js"):
            result = subprocess.run([node, "--check", os.path.join(STATIC, name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, name + "\n" + result.stderr)


class TestLayoutEngine(unittest.TestCase):
    def test_the_layout_engine_behaves(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        result = subprocess.run([node, os.path.join(PROJECT_DIR, "tests", "atlas_layout_check.js")],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith("ok "), result.stdout)


class SessionCase(PalaceCase):
    """Sessions and button files live under the data dir, which PalaceCase already isolates."""

    def setUp(self):
        super().setUp()
        self.t = 1_000_000.0
        os.makedirs(os.path.join(self.root, "x"), exist_ok=True)


class TestSessionRegistry(SessionCase):
    def test_register_touch_end(self):
        rec = sessions.register_session("s1", self.root, now=self.t)
        self.assertEqual(rec["root"], store_mod.project_identity(self.root)[1])
        self.assertEqual(len(sessions.live_sessions(now=self.t + 1)), 1)
        sessions.touch_session("s1", now=self.t + 100)
        self.assertEqual(sessions.live_sessions(now=self.t + 101)[0]["touched"], self.t + 100)
        self.assertEqual(sessions.live_sessions(now=self.t + 101)[0]["started"], self.t)      # started does not move
        sessions.end_session("s1")
        self.assertEqual(sessions.live_sessions(now=self.t + 102), [])
        sessions.end_session("s1")                                                             # twice is fine
        sessions.touch_session("never-registered")                                            # unknown: nothing happens

    def test_sessions_are_grouped_by_project_and_worktrees_share_one(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        a = sessions.register_session("s1", self.root, now=self.t)
        b = sessions.register_session("s2", other, now=self.t)
        self.assertNotEqual(a["key"], b["key"])
        self.assertEqual([r["session"] for r in sessions.live_sessions(a["key"], now=self.t)], ["s1"])

    def test_a_session_nobody_has_heard_from_for_a_day_is_dropped(self):
        sessions.register_session("old", self.root, now=self.t)
        self.assertEqual(sessions.live_sessions(now=self.t + sessions.SESSION_MAX_AGE - 5)[0]["session"], "old")
        self.assertEqual(sessions.live_sessions(now=self.t + sessions.SESSION_MAX_AGE + 5), [])
        self.assertEqual(os.listdir(sessions._sessions_dir()), [])                              # and the file is gone

    def test_hostile_session_ids_cannot_escape_the_folder(self):
        for sid in ("../../evil", "a/b\\c", "x" * 500, "", "nul", "con:"):
            sessions.register_session(sid, self.root, now=self.t)
        names = os.listdir(sessions._sessions_dir())
        self.assertTrue(all(os.sep not in n and "/" not in n and "\\" not in n for n in names), names)
        self.assertTrue(all(n.startswith("s-") and len(n) < 120 for n in names), names)     # "nul", "con" are not device names
        self.assertFalse(os.path.exists(os.path.join(self.home, "evil.json")))
        self.assertEqual(len(sessions.live_sessions(now=self.t + 1)), len(names))

    def test_a_corrupt_record_is_ignored_and_cleaned_up(self):
        sessions.register_session("s1", self.root, now=self.t)
        bad = os.path.join(sessions._sessions_dir(), "broken.json")
        with open(bad, "w") as fh:
            fh.write("{ not json")
        self.assertEqual(len(sessions.live_sessions(now=self.t + 1)), 1)
        self.assertFalse(os.path.exists(bad))


class TestButtonSupervision(SessionCase):
    def setUp(self):
        super().setUp()
        self.key = store_mod.project_identity(self.root)[0]

    def test_a_beat_means_alive_until_it_goes_stale(self):
        self.assertFalse(sessions.button_alive(self.key, now=self.t))
        sessions.write_beat(self.key, 123, 8000, now=self.t)
        self.assertTrue(sessions.button_alive(self.key, now=self.t + sessions.BEAT_TTL - 1))
        self.assertFalse(sessions.button_alive(self.key, now=self.t + sessions.BEAT_TTL + 1))
        self.assertEqual(sessions.button_pid(self.key), 123)

    def test_only_one_of_two_simultaneous_starters_gets_the_lock(self):
        self.assertTrue(sessions.try_lock(self.key, now=self.t))
        self.assertFalse(sessions.try_lock(self.key, now=self.t + 1))
        sessions.clear_button(self.key)
        self.assertTrue(sessions.try_lock(self.key, now=self.t + 2))

    def test_a_lock_left_by_a_dead_button_is_taken_over_but_a_fresh_one_is_respected(self):
        self.assertTrue(sessions.try_lock(self.key))
        lock = sessions._button_path(self.key)[:-5] + ".lock"
        self.assertFalse(sessions.try_lock(self.key), "a lock only just created must be respected")
        os.utime(lock, (self.t, self.t))                                        # long ago, and no heartbeat
        self.assertTrue(sessions.try_lock(self.key, now=self.t + 3 * sessions.BEAT_TTL))

    def test_a_live_button_keeps_its_lock_however_old_the_file(self):
        self.assertTrue(sessions.try_lock(self.key, now=self.t))
        lock = sessions._button_path(self.key)[:-5] + ".lock"
        os.utime(lock, (self.t, self.t))                                        # an old lock file ...
        sessions.write_beat(self.key, 1, 1, now=self.t + 1000)                  # ... whose owner is still beating
        self.assertFalse(sessions.try_lock(self.key, now=self.t + 1001))
        self.assertTrue(os.path.exists(lock), "a live owner's lock must not be removed")

    def test_the_stop_check_speaks_once_per_prompt_and_not_again_for_the_same_one(self):
        self.assertTrue(sessions.claim_correction("s1", "prompt-1", now=self.t))
        self.assertFalse(sessions.claim_correction("s1", "prompt-1", now=self.t + 1))
        self.assertTrue(sessions.claim_correction("s1", "prompt-2", now=self.t + 2))
        self.assertTrue(sessions.claim_correction("s2", "prompt-2", now=self.t + 2), "another session is independent")

    def test_without_a_prompt_id_the_stop_check_falls_back_to_a_cooldown(self):
        self.assertTrue(sessions.claim_correction("s1", None, now=self.t))
        self.assertFalse(sessions.claim_correction("s1", None, now=self.t + 10))
        self.assertTrue(sessions.claim_correction("s1", None, now=self.t + 60))

    def test_ending_a_session_forgets_its_stop_record(self):
        sessions.register_session("s1", self.root, now=self.t)
        sessions.claim_correction("s1", "p", now=self.t)
        sessions.end_session("s1")
        self.assertTrue(sessions.claim_correction("s1", "p", now=self.t + 1))


class TestEnsureButton(SessionCase):
    def setUp(self):
        super().setUp()
        write_files(self.root, {"a.py": ""})
        write_graph(self.root, {"a.py": {"symbols": ["f"]}})
        self.spawned = []
        self.patches = [mock.patch.object(sessions, "gui_available", return_value=True),
                        mock.patch.object(sessions, "tkinter_available", return_value=True)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def spawn(self, root):
        self.spawned.append(root)

    def test_starts_one_when_there_is_a_map_and_none_is_running(self):
        self.assertEqual(sessions.ensure_button(self.root, spawn=self.spawn), "started")
        self.assertEqual(self.spawned, [self.root])

    def test_does_not_start_a_second_while_one_is_alive(self):
        key = store_mod.project_identity(self.root)[0]
        sessions.write_beat(key, 1, 1)
        self.assertEqual(sessions.ensure_button(self.root, spawn=self.spawn), "running")
        self.assertEqual(self.spawned, [])

    def test_every_reason_not_to_show_it(self):
        sessions.set_button_enabled(False)
        self.assertEqual(sessions.ensure_button(self.root, spawn=self.spawn), "disabled")
        sessions.set_button_enabled(True)
        self.assertEqual(sessions.ensure_button(self.root, spawn=self.spawn, env={"CORTEX_BUTTON": "off"}), "disabled")
        with mock.patch.object(sessions, "gui_available", return_value=False):
            self.assertEqual(sessions.ensure_button(self.root, spawn=self.spawn), "no-screen")
        with mock.patch.object(sessions, "tkinter_available", return_value=False):
            self.assertEqual(sessions.ensure_button(self.root, spawn=self.spawn), "no-tk")
        shutil.rmtree(os.path.join(self.root, "graphify-out"))
        self.assertEqual(sessions.ensure_button(self.root, spawn=self.spawn), "nothing-to-show")
        self.assertEqual(self.spawned, [])

    def test_a_project_with_only_a_palace_gets_a_button(self):
        shutil.rmtree(os.path.join(self.root, "graphify-out"))
        store_mod.open_store("project", cwd=self.root).close()                   # creates the project's palace
        self.assertEqual(sessions.ensure_button(self.root, spawn=self.spawn), "started")

    def test_the_button_is_started_in_a_way_a_project_cannot_hijack(self):
        # Found by running the real chain: a project with its own top-level `cortex` folder (older, or this
        # repository) was imported instead of the real core, and the console-less button died silently.
        decoy = os.path.join(self.tmp, "decoy-project")
        os.makedirs(os.path.join(decoy, "cortex"))
        with open(os.path.join(decoy, "cortex", "__init__.py"), "w") as fh:
            fh.write("raise SystemExit('the decoy cortex was imported')\n")
        argv, cwd = sessions.launch_command(["button", "status", "--project", decoy], python=sys.executable)
        self.assertNotEqual(os.path.abspath(cwd), os.path.abspath(decoy))
        env = dict(os.environ, PYTHONUTF8="1")
        env.pop("PYTHONPATH", None)
        result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("button", result.stdout)
        self.assertNotIn("the decoy cortex was imported", result.stdout + result.stderr)

    def test_a_failing_spawn_is_reported_not_raised(self):
        def boom(_root):
            raise OSError("no")
        self.assertEqual(sessions.ensure_button(self.root, spawn=boom), "failed")

    def test_the_setting_persists_and_the_environment_overrides_it(self):
        self.assertTrue(sessions.button_enabled())
        sessions.set_button_enabled(False)
        self.assertFalse(sessions.button_enabled())
        sessions.set_button_enabled(True)
        self.assertTrue(sessions.button_enabled())
        self.assertFalse(sessions.button_enabled({"CORTEX_BUTTON": "0"}))
        self.assertTrue(sessions.button_enabled({"CORTEX_BUTTON": "on"}))

    def test_the_studio_folder_follows_the_data_dir_not_the_code_dir(self):
        # CORTEX_HOME means "where the Cortex code is" to the shims; the data dir has its own variable.
        self.assertTrue(sessions.studio_dir().startswith(self.home))
        with mock.patch.dict(os.environ, {"CORTEX_HOME": os.path.join(self.tmp, "somewhere-else")}):
            self.assertTrue(sessions.studio_dir().startswith(self.home))


class TestSessionHook(AtlasCase):
    """The script Claude Code runs. Always exits 0 and says nothing unless the Stop check has something to say."""

    def run_hook(self, payload, raw=None, extra_env=None):
        env = dict(os.environ, CORTEX_BUTTON="off", PYTHONUTF8="1", **(extra_env or {}))
        data = raw if raw is not None else json.dumps(payload)
        return subprocess.run([sys.executable, HOOK], input=data, capture_output=True, text=True, env=env,
                              timeout=60, cwd=self.tmp)

    def test_garbage_and_empty_input_exit_quietly(self):
        for raw in ("", "   ", "not json", "[1,2]", "null", '{"hook_event_name": 5}'):
            r = self.run_hook(None, raw=raw)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), raw)

    def test_session_start_registers_and_session_end_removes(self):
        self.run_hook({"hook_event_name": "SessionStart", "session_id": "abc", "cwd": self.root, "source": "startup"})
        self.assertEqual([r["session"] for r in sessions.live_sessions()], ["abc"])
        r = self.run_hook({"hook_event_name": "SessionEnd", "session_id": "abc", "cwd": self.root})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        self.assertEqual(sessions.live_sessions(), [])

    def test_compaction_makes_the_palace_willing_to_repeat_itself(self):
        # The hook finds the palace by project identity, so seed that palace (not the test's own file).
        path = store_mod.db_path("project", self.root)
        real = store_mod.Store(path)
        write.remember(real, "Config loading", "load_config reads the file once.", project_root=self.root,
                       kind="decision", paths=["a.py"])
        mid = real.list_memories()[0]["id"]
        real.close()
        for source, expect_reset in (("startup", False), ("resume", False), ("fork", False), ("clear", True),
                                     ("compact", True)):
            real = store_mod.Store(path)
            real.conn.execute("DELETE FROM feedback WHERE session = 'sess-1'")
            real.record_injection(mid, "sess-1", "full")
            real.close()
            self.run_hook({"hook_event_name": "SessionStart", "session_id": "sess-1", "cwd": self.root, "source": source})
            real = store_mod.Store(path)
            shown = real.injected_in_session("sess-1")
            history = real.conn.execute("SELECT COUNT(*) FROM feedback WHERE session = 'sess-1'").fetchone()[0]
            real.close()
            self.assertEqual(shown == set(), expect_reset, "source=%s" % source)
            self.assertEqual(history, 1, "the usage history must survive a reset (source=%s)" % source)

    def test_stop_says_nothing_unless_grounding_is_on(self):
        said = "See `cortex/gaurd.py` and notes.md."
        r = self.run_hook({"hook_event_name": "Stop", "cwd": self.root, "last_assistant_message": said})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_stop_with_grounding_on_points_out_a_missing_file_once(self):
        path = store_mod.db_path("project", self.root)
        real = store_mod.Store(path)
        real.meta_set("ground", "on")
        real.close()
        said = "The fix is in `bb.py`, next to a.py."
        r = self.run_hook({"hook_event_name": "Stop", "cwd": self.root, "last_assistant_message": said})
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("bb.py", out["reason"])
        self.assertIn("b.py", out["reason"])                 # the closest real file is offered
        again = self.run_hook({"hook_event_name": "Stop", "cwd": self.root, "last_assistant_message": said,
                               "stop_hook_active": True})
        self.assertEqual(again.stdout.strip(), "", "must never loop on its own correction")

    def test_stop_corrects_once_per_prompt_even_if_claude_code_sends_no_stop_hook_active_field(self):
        # The documentation does not list stop_hook_active, so the loop guard must not depend on it.
        real = store_mod.Store(store_mod.db_path("project", self.root))
        real.meta_set("ground", "on")
        real.close()
        said = {"hook_event_name": "Stop", "session_id": "s-loop", "prompt_id": "turn-1", "cwd": self.root,
                "last_assistant_message": "It lives in `bb.py`."}
        first = self.run_hook(said)
        second = self.run_hook(said)                                            # the corrected answer, still imperfect
        self.assertEqual(json.loads(first.stdout)["decision"], "block")
        self.assertEqual(second.stdout.strip(), "", "a second block for the same prompt would be a loop")
        said["prompt_id"] = "turn-2"
        self.assertEqual(json.loads(self.run_hook(said).stdout)["decision"], "block")   # a new prompt: fine
        clean = self.run_hook({"hook_event_name": "Stop", "cwd": self.root, "last_assistant_message": "All good in a.py."})
        self.assertEqual(clean.stdout.strip(), "")

    def test_the_hook_survives_a_missing_cortex_core(self):
        lonely = os.path.join(self.tmp, "lonely", "scripts")
        os.makedirs(lonely)
        copy = os.path.join(lonely, "cortex-session-hook.py")
        shutil.copy(HOOK, copy)
        env = dict(os.environ, HOME=self.fake_user_home, USERPROFILE=self.fake_user_home)
        r = subprocess.run([sys.executable, copy], input=json.dumps({"hook_event_name": "SessionStart"}),
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))


class TestCli(AtlasCase):
    def run_cli(self, *args):
        from cortex.atlas import cli
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(list(args))
        return code, buf.getvalue()

    def test_status_describes_the_project(self):
        self.note("Config loading", "load_config reads once.", kind="decision", paths=["a.py"])
        with mock.patch.object(store_mod, "db_path", return_value=self.store.path):
            code, out = self.run_cli("status", "--project", self.root)
        self.assertEqual(code, 0)
        self.assertIn("4 files", out)
        self.assertIn("1 notes", out)
        self.assertIn("button", out)

    def test_button_on_and_off_persist(self):
        code, out = self.run_cli("button", "off", "--project", self.root)
        self.assertEqual(code, 0)
        self.assertFalse(sessions.button_enabled())
        self.assertIn("button on", out)
        self.run_cli("button", "on", "--project", self.root)
        self.assertTrue(sessions.button_enabled())

    def test_stopping_a_button_that_is_not_running_is_fine(self):
        code, out = self.run_cli("button", "stop", "--project", self.root)
        self.assertEqual(code, 0)
        self.assertIn("No button", out)

    def test_unknown_subcommands_are_refused_by_the_parser(self):
        from cortex.atlas import cli
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr"):
                cli.main(["nonsense"])


if __name__ == "__main__":
    unittest.main()
