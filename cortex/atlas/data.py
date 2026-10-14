"""
What the map shows: the project's files, the links between them, and the memories pinned to them.

Built from two read-only sources:

* Graphify's ``graphify-out/graph.json`` - kept as a small file-level cache in the palace database
  (``gfile`` / ``gedge`` / ``gsym``, see ``palace/graph.py``) so an overview is a few SQL queries, not
  a parse of a big JSON file. Symbol-level detail (one file's functions and their callers) is read
  from ``graph.json`` on demand, once per version of the file.
* The palace database - memories, their anchors, and the live freshness of each.

With no Graphify graph the map still works: it shows the files memories are anchored to. With no
palace it shows the code graph alone. With neither, it says how to get one.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import threading
import time

from ..palace import PalaceError
from ..palace import graph as graph_mod
from ..palace import store as store_mod
from ..palace.store import iso, utc_now

MAX_FILES = 1500          # more than this and the map stops being readable; the biggest are kept
MAX_MEMORIES = 600
MAX_EDGES = 9000
MAX_SYMBOL_LINKS = 500
_ATTENTION_TTL = 60.0     # seconds: live freshness reads files, so it is not recomputed every poll
_ORDER = {"orphaned": 3, "verify": 2, "fresh": 1, "unknown": 0}
_LOCATION_DIGITS = "0123456789"


def _like(text):
    """Escape a user string for a SQL LIKE ... ESCAPE '\\' pattern."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _line_of(location):
    digits = "".join(ch for ch in str(location or "") if ch in _LOCATION_DIGITS)
    return int(digits) if digits else None


def _top_dir(rel):
    return rel.split("/", 1)[0] if "/" in rel else "."


def _from_epoch(seconds):
    import datetime
    return datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)


class Atlas:
    """Read-only view of one project. Safe to share between server threads."""

    def __init__(self, project_dir=None, palace_path=None):
        self.project_dir = os.path.abspath(project_dir or os.getcwd())
        self.key, self.root = store_mod.project_identity(self.project_dir)
        self.palace_path = palace_path or store_mod.db_path("project", self.project_dir)
        self.name = os.path.basename(self.root.rstrip("\\/")) or "project"
        self._scratch = None
        self._parsed = None                     # (fingerprint, index) of graph.json for symbol views
        self._attention = (0.0, 0)
        self._lock = threading.RLock()

    # -- plumbing ------------------------------------------------------------------------

    def close(self):
        with self._lock:
            if self._scratch:
                shutil.rmtree(self._scratch, ignore_errors=True)
                self._scratch = None

    @contextlib.contextmanager
    def _scratch_store(self):
        """A throwaway database that only holds the graph cache (no palace, or one we cannot read)."""
        with self._lock:
            if not self._scratch:
                self._scratch = tempfile.mkdtemp(prefix="cortex-atlas-")
        st = store_mod.Store(os.path.join(self._scratch, "map.db"), create=True)
        try:
            yield st
        finally:
            st.close()

    @contextlib.contextmanager
    def _store(self):
        """The palace if there is one, else a scratch database."""
        if os.path.isfile(self.palace_path):
            st = store_mod.Store(self.palace_path, create=False)
            try:
                yield st
            finally:
                st.close()
        else:
            with self._scratch_store() as st:
                yield st

    def _has_palace(self, st):
        return os.path.abspath(st.path) == os.path.abspath(self.palace_path)

    def _graph_meta(self, st):
        paths = graph_mod.find_graphs(self.root)
        meta = {"present": bool(paths), "path": None, "built_at": None, "age_seconds": None,
                "files": 0, "symbols": 0, "edges": 0}
        if paths:
            meta["path"] = os.path.relpath(paths[0], self.root).replace("\\", "/")
            try:
                mtime = os.path.getmtime(paths[0])
                meta["built_at"] = iso(_from_epoch(mtime))
                meta["age_seconds"] = max(0, int(time.time() - mtime))
            except OSError:
                pass
            c = st.conn
            meta["files"] = c.execute("SELECT COUNT(*) FROM gfile").fetchone()[0]
            meta["symbols"] = c.execute("SELECT COUNT(*) FROM gsym").fetchone()[0]
            meta["edges"] = c.execute("SELECT COUNT(*) FROM gedge").fetchone()[0]
        return meta

    # -- overview ------------------------------------------------------------------------

    def overview(self):
        """Everything the first screen needs, as plain JSON-able data."""
        with self._lock:
            try:
                with self._store() as st:
                    return self._overview(st)
            except PalaceError as exc:                      # a newer or damaged palace: show the code graph anyway
                with self._scratch_store() as st:
                    out = self._overview(st)
                out["palace"] = {"present": False, "memories": 0, "shown": 0, "attention": 0, "error": str(exc)}
                return out

    def _overview(self, st):
        has_palace = self._has_palace(st)
        graph_error = None
        try:
            graph_mod.sync(st, self.root)
        except PalaceError as exc:
            graph_error = str(exc)
        index = graph_mod.GraphIndex(st)
        c = st.conn

        files = {r["file"]: {"community": r["community"], "area": r["community_name"]}
                 for r in c.execute("SELECT file, community, community_name FROM gfile")}
        symbols = {r["file"]: r["n"] for r in c.execute("SELECT file, COUNT(*) AS n FROM gsym GROUP BY file")}
        degree, raw_edges = {}, []
        for r in c.execute("SELECT src, dst, weight FROM gedge"):
            raw_edges.append((r["src"], r["dst"], r["weight"]))
            degree[r["src"]] = degree.get(r["src"], 0) + 1
            degree[r["dst"]] = degree.get(r["dst"], 0) + 1

        memories, anchored = [], {}
        attention = 0
        total_memories = 0
        if has_palace:
            total_memories = st.count()
            for m in st.list_memories(status="active", limit=MAX_MEMORIES, order="importance DESC"):
                anchors = st.anchors_of(m["id"])
                fresh = graph_mod.memory_freshness(st, self.root, m["id"], index) if anchors else "unknown"
                if fresh in ("verify", "orphaned"):
                    attention += 1
                entry_files = sorted({a["file"] for a in anchors})
                for f in entry_files:
                    files.setdefault(f, {"community": None, "area": None})
                    anchored.setdefault(f, []).append(fresh)
                memories.append({"id": m["id"], "kind": m["kind"], "tier": m["tier"], "title": m["title"],
                                 "gist": m["gist"], "fresh": fresh, "pinned": bool(m["pinned"]),
                                 "trust": m["trust"], "importance": round(m["importance"], 2),
                                 "_files": entry_files})
            self._attention = (time.time(), attention)

        # Keep the most connected / most remembered files when there are too many to read.
        dropped_files = 0
        names = list(files)
        if len(names) > MAX_FILES:
            names.sort(key=lambda f: -(degree.get(f, 0) + 4 * len(anchored.get(f, []))))
            dropped_files = len(names) - MAX_FILES
            names = names[:MAX_FILES]
        names.sort()
        position = {f: i for i, f in enumerate(names)}

        out_files = []
        for f in names:
            states = anchored.get(f, [])
            health = max(states, key=lambda s: _ORDER[s]) if states else None
            out_files.append({"id": f, "name": f.rsplit("/", 1)[-1], "dir": _top_dir(f),
                              "community": files[f]["community"], "area": files[f]["area"],
                              "degree": degree.get(f, 0), "symbols": symbols.get(f, 0),
                              "memories": len(states), "health": health})

        kept = [(a, b, w) for a, b, w in raw_edges if a in position and b in position]
        kept.sort(key=lambda e: -e[2])
        dropped_edges = max(0, len(kept) - MAX_EDGES)
        links = [[position[a], position[b], round(w, 2)] for a, b, w in kept[:MAX_EDGES]]

        for m in memories:
            m["files"] = [position[f] for f in m.pop("_files") if f in position]

        areas = [{"id": cid, "name": name, "files": n} for cid, name, n in index.community_names()[:60]]
        return {
            "project": {"name": self.name, "root": self.root.replace("\\", "/"), "key": self.key},
            "graph": dict(self._graph_meta(st), error=graph_error),
            "palace": {"present": has_palace, "memories": total_memories, "shown": len(memories),
                       "attention": attention, "error": None},
            "files": out_files, "links": links, "memories": memories, "areas": areas,
            "truncated": {"files": dropped_files, "edges": dropped_edges,
                          "memories": max(0, total_memories - len(memories))},
            "generated_at": iso(utc_now()),
        }

    def status(self):
        """A few numbers for the floating button. Cheap; never raises."""
        try:
            with self._lock:
                with self._store() as st:
                    try:
                        graph_mod.sync(st, self.root)
                    except PalaceError:
                        pass
                    meta = self._graph_meta(st)
                    has_palace = self._has_palace(st)
                    memories = st.count() if has_palace else 0
                    if has_palace and time.time() - self._attention[0] > _ATTENTION_TTL:
                        index = graph_mod.GraphIndex(st)
                        bad = 0
                        for m in st.list_memories(status="active", limit=MAX_MEMORIES):
                            if graph_mod.memory_freshness(st, self.root, m["id"], index) in ("verify", "orphaned"):
                                bad += 1
                        self._attention = (time.time(), bad)
                    return {"project": self.name, "graph": meta["present"], "files": meta["files"],
                            "age_seconds": meta["age_seconds"], "palace": has_palace, "memories": memories,
                            "attention": self._attention[1] if has_palace else 0}
        except Exception as exc:                            # a status poll must never take the button down
            return {"project": self.name, "graph": False, "files": 0, "age_seconds": None,
                    "palace": False, "memories": 0, "attention": 0, "error": str(exc)}

    # -- one file's symbols --------------------------------------------------------------

    def _graph_index(self):
        """Parse graph.json once per version into per-node info, grouped by file."""
        paths = graph_mod.find_graphs(self.root)
        if not paths:
            return None
        fp = graph_mod.fingerprint(paths)
        if self._parsed and self._parsed[0] == fp:
            return self._parsed[1]
        nodes, by_file, links = {}, {}, []
        for path in paths:
            data = graph_mod.load_graph(path)
            groot = graph_mod.graph_root(path)
            for node in data["nodes"]:
                if not isinstance(node, dict) or "id" not in node:
                    continue
                rel = graph_mod.project_relative(self.root, groot, node.get("source_file"))
                if rel is None:
                    continue
                label = str(node.get("label", ""))
                is_file_node = label == os.path.basename(str(node.get("source_file", "")))
                if node.get("file_type") != "code" or not label or is_file_node:
                    nodes.setdefault(node["id"], None)
                    continue
                if node.get("_callable_class"):
                    kind = "class"
                elif node.get("_callable"):
                    kind = "function"
                else:
                    kind = "symbol"
                info = {"id": str(node["id"]), "label": graph_mod.symbol_label(label), "kind": kind,
                        "file": rel, "line": _line_of(node.get("source_location"))}
                nodes[node["id"]] = info
                by_file.setdefault(rel, []).append(info)
            for link in data.get("links", data.get("edges", [])):
                if isinstance(link, dict) and link.get("relation") not in graph_mod.STRUCTURAL_RELATIONS:
                    links.append((link.get("source"), link.get("target"), str(link.get("relation", "")),
                                  str(link.get("confidence", ""))))
        index = {"nodes": nodes, "by_file": by_file, "links": links}
        self._parsed = (fp, index)
        return index

    def symbols(self, file):
        """The functions/classes in ``file``, how they connect, and what outside they touch."""
        with self._lock:
            index = self._graph_index()
            if index is None or file not in index["by_file"]:
                return {"file": file, "symbols": [], "links": [], "external": []}
            mine = {s["id"]: s for s in index["by_file"][file]}
            chosen, external = [], {}
            for source, target, relation, confidence in index["links"]:
                if source not in mine and target not in mine:
                    continue
                known_s = source in mine or index["nodes"].get(source)
                known_t = target in mine or index["nodes"].get(target)
                if not (known_s and known_t):
                    continue
                for end in (source, target):
                    if end not in mine:
                        external[end] = index["nodes"][end]
                chosen.append((0 if confidence == "EXTRACTED" else 1, source, target, relation, confidence))
            chosen.sort(key=lambda e: e[0])
            links = [{"s": s, "t": t, "relation": r, "confidence": cf} for _p, s, t, r, cf in chosen[:MAX_SYMBOL_LINKS]]
            used = {x["s"] for x in links} | {x["t"] for x in links}
            return {"file": file,
                    "symbols": sorted(mine.values(), key=lambda s: (s["line"] or 0, s["label"])),
                    "links": links,
                    "external": [v for k, v in external.items() if k in used]}

    # -- one memory ----------------------------------------------------------------------

    def memory(self, memory_id):
        with self._lock:
            if not os.path.isfile(self.palace_path):
                return None
            with self._store() as st:
                try:
                    mid = st.resolve_id(memory_id)
                except PalaceError:
                    return None
                m = st.get(mid)
                index = graph_mod.GraphIndex(st)
                anchors = []
                for a in st.anchors_of(mid):
                    anchors.append({"file": a["file"], "label": a["label"], "kind": a["kind"],
                                    "state": graph_mod.anchor_state(st, self.root, a, index)})
                older = [dict(id=r["id"], title=r["title"], recorded_at=r["recorded_at"]) for r in st.conn.execute(
                    "SELECT id, title, recorded_at FROM memory WHERE superseded_by = ? ORDER BY recorded_at DESC", (mid,))]
                keep = ("id", "kind", "tier", "title", "headline", "gist", "body", "tags", "status", "valid_from",
                        "valid_to", "recorded_at", "updated_at", "superseded_by", "confidence", "importance",
                        "pinned", "uses", "last_used", "trust", "source_session", "source_commit")
                out = {k: m[k] for k in keep}
                out["pinned"] = bool(out["pinned"])
                out["anchors"] = anchors
                out["supersedes"] = older
                out["fresh"] = max((a["state"] for a in anchors), key=lambda s: _ORDER[s], default="unknown")
                return out

    # -- search --------------------------------------------------------------------------

    def search(self, query, limit=12):
        query = (query or "").strip().lower()
        if len(query) < 2:
            return []
        pattern = "%" + _like(query) + "%"
        results = []
        with self._lock:
            with self._store() as st:
                try:
                    graph_mod.sync(st, self.root)               # cheap when nothing changed; search may come first
                except PalaceError:
                    pass
                c = st.conn
                for r in c.execute("SELECT file FROM gfile WHERE lower(file) LIKE ? ESCAPE '\\' "
                                   "ORDER BY length(file) LIMIT ?", (pattern, limit)):
                    results.append({"type": "file", "id": r["file"], "label": r["file"].rsplit("/", 1)[-1],
                                    "sub": r["file"], "file": r["file"]})
                for r in c.execute("SELECT node_id, label, file, kind FROM gsym WHERE lower(label) LIKE ? ESCAPE '\\' "
                                   "ORDER BY length(label) LIMIT ?", (pattern, limit)):
                    results.append({"type": "symbol", "id": r["node_id"], "label": r["label"],
                                    "sub": "%s in %s" % (r["kind"] or "symbol", r["file"]), "file": r["file"]})
                if self._has_palace(st):
                    for r in c.execute(
                            "SELECT id, title, kind FROM memory WHERE status = 'active' AND "
                            "(lower(title) LIKE ? ESCAPE '\\' OR lower(headline) LIKE ? ESCAPE '\\' "
                            "OR lower(gist) LIKE ? ESCAPE '\\' OR lower(tags) LIKE ? ESCAPE '\\') LIMIT ?",
                            (pattern, pattern, pattern, pattern, limit)):
                        results.append({"type": "memory", "id": r["id"], "label": r["title"],
                                        "sub": r["kind"], "file": None})
        return results
