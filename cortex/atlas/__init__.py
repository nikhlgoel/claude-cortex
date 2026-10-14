"""
Atlas: the interactive map of a project (``cc graph``).

It draws two things that already exist and invents nothing of its own:

* the **code graph** Graphify built (files, symbols, who-calls-whom, the areas it found), and
* the **palace** (what was decided and learned), pinned onto the files it is about, with a health
  colour: green = the code it refers to is unchanged, amber = it changed since, red = it is gone.

Everything here is read-only and local. The viewer is a page served from 127.0.0.1 behind a random
key; nothing is sent anywhere, and nothing is edited from it.
"""

from __future__ import annotations


class AtlasError(Exception):
    """Something the person can act on (no project, a port in use). Message is user-facing."""
