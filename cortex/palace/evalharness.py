"""
Measuring the palace: is retrieval actually better, or does it only feel better?

Given a corpus (memories + questions with known answers) this builds a throwaway palace, runs
every question through the new engine **and** the old v2.5 scorer, and reports:

* **hit@1 / hit@3 / MRR** - is the right memory first / in the top three / how high on average;
* **update correctness** - when a fact changed, does the newest win and the old one stay out;
* **false injection** - on prompts that should get nothing, how often was something injected
  (the number that decides whether auto-injection is safe to leave on);
* **tokens** - how much was injected per useful hit.

Cases flagged ``heldout`` are reported separately: thresholds are tuned on the rest only, so the
held-out score is the honest one.
"""

from __future__ import annotations

import json
import os
import runpy
import shutil
import tempfile
from datetime import datetime, timedelta, timezone

from . import PalaceError, legacy, retrieve, text, write
from .store import Store, iso

FIXED_NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)


def load_corpus(path):
    """A corpus from a ``.py`` module (``MEMORIES`` and ``CASES``) or a ``.json`` file."""
    try:
        if path.endswith(".json"):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        else:
            ns = runpy.run_path(path)
            data = {"MEMORIES": ns.get("MEMORIES"), "CASES": ns.get("CASES")}
    except (OSError, ValueError, SyntaxError) as exc:
        raise PalaceError("Cannot load the corpus %s: %s" % (path, exc))
    data = {k.upper(): v for k, v in data.items()}
    if not isinstance(data.get("MEMORIES"), list) or not isinstance(data.get("CASES"), list):
        raise PalaceError("%s must define MEMORIES and CASES lists." % path)
    return data


def _build_new(corpus, workdir, now):
    root = os.path.join(workdir, "project")
    os.makedirs(root, exist_ok=True)
    store = Store(os.path.join(workdir, "eval.db"), clock=lambda: now)
    ids = {}
    for m in sorted(corpus["MEMORIES"], key=lambda item: -float(item.get("age_days", 0))):
        for rel in m.get("paths", []):
            full = os.path.join(root, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write("# placeholder for the evaluation corpus\n")
        sup = [ids[m["supersedes"]]] if m.get("supersedes") else None
        when = iso(now - timedelta(days=float(m.get("age_days", 0))))
        r = write.remember(store, m["title"], m["body"], kind=m.get("kind"), paths=m.get("paths"),
                           supersedes=sup, project_root=root, created_at=when, valid_from=when,
                           importance=m.get("importance"), pinned=bool(m.get("pinned")))
        ids[m["key"]] = r["id"]
    return store, ids, root


def _legacy_memories(corpus, now):
    out = []
    for m in corpus["MEMORIES"]:
        when = iso(now - timedelta(days=float(m.get("age_days", 0))))
        out.append({"id": m["key"], "title": m["title"], "tags": legacy.legacy_tags(m["title"], m["body"]),
                    "summary": text.normalize_ws(m["body"].split("\n", 1)[0])[:150],
                    "created_at": when, "body": m["body"]})
    return out


def _case_new(store, ids_by_key, root, case, config, now):
    by_id = {v: k for k, v in ids_by_key.items()}
    result = retrieve.recall(store, case["query"], project_root=root, now=now, config=config)
    return [by_id[i["id"]] for i in result["items"] if i["id"] in by_id], result["tokens"]


def _case_legacy(memories, case, now):
    by_id = {m["id"]: m for m in memories}
    ids = legacy.legacy_recall(memories, case["query"], now)
    return ids, sum(text.estimate_tokens(by_id[i]["title"] + " " + by_id[i]["body"]) for i in ids)


def _score(corpus, runner, split):
    rel = {"n": 0, "hit1": 0, "hit3": 0, "mrr": 0.0, "tokens": 0, "hits": 0}
    upd = {"n": 0, "ok": 0}
    quiet = {"n": 0, "false": 0, "tokens": 0}
    failures = []
    for case in corpus["CASES"]:
        held = bool(case.get("heldout"))
        if (split == "tuned" and held) or (split == "heldout" and not held):
            continue
        keys, tokens = runner(case)
        if case["type"] == "relevant":
            rel["n"] += 1
            expect = set(case["expect"])
            rank = next((i for i, k in enumerate(keys, 1) if k in expect), None)
            if rank:
                rel["hits"] += 1
                rel["hit3"] += rank <= 3
                rel["hit1"] += rank == 1
                rel["mrr"] += 1.0 / rank
                rel["tokens"] += tokens
            else:
                failures.append((case["id"], case["query"], "expected %s, got %s" % (sorted(expect), keys)))
        elif case["type"] == "update":
            upd["n"] += 1
            ok = bool(set(case["expect"]) & set(keys)) and not (set(case.get("forbid", [])) & set(keys))
            upd["ok"] += ok
            if not ok:
                failures.append((case["id"], case["query"], "expected %s, forbid %s, got %s"
                                 % (case["expect"], case.get("forbid"), keys)))
        else:
            quiet["n"] += 1
            if keys:
                quiet["false"] += 1
                quiet["tokens"] += tokens
                failures.append((case["id"], case["query"], "injected %s" % keys))
    return rel, upd, quiet, failures


def _summarise(rel, upd, quiet):
    def pct(a, b):
        return round(100.0 * a / b, 1) if b else None
    return {
        "relevant_cases": rel["n"], "hit_at_1": pct(rel["hit1"], rel["n"]), "hit_at_3": pct(rel["hit3"], rel["n"]),
        "mrr": round(rel["mrr"] / rel["n"], 3) if rel["n"] else None,
        "tokens_per_hit": round(rel["tokens"] / rel["hits"]) if rel["hits"] else None,
        "update_cases": upd["n"], "update_correct": pct(upd["ok"], upd["n"]),
        "quiet_cases": quiet["n"], "false_injection": pct(quiet["false"], quiet["n"]),
        "tokens_per_false_injection": round(quiet["tokens"] / quiet["false"]) if quiet["false"] else 0,
    }


def evaluate(corpus, config=None, now=None, engines=("new", "legacy")):
    """Run the corpus. Returns ``{engine: {split: summary}}`` plus ``failures`` for the new engine."""
    now = now or FIXED_NOW
    workdir = tempfile.mkdtemp(prefix="palace-eval-")
    out = {}
    try:
        if "new" in engines:
            store, ids, root = _build_new(corpus, workdir, now)
            try:
                def run_new(case):
                    return _case_new(store, ids, root, case, config, now)
                out["new"], out["failures"] = {}, {}
                for split in ("all", "tuned", "heldout"):
                    rel, upd, quiet, fails = _score(corpus, run_new, split)
                    out["new"][split] = _summarise(rel, upd, quiet)
                    out["failures"][split] = fails
            finally:
                store.close()
        if "legacy" in engines:
            memories = _legacy_memories(corpus, now)

            def run_legacy(case):
                return _case_legacy(memories, case, now)
            out["legacy"] = {}
            for split in ("all", "tuned", "heldout"):
                rel, upd, quiet, _fails = _score(corpus, run_legacy, split)
                out["legacy"][split] = _summarise(rel, upd, quiet)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return out


def format_report(result):
    rows = [("hit@1 %", "hit_at_1"), ("hit@3 %", "hit_at_3"), ("MRR", "mrr"),
            ("tokens per hit", "tokens_per_hit"), ("update correct %", "update_correct"),
            ("false injection %", "false_injection"), ("tokens per false inj.", "tokens_per_false_injection")]
    engines = [e for e in ("new", "legacy") if e in result]
    lines = []
    for split in ("all", "heldout"):
        s = result[engines[0]][split]
        lines.append("")
        lines.append("%s: %d relevant, %d update, %d quiet" % (
            "ALL CASES" if split == "all" else "HELD-OUT (not tuned on)",
            s["relevant_cases"], s["update_cases"], s["quiet_cases"]))
        lines.append("  %-24s%s" % ("", "".join("%12s" % e for e in engines)))
        for label, key in rows:
            cells = "".join("%12s" % ("-" if result[e][split][key] is None else result[e][split][key])
                            for e in engines)
            lines.append("  %-24s%s" % (label, cells))
    fails = result.get("failures", {}).get("all", [])
    if fails:
        lines.append("")
        lines.append("New-engine misses (%d):" % len(fails))
        for cid, query, why in fails:
            lines.append("  %-4s %-58.58s  %s" % (cid, query, why))
    return "\n".join(lines).lstrip("\n")
