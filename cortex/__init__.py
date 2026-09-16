"""Claude Cortex - multi-account Claude Code launcher."""

import sys

__version__ = "2.0.0"

#: Minimum interpreter. The core uses f-strings with ``=``-free formatting,
#: ``from __future__ import annotations``, and ``os.replace`` semantics that are
#: stable from 3.8 onward.
MIN_PYTHON = (3, 8)

if sys.version_info < MIN_PYTHON:
    # A shell shim may pick up a Python 2 installed as `python`, in which case the
    # failure would otherwise be a SyntaxError deep inside an import - which looks
    # like a corrupt install rather than a wrong interpreter.
    sys.stderr.write(
        "cc: Python {}.{}+ is required, but this is {}.{} ({}).\n".format(
            MIN_PYTHON[0], MIN_PYTHON[1],
            sys.version_info[0], sys.version_info[1], sys.executable)
    )
    sys.stderr.write("    Set CORTEX_PYTHON to a newer interpreter, e.g.\n")
    sys.stderr.write("      CORTEX_PYTHON=$(command -v python3.12) cc\n")
    sys.exit(1)
