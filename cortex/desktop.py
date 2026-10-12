"""The Claude Desktop surface: find the app, detect existing profiles, launch one.

Each Desktop "profile" is an Electron ``--user-data-dir`` folder. Tools that offer several
Desktop accounts (and the default install) are all just different folders, so adopting
them is a matter of REMEMBERING where they are - nothing here moves, copies or edits
them. Detection reads shortcut targets and folder names only; it never opens credential
or session files.

Launching passes ``CLAUDE_CONFIG_DIR`` so Claude Code sessions started from the app can
use the same folder as the terminal. That is the documented way to point Claude Code at a
config folder, but whether the Desktop app's own Code tab honours it has NOT been
verified here; ``--no-config-dir`` launches the app untouched.
"""

from __future__ import annotations

import os
import re
import subprocess

from . import proc
from .paths import profile_dir, shared_claude_dir

_APP_DIR = re.compile(r"^app-(\d+(?:\.\d+)*)$")
_USER_DATA = re.compile(r'--user-data-dir=("([^"]+)"|(\S+))', re.I)

_LNK_SCRIPT = r"""
$w = New-Object -ComObject WScript.Shell
$dirs = @("$env:APPDATA\Microsoft\Windows\Start Menu\Programs", "$env:USERPROFILE\Desktop")
foreach ($d in $dirs) {
  if (Test-Path $d) {
    Get-ChildItem $d -Recurse -Filter *.lnk -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match 'claude' } |
      ForEach-Object { $s = $w.CreateShortcut($_.FullName); "{0}|{1}|{2}" -f $_.BaseName, $s.TargetPath, $s.Arguments }
  }
}
"""


def _version_key(name):
    match = _APP_DIR.match(name)
    return tuple(int(p) for p in match.group(1).split(".")) if match else ()


def find_exe():
    """Path to the newest installed Claude Desktop executable, or None.

    The versioned ``app-X.Y.Z`` folder is resolved at launch time, never stored: a
    shortcut that hard-codes it stops working at the next update.
    """
    local = os.environ.get("LOCALAPPDATA")
    if os.name != "nt" or not local:
        return None
    base = os.path.join(local, "AnthropicClaude")
    try:
        apps = sorted((e for e in os.listdir(base) if _version_key(e)), key=_version_key, reverse=True)
    except OSError:
        return None
    for app in apps:
        candidate = os.path.join(base, app, "claude.exe")
        if os.path.isfile(candidate):
            return candidate
    stub = os.path.join(base, "claude.exe")
    return stub if os.path.isfile(stub) else None


def _native(path):
    """Native separators on Windows. An MSYS-built Python hands back forward slashes."""
    return path.replace("/", "\\") if os.name == "nt" else path


def suggest_name(label):
    """A short profile name from a shortcut label: 'Claude (Studio)' -> 'studio'."""
    cleaned = re.sub(r"(?i)\bclaude\b", " ", label)
    name = "".join(c for c in cleaned.lower() if c.isalnum() or c in "-_")
    return name or "profile"


def _has_cli_login(folder):
    return os.path.isfile(os.path.join(folder, ".credentials.json"))


def _shortcuts(runner=proc.run):
    """``[(label, user_data_dir_or_None)]`` from Start-menu and Desktop Claude shortcuts."""
    if os.name != "nt":
        return []
    try:
        result = runner(["powershell", "-NoProfile", "-NonInteractive", "-Command", _LNK_SCRIPT],
                        timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in (result.stdout or "").splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        match = _USER_DATA.search(parts[2])
        found.append((parts[0].strip(), (match.group(2) or match.group(3)) if match else None))
    return found


def detect(runner=proc.run):
    """Candidate profiles found on this machine. Read-only; returns plain dicts.

    Each has ``label``, ``desktop_dir``, ``config_dir`` (a folder that already holds a CLI
    login, or None) and ``evidence``.
    """
    candidates, seen = [], set()

    def add(label, desktop_dir, evidence):
        desktop_dir = _native(desktop_dir)
        key = os.path.normcase(desktop_dir)
        if key in seen or not os.path.isdir(desktop_dir):
            return
        seen.add(key)
        config = desktop_dir if _has_cli_login(desktop_dir) else None
        candidates.append({"label": label, "desktop_dir": desktop_dir, "config_dir": config,
                           "evidence": evidence})

    appdata = os.environ.get("APPDATA")
    if appdata:
        add("default", os.path.join(appdata, "Claude"), "the default Desktop data folder")
    for label, folder in _shortcuts(runner):
        if folder:
            add(label, folder, f"shortcut '{label}' launches with --user-data-dir")

    shared = _native(shared_claude_dir())
    for entry in candidates:
        if entry["label"] == "default" and entry["config_dir"] is None and _has_cli_login(shared):
            entry["config_dir"] = shared
    return candidates


def launch(name, entry, share_config=True, spawn=subprocess.Popen):
    """Start Claude Desktop for a registry ``entry``. Returns the process id.

    Raises ``RuntimeError`` with a plain explanation if it cannot.
    """
    exe = find_exe()
    if not exe:
        raise RuntimeError("Claude Desktop was not found (looked in %LOCALAPPDATA%\\AnthropicClaude)")
    folder = (entry or {}).get("desktop_dir")
    if not folder or not os.path.isdir(folder):
        raise RuntimeError(f"profile '{name}' has no Desktop folder registered; run: "
                           f"cc profile adopt {name} --desktop <folder>")
    env = dict(os.environ)
    config = profile_dir(name)
    if share_config and os.path.isdir(config):
        env["CLAUDE_CONFIG_DIR"] = config
        env["CLAUDE_SECURESTORAGE_CONFIG_DIR"] = config
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    child = spawn([exe, f"--user-data-dir={folder}"], env=env, creationflags=flags,
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  close_fds=True)
    return child.pid
