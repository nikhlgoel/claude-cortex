"""
Grounding: check what a piece of text says about the code against what actually exists.

The commonest hallucination in a coding session is not a wrong idea but a wrong *name*: a file that was
never there, a function that was renamed two commits ago, a plausible path. The code graph (Graphify)
and the file system know the truth, so this looks things up instead of trusting them.

It is deliberately modest about what it can know:

* **Files** are checked against the disk first, then the graph. A path the graph lists but the disk
  does not has been deleted since the graph was built (``stale``). A path in neither is ``missing``,
  with the closest real names offered, because "you meant ``cortex/guard.py``" is the useful part.
* **Symbols** are only checked when they are written in backticks (like `profile_dir`): a bare word in a
  sentence is too often just a word. A name the graph does not have is ``unknown`` - it may be library
  code - unless a close match exists, which makes a typo or a rename the likely story (``missing``).
* With **no graph**, symbols are ``unchecked`` and only file paths are verified. Said plainly in the
  report; never guessed.

Nothing here raises for odd input, writes anything, or touches the network.
"""

from __future__ import annotations

import difflib
import os
import re

from . import graph as graph_mod
from . import text as text_mod

_TICK = re.compile(r"`([^`\n]{2,120})`")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\(\))?$")
_FILE_LIKE = re.compile(r"[\w\-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|cs|cpp|c|h|md|json|toml|yaml|yml|sh|ps1|cmd|sql|html|css)$")
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:/|/|~)")
_GENERIC = frozenset(("main", "run", "get", "set", "init", "test", "name", "type", "data", "self", "none", "true",
                      "false", "list", "dict", "str", "int", "open", "read", "write", "close", "path", "file", "args"))
_MAX_FILES = 40
_MAX_SYMBOLS = 40


# Boundaries exclude "-", ":", "@" and "~" as well as word characters, so a path inside a longer one
# (palace-test-ab12/project/x.py inside C:/Temp/palace-test-ab12/project/x.py) never comes out as a fragment.
_EDGE = r"(?<![\w/\\.\-:@~])"
_ABS = re.compile(_EDGE + r"((?:[A-Za-z]:[\\/]|~[\\/]|/)(?:[\w.\-@+]+[\\/])*[\w.\-@+]+\.[A-Za-z0-9]{1,6})(?![\w])")
_REL = re.compile(_EDGE + r"((?:[\w.\-]+[\\/])+[\w.\-]+\.[A-Za-z0-9]{1,6})(?![\w])")
_BARE = re.compile(_EDGE + r"([\w\-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|cs|cpp|c|h|md|json|toml|yaml|yml|sh|ps1|cmd|sql|html|css))\b")


def _file_claims(text):
    """File paths in ``text``: absolute ones first (and blanked out), then relative, then bare names."""
    text = text or ""
    found = []

    def take(pattern, where):
        for m in pattern.finditer(where):
            path = text_mod.clean_path(m.group(1))
            if path and path not in found:
                found.append(path)

    take(_ABS, text)
    rest = _ABS.sub(lambda m: " " * len(m.group(0)), text)
    take(_REL, rest)
    take(_BARE, rest)
    return found[:_MAX_FILES]


def _claims(text):
    files = _file_claims(text)
    symbols = []
    for m in _TICK.finditer(text or ""):
        token = m.group(1).strip()
        if _FILE_LIKE.search(token.replace("\\", "/").rsplit("/", 1)[-1]) or "/" in token or "\\" in token:
            continue                                    # a path: handled as a file
        if _NAME.match(token):
            name = token[:-2] if token.endswith("()") else token
            if name not in symbols:
                symbols.append(name)
    return files, symbols[:_MAX_SYMBOLS]


def _inside(root, absolute):
    try:
        rel = os.path.relpath(absolute, root)
    except ValueError:
        return None
    return None if rel.startswith("..") else text_mod.clean_path(rel)


def _check_file(path, root, index, graph_files, basenames):
    """One file claim -> {"path", "status", "resolved"?, "suggest"?}."""
    out = {"path": path, "status": "missing"}
    rel = path
    if _ABSOLUTE.match(path):
        if path.startswith("~"):
            out["status"] = "outside"
            return out
        inside = _inside(root, os.path.normpath(path)) if root else None
        if inside is None:
            out["status"] = "outside"                   # not this project's: not ours to judge
            return out
        rel = inside
    if root and os.path.isfile(os.path.join(root, rel)):
        out["status"] = "exists"
        return out
    if "/" not in rel:                                  # a bare name such as guard.py
        found = [f for f in graph_files if f == rel or f.endswith("/" + rel)]
        if len(found) == 1:
            if root and not os.path.isfile(os.path.join(root, found[0])):
                out.update(status="stale", resolved=found[0])
            else:
                out.update(status="exists", resolved=found[0])
            return out
        if len(found) > 1:
            out.update(status="ambiguous", suggest=sorted(found)[:5])
            return out
    elif rel in graph_files:
        out["status"] = "stale"                         # the graph knows it, the disk does not: deleted since
        return out
    near = difflib.get_close_matches(os.path.basename(rel), list(basenames), n=3, cutoff=0.8)
    suggest = []
    for b in near:
        suggest.extend(basenames[b][:2])
    if suggest:
        out["suggest"] = suggest[:4]
    return out


def verify(store, project_root, text, graph=None):
    """Check the files and backticked symbols in ``text``. See the module docstring for what each
    status means. Returns ``{"files": [...], "symbols": [...], "graph": bool, "problems": int}``."""
    graph = graph or graph_mod.GraphIndex(store)
    files, symbols = _claims(text)
    graph_files, basenames = set(), {}
    if graph.available:
        for row in store.conn.execute("SELECT file FROM gfile"):
            graph_files.add(row[0])
            basenames.setdefault(os.path.basename(row[0]), []).append(row[0])
    file_results = [_check_file(p, project_root, graph, graph_files, basenames) for p in files]

    symbol_results = []
    labels = None
    stems = {os.path.splitext(os.path.basename(f))[0] for f in graph_files}
    for name in symbols:
        entry = {"name": name}
        if not graph.available:
            entry["status"] = "unchecked"
            symbol_results.append(entry)
            continue
        parts = name.split(".")
        key = graph_mod.symbol_key(parts[-1])
        if len(parts) > 1:
            # module.attr or Class.method: only the project's own heads are ours to judge. `subprocess.run`
            # must not count as found just because this project also has a function called run.
            head = graph_mod.symbol_key(parts[0])
            ours = head in stems or store.conn.execute(
                "SELECT 1 FROM gsym WHERE norm_label = ? LIMIT 1", (head,)).fetchone()
            if not ours:
                entry["status"] = "external"            # os.path.join, np.array ...
                symbol_results.append(entry)
                continue
        if key in _GENERIC or len(key) < 4:
            entry["status"] = "unchecked"               # "main", "run", "get": a hit would prove nothing
            symbol_results.append(entry)
            continue
        rows = store.conn.execute("SELECT label, file FROM gsym WHERE norm_label = ? LIMIT 4", (key,)).fetchall()
        if rows:
            entry.update(status="found", where=sorted({r["file"] for r in rows})[:3])
        else:
            if labels is None:
                labels = {r[0]: r[1] for r in store.conn.execute("SELECT norm_label, label FROM gsym")}
            near = difflib.get_close_matches(key, list(labels), n=3, cutoff=0.8)
            if near:
                entry.update(status="missing", suggest=[labels[n] for n in near])
            else:
                entry["status"] = "unknown"             # nothing like it here; may be library code
        symbol_results.append(entry)

    problems = sum(1 for f in file_results if f["status"] in ("missing", "stale", "ambiguous")) \
        + sum(1 for s in symbol_results if s["status"] == "missing")
    return {"files": file_results, "symbols": symbol_results, "graph": bool(graph.available), "problems": problems}


_FILE_WORDS = {"exists": "ok", "stale": "DELETED since the graph was built", "missing": "NOT FOUND",
               "ambiguous": "several files by that name", "outside": "outside this project (not checked)"}
_SYMBOL_WORDS = {"found": "ok", "missing": "NOT FOUND (a close name exists)", "unknown": "not in this project's graph (may be library code)",
                 "external": "library code (not checked)", "unchecked": "not checked"}


def format_report(result):
    """Human text for ``cc palace verify`` and the MCP tool."""
    lines = []
    for f in result["files"]:
        line = "  file    %-44s %s" % (f["path"], _FILE_WORDS.get(f["status"], f["status"]))
        if f.get("resolved"):
            line += "  -> %s" % f["resolved"]
        if f.get("suggest"):
            line += "  (did you mean: %s)" % ", ".join(f["suggest"])
        lines.append(line)
    for s in result["symbols"]:
        line = "  symbol  %-44s %s" % (s["name"], _SYMBOL_WORDS.get(s["status"], s["status"]))
        if s.get("where"):
            line += "  in %s" % ", ".join(s["where"])
        if s.get("suggest"):
            line += "  (did you mean: %s)" % ", ".join(s["suggest"])
        lines.append(line)
    if not lines:
        return "Nothing to check: no file paths or `backticked` names found in the text."
    if not result["graph"] and result["symbols"]:
        lines.append("  (no code graph for this project, so names were not checked; build one: graphify update .)")
    head = ("%d reference%s to check before relying on:" % (result["problems"], "" if result["problems"] == 1 else "s")
            if result["problems"] else "Every file and name that could be checked exists.")
    return "\n".join([head] + lines)
