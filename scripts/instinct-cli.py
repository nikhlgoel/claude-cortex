#!/usr/bin/env python3
"""
Instinct store - learned behavioural patterns with confidence.

Background: the /instinct-* commands come from the ECC continuous-learning
plugin and resolve that plugin's own CLI at runtime. When the plugin is present
they use it. This file is the fallback so the commands WORK even when it is not,
using Cortex-native storage instead of failing with a missing-script error.

An instinct is a small, learned rule: "when modifying code, grep first" at 70%
confidence. It differs from a memory-palace entry (a fact or decision) in that it
carries a confidence that rises with reinforcement and decays without it, and a
trigger describing when it applies.

Storage, matching the ECC layout so the two are interchangeable:
    global   ~/.claude/homunculus/instincts/<id>.json
    project  ~/.claude/homunculus/projects/<project-id>/instincts/<id>.json

Project instincts override global ones with the same id.

Commands:
    status                        show instincts, grouped by domain
    add <domain> <pattern>        record an instinct (--trigger, --scope, --confidence)
    reinforce <id>                raise confidence (learned again)
    weaken <id>                   lower confidence (contradicted)
    promote <id>                  move a project instinct to global
    prune [--below 0.2]           remove low-confidence instincts
    export [--out FILE]           write all instincts as JSON
    import <file> [--scope ...]   load instincts, merging by id
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# CORTEX_INSTINCT_ROOT lets tests point storage somewhere disposable. Without an
# override this is ~/.claude/homunculus, matching the ECC layout so the ECC
# plugin and this fallback read the same files.
HOME = Path.home()
_override = os.environ.get("CORTEX_INSTINCT_ROOT")
ROOT = Path(_override) if _override else HOME / ".claude" / "homunculus"
GLOBAL_DIR = ROOT / "instincts"

DOMAINS = ("workflow", "security", "performance", "testing", "style",
           "architecture", "debugging", "general")

CONFIDENCE_STEP = 0.1
DEFAULT_CONFIDENCE = 0.5
MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 0.99


def project_id():
    """Stable id for the current project: git remote if present, else path hash."""
    try:
        result = subprocess.run(["git", "remote", "get-url", "origin"],
                                capture_output=True, text=True, timeout=5)
        key = result.stdout.strip() or os.getcwd()
    except (OSError, subprocess.SubprocessError):
        key = os.getcwd()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    name = os.path.basename(os.getcwd()) or "project"
    return name, digest


def project_dir():
    _, digest = project_id()
    return ROOT / "projects" / digest / "instincts"


def _load_dir(directory, scope):
    items = []
    if not directory.is_dir():
        return items
    for path in sorted(directory.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        data["scope"] = scope
        data.setdefault("id", path.stem)
        items.append(data)
    return items


def load_all():
    """Global + project instincts, project overriding global by id."""
    merged = {i["id"]: i for i in _load_dir(GLOBAL_DIR, "global")}
    for instinct in _load_dir(project_dir(), "project"):
        merged[instinct["id"]] = instinct
    return list(merged.values())


def _dir_for_scope(scope):
    return project_dir() if scope == "project" else GLOBAL_DIR


def save(instinct):
    directory = _dir_for_scope(instinct.get("scope", "project"))
    directory.mkdir(parents=True, exist_ok=True)
    instinct["updated"] = int(time.time())
    payload = {k: v for k, v in instinct.items() if k != "scope"}
    path = directory / f"{instinct['id']}.json"
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)
    return path


def find(instinct_id):
    for instinct in load_all():
        if instinct["id"] == instinct_id:
            return instinct
    return None


def _bar(confidence):
    filled = int(round(confidence * 10))
    return "█" * filled + "░" * (10 - filled)


def cmd_status(_args):
    instincts = load_all()
    name, digest = project_id()

    print("=" * 60)
    print(f"  INSTINCT STATUS - {len(instincts)} total")
    print("=" * 60)
    print(f"  Project: {name} ({digest})")
    project = [i for i in instincts if i["scope"] == "project"]
    glob = [i for i in instincts if i["scope"] == "global"]
    print(f"  Project instincts: {len(project)}")
    print(f"  Global instincts:  {len(glob)}")

    if not instincts:
        print()
        print("  No instincts yet. Record one with:")
        print("    instinct-cli.py add workflow 'grep before editing' "
              "--trigger 'when modifying code'")
        print("=" * 60)
        return 0

    for scope_label, group in (("PROJECT-SCOPED", project), ("GLOBAL", glob)):
        if not group:
            continue
        print(f"\n## {scope_label}")
        by_domain = {}
        for instinct in group:
            by_domain.setdefault(instinct.get("domain", "general"), []).append(instinct)
        for domain in sorted(by_domain):
            print(f"  ### {domain.upper()} ({len(by_domain[domain])})")
            for instinct in sorted(by_domain[domain],
                                   key=lambda i: -i.get("confidence", 0)):
                conf = instinct.get("confidence", 0)
                print(f"    {_bar(conf)}  {int(conf * 100):3d}%  "
                      f"{instinct['pattern']}  [{instinct['id']}]")
                trigger = instinct.get("trigger")
                if trigger:
                    print(f"              trigger: {trigger}")
    print("=" * 60)
    return 0


def cmd_add(args):
    domain = args.domain.lower()
    if domain not in DOMAINS:
        print(f"Unknown domain '{domain}'. One of: {', '.join(DOMAINS)}",
              file=sys.stderr)
        return 2
    base = "-".join(args.pattern.lower().split()[:4])
    base = "".join(c for c in base if c.isalnum() or c == "-")[:40] or "instinct"
    instinct = {
        "id": f"{domain}-{base}",
        "domain": domain,
        "pattern": args.pattern,
        "trigger": args.trigger or "",
        "confidence": max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, args.confidence)),
        "observations": 1,
        "scope": args.scope,
        "created": int(time.time()),
    }
    path = save(instinct)
    print(f"Recorded instinct '{instinct['id']}' ({args.scope}) -> {path}")
    return 0


def _adjust(instinct_id, delta):
    instinct = find(instinct_id)
    if not instinct:
        print(f"No instinct '{instinct_id}'.", file=sys.stderr)
        return 2
    instinct["confidence"] = max(MIN_CONFIDENCE,
                                 min(MAX_CONFIDENCE,
                                     instinct.get("confidence", DEFAULT_CONFIDENCE) + delta))
    instinct["observations"] = instinct.get("observations", 1) + 1
    save(instinct)
    print(f"{instinct_id}: confidence now {int(instinct['confidence'] * 100)}%")
    return 0


def cmd_reinforce(args):
    return _adjust(args.id, CONFIDENCE_STEP)


def cmd_weaken(args):
    return _adjust(args.id, -CONFIDENCE_STEP)


def cmd_promote(args):
    instinct = find(args.id)
    if not instinct:
        print(f"No instinct '{args.id}'.", file=sys.stderr)
        return 2
    if instinct["scope"] == "global":
        print(f"'{args.id}' is already global.")
        return 0
    # Remove the project copy, write a global one.
    project_path = project_dir() / f"{args.id}.json"
    instinct["scope"] = "global"
    save(instinct)
    try:
        project_path.unlink()
    except OSError:
        pass
    print(f"Promoted '{args.id}' to global.")
    return 0


def cmd_prune(args):
    removed = 0
    for instinct in load_all():
        if instinct.get("confidence", 0) < args.below:
            directory = _dir_for_scope(instinct["scope"])
            try:
                (directory / f"{instinct['id']}.json").unlink()
                removed += 1
            except OSError:
                pass
    print(f"Pruned {removed} instinct(s) below {args.below:.0%} confidence.")
    return 0


def cmd_export(args):
    instincts = [{k: v for k, v in i.items() if k != "scope"} | {"scope": i["scope"]}
                 for i in load_all()]
    payload = json.dumps({"instincts": instincts}, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"Exported {len(instincts)} instinct(s) to {args.out}")
    else:
        print(payload)
    return 0


def cmd_import(args):
    source = args.source
    try:
        if source.startswith(("http://", "https://")):
            import urllib.request
            with urllib.request.urlopen(source, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        else:
            with open(source, encoding="utf-8") as fh:
                data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"Cannot read '{source}': {exc}", file=sys.stderr)
        return 1

    incoming = data.get("instincts", data if isinstance(data, list) else [])
    added = 0
    for instinct in incoming:
        if not isinstance(instinct, dict) or "pattern" not in instinct:
            continue
        if instinct.get("confidence", 1) < args.min_confidence:
            continue
        instinct.setdefault("id", f"{instinct.get('domain', 'general')}-"
                                  f"{abs(hash(instinct['pattern'])) % 10000}")
        instinct["scope"] = args.scope
        existing = find(instinct["id"])
        if existing and not args.force:
            continue
        if args.dry_run:
            print(f"  would import: {instinct['id']} ({args.scope})")
        else:
            save(instinct)
        added += 1
    verb = "would import" if args.dry_run else "imported"
    print(f"{verb} {added} instinct(s) into {args.scope} scope.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Cortex instinct store")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status").set_defaults(func=cmd_status)

    add = sub.add_parser("add")
    add.add_argument("domain")
    add.add_argument("pattern")
    add.add_argument("--trigger", default="")
    add.add_argument("--scope", choices=("project", "global"), default="project")
    add.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE)
    add.set_defaults(func=cmd_add)

    for name, func in (("reinforce", cmd_reinforce), ("weaken", cmd_weaken),
                       ("promote", cmd_promote)):
        p = sub.add_parser(name)
        p.add_argument("id")
        p.set_defaults(func=func)

    prune = sub.add_parser("prune")
    prune.add_argument("--below", type=float, default=0.2)
    prune.set_defaults(func=cmd_prune)

    export = sub.add_parser("export")
    export.add_argument("--out")
    export.set_defaults(func=cmd_export)

    imp = sub.add_parser("import")
    imp.add_argument("source")
    imp.add_argument("--scope", choices=("project", "global"), default="project")
    imp.add_argument("--min-confidence", type=float, default=0.0, dest="min_confidence")
    imp.add_argument("--force", action="store_true")
    imp.add_argument("--dry-run", action="store_true")
    imp.set_defaults(func=cmd_import)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        return cmd_status(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
