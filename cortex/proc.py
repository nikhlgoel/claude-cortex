"""Run child processes so that a timeout actually bounds the wait.

``subprocess.run(args, capture_output=True, timeout=N)`` looks bounded, and on
POSIX it is. On Windows it is not, whenever the child spawned a grandchild that
inherited the stdout/stderr pipes - which is the normal case for ``code.CMD`` and
``npm.CMD`` (cmd.exe -> node), ``git`` (-> git-remote-https) and ``docker``. On
timeout Python kills only the direct child; ``run()`` then calls ``communicate()``
again with *no* timeout and blocks until the grandchild exits. A reproduction here
returned after 11.2 s for ``timeout=2``.

This helper starts the child in its own process group, and on timeout kills the
whole tree, so the pipes close and the call returns when it said it would. It also
resolves ``.CMD`` shims (``npm``, ``code``), which ``CreateProcess`` cannot launch
by bare name, and decodes output as UTF-8 so a legacy console code page cannot
turn a harmless emoji into a ``UnicodeDecodeError``.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess

#: How long to wait for the pipes to drain after the tree has been killed.
DRAIN_SECONDS = 5


def resolve(command):
    """Return ``command`` with its executable resolved through PATH.

    ``shutil.which`` honours PATHEXT, so ``npm`` becomes ``...\\npm.CMD`` - which
    ``subprocess`` can launch - where the bare name raises FileNotFoundError.
    Unresolvable names are returned unchanged so the caller still gets the OS's
    own error.
    """
    command = list(command)
    if command:
        found = shutil.which(command[0])
        if found:
            # Native separators matter: under an MSYS-built Python, which() returns
            # mixed or forward slashes ("C:/WINDOWS/system32/cmd.EXE") and even
            # os.path.normpath keeps them, and cmd.exe mis-parses its own command
            # line ("The syntax of the command is incorrect") when its argv[0]
            # contains a forward slash. So convert explicitly on Windows.
            command[0] = found.replace("/", "\\") if os.name == "nt" else found
    return command


def kill_tree(proc):
    """Kill ``proc`` and everything it started. Never raises."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run(command, timeout, capture=True, input_text=None, env=None, cwd=None):
    """Run ``command`` and return a ``CompletedProcess``; raise TimeoutExpired.

    ``capture=False`` discards output instead of capturing it, which is the right
    choice whenever the output is not used.
    """
    kwargs = {
        "stdin": subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        "stdout": subprocess.PIPE if capture else subprocess.DEVNULL,
        "stderr": subprocess.PIPE if capture else subprocess.DEVNULL,
        "env": env,
        "cwd": cwd,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(resolve(command), **kwargs)
    try:
        out, err = proc.communicate(input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            # Something outside the tree still holds the pipes. Give up on the
            # captured text rather than hang - the caller asked for a bound.
            out, err = "", ""
        raise subprocess.TimeoutExpired(command, timeout, output=out, stderr=err) from None
    except BaseException:
        kill_tree(proc)
        raise
    return subprocess.CompletedProcess(command, proc.returncode, out, err)
