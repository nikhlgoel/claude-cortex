"""
Profile management and authentication.

Two bugs this module exists to fix:

1. **Authentication was probed by looking for ``.credentials.json``.** That file
   is not the whole story - on Windows credentials can live in Credential
   Manager instead, and the file's presence says nothing about whether the token
   is valid. The CLI ships ``claude auth status``, which reports authoritatively.
   It exits 0 *even when logged out*, so the ``loggedIn`` field must be read;
   the exit code carries no information.

2. **Onboarding state was never seeded.** ``claude auth login`` writes
   credentials, but the theme/onboarding prompt is driven by
   ``hasCompletedOnboarding`` in ``.claude.json`` inside the config dir. Without
   seeding it, every launch of a profile re-ran first-run onboarding - which is
   what looked like "it asks me to log in again even though I just did".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from . import binary, jsonfile
from .paths import (apply_config_env, canonical_dir, profile_dir, profiles_dir, shared_claude_dir,
                    user_config_path)

class CortexError(Exception):
    """An operation failed for a reason worth explaining to the operator.

    Used for filesystem conditions - read-only profiles root, no space, denied
    permissions - where a traceback tells the user nothing actionable.
    """


VALID_NAME = "abcdefghijklmnopqrstuvwxyz0123456789_-"

# Directories shared between profiles in "synced" mode. Credentials and
# .claude.json are deliberately absent: those are what makes a profile distinct.
SYNCED_ITEMS = [
    "projects", "file-history", "history.jsonl", "commands", "skills",
    "rules", "plugins", "mcp-configs", "ide", "palace", "agents",
    # The user's global instructions. CLAUDE_CONFIG_DIR relocates every ~/.claude
    # path, so without this a synced profile never saw the global CLAUDE.md (and
    # with it Cortex's own instructions). Isolated profiles share nothing, by design.
    "CLAUDE.md",
]


def normalize_name(name: str) -> str:
    return "".join(c for c in (name or "").strip().lower() if c in VALID_NAME)


def list_profiles():
    from . import registry
    adopted = registry.names()
    root = profiles_dir()
    if not os.path.isdir(root):
        return adopted
    try:
        managed = [e for e in os.listdir(root) if os.path.isdir(os.path.join(root, e))]
    except OSError:
        managed = []
    return sorted(set(managed) | set(adopted))


def current_profile_file() -> str:
    return os.path.join(profiles_dir(), "current_profile")


def active_profile() -> str:
    env = os.environ.get("CLAUDE_PROFILE")
    if env:
        return normalize_name(env)
    try:
        # errors="replace" because this file can contain anything: a truncated
        # write, a synced-folder conflict, or binary garbage. Undecodable bytes
        # become replacement characters, which normalize_name then strips - a
        # meaningless name rather than a UnicodeDecodeError traceback.
        with open(current_profile_file(), encoding="utf-8", errors="replace") as fh:
            name = normalize_name(fh.read())
            if name:
                return name
    except OSError:
        pass
    existing = list_profiles()
    return existing[0] if existing else "main"


def set_active(name: str) -> None:
    """Record the active profile.

    Raises :class:`CortexError` rather than a bare OSError so the caller can
    report something useful for a read-only or full filesystem.
    """
    name = normalize_name(name)
    try:
        os.makedirs(profiles_dir(), exist_ok=True)
        jsonfile.write_text(current_profile_file(), name)
    except OSError as exc:
        raise CortexError(
            f"cannot record the active profile in {profiles_dir()}: {exc.strerror}"
        ) from exc


def profile_mode(name: str) -> str:
    from . import registry
    if registry.is_adopted(name):
        return "adopted"
    path = os.path.join(profile_dir(name), ".profile_mode")
    try:
        with open(path, encoding="utf-8") as fh:
            mode = fh.read().strip().lower()
            return mode if mode in ("synced", "isolated") else "synced"
    except OSError:
        return "synced"


def _link(src: str, dst: str) -> None:
    """Link src -> dst, falling back to a copy where links are unavailable."""
    if os.path.exists(dst) or os.path.islink(dst):
        return
    try:
        os.symlink(src, dst, target_is_directory=os.path.isdir(src))
        return
    except (OSError, NotImplementedError, AttributeError):
        pass

    # Windows without the symlink privilege (no Developer Mode, not elevated):
    # a directory junction needs no privilege and shares a folder just as well.
    # Without this, "synced" mode quietly produced empty directories on exactly
    # the machines where it matters most.
    if os.name == "nt" and os.path.isdir(src):
        try:
            import _winapi
            _winapi.CreateJunction(src, dst)
            return
        except (ImportError, AttributeError, OSError):
            pass

    try:
        if os.path.isdir(src):
            os.makedirs(dst, exist_ok=True)
        else:
            # A hard link first: unlike a symlink it needs no privilege on Windows
            # (same volume), and it keeps the file shared. Only then fall back to a
            # copy - which is created once and never refreshed, so a later edit to
            # either side does not silently overwrite the other.
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
    except OSError:
        pass


_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: symlinks *and* junctions


def _is_link(path: str) -> bool:
    """True for a symlink or a Windows junction (os.path.islink misses junctions)."""
    if os.path.islink(path):
        return True
    try:
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & _REPARSE_POINT)


def _detach_links(target: str) -> list:
    """Remove the links at the top of a profile without following them.

    In synced mode ``projects``, ``skills`` and friends are links into the shared
    ``~/.claude``. ``shutil.rmtree`` is not guaranteed to leave a junction alone
    on every supported Python, and following one would delete the user's shared
    data, not just this profile's. Detach the links first, so what ``rmtree`` then
    deletes is only the profile's own files. Returns any links that survived.
    """
    try:
        entries = os.listdir(target)
    except OSError:
        return []
    survivors = []
    for entry in entries:
        path = os.path.join(target, entry)
        if not _is_link(path):
            continue
        try:
            os.unlink(path)
        except OSError:
            try:
                os.rmdir(path)   # removes a junction/dir-symlink, never its target
            except OSError:
                survivors.append(path)
    return survivors


def ensure_structure(name: str, mode: str = "synced") -> str:
    """Create the profile directory, returning its canonical path.

    An adopted profile is returned as-is: nothing is created, linked or copied into a
    folder that already holds a real account's data.
    """
    from . import registry
    name = normalize_name(name)
    if registry.is_adopted(name):
        return profile_dir(name)
    target = profile_dir(name)
    try:
        os.makedirs(target, exist_ok=True)
        jsonfile.write_text(os.path.join(target, ".profile_mode"), mode)
    except OSError as exc:
        raise CortexError(
            f"cannot create the profile directory {target}: {exc.strerror}"
        ) from exc

    if mode == "synced":
        shared = shared_claude_dir()
        for item in SYNCED_ITEMS:
            src = os.path.join(shared, item)
            if os.path.exists(src):
                _link(src, os.path.join(target, item))

    # settings.json is COPIED, never linked.
    #
    # Claude Code writes this file itself when you change something in /config or
    # save a default with /model. If it is a link into a shared location, those
    # writes either escape into every other profile or are silently lost - a
    # documented failure mode ("another tool generates it or links it to a
    # read-only copy"). A copy keeps each profile's settings its own.
    prof_settings = os.path.join(target, "settings.json")
    if not os.path.exists(prof_settings):
        shared_settings = os.path.join(shared_claude_dir(), "settings.json")
        if os.path.exists(shared_settings):
            shutil.copy2(shared_settings, prof_settings)

    return target


# Each auth check spawns the CLI. `cc status` checks every profile, and several
# code paths check the same profile more than once in a single command, so an
# uncached lookup multiplies process spawns and turns a status listing into
# seconds of waiting. Auth cannot change mid-command, so cache per process.
_AUTH_CACHE = {}


def auth_status(config_dir: str, refresh=False):
    """Ask the CLI whether this config dir is authenticated.

    Returns a dict from ``claude auth status``. The exit code is ignored on
    purpose: the real CLI exits 0 whether or not you are signed in, so only the
    ``loggedIn`` field is meaningful.
    """
    if not refresh and config_dir in _AUTH_CACHE:
        return _AUTH_CACHE[config_dir]

    result = _auth_status_uncached(config_dir)
    _AUTH_CACHE[config_dir] = result
    return result


def _auth_status_uncached(config_dir: str):
    exe = binary.find()
    if not exe:
        return {"loggedIn": False, "error": "no Claude Code binary found"}

    env = apply_config_env(dict(os.environ), config_dir)
    try:
        res = subprocess.run([exe, "auth", "status"], capture_output=True,
                             text=True, timeout=60, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"loggedIn": False, "error": str(exc)}

    text = (res.stdout or "").strip()
    start = text.find("{")
    if start >= 0:
        try:
            return json.loads(text[start:])
        except ValueError:
            pass
    return {"loggedIn": False, "error": text[:200] or "unparseable auth status"}


def is_authenticated(name: str) -> bool:
    return bool(auth_status(profile_dir(name)).get("loggedIn"))


def seed_identity(name: str) -> bool:
    """Record onboarding + account identity in the profile's .claude.json.

    Without this the CLI treats the profile as a brand new install on every
    launch and re-runs the theme picker and login prompt.
    """
    from . import registry
    target = profile_dir(name)
    status = auth_status(target)
    if not status.get("loggedIn"):
        return False
    if registry.is_adopted(name):
        return True                      # report the login; never rewrite an adopted folder

    config_path = os.path.join(target, ".claude.json")
    email = status.get("email")

    def apply(cfg):
        cfg["hasCompletedOnboarding"] = True
        if email:
            account = cfg.get("oauthAccount")
            if not isinstance(account, dict):
                account = {}
            account["emailAddress"] = email
            cfg["oauthAccount"] = account
        if status.get("subscriptionType"):
            cfg["subscriptionType"] = status["subscriptionType"]

    # Locked read-modify-write: two terminals logging in at once must not lose
    # one another's changes to this file.
    jsonfile.update(config_path, apply, {})

    # Cache the email so status listings work without spawning the CLI.
    try:
        jsonfile.write_text(os.path.join(target, ".profile_email"), email or "")
    except OSError:
        pass
    return True


def profile_email(name: str) -> str:
    cfg = jsonfile.read(user_config_path(profile_dir(name)), {})
    account = cfg.get("oauthAccount")
    if isinstance(account, dict) and account.get("emailAddress"):
        return account["emailAddress"]
    try:
        with open(os.path.join(profile_dir(name), ".profile_email"), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def login(name: str) -> int:
    """Run the interactive browser login for a profile, then seed identity."""
    name = normalize_name(name)
    target = ensure_structure(name, profile_mode(name))

    exe = binary.find()
    if not exe:
        print("No working Claude Code binary found.", file=sys.stderr)
        print("    Run 'cc doctor' to see each candidate and why it was rejected.",
              file=sys.stderr)
        print("    Or install Claude Code from https://claude.ai/download",
              file=sys.stderr)
        return 1

    env = apply_config_env(dict(os.environ), target)

    print(f"Starting authentication for profile '{name}'...")
    try:
        subprocess.run([exe, "auth", "login"], env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Login failed to start: {exc}")
        return 1

    _AUTH_CACHE.pop(target, None)  # a login just changed the answer
    if seed_identity(name):
        print(f"Authenticated '{name}' as {profile_email(name) or 'unknown account'}.")
        return 0

    print(f"Login did not complete for '{name}'. Run 'cc login {name}' to retry.")
    return 1


def remove(name: str) -> int:
    from . import registry
    name = normalize_name(name)
    if registry.is_adopted(name):
        # Unregister only. The folder holds a real account's login and history and was
        # not created by Cortex, so it is never deleted from here.
        folder = profile_dir(name)
        registry.forget(name)
        _AUTH_CACHE.pop(folder, None)
        print(f"Unregistered '{name}'. Its folder was left untouched: {folder}")
        return 0
    target = profile_dir(name)
    if not os.path.isdir(target):
        print(f"Profile '{name}' does not exist.")
        return 1
    if canonical_dir(target) == canonical_dir(profiles_dir()):
        print("Refusing to remove the profiles root.")
        return 1

    # Never let the delete walk through a link into shared data.
    survivors = _detach_links(target)
    if survivors:
        print(f"Refusing to remove '{name}': could not safely detach "
              f"{', '.join(os.path.basename(p) for p in survivors)}.", file=sys.stderr)
        print("    Deleting now could erase shared data. Remove those links by hand.",
              file=sys.stderr)
        return 1

    shutil.rmtree(target, ignore_errors=True)
    _AUTH_CACHE.pop(target, None)

    # ignore_errors hides failures (a file held open on Windows, for instance), so
    # check the result rather than announcing a removal that did not happen.
    if os.path.exists(target):
        print(f"Profile '{name}' was only partly removed - some files are in use "
              f"or read-only.", file=sys.stderr)
        print(f"    Close any session using it and delete {target} by hand.",
              file=sys.stderr)
        return 1

    if active_profile() == name:
        remaining = list_profiles()
        if remaining:
            set_active(remaining[0])
            print(f"Active profile switched to '{remaining[0]}'.")
        else:
            # Leaving the pointer at a deleted profile makes the next launch
            # silently recreate it, unauthenticated, under the old name.
            set_active("")
            print("No profiles remain. Create one with: cc profile add")
    print(f"Removed profile '{name}'.")
    return 0
