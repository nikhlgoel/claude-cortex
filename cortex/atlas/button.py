"""
The floating button.

A small round button that stays on top of your windows while a Claude session is open in a project
that has a map. Click it to open the map in its own window; click again to close it. Drag it anywhere
(it remembers where, and snaps to the nearest screen edge); right-click for a menu; hover for a
summary. A badge counts notes whose code changed since they were written.

How it fits together:

* one process per project, started by the session hook (``cc graph button start --follow-sessions``);
* the process also runs the local map server (``server.py``), so opening the map is instant;
* the map opens in the Chromium-based browser already on the machine (Edge, Chrome, Brave), in its own
  chromeless window (``--app``) with a private profile - so the button can really close it again.
  With no such browser it falls back to the default browser, which it cannot close;
* it quits itself shortly after the last session in the project ends.

Only the standard library is used (``tkinter``, ``ctypes``): nothing to install.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from . import AtlasError, sessions
from .data import Atlas
from .server import AtlasServer

SIZE = 50
EDGE_GAP = 8
TRANSPARENT = "#010203"                    # drawn as "nothing" on Windows, so the button is round
COLORS = {"disc": "#1d2230", "ink": "#e8ecf4", "line": "#98a3ba", "good": "#3fb27f", "attention": "#e0a030",
          "none": "#6f7686", "open": "#6c9bff", "badge_text": "#1b1300"}
TITLE_SUFFIX = "project map"


# --------------------------------------------------------------------------- the map window

def find_app_browser(env=None):
    """A Chromium-based browser that supports ``--app``, or None. ``CORTEX_BROWSER`` overrides."""
    env = env or os.environ
    override = env.get("CORTEX_BROWSER")
    if override and os.path.isfile(override):
        return override
    if sys.platform.startswith("win"):
        pf, pf86, local = env.get("ProgramFiles", ""), env.get("ProgramFiles(x86)", ""), env.get("LOCALAPPDATA", "")
        candidates = [os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
                      os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
                      os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
                      os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
                      os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
                      os.path.join(pf, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")]
    elif sys.platform == "darwin":
        candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                      "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]
    else:
        candidates = [shutil.which(n) or "" for n in ("google-chrome", "google-chrome-stable", "chromium",
                                                       "chromium-browser", "microsoft-edge", "brave-browser")]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def app_command(exe, url, profile_dir):
    return [exe, "--app=" + url, "--user-data-dir=" + profile_dir, "--window-size=1280,860",
            "--no-first-run", "--no-default-browser-check", "--disable-background-mode", "--disable-sync"]


class MapWindow:
    """Open, close and ask about the map's window."""

    def __init__(self, url, project_name):
        self.url = url
        self.name = project_name
        self.proc = None
        self.launched = 0.0

    # Windows: ask the OS, so a window the person closed (or another process owns) is seen correctly.
    def _hwnds(self):
        if not sys.platform.startswith("win"):
            return []
        import ctypes
        user32 = ctypes.windll.user32
        wanted = {("%s – %s" % (self.name, TITLE_SUFFIX)).lower(), TITLE_SUFFIX}
        found = []
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def visit(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if buf.value.strip().lower() in wanted:
                        found.append(hwnd)
            return True

        user32.EnumWindows(proc_type(visit), 0)
        return found

    def is_open(self):
        if sys.platform.startswith("win"):
            if self._hwnds():
                return True
            return bool(self.proc and self.proc.poll() is None and time.time() - self.launched < 10)   # still starting
        return bool(self.proc and self.proc.poll() is None)

    def open(self):
        exe = find_app_browser()
        if exe:
            profile = os.path.join(sessions.studio_dir(), "browser-profile")
            os.makedirs(profile, exist_ok=True)
            self.proc = subprocess.Popen(app_command(exe, self.url, profile), stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            self.launched = time.time()
            return "app-window"
        webbrowser.open(self.url)
        return "default-browser"

    def close(self):
        if sys.platform.startswith("win"):
            import ctypes
            for hwnd in self._hwnds():
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)       # WM_CLOSE: a polite close
            deadline = time.time() + 2.5
            while self._hwnds() and time.time() < deadline:
                time.sleep(0.1)
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None

    def toggle(self):
        if self.is_open():
            self.close()
            return "closed"
        return self.open()


# --------------------------------------------------------------------------- remembered position

def _position_file():
    return os.path.join(sessions.studio_dir(), "button-position.json")


def _load_position():
    try:
        with open(_position_file(), encoding="utf-8") as fh:
            data = json.load(fh)
        return int(data["x"]), int(data["y"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_position(x, y):
    try:
        os.makedirs(os.path.dirname(_position_file()), exist_ok=True)
        with open(_position_file(), "w", encoding="utf-8") as fh:
            json.dump({"x": x, "y": y}, fh)
    except OSError:
        pass


# --------------------------------------------------------------------------- the button

def _summary(status):
    if not status:
        return "Loading the project map..."
    lines = ["Project map - %s" % status.get("project", "")]
    parts = []
    if status.get("graph"):
        parts.append("%d files" % status.get("files", 0))
    else:
        parts.append("no code graph yet (graphify update .)")
    if status.get("palace"):
        parts.append("%d notes" % status.get("memories", 0))
    lines.append("  ·  ".join(parts))
    if status.get("attention"):
        lines.append("%d note%s to check" % (status["attention"], "" if status["attention"] == 1 else "s"))
    lines.append("Click to open or close  ·  drag to move  ·  right-click for more")
    return "\n".join(lines)


class FloatingButton:
    def __init__(self, project_dir, follow_sessions=False, selftest=False):
        try:
            import tkinter
        except ImportError as exc:
            raise AtlasError("The floating button needs Python's tkinter, which this Python does not have (%s)." % exc)
        self.tk = tkinter
        self.atlas = Atlas(project_dir)
        self.key = self.atlas.key
        self.follow = follow_sessions
        self.selftest = selftest
        self.server = AtlasServer(self.atlas).start()
        self.window = MapWindow(self.server.url, self.atlas.name)
        self.status = {}
        self._stop = threading.Event()
        self._tip = None
        self._tip_job = None
        self._press = None
        self._dragged = False
        self._empty_since = None
        self._result = 0
        self._build()

    # -- window ----------------------------------------------------------------------

    def _build(self):
        tk = self.tk
        if sys.platform.startswith("win"):
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)      # crisp on high-DPI screens
            except Exception:
                pass
        self.root = tk.Tk()
        self.root.title("Cortex project map button")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.95)
        except tk.TclError:
            pass
        background = COLORS["disc"]
        if sys.platform.startswith("win"):
            self.root.configure(bg=TRANSPARENT)
            self.root.attributes("-transparentcolor", TRANSPARENT)
            background = TRANSPARENT
        self.canvas = tk.Canvas(self.root, width=SIZE, height=SIZE, bg=background, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_menu)
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._hide_tip)
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        saved = _load_position()
        x, y = saved if saved else (sw - SIZE - 14, int(sh * 0.42))
        self._place(x, y, snap=False)
        self._draw()

    def _place(self, x, y, snap=True):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if snap:
            x = EDGE_GAP if x + SIZE / 2 < sw / 2 else sw - SIZE - EDGE_GAP
        x = max(0, min(x, sw - SIZE))
        y = max(EDGE_GAP, min(y, sh - SIZE - 60))                   # keep clear of the taskbar
        self.root.geometry("%dx%d+%d+%d" % (SIZE, SIZE, x, y))

    # -- drawing ---------------------------------------------------------------------

    def _state_color(self):
        if self.window.is_open():
            return COLORS["open"]
        if not self.status.get("graph") and not self.status.get("palace"):
            return COLORS["none"]
        return COLORS["attention"] if self.status.get("attention") else COLORS["good"]

    def _draw(self):
        c = self.canvas
        c.delete("all")
        c.create_oval(3, 3, SIZE - 3, SIZE - 3, fill=COLORS["disc"], outline=self._state_color(), width=3)
        nodes = [(17, 18, 3.6), (34, 16, 3.2), (25, 34, 4.4)]
        for a, b in ((0, 1), (0, 2), (1, 2)):
            c.create_line(nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1], fill=COLORS["line"], width=1.6)
        for x, y, r in nodes:
            c.create_oval(x - r, y - r, x + r, y + r, fill=COLORS["ink"], outline="")
        attention = self.status.get("attention") or 0
        if attention:
            c.create_oval(SIZE - 21, 1, SIZE - 3, 19, fill=COLORS["attention"], outline=COLORS["disc"], width=2)
            c.create_text(SIZE - 12, 10, text=str(attention) if attention < 10 else "9+", fill=COLORS["badge_text"],
                          font=("Segoe UI" if sys.platform.startswith("win") else "Helvetica", 8, "bold"))

    # -- mouse -----------------------------------------------------------------------

    def _on_press(self, event):
        self._hide_tip()
        self._press = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self._dragged = False

    def _on_motion(self, event):
        if not self._press:
            return
        dx, dy = event.x_root - self._press[0], event.y_root - self._press[1]
        if abs(dx) + abs(dy) > 5:
            self._dragged = True
        if self._dragged:
            self._place(self._press[2] + dx, self._press[3] + dy, snap=False)

    def _on_release(self, _event):
        if self._dragged:
            self._place(self.root.winfo_x(), self.root.winfo_y(), snap=True)
            _save_position(self.root.winfo_x(), self.root.winfo_y())
        else:
            self.toggle_map()
        self._press = None

    def toggle_map(self):
        try:
            self.window.toggle()
        except Exception:
            pass
        self._draw()

    def _on_menu(self, event):
        tk = self.tk
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Close the map" if self.window.is_open() else "Open the map", command=self.toggle_map)
        menu.add_command(label="Refresh numbers", command=self._refresh_now)
        menu.add_separator()
        menu.add_command(label="Hide the button for good", command=self._disable)
        menu.add_command(label="Quit (it returns with the next session)", command=self.quit)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_enter(self, _event):
        self._tip_job = self.root.after(350, self._show_tip)

    def _show_tip(self):
        self._hide_tip()
        tk = self.tk
        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        label = tk.Label(tip, text=_summary(self.status), justify="left", bg="#1d2230", fg="#e8ecf4",
                         padx=10, pady=7, font=("Segoe UI" if sys.platform.startswith("win") else "Helvetica", 9))
        label.pack()
        tip.update_idletasks()
        sw = self.root.winfo_screenwidth()
        x = self.root.winfo_x() - tip.winfo_width() - 8 if self.root.winfo_x() > sw / 2 else self.root.winfo_x() + SIZE + 8
        tip.geometry("+%d+%d" % (max(0, x), self.root.winfo_y()))
        self._tip = tip

    def _hide_tip(self, _event=None):
        if self._tip_job:
            try:
                self.root.after_cancel(self._tip_job)
            except Exception:
                pass
            self._tip_job = None
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    # -- background work -------------------------------------------------------------

    def _poll_loop(self):
        while not self._stop.is_set():
            self.status = self.atlas.status()
            self._stop.wait(8.0)

    def _refresh_now(self):
        threading.Thread(target=lambda: setattr(self, "status", self.atlas.status()), daemon=True).start()

    def _tick(self):
        """Every few seconds: show the latest numbers, prove we are alive, decide whether to quit."""
        sessions.write_beat(self.key, os.getpid(), self.server.port)
        self._draw()
        if self.follow:
            if not sessions.button_enabled():
                return self.quit()
            if sessions.live_sessions(self.key):
                self._empty_since = None
            else:
                self._empty_since = self._empty_since or time.time()
                if time.time() - self._empty_since > 20:
                    return self.quit()
        self.root.after(3000, self._tick)

    def _disable(self):
        sessions.set_button_enabled(False)
        self.quit()

    def quit(self, code=0):
        self._result = code
        self._stop.set()
        try:
            self.window.close()
        except Exception:
            pass
        try:
            self.server.stop()
            self.atlas.close()
        except Exception:
            pass
        sessions.clear_button(self.key)
        self._hide_tip()
        try:
            self.root.destroy()
        except Exception:
            pass

    # -- an end-to-end check you can run by hand ------------------------------------

    def _selftest(self):
        """Open the map, confirm its window exists, close it, confirm it is gone. Needs a real screen."""
        log = []

        def step(delay, fn):
            self.root.after(delay, fn)

        def opened():
            ok = self.window.is_open()
            log.append("window opened: %s" % ok)
            self.toggle_map()
            step(4000, closed)

        def closed():
            gone = not self.window.is_open()
            log.append("window closed again: %s" % gone)
            print("; ".join(log))
            self.quit(0 if log[1].endswith("True") and log[2].endswith("True") else 1)

        def start():
            how = self.window.open()
            log.append("opened as %s" % how)
            step(9000, opened)

        step(1200, start)

    def run(self):
        threading.Thread(target=self._poll_loop, daemon=True, name="button-status").start()
        self.root.after(1500, self._tick)
        if self.selftest:
            self._selftest()
        self.root.mainloop()
        return self._result


def run_button(project_dir, follow_sessions=False, selftest=False):
    """Run the floating button for a project until it quits. Returns an exit code."""
    atlas_key = Atlas(project_dir).key
    if not selftest and not sessions.try_lock(atlas_key):
        return 0                                    # another button already serves this project
    sessions.write_beat(atlas_key, os.getpid(), 0)
    button = FloatingButton(project_dir, follow_sessions=follow_sessions, selftest=selftest)
    try:
        return button.run()
    finally:
        sessions.clear_button(atlas_key)
