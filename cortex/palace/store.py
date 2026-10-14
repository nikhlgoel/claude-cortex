"""
Storage for the palace: one SQLite file per scope.

Why SQLite and not the old Markdown-plus-JSON files:

* several sessions (and the Desktop app, the terminal and a hook) write at once, and a file that
  is read, edited and rewritten loses entries when two of them race. SQLite in WAL mode with a
  busy timeout serialises writers and never shows a reader a half-written state;
* a query touches only the rows it needs instead of loading and scanning everything;
* the schema carries a version, so an upgrade is a deliberate migration, and a file written by a
  *newer* Cortex is refused instead of being silently "fixed".

The keyword index is plain tables (``posting``), not FTS5: SQLite builds differ in whether FTS5
is compiled in, and an analyzer that understands ``load_config`` / ``loadConfig`` / paths needs to
be ours anyway. One code path on every Python 3.8+.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from . import PalaceError

SCHEMA_VERSION = 1

TIERS = {0: "scratch", 1: "core", 2: "episodic", 3: "semantic", 4: "procedural", 5: "archive"}
KINDS = ("decision", "fact", "structure", "failure", "fix", "recipe", "rule", "preference",
         "task", "note")
TRUSTS = ("user", "agent", "tool", "web")
STATUSES = ("active", "superseded", "archived")
FRESHNESS = ("unknown", "fresh", "verify", "orphaned")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS memory (
    id            TEXT PRIMARY KEY,
    scope         TEXT NOT NULL DEFAULT 'project',
    tier          INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    room          TEXT,
    title         TEXT NOT NULL,
    headline      TEXT NOT NULL,
    gist          TEXT NOT NULL,
    body          TEXT NOT NULL,
    tags          TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'active',
    freshness     TEXT NOT NULL DEFAULT 'unknown',
    valid_from    TEXT NOT NULL,
    valid_to      TEXT,
    recorded_at   TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    superseded_by TEXT,
    confidence    REAL NOT NULL DEFAULT 0.7,
    importance    REAL NOT NULL DEFAULT 0.5,
    pinned        INTEGER NOT NULL DEFAULT 0,
    uses          INTEGER NOT NULL DEFAULT 0,
    last_used     TEXT,
    content_hash  TEXT NOT NULL,
    source_session TEXT,
    source_commit TEXT,
    source_ref    TEXT,
    trust         TEXT NOT NULL DEFAULT 'agent'
);
CREATE INDEX IF NOT EXISTS memory_status ON memory(status, tier);
CREATE INDEX IF NOT EXISTS memory_hash ON memory(content_hash);
CREATE INDEX IF NOT EXISTS memory_source ON memory(source_ref);

CREATE TABLE IF NOT EXISTS posting (
    term TEXT NOT NULL, memory TEXT NOT NULL, field TEXT NOT NULL, tf INTEGER NOT NULL,
    PRIMARY KEY (term, memory, field)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS posting_memory ON posting(memory);

CREATE TABLE IF NOT EXISTS fieldlen (
    memory TEXT NOT NULL, field TEXT NOT NULL, n INTEGER NOT NULL,
    PRIMARY KEY (memory, field)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS anchor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory TEXT NOT NULL, kind TEXT NOT NULL,
    file TEXT NOT NULL, label TEXT, node_id TEXT,
    ast_hash TEXT, sha TEXT, checked_at TEXT
);
CREATE INDEX IF NOT EXISTS anchor_memory ON anchor(memory);
CREATE INDEX IF NOT EXISTS anchor_file ON anchor(file);

CREATE TABLE IF NOT EXISTS link (
    src TEXT NOT NULL, dst TEXT NOT NULL, rel TEXT NOT NULL, weight REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (src, dst, rel)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS alias (term TEXT PRIMARY KEY, grp TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory TEXT NOT NULL, session TEXT, ts TEXT NOT NULL, resolution TEXT, outcome TEXT
);
CREATE INDEX IF NOT EXISTS feedback_memory ON feedback(memory);
CREATE INDEX IF NOT EXISTS feedback_session ON feedback(session, memory);

CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, op TEXT NOT NULL, memory TEXT, detail TEXT
);

CREATE TABLE IF NOT EXISTS gfile (
    file TEXT PRIMARY KEY, ast_hash TEXT, community INTEGER, community_name TEXT
);
CREATE TABLE IF NOT EXISTS gedge (
    src TEXT NOT NULL, dst TEXT NOT NULL, weight REAL NOT NULL, PRIMARY KEY (src, dst)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS gsym (
    node_id TEXT PRIMARY KEY, norm_label TEXT NOT NULL, label TEXT NOT NULL,
    file TEXT NOT NULL, kind TEXT
);
CREATE INDEX IF NOT EXISTS gsym_label ON gsym(norm_label);
"""
# gfile/gedge/gsym are a derived, file-level view of a code graph (see graph.py), rebuilt whenever
# the graph changes. They are caches: deleting them loses nothing.


def _statements():
    for statement in _SCHEMA.split(";\n"):
        statement = statement.strip()
        if statement:
            yield statement


# --------------------------------------------------------------------------- time and ids

def utc_now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    """Parse the timestamps this module writes; None when absent or malformed."""
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


def new_id():
    return "m_" + uuid.uuid4().hex[:10]


# --------------------------------------------------------------------------- where data lives

def home():
    """The palace home. ``CORTEX_DATA_DIR`` overrides; the default is shared by every profile
    and surface of this person, because a project's memory belongs to the project."""
    override = os.environ.get("CORTEX_DATA_DIR")
    base = override if override else os.path.join(os.path.expanduser("~"), ".cortex")
    return os.path.join(base, "palace")


def _git_dir_for(start):
    """Walk up from ``start`` to a directory holding ``.git``. Returns (root, gitpath) or (None, None)."""
    current = os.path.abspath(start)
    while True:
        candidate = os.path.join(current, ".git")
        if os.path.exists(candidate):
            return current, candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None, None
        current = parent


def _common_git_dir(gitpath):
    """The git directory shared by every worktree of a repository."""
    if os.path.isdir(gitpath):
        return os.path.abspath(gitpath)
    try:
        with open(gitpath, encoding="utf-8") as fh:
            line = fh.readline().strip()
    except OSError:
        return os.path.abspath(gitpath)
    if not line.startswith("gitdir:"):
        return os.path.abspath(gitpath)
    gitdir = line.split(":", 1)[1].strip()
    if not os.path.isabs(gitdir):
        gitdir = os.path.join(os.path.dirname(gitpath), gitdir)
    gitdir = os.path.abspath(gitdir)
    try:
        with open(os.path.join(gitdir, "commondir"), encoding="utf-8") as fh:
            common = fh.readline().strip()
        return os.path.abspath(os.path.join(gitdir, common))
    except OSError:
        return gitdir


def _slug(name):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return slug[:32] or "project"


def project_identity(cwd=None):
    """``(key, root)`` for the project containing ``cwd``.

    Worktrees of one repository share a key (they share a git common dir), so memory follows
    the project, not the checkout. Outside git, the directory itself is the project.
    """
    start = os.path.abspath(cwd or os.getcwd())
    root, gitpath = _git_dir_for(start)
    if root is None:
        root, canonical = start, start
    else:
        common = _common_git_dir(gitpath)
        canonical = os.path.dirname(common) if os.path.basename(common) == ".git" else common
    canonical = os.path.normcase(os.path.realpath(canonical))
    digest = hashlib.sha1(canonical.encode("utf-8", "replace")).hexdigest()[:8]
    name = os.path.basename(canonical.rstrip("\\/")) or "project"
    return "%s-%s" % (_slug(name), digest), root


def db_path(scope, cwd=None):
    if scope == "global":
        return os.path.join(home(), "global", "palace.db")
    key, _root = project_identity(cwd)
    return os.path.join(home(), "projects", key, "palace.db")


# --------------------------------------------------------------------------- the store

class Store:
    """One palace database. Methods are small and explicit; the logic lives in the other modules."""

    def __init__(self, path, scope="project", create=True, clock=None):
        self.path = path
        self.scope = scope
        self.clock = clock or utc_now
        self._depth = 0
        self._lock = threading.RLock()
        exists = os.path.exists(path)
        if not exists and not create:
            raise PalaceError("No palace yet at %s. Run: cc palace init" % path)
        if not exists:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            self.conn = sqlite3.connect(path, timeout=10.0, isolation_level=None,
                                        check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA busy_timeout = 10000")
            self.conn.execute("PRAGMA foreign_keys = ON")
            try:
                self.conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError:
                pass                                    # e.g. a filesystem without shared memory
            self.conn.execute("PRAGMA synchronous = NORMAL")
            self._migrate()
        except PalaceError:
            self.close()                                # e.g. a newer schema: release the file lock
            raise
        except sqlite3.DatabaseError as exc:
            self.close()
            raise PalaceError(
                "%s is not a usable palace database (%s). It was left untouched; move it aside "
                "or restore a copy, then run: cc palace init" % (path, exc))

    # -- lifecycle -----------------------------------------------------------------------

    def close(self):
        conn = getattr(self, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _migrate(self):
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise PalaceError(
                "This palace was written by a newer Cortex (schema %d, this one understands %d). "
                "Update Cortex; the file was not changed." % (version, SCHEMA_VERSION))
        if version == SCHEMA_VERSION:
            return
        with self.tx():
            for statement in _statements():
                self.conn.execute(statement)
            self.conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
            self.meta_set("created", iso(self.clock()))
            self.meta_set("scope", self.scope)

    @contextlib.contextmanager
    def tx(self):
        """A write transaction. Re-entrant: an inner ``tx`` joins the outer one."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                if outer:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self.conn.execute("COMMIT")

    def integrity(self):
        rows = self.conn.execute("PRAGMA integrity_check").fetchall()
        return [r[0] for r in rows]

    # -- meta ----------------------------------------------------------------------------

    def meta_get(self, key, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def meta_set(self, key, value):
        self.conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    def bump_rev(self):
        """Invalidate caches that depend on corpus statistics."""
        rev = int(self.meta_get("rev", "0")) + 1
        self.meta_set("rev", rev)
        return rev

    def rev(self):
        return int(self.meta_get("rev", "0"))

    # -- memories ------------------------------------------------------------------------

    _COLUMNS = ("id", "scope", "tier", "kind", "room", "title", "headline", "gist", "body", "tags",
                "status", "freshness", "valid_from", "valid_to", "recorded_at", "updated_at",
                "superseded_by", "confidence", "importance", "pinned", "uses", "last_used",
                "content_hash", "source_session", "source_commit", "source_ref", "trust")

    def insert_memory(self, row):
        cols = [c for c in self._COLUMNS if c in row]
        sql = "INSERT INTO memory(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols)))
        self.conn.execute(sql, [row[c] for c in cols])
        return row["id"]

    def get(self, memory_id):
        row = self.conn.execute("SELECT * FROM memory WHERE id = ?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def resolve_id(self, text):
        """An id, or an unambiguous prefix of one. Raises PalaceError when it does not resolve."""
        text = (text or "").strip()
        if not text:
            raise PalaceError("A memory id is required.")
        row = self.conn.execute("SELECT id FROM memory WHERE id = ?", (text,)).fetchone()
        if row:
            return row[0]
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.conn.execute("SELECT id FROM memory WHERE id LIKE ? ESCAPE '\\'",
                                 (escaped + "%",)).fetchall()
        if len(rows) == 1:
            return rows[0][0]
        if not rows:
            raise PalaceError("No memory with id '%s'." % text)
        raise PalaceError("'%s' matches %d memories; use more of the id." % (text, len(rows)))

    def update(self, memory_id, **fields):
        if not fields:
            return
        fields.setdefault("updated_at", iso(self.clock()))
        names = list(fields)
        bad = [n for n in names if n not in self._COLUMNS or n == "id"]
        if bad:
            raise PalaceError("Cannot update field(s): %s" % ", ".join(bad))
        sql = "UPDATE memory SET %s WHERE id = ?" % ", ".join("%s = ?" % n for n in names)
        self.conn.execute(sql, [fields[n] for n in names] + [memory_id])

    def count(self, status="active"):
        if status is None:
            return self.conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM memory WHERE status = ?", (status,)).fetchone()[0]

    def list_memories(self, status="active", tier=None, kind=None, limit=None, order="recorded_at DESC"):
        sql, args = "SELECT * FROM memory WHERE 1=1", []
        if status:
            sql += " AND status = ?"
            args.append(status)
        if tier is not None:
            sql += " AND tier = ?"
            args.append(tier)
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if order not in ("recorded_at DESC", "recorded_at ASC", "importance DESC", "last_used DESC"):
            order = "recorded_at DESC"
        sql += " ORDER BY " + order
        if limit:
            sql += " LIMIT %d" % int(limit)
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def find_by_hash(self, content_hash):
        row = self.conn.execute("SELECT * FROM memory WHERE content_hash = ? AND status = 'active' "
                                "ORDER BY recorded_at LIMIT 1", (content_hash,)).fetchone()
        return dict(row) if row else None

    def find_by_source(self, source_ref):
        row = self.conn.execute("SELECT * FROM memory WHERE source_ref = ? LIMIT 1", (source_ref,)).fetchone()
        return dict(row) if row else None

    # -- the keyword index ---------------------------------------------------------------

    def index_memory(self, memory_id, fields):
        """(Re)build the postings for a memory. ``fields`` maps field name -> list of terms."""
        self.conn.execute("DELETE FROM posting WHERE memory = ?", (memory_id,))
        self.conn.execute("DELETE FROM fieldlen WHERE memory = ?", (memory_id,))
        for field, term_list in fields.items():
            counts = {}
            for t in term_list:
                counts[t] = counts.get(t, 0) + 1
            if counts:
                self.conn.executemany(
                    "INSERT INTO posting(term, memory, field, tf) VALUES(?,?,?,?)",
                    [(t, memory_id, field, n) for t, n in counts.items()])
            self.conn.execute("INSERT INTO fieldlen(memory, field, n) VALUES(?,?,?)",
                              (memory_id, field, len(term_list)))

    # -- anchors, links, aliases, events, feedback ---------------------------------------

    def add_anchor(self, memory_id, kind, file, label=None, node_id=None, ast_hash=None, sha=None):
        self.conn.execute(
            "INSERT INTO anchor(memory, kind, file, label, node_id, ast_hash, sha, checked_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (memory_id, kind, file, label, node_id, ast_hash, sha, iso(self.clock())))

    def anchors_of(self, memory_id):
        return [dict(r) for r in self.conn.execute("SELECT * FROM anchor WHERE memory = ?", (memory_id,))]

    def add_link(self, src, dst, rel, weight=1.0):
        self.conn.execute(
            "INSERT INTO link(src, dst, rel, weight) VALUES(?,?,?,?) "
            "ON CONFLICT(src, dst, rel) DO UPDATE SET weight = excluded.weight", (src, dst, rel, weight))

    def links_of(self, memory_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM link WHERE src = ? OR dst = ?", (memory_id, memory_id))]

    def aliases(self):
        """term -> set of terms in the same group (default groups plus this project's own)."""
        from . import text
        groups = {}
        for group in text.DEFAULT_ALIAS_GROUPS:
            members = {text.stem(w) for w in group}
            for t in members:
                groups.setdefault(t, set()).update(members)
        custom = {}
        for row in self.conn.execute("SELECT term, grp FROM alias"):
            custom.setdefault(row["grp"], set()).add(text.stem(row["term"]))
        for members in custom.values():
            for t in members:
                groups.setdefault(t, set()).update(members)
        return groups

    def log(self, op, memory_id=None, detail=None):
        self.conn.execute("INSERT INTO event(ts, op, memory, detail) VALUES(?,?,?,?)",
                          (iso(self.clock()), op, memory_id,
                           json.dumps(detail, sort_keys=True) if detail is not None else None))

    def record_injection(self, memory_id, session, resolution):
        self.conn.execute("INSERT INTO feedback(memory, session, ts, resolution, outcome) VALUES(?,?,?,?,NULL)",
                          (memory_id, session, iso(self.clock()), resolution))

    def injected_in_session(self, session):
        """Memories already put in front of the model in this session and still in its context."""
        if not session:
            return set()
        rows = self.conn.execute(
            "SELECT DISTINCT memory FROM feedback WHERE session = ? AND COALESCE(outcome, '') != 'reset'", (session,))
        return {r[0] for r in rows}

    def forget_injections(self, session):
        """The conversation was compacted or cleared, so what was shown is no longer in front of the model
        and may be shown again. The rows stay (marked, not deleted): they are the usage history."""
        if not session:
            return 0
        with self.tx():
            cur = self.conn.execute(
                "UPDATE feedback SET outcome = 'reset' WHERE session = ? AND COALESCE(outcome, '') != 'reset'", (session,))
        return cur.rowcount

    # -- removal -------------------------------------------------------------------------

    def purge(self, memory_id):
        """Really delete a memory and everything derived from it (for privacy). Logs only the id."""
        with self.tx():
            for table in ("posting", "fieldlen", "anchor", "feedback"):
                self.conn.execute("DELETE FROM %s WHERE memory = ?" % table, (memory_id,))
            self.conn.execute("DELETE FROM link WHERE src = ? OR dst = ?", (memory_id, memory_id))
            self.conn.execute("UPDATE memory SET superseded_by = NULL WHERE superseded_by = ?", (memory_id,))
            self.conn.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
            self.log("purge", memory_id)
            self.bump_rev()


def open_store(scope="project", cwd=None, create=True, clock=None, path=None):
    """Open the palace for a scope. ``path`` overrides the location (tests, ``--path``)."""
    return Store(path or db_path(scope, cwd), scope=scope, create=create, clock=clock)
