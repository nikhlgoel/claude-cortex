"""Snapshot-and-verify for the folders that hold real accounts and settings.

The question this answers: *did that install / test / script change anything it should
not have?* Take a snapshot, do the risky thing (in a sandbox or for real), then verify.

Files are sorted into two kinds because Claude itself writes constantly while you work:

* ``protected`` - settings, configs, credentials, plugins, skills. Any change here is a
  failure the person should look at.
* ``live`` - history, sessions, projects, caches, logs. These change as a normal part of
  using Claude; they are summarised (count and size) and never fail the check.

Credential files are compared by size and modification time ONLY - their contents are
never read, hashed or stored. Snapshots live in their own folder, never inside the
folders being watched. For a clean verdict, close Claude Desktop first: it rewrites its
own config while running, and that will (correctly) show up as a change.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from . import registry
from .paths import home, shared_claude_dir

#: Directory names whose contents are volatile or disposable: counted, not compared.
LIVE_DIRS = frozenset({
    "cache", "code cache", "gpucache", "dawngraphitecache", "dawnwebgpucache", "crashpad",
    "logs", "blob_storage", "shared dictionary", "sentry", "shell-snapshots", "telemetry",
    "metrics", "session-env", "sessions", "session-data", "projects", "file-history",
    "backups", "claude-code", "claude-code-sessions", "local-agent-mode-sessions", "partitions",
    "indexeddb", "local storage", "session storage", "webstorage", "network", "shared_proto_db",
    "videodecodestats", "scratch-workspaces", "git-shadow", "cowork", "todos", "statsig", "debug",
})

#: Individual files that change while Claude runs.
LIVE_FILES = frozenset({
    "history.jsonl", ".claude.json", "bash-commands.log", "cost-tracker.log", ".last-cleanup",
    "window-state.json", "plan-usage-history.json", "dips", "dips-wal", "fcache", "lockfile",
    "sharedstorage", "declarative_performance_observer.db",
    "declarative_performance_observer.db-journal", "gpu-crash-streak", "update_cache.json",
    "mcp-needs-auth-cache.json", "remote-control-state.json", "git-worktrees.json",
    "buddy-tokens.json", "ant-device-registry.json", "ccd-ids.json",
})

#: Files compared by size + mtime only (their contents are never opened).
SECRET_FILES = frozenset({".credentials.json", "credentials.json", "config.json", "local state",
                          "cookies", "login data"})

HASH_LIMIT = 2 * 1024 * 1024


def store_dir():
    return os.path.join(home(), ".cortex-guard")


def default_roots():
    """Folders worth protecting: every registered profile folder plus the shared defaults."""
    roots = [shared_claude_dir()]
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(os.path.join(appdata, "Claude"))
    try:
        for entry in registry.load().values():
            roots += [p for p in (entry.get("config_dir"), entry.get("desktop_dir")) if p]
    except Exception:                       # a damaged registry must not stop a safety check
        pass
    unique, seen = [], set()
    for root in roots:
        key = os.path.normcase(os.path.abspath(root))
        if key not in seen and os.path.isdir(root):
            seen.add(key)
            unique.append(root)
    return unique


def _classify(rel_parts):
    """``'live'`` or ``'protected'`` for a path relative to its root."""
    for part in rel_parts[:-1]:
        if part.lower() in LIVE_DIRS:
            return "live"
    name = rel_parts[-1].lower()
    if name in LIVE_FILES or name.endswith((".tmp", ".log", "-journal", "-wal", ".lock")) \
            or ".tmp-" in name:
        return "live"
    return "protected"


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _count(folder):
    files = size = 0
    for base, _dirs, names in os.walk(folder):
        for name in names:
            try:
                size += os.path.getsize(os.path.join(base, name))
                files += 1
            except OSError:
                pass
    return files, size


def scan(roots):
    """Manifest ``{root: {"protected": {rel: info}, "live": {"files": n, "bytes": n}}}``."""
    manifest = {}
    for root in roots:
        protected, live_files, live_bytes = {}, 0, 0
        for base, dirs, files in os.walk(root, followlinks=False):
            rel_base = os.path.relpath(base, root)
            rel_dir = [] if rel_base == "." else rel_base.split(os.sep)
            keep = []
            for d in dirs:
                if d.lower() in LIVE_DIRS:          # counted by size, never descended into
                    n, size = _count(os.path.join(base, d))
                    live_files += n
                    live_bytes += size
                else:
                    keep.append(d)
            dirs[:] = keep
            for f in files:
                path = os.path.join(base, f)
                parts = rel_dir + [f]
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                if _classify(parts) == "live":
                    live_files += 1
                    live_bytes += st.st_size
                    continue
                info = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
                if f.lower() not in SECRET_FILES and st.st_size <= HASH_LIMIT:
                    try:
                        info["sha256"] = _sha256(path)
                    except OSError:
                        pass
                protected["/".join(parts)] = info
        manifest[root] = {"protected": protected, "live": {"files": live_files, "bytes": live_bytes}}
    return manifest


def _path(label):
    safe = "".join(c for c in label if c.isalnum() or c in "-_.") or "snapshot"
    return os.path.join(store_dir(), safe + ".json")


def snapshot(label, roots=None):
    roots = roots or default_roots()
    manifest = scan(roots)
    os.makedirs(store_dir(), exist_ok=True)
    payload = {"label": label, "taken": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "roots": manifest}
    with open(_path(label), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    files = sum(len(r["protected"]) for r in manifest.values())
    return {"path": _path(label), "roots": list(manifest), "protected_files": files}


def compare(before, after):
    """Differences between two ``scan`` manifests, as plain data."""
    result = {"added": [], "removed": [], "changed": [], "live": {}, "missing_roots": []}
    for root, old in before.items():
        new = after.get(root)
        if new is None:
            result["missing_roots"].append(root)
            continue
        for rel in sorted(set(old["protected"]) | set(new["protected"])):
            a, b = old["protected"].get(rel), new["protected"].get(rel)
            if a is None:
                result["added"].append(os.path.join(root, rel))
            elif b is None:
                result["removed"].append(os.path.join(root, rel))
            elif a.get("sha256") and b.get("sha256"):
                if a["sha256"] != b["sha256"]:
                    result["changed"].append(os.path.join(root, rel))
            elif (a["size"], a["mtime_ns"]) != (b["size"], b["mtime_ns"]):
                result["changed"].append(os.path.join(root, rel))
        result["live"][root] = {"files": new["live"]["files"] - old["live"]["files"],
                                "bytes": new["live"]["bytes"] - old["live"]["bytes"]}
    return result


def verify(label):
    """Compare now against snapshot ``label``. Returns ``(ok, result)``; raises if no snapshot."""
    with open(_path(label), encoding="utf-8") as fh:
        saved = json.load(fh)
    roots = list(saved["roots"])
    result = compare(saved["roots"], scan([r for r in roots if os.path.isdir(r)]))
    result["missing_roots"] += [r for r in roots if not os.path.isdir(r)]
    ok = not (result["added"] or result["removed"] or result["changed"] or result["missing_roots"])
    return ok, result


def render(ok, result):
    lines = []
    for key, title in (("missing_roots", "FOLDER MISSING"), ("removed", "REMOVED"),
                       ("changed", "CHANGED"), ("added", "ADDED")):
        for item in result[key]:
            lines.append(f"  {title:<14} {item}")
    for root, delta in result["live"].items():
        lines.append(f"  (live, expected to move) {root}: {delta['files']:+d} files, "
                     f"{delta['bytes'] / 1e6:+.1f} MB")
    lines.append("")
    lines.append("OK: no protected file was added, removed or changed." if ok else
                 "PROTECTED FILES DIFFER - look at the lines above before continuing.")
    return "\n".join(lines)
