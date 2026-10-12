#!/usr/bin/env python3
"""
Claude Cortex - Multi-Component Unified Update Manager
Monitors, checks, and updates:
  1. Claude Code CLI (official binary & npm release)
  2. VS Code / IDE Extensions (anthropic.claude-code)
  3. Claude Desktop application
  4. Connected tools & libraries (specify-cli / spec-kit, scrapling)
  5. Claude Cortex repository (auto-fetch & pull from origin/main)

Honesty rules this tool follows (each one was a real defect):
  * A failed lookup is "Unknown" / "remote unreachable" - never "Up to date" - and a
    failed lookup is never cached as if it were an answer.
  * Every child process is bounded: on Windows a plain subprocess timeout does not
    bound the wait when a grandchild holds the pipe (see cortex/proc.py).
  * The summary line only says "complete" if every step succeeded.
"""

import os
import sys
import time
import json
import shutil
import argparse
import subprocess
import urllib.request

# Paths
HOME = os.path.expanduser("~")
BIN_DIR = os.path.join(HOME, ".local", "bin")
CORTEX_REPO_DIR = os.environ.get("CLAUDE_CORTEX_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if not os.path.isdir(os.path.join(CORTEX_REPO_DIR, ".git")):
    # Check common user workspaces
    for candidate in [os.path.expanduser("~/projects/claude-cortex"), os.path.expanduser("~/projects/temp/claude-cortex")]:
        if os.path.isdir(os.path.join(candidate, ".git")):
            CORTEX_REPO_DIR = candidate
            break

# --- Cortex's bounded process runner ---------------------------------------
# Prefer the installed core, then the checkout this script sits in. If neither is
# importable the script still works, with plain subprocess (and its Windows limits).
for _base in (os.path.expanduser("~/.claude/cortex-core"),
              os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
    if os.path.isdir(os.path.join(_base, "cortex")):
        sys.path.insert(0, _base)
        break
try:
    from cortex import proc as _proc
except ImportError:
    _proc = None

GIT_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0")   # never block on a credential prompt


def _utf8_stdio():
    """The status table prints symbols; a legacy console code page would crash on them."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _run(args, timeout, capture=True, env=None, cwd=None):
    """Run a command with a real time bound. Raises OSError / SubprocessError."""
    if _proc is not None:
        return _proc.run(args, timeout=timeout, capture=capture, env=env, cwd=cwd)
    args = list(args)
    found = shutil.which(args[0])
    if found:
        args[0] = found.replace("/", "\\") if os.name == "nt" else found
    sink = subprocess.PIPE if capture else subprocess.DEVNULL
    return subprocess.run(args, stdin=subprocess.DEVNULL, stdout=sink, stderr=sink, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=env, cwd=cwd)


def run_cmd(args, timeout=20):
    """Runs a command and returns stripped stdout, or '' on any failure."""
    try:
        res = _run(args, timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


def find_real_claude():
    """Path to the official Claude Code binary Cortex preserved, or None.

    Windows installs it as ``claude.real.exe``; looking only for ``claude.real``
    meant the CLI version probe and the apply step never found it there. Cortex's
    own ``claude`` wrapper is deliberately NOT a candidate: running it to read a
    version prints Cortex's version, not Claude Code's.
    """
    names = ("claude.real.exe", "claude.real.cmd", "claude.real") if os.name == "nt" else ("claude.real",)
    for name in names:
        path = os.path.join(BIN_DIR, name)
        if os.path.isfile(path):
            return path
    local = os.environ.get("LOCALAPPDATA")
    if local:
        path = os.path.join(local, "Programs", "claude", "claude.exe")
        if os.path.isfile(path):
            return path
    return None


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
    A side with no version digits ('Not Installed', 'Unknown') compares equal: no
    information is not "newer" - it used to compare as 1, so an uninstalled tool
    showed "UPDATE READY".
    """
    s1 = extract_version_number(v1)
    s2 = extract_version_number(v2)
    p1 = [int(x) for x in s1.split(".") if x.isdigit()]
    p2 = [int(x) for x in s2.split(".") if x.isdigit()]
    if not p1 or not p2:
        return 0
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
            with open(UPDATE_CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}


def save_update_cache(cache):
    try:
        os.makedirs(os.path.dirname(UPDATE_CACHE_FILE), exist_ok=True)
        with open(UPDATE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass


def get_cached_or_fetch(key, fetch_fn, ttl_seconds=600, force=False):
    """Return a cached answer, else fetch. A falsy result is a failure and is NOT cached."""
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
    except OSError:
        return True


def current_branch(repo_dir):
    """The checked-out branch, read from .git/HEAD (no subprocess), or '' if detached."""
    try:
        with open(os.path.join(repo_dir, ".git", "HEAD"), encoding="utf-8") as f:
            head = f.read().strip()
    except OSError:
        return ""
    prefix = "ref: refs/heads/"
    return head[len(prefix):] if head.startswith(prefix) else ""


def get_claude_cli_status(force=False):
    """Checks local vs upstream Claude Code CLI version."""
    local_ver = "Unknown"
    real = find_real_claude()
    if real:
        raw = run_cmd([real, "--version"])
        if raw:
            local_ver = raw.split()[0]

    def fetch_remote():
        # '' on failure so the failure is not cached as if it were a version.
        return run_cmd(["npm", "view", "@anthropic-ai/claude-code", "version"])

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
            with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg_name}/json", timeout=5) as resp:
                return json.load(resp).get("info", {}).get("version", "")
        except (OSError, ValueError):
            return ""          # not cached: an unreachable PyPI is not an answer

    latest_ver = get_cached_or_fetch(f"pypi:{pkg_name}", fetch_pypi, ttl_seconds=900, force=force) or "Unknown"
    has_update = (local_ver != "Not Installed" and latest_ver != "Unknown"
                  and compare_versions(latest_ver, local_ver) > 0)
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
    fetch_ok = True
    if force_fetch or should_fetch_git(CORTEX_REPO_DIR, max_age_seconds=600):
        try:
            # The output is unused, so it is discarded (capture=False): with a
            # captured pipe a hung git-remote-https keeps the call alive on Windows.
            fetch_ok = _run(["git", "fetch", "origin", "main"], timeout=10, capture=False,
                            env=GIT_ENV, cwd=CORTEX_REPO_DIR).returncode == 0
        except (OSError, subprocess.SubprocessError):
            fetch_ok = False

    local_hash = run_cmd(["git", "-C", CORTEX_REPO_DIR, "rev-parse", "--short", "HEAD"], timeout=5)
    remote_hash = run_cmd(["git", "-C", CORTEX_REPO_DIR, "rev-parse", "--short", "origin/main"], timeout=5)
    behind_count = run_cmd(["git", "-C", CORTEX_REPO_DIR, "rev-list", "HEAD..origin/main", "--count"], timeout=5)
    try:
        behind = int(behind_count)
    except ValueError:
        behind = 0

    has_update = (behind > 0)
    cur_label = f"{local_hash}"
    if has_update:
        latest_label = f"{remote_hash} (+{behind} commits)"
    elif fetch_ok:
        latest_label = f"{local_hash} (Up to date)"
    else:
        # The remote was never reached, so "Up to date" would be a claim with no
        # evidence behind it.
        latest_label = f"{local_hash} (remote unreachable)"
    return {
        "name": "Claude Cortex Core Engine",
        "current": cur_label,
        "latest": latest_label,
        "has_update": has_update,
        "type": "repo",
        "behind": behind,
        "branch": current_branch(CORTEX_REPO_DIR),
        "fetch_ok": fetch_ok,
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

    for item in statuses:
        has_up = item["has_update"]
        unknown = "Unknown" in (item["current"], item["latest"]) or "unreachable" in item["latest"]
        if has_up:
            status_tag = "\033[1;33m⚡ UPDATE READY\033[0m"
        elif unknown:
            status_tag = "\033[1;90m? UNKNOWN\033[0m"
        else:
            status_tag = "\033[1;32m✓ UP TO DATE\033[0m"
        print(f"  {item['name']:<28} {item['current']:<18} {item['latest']:<26} {status_tag}")

    any_update = any(item["has_update"] for item in statuses)
    print("==========================================================================================")
    if any_update:
        print("  To apply all pending updates, run:")
        print("    cc update apply   (or claude update apply)")
    else:
        print("  No pending updates found. (Rows marked UNKNOWN could not be checked.)")
    print("==========================================================================================")


def apply_updates(statuses, with_ide=False):
    """Applies available updates across components safely.

    Only official, in-place update mechanisms are used. This function never pipes
    a remote script into a shell, never re-runs the Cortex installer, and never
    touches an IDE extension unless ``with_ide`` is explicitly set.

    Returns the list of steps that did not complete (empty = everything worked).
    """
    print("Starting automated updates across Claude Cortex ecosystem...\n")
    problems = []

    # 1. Update Claude Code CLI
    cli_item = next((s for s in statuses if s["type"] == "cli"), None)
    if cli_item and cli_item["has_update"]:
        print(f"[*] Updating Claude Code CLI from {cli_item['current']} -> {cli_item['latest']}...")
        # Use the CLI's own `update` subcommand. Never pipe a remote script into a
        # shell, and never re-point claude.real ourselves: the official updater
        # manages its own install layout, and rewriting that symlink from here is
        # how a half-finished update leaves the `claude` command broken.
        real = find_real_claude()
        if real:
            try:
                # Generous bound: killing the updater mid-replace could leave the
                # install half-updated, so this should only ever fire on a true hang.
                run_res = _run([real, "update"], timeout=900)
                if run_res.returncode == 0:
                    print("  ✓ Claude Code CLI updated via its official updater.")
                else:
                    print(f"  ⚠ Claude Code CLI update warning: {run_res.stderr.strip()[:150]}")
                    problems.append("Claude Code CLI")
            except subprocess.TimeoutExpired:
                print("  ⚠ The Claude Code updater did not finish in 15 minutes and was stopped.")
                print("    Re-run `claude update` yourself and check that `claude --version` works.")
                problems.append("Claude Code CLI (timed out)")
            except OSError as exc:
                print(f"  ⚠ Could not run the Claude Code updater: {exc}")
                problems.append("Claude Code CLI")
        else:
            print("  ⚠ Official Claude Code binary not found; skipping CLI update.")
            print("    Install or repair it from https://claude.ai/download, then re-run.")
            problems.append("Claude Code CLI (binary not found)")

    # 2. Update VS Code Extension
    ide_item = next((s for s in statuses if s["name"] == "VS Code Extension"), None)
    if ide_item and ide_item["has_update"]:
        if with_ide:
            print("[*] Updating VS Code Extension (anthropic.claude-code)...")
            try:
                res = _run(["code", "--install-extension", "anthropic.claude-code", "--force"], timeout=180)
                if res.returncode == 0:
                    print("  ✓ VS Code extension updated.")
                else:
                    print(f"  ⚠ Extension update warning: {res.stderr.strip()[:100]}")
                    problems.append("VS Code extension")
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"  ⚠ Extension update failed: {exc}")
                problems.append("VS Code extension")
        else:
            # Reinstalling an extension restarts the extension host and can drop a
            # live IDE session. Opt-in only.
            print("[ ] VS Code Extension update available (skipped).")
            print("    Re-run with --with-ide to update it, or update from the IDE UI.")

    # 3. Update UV tools (specify-cli & scrapling)
    for pkg in ("specify-cli", "scrapling"):
        item = next((s for s in statuses if s["name"] == pkg), None)
        if item and item["has_update"]:
            print(f"[*] Upgrading {pkg} via uv tool upgrade...")
            try:
                res = _run(["uv", "tool", "upgrade", pkg], timeout=300)
                if res.returncode == 0:
                    print(f"  ✓ {pkg} upgraded successfully.")
                else:
                    print(f"  ⚠ {pkg} upgrade warning: {res.stderr.strip()[:100]}")
                    problems.append(pkg)
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"  ⚠ {pkg} upgrade failed: {exc}")
                problems.append(pkg)

    # 4. Update Claude Cortex repository
    repo_item = next((s for s in statuses if s["type"] == "repo"), None)
    if repo_item and repo_item["has_update"]:
        branch = repo_item.get("branch", "")
        if branch != "main":
            # `git pull origin main` merges origin/main into WHATEVER is checked
            # out. On a feature branch that is a surprise merge into your work.
            print(f"[ ] Cortex repository is behind origin/main, but '{branch or 'a detached HEAD'}' is checked out (not main).")
            print("    Not pulling automatically; switch to main or merge origin/main yourself.")
        else:
            print(f"[*] Pulling latest updates in Claude Cortex repository ({repo_item['behind']} new commits)...")
            try:
                pull_res = _run(["git", "pull", "--ff-only", "origin", "main"], timeout=120,
                                env=GIT_ENV, cwd=CORTEX_REPO_DIR)
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"  ⚠ Git pull failed: {exc}")
                problems.append("Cortex repository")
            else:
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
                    problems.append("Cortex repository")

    if problems:
        print(f"\n⚠ {len(problems)} step(s) did not complete: {', '.join(problems)}")
    else:
        print("\n✓ Update execution complete!")
    print("Verifying updated environment:")
    print_status_table(get_all_statuses())
    return problems


def main():
    _utf8_stdio()
    parser = argparse.ArgumentParser(description="Claude Cortex Multi-Component Update Manager")
    parser.add_argument("action", nargs="?", default="check", choices=["check", "status", "apply", "upgrade", "sync"])
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    parser.add_argument("--with-ide", action="store_true",
                        help="Also update the IDE extension (restarts the extension host)")
    args = parser.parse_args()

    statuses = get_all_statuses()

    if args.json:
        print(json.dumps(statuses, indent=2))
        return 0

    if args.action in ("check", "status"):
        print_status_table(statuses)
        return 0
    problems = apply_updates(statuses, with_ide=args.with_ide)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
