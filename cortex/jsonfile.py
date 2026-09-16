"""Safe JSON read/write helpers.

Every write is atomic (temp file + replace) and backed up, because the files
involved - ``settings.json`` and ``.claude.json`` - hold a user's sign-in
session, MCP servers, folder-trust decisions, and their own customizations. A
half-written or clobbered file there is a genuinely bad outcome.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile


#: Returned by :func:`read_status` when a file exists but cannot be parsed.
MISSING = "missing"
PARSED = "parsed"
UNPARSEABLE = "unparseable"


def read(path, default=None):
    """Read JSON, returning ``default`` when missing or unparseable."""
    if default is None:
        default = {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def read_status(path):
    """Read JSON, distinguishing "absent" from "present but unparseable".

    This distinction is load-bearing for any file we might rewrite. A VS Code
    ``settings.json`` is JSONC - comments and trailing commas are normal and
    ``json.load`` rejects them. Treating that failure as "empty file" and then
    writing turns a merge into a wipe: the user loses their theme, keybindings,
    and every other setting. Callers must check the status and refuse to write
    when it is ``UNPARSEABLE``.

    Returns ``(status, data)``.
    """
    if not os.path.exists(path):
        return MISSING, {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError:
        return UNPARSEABLE, {}
    except ValueError:
        return UNPARSEABLE, {}
    if not isinstance(data, dict):
        return UNPARSEABLE, {}
    return PARSED, data


def write(path, data, backup=True):
    """Atomically write JSON, keeping a ``.bak`` of any previous content."""
    path = os.fspath(path)
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)

    if backup and os.path.exists(path):
        try:
            shutil.copy2(path, path + ".bak")
        except OSError:
            pass

    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".cortex-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_text(path, text):
    """Atomically write a small text file.

    Found by the risk analyser: current_profile, .profile_mode and
    .profile_email were written with a plain open(mode="w"), which truncates
    immediately. A process killed between truncate and write leaves the file
    empty, and an empty current_profile means the next launch silently falls
    back to a different profile - a wrong answer with no error. JSON writes were
    already atomic; these were not.
    """
    path = os.fspath(path)
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".cortex-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def merge(path, updates, backup=True):
    """Shallow-merge ``updates`` into the JSON object at ``path``."""
    current = read(path, {})
    current.update(updates)
    write(path, current, backup=backup)
    return current
