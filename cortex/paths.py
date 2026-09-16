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
    return canonical_dir(os.path.join(profiles_dir(), name))


def bin_dir() -> str:
    return canonical_dir(os.path.join(home(), ".local", "bin"))
