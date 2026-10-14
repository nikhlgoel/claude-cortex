"""
``cc graph`` - the interactive project map.

    cc graph                      open the map for this project in its own window
    cc graph serve                just serve it; open the printed address in any browser
    cc graph status               what exists for this project, and the state of the floating button
    cc graph button               state of the floating button
    cc graph button off | on      stop / allow the floating button (it is on by default)
    cc graph button start         run the button in this terminal (normally a hook starts it)
    cc graph button stop          close the running button for this project

The floating button appears by itself while a Claude session is open in a project that has a Graphify
graph or a palace. See docs/ATLAS.md.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

from . import AtlasError, sessions
from .data import Atlas
from .server import AtlasServer


def _atlas(args):
    return Atlas(getattr(args, "project", None) or os.getcwd())


def _ago(seconds):
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return "%d min ago" % round(seconds / 60)
    if seconds < 129600:
        return "%d h ago" % round(seconds / 3600)
    return "%d days ago" % round(seconds / 86400)


def cmd_status(args):
    atlas = _atlas(args)
    status = atlas.status()
    print("Project: %s   (%s)" % (atlas.name, atlas.root))
    if status.get("graph"):
        print("  code graph : %d files, built %s" % (status["files"], _ago(status["age_seconds"])))
    else:
        print("  code graph : none yet - build one (offline, no model):  graphify update .")
    if status.get("palace"):
        extra = ", %d need a check" % status["attention"] if status["attention"] else ""
        print("  palace     : %d notes%s" % (status["memories"], extra))
    else:
        print("  palace     : none yet - start it with:  cc palace init")
    return cmd_button_status(args, header=False)


def cmd_button_status(args, header=True):
    from .button import find_app_browser
    atlas = _atlas(args)
    if header:
        print("Project: %s" % atlas.name)
    enabled = sessions.button_enabled()
    alive = sessions.button_alive(atlas.key)
    print("  button     : %s, %s" % ("on" if enabled else "OFF (cc graph button on)",
                                    "running now" if alive else "not running"))
    print("  sessions   : %d open in this project" % len(sessions.live_sessions(atlas.key)))
    print("  screen     : %s; tkinter %s" % ("available" if sessions.gui_available() else "none",
                                            "available" if sessions.tkinter_available() else "MISSING (the button cannot start)"))
    browser = find_app_browser()
    print("  map window : %s" % (os.path.basename(browser) + " (its own window; the button can close it)"
                                 if browser else "no Edge/Chrome/Brave found - falls back to your default browser"))
    return 0


def _open_window(url):
    """Open the map in its own window if a suitable browser exists; return the Popen or None."""
    import subprocess
    import webbrowser
    from .button import app_command, find_app_browser
    exe = find_app_browser()
    if not exe:
        webbrowser.open(url)
        return None
    profile = os.path.join(sessions.studio_dir(), "browser-profile")
    os.makedirs(profile, exist_ok=True)
    return subprocess.Popen(app_command(exe, url, profile), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True)


def _serve_forever(server, proc=None):
    print("Map: %s" % server.url)
    print("Press Ctrl+C to stop.")
    try:
        while proc is None or proc.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
        server.stop()
    return 0


def cmd_open(args):
    atlas = _atlas(args)
    server = AtlasServer(atlas, port=args.port).start()
    proc = None if args.no_window else _open_window(server.url)
    try:
        return _serve_forever(server, proc)         # until the window closes, or Ctrl+C when there is none
    finally:
        atlas.close()


def cmd_serve(args):
    atlas = _atlas(args)
    server = AtlasServer(atlas, port=args.port).start()
    try:
        return _serve_forever(server)
    finally:
        atlas.close()


def cmd_button(args):
    action = args.action
    atlas = _atlas(args)
    if action == "status":
        return cmd_button_status(args)
    if action == "on":
        sessions.set_button_enabled(True)
        print("The floating button is on. It appears while a Claude session is open in a project with a map.")
        return 0
    if action == "off":
        sessions.set_button_enabled(False)
        pid = sessions.button_pid(atlas.key)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        print("The floating button is off. Turn it back on with:  cc graph button on")
        return 0
    if action == "stop":
        pid = sessions.button_pid(atlas.key)
        if not pid:
            print("No button is running for this project.")
            return 0
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            print("Could not stop it (%s)." % exc)
            return 1
        sessions.clear_button(atlas.key)
        print("Stopped.")
        return 0
    # start
    from .button import run_button
    try:
        return run_button(atlas.project_dir, follow_sessions=args.follow_sessions, selftest=args.selftest)
    except AtlasError as exc:
        print("cc graph: %s" % exc, file=sys.stderr)
        return 1


def build_parser():
    parser = argparse.ArgumentParser(prog="cc graph", description="The interactive map of this project.")
    sub = parser.add_subparsers(dest="command")

    def common(p):
        p.add_argument("--project", help="the project folder (default: the current folder)")

    p = sub.add_parser("open", help="open the map in its own window (the default)")
    common(p)
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-window", action="store_true", help="only serve; print the address")
    p.set_defaults(func=cmd_open)
    p = sub.add_parser("serve", help="serve the map and print its address")
    common(p)
    p.add_argument("--port", type=int, default=0)
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("status", help="what exists for this project")
    common(p)
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("button", help="the floating button")
    p.add_argument("action", nargs="?", default="status", choices=("status", "on", "off", "start", "stop"))
    common(p)
    p.add_argument("--follow-sessions", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_button)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = ["open"] + argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except AtlasError as exc:
        print("cc graph: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
