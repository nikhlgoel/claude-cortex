"""
Integrity manifest - verify that an install matches what was reviewed.

The concern this answers is the one a careful person has before installing:
"how do I know the files on my machine are the files I read in the repo, and not
something modified in transit or by a later process?" We built exactly this for
Ghidra (audit -> baseline -> diff on update). Cortex should be verifiable the
same way, about itself.

A manifest is a list of `sha256  relative/path` lines over the shipped payload -
the code the installer copies, nothing volatile. Generated from the repo at a
known commit, shipped alongside the install, and re-checked on the installed
tree, it makes a precise claim:

    the repo at commit X has manifest M
    my install matches M
    therefore my install is byte-for-byte the repo at X

Verification reports four states per file: ok, MODIFIED (hash differs), MISSING
(in the manifest, not on disk), and - separately - EXTRA files present in the
install that the manifest does not mention, which is how a leftover from an
older version or an injected file shows up.
"""

from __future__ import annotations

import hashlib
import os

# Directories and patterns that are payload, in the order the installer ships
# them. A file is included only if it lives under one of these roots.
# Roots snapshotted into the canonical install (cortex-core). The installer
# copies these there verbatim and generates the manifest over that copy, so
# verify has one coherent tree to check. Operational copies deployed elsewhere
# (hooks in ~/.claude/scripts, the wrapper in ~/.local/bin) are derived from
# this snapshot; the snapshot is what "matches the reviewed source" means.
PAYLOAD_ROOTS = ("cortex", "scripts", "config", "completion", "skills",
                 "tools/ghidra")

# Never part of the integrity claim: generated, per-machine, or volatile.
EXCLUDE_DIRS = {".git", "__pycache__", "build", "dist", "node_modules",
                ".ghidra-test", "ghidra-out", "releases"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".tmp", ".bak", ".log")
EXCLUDE_NAMES = {"MANIFEST.sha256", "watch-state.json", "baseline-current.json",
                 ".last-cleanup", "current_profile"}

MANIFEST_NAME = "MANIFEST.sha256"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _included(rel):
    parts = rel.replace("\\", "/").split("/")
    if any(p in EXCLUDE_DIRS for p in parts):
        return False
    if os.path.basename(rel) in EXCLUDE_NAMES:
        return False
    if rel.endswith(EXCLUDE_SUFFIXES):
        return False
    # Must sit under a payload root.
    normalized = rel.replace("\\", "/")
    return any(normalized == root or normalized.startswith(root + "/")
               for root in PAYLOAD_ROOTS)


def shipped_files(root):
    """Every payload file under root, as sorted relative paths."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if _included(rel):
                found.append(rel)
    return sorted(found)


def build_manifest(root):
    """Return {relative_path: sha256} for the payload under root."""
    return {rel: _sha256(os.path.join(root, rel)) for rel in shipped_files(root)}


def write_manifest(root, out_path=None):
    manifest = build_manifest(root)
    out_path = out_path or os.path.join(root, MANIFEST_NAME)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        for rel in sorted(manifest):
            fh.write(f"{manifest[rel]}  {rel}\n")
    return out_path, len(manifest)


def read_manifest(path):
    manifest = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or "  " not in line:
                continue
            digest, rel = line.split("  ", 1)
            manifest[rel] = digest
    return manifest


def verify(root, manifest):
    """Compare the tree at root against a manifest.

    Returns (ok, modified, missing, extra) as lists of relative paths.
    """
    ok, modified, missing = [], [], []
    for rel, expected in sorted(manifest.items()):
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            missing.append(rel)
            continue
        actual = _sha256(full)
        (ok if actual == expected else modified).append(rel)

    on_disk = set(shipped_files(root))
    extra = sorted(on_disk - set(manifest))
    return ok, modified, missing, extra


def render(root, manifest):
    ok, modified, missing, extra = verify(root, manifest)
    lines = ["=" * 70, "  Cortex integrity check", "=" * 70,
             f"  root: {root}", ""]

    total = len(manifest)
    lines.append(f"  {len(ok)}/{total} file(s) match the manifest")
    if not (modified or missing or extra):
        lines.append("")
        lines.append("  Every payload file matches. This install is byte-for-byte")
        lines.append("  the reviewed source.")
        lines.append("=" * 70)
        return "\n".join(lines), True

    lines.append("")
    if modified:
        lines.append(f"  MODIFIED ({len(modified)}) - content differs from the manifest:")
        for rel in modified[:30]:
            lines.append(f"      {rel}")
    if missing:
        lines.append(f"  MISSING ({len(missing)}) - in the manifest, not on disk:")
        for rel in missing[:30]:
            lines.append(f"      {rel}")
    if extra:
        lines.append(f"  EXTRA ({len(extra)}) - present but not in the manifest:")
        for rel in extra[:30]:
            lines.append(f"      {rel}")
    lines.append("")
    lines.append("  A modified or extra file means the install no longer matches")
    lines.append("  the reviewed source. Reinstall from a trusted copy, or inspect")
    lines.append("  the listed files.")
    lines.append("=" * 70)
    return "\n".join(lines), False


def main(args):
    """cc integrity: generate|verify [--root DIR]"""
    import sys

    action = args[0] if args else "verify"
    rest = args[1:]

    root = os.getcwd()
    if "--root" in rest:
        root = rest[rest.index("--root") + 1]

    if action == "generate":
        # From a repo checkout: write MANIFEST.sha256 for the payload.
        out, count = write_manifest(root)
        print(f"Wrote manifest for {count} file(s): {out}")
        return 0

    if action == "verify":
        # An explicit --root is authoritative: verify exactly that tree against
        # its own manifest. Only without one do we fall back to the installed
        # location, then the current directory.
        if "--root" in rest:
            candidates = [os.path.join(root, MANIFEST_NAME)]
        else:
            candidates = [
                os.path.join(os.path.expanduser("~/.claude/cortex-core"), MANIFEST_NAME),
                os.path.join(root, MANIFEST_NAME),
            ]
        manifest_path = next((c for c in candidates if os.path.isfile(c)), None)
        if not manifest_path:
            print("No MANIFEST.sha256 found. Generate one with:", file=sys.stderr)
            print("  cc integrity generate   (from a repo checkout)", file=sys.stderr)
            return 1

        check_root = os.path.dirname(manifest_path)
        manifest = read_manifest(manifest_path)
        report, ok = render(check_root, manifest)
        print(report)
        return 0 if ok else 1

    print(f"cc integrity: unknown action '{action}'", file=sys.stderr)
    print("  usage: cc integrity generate|verify [--root DIR]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    # Runnable standalone: `python integrity.py verify --root DIR`. This matters
    # because verifying a compromised install by running THAT install's code is
    # circular - if a core module was deleted or altered, `python -m cortex` may
    # not even import. A trusted copy of this one file, which imports only hashlib
    # and os, can still check the install.
    import sys
    sys.exit(main(sys.argv[1:]))
