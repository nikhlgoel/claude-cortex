#!/usr/bin/env python3
"""
Claude Cortex - Cognitive Memory Palace Engine v2.5
Neuroscience-inspired cognitive architecture with inverted label indexing,
autonomous recall, room filtering, cooperative file-locking concurrency,
deduplication guards, and recency-weighted recall.
"""

import os
import sys
import json
import re
import argparse
import hashlib
import contextlib
import time
from datetime import datetime, timezone

ROOMS = {
    "blueprint": {
        "name": "The Blueprint Room",
        "file": "blueprint.md",
        "desc": "Semantic memory: system architecture, data models, contracts, tech stack.",
        "icon": "🏛️"
    },
    "procedures": {
        "name": "The Workshop",
        "file": "procedures.md",
        "desc": "Procedural memory: build recipes, verified workflows, test commands.",
        "icon": "⚙️"
    },
    "graveyard": {
        "name": "The Graveyard & Trophy Hall",
        "file": "graveyard.md",
        "desc": "Episodic memory: hard-won bugfixes, edge cases, traps, anti-patterns.",
        "icon": "🛡️"
    },
    "decisions": {
        "name": "The Council Chamber",
        "file": "decisions.md",
        "desc": "Architectural Decision Records (ADRs), trade-offs, design rationale.",
        "icon": "⚖️"
    },
    "working": {
        "name": "The Study",
        "file": "working.md",
        "desc": "Working memory: current sprint/session goals, immediate focus, next steps.",
        "icon": "📝"
    }
}

STOPWORDS = {
    "the", "and", "a", "an", "in", "on", "of", "to", "for", "with", "is", "at",
    "by", "this", "that", "it", "from", "as", "are", "be", "was", "or", "we", "i"
}

_LOCK_DEPTH = 0
_LOCK_FD = None
LOCK_TIMEOUT = 10.0


def _utf8_stdio():
    """Make printing the palace's emoji safe on a legacy console code page.

    Under the default Windows locale (cp1252) the very first ``print`` of a room
    icon raised UnicodeEncodeError, so every palace command - and the MCP
    remember/recall tools that spawn this script - failed before writing anything.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _first_line(text, limit):
    """First non-empty line of ``text`` (or ''), never raising on empty input."""
    lines = (text or "").strip().splitlines()
    return lines[0][:limit] if lines else ""


def _try_lock(fd):
    """One non-blocking attempt at an exclusive lock. True if acquired."""
    try:
        import fcntl
    except ImportError:
        fcntl = None
    try:
        if fcntl is not None:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        import msvcrt
        fd.seek(0)
        msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except (ImportError, AttributeError):
        return None        # no locking primitive on this platform
    except OSError:
        return False       # someone else holds it


def _unlock(fd):
    try:
        import fcntl
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        return
    except ImportError:
        pass
    except OSError:
        return
    try:
        import msvcrt
        fd.seek(0)
        msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
    except (ImportError, OSError):
        pass


@contextlib.contextmanager
def palace_lock(palace_dir):
    """Cooperative re-entrant cross-process file lock for memory palace writes.

    POSIX uses flock; Windows uses msvcrt.locking. The old code imported only
    fcntl and swallowed the ImportError, so on Windows the "lock" silently did
    nothing and concurrent writers (the hook, the MCP server, the CLI) could
    overwrite each other's index updates. Acquisition polls against a deadline
    rather than blocking forever; if it times out it warns and proceeds, because a
    stuck lock must never hang a hook.
    """
    global _LOCK_DEPTH, _LOCK_FD
    os.makedirs(palace_dir, exist_ok=True)
    lock_file = os.path.join(palace_dir, ".palace.lock")

    if _LOCK_DEPTH > 0:
        _LOCK_DEPTH += 1
        try:
            yield
        finally:
            _LOCK_DEPTH -= 1
        return

    fd = open(lock_file, "a", encoding="utf-8")
    deadline = time.monotonic() + LOCK_TIMEOUT
    held = False
    while True:
        state = _try_lock(fd)
        if state is None:                  # platform has no locking at all
            break
        if state:
            held = True
            break
        if time.monotonic() >= deadline:
            print("palace: timed out waiting for another process's lock; "
                  "continuing without it", file=sys.stderr)
            break
        time.sleep(0.05)

    _LOCK_FD = fd
    _LOCK_DEPTH = 1
    try:
        yield
    finally:
        _LOCK_DEPTH = 0
        if held:
            _unlock(fd)
        try:
            fd.close()
        except OSError:
            pass
        _LOCK_FD = None

def find_palace_dir():
    cwd = os.getcwd()
    try:
        import subprocess
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL,
            timeout=5).decode("utf-8", errors="replace").strip()
        if git_root:
            local_palace = os.path.join(git_root, ".claude", "palace")
            if os.path.exists(local_palace):
                return local_palace
    except Exception:
        pass

    clean_cwd = cwd.replace("/", "-").strip("-")
    project_palace = os.path.expanduser(f"~/.claude/projects/{clean_cwd}/palace")
    if os.path.exists(project_palace):
        return project_palace

    return os.path.expanduser("~/.claude/palace")

def load_index(palace_dir):
    index_file = os.path.join(palace_dir, "index.json")
    idx = {
        "palace_version": "2.5",
        "initialized_at": datetime.now(timezone.utc).isoformat(),
        "last_consolidated": datetime.now(timezone.utc).isoformat(),
        "stats": {"total_memories": 0, "total_tags": 0},
        "tag_index": {},
        "memories": {},
        "rooms": {}
    }
    if os.path.exists(index_file):
        try:
            with open(index_file, encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("top level is not an object")
            idx.update(loaded)
            idx.setdefault("stats", {"total_memories": 0, "total_tags": 0})
            idx.setdefault("tag_index", {})
            idx.setdefault("memories", {})
            idx.setdefault("rooms", {})
        except (OSError, ValueError) as exc:
            # Returning an empty index here is only safe if nothing then saves it:
            # the next `remember` would atomically replace index.json with the empty
            # one and erase every entry, tag and room count. Move the unreadable
            # file aside first, under the lock, and say so.
            with palace_lock(palace_dir):
                bad = f"{index_file}.corrupt-{int(time.time())}"
                try:
                    os.replace(index_file, bad)
                except OSError:
                    bad = "(could not move it aside)"
            print(f"palace: index.json unreadable ({exc}); kept as {bad}, "
                  f"starting a fresh index", file=sys.stderr)
    return idx

def save_index(palace_dir, idx):
    with palace_lock(palace_dir):
        index_file = os.path.join(palace_dir, "index.json")
        idx["last_consolidated"] = datetime.now(timezone.utc).isoformat()
        idx["stats"]["total_memories"] = len(idx.get("memories", {}))
        idx["stats"]["total_tags"] = len(idx.get("tag_index", {}))
        tmp_file = f"{index_file}.tmp.{os.getpid()}"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(idx, f, indent=2)
        os.replace(tmp_file, index_file)

def ensure_palace_structure(palace_dir):
    rooms_dir = os.path.join(palace_dir, "rooms")
    os.makedirs(rooms_dir, exist_ok=True)

    # The whole load -> modify -> save runs under the (re-entrant) lock. It used to
    # load outside it, so a concurrent `remember` could save a new memory between
    # this function's load and its save, and the stale snapshot then overwrote it.
    with palace_lock(palace_dir):
        index_path = os.path.join(palace_dir, "index.json")
        changed = not os.path.exists(index_path)
        idx = load_index(palace_dir)

        for rkey, rinfo in ROOMS.items():
            rpath = os.path.join(rooms_dir, rinfo["file"])
            if not os.path.exists(rpath):
                header = f"# {rinfo['icon']} {rinfo['name']}\n\n> {rinfo['desc']}\n\n---\n"
                with open(rpath, "w", encoding="utf-8") as f:
                    f.write(header)
                changed = True

            if rkey not in idx["rooms"]:
                idx["rooms"][rkey] = {
                    "name": rinfo["name"],
                    "file": f"rooms/{rinfo['file']}",
                    "entries_count": 0,
                    "tags": [],
                    "last_updated": datetime.now(timezone.utc).isoformat()
                }
                changed = True

        # Read-only commands (recall, status) call this too; only rewrite the index
        # when something was actually created, so reading never races a writer.
        if changed or not os.path.exists(index_path):
            save_index(palace_dir, idx)
    return palace_dir

def tokenize(text):
    words = re.findall(r'[a-zA-Z0-9_\-]+', text.lower())
    cleaned = []
    for w in words:
        w = w.strip("-_.")
        if len(w) > 2 and w not in STOPWORDS:
            cleaned.append(w)
    return cleaned

def resolve_room(room_query):
    if not room_query:
        return None
    rq = room_query.lower()
    for k in ROOMS:
        if rq in k or k in rq:
            return k
    return None

def remember(palace_dir, room_key, title, content, tags=None):
    if not (content or "").strip():
        print("palace: nothing to remember - the content is empty.", file=sys.stderr)
        return None
    ensure_palace_structure(palace_dir)

    with palace_lock(palace_dir):
        idx = load_index(palace_dir)

        # Match room
        resolved = resolve_room(room_key)
        if not resolved:
            resolved = "graveyard" if "bug" in title.lower() or "fix" in title.lower() else "blueprint"
        room_key = resolved

        rinfo = ROOMS[room_key]
        rpath = os.path.join(palace_dir, "rooms", rinfo["file"])
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Deduplication guard: a memory is a duplicate only if BOTH the title and
        # the content (its first line, as stored in the summary) already exist in
        # this room. The earlier version compared titles alone, so recording a
        # changed decision under an unchanged title ("pool size 10" -> "pool size
        # 50 after the outage") was discarded and reported as "already recorded" -
        # the model was told its new information was safe when it had been lost.
        title_clean = title.strip().lower()
        summary_clean = _first_line(content, 150).strip().lower()
        for mid, mdata in idx.get("memories", {}).items():
            if mdata.get("room") == room_key:
                exist_title = mdata.get("title", "").strip().lower()
                exist_summary = mdata.get("summary", "").strip().lower()
                same_title = exist_title == title_clean or (
                    len(title_clean) > 8 and title_clean in exist_title)
                if same_title and exist_summary == summary_clean:
                    print(f"ℹ Memory already recorded in {rinfo['icon']} {rinfo['name']} as [{mid}]: '{title}'. Skipped duplicate.")
                    return mid

        # Generate deterministic short ID
        h = hashlib.sha256(f"{room_key}:{title}:{datetime.now().timestamp()}".encode()).hexdigest()[:6]
        mem_id = f"{room_key[:4]}_{h}"

        # Auto-extract tags if not passed
        extracted_tags = set(tags or [])
        for word in tokenize(title + " " + content):
            if len(word) > 2 and word not in STOPWORDS:
                extracted_tags.add(word)

        clean_tags = []
        for t in extracted_tags:
            ct = t.strip("#.,!?:;\"'()[]{} \t\n\r").lower()
            if len(ct) > 2 and ct not in STOPWORDS:
                clean_tags.append(ct)
        final_tags = sorted(list(set(clean_tags)))[:10]

        # Markdown format
        tag_header = " ".join(f"#{t}" for t in final_tags)
        entry = f"\n### [{now_str}] {title} <!-- id:{mem_id} -->\n"
        entry += f"**Tags:** `{tag_header}`\n\n"
        entry += f"{content.strip()}\n"

        with open(rpath, "a", encoding="utf-8") as f:
            f.write(entry)

        # Update index
        idx.setdefault("memories", {})[mem_id] = {
            "id": mem_id,
            "room": room_key,
            "title": title,
            "tags": final_tags,
            "summary": content.strip().split("\n")[0][:150],
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Update inverted tag_index
        for t in final_tags:
            idx.setdefault("tag_index", {}).setdefault(t, [])
            if mem_id not in idx["tag_index"][t]:
                idx["tag_index"][t].append(mem_id)

        rmeta = idx["rooms"].setdefault(room_key, {})
        rmeta["entries_count"] = rmeta.get("entries_count", 0) + 1
        rmeta["last_updated"] = datetime.now(timezone.utc).isoformat()
        existing_tags = set(rmeta.get("tags", []))
        existing_tags.update(final_tags)
        rmeta["tags"] = sorted(list(existing_tags))

        save_index(palace_dir, idx)
        print(f"✓ Deposited memory [{mem_id}] into {rinfo['icon']} {rinfo['name']}: '{title}'")
        return mem_id

def recall(palace_dir, query, room=None, auto_mode=False, max_results=3):
    ensure_palace_structure(palace_dir)
    idx = load_index(palace_dir)

    terms = tokenize(query)
    if not terms:
        if not auto_mode:
            print("Please provide search keywords.")
        return []

    target_room = resolve_room(room) if room else None

    # Filter candidate memories by room if specified
    candidates = idx.get("memories", {})
    if target_room:
        candidates = {mid: m for mid, m in candidates.items() if m.get("room") == target_room}

    if not candidates:
        if not auto_mode:
            rname = ROOMS.get(target_room, {}).get("name", target_room or "all rooms")
            print(f"No memories found matching in {rname}.")
        return []

    # Score memories using inverted tag index, title terms, and recency weighting
    scores = {}
    for mid, mdata in candidates.items():
        m_tags = mdata.get("tags", [])
        title_terms = tokenize(mdata.get("title", ""))
        summary_terms = tokenize(mdata.get("summary", ""))

        score = 0.0
        for term in terms:
            for tag in m_tags:
                if term == tag:
                    score += 4.0
                elif term in tag or tag in term:
                    score += 2.0
            if term in title_terms:
                score += 3.0
            if term in summary_terms:
                score += 1.0

        if score > 0:
            # Recency bonus: recent memories receive a gentle priority boost
            created_str = mdata.get("created_at")
            if created_str:
                try:
                    dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
                    if age_days < 3:
                        score += 2.0
                    elif age_days < 14:
                        score += 1.0
                    elif age_days < 30:
                        score += 0.5
                except Exception:
                    pass
            scores[mid] = score

    sorted_mids = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_mids = [m[0] for m in sorted_mids[:max_results]]

    if not top_mids:
        if not auto_mode:
            rdesc = f" in {ROOMS[target_room]['name']}" if target_room else ""
            print(f"No specific memories found matching '{query}'{rdesc}.")
        return []

    # Fetch contents
    results = []
    for mid in top_mids:
        mdata = idx.get("memories", {}).get(mid)
        if not mdata:
            continue
        room_key = mdata.get("room")
        rinfo = ROOMS.get(room_key, {})
        rpath = os.path.join(palace_dir, "rooms", rinfo.get("file", ""))
        full_text = ""
        if os.path.exists(rpath):
            with open(rpath, encoding="utf-8") as f:
                content = f.read()
            pattern = re.compile(rf'(### .*?<!-- id:{mid} -->.*?)(?=\n### |\Z)', re.DOTALL)
            m = pattern.search(content)
            if m:
                full_text = m.group(1).strip()
            else:
                full_text = f"### {mdata.get('title')}\n{mdata.get('summary')}"
        results.append({
            "id": mid,
            "room": rinfo.get("name", room_key),
            "room_key": room_key,
            "icon": rinfo.get("icon", "📝"),
            "title": mdata.get("title"),
            "tags": mdata.get("tags", []),
            "content": full_text
        })

    if auto_mode:
        for r in results:
            print(f"{r['icon']} [{r['room'].upper()}] {r['title']} (tags: {', '.join(r['tags'])})")
            print(r['content'])
            print("---")
    else:
        print("======================================================================")
        room_suffix = f" in {ROOMS[target_room]['name']}" if target_room else ""
        print(f"      🏰 Palace Recall: Found {len(results)} relevant memories{room_suffix}")
        print("======================================================================")
        for r in results:
            print(f"{r['icon']} [{r['room'].upper()}] {r['title']}")
            print(r['content'])
            print("-" * 70)

    return results

def prune(palace_dir, mem_id=None, tag=None):
    ensure_palace_structure(palace_dir)

    with palace_lock(palace_dir):
        idx = load_index(palace_dir)
        removed = 0
        if mem_id:
            if mem_id in idx.get("memories", {}):
                mdata = idx["memories"].pop(mem_id)
                # Remove from tag_index
                for t in mdata.get("tags", []):
                    if t in idx.get("tag_index", {}):
                        idx["tag_index"][t] = [x for x in idx["tag_index"][t] if x != mem_id]
                        if not idx["tag_index"][t]:
                            del idx["tag_index"][t]
                # Remove from markdown file
                room_key = mdata.get("room")
                rinfo = ROOMS.get(room_key, {})
                rpath = os.path.join(palace_dir, "rooms", rinfo.get("file", ""))
                if os.path.exists(rpath):
                    with open(rpath, encoding="utf-8") as f:
                        content = f.read()
                    pattern = re.compile(rf'\n### .*?<!-- id:{mem_id} -->.*?(?=\n### |\Z)', re.DOTALL)
                    clean_content = pattern.sub('', content)
                    with open(rpath, "w", encoding="utf-8") as f:
                        f.write(clean_content)
                removed += 1
                print(f"✓ Pruned memory [{mem_id}] ({mdata.get('title')})")

        save_index(palace_dir, idx)
        if removed == 0 and mem_id:
            print(f"Memory ID '{mem_id}' not found.")

def show_status(palace_dir):
    ensure_palace_structure(palace_dir)
    idx = load_index(palace_dir)

    print("======================================================================")
    print("                    🏰 Claude Code Memory Palace v2.5")
    print("======================================================================")
    print(f"Location:           {palace_dir}")
    print(f"Total Memories:     {idx['stats'].get('total_memories', 0)}")
    print(f"Indexed Tags:       {idx['stats'].get('total_tags', 0)}")
    print(f"Last Consolidated:  {idx.get('last_consolidated', 'N/A')[:19]}")
    print("----------------------------------------------------------------------")
    print("Cognitive Memory Hierarchy:")

    room_mems = {}
    for mid, mdata in idx.get("memories", {}).items():
        rk = mdata.get("room", "blueprint")
        room_mems.setdefault(rk, []).append(mdata)

    room_items = list(ROOMS.items())
    for idx_r, (rkey, rinfo) in enumerate(room_items):
        is_last_room = (idx_r == len(room_items) - 1)
        r_prefix = "└── " if is_last_room else "├── "
        child_indent = "    " if is_last_room else "│   "

        rpath = os.path.join(palace_dir, "rooms", rinfo["file"])
        line_count = 0
        if os.path.exists(rpath):
            with open(rpath, encoding="utf-8") as f:
                line_count = len(f.readlines())

        mems_in_room = room_mems.get(rkey, [])
        tags_set = set()
        for m in mems_in_room:
            tags_set.update(m.get("tags", []))
        tags_str = " ".join(f"#{t}" for t in sorted(list(tags_set))[:5])
        if len(tags_set) > 5:
            tags_str += f" (+{len(tags_set)-5} more)"

        print(f"  {r_prefix}{rinfo['icon']} {rinfo['name'].upper()} ({rinfo['file']})")
        print(f"  {child_indent}├── Purpose: {rinfo['desc']}")
        print(f"  {child_indent}├── Metrics: {len(mems_in_room)} memories, {line_count} markdown lines")
        if tags_str:
            print(f"  {child_indent}├── Tags:    {tags_str}")

        if mems_in_room:
            sorted_mems = sorted(mems_in_room, key=lambda x: x.get("created_at", ""), reverse=True)
            print(f"  {child_indent}└── Recent Entries:")
            for m_idx, m in enumerate(sorted_mems[:3]):
                is_last_m = (m_idx == min(3, len(sorted_mems)) - 1) and (len(sorted_mems) <= 3)
                m_bullet = "└── " if is_last_m else "├── "
                m_date = m.get("created_at", "")[:10]
                print(f"  {child_indent}    {m_bullet}[{m.get('id', 'N/A')}] {m.get('title', '')} ({m_date})")
            if len(sorted_mems) > 3:
                print(f"  {child_indent}    └── ... (+{len(sorted_mems) - 3} older entries)")
        else:
            print(f"  {child_indent}└── No active memories recorded yet")

        if not is_last_room:
            print("  │")

    print("======================================================================")

def main():
    parser = argparse.ArgumentParser(description="Cognitive Memory Palace Engine v2.5")
    parser.add_argument("action", nargs="?", default="status",
                        choices=["status", "map", "tree", "init", "remember", "recall", "search", "auto-recall", "prune", "consolidate"])
    parser.add_argument("--room", "-r", help="Target room (blueprint, procedures, graveyard, decisions, working)")
    parser.add_argument("--title", "-t", help="Memory entry title")
    parser.add_argument("--content", "-c", help="Memory body content")
    parser.add_argument("--tags", nargs="*", help="Tags for inverted indexing")
    parser.add_argument("--query", "-q", help="Search query")
    parser.add_argument("--id", help="Memory ID to prune")
    parser.add_argument("--path", help="Custom palace directory")
    args, unknown = parser.parse_known_args()
    _utf8_stdio()

    palace_dir = args.path or find_palace_dir()

    if args.action == "init":
        ensure_palace_structure(palace_dir)
        print(f"✓ Memory Palace initialized at: {palace_dir}")
    elif args.action in ["status", "map", "tree"]:
        show_status(palace_dir)
    elif args.action == "remember":
        room = args.room
        title = args.title
        content = args.content
        # Titles are derived only AFTER the content is known to be non-empty. The
        # old code took content.splitlines()[0] while parsing positionals, so
        # `remember blueprint ""` raised IndexError before the usage check ran.
        if not room and unknown:
            room = unknown[0]
            if len(unknown) == 2:
                content = unknown[1]
            elif len(unknown) > 2:
                if not title:
                    title = unknown[1]
                if not content:
                    content = " ".join(unknown[2:])
        elif room and not content and unknown:
            if len(unknown) == 1:
                content = unknown[0]
            elif len(unknown) >= 2:
                if not title:
                    title = unknown[0]
                content = " ".join(unknown[1:])

        if not room or not (content or "").strip():
            print("Usage: cc palace remember <room> <notes> OR cc palace remember --room <room> --title <title> --content <content> [--tags <tags>]")
            sys.exit(1)
        if not title:
            title = _first_line(content, 60)
        remember(palace_dir, room, title, content, args.tags)
    elif args.action in ["recall", "search", "auto-recall"]:
        q = args.query or " ".join(unknown)
        if not q:
            if args.action == "auto-recall":
                sys.exit(0)
            print("Usage: cc palace recall [--room <room>] <query>")
            sys.exit(1)
        recall(palace_dir, q, room=args.room, auto_mode=(args.action == "auto-recall"))
    elif args.action == "prune":
        mem_id = args.id or (unknown[0] if unknown else None)
        if not mem_id:
            print("Usage: cc palace prune --id <memory_id>")
            sys.exit(1)
        prune(palace_dir, mem_id=mem_id)
    elif args.action == "consolidate":
        ensure_palace_structure(palace_dir)
        save_index(palace_dir, load_index(palace_dir))   # refresh the stats/timestamp
        print(f"✓ Consolidated and indexed Memory Palace at: {palace_dir}")

if __name__ == "__main__":
    main()
