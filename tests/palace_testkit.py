"""
Shared helpers for the palace tests: a fixed clock, throwaway projects, and Graphify graphs in the
exact node-link shape the real tool writes (field names taken from a graph generated on this very
repository, so the tests fail if the bridge stops understanding the real format).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from cortex.palace import store as store_mod  # noqa: E402

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)


def days_ago(n):
    return NOW - timedelta(days=n)


def write_files(root, files):
    """``files`` maps relative path -> text. Returns ``root``."""
    for rel, content in files.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    return root


def write_graph(out_parent, files, links=(), graph_root=None):
    """Write ``<out_parent>/graphify-out/{graph.json,manifest.json,.graphify_root}``.

    ``files``: ``{source_file: {"symbols": [names], "community": int, "ast_hash": "..."}}`` with
    ``source_file`` relative to ``graph_root`` (default: ``out_parent``). ``links``: ``(a, b,
    relation, confidence)`` between source files (use "EXTRACTED" or "INFERRED").
    """
    graph_root = graph_root or out_parent
    out = os.path.join(out_parent, "graphify-out")
    os.makedirs(out, exist_ok=True)
    nodes, manifest, first_node = [], {}, {}
    for source, spec in files.items():
        stem = os.path.splitext(os.path.basename(source))[0]
        community = spec.get("community", 0)
        file_node = "%s_file" % stem
        nodes.append({"id": file_node, "label": os.path.basename(source),
                      "norm_label": os.path.basename(source).lower(), "file_type": "code",
                      "source_file": source, "source_location": "L1", "community": community,
                      "community_name": spec.get("community_name", stem), "_origin": "ast"})
        first_node[source] = file_node
        for name in spec.get("symbols", []):
            label = name + "()" if name[:1].islower() else name
            node = {"id": "%s_%s" % (stem, name.lower()), "label": label, "norm_label": label.lower(),
                    "file_type": "code", "source_file": source, "source_location": "L10",
                    "community": community, "community_name": spec.get("community_name", stem),
                    "_origin": "ast", "_callable": True}
            if name[:1].isupper():
                node["_callable_class"] = True
            nodes.append(node)
        manifest[source] = {"mtime": 1.0, "seen": 1.0, "ast_hash": spec.get("ast_hash", "hash-" + stem),
                            "semantic_hash": ""}
    edges = []
    for a, b, relation, confidence in links:
        edges.append({"source": first_node[a], "target": first_node[b], "relation": relation,
                      "confidence": confidence, "confidence_score": 1.0 if confidence == "EXTRACTED" else 0.8,
                      "_origin": "ast", "context": "call", "source_file": a, "source_location": "L5",
                      "weight": 1.0})
    # structural edges Graphify also writes; the bridge must ignore them
    for source, spec in files.items():
        stem = os.path.splitext(os.path.basename(source))[0]
        for name in spec.get("symbols", []):
            edges.append({"source": first_node[source], "target": "%s_%s" % (stem, name.lower()),
                          "relation": "contains", "confidence": "EXTRACTED", "confidence_score": 1.0,
                          "source_file": source, "source_location": "L10"})
    graph = {"directed": True, "multigraph": False, "graph": {}, "nodes": nodes, "links": edges,
             "hyperedges": []}
    with open(os.path.join(out, "graph.json"), "w", encoding="utf-8") as fh:
        json.dump(graph, fh)
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    with open(os.path.join(out, ".graphify_root"), "w", encoding="utf-8") as fh:
        fh.write(graph_root)
    return os.path.join(out, "graph.json")


def touch_graph(path):
    """Make the graph file look changed (new size and mtime)."""
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(" ")
    os.utime(path, None)


class PalaceCase(unittest.TestCase):
    """A temp directory, a fixed clock, an isolated palace home, and a ready store."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="palace-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.fake_user_home = os.path.join(self.tmp, "userhome")
        os.makedirs(self.fake_user_home)
        patcher = mock.patch.dict(os.environ, {"CORTEX_DATA_DIR": self.home, "PYTHONUTF8": "1",
                                               "HOME": self.fake_user_home, "USERPROFILE": self.fake_user_home})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("CORTEX_PALACE", None)
        self.now = NOW
        self.root = os.path.join(self.tmp, "project")
        os.makedirs(self.root)
        self.store = self.open_store()

    def open_store(self, name="palace.db"):
        st = store_mod.Store(os.path.join(self.tmp, name), clock=lambda: self.now)
        self.addCleanup(st.close)
        return st
