#!/usr/bin/env python3
"""
Claude Cortex: Universal Python Installer (Windows, Linux, macOS)
Multi-Account Manager, Capacity Auto-Failover, Cognitive Memory Palace,
Neuroscience Dream Simulation, Models & Reasoning Control, API Fallback Proxy
"""

import os
import sys
import shutil
import json
import time
import zipfile
import tarfile
import urllib.request
from pathlib import Path

# Exit code meaning "the safety guard stopped this run". Callers such as
# install.cmd must NOT treat it as a recoverable failure and retry another
# installer, or the guard is trivially bypassed.
GUARD_DECLINED_EXIT = 3


def register_desktop_mcp(cfg_path, command, script):
    """Add the Cortex MCP server to a Claude Desktop config without losing anything.

    The installer used to treat "could not parse" as "empty" and then write, which
    replaced a user's entire Desktop config - every other MCP server and setting -
    with just the Cortex entry. A config that exists but is not valid JSON is now
    left exactly as it is, and the user is told what to add by hand. Otherwise a
    ``.bak`` is kept and the write is atomic. Returns True if the file was written.
    """
    cfg = {}
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                raise ValueError("top level is not an object")
        except (OSError, ValueError):
            print(f"  ! Left {cfg_path} untouched: it is not valid JSON, so it was "
                  f"not rewritten.")
            print(f"    Add an mcpServers entry named 'claude-cortex' "
                  f"(command: {command}, args: [{script}]) by hand.")
            return False

    servers = cfg.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        print(f"  ! Left {cfg_path} untouched: 'mcpServers' is not an object.")
        return False
    servers["claude-cortex"] = {"command": command, "args": [script]}

    try:
        if cfg_path.exists():
            shutil.copy2(cfg_path, str(cfg_path) + ".bak")
        tmp = str(cfg_path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, cfg_path)
    except OSError as exc:
        print(f"  ! Could not update {cfg_path}: {exc}")
        return False
    return True


def print_header(title):
    print("=" * 70)
    print(f"          {title}")
    print("=" * 70)

def confirm_install(bin_dir, claude_dir, profiles_dir):
    """Sandbox guard.

    This installer replaces the `claude` command, writes lifecycle hooks, and
    installs rules that change model behavior. It refuses to run unless the
    operator has explicitly opted in, so it cannot be triggered by accident.

    Returns False when the caller should stop (dry run or declined).
    """
    argv = sys.argv[1:]
    assume_yes = any(a in ("--yes", "-y") for a in argv)
    dry_run = "--dry-run" in argv

    if dry_run:
        print("[DRY RUN] Would install Claude Cortex with:")
        print(f"  wrapper   -> {bin_dir}")
        print(f"  scripts   -> {claude_dir / 'scripts'}")
        print(f"  commands  -> {claude_dir / 'commands'}")
        print(f"  rules     -> {claude_dir / 'rules'}")
        print(f"  settings  -> {claude_dir / 'settings.json'} (hooks)")
        print(f"  profiles  -> {profiles_dir}")
        print("[DRY RUN] No changes made.")
        return False

    if os.environ.get("CORTEX_SANDBOX") == "1" or assume_yes:
        return True

    print("=" * 70)
    print("  Claude Cortex installer - CONFIRMATION REQUIRED")
    print("=" * 70)
    print("  This will modify your live Claude Code installation:")
    print(f"    * replace the claude command in {bin_dir}")
    print(f"    * write lifecycle hooks into {claude_dir / 'settings.json'}")
    print("    * install rules that change model behavior")
    print()
    print("  Set CORTEX_SANDBOX=1 to run in a container, or pass --dry-run first.")
    print("=" * 70)

    # isatty() is unreliable under some Windows shells, so treat a failed read as
    # "no operator present" rather than letting an EOFError escape.
    try:
        if not sys.stdin.isatty():
            raise EOFError
        answer = input("  Type INSTALL to continue: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("  Refusing to run non-interactively without --yes or CORTEX_SANDBOX=1.")
        sys.exit(GUARD_DECLINED_EXIT)

    if answer != "INSTALL":
        print("  Aborted. Nothing was changed.")
        return False
    return True


def main():
    is_windows = (sys.platform == "win32")
    is_mac = (sys.platform == "darwin")
    home = Path.home()
    script_dir = Path(__file__).resolve().parent
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    bin_dir = home / ".local" / "bin"
    claude_dir = home / ".claude"
    profiles_dir = home / ".claude-profiles"
    backup_dir = home / ".claude-backups"

    if not confirm_install(bin_dir, claude_dir, profiles_dir):
        return

    print_header(f"Installing Claude Cortex ({sys.platform})")
    print(f"Source Directory: {script_dir}")
    print(f"Target Directory: {claude_dir}")

    # 0. Ensure base directories exist
    bin_dir.mkdir(parents=True, exist_ok=True)
    claude_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 1. Detect existing official Claude installation
    print("\n[1/7] Detecting previous official Claude Code installations...")
    official_candidates = []
    if is_windows:
        local_app_data = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        app_data = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        official_candidates = [
            Path(local_app_data) / "Programs" / "claude" / "claude.exe",
            bin_dir / "claude.exe",
            bin_dir / "claude.real.exe",
            claude_dir / "bin" / "claude.exe",
            Path(app_data) / "npm" / "claude.cmd",
            Path(app_data) / "npm" / "claude",
        ]
    else:
        official_candidates = [
            bin_dir / "claude",
            bin_dir / "claude.real",
            Path("/usr/local/bin/claude"),
            home / ".local" / "share" / "claude" / "versions",
        ]

    detected_official = [p for p in official_candidates if p.exists()]
    which_claude = shutil.which("claude")
    if which_claude and Path(which_claude) not in detected_official:
        detected_official.append(Path(which_claude))

    if detected_official:
        print("  ✓ Detected official Claude Code installation:")
        for d in detected_official:
            print(f"    • {d}")
    else:
        print("  ℹ No existing official binary found in standard locations.")

    # 2. Comprehensive safe backup & data staging
    print("\n[2/7] Creating pre-installation backup and staging core user data...")
    staging_dir = backup_dir / f"staged_user_data_{timestamp}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    user_claude_json = home / ".claude.json"
    if user_claude_json.exists():
        shutil.copy2(user_claude_json, staging_dir / ".claude.json")
        print("  ✓ Staged authentication & account credentials (.claude.json)")

    projects_dir = claude_dir / "projects"
    if projects_dir.exists() and projects_dir.is_dir():
        shutil.copytree(projects_dir, staging_dir / "projects", dirs_exist_ok=True)
        print("  ✓ Staged user project memory & conversation histories")

    for item in ["file-history", "history.jsonl", "config.json"]:
        p = claude_dir / item
        if p.exists():
            if p.is_dir():
                shutil.copytree(p, staging_dir / item, dirs_exist_ok=True)
            else:
                shutil.copy2(p, staging_dir / item)

    # Archive to zip/tar
    if is_windows:
        backup_archive = backup_dir / f"claude-backup-{timestamp}.zip"
        try:
            with zipfile.ZipFile(backup_archive, "w", zipfile.ZIP_DEFLATED) as zf:
                if user_claude_json.exists():
                    zf.write(user_claude_json, ".claude.json")
                for root, _, files in os.walk(claude_dir):
                    for file in files:
                        fp = Path(root) / file
                        rel = fp.relative_to(home)
                        zf.write(fp, str(rel))
            size_mb = backup_archive.stat().st_size / (1024 * 1024)
            shutil.copy2(backup_archive, backup_dir / "latest.zip")
            print(f"  ✓ Safe pre-installation archive created: {backup_archive.name} ({size_mb:.2f} MB)")
        except Exception as e:
            print(f"  ⚠ Backup archive note: {e}")
    else:
        backup_archive = backup_dir / f"claude-backup-{timestamp}.tar.gz"
        try:
            with tarfile.open(backup_archive, "w:gz") as tf:
                if user_claude_json.exists():
                    tf.add(user_claude_json, arcname=".claude.json")
                if claude_dir.exists():
                    tf.add(claude_dir, arcname=".claude")
            size_mb = backup_archive.stat().st_size / (1024 * 1024)
            print(f"  ✓ Safe pre-installation archive created: {backup_archive.name} ({size_mb:.2f} MB)")
        except Exception as e:
            print(f"  ⚠ Backup archive note: {e}")

    # 3. Preserve underlying official binary
    print("\n[3/7] Preserving underlying official Claude binary...")
    real_binary_name = "claude.real.exe" if is_windows else "claude.real"
    real_binary_target = bin_dir / real_binary_name

    preserved = False
    for cand in detected_official:
        if cand.is_file() and "claude.real" not in cand.name:
            try:
                shutil.copy2(cand, real_binary_target)
                if not is_windows:
                    real_binary_target.chmod(0o755)
                print(f"  ✓ Preserved official binary to: {real_binary_target}")
                preserved = True
                break
            except Exception:
                pass

    if not preserved and not real_binary_target.exists():
        print("  Downloading official Claude binary from Anthropic CDN...")
        try:
            if is_windows:
                url = "https://downloads.claude.ai/claude-code-releases/latest/win32-x64/claude.exe"
            elif is_mac:
                url = "https://downloads.claude.ai/claude-code-releases/latest/darwin-x64/claude"
            else:
                url = "https://downloads.claude.ai/claude-code-releases/latest/linux-x64/claude"
            urllib.request.urlretrieve(url, real_binary_target)
            if not is_windows:
                real_binary_target.chmod(0o755)
            print(f"  ✓ Downloaded latest official binary to: {real_binary_target}")
        except Exception as e:
            print(f"  ⚠ Note on binary download: {e}")

    # 4. Clean removal of conflicting official installation artifacts
    print("\n[4/7] Cleaning previous installation residue...")
    downloads_dir = claude_dir / "downloads"
    if downloads_dir.exists():
        try:
            shutil.rmtree(downloads_dir)
            print(f"  ✓ Cleaned official installer download cache ({downloads_dir})")
        except Exception:
            pass

    if is_windows:
        local_app_claude = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))) / "Programs" / "claude" / "claude.exe"
        if local_app_claude.exists() and local_app_claude != real_binary_target:
            try:
                bak = local_app_claude.with_suffix(".exe.bak")
                local_app_claude.rename(bak)
                print(f"  ✓ Relocated conflicting official binary to {bak}")
            except Exception:
                pass

    # 5. Install Claude Cortex components
    print("\n[5/7] Installing Claude Cortex wrappers, rules & cognitive engines...")

    # The Python core. All real logic lives here; the shell wrappers are thin
    # shims, so without this every command fails with "Cortex core not found".
    src_core = script_dir / "cortex"
    if src_core.is_dir():
        core_dir = claude_dir / "cortex-core"
        core_target = core_dir / "cortex"
        core_dir.mkdir(parents=True, exist_ok=True)
        if core_target.exists():
            shutil.rmtree(core_target, ignore_errors=True)
        shutil.copytree(src_core, core_target)
        print(f"  ✓ Installed Cortex core to {core_target}")
    else:
        print("  ! cortex/ package not found in the source tree; install is incomplete")

    # The `cc` shortcut. Every document refers to `cc`, so an install without it
    # leaves the documented command simply not existing.
    def install_cc_alias():
        if is_windows:
            # Windows has no reliable unprivileged symlink, so write real shims.
            (bin_dir / "cc.cmd").write_text(
                "@echo off\r\n"
                "REM Claude Cortex - cc shortcut\r\n"
                'powershell.exe -NoProfile -ExecutionPolicy Bypass '
                '-File "%~dp0claude.ps1" %*\r\n',
                encoding="ascii")
            (bin_dir / "cc.ps1").write_text(
                "# Claude Cortex - cc shortcut\n"
                '& "$PSScriptRoot\\claude.ps1" @args\n'
                "exit $LASTEXITCODE\n",
                encoding="utf-8")
        else:
            link = bin_dir / "cc"
            target = bin_dir / "claude"
            try:
                if link.exists() or link.is_symlink():
                    link.unlink()
                link.symlink_to(target)
            except OSError:
                shutil.copy2(target, link)
                link.chmod(0o755)
        print(f"  ✓ Created cc shortcut in {bin_dir}")

    # Binaries
    src_bin = script_dir / "bin"
    if src_bin.exists():
        for b in src_bin.iterdir():
            dest = bin_dir / b.name
            shutil.copy2(b, dest)
            if not is_windows:
                dest.chmod(0o755)
        print(f"  ✓ Installed master execution wrappers to {bin_dir}")
        install_cc_alias()

    # Config, Rules, Commands, Scripts, Skills
    for folder in ["rules", "commands", "scripts", "skills"]:
        src_f = script_dir / folder if (script_dir / folder).exists() else script_dir / "config" / folder
        if not src_f.exists() and (script_dir / folder).exists():
            src_f = script_dir / folder
        dest_f = claude_dir / folder
        dest_f.mkdir(parents=True, exist_ok=True)
        if src_f.exists():
            shutil.copytree(src_f, dest_f, dirs_exist_ok=True)

    claude_md = script_dir / "config" / "CLAUDE.md"
    if claude_md.exists():
        shutil.copy2(claude_md, claude_dir / "CLAUDE.md")

    # Merge settings.json
    src_settings = script_dir / "config" / "settings.json"
    dest_settings = claude_dir / "settings.json"
    if src_settings.exists():
        if dest_settings.exists():
            try:
                with open(dest_settings, "r", encoding="utf-8") as f:
                    orig_cfg = json.load(f)
                with open(src_settings, "r", encoding="utf-8") as f:
                    new_cfg = json.load(f)
                orig_cfg.update(new_cfg)
                with open(dest_settings, "w", encoding="utf-8") as f:
                    json.dump(orig_cfg, f, indent=2)
            except Exception:
                shutil.copy2(src_settings, dest_settings)
        else:
            shutil.copy2(src_settings, dest_settings)

    print("  ✓ Installed Core Cognition rules, Memory Palace, Dream Simulator & Skills")

    # 6. Restore core user data & re-link profiles
    print("\n[6/7] Restoring user credentials, project context & re-linking profiles...")
    staged_claude_json = staging_dir / ".claude.json"
    if staged_claude_json.exists():
        shutil.copy2(staged_claude_json, user_claude_json)
        print("  ✓ Restored user authentication credentials (.claude.json) - No login required!")

    staged_projects = staging_dir / "projects"
    if staged_projects.exists():
        shutil.copytree(staged_projects, claude_dir / "projects", dirs_exist_ok=True)
        print("  ✓ Restored user conversation history and project data")

    for item in ["file-history", "history.jsonl", "config.json"]:
        sp = staging_dir / item
        if sp.exists():
            dp = claude_dir / item
            if sp.is_dir():
                shutil.copytree(sp, dp, dirs_exist_ok=True)
            else:
                shutil.copy2(sp, dp)

    # Setup profile
    primary_prof = "main"
    pdir = profiles_dir / primary_prof
    pdir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "current_profile").write_text(primary_prof, encoding="utf-8")
    (pdir / ".profile_mode").write_text("synced", encoding="utf-8")

    if user_claude_json.exists():
        shutil.copy2(user_claude_json, pdir / ".claude.json")

    shared_items = [
        "projects", "file-history", "history.jsonl", "commands",
        "skills", "rules", "plugins", "settings.json", "mcp-configs",
        "session-env", "shell-snapshots", "ide", "palace"
    ]
    for s_item in shared_items:
        src_item = claude_dir / s_item
        dst_item = pdir / s_item
        if src_item.exists() and not dst_item.exists():
            try:
                if is_windows:
                    if src_item.is_dir():
                        import subprocess
                        subprocess.run(["cmd", "/c", "mklink", "/J", str(dst_item), str(src_item)], capture_output=True)
                    else:
                        shutil.copy2(src_item, dst_item)
                else:
                    os.symlink(src_item, dst_item)
            except Exception:
                if src_item.is_dir():
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_item, dst_item)
    print(f"  ✓ Initialized primary profile [{primary_prof}] with full data synchronization")

    # 7. Configure PATH, Multi-IDE Extension Wizard & Desktop Native MCP Integration
    print("\n[7/7] Configuring User PATH, Multi-IDE Extensions & Claude Desktop MCP...")
    if is_windows:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                current_path, _ = winreg.QueryValueEx(key, "Path")
                bin_str = str(bin_dir)
                if bin_str not in current_path:
                    new_path = f"{bin_str};{current_path}"
                    winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
                    print(f"  ✓ Added {bin_dir} to User PATH in Windows Registry")
        except Exception as e:
            print(f"  ⚠ Registry PATH update note: {e}")

        # Multi-IDE Detection & Configuration on Windows
        app_data = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        wrapper_cmd = str(bin_dir / "claude.cmd")

        ide_targets_win = [
            ("VS Code", Path(app_data) / "Code" / "User" / "settings.json", "code.cmd"),
            ("Google Antigravity", Path(app_data) / "Antigravity" / "User" / "settings.json", "antigravity.cmd"),
            ("Cursor", Path(app_data) / "Cursor" / "User" / "settings.json", "cursor.cmd"),
            ("VSCodium", Path(app_data) / "VSCodium" / "User" / "settings.json", "codium.cmd"),
            ("Windsurf", Path(app_data) / "Windsurf" / "User" / "settings.json", "windsurf.cmd"),
        ]

        for ide_name, s_file, ide_cli in ide_targets_win:
            if s_file.parent.exists() or s_file.exists():
                s_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    data = {}
                    if s_file.exists():
                        with open(s_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    data["claudeCode.claudeProcessWrapper"] = wrapper_cmd
                    with open(s_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=4)
                    print(f"  ✓ Configured Claude Code process wrapper for {ide_name}")
                except Exception:
                    pass

        # Claude Desktop MCP & Profiles on Windows
        desktop_dirs_win = [
            Path(app_data) / "Claude",
            Path(app_data) / "Claude-profile-1",
            Path(app_data) / "Claude-profile-2",
        ]
        cortex_mcp_script = str(claude_dir / "scripts" / "cortex-mcp.py")
        for d in desktop_dirs_win:
            d.mkdir(parents=True, exist_ok=True)
            cfg_p = d / "claude_desktop_config.json"
            if register_desktop_mcp(cfg_p, "python", cortex_mcp_script):
                print(f"  ✓ Registered Cortex MCP tools in: {cfg_p.name} ({d.name})")

    else:
        # Bash / Zsh PATH
        for rc in [home / ".bashrc", home / ".zshrc"]:
            if rc.exists():
                try:
                    content = rc.read_text(encoding="utf-8")
                    if str(bin_dir) not in content:
                        with open(rc, "a", encoding="utf-8") as f:
                            f.write(f'\nexport PATH="{bin_dir}:$PATH"\n')
                        print(f"  ✓ Added {bin_dir} to {rc.name}")
                except Exception:
                    pass

        # Multi-IDE Detection on Linux / macOS
        wrapper_sh = str(bin_dir / "claude")
        ide_targets_posix = [
            ("VS Code", home / ".config" / "Code" / "User" / "settings.json", "code"),
            ("VS Code (macOS)", home / "Library" / "Application Support" / "Code" / "User" / "settings.json", "code"),
            ("Google Antigravity", home / ".config" / "Antigravity" / "User" / "settings.json", "antigravity"),
            ("Google Antigravity (macOS)", home / "Library" / "Application Support" / "Antigravity" / "User" / "settings.json", "antigravity"),
            ("Cursor", home / ".config" / "Cursor" / "User" / "settings.json", "cursor"),
            ("Cursor (macOS)", home / "Library" / "Application Support" / "Cursor" / "User" / "settings.json", "cursor"),
            ("VSCodium", home / ".config" / "VSCodium" / "User" / "settings.json", "codium"),
            ("VSCodium (macOS)", home / "Library" / "Application Support" / "VSCodium" / "User" / "settings.json", "codium"),
            ("Windsurf", home / ".config" / "Windsurf" / "User" / "settings.json", "windsurf"),
            ("Windsurf (macOS)", home / "Library" / "Application Support" / "Windsurf" / "User" / "settings.json", "windsurf"),
        ]

        for ide_name, s_file, ide_cli in ide_targets_posix:
            if s_file.parent.exists() or s_file.exists():
                s_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    data = {}
                    if s_file.exists():
                        with open(s_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    data["claudeCode.claudeProcessWrapper"] = wrapper_sh
                    with open(s_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=4)
                    print(f"  ✓ Configured Claude Code process wrapper for {ide_name}")
                except Exception:
                    pass

        # Claude Desktop MCP Integration on Linux / macOS
        desktop_dirs_posix = [
            home / ".config" / "Claude",
            home / ".config" / "claude-profile-1",
            home / ".config" / "claude-profile-2",
            home / "Library" / "Application Support" / "Claude",
        ]
        cortex_mcp_script = str(claude_dir / "scripts" / "cortex-mcp.py")
        for d in desktop_dirs_posix:
            if d.exists() or (d.parent.exists() and "claude-profile" in d.name):
                d.mkdir(parents=True, exist_ok=True)
                cfg_p = d / "claude_desktop_config.json"
                if register_desktop_mcp(cfg_p, "python3", cortex_mcp_script):
                    print(f"  ✓ Registered Cortex MCP tools in: {cfg_p}")

    print_header("Installation Complete! Claude Cortex is Ready Everywhere.")
    print("\nAccessible from:")
    print("  • Terminal / CMD / PowerShell: claude, claude -ws, claude -vl, claude continue")
    print("  • VS Code Extension:           Native extension auto-routed through wrapper")
    print("  • Claude Desktop App:          claude desktop ws, claude desktop vl")
    print("\nKey Commands:")
    print("  claude continue        Auto-check capacity across all accounts and resume session")
    print("  claude switch [prof]   Switch active default profile")
    print("  claude status / quota  Display real-time capacity and rate-limit countdowns")
    print("  claude -t / --turbo    High-speed output with minimal token consumption")
    print("  claude palace          Inspect Cognitive Memory Palace")
    print("  claude dream           Simulate counterfactual edge cases & stress-test code")
    print("  claude docs            View comprehensive Cortex documentation")
    print("=" * 70)

if __name__ == "__main__":
    main()
