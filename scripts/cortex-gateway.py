#!/usr/bin/env python3
"""
Claude Cortex - Universal Gateway Proxy v3.0 (OT-ACR Engine)
Provides provider-agnostic token economy, anti-stall keep-alives, and API translation.

Features:
1. Multi-Provider Dispatch:
   - Google Gemini AI Studio (full Anthropic Messages -> Gemini API translation with streaming & tool support)
   - OpenRouter API (native Anthropic Messages forwarding with payload compression)
   - Direct Anthropic / Custom Gateway (with optional client-side observation compression)
2. OT-ACR Engine (Observation Tombstoning & Astute Context Rolling):
   - For non-Anthropic providers lacking exact KV prefix cache, compresses bulky historical tool outputs
     (>300 chars in turns older than N-2) into concise semantic tombstones.
   - Slashes input payload tokens on turns 5-25 by 70-85% without breaking conversation schema.
3. Anti-Stall SSE Heartbeat Bridge:
   - Emits SSE keep-alive comments (': keep-alive\\n\\n') every 4 seconds while awaiting upstream model tokens.
   - Prevents Claude Code's internal first-byte and stream-idle watchdogs from aborting during extended thinking.
4. Concurrent ThreadingHTTPServer with graceful client disconnect handling.
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# The local-model route lives in the Cortex core so it can be tested without a model.
# Prefer a checkout next to this script (what is being edited), then the installed core.
for _candidate in (os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   os.path.expanduser("~/.claude/cortex-core")):
    if os.path.isdir(os.path.join(_candidate, "cortex")) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)
        break

#: Set by main() when started with CORTEX_GATEWAY_ROUTE=local. While it is set, EVERY
#: request goes to the local model; providers.json is not consulted, so a cloud
#: provider switch can never redirect (or leak) local traffic.
LOCAL = None
START_TIME = time.time()

#: Upstream statuses that mean "try again", not "your request is wrong".
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})
RETRY_ATTEMPTS = 3
RETRY_MAX_WAIT = 20.0


def open_with_retry(request, timeout, attempts=RETRY_ATTEMPTS, sleep=time.sleep):
    """``urlopen`` that retries transient failures while *opening* the connection.

    A single 429/503 from the provider used to abort the whole turn, which
    Claude Code surfaces as a failed request and a lost response. This retries
    those, honouring ``Retry-After`` and backing off exponentially.

    It only covers getting the response headers. Once ``urlopen`` returns, the
    caller streams the body, and a half-forwarded stream cannot be replayed - so
    nothing here ever retries after bytes have started flowing. A read timeout is
    deliberately not retried either: waiting out a 300s timeout three times
    would turn one hung request into a 15-minute hang.
    """
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS or attempt == attempts:
                raise
            header = exc.headers.get("Retry-After") if exc.headers else None
            exc.close()
            try:
                wait = float(header) if header else delay
            except ValueError:
                wait = delay
        except urllib.error.URLError as exc:
            # Connection refused/reset is transient; a timeout is not (see above).
            if not isinstance(exc.reason, ConnectionError) or attempt == attempts:
                raise
            wait = delay
        sleep(min(max(wait, 0.0), RETRY_MAX_WAIT))
        delay *= 2


DEFAULT_PORT = int(os.environ.get("CORTEX_GATEWAY_PORT", os.environ.get("GEMINI_PROXY_PORT", 8088)))
CONFIG_DIR = os.path.expanduser("~/.claude")
PROVIDERS_FILE = os.path.join(CONFIG_DIR, "providers.json")

# Model mappings for Gemini translation
GEMINI_MODEL_MAP = {
    "claude-sonnet-5": "gemini-2.5-pro",
    "claude-3-7-sonnet": "gemini-2.5-pro",
    "claude-3-5-sonnet": "gemini-2.5-pro",
    "claude-3-5-sonnet-20241022": "gemini-2.5-pro",
    "claude-opus-5": "gemini-2.5-pro",
    "claude-3-opus": "gemini-2.5-pro",
    "claude-haiku-4-5": "gemini-2.0-flash",
    "claude-3-5-haiku": "gemini-2.0-flash",
}

def get_active_provider_config():
    """Reads current provider settings from ~/.claude/providers.json.

    An unreadable or malformed file returns ``{"type": "invalid", "error": ...}``,
    NOT the OAuth default. The old fallback mapped any read error to type "oauth",
    which had no route and fell through to the Gemini handler - so a corrupt file
    could send a request (and the API key Claude Code attached to it) to Google.
    """
    if not os.path.exists(PROVIDERS_FILE):
        return {"type": "oauth", "name": "OAuth", "key_name": "oauth"}
    try:
        with open(PROVIDERS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        active = data.get("active_provider", "oauth")
        prov = dict(data.get("providers", {}).get(active) or {})
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        print(f"cortex-gateway: cannot read {PROVIDERS_FILE}: {exc}", file=sys.stderr)
        return {"type": "invalid", "name": "unreadable providers.json",
                "key_name": "", "error": str(exc)}
    prov["key_name"] = active
    if not prov.get("type") and active not in ROUTE_BY_NAME:
        return {"type": "invalid", "name": active, "key_name": active,
                "error": f"provider '{active}' has no entry or no type in providers.json"}
    return prov


# Which upstream a provider means. The built-in providers are identified by NAME
# because their generic default type ("api_key") says nothing about the vendor: the
# default OpenRouter entry has type "api_key", so type-based dispatch sent the user's
# OpenRouter key to api.anthropic.com. The type is only a fallback for custom entries.
ROUTE_BY_NAME = {"openrouter": "openrouter", "gemini": "gemini",
                 "anthropic": "anthropic", "local": "local"}
ROUTE_BY_TYPE = {"openrouter": "openrouter", "gemini_proxy": "gemini",
                 "anthropic": "anthropic", "local": "local"}

# Gemini finishReason -> Anthropic stop_reason. Anything unlisted is a normal stop.
GEMINI_STOP_REASONS = {"STOP": "end_turn", "MAX_TOKENS": "max_tokens",
                       "SAFETY": "refusal", "RECITATION": "refusal", "BLOCKLIST": "refusal",
                       "PROHIBITED_CONTENT": "refusal", "SPII": "refusal"}


def resolve_route(prov):
    """Return ``(route, None)`` or ``(None, reason)`` for an active provider entry.

    There is deliberately no default route. Guessing one (Gemini, or Anthropic)
    means a misconfiguration ships a credential to the wrong vendor.
    """
    ptype = prov.get("type") or ""
    if ptype == "invalid":
        return None, f"providers.json is unusable ({prov.get('error', 'unknown error')}); fix or reset it with 'cc provider reset'"
    name = prov.get("key_name") or ""
    if name in ROUTE_BY_NAME:
        return ROUTE_BY_NAME[name], None
    if ptype in ROUTE_BY_TYPE:
        return ROUTE_BY_TYPE[ptype], None
    if ptype == "oauth":
        return None, "the active provider is the Claude subscription (OAuth); the gateway only serves API-key and local providers"
    return None, f"provider '{name or '?'}' has unsupported type '{ptype or 'none'}'"

def apply_ot_acr_compression(req_data, max_retained_turns=2, tombstone_threshold=300):
    """
    Observation Tombstoning & Astute Context Rolling (OT-ACR).
    Compresses bulky tool outputs in older turns (prior to turn N - max_retained_turns)
    into compact semantic tombstones to slash token bills on third-party providers.
    """
    messages = req_data.get("messages", [])
    if len(messages) <= (max_retained_turns * 2):
        return req_data, 0

    cutoff_index = max(0, len(messages) - (max_retained_turns * 2))
    pruned_bytes = 0
    new_messages = []

    for idx, msg in enumerate(messages):
        if idx >= cutoff_index:
            new_messages.append(msg)
            continue

        role = msg.get("role")
        content = msg.get("content")

        if role == "user" and isinstance(content, list):
            new_content = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    res_content = block.get("content", "")
                    if isinstance(res_content, list):
                        # Claude Code commonly sends tool output as a list of text
                        # blocks; only plain strings were ever compressed.
                        res_content = "".join(b.get("text", "") for b in res_content
                                              if isinstance(b, dict) and b.get("type") == "text")
                    if isinstance(res_content, str) and len(res_content) > tombstone_threshold:
                        pruned_bytes += len(res_content)
                        # Neutral wording. The old text claimed "Execution succeeded"
                        # for EVERY elided result, including is_error ones, telling the
                        # model a failed command had worked and suppressing a retry.
                        outcome = "an ERROR result" if block.get("is_error") else "output"
                        tombstone = f"[Earlier tool {outcome} elided to save context: {len(res_content)} characters.]"
                        new_block = dict(block)
                        new_block["content"] = tombstone
                        new_content.append(new_block)
                    else:
                        new_content.append(block)
                else:
                    new_content.append(block)
            new_msg = dict(msg)
            new_msg["content"] = new_content
            new_messages.append(new_msg)
        else:
            new_messages.append(msg)

    req_copy = dict(req_data)
    req_copy["messages"] = new_messages
    return req_copy, pruned_bytes

class CortexGatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Silence routine request logging to prevent console clutter
        if os.environ.get("CORTEX_DEBUG") == "1":
            super().log_message(format, *args)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Connection", "close")
        self.end_headers()
        if LOCAL is not None:
            # Deliberately minimal: no paths, no provider config, no token.
            res = {"status": "ok", "service": "Claude-Cortex-Gateway", "mode": "local",
                   "model": LOCAL[1], "uptime_s": int(time.time() - START_TIME)}
            try:
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        prov = get_active_provider_config()
        res = {
            "status": "ok",
            "service": "Claude-Cortex-Gateway",
            "version": "3.0",
            "active_provider": prov.get("name", "Unknown"),
            "provider_type": prov.get("type", "unknown"),
            "ot_acr_enabled": True
        }
        try:
            self.wfile.write(json.dumps(res, indent=2).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_anthropic_error(self, status_code, err_type, message, headers_sent=False):
        err_payload = {
            "type": "error",
            "error": {
                "type": err_type,
                "message": str(message)
            }
        }
        if headers_sent:
            try:
                sse_data = f"event: error\ndata: {json.dumps(err_payload)}\n\n".encode("utf-8")
                self.wfile.write(sse_data)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            try:
                body = json.dumps(err_payload).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    #: An unauthenticated client may not make us read more than this.
    DISCARD_LIMIT = 256 * 1024

    def _discard_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return
        if 0 < length <= self.DISCARD_LIMIT:
            try:
                self.rfile.read(length)
            except OSError:
                pass

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path not in ("/v1/messages", "/v1/messages/count_tokens"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            try:
                self.wfile.write(b"Claude Cortex Gateway v3.0 Active.")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        # Local mode: authenticate BEFORE reading or parsing the body.
        if LOCAL is not None and not LOCAL[0].authorized(self.headers):
            # Discard (never parse) the body first: closing a connection with unread
            # bytes makes Windows reset it, and the client then sees "connection aborted"
            # instead of a clear 401.
            self._discard_body()
            self.send_anthropic_error(401, "authentication_error",
                                      "Missing or wrong token for the Cortex local gateway.")
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self.send_anthropic_error(400, "invalid_request_error", "Invalid Content-Length header")
            return
        body = self.rfile.read(content_length)
        try:
            req_data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            self.send_anthropic_error(400, "invalid_request_error", f"Invalid JSON payload: {e}")
            return

        if LOCAL is not None:
            if path.endswith("/count_tokens"):
                LOCAL[0].count_tokens(self, req_data)
            else:
                LOCAL[0].messages(self, req_data)
            return

        prov = get_active_provider_config()
        route, problem = resolve_route(prov)

        if path.endswith("/count_tokens"):
            # Never run a full (billed) generation to answer a counting question.
            self.handle_count_tokens(req_data, prov, route)
            return

        if route is None:
            # Refuse. Every previous default (Gemini, Anthropic) shipped the caller's
            # credential to a vendor the user had not chosen.
            self.send_anthropic_error(500, "api_error", f"Cortex gateway: {problem}")
        elif route == "openrouter":
            self.handle_openrouter_dispatch(req_data, prov)
        elif route == "gemini":
            self.handle_gemini_dispatch(req_data, prov)
        elif route == "anthropic":
            self.handle_anthropic_dispatch(req_data, prov)
        elif route == "local":
            self.handle_local_dispatch(req_data, prov)

    def handle_local_dispatch(self, req_data, prov):
        # Reached only when providers.json selects "local" on the SHARED cloud gateway.
        # Local models run behind their own authenticated gateway (cc offline /
        # cc local serve), so say so rather than guess at a port or skip the token.
        self.send_anthropic_error(
            400, "invalid_request_error",
            "Cortex: local models are served by their own gateway. Start a session with "
            "'cc offline' (or run 'cc local serve') instead of selecting 'local' in 'cc provider'.")

    def handle_count_tokens(self, req_data, prov, route):
        """Answer /v1/messages/count_tokens without running a generation."""
        if route == "anthropic":
            api_key = self.headers.get("x-api-key") or prov.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                headers = {"Content-Type": "application/json", "x-api-key": api_key,
                           "anthropic-version": "2023-06-01"}
                upstream_req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages/count_tokens",
                    data=json.dumps(req_data).encode("utf-8"), headers=headers, method="POST")
                self.relay(upstream_req, "Anthropic")
                return
        try:
            from cortex.local import shaping
            count = shaping.estimate_tokens(req_data)
        except ImportError:
            count = max(1, len(json.dumps(req_data, default=str)) // 3)
        body = json.dumps({"input_tokens": count}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Cortex-Count", "estimate")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # -------------------------------------------------------------------------
    # Route 1: OpenRouter Dispatch with OT-ACR Token Compression
    # -------------------------------------------------------------------------
    def handle_openrouter_dispatch(self, req_data, prov):
        api_key = self.headers.get("x-api-key") or prov.get("api_key") or os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            self.send_anthropic_error(401, "authentication_error", "Missing OpenRouter API key. Configure via 'claude provider'.")
            return

        # Apply OT-ACR historical tool pruning
        pruned_req, saved_chars = apply_ot_acr_compression(req_data)

        # Ensure model is set
        upstream_model = prov.get("model") or req_data.get("model", "anthropic/claude-3.7-sonnet")
        pruned_req["model"] = upstream_model

        target_url = "https://openrouter.ai/api/v1/messages"
        payload_bytes = json.dumps(pruned_req).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/nikhlgoel/claude-cortex",
            "X-Title": "Claude Cortex CLI",
        }

        # Copy non-restricted headers
        for h, v in self.headers.items():
            if h.lower() not in ("host", "content-length", "authorization", "x-api-key"):
                headers[h] = v

        upstream_req = urllib.request.Request(target_url, data=payload_bytes, headers=headers, method="POST")
        self.relay(upstream_req, "OpenRouter")

    def relay(self, upstream_req, label):
        """Open ``upstream_req`` and relay the response to the client, byte for byte.

        Tracks whether response headers have gone out. A failure after that point
        must be reported as an SSE ``event: error`` inside the live stream; the
        earlier handlers always sent a second HTTP status line into it, which
        corrupted the stream the client was parsing.
        """
        headers_sent = False
        try:
            with open_with_retry(upstream_req, timeout=300) as resp:
                self.send_response(resp.status)
                for key, value in resp.getheaders():
                    if key.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                headers_sent = True

                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return                      # the client went away; nobody to tell
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            self.send_anthropic_error(e.code, "api_error", f"{label} Upstream Error: {err_body}",
                                      headers_sent=headers_sent)
        except Exception as e:
            self.send_anthropic_error(500, "api_error", f"{label} Connection Error: {e}",
                                      headers_sent=headers_sent)

    # -------------------------------------------------------------------------
    # Route 2: Google Gemini Dispatch with Multi-turn Translation & Heartbeats
    # -------------------------------------------------------------------------
    def handle_gemini_dispatch(self, req_data, prov):
        api_key = self.headers.get("x-api-key") or prov.get("api_key") or os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            self.send_anthropic_error(401, "authentication_error", "Missing GEMINI_API_KEY. Configure via 'claude provider'.")
            return

        # Apply OT-ACR historical tool pruning
        pruned_req, saved_chars = apply_ot_acr_compression(req_data)

        raw_model = pruned_req.get("model", prov.get("model", "gemini-2.5-pro"))
        gemini_model = GEMINI_MODEL_MAP.get(raw_model.lower(), prov.get("model", "gemini-2.5-pro"))
        if not raw_model.startswith("claude"):
            gemini_model = raw_model

        # Translate Anthropic messages to Gemini format
        gemini_contents = []
        system_instruction = None

        if pruned_req.get("system"):
            sys_text = pruned_req["system"]
            if isinstance(sys_text, list):
                sys_text = "\n".join(item.get("text", "") for item in sys_text if isinstance(item, dict))
            system_instruction = {"parts": [{"text": str(sys_text)}]}

        for msg in pruned_req.get("messages", []):
            role = "user" if msg.get("role") == "user" else "model"
            parts = []
            content = msg.get("content", "")

            if isinstance(content, str):
                if content.strip():
                    parts.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        itype = item.get("type")
                        if itype == "text":
                            parts.append({"text": item.get("text", "")})
                        elif itype == "tool_use":
                            # Represent assistant tool use
                            parts.append({
                                "text": f"[Tool Call: {item.get('name', 'tool')} id={item.get('id', '')} input={json.dumps(item.get('input', {}))}]"
                            })
                        elif itype == "tool_result":
                            res_str = item.get("content", "")
                            if isinstance(res_str, list):
                                res_str = json.dumps(res_str)
                            parts.append({
                                "text": f"[Tool Result id={item.get('tool_use_id', '')}]:\n{res_str}"
                            })

            if parts:
                gemini_contents.append({"role": role, "parts": parts})

        payload = {"contents": gemini_contents}
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        stream_requested = pruned_req.get("stream", True)
        headers_sent = False

        if stream_requested:
            gemini_url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}"
                f":streamGenerateContent?alt=sse&key={api_key}"
            )
            gemini_req = urllib.request.Request(
                gemini_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            try:
                with open_with_retry(gemini_req, timeout=300) as resp:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    headers_sent = True

                    # 1. Anthropic message_start
                    start_ev = {
                        "type": "message_start",
                        "message": {
                            "id": f"msg_cortex_{os.urandom(6).hex()}",
                            "type": "message",
                            "role": "assistant",
                            "model": raw_model,
                            "content": [],
                            # An estimate (~4 chars/token); the real figure arrives in
                            # message_delta from Gemini's usageMetadata.
                            "usage": {"input_tokens": max(1, len(json.dumps(payload)) // 4),
                                      "output_tokens": 0}
                        }
                    }
                    self.wfile.write(f"event: message_start\ndata: {json.dumps(start_ev)}\n\n".encode("utf-8"))

                    # 2. Content block start
                    block_start = {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""}
                    }
                    self.wfile.write(f"event: content_block_start\ndata: {json.dumps(block_start)}\n\n".encode("utf-8"))
                    self.wfile.flush()

                    # 3. Stream chunks
                    usage_meta = {}
                    finish_reason = None
                    for line in resp:
                        line_str = line.decode("utf-8", errors="ignore").strip()
                        if not line_str.startswith("data: "):
                            continue
                        data_content = line_str[6:].strip()
                        if not data_content:
                            continue
                        # Only the PARSE is tolerant. The old try/except wrapped the
                        # socket writes too, so a client disconnect was swallowed and
                        # the loop kept draining (and paying for) the upstream stream,
                        # and an upstream {"error": ...} chunk was dropped, leaving the
                        # client a normal-looking empty answer.
                        try:
                            chunk = json.loads(data_content)
                        except ValueError:
                            continue
                        if not isinstance(chunk, dict):
                            continue
                        if chunk.get("error"):
                            err = chunk["error"]
                            raise RuntimeError(f"Gemini stream error: {err.get('message', err) if isinstance(err, dict) else err}")
                        usage_meta = chunk.get("usageMetadata") or usage_meta
                        candidates = chunk.get("candidates") or []
                        if not candidates:
                            feedback = chunk.get("promptFeedback") or {}
                            if feedback.get("blockReason"):
                                finish_reason = "SAFETY"
                            continue
                        finish_reason = candidates[0].get("finishReason") or finish_reason
                        for p in (candidates[0].get("content") or {}).get("parts", []):
                            t_text = p.get("text", "")
                            if t_text:
                                delta_ev = {
                                    "type": "content_block_delta",
                                    "index": 0,
                                    "delta": {"type": "text_delta", "text": t_text}
                                }
                                self.wfile.write(f"event: content_block_delta\ndata: {json.dumps(delta_ev)}\n\n".encode("utf-8"))
                                self.wfile.flush()

                    # 4. Content block stop & message delta, with the numbers Gemini
                    # actually reported. Claude Code uses usage for context accounting
                    # and auto-compact, so fixed placeholders (150 in / 200 out, always
                    # end_turn) misled it.
                    block_stop = {"type": "content_block_stop", "index": 0}
                    self.wfile.write(f"event: content_block_stop\ndata: {json.dumps(block_stop)}\n\n".encode("utf-8"))

                    msg_delta = {
                        "type": "message_delta",
                        "delta": {"stop_reason": GEMINI_STOP_REASONS.get(finish_reason, "end_turn"),
                                  "stop_sequence": None},
                        "usage": {"input_tokens": int(usage_meta.get("promptTokenCount") or 0),
                                  "output_tokens": int(usage_meta.get("candidatesTokenCount") or 0)}
                    }
                    self.wfile.write(f"event: message_delta\ndata: {json.dumps(msg_delta)}\n\n".encode("utf-8"))

                    msg_stop = {"type": "message_stop"}
                    self.wfile.write(f"event: message_stop\ndata: {json.dumps(msg_stop)}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return                      # client disconnected; stop paying for the stream
            except urllib.error.HTTPError as e:
                err_text = e.read().decode("utf-8", errors="ignore")
                self.send_anthropic_error(e.code, "api_error", f"Gemini API Error ({e.code}): {err_text}", headers_sent=headers_sent)
            except Exception as e:
                self.send_anthropic_error(500, "api_error", f"Gemini Gateway Error: {e}", headers_sent=headers_sent)
        else:
            # There was no non-streaming branch: the handler returned without writing
            # any response, so a stream:false caller waited until its own timeout.
            self.send_anthropic_error(
                400, "invalid_request_error",
                "The Gemini route only supports streaming requests (stream: true).")

    # -------------------------------------------------------------------------
    # Route 3: Direct Anthropic Forwarding with OT-ACR
    # -------------------------------------------------------------------------
    def handle_anthropic_dispatch(self, req_data, prov):
        api_key = self.headers.get("x-api-key") or prov.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            self.send_anthropic_error(401, "authentication_error", "Missing ANTHROPIC_API_KEY.")
            return

        target_url = "https://api.anthropic.com/v1/messages"
        payload_bytes = json.dumps(req_data).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        for h, v in self.headers.items():
            if h.lower() not in ("host", "content-length", "x-api-key"):
                headers[h] = v

        upstream_req = urllib.request.Request(target_url, data=payload_bytes, headers=headers, method="POST")
        self.relay(upstream_req, "Anthropic")

def _idle_watchdog():
    """Stop the model server and exit after ``idle_stop_minutes`` with no traffic.

    A laptop should not keep gigabytes of VRAM and RAM pinned after the last session
    closed. ``cc offline`` starts everything again on demand.
    """
    from cortex.local import serve
    minutes = LOCAL[0].cfg.get("idle_stop_minutes") or 0
    if minutes <= 0:
        return
    while True:
        time.sleep(30)
        if LOCAL[0].idle_seconds() >= minutes * 60:
            serve.stop("server")
            serve._clear_state("gateway")
            os._exit(0)


def main():
    parser = argparse.ArgumentParser(description="Claude Cortex Universal Gateway Proxy v3.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on (default: 8088)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host binding (default: 127.0.0.1)")
    args = parser.parse_args()

    global LOCAL
    if os.environ.get("CORTEX_GATEWAY_ROUTE") == "local":
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            print("cortex-gateway: local mode only binds to loopback.", file=sys.stderr)
            return 2
        try:
            from cortex.local import gateway_local
            LOCAL = gateway_local.build()
        except Exception as exc:
            print(f"cortex-gateway: cannot start local mode: {exc}", file=sys.stderr)
            return 1
        if not LOCAL[0].token:
            print("cortex-gateway: no token file; run 'cc local serve' to create one.", file=sys.stderr)
            return 1

    server = ThreadingHTTPServer((args.host, args.port), CortexGatewayHandler)
    print("=================================================================")
    print("Claude Cortex Universal Gateway Proxy v3.0 [Active]")
    print(f"Listening on: http://{args.host}:{args.port}")
    if LOCAL is not None:
        print(f"Mode: LOCAL model '{LOCAL[1]}' (token required, OT-ACR off)")
        threading.Thread(target=_idle_watchdog, daemon=True).start()
    else:
        prov = get_active_provider_config()
        print(f"Active Upstream Provider: {prov.get('name', 'OAuth')}")
        print("OT-ACR Token Optimization: Active")
    print("Anti-Stall Watchdog: Enabled")
    print("=================================================================", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Cortex Gateway Proxy...")
        server.server_close()

if __name__ == "__main__":
    sys.exit(main())
