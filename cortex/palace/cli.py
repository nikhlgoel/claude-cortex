"""
``cc palace`` - the command line for the palace.

The default path is one command, no questions::

    cc palace init

It picks the right store for the project you are in, imports any old (v2.5) palace it finds without
touching it, links a Graphify graph if there is one, and prints what it did and what to try next.
Everything else is optional.

Output is plain ASCII on purpose: it is read by people on legacy Windows code pages, and by Claude.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import PalaceError, evalharness, graph, ground, legacy, lifecycle, retrieve, text, write
from . import hook as hook_mod
from . import store as store_mod
from .store import KINDS, TIERS

_OPENED = []        # stores opened by the running command; closed when it finishes

LEGACY_ROOMS = ("blueprint", "procedures", "graveyard", "decisions", "working")


# --------------------------------------------------------------------------- helpers

def _out(*parts):
    print(*parts)


def _err(*parts):
    print(*parts, file=sys.stderr)


def _open(args, create=True):
    scope = "global" if getattr(args, "scope", "project") == "global" else "project"
    path = getattr(args, "path", None)
    if path and (os.path.isdir(path) or not os.path.splitext(path)[1]):
        path = os.path.join(path, "palace.db")           # the old --path named a folder
    st = store_mod.open_store(scope=scope, cwd=os.getcwd(), create=create, path=path)
    _OPENED.append(st)
    st.reindexed = write.ensure_index_current(st)
    root = None if scope == "global" else store_mod.project_identity(os.getcwd())[1]
    return st, root


def _sync_graph(st, root):
    if not root:
        return None
    try:
        return graph.sync(st, root)
    except PalaceError as exc:
        _err("palace: %s" % exc)
        return None


def _fmt_tier(n):
    return "%d-%s" % (n, TIERS.get(n, "?"))


def _show(st, row):
    flags = []
    if row["pinned"]:
        flags.append("pinned")
    if row["status"] != "active":
        flags.append(row["status"])
    if row["freshness"] in ("verify", "orphaned"):
        flags.append("code " + ("changed" if row["freshness"] == "verify" else "gone"))
    _out("[%s] %s  (%s, %s%s)" % (row["id"], row["title"], row["kind"], _fmt_tier(row["tier"]),
                                  ", " + ", ".join(flags) if flags else ""))
    _out("  recorded %s, trust %s, importance %.1f, confidence %.1f, used %d time(s)"
         % (row["recorded_at"], row["trust"], row["importance"], row["confidence"], row["uses"]))
    for a in st.anchors_of(row["id"]):
        _out("  anchor: %s%s" % (a["file"], " :: " + a["label"] if a.get("label") else ""))
    if row.get("superseded_by"):
        _out("  superseded by %s" % row["superseded_by"])
    _out("")
    _out(row["body"])


# --------------------------------------------------------------------------- commands

def cmd_init(args):
    """One command, no questions."""
    st, root = _open(args)
    _out("Palace: %s" % st.path)
    _out("  scope: %s%s" % (st.scope, "   project: %s" % root if root else ""))
    if st.reindexed:
        _out("  keyword index rebuilt for %d memories (analyzer updated)" % st.reindexed)
    for old in ([] if args.no_import else legacy.find_legacy_dirs(os.getcwd())):
        dry = legacy.import_legacy(st, old, project_root=root, dry_run=True)
        if dry["imported"] == 0:
            _out("  old palace %s: already imported (%d memories)" % (old, dry["found"]))
            continue
        res = legacy.import_legacy(st, old, project_root=root)
        _out("  imported %d of %d memories from the old palace at %s" % (res["imported"], res["found"], old))
        _out("    (the old files were not changed or deleted)")
    if root:
        rep = _sync_graph(st, root)
        if rep and rep.get("graph"):
            _out("  Graphify graph linked: %d files, %d symbols" % (rep.get("files", 0), rep.get("symbols", 0)))
        else:
            _out("  No Graphify graph here (optional). Build one offline with:  graphify update .")
    _out("")
    _out("%d active memories. Try:" % st.count("active"))
    _out("  cc palace remember \"Title\" \"What happened and why\"")
    _out("  cc palace recall \"a question in your own words\"")
    _out("  cc palace status")
    return 0


def cmd_remember(args):
    st, root = _open(args)
    positional = list(args.text)
    title, body = args.title, args.content
    legacy_room = None
    if positional and positional[0].lower() in LEGACY_ROOMS and not args.kind:
        legacy_room = positional.pop(0).lower()          # old form: remember <room> <notes>
    if title is None and body is None:
        if len(positional) >= 2:
            title, body = positional[0], " ".join(positional[1:])
        elif len(positional) == 1:
            body = positional[0]
    if args.room and not legacy_room:
        legacy_room = args.room.lower()
    kind, tier = args.kind, args.tier
    if legacy_room and legacy_room not in LEGACY_ROOMS:
        raise PalaceError("Unknown room '%s'. Rooms: %s. (Or use --kind: %s)"
                          % (legacy_room, ", ".join(LEGACY_ROOMS), ", ".join(KINDS)))
    if legacy_room and not kind:
        tier0, kind = legacy.ROOM_MAP[legacy_room]
        tier = tier if tier is not None else tier0
    res = write.remember(st, title or "", body or "", kind=kind, tier=tier, tags=args.tags,
                         paths=args.path_arg, trust=args.trust, pinned=args.pin, importance=args.importance,
                         supersedes=args.supersedes, project_root=root, session=os.environ.get("CORTEX_SESSION"))
    verbs = {"created": "Stored", "updated": "Stored (replaces an earlier memory)", "duplicate": "Already known"}
    detail = ""
    if "tier" in res:
        detail = ", %s %s" % (res["kind"], _fmt_tier(res["tier"]))
    _out("%s [%s]%s%s" % (verbs[res["action"]], res["id"], detail, "; " + res["note"] if res["note"] else ""))
    if res["anchors"]:
        _out("  anchored to %d file/symbol(s) in the code" % res["anchors"])
    if res["related"]:
        _out("  related: %s" % ", ".join(res["related"]))
    return 0


def cmd_recall(args):
    query = " ".join(args.query).strip()
    if not query:
        if args.command == "auto-recall":
            return 0
        raise PalaceError("Give a question or topic: cc palace recall \"how does X work\"")
    try:
        st, root = _open(args, create=False)
    except PalaceError as exc:
        if "No palace yet" in str(exc):
            if args.command != "auto-recall":
                _out("No palace for this project yet, so nothing to recall. Set one up with:  cc palace init")
            return 0
        raise
    _sync_graph(st, root)
    result = retrieve.recall(st, query, project_root=root, budget=args.budget,
                             context={"files": args.file or []}, include_history=args.history,
                             include_core=args.core)
    if args.json:
        _out(json.dumps({"text": result["text"], "tokens": result["tokens"],
                         "items": [{k: v for k, v in i.items() if k != "why"} for i in result["items"]]}, indent=2))
        return 0
    if not result["text"]:
        if args.command != "auto-recall":
            _out("Nothing relevant in memory for that. (The palace stays silent when the evidence is thin.)")
            if args.explain:
                _out("  query terms: %s" % ", ".join(retrieve._query_terms(query)))
        return 0
    _out(result["text"])
    _out("")
    _out("(%d memories, about %d tokens%s)" % (len(result["items"]), result["tokens"],
                                              ", %d more did not fit" % result["dropped"] if result["dropped"] else ""))
    if args.explain:
        _out("")
        for cand in result["candidates"]:
            _out("%s  score %.3f" % (cand["id"], cand["score"]))
            for line in cand["why"]:
                _out("    " + line)
    if not args.no_record:
        retrieve.record_injection(st, result, session=os.environ.get("CORTEX_SESSION"))
    return 0


def cmd_expand(args):
    st, _root = _open(args, create=False)
    _show(st, st.get(st.resolve_id(args.id)))
    return 0


def cmd_status(args):
    st, root = _open(args, create=False)
    s = lifecycle.stats(st)
    _out("Palace: %s" % st.path)
    _out("  %d active, %d superseded (history), %d archived   (%.1f KB, %d events)"
         % (s["active"], s["superseded"], s["archived"], s["size_bytes"] / 1024.0, s["events"]))
    _out("  by tier: %s" % (", ".join("%s %d" % (_fmt_tier(t), n) for t, n in sorted(s["by_tier"].items())) or "-"))
    _out("  by kind: %s" % (", ".join("%s %d" % kv for kv in sorted(s["by_kind"].items())) or "-"))
    if s["by_freshness"]:
        _out("  freshness: %s" % ", ".join("%s %d" % kv for kv in sorted(s["by_freshness"].items())))
    _out("  last consolidated: %s" % (s["last_consolidated"] or "never"))
    if root:
        for line in graph.status_lines(st, root):
            _out(line)
    return 0


def cmd_list(args):
    st, _root = _open(args, create=False)
    rows = st.list_memories(status=None if args.all else "active", tier=args.tier, kind=args.kind,
                            limit=args.limit)
    for r in rows:
        _out("%s  %-10s %-12s %s%s" % (r["id"], r["kind"], _fmt_tier(r["tier"]), r["headline"],
                                       "  [%s]" % r["status"] if r["status"] != "active" else ""))
    if not rows:
        _out("No memories.")
    return 0


def cmd_pin(args, pinned=True):
    st, _root = _open(args, create=False)
    _out("%s %s" % ("Pinned" if pinned else "Unpinned", write.set_pinned(st, args.id, pinned)))
    return 0


def cmd_tier(args):
    st, _root = _open(args, create=False)
    mid = write.set_tier(st, args.id, args.tier)
    _out("%s is now %s%s" % (mid, _fmt_tier(args.tier),
                             "  (shown at the start of every session)" if args.tier == 1 else ""))
    return 0


def cmd_archive(args, restore=False):
    st, _root = _open(args, create=False)
    mid = write.archive(st, args.id, restore=restore)
    _out("Restored %s" % mid if restore else "Archived %s (reversible: cc palace restore %s)" % (mid, mid))
    return 0


def cmd_supersede(args):
    st, _root = _open(args, create=False)
    old, new = write.supersede(st, args.old, args.new)
    _out("%s is now history; %s is current." % (old, new))
    return 0


def cmd_forget(args):
    st, _root = _open(args, create=False)
    mid = st.resolve_id(args.id)
    if not args.yes:
        _out("This permanently deletes [%s] %s and everything derived from it." % (mid, st.get(mid)["title"]))
        _out("Archive instead (reversible):  cc palace archive %s" % mid)
        _out("To really delete:               cc palace forget %s --yes" % mid)
        return 1
    st.purge(mid)
    _out("Deleted %s." % mid)
    return 0


def cmd_about(args):
    st, root = _open(args, create=False)
    _sync_graph(st, root)
    target = args.target.replace("\\", "/")
    gi = graph.GraphIndex(st)
    files = []
    if gi.available:
        if gi.info(target):
            files = [target]
        elif "/" not in target and gi.resolve_basename(target):
            files = [gi.resolve_basename(target)]
        hit = gi.resolve_symbol(target)
        if hit and hit["file"] not in files:
            files.append(hit["file"])
    files = files or [target]
    seen = set()
    for f in files:
        for r in st.conn.execute(
                "SELECT DISTINCT m.id FROM anchor a JOIN memory m ON m.id = a.memory WHERE a.file = ? "
                "AND m.status = 'active' ORDER BY m.recorded_at DESC", (f,)).fetchall():
            if r[0] in seen:
                continue
            seen.add(r[0])
            row = st.get(r[0])
            _out("%s  %-10s %s%s" % (row["id"], row["kind"], row["headline"],
                                     "  [code changed]" if row["freshness"] == "verify" else ""))
    if not seen:
        _out("No memories are anchored to %s." % ", ".join(files))
    return 0


def cmd_verify(args):
    """Check the files and `backticked` names in some text against the project and its code graph."""
    if args.file:
        try:
            with open(args.file, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except OSError as exc:
            _err("palace: cannot read %s: %s" % (args.file, exc))
            return 2
    elif args.text == ["-"]:
        body = sys.stdin.read()
    else:
        body = " ".join(args.text or [])
    st, root = _open(args, create=False)
    _sync_graph(st, root)
    result = ground.verify(st, root, body)
    _out(json.dumps(result, indent=2) if args.json else ground.format_report(result))
    return 1 if result["problems"] else 0


def cmd_graph(args):
    st, root = _open(args, create=False)
    if not root:
        _out("The global palace is not tied to a project, so it has no code graph.")
        return 0
    if args.sync:
        rep = graph.sync(st, root, force=True)
        _out("Graph synced: %s" % ({k: v for k, v in rep.items() if k in ("files", "symbols", "edges")} or rep))
    for line in graph.status_lines(st, root):
        _out(line)
    return 0


def cmd_consolidate(args):
    st, root = _open(args, create=False)
    _sync_graph(st, root)
    _out(lifecycle.format_report(lifecycle.consolidate(st, root, apply=args.apply), st))
    return 0


def cmd_migrate(args):
    st, root = _open(args)
    sources = [args.source] if args.source else legacy.find_legacy_dirs(os.getcwd())
    if not sources:
        _out("No old palace found for this project. Nothing to import.")
        return 0
    for src in sources:
        res = legacy.import_legacy(st, src, project_root=root, dry_run=not args.apply)
        _out("%s: %d memories found, %d %s, %d already present%s"
             % (src, res["found"], res["imported"], "imported" if args.apply else "to import", res["skipped"],
                "" if args.apply else "   (dry run - add --apply to import; the old files are never changed)"))
    return 0


def cmd_export(args):
    st, _root = _open(args, create=False)
    os.makedirs(args.dir, exist_ok=True)
    by_room = {}
    for r in st.list_memories(status="active", order="recorded_at ASC"):
        by_room.setdefault(r["room"] or "notes", []).append(r)
    for room, rows in by_room.items():
        with open(os.path.join(args.dir, "%s.md" % room), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# %s\n\n> Generated from the palace database; edits here are not read back.\n\n" % room)
            for r in rows:
                fh.write("### %s <!-- id:%s -->\n" % (r["title"], r["id"]))
                fh.write("*%s, %s, recorded %s*\n\n%s\n\n" % (r["kind"], _fmt_tier(r["tier"]), r["recorded_at"], r["body"]))
    _out("Exported %d rooms to %s" % (len(by_room), args.dir))
    return 0


def cmd_eval(args):
    path = args.corpus
    if not path:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(here, "tests", "palace_corpus.py")
    if not os.path.isfile(path):
        raise PalaceError("No corpus at %s. Pass one with --corpus." % path)
    _out(evalharness.format_report(evalharness.evaluate(evalharness.load_corpus(path))))
    return 0


def cmd_inject(args):
    st, _root = _open(args, create=False)
    if args.state in ("on", "off"):
        with st.tx():
            st.meta_set("inject", args.state)
    state = st.meta_get("inject", "on")
    env_off = not hook_mod.enabled_by_env()
    _out("Automatic memory in prompts for this %s: %s%s" % (
        "project" if st.scope == "project" else "scope", state.upper(),
        "   (but CORTEX_PALACE=off is set in your environment, which overrides this)" if env_off else ""))
    if state == "on" and not env_off:
        _out("  Relevant memories are added to a prompt only when the evidence is strong; most prompts get nothing.")
    return 0


def cmd_ground(args):
    st, _root = _open(args, create=False)
    if args.state in ("on", "off"):
        with st.tx():
            st.meta_set("ground", args.state)
    state = st.meta_get("ground", "off")
    _out("Checking Claude's answers for invented file and function names, for this project: %s" % state.upper())
    if state == "on":
        _out("  After each answer, files and names that do not exist (with a close real match) are pointed out to Claude once.")
    else:
        _out("  Off by default. Turn on with: cc palace ground on      (Claude can also check by itself with the verify_refs tool.)")
    return 0


def cmd_doctor(args):
    st, root = _open(args, create=False)
    problems = 0
    check = st.integrity()
    ok = check == ["ok"]
    _out("  [%s] database integrity: %s" % ("ok" if ok else "FAIL", check[0] if ok else "; ".join(check[:3])))
    problems += 0 if ok else 1
    _out("  [ok] schema version %d" % st.conn.execute("PRAGMA user_version").fetchone()[0])
    stale = str(st.meta_get("analyzer", "")) != str(text.ANALYZER_VERSION)
    _out("  [%s] keyword index %s" % ("warn" if stale else "ok", "needs a rebuild: cc palace init" if stale else "is current"))
    orphan = st.conn.execute(
        "SELECT COUNT(*) FROM posting p WHERE NOT EXISTS (SELECT 1 FROM memory m WHERE m.id = p.memory)").fetchone()[0]
    _out("  [%s] orphan index rows: %d" % ("ok" if not orphan else "warn", orphan))
    if root:
        found = graph.find_graphs(root)
        _out("  [%s] Graphify graph: %s" % ("ok" if found else "info", "found" if found else "none (optional)"))
        changed = lifecycle.freshness_report(st, root)
        _out("  [%s] memories whose code changed or vanished: %d" % ("warn" if changed else "ok", len(changed)))
    pending = 0
    for d in legacy.find_legacy_dirs(os.getcwd()):
        try:
            pending += legacy.import_legacy(st, d, project_root=root, dry_run=True)["imported"]
        except PalaceError:
            pass
    _out("  [%s] old-palace memories not yet imported: %d" % ("warn" if pending else "ok", pending))
    return 1 if problems else 0


# --------------------------------------------------------------------------- parser

def build_parser():
    p = argparse.ArgumentParser(prog="cc palace", description="The Cortex memory palace.")
    p.add_argument("--scope", choices=["project", "global"], default="project",
                   help="which palace (default: the project you are in)")
    p.add_argument("--path", help="use a specific palace database file (testing, advanced)")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("init", help="set up the palace for this project (one command, no questions)")
    s.add_argument("--no-import", action="store_true", help="do not look for an old palace to import")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("remember", help="store a memory")
    s.add_argument("text", nargs="*", help="TITLE CONTENT  (or just CONTENT)")
    s.add_argument("--title", "-t")
    s.add_argument("--content", "-c")
    s.add_argument("--room", "-r", help="old-style room: %s" % ", ".join(LEGACY_ROOMS))
    s.add_argument("--kind", choices=KINDS)
    s.add_argument("--tier", type=int, choices=sorted(TIERS))
    s.add_argument("--tags", nargs="*")
    s.add_argument("--file", "--path-arg", nargs="*", dest="path_arg", help="files this memory is about")
    s.add_argument("--trust", choices=["user", "agent", "tool", "web"], default="agent")
    s.add_argument("--importance", type=float)
    s.add_argument("--pin", action="store_true")
    s.add_argument("--supersedes", nargs="*", help="ids of memories this replaces")
    s.set_defaults(func=cmd_remember)

    s = sub.add_parser("recall", aliases=["search", "auto-recall"], help="find relevant memories")
    s.add_argument("query", nargs="*")
    s.add_argument("--room", "-r", help=argparse.SUPPRESS)          # accepted for old callers, ignored
    s.add_argument("--query", "-q", dest="query_opt", help=argparse.SUPPRESS)
    s.add_argument("--budget", type=int, help="token budget (default %d)" % retrieve.CONFIG["budget"])
    s.add_argument("--file", action="append", help="a file you are working on (boosts memories about it)")
    s.add_argument("--history", action="store_true", help="include superseded memories")
    s.add_argument("--core", action="store_true", help="include always-on core memories")
    s.add_argument("--explain", action="store_true", help="show why each memory was chosen")
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-record", action="store_true", help="do not count this as an injection")
    s.set_defaults(func=cmd_recall)

    s = sub.add_parser("expand", help="show one memory in full")
    s.add_argument("id")
    s.set_defaults(func=cmd_expand)

    sub.add_parser("status", aliases=["map", "tree"], help="counts and health").set_defaults(func=cmd_status)

    s = sub.add_parser("list", help="list memories")
    s.add_argument("--all", action="store_true", help="include superseded and archived")
    s.add_argument("--tier", type=int, choices=sorted(TIERS))
    s.add_argument("--kind", choices=KINDS)
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(func=cmd_list)

    for name, pinned in (("pin", True), ("unpin", False)):
        s = sub.add_parser(name, help="%s a memory" % name)
        s.add_argument("id")
        s.set_defaults(func=lambda a, pinned=pinned: cmd_pin(a, pinned))

    s = sub.add_parser("tier", help="move a memory to a tier (1 = always-on core)")
    s.add_argument("id")
    s.add_argument("tier", type=int, choices=sorted(TIERS))
    s.set_defaults(func=cmd_tier)

    s = sub.add_parser("archive", aliases=["prune"], help="archive a memory (reversible)")
    s.add_argument("id", nargs="?")
    s.add_argument("--id", dest="id_opt")
    s.set_defaults(func=cmd_archive)
    s = sub.add_parser("restore", help="restore an archived memory")
    s.add_argument("id")
    s.set_defaults(func=lambda a: cmd_archive(a, restore=True))

    s = sub.add_parser("supersede", help="mark OLD as replaced by NEW")
    s.add_argument("old")
    s.add_argument("new")
    s.set_defaults(func=cmd_supersede)

    s = sub.add_parser("forget", help="permanently delete a memory")
    s.add_argument("id")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_forget)

    s = sub.add_parser("about", help="memories anchored to a file or symbol")
    s.add_argument("target")
    s.set_defaults(func=cmd_about)

    s = sub.add_parser("verify", help="check the files and `names` in some text against the code")
    s.add_argument("text", nargs="*", help="the text to check, or - to read standard input")
    s.add_argument("--file", help="read the text from a file")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("graph", help="the Graphify link")
    s.add_argument("--sync", action="store_true", help="re-read the graph now")
    s.set_defaults(func=cmd_graph)

    s = sub.add_parser("consolidate", help="maintenance: freshness, duplicates, proposals")
    s.add_argument("--apply", action="store_true", help="perform the safe, reversible actions")
    s.set_defaults(func=cmd_consolidate)

    s = sub.add_parser("migrate", help="import an old (v2.5) palace")
    s.add_argument("--source", help="the old palace folder (default: search for it)")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_migrate)

    s = sub.add_parser("export", help="write the palace as Markdown files")
    s.add_argument("dir")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("eval", help="measure retrieval quality against the test corpus")
    s.add_argument("--corpus")
    s.set_defaults(func=cmd_eval)

    s = sub.add_parser("inject", help="turn automatic memory in prompts on or off for this project")
    s.add_argument("state", nargs="?", choices=["on", "off", "status"], default="status")
    s.set_defaults(func=cmd_inject)

    s = sub.add_parser("ground", help="check Claude's answers for invented file/function names (off by default)")
    s.add_argument("state", nargs="?", choices=["on", "off", "status"], default="status")
    s.set_defaults(func=cmd_ground)

    sub.add_parser("doctor", help="check the palace for problems").set_defaults(func=cmd_doctor)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv or ["status"])
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    if args.command in ("recall", "search", "auto-recall"):
        args.query = list(args.query) + unknown + ([args.query_opt] if args.query_opt else [])
        unknown = []
        if args.command == "auto-recall":
            args.no_record = True
    if args.command in ("archive", "prune"):
        args.id = args.id or args.id_opt
        if not args.id:
            _err("Usage: cc palace archive <memory id>")
            return 2
    if unknown:
        _err("palace: unrecognised arguments: %s" % " ".join(unknown))
        return 2
    try:
        return int(args.func(args) or 0)
    except PalaceError as exc:
        _err("palace: %s" % exc)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        # In-process callers (cc's dispatcher, tests) must not keep database files locked.
        while _OPENED:
            _OPENED.pop().close()
