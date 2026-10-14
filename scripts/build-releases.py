#!/usr/bin/env python3
"""
Claude Cortex - Multi-Flavor Release Packaging Pipeline

Builds the release archives and their SHA-256 checksums.

Rules this packager enforces, each learned from a broken release:
  * EVERY flavor contains the ``cortex/`` Python core. All shims exec it; an archive
    without it installs but fails every command with "Cortex core not found".
  * A listed item that does not exist FAILS the build. It used to be skipped
    silently, so a typo or a deleted script shipped as a release with a hole in it
    (``claude-dream.py`` and ``claude-cognition.py`` were listed for months and
    do not exist). Only the explicit OPTIONAL set may be absent, with a warning.
  * The version comes from the core itself, so the archive name, the installer and
    ``cc version`` cannot disagree.
"""

import hashlib
import os
import sys
import re
import shutil
import tarfile
import zipfile
from datetime import date
from pathlib import Path

# The progress lines use check marks; a Windows console on cp1252 cannot print them and the
# build used to crash half way through with a UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_PARENT = REPO_ROOT / "releases"


def _core_version():
    text = (REPO_ROOT / "cortex" / "__main__.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("build-releases: cannot find VERSION in cortex/__main__.py")
    return match.group(1)


VERSION = _core_version()
DIST_DIR = DIST_PARENT / f"v{VERSION}"

# What every working install needs. `cortex` is the one that was missing.
CORE = ("cortex", "scripts", "config", "bin", "skills", "completion", "tools", "docs",
        "native", "README.md", "uninstall.sh")
INSTALLERS = ("install.sh", "install.ps1", "install.cmd", "install.py", "install.exe")

#: Items that may be absent (with a warning) rather than failing the build.
OPTIONAL = {"LICENSE"}

#: flavor -> (items to include, paths to remove from the staged copy)
FLAVORS = {
    "full": (CORE + INSTALLERS + ("LICENSE",), ()),
    # No desktop MCP server: for SSH boxes and pure-terminal use.
    "terminal-only": (CORE + ("install.sh", "install.ps1", "install.py", "LICENSE"),
                      ("scripts/cortex-mcp.py",)),
    # The MCP server for Claude Desktop / IDEs. Same core, so the tools it calls exist.
    "desktop-mcp": (("cortex", "scripts", "tools", "config", "README.md",
                     "install.py", "install.sh", "install.ps1", "LICENSE"), ()),
    "windows-x64": (CORE + INSTALLERS + ("LICENSE",), ()),
    "unix": (CORE + ("install.sh", "install.py", "LICENSE"), ("bin/claude.cmd", "bin/claude.ps1")),
}

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.bak", ".git")

#: Removed from every staged flavor: internal planning notes are not release content.
GLOBAL_EXCLUDES = ("docs/management",)


def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def make_zip(source_dir, output_zip, prefix="claude-cortex"):
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(source_dir):
            for file in files:
                p = Path(root) / file
                rel = p.relative_to(source_dir)
                zf.write(p, f"{prefix}/{rel.as_posix()}")


def make_tar(source_dir, output_tar, prefix="claude-cortex"):
    with tarfile.open(output_tar, "w:gz") as tf:
        tf.add(source_dir, arcname=prefix)


def missing_items(items):
    """Items that are neither present nor allowed to be absent."""
    return [i for i in items if not (REPO_ROOT / i).exists() and i not in OPTIONAL]


def build_flavor(name, items, excludes, stage_parent):
    absent = missing_items(items)
    if absent:
        raise SystemExit(f"build-releases: flavor '{name}' lists items that do not exist: "
                         f"{', '.join(absent)}\nFix the list; a silent skip ships a hole.")
    for item in items:
        if item in OPTIONAL and not (REPO_ROOT / item).exists():
            print(f"  ! {item} is not in the repository; '{name}' ships without it.")

    stage_dir = stage_parent / name
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    for item in items:
        src = REPO_ROOT / item
        if not src.exists():
            continue
        dst = stage_dir / item
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=IGNORE)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    for rel in tuple(excludes) + GLOBAL_EXCLUDES:
        target = stage_dir / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    if "cortex" in items and not (stage_dir / "cortex" / "__main__.py").is_file():
        raise SystemExit(f"build-releases: flavor '{name}' was staged without the cortex core")
    return stage_dir


def main():
    print("=" * 70)
    print(f"      Building Claude Cortex v{VERSION} Release Distributions")
    print("=" * 70)

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    temp_stage = REPO_ROOT / ".release_staging"
    if temp_stage.exists():
        shutil.rmtree(temp_stage)
    temp_stage.mkdir(parents=True, exist_ok=True)

    artifacts = []     # (display name, filename, size_kb, note)
    try:
        notes = {
            "full": "Everything: core, hooks, MCP server, tools, all installers.",
            "terminal-only": "Core + hooks for servers and pure terminals; no desktop MCP server.",
            "desktop-mcp": "Core + the MCP server, for Claude Desktop and IDE use.",
            "windows-x64": "Windows bundle with install.exe / install.cmd / install.ps1.",
            "unix": "macOS and Linux bundle (no Windows shims).",
        }
        for index, (name, (items, excludes)) in enumerate(FLAVORS.items(), 1):
            print(f"\n[{index}/{len(FLAVORS)}] Building {name}...")
            stage = build_flavor(name, items, excludes, temp_stage)
            prefix = f"claude-cortex-v{VERSION}"
            if name == "unix":
                outputs = [DIST_DIR / f"claude-cortex-v{VERSION}-darwin-linux.tar.gz"]
                make_tar(stage, outputs[0], prefix=prefix)
            elif name == "windows-x64":
                outputs = [DIST_DIR / f"claude-cortex-v{VERSION}-windows-x64.zip"]
                make_zip(stage, outputs[0], prefix=prefix)
            else:
                outputs = [DIST_DIR / f"claude-cortex-v{VERSION}-{name}.zip",
                           DIST_DIR / f"claude-cortex-v{VERSION}-{name}.tar.gz"]
                make_zip(stage, outputs[0], prefix=prefix)
                make_tar(stage, outputs[1], prefix=prefix)
            for out in outputs:
                size_kb = out.stat().st_size / 1024
                artifacts.append((name, out.name, size_kb, notes[name]))
                print(f"  ✓ Created: {out.name} ({size_kb:.1f} KB)")

        print("\nGenerating SHA-256 Checksums...")
        checksums_file = DIST_DIR / "SHA256SUMS.txt"
        checksum_lines = []
        for f in sorted(DIST_DIR.iterdir()):
            if f.is_file() and f.name != "SHA256SUMS.txt" and not f.name.endswith(".md"):
                checksum_lines.append(f"{sha256_file(f)}  {f.name}")
        checksums_file.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
        print(f"  ✓ Saved checksums to {checksums_file.name}")

        manifest_file = DIST_DIR / f"RELEASE_v{VERSION}.md"
        rows = "\n".join(f"| `{fn}` | {kb:.1f} KB | {note} |" for _n, fn, kb, note in artifacts)
        manifest_file.write_text(
            f"# Claude Cortex v{VERSION} Release Manifest\n\n"
            f"**Built:** {date.today().isoformat()}\n\n"
            f"## Artifacts\n\n| Package | Size | Contents |\n| :--- | :--- | :--- |\n{rows}\n\n"
            f"## SHA-256 Checksums\n```\n" + "\n".join(checksum_lines) + "\n```\n\n"
            "Every package contains the `cortex/` Python core. After extracting, run\n"
            "`./install.sh --dry-run` (or `install.ps1 -DryRun`) to see exactly what an install\n"
            "would change, and `cc integrity verify` afterwards. See README.md for what is\n"
            "real and what is a limitation.\n",
            encoding="utf-8")
        print(f"  ✓ Saved release manifest to {manifest_file.name}")
    finally:
        if temp_stage.exists():
            shutil.rmtree(temp_stage)

    print("\n" + "=" * 70)
    print(f"✓ All release artifacts generated successfully at: {DIST_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
