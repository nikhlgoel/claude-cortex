#!/usr/bin/env python3
"""
Dream exploration archive.

A dream is a deep exploration of a concept, and it produces something worth
keeping - research, analysis, a decision map, an action plan. This is the
automation that persists each one, indexes it, and lets you recall it, so a
project accumulates a decision history instead of a scatter of one-off answers.

The point the framework leans on: saving is AUTOMATIC and STRUCTURED, not a
command the user remembers to run. Dream writes its full exploration here as the
last phase, every time.

Storage:
    ~/.claude/dreams/<date>-<slug>/exploration.md   the full write-up
    ~/.claude/dreams/<date>-<slug>/research.md       raw grounded findings
    ~/.claude/dreams/<date>-<slug>/meta.json         concept, crux, date, lenses
    ~/.claude/dreams/index.json                      one line per exploration

Commands:
    save --concept "..." --exploration FILE [--research FILE] [--crux "..."]
                                  [--lenses a,b] [--action "..."]
    list [--limit N]              recent explorations
    show <slug>                   print one exploration
    path --concept "..."          print the directory to write into (for the
                                  framework to target before it writes)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("CORTEX_DREAMS_ROOT")
            or (Path.home() / ".claude" / "dreams"))
INDEX = ROOT / "index.json"


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug[:48] or "concept")


def entry_dir(concept, when=None):
    when = when or time.strftime("%Y%m%d")
    return ROOT / f"{when}-{slugify(concept)}"


def _read_index():
    try:
        with open(INDEX, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def _write_index(entries):
    ROOT.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
    os.replace(tmp, INDEX)


def cmd_path(args):
    """Print (and create) the directory dream should write its files into."""
    directory = entry_dir(args.concept)
    directory.mkdir(parents=True, exist_ok=True)
    print(directory)
    return 0


def cmd_save(args):
    directory = entry_dir(args.concept)
    directory.mkdir(parents=True, exist_ok=True)

    def place(src, name):
        if not src:
            return None
        try:
            with open(src, encoding="utf-8") as fh:
                content = fh.read()
        except OSError as exc:
            print(f"dream-doc: cannot read {src}: {exc}", file=sys.stderr)
            return None
        dest = directory / name
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(content)
        return str(dest)

    exploration = place(args.exploration, "exploration.md")
    research = place(args.research, "research.md")

    meta = {
        "concept": args.concept,
        "slug": directory.name,
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "crux": args.crux or "",
        "lenses": [lens.strip() for lens in (args.lenses or "").split(",") if lens.strip()],
        "next_action": args.action or "",
        "files": {k: v for k, v in
                  (("exploration", exploration), ("research", research)) if v},
    }
    with open(directory / "meta.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    index = [e for e in _read_index() if e.get("slug") != directory.name]
    index.insert(0, {"slug": directory.name, "concept": args.concept,
                     "date": meta["date"], "crux": meta["crux"],
                     "next_action": meta["next_action"]})
    _write_index(index)

    print(f"Saved exploration -> {directory}")
    if meta["next_action"]:
        print(f"  next action: {meta['next_action']}")
    return 0


def cmd_list(args):
    entries = _read_index()[: args.limit]
    if not entries:
        print("No dream explorations yet.")
        return 0
    print("=" * 70)
    print(f"  Dream explorations ({len(entries)})")
    print("=" * 70)
    for e in entries:
        print(f"  {e['date']}  {e['concept']}")
        if e.get("crux"):
            print(f"      crux: {e['crux']}")
        if e.get("next_action"):
            print(f"      next: {e['next_action']}")
        print(f"      slug: {e['slug']}")
    print("=" * 70)
    return 0


def cmd_show(args):
    directory = ROOT / args.slug
    doc = directory / "exploration.md"
    if not doc.is_file():
        # Allow a bare concept too.
        matches = [e for e in _read_index()
                   if args.slug in e["slug"] or args.slug.lower() in e["concept"].lower()]
        if matches:
            doc = ROOT / matches[0]["slug"] / "exploration.md"
    if not doc.is_file():
        print(f"No exploration '{args.slug}'. Try: dream-doc.py list", file=sys.stderr)
        return 1
    print(doc.read_text(encoding="utf-8"))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Dream exploration archive")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("path")
    p.add_argument("--concept", required=True)
    p.set_defaults(func=cmd_path)

    p = sub.add_parser("save")
    p.add_argument("--concept", required=True)
    p.add_argument("--exploration", required=True)
    p.add_argument("--research")
    p.add_argument("--crux")
    p.add_argument("--lenses")
    p.add_argument("--action")
    p.set_defaults(func=cmd_save)

    p = sub.add_parser("list")
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show")
    p.add_argument("slug")
    p.set_defaults(func=cmd_show)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
