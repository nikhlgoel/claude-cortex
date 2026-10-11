"""
Claude Cortex - test suite sandbox guard.

Several tests in this suite read and write real paths under ``~/.claude``
(``scripts/``, ``commands/``, ``providers.json``). Running them against a live
Claude Code installation can overwrite a working configuration, so the suite
refuses to run outside a sandbox.

A run is considered sandboxed when either:

* ``CORTEX_SANDBOX=1`` is set - a container or throwaway environment, or
* ``HOME`` (``USERPROFILE`` on Windows) points somewhere clearly disposable,
  which is how the Windows sandbox script isolates a run.

Import ``require_sandbox()`` and call it before any test touches the filesystem.
"""

import os
import sys
import tempfile

#: Exit code meaning "the safety guard stopped this run", matching the installers.
GUARD_DECLINED_EXIT = 3


def _home() -> str:
    return os.path.expanduser("~")


def _looks_disposable(path: str) -> bool:
    """True when ``path`` sits inside a temp directory tree."""
    try:
        real = os.path.realpath(path)
        temp = os.path.realpath(tempfile.gettempdir())
    except OSError:
        return False
    return os.path.commonpath([real, temp]) == temp if real and temp else False


def _latency_scale() -> float:
    """Multiplier applied to every millisecond budget in the suite.

    The budgets were written against Linux containers. Spawning a Python process
    and doing fsync'd file work is several times slower on Windows (process
    creation, antivirus scanning), so the same code measures 5-10x higher there
    without being any slower relative to its platform. Scale instead of deleting
    the checks: they still catch a hook that becomes genuinely heavy. Override
    with CORTEX_TEST_LATENCY_SCALE (e.g. 1 for strict, 10 for a loaded CI box).
    """
    raw = os.environ.get("CORTEX_TEST_LATENCY_SCALE")
    if raw:
        try:
            return max(0.1, float(raw))
        except ValueError:
            pass
    return 6.0 if os.name == "nt" else 1.0


LATENCY_SCALE = _latency_scale()


def is_sandboxed() -> bool:
    if os.environ.get("CORTEX_SANDBOX") == "1":
        return True
    return _looks_disposable(_home())


def require_sandbox() -> None:
    """Abort the run unless we are in a sandbox."""
    if is_sandboxed():
        return

    home = _home()
    print("=" * 70)
    print("  Claude Cortex test suite - REFUSING TO RUN")
    print("=" * 70)
    print("  These tests read and write real paths under your home directory:")
    print(f"    {os.path.join(home, '.claude', 'scripts')}")
    print(f"    {os.path.join(home, '.claude', 'commands')}")
    print(f"    {os.path.join(home, '.claude', 'providers.json')}")
    print()
    print("  Running them against a live Claude Code installation can overwrite a")
    print("  working configuration. Run them in a container instead:")
    print()
    print("    make sandbox-fedora      # or: CORTEX_SANDBOX=1 inside a container")
    print("=" * 70)
    sys.exit(GUARD_DECLINED_EXIT)
