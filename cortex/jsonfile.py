"""Safe JSON read/write helpers.

Every write is atomic (temp file + replace) and backed up, because the files
involved - ``settings.json`` and ``.claude.json`` - hold a user's sign-in
session, MCP servers, folder-trust decisions, and their own customizations. A
half-written or clobbered file there is a genuinely bad outcome.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import time


#: Returned by :func:`read_status` when a file exists but cannot be parsed.
MISSING = "missing"
PARSED = "parsed"
UNPARSEABLE = "unparseable"

#: How long a caller waits for another process to finish its update.
LOCK_TIMEOUT = 10.0
#: A lock older than this belongs to a process that died holding it. Updates
#: here take milliseconds, so nothing legitimate holds a lock this long.
LOCK_STALE_AFTER = 30.0


def _break_if_stale(lock_path, stale_after):
    """Remove a lock whose owner is gone. Never raises."""
    try:
        age = time.time() - os.stat(lock_path).st_mtime
        if age > stale_after:
            os.unlink(lock_path)
    except OSError:
        pass


@contextlib.contextmanager
def file_lock(path, timeout=LOCK_TIMEOUT, stale_after=LOCK_STALE_AFTER):
    """Exclusive cross-process lock for read-modify-write of ``path``.

    ``write`` is atomic, but atomic replacement alone does not stop two terminals
    from each reading the old file and then each writing their own change, which
    silently loses one of them. This serialises the whole read-modify-write.

    The lock is a sidecar file created with ``O_EXCL``. A process killed while
    holding it would otherwise block every later caller forever, so a lock older
    than ``stale_after`` seconds is treated as abandoned and removed.
    """
    path = os.fspath(path)
    lock_path = path + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    deadline = time.monotonic() + timeout

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):
            # Windows reports PermissionError, not FileExistsError, when the
            # lock is held open or is pending deletion by another process.
            _break_if_stale(lock_path, stale_after)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for another Cortex process "
                                   f"to finish updating {path}") from None
            time.sleep(0.05)
            continue
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        finally:
            os.close(fd)
        break

    try:
        yield
    finally:
        try:
            os.unlink(lock_path)
        except OSError:
            pass


def update(path, modifier_fn, default=None):
    """Locked read-modify-write of a JSON object.

    ``modifier_fn`` receives the current data and either mutates it in place or
    returns a replacement. Returns the data that was written.
    """
    with file_lock(path):
        data = read(path, default)
        replacement = modifier_fn(data)
        if replacement is not None:
            data = replacement
        write(path, data)
    return data


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
    """Shallow-merge ``updates`` into the JSON object at ``path`` under a lock."""
    with file_lock(path):
        current = read(path, {})
        current.update(updates)
        write(path, current, backup=backup)
    return current
