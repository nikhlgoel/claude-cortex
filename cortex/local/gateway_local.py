"""The local route of the Cortex gateway: Claude Code -> llama-server.

``scripts/cortex-gateway.py`` hands requests here when it runs in local mode. The
logic lives in this importable module (not the script) so it can be tested against a
fake upstream with no model and no network.

What it does that a plain pass-through would not (each fixes a verified failure):

* Requires the bearer token - a loopback port is still reachable by every local
  program, and an unauthenticated model server is a free compute/exfil endpoint.
* Shapes the request (``shaping.shape_request``).
* Streams SSE line by line, never ``read(4096)``, which holds small events back for a
  full buffer (a 3 s delay was measured).
* Sends ``event: ping`` while the model is silent during prompt prefill; without it
  Claude Code's idle watchdog aborts a long first-token wait.
* Turns a context overflow into the "Prompt is too long" error Claude Code compacts on.
* Answers ``/v1/messages/count_tokens`` instead of treating it as an inference.
* Limits concurrent requests to what the server was started for.
* Logs one metadata line per request (never prompt text) for tuning the reasoning table.
"""

from __future__ import annotations

import hmac
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import shaping, store

CHUNK_WAIT = 0.25            # worker poll granularity, seconds
MAX_ERROR_TEXT = 600


class LocalRoute:
    def __init__(self, cfg, model_entry, token, upstream_base=None, event_log=None):
        self.cfg = cfg
        self.entry = model_entry
        self.token = token
        self.upstream = upstream_base or f"http://127.0.0.1:{cfg['ports']['server']}"
        self.levels = cfg["reasoning"]["levels"]
        self.default_effort = cfg["reasoning"].get("default_effort")
        gw = cfg["gateway"]
        self.ping_after = float(gw.get("ping_after_s", 10))
        self.ping_every = float(gw.get("ping_every_s", 10))
        self.n_ctx = None
        self.semaphore = threading.BoundedSemaphore(max(1, int(gw.get("max_concurrent", 1))))
        self.event_log = event_log if gw.get("log_requests", True) else None
        self.active = 0
        self.last_activity = time.monotonic()
        self._lock = threading.Lock()
        #: Callable that starts the model server; set by ``build``. None = never auto-start.
        self.wake = None
        self._wake_lock = threading.Lock()

    # ------------------------------------------------------------------ auth

    def authorized(self, headers):
        """True when the request carries the token as ``Authorization: Bearer`` or ``x-api-key``."""
        if not self.token:
            return False                       # no token configured: fail closed
        given = headers.get("x-api-key") or ""
        auth = headers.get("Authorization") or headers.get("authorization") or ""
        if not given and auth.lower().startswith("bearer "):
            given = auth[7:].strip()
        return hmac.compare_digest(given.encode("utf-8"), self.token.encode("utf-8"))

    # --------------------------------------------------------------- activity

    def _begin(self):
        with self._lock:
            self.active += 1
            self.last_activity = time.monotonic()

    def _end(self):
        with self._lock:
            self.active -= 1
            self.last_activity = time.monotonic()

    def idle_seconds(self):
        with self._lock:
            return 0.0 if self.active else time.monotonic() - self.last_activity

    def _log(self, **fields):
        if not self.event_log:
            return
        fields["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            os.makedirs(os.path.dirname(self.event_log), exist_ok=True)
            with open(self.event_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(fields) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------ count_tokens

    def count_tokens(self, handler, req):
        """Answer ``/v1/messages/count_tokens``: ask the server, else estimate.

        A 404 here makes Claude Code fall back to its own (poor) estimate, and sending
        it to the inference route would run - and bill - a full generation.
        """
        shaped, _info = shaping.shape_request(req, self.entry, self.levels, self.default_effort)
        shaped.pop("stream", None)
        count = None
        try:
            with urllib.request.urlopen(self._request(f"{self.upstream}/v1/messages/count_tokens", shaped),
                                        timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data.get("input_tokens"), int):
                    count = data["input_tokens"]
        except urllib.error.HTTPError as exc:
            exc.close()                   # e.g. a 404 from a build with no count endpoint
        except (urllib.error.URLError, OSError, ValueError):
            pass
        exact = count is not None
        if count is None:
            count = shaping.estimate_tokens(shaped)
        body = json.dumps({"input_tokens": count}).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("X-Cortex-Count", "exact" if exact else "estimate")
        handler.end_headers()
        handler.wfile.write(body)

    # ----------------------------------------------------------------- upstream

    def _request(self, url, payload):
        return urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}",
                     "x-api-key": self.token, "anthropic-version": "2023-06-01"})

    def _worker(self, payload, out, cancel):
        """Open the upstream request and push events onto ``out``; never raises.

        ``cancel`` is set when the client has gone. Leaving the ``with`` block closes the
        upstream connection, which makes llama-server abort the generation instead of
        finishing a response nobody will read.
        """
        woke = False
        while True:
            try:
                with self.semaphore:
                    if cancel.is_set():
                        return
                    with urllib.request.urlopen(self._request(f"{self.upstream}/v1/messages", payload),
                                                timeout=1800) as resp:
                        out.put(("open", resp.status, resp.headers.get("Content-Type", "application/json")))
                        while not cancel.is_set():
                            line = resp.readline()
                            if not line:
                                break
                            out.put(("chunk", line))
                out.put(("end",))
                return
            except urllib.error.HTTPError as exc:
                try:
                    text = exc.read().decode("utf-8", errors="replace")
                except OSError:
                    text = ""
                finally:
                    exc.close()                    # an HTTPError holds the socket open until closed
                out.put(("http_error", exc.code, text))
                return
            except (urllib.error.URLError, OSError) as exc:
                refused = isinstance(getattr(exc, "reason", exc), ConnectionError)
                if refused and self.wake and not woke and not cancel.is_set():
                    # The model was put to sleep after a quiet spell (it frees VRAM and RAM).
                    # Wake it once and retry; the client is kept alive with pings meanwhile.
                    woke = True
                    try:
                        self._wake_model()
                    except Exception as wake_error:
                        out.put(("error", f"the local model was asleep and could not be started: "
                                          f"{wake_error}"))
                        return
                    continue
                out.put(("error", f"the local model server is not reachable ({exc}). "
                                  f"Start it with: cc local serve"))
                return
            except Exception as exc:                       # never leave the client hanging
                out.put(("error", f"unexpected gateway error: {exc}"))
                return

    def _server_up(self):
        try:
            with urllib.request.urlopen(f"{self.upstream}/health", timeout=3) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as exc:
            exc.close()
            return False
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _wake_model(self):
        """Start the model server if it is not up. One caller does it; the rest wait and reuse."""
        with self._wake_lock:
            if not self._server_up():
                self.wake()

    # ------------------------------------------------------------------ messages

    def messages(self, handler, req):
        """Forward one ``/v1/messages`` request. Handles streaming and plain JSON."""
        started = time.monotonic()
        shaped, info = shaping.shape_request(req, self.entry, self.levels, self.default_effort)
        stream = bool(shaped.get("stream"))
        out = queue.Queue()
        cancel = threading.Event()
        self._begin()
        status = None
        try:
            threading.Thread(target=self._worker, args=(shaped, out, cancel), daemon=True).start()
            status = self._pump(handler, out, stream)
        finally:
            cancel.set()
            self._end()
            self._log(path="/v1/messages", stream=stream, status=status,
                      ms=int((time.monotonic() - started) * 1000),
                      effort=info["effort"], turn=info["turn"], budget=info["budget"],
                      template=info["template"], messages=len(req.get("messages", [])),
                      chars=len(json.dumps(req.get("messages", []), default=str)))

    def _pump(self, handler, out, stream):
        """Relay worker events to the client, pinging while the model is silent."""
        sent = False
        in_event = False
        status = None
        deadline = time.monotonic() + self.ping_after

        def begin(code, ctype):
            nonlocal sent
            handler.send_response(code)
            handler.send_header("Content-Type", ctype)
            handler.send_header("Cache-Control", "no-cache")
            handler.send_header("Connection", "close")
            handler.end_headers()
            sent = True

        while True:
            try:
                event = out.get(timeout=CHUNK_WAIT)
            except queue.Empty:
                if stream and not in_event and time.monotonic() >= deadline:
                    try:
                        if not sent:
                            begin(200, "text/event-stream")
                        handler.wfile.write(b'event: ping\ndata: {"type": "ping"}\n\n')
                        handler.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return status
                    deadline = time.monotonic() + self.ping_every
                continue

            kind = event[0]
            try:
                if kind == "open":
                    status = event[1]
                    if not sent:
                        begin(event[1], event[2])
                elif kind == "chunk":
                    handler.wfile.write(event[1])
                    handler.wfile.flush()
                    in_event = event[1].strip() != b""
                    deadline = time.monotonic() + self.ping_every
                elif kind == "end":
                    return status
                elif kind == "http_error":
                    self._upstream_error(handler, event[1], event[2], sent)
                    return event[1]
                else:                                   # "error"
                    handler.send_anthropic_error(502, "api_error", event[1], headers_sent=sent)
                    return 502
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return status                            # client went away; nobody to tell

    def _upstream_error(self, handler, code, text, headers_sent):
        if shaping.is_overflow(code, text):
            message = shaping.overflow_error(self.n_ctx)["error"]["message"]
            handler.send_anthropic_error(400, "invalid_request_error", message, headers_sent=headers_sent)
            return
        kind = {400: "invalid_request_error", 401: "authentication_error", 403: "permission_error",
                404: "not_found_error", 429: "rate_limit_error"}.get(code, "api_error")
        handler.send_anthropic_error(code, kind, f"local model server: {text[:MAX_ERROR_TEXT]}",
                                     headers_sent=headers_sent)


def sleep_model_if_idle(route, is_running, stop):
    """Free the model's VRAM/RAM after ``idle_stop_minutes`` of silence. Returns True if it did.

    Only the MODEL sleeps. The gateway stays up (it costs almost nothing) so the client's
    connection never breaks, and the next request wakes the model on demand.
    """
    minutes = route.cfg.get("idle_stop_minutes") or 0
    if minutes <= 0 or route.idle_seconds() < minutes * 60 or not is_running():
        return False
    stop()
    return True


def build(model_id=None):
    """Construct the route from on-disk config. Used by the gateway at startup."""
    from . import serve                                  # late: avoids an import cycle
    cfg, _status = store.load()
    model_id = model_id or os.environ.get("CORTEX_LOCAL_MODEL") or cfg.get("active_model")
    entry = serve.entry_for(model_id, cfg)
    route = LocalRoute(cfg, entry, store.token(create=False),
                       event_log=os.path.join(store.logs_dir(), "gateway-events.jsonl"))
    installed = (cfg.get("models") or {}).get(model_id) or {}
    route.n_ctx = installed.get("ctx") or entry["ctx"][0]
    route.wake = lambda: serve.start_server(cfg, model_id)
    return route, model_id
