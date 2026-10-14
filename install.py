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
    # One implementation, shared with `cc profile surfaces` (cortex/surfaces.py).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cortex import surfaces
    return surfaces.register_desktop_mcp(cfg_path, command, script)


#: Folders inside ~/.claude that this installer writes into (so they are what a backup must keep).
_BACKUP_DIRS = ("commands", "rules", "scripts", "skills", "agents", "hooks")
#: Never worth archiving: regenerable, and the reason a full-folder archive took hours.
_BACKUP_SKIP = {"node_modules", "__pycache__", ".git", "cache", ".cache"}
_BACKUP_MAX_FILE_MB = 5


def _backup_limit_mb():
    """How big a folder may be before the installer leaves it in place instead of copying it."""
    try:
        return max(1, int(os.environ.get("CORTEX_BACKUP_LIMIT_MB", "300")))
    except ValueError:
        return 300


def _tree_size_mb(path, limit_mb):
    """Size of a folder in MB, giving up as soon as it is clearly over ``limit_mb``."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
            if total > limit_mb * 1048576:
                return total / 1048576.0
    return total / 1048576.0


def _backup_members(claude_dir):
    """The small files worth archiving: top-level config in ``~/.claude`` and the folders the installer
    writes into. Skips caches and any single file over a few MB."""
    cap = _BACKUP_MAX_FILE_MB * 1048576

    def small(fp):
        try:
            return fp.is_file() and fp.stat().st_size <= cap
        except OSError:
            return False

    if not claude_dir.is_dir():
        return
    for entry in sorted(claude_dir.iterdir()):
        if small(entry):
            yield entry
    for name in _BACKUP_DIRS:
        folder = claude_dir / name
        if not folder.is_dir():
            continue
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in _BACKUP_SKIP]
            for fname in files:
                fp = Path(root) / fname
                if small(fp):
                    yield fp


def merge_settings(src_path, dest_path):
    """Add Cortex's hooks and defaults to the user's settings.json without losing theirs.

    The old code treated ANY failure (a trailing comma, a BOM, a half-written file)
    as permission to copy Cortex's file over the user's - discarding their
    permissions, environment, MCP servers and hooks with no message. And on valid
    JSON it did a shallow ``dict.update``, replacing the user's whole ``hooks`` object
    and their model/theme/effort. Now:
      * an unreadable existing file is left exactly as it is, with instructions;
      * the user's values win; Cortex only fills in keys they have not set;
      * hooks are merged per event, adding Cortex's commands if not already present;
      * a backup is taken and the write is atomic.
    Returns True if the file was written.
    """
    try:
        with open(src_path, "r", encoding="utf-8-sig") as f:
            ours = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"  ! Could not read Cortex's settings ({exc}); settings.json not changed.")
        return False

    if not dest_path.exists():
        shutil.copy2(src_path, dest_path)
        return True

    try:
        with open(dest_path, "r", encoding="utf-8-sig") as f:   # tolerate a BOM
            theirs = json.load(f)
        if not isinstance(theirs, dict):
            raise ValueError("top level is not an object")
    except (OSError, ValueError) as exc:
        print(f"  ! Left {dest_path} untouched: it could not be parsed ({exc}).")
        print(f"    Merge the 'hooks' from {src_path} into it by hand.")
        return False

    for key, value in ours.items():
        if key != "hooks":
            theirs.setdefault(key, value)

    their_hooks = theirs.get("hooks")
    if their_hooks is not None and not isinstance(their_hooks, dict):
        print(f"  ! Left {dest_path} untouched: its 'hooks' is not an object.")
        return False
    their_hooks = theirs.setdefault("hooks", {})
    for event, entries in (ours.get("hooks") or {}).items():
        existing = their_hooks.setdefault(event, [])
        if not isinstance(existing, list):
            print(f"  ! Skipped hook event '{event}': yours is not a list.")
            continue
        have = {h.get("command") for e in existing if isinstance(e, dict)
                for h in (e.get("hooks") or []) if isinstance(h, dict)}
        for entry in entries:
            commands = {h.get("command") for h in (entry.get("hooks") or []) if isinstance(h, dict)}
            if not commands & have:
                existing.append(entry)
            elif "matcher" in entry:
                # Already installed by an earlier version: bring ITS matcher up to
                # date (the guard used to match only "Bash", so PowerShell was never
                # guarded) without touching anything of the user's.
                for e in existing:
                    mine = {h.get("command") for h in (e.get("hooks") or []) if isinstance(h, dict)} \
                        if isinstance(e, dict) else set()
                    if mine & commands:
                        e["matcher"] = entry["matcher"]

    try:
        shutil.copy2(dest_path, str(dest_path) + ".cortex-install.bak")
        tmp = str(dest_path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(theirs, f, indent=2)
        os.replace(tmp, dest_path)
    except OSError as exc:
        print(f"  ! Could not update {dest_path}: {exc}")
        return False
    print(f"  ✓ Merged Cortex hooks into {dest_path} (backup: settings.json.cortex-install.bak)")
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
        sys.exit(GUARD_DECLINED_EXIT)      # not 0: a caller must not report "installed"
    return True


def choose_surfaces():
    """Where the person will use Cortex: from --surfaces, else asked, else terminal only.

    Any mix is allowed and more can be added later with `cc profile surfaces`; the choice
    only controls what the installer touches, never which account or data is used.
    """
    argv = sys.argv[1:]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cortex import surfaces
    given = None
    for i, arg in enumerate(argv):
        if arg == "--surfaces" and i + 1 < len(argv):
            given = argv[i + 1]
        elif arg.startswith("--surfaces="):
            given = arg.split("=", 1)[1]
    if given is not None:
        try:
            return surfaces.parse(given)
        except ValueError as exc:
            print(f"  {exc}")
            sys.exit(2)
    interactive = (sys.stdin.isatty() and "--yes" not in argv and "-y" not in argv
                   and os.environ.get("CORTEX_SANDBOX") != "1")
    if not interactive:
        return ["terminal"]
    print("  Where will you use Cortex profiles?  (you can add more later)")
    print("    1) terminal      2) IDE extensions (VS Code, Antigravity...)      3) Claude Desktop")
    try:
        answer = input("  Choose, e.g. 1,3  [1]: ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        return ["terminal"]
    names = {"1": "terminal", "2": "ide", "3": "desktop"}
    tokens = [c for c in answer.replace(" ", ",").split(",") if c]
    picked = [names[c] for c in tokens if c in names]
    unknown = [c for c in tokens if c not in names]
    if unknown or not picked:
        print(f"  Did not understand '{answer}' (use numbers 1, 2, 3). "
              f"{'Using ' + ', '.join(picked) if picked else 'Using terminal only'}; "
              f"add more any time with: cc profile surfaces <name> terminal,ide,desktop")
    return surfaces.parse(",".join(picked)) if picked else ["terminal"]


def skip_primary_profile(profiles_dir):
    """True when the 'main' profile should not be created.

    It is a copy/link set of ~/.claude with no login of its own; once the person has
    adopted their real account folders it only adds a confusing extra profile.
    """
    if "--no-primary-profile" in sys.argv[1:]:
        return True
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from cortex import registry
        return bool(registry.names())
    except Exception:
        return False


KNOWN_FLAGS = {"--yes", "-y", "--dry-run", "--surfaces", "--no-primary-profile",
               "--help", "-h"}
USAGE = """usage: install.py [--dry-run] [--yes] [--surfaces terminal,ide,desktop]
                  [--no-primary-profile]

  --dry-run               show what would change, change nothing
  --yes, -y               skip the typed confirmation (CORTEX_SANDBOX=1 also does)
  --surfaces LIST         where profiles will be used: terminal, ide, desktop (any mix)
  --no-primary-profile    do not create the extra 'main' profile
"""


def check_arguments(argv):
    """Exit 2 on a flag this installer does not know, instead of ignoring it silently.

    Silently ignoring `--profile=work` or a typo'd `--dry_run` would run a real install
    the person did not ask for.
    """
    skip = False
    for i, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        if arg == "--surfaces":
            if i + 1 >= len(argv):
                print("  --surfaces needs a value, e.g. --surfaces terminal,desktop")
                sys.exit(2)
            skip = True
        elif arg.startswith("--surfaces="):
            continue
        elif arg not in KNOWN_FLAGS:
            print(f"  Unknown option: {arg}")
            print()
            print(USAGE)
            sys.exit(2)
    if "--help" in argv or "-h" in argv:
        print(USAGE)
        sys.exit(0)


def main():
    check_arguments(sys.argv[1:])
    is_windows = (sys.platform == "win32")
    home = Path.home()
    script_dir = Path(__file__).resolve().parent
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    bin_dir = home / ".local" / "bin"
    claude_dir = home / ".claude"
    profiles_dir = home / ".claude-profiles"
    backup_dir = home / ".claude-backups"

    if not confirm_install(bin_dir, claude_dir, profiles_dir):
        return

    surface_list = choose_surfaces()
    skip_primary = skip_primary_profile(profiles_dir)

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

    # What is backed up is what this installer can change, plus the account file - not a full copy of
    # ~/.claude. On a real machine that folder is gigabytes of conversation history and plugin caches
    # which the installer never touches; zipping all of it took hours (every small file is scanned by
    # antivirus) and several GB of disk. Big folders are measured and left in place with a note;
    # `cc guard snapshot` / `cc guard verify` is the check that they were not changed.
    limit_mb = _backup_limit_mb()
    for item in ["projects", "file-history", "history.jsonl", "config.json"]:
        p = claude_dir / item
        if not p.exists():
            continue
        size_mb = _tree_size_mb(p, limit_mb) if p.is_dir() else p.stat().st_size / 1048576.0
        if size_mb > limit_mb:
            print(f"  ℹ Left {item} in place ({'over ' if p.is_dir() else ''}{size_mb:,.0f} MB, more than the "
                  f"{limit_mb} MB backup limit). The installer does not touch it.")
            continue
        if p.is_dir():
            shutil.copytree(p, staging_dir / item, dirs_exist_ok=True)
        else:
            shutil.copy2(p, staging_dir / item)
        print(f"  ✓ Staged {item}")

    members = list(_backup_members(claude_dir))
    # Archive to zip/tar
    if is_windows:
        backup_archive = backup_dir / f"claude-backup-{timestamp}.zip"
        try:
            with zipfile.ZipFile(backup_archive, "w", zipfile.ZIP_DEFLATED) as zf:
                if user_claude_json.exists():
                    zf.write(user_claude_json, ".claude.json")
                for fp in members:
                    zf.write(fp, str(fp.relative_to(home)))
            size_mb = backup_archive.stat().st_size / (1024 * 1024)
            shutil.copy2(backup_archive, backup_dir / "latest.zip")
            print(f"  ✓ Safe pre-installation archive created: {backup_archive.name} "
                  f"({size_mb:.2f} MB, {len(members)} files)")
        except Exception as e:
            print(f"  ⚠ Backup archive note: {e}")
    else:
        backup_archive = backup_dir / f"claude-backup-{timestamp}.tar.gz"
        try:
            with tarfile.open(backup_archive, "w:gz") as tf:
                if user_claude_json.exists():
                    tf.add(user_claude_json, arcname=".claude.json")
                for fp in members:
                    tf.add(fp, arcname=str(fp.relative_to(home)), recursive=False)
            size_mb = backup_archive.stat().st_size / (1024 * 1024)
            print(f"  ✓ Safe pre-installation archive created: {backup_archive.name} "
                  f"({size_mb:.2f} MB, {len(members)} files)")
        except Exception as e:
            print(f"  ⚠ Backup archive note: {e}")

    # 3. Preserve underlying official binary
    print("\n[3/7] Preserving underlying official Claude binary...")
    real_binary_name = "claude.real.exe" if is_windows else "claude.real"
    real_binary_target = bin_dir / real_binary_name

    preserved = False
    for cand in detected_official:
        if cand.is_file() and "claude.real" not in cand.name:
            # Copy to a temp name and replace, so a failed copy (disk full, an
            # antivirus lock) never leaves a truncated claude.real that a later run
            # mistakes for a good one and the wrapper then execs. A good binary
            # preserved by an earlier install is never deleted on failure.
            tmp_target = real_binary_target.with_name(real_binary_target.name + ".tmp")
            try:
                shutil.copy2(cand, tmp_target)
                if not is_windows:
                    tmp_target.chmod(0o755)
                os.replace(tmp_target, real_binary_target)
                print(f"  ✓ Preserved official binary to: {real_binary_target}")
                preserved = True
                break
            except OSError as exc:
                print(f"  ! Could not preserve {cand}: {exc}")
                try:
                    tmp_target.unlink()
                except OSError:
                    pass

    if not preserved and not real_binary_target.exists():
        # Never downloaded here. This used to fetch an executable from a hard-coded URL with
        # no checksum and install it as the binary the wrapper runs; the URL is now a 404, and
        # even a working one would be an unverified program fetched without being asked.
        print("  ! Claude Code itself was not found, so there is nothing to wrap yet.")
        print("    Install it first (https://claude.ai/download, or: npm i -g @anthropic-ai/claude-code),")
        print("    then run `cc doctor`. Cortex does not download programs for you.")

    # 4. Nothing to clean. This step used to delete ~/.claude/downloads and RENAME the
    # official %LOCALAPPDATA%\Programs\claude\claude.exe to .exe.bak - moving aside the
    # user's working Claude Code, which is exactly the failure the README and HANDOVER
    # say the installer never causes. Cortex preserves a COPY (step 3) and leaves
    # the official installation exactly where it is.
    print("\n[4/7] Leaving the official Claude Code installation untouched.")

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

    # CLAUDE.md is the user's own global memory. Never overwrite it: if there is
    # already one that differs, ship ours beside it and say how to include it.
    claude_md = script_dir / "config" / "CLAUDE.md"
    if claude_md.exists():
        user_md = claude_dir / "CLAUDE.md"
        if not user_md.exists():
            shutil.copy2(claude_md, user_md)
        elif user_md.read_bytes() != claude_md.read_bytes():
            shutil.copy2(claude_md, claude_dir / "CLAUDE.cortex.md")
            print("  ! You already have ~/.claude/CLAUDE.md, so it was left alone.")
            print("    Cortex's instructions are in ~/.claude/CLAUDE.cortex.md; add the line")
            print("    @CLAUDE.cortex.md to your CLAUDE.md to include them.")

    # Merge settings.json
    src_settings = script_dir / "config" / "settings.json"
    dest_settings = claude_dir / "settings.json"
    if src_settings.exists():
        merge_settings(src_settings, dest_settings)

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

    # Setup profile. Skipped when the person has adopted real account folders (or asked
    # for no primary profile): the 'main' profile below is a COPY/link set of ~/.claude
    # that has no login of its own, and an adopted profile is what they actually use.
    if skip_primary:
        print("  - Skipped the primary 'main' profile (adopted profiles are in use, or --no-primary-profile).")
    else:
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
                    # settings.json is COPIED, never linked: Claude Code writes it when
                    # you change /config or /model, and through a link those writes
                    # either leak into every other profile or are lost (see profiles.py).
                    if s_item == "settings.json":
                        shutil.copy2(src_item, dst_item)
                    elif is_windows:
                        if src_item.is_dir():
                            # A junction needs no privilege. The old `mklink /J` call never
                            # checked its result, so when it failed nothing raised, the
                            # copy fallback below never ran, and the profile silently
                            # lacked the shared directory while the installer reported
                            # "full data synchronization".
                            import _winapi
                            _winapi.CreateJunction(str(src_item), str(dst_item))
                        else:
                            shutil.copy2(src_item, dst_item)
                    else:
                        os.symlink(src_item, dst_item)
                except (OSError, ImportError, AttributeError):
                    if src_item.is_dir():
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_item, dst_item)
        print(f"  ✓ Initialized primary profile [{primary_prof}] with full data synchronization")

    # 7. Surfaces. Only what was chosen is touched: PATH for the terminal, the Cortex MCP
    # tools for Claude Desktop folders that ALREADY exist, and a pointer for IDE extensions
    # (`cc ide apply` takes a profile, so it is the person's choice, not the installer's).
    print("\n[7/7] Configuring the surfaces you chose: " + ", ".join(surface_list) + "...")
    sandbox = os.environ.get("CORTEX_SANDBOX") == "1"
    if "terminal" in surface_list:
        if sandbox:
            # The registry and shell rc files belong to the REAL user whatever HOME says, so
            # a sandboxed run must never write them.
            print("  - Sandbox mode: PATH was not changed.")
        elif is_windows:
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0,
                                    winreg.KEY_READ | winreg.KEY_WRITE) as key:
                    current_path, _ = winreg.QueryValueEx(key, "Path")
                    bin_str = str(bin_dir)
                    if bin_str not in current_path:
                        new_path = f"{bin_str};{current_path}"
                        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
                        print(f"  ✓ Added {bin_dir} to User PATH in Windows Registry")
            except Exception as e:
                print(f"  ⚠ Registry PATH update note: {e}")
        else:
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

    from cortex import surfaces as surface_tools
    for line in surface_tools.apply(surface_list, str(claude_dir / "scripts" / "cortex-mcp.py"),
                                    "python" if is_windows else "python3"):
        print(f"  - {line}")

    print_header("Installation Complete! Claude Cortex is Ready Everywhere.")
    print("\nGet started:")
    print("  cc doctor                  Check the install and your Claude Code binary")
    print("  cc profile detect          Find your existing Claude folders (read-only), then adopt them")
    print("  cc profile add <name>      Or create a new profile, then: cc login <name>")
    print("  cc profile surfaces <name> terminal,ide,desktop    Add where a profile is used, any time")
    print("  cc status                  Per-profile capacity (unknown stays unknown)")
    print("  cc continue                Resume the last conversation on a profile with room")
    print("  cc ide check | apply       Point IDE extensions at a profile (no files modified)")
    print("  cc palace init             Give this project a memory (one command, no questions)")
    print("  cc palace | remember | recall   Project memory")
    print("  cc analyze <path>          Static risk analysis of source code")
    print("  cc --help                  Everything else")
    print("=" * 70)

if __name__ == "__main__":
    main()
