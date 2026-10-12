#!/usr/bin/env bash
# ==============================================================================
# Claude Cortex installer (macOS / Linux)
#
# A thin launcher. Everything the installer does lives in install.py, which is the
# one tested implementation (backup, settings merge, surfaces, profiles). Keeping a
# second copy of that logic here is how the shell and Python installers drifted
# apart before, so this file only finds Python and hands over.
#
#   ./install.sh --dry-run                       show what would change, change nothing
#   ./install.sh                                 ask first, then install
#   ./install.sh --yes --surfaces terminal,ide   unattended, with these surfaces
#   CORTEX_SANDBOX=1 ./install.sh                throwaway container / test home
#   CORTEX_PYTHON=/path/to/python3 ./install.sh  use a specific interpreter
#
# Needs Python 3.8+. Exit codes: 0 done, 2 bad option, 3 the safety prompt stopped it.
# ==============================================================================

set -eu

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${HOME:-}" ] || [ ! -d "${HOME}" ]; then
    echo "error: HOME is not set to an existing directory; refusing to continue." >&2
    exit 1
fi

usable() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1
}

PY=""
if [ -n "${CORTEX_PYTHON:-}" ]; then
    if usable "${CORTEX_PYTHON}"; then
        PY="${CORTEX_PYTHON}"
    else
        echo "error: CORTEX_PYTHON='${CORTEX_PYTHON}' is not a working Python 3.8+." >&2
        exit 1
    fi
else
    for candidate in python3 python python3.13 python3.12 python3.11 python3.10 python3.9 python3.8; do
        if command -v "$candidate" >/dev/null 2>&1 && usable "$candidate"; then
            PY="$candidate"
            break
        fi
    done
fi

if [ -z "$PY" ]; then
    echo "error: Python 3.8 or newer is required and was not found." >&2
    echo "       Install it (https://www.python.org/downloads/), or set CORTEX_PYTHON." >&2
    exit 1
fi

exec "$PY" "${HERE}/install.py" "$@"
