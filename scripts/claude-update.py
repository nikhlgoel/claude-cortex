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
import time
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

def extract_version_number(v_str):
    """Extracts clean numeric semver (e.g. '1.1.0' from 'v1.1.0-beta')."""
    if not v_str:
        return ""
    import re
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", v_str)
    if m:
        return m.group(1)
    return re.sub(r"[^\d.]", "", v_str).strip(".")

def compare_versions(v1, v2):
    """
    Compares two semver version strings.
    Returns:
       1 if v1 > v2
       0 if v1 == v2
      -1 if v1 < v2
    """
    s1 = extract_version_number(v1)
    s2 = extract_version_number(v2)
    p1 = [int(x) for x in s1.split(".") if x.isdigit()]
    p2 = [int(x) for x in s2.split(".") if x.isdigit()]
    maxlen = max(len(p1), len(p2))
    p1.extend([0] * (maxlen - len(p1)))
    p2.extend([0] * (maxlen - len(p2)))
    if p1 > p2:
        return 1
    elif p1 < p2:
        return -1
    return 0

UPDATE_CACHE_FILE = os.path.expanduser("~/.claude/update_cache.json")

def load_update_cache():
    if os.path.exists(UPDATE_CACHE_FILE):
        try:
            with open(UPDATE_CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_update_cache(cache):
    try:
        os.makedirs(os.path.dirname(UPDATE_CACHE_FILE), exist_ok=True)
        with open(UPDATE_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass

def get_cached_or_fetch(key, fetch_fn, ttl_seconds=600, force=False):
    if not force:
        cache = load_update_cache()
        entry = cache.get(key)
        now = time.time()
        if entry and isinstance(entry, dict):
            if now - entry.get("timestamp", 0) < ttl_seconds:
                return entry.get("data")
    data = fetch_fn()
    if data:
        cache = load_update_cache()
        cache[key] = {"timestamp": time.time(), "data": data}
        save_update_cache(cache)
    return data

def should_fetch_git(repo_dir, max_age_seconds=600):
    fetch_head = os.path.join(repo_dir, ".git", "FETCH_HEAD")
    if not os.path.exists(fetch_head):
        return True
    try:
        age = time.time() - os.path.getmtime(fetch_head)
        return age > max_age_seconds
    except Exception:
        return True

def get_claude_cli_status(force=False):
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

    def fetch_remote():
        return run_cmd(["npm", "view", "@anthropic-ai/claude-code", "version"]) or "Unknown"

    remote_ver = get_cached_or_fetch("npm:@anthropic-ai/claude-code", fetch_remote, ttl_seconds=900, force=force) or "Unknown"
    has_update = (local_ver != "Unknown" and remote_ver != "Unknown" and compare_versions(remote_ver, local_ver) > 0)
    return {
        "name": "Claude Code CLI",
        "current": local_ver,
        "latest": remote_ver,
        "has_update": has_update,
        "type": "cli"
    }

def get_vscode_extension_status(force=False):
    """Checks VS Code anthropic.claude-code extension."""
    if not shutil.which("code"):
        return {"name": "VS Code Extension", "current": "N/A (code not installed)", "latest": "-", "has_update": False, "type": "ide"}

    ext_list = run_cmd(["code", "--list-extensions", "--show-versions"])
    local_ver = "Not Installed"
    for line in ext_list.splitlines():
        if "anthropic.claude-code@" in line:
            local_ver = line.split("@")[-1].strip()
            break

    cli_status = get_claude_cli_status(force=force)
    latest_ver = cli_status["latest"]
    has_update = (local_ver != "Not Installed" and latest_ver != "Unknown" and compare_versions(latest_ver, local_ver) > 0)
    return {
        "name": "VS Code Extension",
        "current": local_ver,
        "latest": latest_ver,
        "has_update": has_update,
        "type": "ide"
    }

def get_uv_tool_status(tool_name, pkg_name, force=False):
    """Checks versions of uv-installed tools (specify-cli, scrapling)."""
    if not shutil.which("uv"):
        return {"name": pkg_name, "current": "N/A (uv missing)", "latest": "-", "has_update": False, "type": "tool"}

    raw = run_cmd(["uv", "tool", "list"])
    local_ver = "Not Installed"
    for line in raw.splitlines():
        if line.startswith(f"{pkg_name} "):
            local_ver = line.split()[1].lstrip("v")
            break

    def fetch_pypi():
        try:
            pypi_info = run_cmd(["curl", "-s", f"https://pypi.org/pypi/{pkg_name}/json"], timeout=5)
            if pypi_info:
                d = json.loads(pypi_info)
                return d.get("info", {}).get("version", local_ver)
        except Exception:
            pass
        return local_ver

    latest_ver = get_cached_or_fetch(f"pypi:{pkg_name}", fetch_pypi, ttl_seconds=900, force=force) or local_ver
    has_update = (compare_versions(latest_ver, local_ver) > 0)
    return {
        "name": pkg_name,
        "current": local_ver,
        "latest": latest_ver,
        "has_update": has_update,
        "type": "tool"
    }

def get_cortex_repo_status(force_fetch=False):
    """Checks Claude Cortex local git repository against remote origin/main."""
    if not os.path.isdir(os.path.join(CORTEX_REPO_DIR, ".git")):
        return {"name": "Claude Cortex Core Engine", "current": "v1.1.0", "latest": "v1.1.0", "has_update": False, "type": "repo"}

    # Throttled fetch: only fetch from remote origin if cache is older than 10 mins or force_fetch=True
    if force_fetch or should_fetch_git(CORTEX_REPO_DIR, max_age_seconds=600):
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
        "name": "Claude Cortex Core Engine",
        "current": cur_label,
        "latest": latest_label,
        "has_update": has_update,
        "type": "repo",
        "behind": behind
    }

# Alias for testing and programmatic checks
check_cortex_repo = get_cortex_repo_status

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

def apply_updates(statuses, with_ide=False):
    """Applies available updates across components safely.

    Only official, in-place update mechanisms are used. This function never pipes
    a remote script into a shell, never re-runs the Cortex installer, and never
    touches an IDE extension unless ``with_ide`` is explicitly set.
    """
    print("Starting automated updates across Claude Cortex ecosystem...\n")

    # 1. Update Claude Code CLI
    cli_item = next((s for s in statuses if s["type"] == "cli"), None)
    if cli_item and cli_item["has_update"]:
        print(f"[*] Updating Claude Code CLI from {cli_item['current']} -> {cli_item['latest']}...")
        # Use the CLI's own `update` subcommand. Never pipe a remote script into a
        # shell, and never re-point claude.real ourselves: the official updater
        # manages its own install layout, and rewriting that symlink from here is
        # how a half-finished update leaves the `claude` command broken.
        if os.path.exists(REAL_CLAUDE):
            run_res = subprocess.run([REAL_CLAUDE, "update"], capture_output=True, text=True)
            if run_res.returncode == 0:
                print("  ✓ Claude Code CLI updated via its official updater.")
            else:
                print(f"  ⚠ Claude Code CLI update warning: {run_res.stderr.strip()[:150]}")
        else:
            print("  ⚠ Official Claude Code binary not found; skipping CLI update.")
            print("    Install or repair it from https://claude.ai/download, then re-run.")

    # 2. Update VS Code Extension
    ide_item = next((s for s in statuses if s["name"] == "VS Code Extension"), None)
    if ide_item and ide_item["has_update"]:
        if with_ide:
            print("[*] Updating VS Code Extension (anthropic.claude-code)...")
            res = subprocess.run(["code", "--install-extension", "anthropic.claude-code", "--force"],
                                 capture_output=True, text=True)
            if res.returncode == 0:
                print("  ✓ VS Code extension updated.")
            else:
                print(f"  ⚠ Extension update warning: {res.stderr.strip()[:100]}")
        else:
            # Reinstalling an extension restarts the extension host and can drop a
            # live IDE session. Opt-in only.
            print("[ ] VS Code Extension update available (skipped).")
            print("    Re-run with --with-ide to update it, or update from the IDE UI.")

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
            # Deliberately NOT re-running install.sh. The installer mutates the
            # system install (wrappers, hooks, settings); running it silently from
            # an updater means a `git pull` can reconfigure the machine with no
            # review. Surface the command and let the operator decide.
            install_sh = os.path.join(CORTEX_REPO_DIR, "install.sh")
            if os.path.isfile(install_sh):
                print("    Repository content changed. To apply it to your install, review then run:")
                print(f"      bash {install_sh}")
        else:
            print(f"  ⚠ Git pull warning: {pull_res.stderr.strip()[:100]}")

    print("\n✓ Update execution complete! Verifying updated environment:")
    print_status_table(get_all_statuses())

def main():
    parser = argparse.ArgumentParser(description="Claude Cortex Multi-Component Update Manager")
    parser.add_argument("action", nargs="?", default="check", choices=["check", "status", "apply", "upgrade", "sync"])
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    parser.add_argument("--with-ide", action="store_true",
                        help="Also update the IDE extension (restarts the extension host)")
    args = parser.parse_args()

    statuses = get_all_statuses()

    if args.json:
        print(json.dumps(statuses, indent=2))
        return

    if args.action in ("check", "status"):
        print_status_table(statuses)
    elif args.action in ("apply", "upgrade", "sync"):
        apply_updates(statuses, with_ide=args.with_ide)

if __name__ == "__main__":
    main()
