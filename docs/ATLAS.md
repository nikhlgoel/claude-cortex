# The project map and the floating button

A map of your project that you can click: the files Graphify found, how they connect, and the notes
the palace holds about them - drawn on one canvas, with a small button that is always one click away
while you work in Claude.

Everything here describes what was built and run. Where something was **not** tried, it says so.

## What you see

- **The button.** A small round button that floats over your other windows, at the edge of the screen,
  whenever a Claude session is open in a project that has a Graphify graph or a palace. Click it: the
  map opens in its own window. Click it again: the map closes.
  - Drag it anywhere; it snaps to the nearest side and remembers where you left it.
  - Hover for a summary (files, notes, how many need a check). Right-click for a menu.
  - A **badge** counts notes whose code has changed since they were written.
  - Its ring is green when all is well, amber when something needs a check, grey when there is nothing
    yet, blue while the map is open.
- **The map.** Files are circles (bigger = more connected, coloured by the "area" Graphify found).
  Notes are diamonds attached to the files they are about:

  | Diamond | Meaning |
  |---|---|
  | green | the code it refers to is unchanged since the note was written |
  | amber | the code changed - read the note again before trusting it |
  | red | the file or function it refers to no longer exists |

  Click anything for details in the side panel. Double-click a file to draw its functions and who calls
  whom. Search (press `/`) finds files, functions and notes; matches stay lit while the rest fades.
  "Notes to check" jumps straight to the amber and red ones.

## You do not set anything up

The installer adds a small session hook. After that the button appears by itself. If you would rather
not have it:

```
cc graph button off        # stop it appearing (cc graph button on to bring it back)
```

or set `CORTEX_BUTTON=off`. With no Graphify graph and no palace in a project, nothing appears there.

To see the map without the button, from any project folder: `cc graph`.

## Commands

| Command | Does |
|---|---|
| `cc graph` | open the map for this project in its own window (closes when you close the window) |
| `cc graph serve` | only serve it, print the address, open it in any browser you like |
| `cc graph status` | what exists for this project, and the state of the button |
| `cc graph button` | status of the button; `on` / `off` to allow or stop it; `stop` closes a running one |

## What it needs

- **Python's tkinter** (the button's window). The standard python.org installer includes it; some Linux
  Pythons do not. `cc graph status` tells you.
- **A Chromium-based browser** already on the machine (Edge, Chrome or Brave) to show the map in its own
  window - the button can then really close it. With none of those, the map opens in your default browser
  and the button cannot close it for you.
- **Graphify**, to have code to draw: `graphify update .` builds a graph offline with no model. Without
  it the map still shows the files your notes mention.

Nothing is downloaded or installed by any of this.

## How it works

1. A `SessionStart` hook (`scripts/cortex-session-hook.py`) notes that a session opened in this project and
   starts the button if there is none. A `SessionEnd` hook removes the note; the button quits itself about
   20 seconds after the last session in its project closes.
2. The button process also runs a small web server for the map, on a random port of your own machine.
3. The map reads Graphify's `graph.json` (through the same small cache the palace uses) and the palace.
   It **never changes** either. The only thing it writes is that derived cache and a few tiny files under
   `~/.cortex/studio/` (open sessions, the button's heartbeat, its screen position, a private browser
   profile for the map window).

## Safety

The page serves your project's notes from a port on your machine, so:

- it listens on `127.0.0.1` only, and **no other program can share its port**;
- every request needs a random key that only the window it opened knows, and the `Host` header must be
  ours (this stops a website you have open from reading the map through your browser);
- it sends no cross-origin headers, never caches, and cannot be put in a frame;
- it is read-only: there is no way to edit, delete or send anything from the page;
- text from your project is inserted as plain text, never as HTML - a note containing `<script>` is just
  text (a test fails if any code path could do otherwise);
- the page loads nothing from the network.

## Honest limits

- **Checked on Windows 11 only.** On this machine: the map was drawn from a real 3,572-node Graphify graph
  of this repository; search, selecting, expanding functions and the amber/red states were used in a real
  browser; the button was shown on the real desktop; and a scripted test (`cc graph button start
  --selftest`) opened the map window, confirmed it existed, closed it and confirmed it was gone. The macOS
  and Linux code paths exist but have **not been run**.
- **Not verified: the Claude Desktop app.** The button is started by hooks, and hooks run wherever Claude
  Code reads your `settings.json` hooks. Whether the Desktop app's Code tab runs these exact hooks has not
  been confirmed on your machine. If the button does not appear there, run `cc graph button start` once
  (it then follows the sessions it finds) and tell me.
- **Hooks call `python3`.** On Windows the hook commands are `python3 ~/.claude/scripts/...`. On this
  machine `python3` happens to resolve (to the MSYS Python that came with your compiler). If it does not
  on another machine, no Cortex hook runs - including these. That is true of the existing hooks too.
- **Big graphs.** Past 1,500 files the map keeps the most connected ones and says so. The 230-file,
  3.5k-symbol graph builds its overview in about 0.2 s; much larger graphs have not been tried.
- **The layout is a force simulation**: good for seeing clusters, not a precise diagram. It is checked for
  settling, clustering, determinism and speed, but "looks good" is a judgement - tell me what is off.
- **The map is as fresh as the graph.** Graphify does not rebuild itself; run `graphify update .` after
  large changes. A note turns amber only when Graphify's record of the code changes (or, without a graph,
  when the file's contents do).

## When something looks wrong

| You see | Likely cause |
|---|---|
| no button | `cc graph status` shows why: the button is off, no tkinter, no screen, or the project has no graph and no palace |
| the map opens in a normal browser tab and the button cannot close it | no Edge/Chrome/Brave found; set `CORTEX_BROWSER` to a Chromium-based browser's path |
| "No Graphify graph for this project yet" | run `graphify update .` in the project |
| a note is amber right after you wrote it | the graph was built before the note's file last changed; run `graphify update .` |
| an empty map | neither a graph nor notes exist yet: `graphify update .` and `cc palace init` |
