"""
The Graphify bridge.

Division of labour (the whole design in one sentence): **Graphify knows what the code *is*;
the palace knows what we *decided, learned and want*.** The palace never copies code structure
into itself. It *anchors* a memory to a file or symbol, and uses Graphify's graph for three things:

1. **Anchoring** - turning "guard.py" or "`profile_dir`" in a memory into a concrete file/symbol;
2. **Expansion** - memories about files *near* the one you are touching (callers, imports, the same
   community) are worth surfacing, weighted by how certain Graphify is about the edge;
3. **Freshness** - Graphify records a hash of each file's syntax tree. A memory written when a file
   looked one way is flagged ("code changed since this was written") when the hash differs, and
   marked orphaned when the file or symbol is gone. Stale memory is the main way project memory
   misleads, and this is how we catch it.

Coupling rules:
* **Read-only, file-based.** We read ``graphify-out/graph.json`` and ``manifest.json``. We never import
  Graphify, never run it, never write into its folder.
* **Detect by shape, not by version.** The format is a NetworkX node-link JSON; this release leaves
  the ``graph`` attributes empty, so there is no ``schema_version`` to trust. Anything that does not
  look like a graph is refused with a clear message.
* **Optional.** With no graph, the palace works fully; anchors then use plain file hashes.
* **A cache, not a copy.** The derived tables (``gfile``, ``gedge``, ``gsym``) hold a small file-level
  summary, rebuilt when the graph file changes, so a per-prompt lookup is a SQL query and never a
  parse of a (possibly huge) JSON file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

from . import PalaceError
from .store import iso

_CALL_SUFFIX = re.compile(r"\(\)$")

#: Bump when the derived tables (gfile/gedge/gsym) would come out different for the same graph file.
GRAPH_FORMAT = 2


def symbol_key(label):
    """Normalise a symbol name for lookup. Graphify labels functions ``name()`` and methods ``.name()``."""
    return _CALL_SUFFIX.sub("", (label or "").strip()).lstrip(".").lower()


def symbol_label(label):
    """A symbol's name as people write it: Graphify's trailing "()" removed, case kept."""
    return _CALL_SUFFIX.sub("", (label or "").strip()).lstrip(".")


#: Relations that say "this file contains that symbol", not "these two things depend on each other".
_STRUCTURAL = {"contains", "rationale_for", "method"}
_MAX_GRAPH_BYTES = 400 * 1024 * 1024


# --------------------------------------------------------------------------- locating

def find_graphs(project_root):
    """Paths of Graphify graphs for a project: ``<root>/graphify-out`` and one level below it."""
    found = []
    if not project_root or not os.path.isdir(project_root):
        return found
    direct = os.path.join(project_root, "graphify-out", "graph.json")
    if os.path.isfile(direct):
        found.append(direct)
    try:
        children = sorted(os.listdir(project_root))
    except OSError:
        return found
    for name in children:
        if name.startswith(".") or name in ("node_modules", "venv", ".venv", "__pycache__"):
            continue
        candidate = os.path.join(project_root, name, "graphify-out", "graph.json")
        if os.path.isfile(candidate):
            found.append(candidate)
    return found


def _fingerprint(paths):
    parts = []
    for p in paths:
        try:
            st = os.stat(p)
            parts.append("%s|%d|%d" % (os.path.abspath(p), st.st_mtime_ns, st.st_size))
        except OSError:
            parts.append("%s|missing" % p)
    # GRAPH_FORMAT is part of the fingerprint so that a change in how names are normalised rebuilds the
    # cached tables of every existing palace, instead of leaving them as they were.
    return ";".join(parts) + ";fmt=%d" % GRAPH_FORMAT


def _load_graph(path):
    try:
        size = os.path.getsize(path)
        if size > _MAX_GRAPH_BYTES:
            raise PalaceError("%s is %d MB; too large to index (limit %d MB)."
                              % (path, size // 1048576, _MAX_GRAPH_BYTES // 1048576))
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise PalaceError("Could not read the Graphify graph %s: %s" % (path, exc))
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list) \
            or not isinstance(data.get("links", data.get("edges")), list):
        raise PalaceError("%s does not look like a Graphify graph (expected nodes and links). "
                          "Not indexing it." % path)
    return data


def _graph_root(graph_path):
    """The folder Graphify extracted from. Node ``source_file`` values are relative to it."""
    out_dir = os.path.dirname(os.path.abspath(graph_path))
    marker = os.path.join(out_dir, ".graphify_root")
    try:
        with open(marker, encoding="utf-8") as fh:
            recorded = fh.read().strip()
        if recorded and os.path.isdir(recorded):
            return os.path.abspath(recorded)
    except OSError:
        pass
    return os.path.dirname(out_dir)


def _manifest(graph_path):
    path = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "manifest.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _rel(project_root, graph_root, source_file):
    """A project-relative, forward-slash path for a node's source file, or None if outside."""
    if not source_file:
        return None
    full = os.path.normpath(os.path.join(graph_root, source_file))
    try:
        rel = os.path.relpath(full, project_root)
    except ValueError:                                  # different drive on Windows
        return None
    if rel.startswith(".."):
        return None
    return rel.replace("\\", "/")


# The parts other read-only consumers (the project map in cortex/atlas) need, under public names.
load_graph = _load_graph
graph_root = _graph_root
project_relative = _rel
fingerprint = _fingerprint
STRUCTURAL_RELATIONS = frozenset(_STRUCTURAL)


# --------------------------------------------------------------------------- syncing

def sync(store, project_root, force=False):
    """Refresh the derived tables from the project's graph(s). Returns a small report dict.

    Cheap when nothing changed (one ``stat`` per graph). Never raises for "no graph": that is a
    normal state, reported as ``{"graph": False}``.
    """
    paths = find_graphs(project_root)
    if not paths:
        had = store.meta_get("graph_fp")
        if had:
            with store.tx():
                for table in ("gfile", "gedge", "gsym"):
                    store.conn.execute("DELETE FROM %s" % table)
                store.meta_set("graph_fp", "")
                store.meta_set("graph_paths", "")
        return {"graph": False, "reason": "no graphify-out/graph.json found", "changed": bool(had)}

    fp = _fingerprint(paths)
    if not force and store.meta_get("graph_fp") == fp:
        return {"graph": True, "changed": False, "files": store.conn.execute(
            "SELECT COUNT(*) FROM gfile").fetchone()[0], "paths": paths}

    files, syms, edges = {}, {}, {}
    notes = []
    for path in paths:
        data = _load_graph(path)
        graph_root = _graph_root(path)
        manifest = _manifest(path)
        node_file = {}
        counts = {}
        for node in data["nodes"]:
            if not isinstance(node, dict) or "id" not in node:
                continue
            rel = _rel(project_root, graph_root, node.get("source_file"))
            if rel is None:
                continue
            node_file[node["id"]] = rel
            entry = files.setdefault(rel, {"ast": None, "community": None, "cname": None})
            community = node.get("community")
            if isinstance(community, int):
                key = (community, node.get("community_name"))
                counts.setdefault(rel, {})[key] = counts.get(rel, {}).get(key, 0) + 1
            is_file_node = str(node.get("label", "")) == os.path.basename(str(node.get("source_file", "")))
            if node.get("file_type") == "code" and node.get("label") and not is_file_node:
                label = str(node["label"])
                if node.get("_callable_class"):
                    kind = "class"
                elif node.get("_callable"):
                    kind = "function"
                else:
                    kind = "symbol"
                syms[str(node["id"])] = (symbol_key(node.get("norm_label") or label),
                                         symbol_label(label), rel, kind)
            info = manifest.get(node.get("source_file"))
            if isinstance(info, dict) and info.get("ast_hash"):
                entry["ast"] = str(info["ast_hash"])
        for rel, by_comm in counts.items():
            (community, cname), _n = max(by_comm.items(), key=lambda kv: kv[1])
            files[rel]["community"], files[rel]["cname"] = community, cname
        for link in data.get("links", data.get("edges", [])):
            if not isinstance(link, dict):
                continue
            a, b = node_file.get(link.get("source")), node_file.get(link.get("target"))
            if not a or not b or a == b or link.get("relation") in _STRUCTURAL:
                continue
            if link.get("confidence") == "EXTRACTED":
                weight = 1.0
            else:
                try:
                    weight = 0.5 * float(link.get("confidence_score", 0.5))
                except (TypeError, ValueError):
                    weight = 0.25
            key = (a, b) if a < b else (b, a)
            edges[key] = edges.get(key, 0.0) + weight
        notes.append("%s: %d nodes" % (os.path.relpath(path, project_root), len(data["nodes"])))

    with store.tx():
        for table in ("gfile", "gedge", "gsym"):
            store.conn.execute("DELETE FROM %s" % table)
        store.conn.executemany(
            "INSERT INTO gfile(file, ast_hash, community, community_name) VALUES(?,?,?,?)",
            [(f, v["ast"], v["community"], v["cname"]) for f, v in files.items()])
        store.conn.executemany(
            "INSERT INTO gedge(src, dst, weight) VALUES(?,?,?)",
            [(a, b, w) for (a, b), w in edges.items()])
        store.conn.executemany(
            "INSERT OR REPLACE INTO gsym(node_id, norm_label, label, file, kind) VALUES(?,?,?,?,?)",
            [(nid, nl, lb, fl, kd) for nid, (nl, lb, fl, kd) in syms.items()])
        store.meta_set("graph_fp", fp)
        store.meta_set("graph_paths", json.dumps(paths))
        store.meta_set("graph_synced", iso(store.clock()))
        store.log("graph_sync", None, {"files": len(files), "symbols": len(syms), "edges": len(edges)})
        store.bump_rev()
    return {"graph": True, "changed": True, "files": len(files), "symbols": len(syms),
            "edges": len(edges), "paths": paths, "notes": notes}


# --------------------------------------------------------------------------- querying

def file_sha(project_root, rel):
    """SHA-256 of a project file's bytes, or None if it is missing or unreadable."""
    try:
        h = hashlib.sha256()
        with open(os.path.join(project_root, rel), "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:32]
    except OSError:
        return None


class GraphIndex:
    """Read access to the derived tables. Safe to construct when there is no graph."""

    def __init__(self, store):
        self.store = store
        self.available = store.conn.execute("SELECT COUNT(*) FROM gfile").fetchone()[0] > 0

    def info(self, rel):
        row = self.store.conn.execute("SELECT * FROM gfile WHERE file = ?", (rel,)).fetchone()
        return dict(row) if row else None

    def resolve_basename(self, name):
        """The one project file with this base name, or None when absent or ambiguous."""
        rows = self.store.conn.execute(
            "SELECT file FROM gfile WHERE file = ? OR file LIKE ?", (name, "%/" + name)).fetchall()
        files = sorted({r[0] for r in rows if r[0] == name or r[0].endswith("/" + name)})
        return files[0] if len(files) == 1 else None

    def resolve_symbol(self, label):
        """A unique code symbol for ``label`` (case-insensitive), or None when absent or ambiguous."""
        rows = self.store.conn.execute(
            "SELECT node_id, label, file, kind FROM gsym WHERE norm_label = ?", (symbol_key(label),)).fetchall()
        return dict(rows[0]) if len(rows) == 1 else None

    def symbol_present(self, label, rel):
        row = self.store.conn.execute(
            "SELECT 1 FROM gsym WHERE norm_label = ? AND file = ? LIMIT 1", (symbol_key(label), rel)).fetchone()
        return bool(row)

    def neighbors(self, files, hops=1):
        """Files connected to any of ``files``: ``{file: weight in (0, 1)}``.

        Weight is the edge strength (EXTRACTED edges count fully, inferred ones less), squashed
        so a heavily-connected file does not drown out the rest, and halved for the second hop.
        Files in ``files`` themselves are not returned.
        """
        start = set(files)
        seen = {}
        frontier = set(start)
        decay = 1.0
        for _hop in range(max(1, hops)):
            reached = {}
            for f in frontier:
                rows = self.store.conn.execute(
                    "SELECT dst AS other, weight FROM gedge WHERE src = ? "
                    "UNION ALL SELECT src AS other, weight FROM gedge WHERE dst = ?", (f, f)).fetchall()
                for r in rows:
                    other = r["other"]
                    if other in start:
                        continue
                    w = decay * (r["weight"] / (r["weight"] + 2.0))
                    if w > reached.get(other, 0.0):
                        reached[other] = w
            for other, w in reached.items():
                if w > seen.get(other, 0.0):
                    seen[other] = w
            frontier = set(reached)
            decay *= 0.5
        return seen

    def same_community(self, files):
        """Other files in the same community as any of ``files``."""
        comms = set()
        for f in files:
            i = self.info(f)
            if i and i["community"] is not None:
                comms.add(i["community"])
        if not comms:
            return set()
        marks = ",".join("?" * len(comms))
        rows = self.store.conn.execute(
            "SELECT file FROM gfile WHERE community IN (%s)" % marks, tuple(comms)).fetchall()
        return {r[0] for r in rows} - set(files)

    def community_names(self):
        rows = self.store.conn.execute(
            "SELECT community, community_name, COUNT(*) AS n FROM gfile WHERE community IS NOT NULL "
            "GROUP BY community, community_name ORDER BY n DESC").fetchall()
        return [(r["community"], r["community_name"], r["n"]) for r in rows]


# --------------------------------------------------------------------------- anchors & freshness

def make_anchor(store, project_root, rel, label=None, node_id=None, graph=None):
    """Hashes to remember about ``rel`` now, so a later change can be noticed."""
    graph = graph or GraphIndex(store)
    info = graph.info(rel) if graph.available else None
    return {"file": rel, "label": label, "node_id": node_id,
            "ast_hash": info["ast_hash"] if info else None,
            "sha": file_sha(project_root, rel) if project_root else None}


def anchor_state(store, project_root, anchor, graph=None):
    """``'fresh' | 'verify' | 'orphaned' | 'unknown'`` for one stored anchor, judged now."""
    if not project_root:
        return "unknown"                                # no project to compare against
    graph = graph or GraphIndex(store)
    rel = anchor["file"]
    info = graph.info(rel) if graph.available else None
    on_disk = os.path.isfile(os.path.join(project_root, rel))
    if not on_disk and info is None:
        return "orphaned"
    if anchor.get("kind") == "symbol" and anchor.get("label") and graph.available and info is not None:
        if not graph.symbol_present(anchor["label"], rel):
            return "orphaned"
    if anchor.get("ast_hash") and info and info.get("ast_hash"):
        return "fresh" if anchor["ast_hash"] == info["ast_hash"] else "verify"
    if anchor.get("sha") and on_disk:
        current = file_sha(project_root, rel)
        if current is None:
            return "unknown"
        return "fresh" if current == anchor["sha"] else "verify"
    return "unknown"


_ORDER = {"orphaned": 3, "verify": 2, "fresh": 1, "unknown": 0}


def memory_freshness(store, project_root, memory_id, graph=None):
    """The worst anchor state of a memory ('unknown' if it has no anchors)."""
    graph = graph or GraphIndex(store)
    worst = "unknown"
    for anchor in store.anchors_of(memory_id):
        state = anchor_state(store, project_root, anchor, graph)
        if _ORDER[state] > _ORDER[worst]:
            worst = state
    return worst


def status_lines(store, project_root):
    """Human lines for ``cc palace graph``."""
    paths = find_graphs(project_root)
    if not paths:
        return ["No Graphify graph found for this project.",
                "  Build one (offline, no model needed):  graphify update .",
                "  The palace works fully without it; with it, memories get anchors and freshness."]
    g = GraphIndex(store)
    lines = ["Graphify graph: %s" % ", ".join(os.path.relpath(p, project_root) for p in paths)]
    synced = store.meta_get("graph_synced") or "never"
    in_sync = store.meta_get("graph_fp") == _fingerprint(paths)
    n_files = store.conn.execute("SELECT COUNT(*) FROM gfile").fetchone()[0]
    n_syms = store.conn.execute("SELECT COUNT(*) FROM gsym").fetchone()[0]
    n_edges = store.conn.execute("SELECT COUNT(*) FROM gedge").fetchone()[0]
    lines.append("  linked: %d files, %d symbols, %d file-to-file links (synced %s%s)"
                 % (n_files, n_syms, n_edges, synced, "" if in_sync else "; graph changed since - run: cc palace graph --sync"))
    if g.available:
        top = g.community_names()[:5]
        if top:
            lines.append("  largest areas: " + ", ".join("%s (%d)" % (n or "#%s" % c, k) for c, n, k in top))
    return lines
