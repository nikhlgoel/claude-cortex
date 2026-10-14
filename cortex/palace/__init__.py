"""
The Cortex memory palace, version 3.

A layered, queryable memory for a project: a small always-on core, episodes, distilled facts,
verified procedures and a cold archive, kept in one SQLite file per scope. Facts have time
(a changed decision supersedes the old one rather than sitting beside it), every memory can be
anchored to the code it concerns (and is flagged when that code changes), and retrieval is a
measured pipeline that packs the best memories into a token budget.

The older flat-file palace (``scripts/claude-palace.py`` v2.5) is imported, never modified:
see ``legacy.py``.
"""

from __future__ import annotations

__all__ = ["PalaceError"]


class PalaceError(Exception):
    """A palace problem the person can act on. The message says what to do."""
