#!/usr/bin/env python3
"""
Claude Cortex - Multi-Flavor Release Packaging Pipeline
Generates categorized, production-ready release distributions:
1. Full Edition (All features: Terminal, Failover, Memory Palace, Dream Simulator, Desktop MCP, Multi-IDE, All Installers)
2. Terminal-Only Edition (Lightweight CLI for servers & pure terminal environments)
3. Desktop & IDE Edition (Desktop MCP server and IDE extension configurations)
4. Windows Standalone Bundle (EXE, CMD, PS1)
5. Unix Bundle (macOS & Linux tar.gz)
Generates SHA256 checksums and comprehensive release manifests.
"""

import os
import sys
import shutil
import zipfile
import tarfile
import hashlib
from pathlib import Path

VERSION = "2.0.0"
REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "releases" / f"v{VERSION}"

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def make_zip(source_dir, output_zip, prefix="claude-cortex"):
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                p = Path(root) / file
                rel = p.relative_to(source_dir)
                zf.write(p, f"{prefix}/{rel}")

def make_tar(source_dir, output_tar, prefix="claude-cortex"):
    with tarfile.open(output_tar, "w:gz") as tf:
        tf.add(source_dir, arcname=prefix)

def build_flavor(name, include_rules, stage_parent):
    stage_dir = stage_parent / name
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    for item in include_rules:
        src = REPO_ROOT / item
        dst = stage_dir / item
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

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

    try:
        # Common items
        base_items = [
            "README.md", "LICENSE", "config", "skills", "completion"
        ]

        # Flavor 1: Full Suite
        print("\n[1/5] Building Full Suite (All components + All installers)...")
        full_items = base_items + [
            "bin", "scripts",
            "install.sh", "install.ps1", "install.cmd", "install.py", "install.exe"
        ]
        s_full = build_flavor("full", full_items, temp_stage)
        zip_full = DIST_DIR / f"claude-cortex-v{VERSION}-full.zip"
        tar_full = DIST_DIR / f"claude-cortex-v{VERSION}-full.tar.gz"
        make_zip(s_full, zip_full, prefix=f"claude-cortex-v{VERSION}")
        make_tar(s_full, tar_full, prefix=f"claude-cortex-v{VERSION}")
        print(f"  ✓ Created: {zip_full.name} ({zip_full.stat().st_size / 1024:.1f} KB)")
        print(f"  ✓ Created: {tar_full.name} ({tar_full.stat().st_size / 1024:.1f} KB)")

        # Flavor 2: Terminal-Only Edition (No Desktop MCP / GUI launchers)
        print("\n[2/5] Building Terminal-Only Edition (Pure CLI)...")
        term_items = [
            "README.md", "bin", "config", "skills", "completion",
            "scripts/claude-capacity-check.py",
            "scripts/claude-models.py",
            "scripts/claude-provider.py",
            "scripts/claude-palace.py",
            "scripts/claude-dream.py",
            "scripts/claude-research.py",
            "scripts/claude-cognition.py",
            "scripts/gemini-proxy.py",
            "scripts/token-opt-clean.sh",
            "scripts/token-opt-clean.ps1",
            "install.sh", "install.py", "install.ps1"
        ]
        s_term = build_flavor("terminal", term_items, temp_stage)
        zip_term = DIST_DIR / f"claude-cortex-v{VERSION}-terminal-only.zip"
        tar_term = DIST_DIR / f"claude-cortex-v{VERSION}-terminal-only.tar.gz"
        make_zip(s_term, zip_term, prefix=f"claude-cortex-terminal-v{VERSION}")
        make_tar(s_term, tar_term, prefix=f"claude-cortex-terminal-v{VERSION}")
        print(f"  ✓ Created: {zip_term.name} ({zip_term.stat().st_size / 1024:.1f} KB)")
        print(f"  ✓ Created: {tar_term.name} ({tar_term.stat().st_size / 1024:.1f} KB)")

        # Flavor 3: Desktop MCP Edition (Claude Desktop App & IDE extensions)
        print("\n[3/5] Building Desktop MCP Edition...")
        mcp_items = [
            "README.md",
            "scripts/cortex-mcp.py",
            "scripts/claude-models.py",
            "scripts/claude-provider.py",
            "scripts/claude-palace.py",
            "scripts/claude-dream.py",
            "scripts/claude-capacity-check.py",
            "install.py", "install.sh", "install.ps1"
        ]
        s_mcp = build_flavor("desktop-mcp", mcp_items, temp_stage)
        zip_mcp = DIST_DIR / f"claude-cortex-v{VERSION}-desktop-mcp.zip"
        tar_mcp = DIST_DIR / f"claude-cortex-v{VERSION}-desktop-mcp.tar.gz"
        make_zip(s_mcp, zip_mcp, prefix=f"claude-cortex-mcp-v{VERSION}")
        make_tar(s_mcp, tar_mcp, prefix=f"claude-cortex-mcp-v{VERSION}")
        print(f"  ✓ Created: {zip_mcp.name} ({zip_mcp.stat().st_size / 1024:.1f} KB)")
        print(f"  ✓ Created: {tar_mcp.name} ({tar_mcp.stat().st_size / 1024:.1f} KB)")

        # Flavor 4: Windows 1-Click Bundle (Optimized for Windows Explorer & CMD/PowerShell)
        print("\n[4/5] Building Windows 1-Click Package...")
        win_items = full_items
        s_win = build_flavor("windows", win_items, temp_stage)
        zip_win = DIST_DIR / f"claude-cortex-v{VERSION}-windows-x64.zip"
        make_zip(s_win, zip_win, prefix=f"claude-cortex-v{VERSION}")
        print(f"  ✓ Created: {zip_win.name} ({zip_win.stat().st_size / 1024:.1f} KB)")

        # Flavor 5: Unix / macOS Package (tar.gz)
        print("\n[5/5] Building Unix / macOS Package...")
        unix_items = [i for i in full_items if not i.endswith((".exe", ".cmd"))]
        s_unix = build_flavor("unix", unix_items, temp_stage)
        tar_unix = DIST_DIR / f"claude-cortex-v{VERSION}-darwin-linux.tar.gz"
        make_tar(s_unix, tar_unix, prefix=f"claude-cortex-v{VERSION}")
        print(f"  ✓ Created: {tar_unix.name} ({tar_unix.stat().st_size / 1024:.1f} KB)")

        # Generate Checksums (SHA-256)
        print("\nGenerating SHA-256 Checksums...")
        checksums_file = DIST_DIR / "SHA256SUMS.txt"
        checksum_lines = []
        for f in sorted(DIST_DIR.iterdir()):
            if f.is_file() and f.name != "SHA256SUMS.txt" and not f.name.endswith(".md"):
                cs = sha256_file(f)
                checksum_lines.append(f"{cs}  {f.name}")

        checksums_file.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
        print(f"  ✓ Saved checksums to {checksums_file.name}")

        # Generate Release Manifest
        manifest_file = DIST_DIR / f"RELEASE_v{VERSION}.md"
        manifest_md = f"""# Claude Cortex v{VERSION} Release Manifest 🚀

**Release Date:** 2026-09-15  
**Upstream Parity:** Claude Code v2.1.272+  
**Target Repository:** github.com/nikhlgoel/claude-cortex.git

## Categorized Release Artifacts

| Distribution Package | Format | Size | Description |
| :--- | :--- | :--- | :--- |
| `claude-cortex-v{VERSION}-full.zip` | ZIP | {zip_full.stat().st_size / 1024:.1f} KB | Complete suite: Terminal + Multi-Account Failover + Memory Palace + Dream Simulator + Desktop MCP + Multi-IDE Wizard + All Installers. |
| `claude-cortex-v{VERSION}-full.tar.gz` | TAR.GZ | {tar_full.stat().st_size / 1024:.1f} KB | Complete suite for Unix / macOS with POSIX executable permissions. |
| `claude-cortex-v{VERSION}-terminal-only.zip` | ZIP | {zip_term.stat().st_size / 1024:.1f} KB | Lightweight terminal edition: CLI wrapper, autonomous failover, models catalog, memory palace. Zero GUI/Desktop overhead. |
| `claude-cortex-v{VERSION}-terminal-only.tar.gz` | TAR.GZ | {tar_term.stat().st_size / 1024:.1f} KB | Pure terminal edition for Linux/macOS SSH servers & workstations. |
| `claude-cortex-v{VERSION}-desktop-mcp.zip` | ZIP | {zip_mcp.stat().st_size / 1024:.1f} KB | Desktop MCP Server edition: Direct integration with Claude Desktop App GUI and IDEs. |
| `claude-cortex-v{VERSION}-windows-x64.zip` | ZIP | {zip_win.stat().st_size / 1024:.1f} KB | Windows 1-Click edition with `install.exe`, `install.cmd`, `install.ps1`, and official binary auto-migration. |
| `claude-cortex-v{VERSION}-darwin-linux.tar.gz` | TAR.GZ | {tar_unix.stat().st_size / 1024:.1f} KB | macOS & Linux distribution with automated pre-install backups. |

## SHA-256 Checksums
```
{chr(10).join(checksum_lines)}
```

## Highlights & Upgrades in v{VERSION}
1. **Interactive Keyboard TUI Model Selector**:
   - Real-time arrow navigation (`↑`/`↓`), Free vs Paid toggle (`f`).
   - Detailed Evaluation Dossier modal popup (`Shift`, `Tab`, `i`) showing SWE coding ratings, MMLU reasoning benchmarks, token generation latency, context limits, and task matching.
2. **Deep Claude Desktop Native MCP Integration**:
   - Local JSON-RPC Model Context Protocol server (`cortex-mcp.py`).
   - Auto-registered across all profile configs in `claude_desktop_config.json` with 6 native GUI tools (`cortex_status`, `cortex_switch`, `cortex_model`, `cortex_provider`, `cortex_palace`, `cortex_dream`).
3. **Multi-IDE Extension Integration Wizard**:
   - Seamlessly configures **VS Code**, **Google Antigravity**, **Cursor**, **VSCodium**, and **Windsurf**.
   - Auto-injects `"claudeCode.claudeProcessWrapper"` into each IDE's `settings.json` without touching personal themes or custom keybindings.
4. **Autonomous Rate-Limit Failover (`claude continue`)**:
   - Zero-loss multi-account capacity scanning and automatic handoff.
5. **Cognitive Memory Palace v2.5 & Dream Simulation**:
   - Dual-speed recall with inverted tag indexing across 5 architectural rooms.
   - 4-chamber REM counterfactual stress-testing engine.
6. **Universal Windows Suite**:
   - Native `install.exe`, ExecutionPolicy auto-bypass `install.cmd`, official binary auto-migration, and login state restoration.
"""
        manifest_file.write_text(manifest_md, encoding="utf-8")
        print(f"  ✓ Saved release manifest to {manifest_file.name}")

    finally:
        if temp_stage.exists():
            shutil.rmtree(temp_stage)

    print("\n" + "=" * 70)
    print(f"✓ All release artifacts generated successfully at: {DIST_DIR}")
    print("=" * 70)

if __name__ == "__main__":
    main()
