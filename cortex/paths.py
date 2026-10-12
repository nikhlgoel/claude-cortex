"""
Canonical path resolution.

Claude Code namespaces stored credentials by a hash of the config-directory
*string*::

    suffix = "-" + sha256(CLAUDE_SECURESTORAGE_CONFIG_DIR).hexdigest()[:8]

The string is normalized NFC and nothing else - no case folding, no separator
normalization, no symlink resolution. So these are three different accounts::

    C:\\Users\\me\\.claude-profiles\\main
    /c/Users/me/.claude-profiles/main
    C:/Users/me/.claude-profiles/main/

That is why logging in through the bash wrapper and launching through the
PowerShell wrapper looked like being logged out: Git Bash and PowerShell built
different strings for the same directory.

Every config-dir string in Cortex therefore comes from :func:`canonical_dir`
here, so the terminal wrappers, the IDE settings writer, and the auth check all
emit byte-identical values.
"""

from __future__ import annotations

import hashlib
import os
import unicodedata
from pathlib import Path


def canonical_dir(path) -> str:
    """Return the one true string form of a directory path.

    Absolute, symlinks resolved, no trailing separator, native separators, NFC
    normalized. Deterministic for a given directory regardless of the shell or
    path syntax the caller used.
    """
    text = os.fspath(path)

    # Git Bash / MSYS style: /c/Users/... or /mnt/c/Users/... -> C:\Users\...
    if os.name == "nt":
        lowered = text.replace("\\", "/")
        if lowered.startswith("/mnt/") and len(lowered) > 6 and lowered[6:7] == "/":
            text = lowered[5].upper() + ":" + lowered[6:]
        elif len(lowered) > 2 and lowered[0] == "/" and lowered[2:3] == "/":
            text = lowered[1].upper() + ":" + lowered[2:]

    expanded = os.path.expanduser(os.path.expandvars(text))

    try:
        resolved = Path(expanded).resolve()
    except (OSError, RuntimeError):
        resolved = Path(os.path.abspath(expanded))

    result = os.path.normpath(str(resolved))

    # normpath keeps the trailing separator on a drive root ("C:\\"); everywhere
    # else a trailing separator would change the hash, so strip it.
    if len(result) > 3 and result.endswith((os.sep, "/")):
        result = result.rstrip(os.sep + "/")

    return unicodedata.normalize("NFC", result)


def securestorage_suffix(config_dir: str) -> str:
    """Reproduce Claude Code's credential-namespace suffix for a config dir.

    Used by ``cortex doctor`` to show whether two entry points would land in the
    same credential namespace.
    """
    canonical = unicodedata.normalize("NFC", config_dir)
    return "-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def home() -> str:
    return canonical_dir(Path.home())


def profiles_dir() -> str:
    override = os.environ.get("CORTEX_PROFILES_DIR")
    if override:
        return canonical_dir(override)
    return canonical_dir(os.path.join(home(), ".claude-profiles"))


def shared_claude_dir() -> str:
    return canonical_dir(os.path.join(home(), ".claude"))


def profile_dir(name: str) -> str:
    # An ADOPTED profile is an existing folder registered in place. Its path is returned
    # verbatim - never re-canonicalised - because Claude Code derives the credential
    # namespace from the exact string the login was created under.
    from . import registry                      # late: registry imports this module
    entry = registry.lookup(name)
    if entry and entry.get("config_dir"):
        return entry["config_dir"]
    return canonical_dir(os.path.join(profiles_dir(), name))


def is_native_default(config_dir: str) -> bool:
    """True when ``config_dir`` is the folder Claude Code uses on its own: ``~/.claude``.

    With CLAUDE_CONFIG_DIR unset, Claude Code keeps its user config in ``~/.claude.json``
    (next to the folder). With it set - even to ``~/.claude`` itself - it reads
    ``<dir>/.claude.json`` instead, a DIFFERENT file: MCP servers, project trust and
    onboarding state would silently go missing for the default account.
    """
    if not config_dir:
        return False
    norm = lambda p: os.path.normcase(os.path.normpath(p).replace("/", os.sep))    # noqa: E731
    return norm(config_dir) == norm(os.path.join(home(), ".claude"))


def apply_config_env(env: dict, config_dir: str) -> dict:
    """Point ``env`` at ``config_dir`` the way Claude Code expects, and return it.

    Both variables carry the identical string (the credential namespace is derived from
    it). For the native default folder they are REMOVED instead, so the session behaves
    exactly like a plain ``claude`` and keeps using ``~/.claude.json``.
    """
    if is_native_default(config_dir):
        env.pop("CLAUDE_CONFIG_DIR", None)
        env.pop("CLAUDE_SECURESTORAGE_CONFIG_DIR", None)
    else:
        env["CLAUDE_CONFIG_DIR"] = config_dir
        env["CLAUDE_SECURESTORAGE_CONFIG_DIR"] = config_dir
    return env


def bin_dir() -> str:
    return canonical_dir(os.path.join(home(), ".local", "bin"))
