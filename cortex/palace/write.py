"""
The write path: turning something worth remembering into a stored, indexed, anchored memory.

What happens to a memory on the way in, and why:

1. **Secrets are scrubbed first.** Memory persists and is later injected into prompts.
2. **It is classified** (kind, tier, importance, confidence) by plain rules. No model is needed;
   a caller that knows better passes ``kind=`` / ``tier=``.
3. **Duplicates are recognised, changes are not mistaken for duplicates.** The v2.5 palace compared
   titles and first lines, so "pool size 10" followed by "pool size 50 after the outage" was
   discarded as already recorded - the one fact that mattered was lost. Here a near-duplicate must
   also agree on every *number*, and a same-titled decision/fact **supersedes** the old one instead.
4. **Facts keep their history.** A superseded memory is marked, dated and linked, never deleted.
5. **It is anchored to the code it concerns** (files and symbols), with hashes, so a later change
   to that code can flag the memory as possibly stale (see ``graph.py``).
6. **It is indexed** for keyword search with the same analyzer retrieval uses.
"""

from __future__ import annotations

import json
import os
import re

from . import PalaceError, graph, text
from .store import KINDS, TIERS, TRUSTS, iso, new_id

#: Where each kind lives by default. L1 (core) is never a default: it is earned or chosen.
KIND_TIER = {"decision": 3, "fact": 3, "structure": 3, "rule": 3, "preference": 3,
             "failure": 2, "fix": 2, "note": 2, "recipe": 4, "task": 0}
KIND_IMPORTANCE = {"rule": 0.9, "preference": 0.8, "decision": 0.8, "failure": 0.7, "fix": 0.6,
                   "recipe": 0.6, "structure": 0.6, "fact": 0.5, "note": 0.3, "task": 0.3}
TRUST_CONFIDENCE = {"user": 0.9, "agent": 0.7, "tool": 0.5, "web": 0.4}
#: Kinds where a new item with the same title replaces the old one (a decision changed, a fact updated).
SUPERSEDING_KINDS = frozenset({"decision", "fact", "structure", "preference", "rule"})
#: The old five "rooms", kept as a view label so nothing in the UI has to change on day one.
ROOM_OF = {"decision": "decisions", "fact": "blueprint", "structure": "blueprint",
           "failure": "graveyard", "fix": "graveyard", "recipe": "procedures",
           "task": "working", "note": "working", "rule": "blueprint", "preference": "blueprint"}

_NEAR_DUPLICATE = 0.92
_RELATED = 0.5

_RULE = re.compile(r"^\s*(always|never|must|do not|don't|dont)\b", re.I)
_PREFER = re.compile(r"^\s*(prefer|i prefer|we prefer)\b", re.I)
_DECISION = re.compile(r"\b(decided|decision|we chose|chose to|going with|instead of|trade-?off|adr)\b", re.I)
_FAILURE = re.compile(r"\b(bug|crash|traceback|regression|broke|broken|root cause|race condition|"
                      r"deadlock|leak|exception|error)\b", re.I)
_FIX = re.compile(r"\b(fix|fixed|workaround|resolved|patched)\b", re.I)
_RECIPE = re.compile(r"(\bhow to\b|\bsteps?:|\brun `|^```|\bto (build|test|deploy|install)\b)", re.I | re.M)
_STRUCTURE = re.compile(r"\b(architecture|module|layer|component|schema|data model|depends on|"
                        r"responsible for)\b", re.I)


def infer_kind(title, body):
    head = (title or "").strip()
    first = text.normalize_ws((body or "").split("\n", 1)[0])
    both = head + "\n" + (body or "")
    if _RULE.search(head) or _RULE.search(first):
        return "rule"
    if _PREFER.search(head) or _PREFER.search(first):
        return "preference"
    if _DECISION.search(both):
        return "decision"
    if _FAILURE.search(both):
        return "fix" if _FIX.search(both) and not re.search(r"\broot cause\b", both, re.I) else "failure"
    if _FIX.search(both):
        return "fix"
    if _RECIPE.search(both):
        return "recipe"
    if _STRUCTURE.search(both):
        return "structure"
    return "note"


def _title_key(title):
    return re.sub(r"[\s\W_]+", " ", (title or "").lower()).strip()


def _clean_tags(tags):
    if not tags:
        return []
    if isinstance(tags, str):
        tags = re.split(r"[,\s]+", tags)
    out = []
    for t in tags:
        t = str(t).strip().lstrip("#").lower()[:40]
        if t and t not in out:
            out.append(t)
    return out[:12]


def to_project_relative(project_root, path):
    """A forward-slash project-relative path, or None when ``path`` is outside the project."""
    p = text.clean_path(path)
    if not p:
        return None
    if os.path.isabs(path) or re.match(r"^[A-Za-z]:[/\\]", path or ""):
        if not project_root:
            return None
        try:
            rel = os.path.relpath(path, project_root).replace("\\", "/")
        except ValueError:
            return None
        return None if rel.startswith("..") else rel
    return p


def collect_anchors(store, project_root, body, explicit_paths=None):
    """Anchors (files, then symbols) a memory should carry. Only things that really exist count."""
    if not project_root:
        return []
    gi = graph.GraphIndex(store)
    anchors, seen = [], set()

    def add(rel, label=None, node_id=None, kind="file"):
        key = (rel, label)
        if key in seen:
            return
        seen.add(key)
        a = graph.make_anchor(store, project_root, rel, label=label, node_id=node_id, graph=gi)
        a["kind"] = kind
        anchors.append(a)

    for raw in list(explicit_paths or []) + text.paths_in(body):
        rel = to_project_relative(project_root, raw)
        if not rel:
            continue
        if os.path.isfile(os.path.join(project_root, rel)) or (gi.available and gi.info(rel)):
            add(rel)
        elif gi.available and "/" not in rel:
            unique = gi.resolve_basename(rel)
            if unique:
                add(unique)
    if gi.available:
        symbols = 0
        for name in text.identifier_candidates(body):
            hit = gi.resolve_symbol(name)
            if hit:
                add(hit["file"], label=hit["label"], node_id=hit["node_id"], kind="symbol")
                symbols += 1
            if symbols >= 6:
                break
    return anchors[:14]


def index_fields(row, anchors, tags):
    """The term lists stored in the keyword index for one memory."""
    anchor_text = " ".join([a["file"] for a in anchors] + [a["label"] for a in anchors if a.get("label")])
    return {"title": text.terms(row["title"]),
            "tags": text.terms(" ".join(tags)),
            "body": text.terms(row["body"]),
            "anchor": text.terms(anchor_text)}


def _stored_terms(store, memory_id):
    rows = store.conn.execute("SELECT term FROM posting WHERE memory = ? AND field IN ('title','body')",
                              (memory_id,)).fetchall()
    return {r[0] for r in rows}


_PROBE_CAP = 150          # a term in more than this many memories is "common" and is not worth probing with


def _rare_terms(store, tset, limit=10):
    """The ``limit`` rarest of ``tset`` that occur somewhere (rare terms have short posting lists)."""
    scored = []
    for term in sorted(tset, key=len, reverse=True)[:40]:
        n = store.conn.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM posting WHERE term = ? AND field IN ('title','body') LIMIT %d)"
            % _PROBE_CAP, (term,)).fetchone()[0]
        if 0 < n < _PROBE_CAP:
            scored.append((n, term))
    scored.sort()
    return [t for _n, t in scored[:limit]]


def _similar(store, tset, kind):
    """``[(memory_id, jaccard, terms)]`` for active memories of this kind sharing many terms.

    Candidates are found through the *rarest* terms (short lists, so the cost does not grow with the
    palace), then compared exactly. Their terms are fetched in one query, not one each.
    """
    probe = _rare_terms(store, tset)
    if not probe:
        return []
    marks = ",".join("?" * len(probe))
    rows = store.conn.execute(
        # CROSS JOIN fixes the order: start from the few postings of the rare terms and look each memory up
        # by key. Left to itself SQLite scanned every memory first, which made this quadratic.
        "SELECT p.memory AS mid, COUNT(DISTINCT p.term) AS hits FROM posting p CROSS JOIN memory m ON m.id = p.memory "
        "WHERE p.term IN (%s) AND p.field IN ('title','body') AND m.status = 'active' AND m.kind = ? "
        "GROUP BY p.memory ORDER BY hits DESC LIMIT 25" % marks, tuple(probe) + (kind,)).fetchall()
    ids = [r["mid"] for r in rows]
    if not ids:
        return []
    terms_of = {}
    for r in store.conn.execute(
            "SELECT memory, term FROM posting WHERE memory IN (%s) AND field IN ('title','body')"
            % ",".join("?" * len(ids)), tuple(ids)):
        terms_of.setdefault(r["memory"], set()).add(r["term"])
    scored = []
    for mid in ids:
        other = terms_of.get(mid, set())
        j = text.jaccard(tset, other)
        if j >= _RELATED:
            scored.append((mid, j, other))
    return scored


def _numbers(term_set):
    return {t for t in term_set if t.isdigit()}


_SAME_ORDER = 0.75


def same_sequence(store, my_terms, other_id):
    """Do the two texts share most adjacent word pairs, not just the same bag of words?

    "auth depends on cache" and "cache depends on auth" have identical word sets and opposite
    meanings; a duplicate must agree on order as well.
    """
    row = store.get(other_id)
    if row is None:
        return False
    other = text.terms(row["title"] + " " + row["body"])
    return text.jaccard(text.bigrams(my_terms), text.bigrams(other)) >= _SAME_ORDER


def remember(store, title, body="", *, kind=None, tier=None, tags=None, paths=None, trust="agent",
             pinned=False, importance=None, confidence=None, supersedes=None, session=None,
             commit=None, source_ref=None, project_root=None, room=None, valid_from=None,
             created_at=None):
    """Store one memory. Returns a dict: ``id``, ``action`` (created / duplicate / updated),
    plus ``superseded``, ``related``, ``redacted``, ``anchors`` and a human ``note``."""
    title = (title or "").strip()
    body = (body or "").strip()
    if not title and not body:
        raise PalaceError("Nothing to remember: give a title or some content.")
    if not title:
        title = text.normalize_ws(body.split("\n", 1)[0])[:80]
    if not body:
        body = title
    if trust not in TRUSTS:
        raise PalaceError("Unknown trust '%s' (use one of: %s)." % (trust, ", ".join(TRUSTS)))
    if kind is not None and kind not in KINDS:
        raise PalaceError("Unknown kind '%s' (use one of: %s)." % (kind, ", ".join(KINDS)))
    if tier is not None and tier not in TIERS:
        raise PalaceError("Unknown tier %r (use 0-5)." % (tier,))
    for name, value in (("importance", importance), ("confidence", confidence)):
        if value is not None and not (0.0 <= float(value) <= 1.0):
            raise PalaceError("%s must be between 0 and 1." % name)

    clean_title, k1 = text.scrub_secrets(title)
    clean_body, k2 = text.scrub_secrets(body)
    redacted = sorted(set(k1 + k2))
    kind = kind or infer_kind(clean_title, clean_body)
    tier = KIND_TIER[kind] if tier is None else tier
    tag_list = _clean_tags(tags)
    chash = text.content_hash(clean_title, clean_body)

    with store.tx():
        if source_ref:
            existing = store.find_by_source(source_ref)
            if existing:
                return {"id": existing["id"], "action": "duplicate", "superseded": [], "related": [],
                        "redacted": redacted, "anchors": 0, "note": "already imported from %s" % source_ref}
        same = store.find_by_hash(chash)
        if same:
            if pinned and not same["pinned"]:
                store.update(same["id"], pinned=1)
                store.log("pin", same["id"], {"via": "duplicate"})
            return {"id": same["id"], "action": "duplicate", "superseded": [], "related": [],
                    "redacted": redacted, "anchors": 0, "note": "identical memory already stored"}

        tset = set(text.terms(clean_title + " " + clean_body))
        explicit = [store.resolve_id(x) for x in (supersedes or [])]
        implicit = []
        if kind in SUPERSEDING_KINDS:
            key = _title_key(clean_title)
            for row in store.conn.execute(
                    "SELECT id, title FROM memory WHERE status = 'active' AND kind = ?", (kind,)):
                if _title_key(row["title"]) == key and row["id"] not in explicit:
                    implicit.append(row["id"])
        replaced = explicit + implicit

        related = []
        for mid, j, other in _similar(store, tset, kind):
            if mid in replaced:
                continue
            if j >= _NEAR_DUPLICATE and _numbers(tset) == _numbers(other) and                     same_sequence(store, text.terms(clean_title + " " + clean_body), mid):
                return {"id": mid, "action": "duplicate", "superseded": [], "related": [],
                        "redacted": redacted, "anchors": 0,
                        "note": "near-identical to an existing memory (%.0f%% of terms)" % (j * 100)}
            related.append(mid)

        now_s = iso(store.clock())
        mem_id = _unique_id(store)
        row = {
            "id": mem_id, "scope": store.scope, "tier": tier, "kind": kind,
            "room": room or ROOM_OF.get(kind), "title": clean_title,
            "headline": text.make_headline(clean_title, clean_body),
            "gist": text.make_gist(clean_body, clean_title),
            "body": clean_body, "tags": json.dumps(tag_list), "status": "active", "freshness": "unknown",
            "valid_from": valid_from or created_at or now_s, "valid_to": None,
            "recorded_at": created_at or now_s, "updated_at": now_s, "superseded_by": None,
            "confidence": float(confidence) if confidence is not None else TRUST_CONFIDENCE[trust],
            "importance": float(importance) if importance is not None else KIND_IMPORTANCE[kind],
            "pinned": 1 if pinned else 0, "uses": 0, "last_used": None, "content_hash": chash,
            "source_session": session, "source_commit": commit, "source_ref": source_ref, "trust": trust,
        }
        store.insert_memory(row)

        anchors = collect_anchors(store, project_root, clean_title + "\n" + clean_body, paths)
        for a in anchors:
            store.add_anchor(mem_id, a["kind"], a["file"], a.get("label"), a.get("node_id"),
                             a.get("ast_hash"), a.get("sha"))
        if anchors:
            store.update(mem_id, freshness="fresh")
        store.index_memory(mem_id, index_fields(row, anchors, tag_list))

        for old in replaced:
            _supersede(store, old, mem_id, now_s)
        for rel_id in related[:5]:
            store.add_link(mem_id, rel_id, "related", 0.5)
        store.log("remember", mem_id, {"kind": kind, "tier": tier, "trust": trust,
                                       "superseded": replaced, "redacted": redacted})
        store.bump_rev()

    note = []
    if replaced:
        note.append("replaces %d earlier memor%s (kept as history)"
                    % (len(replaced), "y" if len(replaced) == 1 else "ies"))
    if redacted:
        note.append("redacted: " + ", ".join(redacted))
    return {"id": mem_id, "action": "updated" if replaced else "created", "kind": kind, "tier": tier,
            "superseded": replaced, "related": related[:5], "redacted": redacted,
            "anchors": len(anchors), "note": "; ".join(note)}


def _unique_id(store):
    for _ in range(20):
        mid = new_id()
        if not store.get(mid):
            return mid
    raise PalaceError("Could not allocate a memory id.")


def _supersede(store, old_id, new_id_, now_s):
    store.update(old_id, status="superseded", valid_to=now_s, superseded_by=new_id_)
    store.add_link(new_id_, old_id, "supersedes", 1.0)
    store.log("supersede", old_id, {"by": new_id_})


def supersede(store, old_id, new_id_):
    """Mark ``old_id`` as replaced by ``new_id_`` (both must exist)."""
    old, new = store.resolve_id(old_id), store.resolve_id(new_id_)
    if old == new:
        raise PalaceError("A memory cannot replace itself.")
    with store.tx():
        _supersede(store, old, new, iso(store.clock()))
        store.bump_rev()
    return old, new


def set_pinned(store, memory_id, pinned=True):
    mid = store.resolve_id(memory_id)
    with store.tx():
        store.update(mid, pinned=1 if pinned else 0)
        store.log("pin" if pinned else "unpin", mid)
        store.bump_rev()
    return mid


def set_tier(store, memory_id, tier):
    if tier not in TIERS:
        raise PalaceError("Unknown tier %r (use 0-5)." % (tier,))
    mid = store.resolve_id(memory_id)
    with store.tx():
        store.update(mid, tier=tier)
        store.log("tier", mid, {"tier": tier})
        store.bump_rev()
    return mid


def archive(store, memory_id, restore=False):
    """Soft-delete (or restore). Nothing is lost; archived memories are simply not retrieved."""
    mid = store.resolve_id(memory_id)
    row = store.get(mid)
    if restore:
        if row["status"] == "superseded":
            raise PalaceError("%s was superseded by %s; restore the newer one instead."
                              % (mid, row["superseded_by"]))
        new_status = "active"
    else:
        new_status = "archived"
    with store.tx():
        store.update(mid, status=new_status)
        store.log("restore" if restore else "archive", mid)
        store.bump_rev()
    return mid


def reindex_all(store):
    """Rebuild every memory's keyword index (after the analyzer changed). Returns how many."""
    n = 0
    with store.tx():
        for row in store.conn.execute("SELECT * FROM memory").fetchall():
            row = dict(row)
            tags = json.loads(row["tags"] or "[]")
            store.index_memory(row["id"], index_fields(row, store.anchors_of(row["id"]), tags))
            n += 1
        store.meta_set("analyzer", text.ANALYZER_VERSION)
        store.bump_rev()
    return n


def ensure_index_current(store):
    """Reindex once if the index was built by an older analyzer. Cheap when already current."""
    if str(store.meta_get("analyzer", "")) == str(text.ANALYZER_VERSION):
        return 0
    if store.count(None) == 0:
        store.meta_set("analyzer", text.ANALYZER_VERSION)
        return 0
    return reindex_all(store)
