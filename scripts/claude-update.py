#!/usr/bin/env python3
"""
Claude Cortex - Multi-Component Unified Update Manager
Monitors, checks, and updates:
  1. Claude Code CLI (official binary & npm release)
  2. VS Code / IDE Extensions (anthropic.claude-code)
  3. Claude Desktop application
  4. Connected tools & libraries (specify-cli / spec-kit, scrapling)
  5. Claude Cortex repository (auto-fetch & pull from origin/main)
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
from pathlib import Path

# Paths
HOME = os.path.expanduser("~")
BIN_DIR = os.path.join(HOME, ".local", "bin")
REAL_CLAUDE = os.path.join(BIN_DIR, "claude.real")
CORTEX_REPO_DIR = os.environ.get("CLAUDE_CORTEX_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if not os.path.isdir(os.path.join(CORTEX_REPO_DIR, ".git")):
    # Check common user workspaces
    for candidate in [os.path.expanduser("~/projects/claude-cortex"), os.path.expanduser("~/projects/temp/claude-cortex")]:
        if os.path.isdir(os.path.join(candidate, ".git")):
            CORTEX_REPO_DIR = candidate
            break

def run_cmd(args, timeout=20):
    """Runs a subprocess command and returns stripped stdout or empty string."""
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if res.returncode == 0:
            return res.stdout.strip()
        return ""
    except Exception:
        return ""

def get_claude_cli_status():
    """Checks local vs upstream Claude Code CLI version."""
    local_ver = "Unknown"
    if os.path.isfile(REAL_CLAUDE) and os.access(REAL_CLAUDE, os.X_OK):
        raw = run_cmd([REAL_CLAUDE, "--version"])
        if raw:
            local_ver = raw.split()[0]
    elif os.path.isfile(os.path.join(BIN_DIR, "claude")):
        raw = run_cmd([os.path.join(BIN_DIR, "claude"), "--version"])
        if raw:
            local_ver = raw.split()[0]

    remote_ver = run_cmd(["npm", "view", "@anthropic-ai/claude-code", "version"]) or "Unknown"
    has_update = (local_ver != "Unknown" and remote_ver != "Unknown" and local_ver != remote_ver)
    return {
        "name": "Claude Code CLI",
        "current": local_ver,
        "latest": remote_ver,
        "has_update": has_update,
        "type": "cli"
    }

def get_vscode_extension_status():
    """Checks VS Code anthropic.claude-code extension."""
    if not shutil.which("code"):
        return {"name": "VS Code Extension", "current": "N/A (code not installed)", "latest": "-", "has_update": False, "type": "ide"}

    ext_list = run_cmd(["code", "--list-extensions", "--show-versions"])
    local_ver = "Not Installed"
    for line in ext_list.splitlines():
        if "anthropic.claude-code@" in line:
            local_ver = line.split("@")[-1].strip()
            break

    cli_status = get_claude_cli_status()
    latest_ver = cli_status["latest"]
    has_update = (local_ver != "Not Installed" and latest_ver != "Unknown" and local_ver != latest_ver)
    return {
        "name": "VS Code Extension",
        "current": local_ver,
        "latest": latest_ver,
        "has_update": has_update,
        "type": "ide"
    }

def get_uv_tool_status(tool_name, pkg_name):
    """Checks versions of uv-installed tools (specify-cli, scrapling)."""
    if not shutil.which("uv"):
        return {"name": pkg_name, "current": "N/A (uv missing)", "latest": "-", "has_update": False, "type": "tool"}

    raw = run_cmd(["uv", "tool", "list"])
    local_ver = "Not Installed"
    for line in raw.splitlines():
        if line.startswith(f"{pkg_name} "):
            local_ver = line.split()[1].lstrip("v")
            break

    # Check PyPI latest
    remote_ver = run_cmd(["uv", "pip", "show", pkg_name])
    latest_ver = local_ver  # Default to current if remote check times out
    try:
        pypi_info = run_cmd(["curl", "-s", f"https://pypi.org/pypi/{pkg_name}/json"], timeout=5)
        if pypi_info:
            d = json.loads(pypi_info)
            latest_ver = d.get("info", {}).get("version", local_ver)
    except Exception:
        pass

    # Semver numeric comparison
    def is_newer(remote, local):
        if not remote or not local or remote == local or remote in ("Unknown", "-") or local in ("Unknown", "Not Installed"):
            return False
        try:
            import re
            p_rem = [int(x) for x in re.sub(r"[^\d.]", "", remote.split(".dev")[0]).split(".") if x.isdigit()]
            p_loc = [int(x) for x in re.sub(r"[^\d.]", "", local.split(".dev")[0]).split(".") if x.isdigit()]
            return p_rem > p_loc
        except Exception:
            return remote != local

    has_update = is_newer(latest_ver, local_ver)
    return {
        "name": pkg_name,
        "current": local_ver,
        "latest": latest_ver,
        "has_update": has_update,
        "type": "tool"
    }

def get_cortex_repo_status():
    """Checks Claude Cortex local git repository against remote origin/main."""
    if not os.path.isdir(os.path.join(CORTEX_REPO_DIR, ".git")):
        return {"name": "Claude Cortex Suite", "current": "v1.1.0", "latest": "v1.1.0", "has_update": False, "type": "repo"}

    # Fetch latest metadata silently
    subprocess.run(["git", "fetch", "origin", "main"], cwd=CORTEX_REPO_DIR, capture_output=True, timeout=10)
    local_hash = run_cmd(["git", "rev-parse", "--short", "HEAD"], timeout=5)
    remote_hash = run_cmd(["git", "rev-parse", "--short", "origin/main"], timeout=5)
    behind_count = run_cmd(["git", "rev-list", "HEAD..origin/main", "--count"], timeout=5)
    try:
        behind = int(behind_count)
    except Exception:
        behind = 0

    has_update = (behind > 0)
    cur_label = f"{local_hash}"
    latest_label = f"{remote_hash} (+{behind} commits)" if has_update else f"{local_hash} (Up to date)"
    return {
        "name": "Claude Cortex Repository",
        "current": cur_label,
        "latest": latest_label,
        "has_update": has_update,
        "type": "repo",
        "behind": behind
    }

def get_all_statuses():
    """Aggregates status across all components."""
    statuses = []
    statuses.append(get_claude_cli_status())
    statuses.append(get_vscode_extension_status())
    statuses.append(get_uv_tool_status("specify", "specify-cli"))
    statuses.append(get_uv_tool_status("scrapling", "scrapling"))
    statuses.append(get_cortex_repo_status())
    return statuses

def print_status_table(statuses):
    """Renders a clean CLI table of all component statuses."""
    print("==========================================================================================")
    print("                   Claude Cortex - Unified Ecosystem Update Status                        ")
    print("==========================================================================================")
    print(f"  {'COMPONENT':<28} {'CURRENT':<18} {'LATEST':<26} {'STATUS'}")
    print(f"  {'-'*28} {'-'*18} {'-'*26} {'-'*16}")

    any_update = False
    for item in statuses:
        has_up = item["has_update"]
        if has_up: any_update = True
        status_tag = "\033[1;33m⚡ UPDATE READY\033[0m" if has_up else "\033[1;32m✓ UP TO DATE\033[0m"
        print(f"  {item['name']:<28} {item['current']:<18} {item['latest']:<26} {status_tag}")

    print("==========================================================================================")
    if any_update:
        print("  To apply all pending updates, run:")
        print("    cc update apply   (or claude update apply)")
    else:
        print("  All components are running the latest official releases.")
    print("==========================================================================================")

def apply_updates(statuses):
    """Applies available updates across components safely."""
    print("Starting automated updates across Claude Cortex ecosystem...\n")

    # 1. Update Claude Code CLI
    cli_item = next((s for s in statuses if s["type"] == "cli"), None)
    if cli_item and cli_item["has_update"]:
        print(f"[*] Updating Claude Code CLI from {cli_item['current']} -> {cli_item['latest']}...")
        run_res = subprocess.run("curl -fsSL https://claude.ai/install.sh | bash", shell=True, capture_output=True, text=True)
        if run_res.returncode == 0:
            print("  ✓ Claude Code CLI updated successfully.")
            # Re-link claude.real to the latest binary in ~/.local/share/claude/versions/
            latest_bin = run_cmd(["bash", "-c", "ls -v ~/.local/share/claude/versions/ 2>/dev/null | tail -n 1"])
            if latest_bin:
                src = os.path.expanduser(f"~/.local/share/claude/versions/{latest_bin}")
                if os.path.isfile(src):
                    os.unlink(REAL_CLAUDE) if os.path.exists(REAL_CLAUDE) else None
                    os.symlink(src, REAL_CLAUDE)
                    print(f"  ✓ Re-linked official binary: {latest_bin}")
        else:
            print(f"  ⚠ Claude Code CLI update warning: {run_res.stderr.strip()[:150]}")

    # 2. Update VS Code Extension
    ide_item = next((s for s in statuses if s["name"] == "VS Code Extension"), None)
    if ide_item and ide_item["has_update"]:
        print("[*] Updating VS Code Extension (anthropic.claude-code)...")
        res = subprocess.run(["code", "--install-extension", "anthropic.claude-code", "--force"], capture_output=True, text=True)
        if res.returncode == 0:
            print("  ✓ VS Code extension updated.")
        else:
            print(f"  ⚠ Extension update warning: {res.stderr.strip()[:100]}")

    # 3. Update UV tools (specify-cli & scrapling)
    for tool_name, pkg in [("specify", "specify-cli"), ("scrapling", "scrapling")]:
        item = next((s for s in statuses if s["name"] == pkg), None)
        if item and item["has_update"]:
            print(f"[*] Upgrading {pkg} via uv tool upgrade...")
            res = subprocess.run(["uv", "tool", "upgrade", pkg], capture_output=True, text=True)
            if res.returncode == 0:
                print(f"  ✓ {pkg} upgraded successfully.")
            else:
                print(f"  ⚠ {pkg} upgrade warning: {res.stderr.strip()[:100]}")

    # 4. Update Claude Cortex repository
    repo_item = next((s for s in statuses if s["type"] == "repo"), None)
    if repo_item and repo_item["has_update"]:
        print(f"[*] Pulling latest updates in Claude Cortex repository ({repo_item['behind']} new commits)...")
        pull_res = subprocess.run(["git", "pull", "origin", "main"], cwd=CORTEX_REPO_DIR, capture_output=True, text=True)
        if pull_res.returncode == 0:
            print("  ✓ Pulled latest repository changes.")
            # Run install.sh to refresh any updated rules, commands, or hooks
            install_sh = os.path.join(CORTEX_REPO_DIR, "install.sh")
            if os.path.isfile(install_sh):
                subprocess.run(["bash", install_sh], cwd=CORTEX_REPO_DIR, capture_output=True)
                print("  ✓ Synchronized system hooks and scripts via installer.")
        else:
            print(f"  ⚠ Git pull warning: {pull_res.stderr.strip()[:100]}")

    print("\n✓ Update execution complete! Verifying updated environment:")
    print_status_table(get_all_statuses())

def main():
    parser = argparse.ArgumentParser(description="Claude Cortex Multi-Component Update Manager")
    parser.add_argument("action", nargs="?", default="check", choices=["check", "status", "apply", "upgrade", "sync"])
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    args = parser.parse_args()

    statuses = get_all_statuses()

    if args.json:
        print(json.dumps(statuses, indent=2))
        return

    if args.action in ("check", "status"):
        print_status_table(statuses)
    elif args.action in ("apply", "upgrade", "sync"):
        apply_updates(statuses)

if __name__ == "__main__":
    main()
