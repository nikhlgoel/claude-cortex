"""
Keeping the palace healthy: the maintenance the old ``last_consolidated`` timestamp only pretended to do.

``consolidate`` looks at the whole palace and reports what it would change; with ``apply=True`` it
performs only the **safe, reversible** parts:

* **freshness** - re-check each memory's anchors against the code (via ``graph.py``) and record
  fresh / verify / orphaned;
* **duplicates** - archive the newer of two near-identical memories (kept, linked, restorable);
* **stale episodes** - archive old, unused, low-importance episodes whose code is no longer fresh.

Judgement calls are **only ever proposed**, never applied: possible conflicts between two
decisions or facts, memories that look worth promoting to the always-on core, and clusters of
episodes that may deserve a distilled fact. A person (or Claude, with the person's approval)
decides those.
"""

from __future__ import annotations

import json
import os

from . import graph, text, write
from .store import iso, parse_iso

ARCHIVE_AFTER_DAYS = 120
_FACTUAL = ("decision", "fact", "structure", "preference", "rule")


def _age_days(row, now):
    stamp = parse_iso(row["recorded_at"])
    return (now - stamp).total_seconds() / 86400.0 if stamp else 0.0


# --------------------------------------------------------------------------- freshness

def freshness_report(store, project_root):
    """``{memory_id: (stored, current)}`` for active memories whose state differs from what is stored."""
    gi = graph.GraphIndex(store)
    rows = store.conn.execute(
        "SELECT m.id AS id, m.freshness AS stored FROM memory m WHERE m.status = 'active' "
        "AND EXISTS (SELECT 1 FROM anchor a WHERE a.memory = m.id)").fetchall()
    changed = {}
    for r in rows:
        current = graph.memory_freshness(store, project_root, r["id"], graph=gi)
        if current != "unknown" and current != r["stored"]:
            changed[r["id"]] = (r["stored"], current)
    return changed


# --------------------------------------------------------------------------- finding things

def find_duplicates(store):
    """``[(older_id, newer_id, jaccard)]`` for near-identical active memories (same kind, same numbers)."""
    pairs, seen = [], set()
    for row in store.list_memories(status="active", order="recorded_at ASC"):
        mine = write._stored_terms(store, row["id"])
        for mid, j, other in write._similar(store, mine, row["kind"]):
            if mid == row["id"] or (mid, row["id"]) in seen or (row["id"], mid) in seen:
                continue
            if j >= write._NEAR_DUPLICATE and write._numbers(mine) == write._numbers(other) and                     write.same_sequence(store, text.terms(row["title"] + " " + row["body"]), mid):
                a, b = sorted([store.get(mid), row], key=lambda r: r["recorded_at"])
                pairs.append((a["id"], b["id"], j))
                seen.add((a["id"], b["id"]))
    return pairs


def find_conflicts(store, limit=20):
    """Pairs of active decisions/facts that may contradict each other. Report only.

    Two memories of the same kind are suspect when they (a) have very similar titles, or (b) are
    anchored to the same file and share part of a title, or (c) share a title word that only a
    few memories use (the same *subject*, e.g. "storage", with possibly different answers).
    """
    rows = [r for r in store.list_memories(status="active", order="recorded_at ASC") if r["kind"] in _FACTUAL]
    files = {r["id"]: {a["file"] for a in store.anchors_of(r["id"])} for r in rows}
    title_terms = {r["id"]: set(text.terms(r["title"])) for r in rows}
    by_term = {}
    for r in rows:
        for t in title_terms[r["id"]]:
            by_term.setdefault((r["kind"], t), []).append(r["id"])
    topic = {}
    for (_kind, term), ids in by_term.items():
        if 2 <= len(ids) <= 3:                              # a subject few memories share
            for i, a_id in enumerate(ids):
                for b_id in ids[i + 1:]:
                    topic.setdefault((a_id, b_id), term)
    found = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a["kind"] != b["kind"]:
                continue
            title_sim = text.jaccard(title_terms[a["id"]], title_terms[b["id"]])
            shared = files[a["id"]] & files[b["id"]]
            subject = topic.get((a["id"], b["id"]))
            if not (title_sim >= 0.6 or (shared and title_sim >= 0.3) or subject):
                continue
            body_sim = text.jaccard(write._stored_terms(store, a["id"]), write._stored_terms(store, b["id"]))
            if body_sim >= write._NEAR_DUPLICATE:
                continue                                     # a duplicate, not a conflict
            found.append({"a": a["id"], "b": b["id"], "title_similarity": round(title_sim, 2),
                          "body_similarity": round(body_sim, 2), "shared_files": sorted(shared),
                          "subject": subject})
    found.sort(key=lambda c: -(c["title_similarity"] + (0.2 if c["shared_files"] else 0) + (0.1 if c["subject"] else 0)))
    return found[:limit]


def stale_episodes(store, now, days=ARCHIVE_AFTER_DAYS):
    """Old, unused, low-importance episodes whose code is not known to be fresh."""
    out = []
    for r in store.list_memories(status="active", tier=2):
        if r["pinned"] or r["uses"] or r["importance"] >= 0.6 or r["freshness"] == "fresh":
            continue
        if _age_days(r, now) >= days:
            out.append(r["id"])
    return out


def promotion_candidates(store):
    """Rules and preferences used often enough to deserve the always-on core. Proposal only."""
    out = []
    for r in store.list_memories(status="active", tier=3, order="importance DESC"):
        if r["kind"] in ("rule", "preference") and r["importance"] >= 0.8 and r["uses"] >= 3 \
                and r["trust"] in ("user", "agent") and not r["pinned"]:
            out.append(r["id"])
    return out


def clusters(store, min_size=3):
    """Groups of active episodes about the same file: candidates for one distilled fact."""
    by_file = {}
    for r in store.list_memories(status="active", tier=2):
        for a in store.anchors_of(r["id"]):
            by_file.setdefault(a["file"], set()).add(r["id"])
    out = []
    for file, ids in by_file.items():
        if len(ids) >= min_size:
            out.append({"file": file, "ids": sorted(ids), "titles": [store.get(i)["headline"] for i in sorted(ids)]})
    out.sort(key=lambda c: -len(c["ids"]))
    return out


# --------------------------------------------------------------------------- consolidate

def consolidate(store, project_root, now=None, apply=False, archive_days=ARCHIVE_AFTER_DAYS):
    """Inspect the palace; with ``apply`` perform the safe actions. Returns a report dict."""
    now = now or store.clock()
    report = {"applied": apply, "freshness": freshness_report(store, project_root),
              "duplicates": find_duplicates(store), "stale": stale_episodes(store, now, archive_days),
              "conflicts": find_conflicts(store), "promotions": promotion_candidates(store),
              "clusters": clusters(store)}
    if apply:
        with store.tx():
            for mid, (_old, new) in report["freshness"].items():
                store.update(mid, freshness=new)
                if new in ("verify", "orphaned"):
                    store.log("freshness", mid, {"state": new})
            for older, newer, j in report["duplicates"]:
                if store.get(newer)["status"] == "active":
                    store.update(newer, status="archived")
                    store.add_link(newer, older, "duplicate_of", j)
                    store.log("archive", newer, {"reason": "duplicate", "of": older})
            for mid in report["stale"]:
                store.update(mid, status="archived")
                store.log("archive", mid, {"reason": "stale episode"})
            store.meta_set("last_consolidated", iso(now))
            store.bump_rev()
    return report


def format_report(report, store):
    def name(mid):
        row = store.get(mid)
        return "%s  %s" % (mid, row["headline"][:60] if row else "(gone)")

    verb = "done" if report["applied"] else "would be done with --apply"
    lines = ["Consolidation report" + ("" if report["applied"] else " (dry run: nothing changed)")]
    fr = report["freshness"]
    lines.append("  Freshness changes: %d" % len(fr))
    for mid, (old, new) in list(fr.items())[:10]:
        lines.append("    %s -> %s: %s" % (old, new, name(mid)))
    lines.append("  Near-duplicates to archive: %d  [%s]" % (len(report["duplicates"]), verb))
    for older, newer, j in report["duplicates"][:10]:
        lines.append("    keep %s ; archive %s (%.0f%% alike)" % (older, newer, j * 100))
    lines.append("  Stale episodes to archive: %d  [%s]" % (len(report["stale"]), verb))
    for mid in report["stale"][:10]:
        lines.append("    " + name(mid))
    lines.append("Proposals (never applied automatically):")
    lines.append("  Possible conflicts: %d" % len(report["conflicts"]))
    for c in report["conflicts"][:10]:
        both = ""
        if c["shared_files"]:
            both = "  (both about " + ", ".join(c["shared_files"]) + ")"
        elif c.get("subject"):
            both = "  (same subject: %s)" % c["subject"]
        lines.append("    %s  <->  %s%s" % (name(c["a"]), name(c["b"]), both))
    lines.append("  Worth promoting to the always-on core: %d" % len(report["promotions"]))
    for mid in report["promotions"][:10]:
        lines.append("    %s   (cc palace tier %s 1)" % (name(mid), mid))
    lines.append("  Episode clusters that may deserve one distilled fact: %d" % len(report["clusters"]))
    for c in report["clusters"][:5]:
        lines.append("    %d episodes about %s" % (len(c["ids"]), c["file"]))
    return "\n".join(lines)


def stats(store):
    """Counts for ``cc palace status``."""
    c = store.conn

    def group(column):
        return {r[0]: r[1] for r in c.execute(
            "SELECT %s, COUNT(*) FROM memory WHERE status = 'active' GROUP BY %s" % (column, column))}
    try:
        size = os.path.getsize(store.path)
    except OSError:
        size = 0
    return {"active": store.count("active"), "superseded": store.count("superseded"),
            "archived": store.count("archived"), "by_tier": group("tier"), "by_kind": group("kind"),
            "by_freshness": group("freshness"),
            "anchors": c.execute("SELECT COUNT(*) FROM anchor").fetchone()[0],
            "events": c.execute("SELECT COUNT(*) FROM event").fetchone()[0],
            "last_consolidated": store.meta_get("last_consolidated"), "size_bytes": size}


def dumps(report):
    return json.dumps(report, indent=2, default=str)
