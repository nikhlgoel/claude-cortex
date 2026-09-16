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
import subprocess

from . import binary, jsonfile
from .paths import canonical_dir, profile_dir, profiles_dir, shared_claude_dir

VALID_NAME = "abcdefghijklmnopqrstuvwxyz0123456789_-"

# Directories shared between profiles in "synced" mode. Credentials and
# .claude.json are deliberately absent: those are what makes a profile distinct.
SYNCED_ITEMS = [
    "projects", "file-history", "history.jsonl", "commands", "skills",
    "rules", "plugins", "mcp-configs", "ide", "palace", "agents",
]


def normalize_name(name: str) -> str:
    return "".join(c for c in (name or "").strip().lower() if c in VALID_NAME)


def list_profiles():
    root = profiles_dir()
    if not os.path.isdir(root):
        return []
    try:
        return sorted(e for e in os.listdir(root)
                      if os.path.isdir(os.path.join(root, e)))
    except OSError:
        return []


def current_profile_file() -> str:
    return os.path.join(profiles_dir(), "current_profile")


def active_profile() -> str:
    env = os.environ.get("CLAUDE_PROFILE")
    if env:
        return normalize_name(env)
    try:
        with open(current_profile_file(), encoding="utf-8") as fh:
            name = normalize_name(fh.read())
            if name:
                return name
    except OSError:
        pass
    existing = list_profiles()
    return existing[0] if existing else "main"


def set_active(name: str) -> None:
    name = normalize_name(name)
    os.makedirs(profiles_dir(), exist_ok=True)
    with open(current_profile_file(), "w", encoding="utf-8") as fh:
        fh.write(name)


def profile_mode(name: str) -> str:
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
    try:
        if os.path.isdir(src):
            os.makedirs(dst, exist_ok=True)
        else:
            import shutil
            shutil.copy2(src, dst)
    except OSError:
        pass


def ensure_structure(name: str, mode: str = "synced") -> str:
    """Create the profile directory, returning its canonical path."""
    name = normalize_name(name)
    target = profile_dir(name)
    os.makedirs(target, exist_ok=True)

    with open(os.path.join(target, ".profile_mode"), "w", encoding="utf-8") as fh:
        fh.write(mode)

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
            import shutil
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

    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = config_dir
    env["CLAUDE_SECURESTORAGE_CONFIG_DIR"] = config_dir
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
    target = profile_dir(name)
    status = auth_status(target)
    if not status.get("loggedIn"):
        return False

    config_path = os.path.join(target, ".claude.json")
    cfg = jsonfile.read(config_path, {})

    cfg["hasCompletedOnboarding"] = True
    email = status.get("email")
    if email:
        account = cfg.get("oauthAccount")
        if not isinstance(account, dict):
            account = {}
        account["emailAddress"] = email
        cfg["oauthAccount"] = account
    if status.get("subscriptionType"):
        cfg["subscriptionType"] = status["subscriptionType"]

    jsonfile.write(config_path, cfg)

    # Cache the email so status listings work without spawning the CLI.
    try:
        with open(os.path.join(target, ".profile_email"), "w", encoding="utf-8") as fh:
            fh.write(email or "")
    except OSError:
        pass
    return True


def profile_email(name: str) -> str:
    cfg = jsonfile.read(os.path.join(profile_dir(name), ".claude.json"), {})
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
        print("No working Claude Code binary found. Run 'cc doctor' for details.")
        return 1

    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = target
    env["CLAUDE_SECURESTORAGE_CONFIG_DIR"] = target

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
    import shutil
    name = normalize_name(name)
    target = profile_dir(name)
    if not os.path.isdir(target):
        print(f"Profile '{name}' does not exist.")
        return 1
    if canonical_dir(target) == canonical_dir(profiles_dir()):
        print("Refusing to remove the profiles root.")
        return 1

    shutil.rmtree(target, ignore_errors=True)
    _AUTH_CACHE.pop(target, None)

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
