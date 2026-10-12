"""Adopted profiles: existing Claude folders registered in place.

Most people who want several accounts already HAVE them - a default install plus
folders made by other tools. Moving or copying such a folder would change the string
Claude Code hashes into its credential namespace and silently log the account out, so
this registry never moves anything. It only remembers, for a profile name:

* ``config_dir``  - the folder used as ``CLAUDE_CONFIG_DIR`` (terminal / IDE), stored
  VERBATIM, never re-canonicalised: the login was created under that exact string.
* ``desktop_dir`` - the Desktop app's ``--user-data-dir`` folder, if there is one.
* ``surfaces``    - where this profile is meant to be used (terminal / ide / desktop).

Everything that would write into a profile folder (linking shared items, copying
settings, seeding identity, deleting) checks :func:`is_adopted` first and leaves an
adopted folder alone. The registry file lives beside the managed profiles.
"""

from __future__ import annotations

import os
from datetime import date

from . import jsonfile
from .paths import profiles_dir

SCHEMA = 1
SURFACES = ("terminal", "ide", "desktop")


def _path():
    return os.path.join(profiles_dir(), "registry.json")


def _error(message):
    from .profiles import CortexError          # late: profiles imports paths imports us
    return CortexError(message)


def load():
    """``{name: entry}``. A damaged registry raises rather than silently forgetting profiles."""
    status, data = jsonfile.read_status(_path())
    if status == jsonfile.MISSING:
        return {}
    if status == jsonfile.UNPARSEABLE:
        raise _error(f"{_path()} is damaged, so adopted profiles cannot be resolved. "
                     f"Restore {_path()}.bak or fix the JSON; nothing was changed.")
    if isinstance(data.get("schema"), int) and data["schema"] > SCHEMA:
        raise _error(f"{_path()} was written by a newer Cortex; update Cortex.")
    profiles = data.get("profiles")
    return profiles if isinstance(profiles, dict) else {}


def lookup(name):
    return load().get(name)


def is_adopted(name):
    """True when the profile's CONFIG folder is an adopted existing folder.

    A registry entry can also carry only a Desktop folder (``config_dir`` absent): the
    CLI side is then a normal Cortex-managed profile, which Cortex may create and
    maintain, and only the Desktop folder is someone else's.
    """
    entry = lookup(name)
    return bool(entry and entry.get("config_dir"))


def names():
    return sorted(load())


def _same(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _inside(parent, child):
    parent, child = os.path.normcase(os.path.abspath(parent)), os.path.normcase(os.path.abspath(child))
    try:
        return os.path.commonpath([parent, child]) == parent
    except ValueError:
        return False


def clean_path(value):
    """``(cleaned, notes)`` for a folder path typed by a person.

    Expands ``~`` and ``%VAR%`` / ``$VAR`` once, and removes a trailing separator (easy to
    paste from tab completion, and the login is tied to the exact string, so one canonical
    spelling without it is the safe one). Nothing else is rewritten: the path is NOT
    canonicalised or case-folded. ``notes`` says what was changed so it is never silent.
    """
    notes = []
    if not isinstance(value, str) or not value.strip():
        return value, notes
    cleaned = value.strip().strip('"')
    expanded = os.path.expanduser(os.path.expandvars(cleaned))
    if expanded != cleaned:
        notes.append(f"expanded {cleaned} to {expanded}")
        cleaned = expanded
    if ("%" in cleaned and cleaned.count("%") >= 2) or "${" in cleaned:
        raise _error(f"{value!r} refers to an environment variable that is not set")
    if len(cleaned) > 3 and cleaned[-1] in ("/", "\\"):
        cleaned = cleaned.rstrip("/\\")
        notes.append("removed the trailing slash")
    return cleaned, notes


def _check_dir(label, value):
    if not isinstance(value, str) or not value:
        raise _error(f"{label}: a folder path is required")
    if not os.path.isabs(value) or (os.name == "nt" and not os.path.splitdrive(value)[0]):
        raise _error(f"{label}: needs a full path including the drive, got {value!r}")
    if not os.path.isdir(value):
        raise _error(f"{label}: {value} is not an existing folder (adopt registers folders that "
                     f"already exist; it never creates or moves one)")


def adopt(name, config_dir, desktop_dir=None, surfaces=None):
    """Register existing folders under ``name``. Touches no profile data. Returns the entry.

    ``config_dir`` may be omitted when only a Desktop folder is being attached; the CLI
    side then stays a normal Cortex-managed profile of the same name.
    """
    if not config_dir and not desktop_dir:
        raise _error("give a config folder, a desktop folder, or both")
    config_dir = clean_path(config_dir)[0] if config_dir else config_dir
    desktop_dir = clean_path(desktop_dir)[0] if desktop_dir else desktop_dir
    if config_dir:
        _check_dir("config dir", config_dir)
    if desktop_dir:
        _check_dir("desktop dir", desktop_dir)
    chosen = list(surfaces or (["terminal"] if config_dir else [])
                  + (["desktop"] if desktop_dir else []))
    bad = [s for s in chosen if s not in SURFACES]
    if bad:
        raise _error(f"unknown surface {', '.join(bad)}; choose from {', '.join(SURFACES)}")

    root = profiles_dir()
    if config_dir and (_same(config_dir, root) or _inside(root, config_dir) or _inside(config_dir, root)):
        raise _error("that folder overlaps the Cortex profiles folder; adopt a separate account folder")

    existing = load()
    if name in existing:
        raise _error(f"profile '{name}' is already registered; forget it first to change it")
    for other, entry in existing.items():
        for key, given in (("config_dir", config_dir), ("desktop_dir", desktop_dir)):
            if given and entry.get(key) and _same(entry[key], given):
                raise _error(f"that folder is already registered as '{other}'")

    entry = {"config_dir": config_dir or None, "desktop_dir": desktop_dir or None, "surfaces": chosen,
             "adopted": date.today().isoformat()}
    os.makedirs(root, exist_ok=True)

    def add(data):
        data.setdefault("schema", SCHEMA)
        data.setdefault("profiles", {})[name] = entry
    jsonfile.update(_path(), add, {})
    return entry


def forget(name):
    """Unregister ``name``. Never touches the folders. Returns True if it was registered."""
    found = []

    def drop(data):
        found.append(bool((data.get("profiles") or {}).pop(name, None)))
    if os.path.exists(_path()):
        jsonfile.update(_path(), drop, {})
    return bool(found and found[0])


def set_surfaces(name, surfaces):
    bad = [s for s in surfaces if s not in SURFACES]
    if bad:
        raise _error(f"unknown surface {', '.join(bad)}; choose from {', '.join(SURFACES)}")

    os.makedirs(profiles_dir(), exist_ok=True)

    def apply(data):
        data.setdefault("schema", SCHEMA)
        table = data.setdefault("profiles", {})
        # A Cortex-managed profile has no entry yet; its surfaces are still worth recording.
        entry = table.setdefault(name, {"config_dir": None, "desktop_dir": None,
                                        "adopted": date.today().isoformat()})
        entry["surfaces"] = sorted(set(surfaces), key=SURFACES.index)
    jsonfile.update(_path(), apply, {})
