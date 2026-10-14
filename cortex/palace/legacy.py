"""
The v2.5 palace: import it, and keep its recall as a measuring stick.

* ``import_legacy`` reads the old ``index.json`` + ``rooms/*.md`` and writes memories into the new
  store. It **never modifies** the old files, and is idempotent (re-running adds nothing).
* ``legacy_recall`` is the old keyword scorer, ported faithfully (including its quirks, such as
  keeping the first ten *alphabetical* auto-tags), so the evaluation harness can show honestly
  whether the new engine is better rather than assuming it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone

from . import PalaceError, write
from .store import iso

#: old room -> (tier, kind)
ROOM_MAP = {"blueprint": (3, "structure"), "procedures": (4, "recipe"), "graveyard": (2, "failure"),
            "decisions": (3, "decision"), "working": (0, "task")}
ROOM_FILES = {"blueprint": "blueprint.md", "procedures": "procedures.md", "graveyard": "graveyard.md",
              "decisions": "decisions.md", "working": "working.md"}

_LEGACY_STOP = {"the", "and", "a", "an", "in", "on", "of", "to", "for", "with", "is", "at", "by", "this",
                "that", "it", "from", "as", "are", "be", "was", "or", "we", "i"}


# --------------------------------------------------------------------------- locating

def find_legacy_dirs(cwd=None):
    """Old palace folders that exist, nearest first (same search order the old engine used)."""
    cwd = os.path.abspath(cwd or os.getcwd())
    found = []

    def consider(path):
        if path and os.path.isfile(os.path.join(path, "index.json")) and path not in found:
            found.append(path)

    cur = cwd
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            consider(os.path.join(cur, ".claude", "palace"))
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    clean = cwd.replace("/", "-").replace("\\", "-").replace(":", "-").strip("-")
    consider(os.path.join(os.path.expanduser("~"), ".claude", "projects", clean, "palace"))
    consider(os.path.join(os.path.expanduser("~"), ".claude", "palace"))
    return found


# --------------------------------------------------------------------------- parsing

def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise PalaceError("Cannot read the old palace index %s: %s. It was not modified." % (path, exc))
    if not isinstance(data, dict):
        raise PalaceError("%s is not a palace index (top level is not an object)." % path)
    return data


def parse_legacy(palace_dir):
    """The old palace as a list of dicts: id, room, title, tags, summary, created_at, body."""
    index = _read_json(os.path.join(palace_dir, "index.json"))
    memories = index.get("memories")
    if not isinstance(memories, dict):
        return []
    room_text = {}
    for room, filename in ROOM_FILES.items():
        path = os.path.join(palace_dir, "rooms", filename)
        try:
            with open(path, encoding="utf-8") as fh:
                room_text[room] = fh.read()
        except OSError:
            room_text[room] = ""
    out = []
    for mid, meta in memories.items():
        if not isinstance(meta, dict):
            continue
        room = meta.get("room") if meta.get("room") in ROOM_MAP else "blueprint"
        body = _body_of(room_text.get(room, ""), mid) or meta.get("summary") or meta.get("title") or ""
        out.append({"id": mid, "room": room, "title": meta.get("title") or mid,
                    "tags": list(meta.get("tags") or []), "summary": meta.get("summary") or "",
                    "created_at": meta.get("created_at"), "body": body})
    return out


def _body_of(room_markdown, mid):
    m = re.search(r"### [^\n]*<!-- id:%s -->\n(.*?)(?=\n### |\Z)" % re.escape(mid), room_markdown, re.S)
    if not m:
        return ""
    block = re.sub(r"^\*\*Tags:\*\*[^\n]*\n", "", m.group(1).lstrip("\n"))
    return block.strip()


# --------------------------------------------------------------------------- importing

def import_legacy(store, palace_dir, project_root=None, dry_run=False):
    """Copy the old palace's memories into ``store``. Returns counts.

    Idempotent: each is stored with a ``source_ref`` of the old folder + id, and one already
    present is skipped. Old creation times are kept so recency stays truthful.
    """
    parsed = parse_legacy(palace_dir)
    tag = hashlib.sha1(os.path.abspath(palace_dir).encode("utf-8", "replace")).hexdigest()[:8]
    result = {"found": len(parsed), "imported": 0, "skipped": 0, "redacted": 0, "dry_run": dry_run}
    for m in parsed:
        ref = "legacy:%s:%s" % (tag, m["id"])
        if store.find_by_source(ref):
            result["skipped"] += 1
            continue
        if dry_run:
            result["imported"] += 1
            continue
        tier, kind = ROOM_MAP[m["room"]]
        when = _to_iso(m["created_at"])
        r = write.remember(store, m["title"], m["body"], kind=kind, tier=tier, tags=m["tags"],
                           trust="agent", source_ref=ref, project_root=project_root,
                           created_at=when, valid_from=when, room=m["room"])
        if r["action"] == "duplicate":
            result["skipped"] += 1
        else:
            result["imported"] += 1
        if r.get("redacted"):
            result["redacted"] += 1
    return result


def _to_iso(value):
    parsed = _parse(value)
    return iso(parsed) if parsed else None


# --------------------------------------------------------------------------- the old recall

def _legacy_tokens(text_):
    words = re.findall(r"[a-zA-Z0-9_\-]+", (text_ or "").lower())
    out = []
    for w in words:
        w = w.strip("-_.")
        if len(w) > 2 and w not in _LEGACY_STOP:
            out.append(w)
    return out


def legacy_tags(title, content):
    """The old auto-tagger: the first ten *alphabetical* words. Faithful, quirk included."""
    return sorted(set(_legacy_tokens(title + " " + content)))[:10]


def legacy_recall(memories, query, now, max_results=3):
    """The old scorer over ``memories`` (dicts with title, tags, summary, created_at).

    Returns the ids of the top results; a result needs only a score above zero, so it never
    abstains - that is exactly the behaviour being compared against.
    """
    terms = _legacy_tokens(query)
    scored = []
    for m in memories:
        title_terms = _legacy_tokens(m["title"])
        summary_terms = _legacy_tokens(m["summary"])
        score = 0.0
        for term in terms:
            for tag in m["tags"]:
                if term == tag:
                    score += 4.0
                elif term in tag or tag in term:
                    score += 2.0
            if term in title_terms:
                score += 3.0
            if term in summary_terms:
                score += 1.0
        if score > 0:
            created = _parse(m.get("created_at"))
            if created is not None:
                age_days = (now - created).total_seconds() / 86400.0
                score += 2.0 if age_days < 3 else 1.0 if age_days < 14 else 0.5 if age_days < 30 else 0.0
            scored.append((score, m["id"]))
    scored.sort(key=lambda s: -s[0])
    return [mid for _score, mid in scored[:max_results]]


def _parse(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
