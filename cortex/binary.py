"""Locating the official Claude Code binary.

Resolution is ordered and every candidate is verified to actually run, because
the failure this guards against is a wrapper that points at a path which no
longer exists - which presents as ``claude: No such file or directory`` with no
indication of why.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .paths import bin_dir, home

WINDOWS = os.name == "nt"
EXE = "claude.exe" if WINDOWS else "claude"


def _candidates():
    """Yield possible binary paths, most specific first."""
    b = Path(bin_dir())
    for name in ("claude.real.exe", "claude.real.cmd", "claude.real"):
        yield b / name

    h = Path(home())
    local = os.environ.get("LOCALAPPDATA")
    if local:
        yield Path(local) / "Programs" / "claude" / "claude.exe"

    # Native installer layout: ~/.local/share/claude/versions/<version>
    versions = h / ".local" / "share" / "claude" / "versions"
    if versions.is_dir():
        try:
            for entry in sorted(versions.iterdir(), reverse=True):
                if entry.is_file():
                    yield entry
        except OSError:
            pass

    # npm global
    yield h / "AppData" / "Roaming" / "npm" / "claude.cmd"
    yield h / ".npm-global" / "bin" / "claude"

    # IDE-bundled native binaries are a legitimate last resort: they are real,
    # current Claude Code builds, and on a machine whose standalone install is
    # broken they are often the only working copy.
    for ide in (".vscode", ".vscode-insiders", ".vscode-oss", ".antigravity-ide",
                ".cursor", ".windsurf"):
        ext_root = h / ide / "extensions"
        if not ext_root.is_dir():
            continue
        try:
            for ext in sorted(ext_root.iterdir(), reverse=True):
                if ext.name.startswith("anthropic.claude-code-"):
                    cand = ext / "resources" / "native-binary" / EXE
                    if cand.exists():
                        yield cand
        except OSError:
            pass

    found = shutil.which("claude.real") or shutil.which("claude")
    if found:
        yield Path(found)


def _is_cortex_wrapper(path) -> bool:
    """True if this file is our own wrapper - never exec it, that would loop."""
    try:
        with open(path, "rb") as fh:
            return b"Claude Cortex" in fh.read(4096)
    except OSError:
        return False


def _runs(path) -> bool:
    try:
        res = subprocess.run([str(path), "--version"], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0 and "Claude Code" in (res.stdout or "")


# Resolution runs `--version` on each candidate, which is a subprocess. Callers
# ask repeatedly - `cc status` checks auth once per profile, and each check
# resolves the binary - so an uncached lookup turns a status listing into N
# process spawns and seconds of latency. The answer cannot change during a single
# command, so cache it for the process lifetime.
_CACHE = {}


def find(verify=True):
    """Return a path to a working Claude Code binary, or None."""
    override = os.environ.get("CORTEX_REAL_CLAUDE")
    if override and os.path.exists(override):
        return override

    if verify in _CACHE:
        return _CACHE[verify]

    result = _resolve(verify)
    _CACHE[verify] = result
    return result


def _resolve(verify):
    seen = set()
    fallback = None
    for cand in _candidates():
        text = str(cand)
        if text in seen or not os.path.exists(cand):
            continue
        seen.add(text)
        if _is_cortex_wrapper(cand):
            continue
        if not verify:
            return text
        if _runs(cand):
            return text
        if fallback is None:
            fallback = text

    # Nothing verified as runnable; hand back a plausible path so the caller can
    # produce a specific error rather than a generic "not found".
    return fallback


def reset_cache():
    """Forget the resolved binary. Used after an install or repair changes it."""
    _CACHE.clear()


def describe():
    """Diagnostic listing of every candidate and its state."""
    rows = []
    seen = set()
    for cand in _candidates():
        text = str(cand)
        if text in seen:
            continue
        seen.add(text)
        if not os.path.exists(cand):
            rows.append((text, "missing"))
        elif _is_cortex_wrapper(cand):
            rows.append((text, "cortex wrapper (skipped)"))
        elif _runs(cand):
            rows.append((text, "OK"))
        else:
            rows.append((text, "present but does not run"))
    return rows
