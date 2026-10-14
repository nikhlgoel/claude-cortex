"""
The local web server behind the map and the floating button.

Rules, because this serves your project's notes from a port on your machine:

* **Loopback only.** Bound to 127.0.0.1; never 0.0.0.0.
* **A random key on every request** (``?k=`` or the ``X-Atlas-Key`` header) - except the two script
  files, which are this program's own source and cannot carry a header. Another page open in your
  browser cannot guess the key, so it cannot read the map by calling localhost.
* **An exclusive port**: no other program can bind the same address and share the connections.
* **The Host header must be ours** (127.0.0.1 or localhost with our port), which defeats DNS-rebinding:
  a hostile site pointing its own name at 127.0.0.1 would otherwise be accepted.
* **No CORS headers**, so a browser will not let another origin read a response even with the key.
* **Read-only.** The one non-reading action is asking the server to rebuild its cache.
* **Fixed set of files.** Nothing is served from disk by path.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import AtlasError

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/force.js": ("force.js", "application/javascript; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
_PUBLIC = frozenset(("/force.js", "/app.js"))
_MAX_QUERY = 200


def _read_static(name):
    with open(os.path.join(STATIC_DIR, name), "rb") as fh:
        return fh.read()


class _ExclusiveServer(ThreadingHTTPServer):
    """A server that nobody else can share the port with.

    The standard server sets SO_REUSEADDR. On Windows that lets a second program bind the same address
    and port - and then connections may reach it instead of us, key or no key. Here the bind is exclusive:
    SO_EXCLUSIVEADDRUSE on Windows, no address reuse elsewhere.
    """

    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class AtlasServer:
    """Serve one Atlas. ``start()`` returns once the socket is listening."""

    def __init__(self, atlas, port=0, token=None):
        self.atlas = atlas
        self.token = token or secrets.token_urlsafe(18)
        self.started = time.time()
        self.last_request = time.time()
        self._httpd = None
        self._thread = None
        self._port = port

    # -- lifecycle -----------------------------------------------------------------------

    def start(self):
        server = self

        class Handler(_Handler):
            owner = server

        try:
            self._httpd = _ExclusiveServer(("127.0.0.1", self._port), Handler)
        except OSError as exc:
            raise AtlasError("Could not open a local port for the map (%s)." % exc)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="atlas-server", daemon=True)
        self._thread.start()
        return self

    @property
    def port(self):
        return self._httpd.server_address[1] if self._httpd else None

    @property
    def url(self):
        return "http://127.0.0.1:%d/?k=%s" % (self.port, self.token)

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


class _Handler(BaseHTTPRequestHandler):
    owner = None
    server_version = "CortexAtlas"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):                      # no per-request noise in the terminal
        pass

    # -- helpers -------------------------------------------------------------------------

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                         "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        port = self.owner.port
        return host in ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def _key_ok(self, query):
        supplied = self.headers.get("X-Atlas-Key") or (query.get("k") or [""])[0]
        return hmac.compare_digest(supplied.encode("utf-8"), self.owner.token.encode("utf-8"))

    # -- routes --------------------------------------------------------------------------

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method):
        owner = self.owner
        owner.last_request = time.time()
        url = urlparse(self.path)
        query = parse_qs(url.query, keep_blank_values=True)
        path = url.path
        if not self._host_ok():
            return self._json(403, {"error": "unexpected Host header"})
        # The two scripts are this program's own source: no project data in them, and a <script src>
        # cannot carry a header. The page and every API route need the key.
        if path not in _PUBLIC and not self._key_ok(query):
            return self._json(401, {"error": "missing or wrong key"})
        try:
            if path in _STATIC and method == "GET":
                name, ctype = _STATIC[path]
                return self._send(200, _read_static(name), ctype)
            if path == "/api/ping" and method == "GET":
                return self._json(200, {"ok": True, "uptime": int(time.time() - owner.started)})
            if path == "/api/overview" and method == "GET":
                return self._json(200, owner.atlas.overview())
            if path == "/api/status" and method == "GET":
                return self._json(200, owner.atlas.status())
            if path == "/api/refresh" and method == "POST":           # the only action: rebuild the cache
                return self._json(200, owner.atlas.overview())
            if path == "/api/symbols" and method == "GET":
                return self._json(200, owner.atlas.symbols(_arg(query, "file")))
            if path == "/api/memory" and method == "GET":
                found = owner.atlas.memory(_arg(query, "id"))
                return self._json(200, found) if found else self._json(404, {"error": "no such memory"})
            if path == "/api/search" and method == "GET":
                return self._json(200, {"results": owner.atlas.search(_arg(query, "q"))})
        except Exception as exc:                                       # report, do not crash the server
            return self._json(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
        return self._json(404 if method == "GET" else 405, {"error": "not found"})


def _arg(query, name):
    return (query.get(name) or [""])[0][:_MAX_QUERY]
