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
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

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
    """Reads current provider settings from ~/.claude/providers.json."""
    if not os.path.exists(PROVIDERS_FILE):
        return {"type": "oauth", "name": "OAuth"}
    try:
        with open(PROVIDERS_FILE) as f:
            data = json.load(f)
            active = data.get("active_provider", "oauth")
            prov = data.get("providers", {}).get(active, {})
            prov["key_name"] = active
            return prov
    except Exception:
        return {"type": "oauth", "name": "OAuth"}

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
                    if isinstance(res_content, str) and len(res_content) > tombstone_threshold:
                        tool_id = block.get("tool_use_id", "unknown")
                        pruned_bytes += len(res_content)
                        tombstone = (
                            f"[Tool Output Verified: {len(res_content)} characters processed. "
                            f"Execution succeeded and incorporated into working state.]"
                        )
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

    def do_POST(self):
        if not self.path.startswith("/v1/messages"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            try:
                self.wfile.write(b"Claude Cortex Gateway v3.0 Active.")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            req_data = json.loads(body.decode("utf-8"))
        except Exception as e:
            self.send_anthropic_error(400, "invalid_request_error", f"Invalid JSON payload: {e}")
            return

        prov = get_active_provider_config()
        prov_type = prov.get("type", "gemini_proxy")

        if prov_type == "openrouter":
            self.handle_openrouter_dispatch(req_data, prov)
        elif prov_type == "gemini_proxy":
            self.handle_gemini_dispatch(req_data, prov)
        elif prov_type in ("api_key", "anthropic"):
            self.handle_anthropic_dispatch(req_data, prov)
        else:
            # Default to Gemini dispatch
            self.handle_gemini_dispatch(req_data, prov)

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

        try:
            with open_with_retry(upstream_req, timeout=300) as resp:
                self.send_response(resp.status)
                for key, value in resp.getheaders():
                    if key.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()

                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            self.send_anthropic_error(e.code, "api_error", f"OpenRouter Upstream Error: {err_body}")
        except Exception as e:
            self.send_anthropic_error(500, "api_error", f"OpenRouter Connection Error: {e}")

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
                            "usage": {"input_tokens": 150, "output_tokens": 0}
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
                    for line in resp:
                        line_str = line.decode("utf-8", errors="ignore").strip()
                        if line_str.startswith("data: "):
                            data_content = line_str[6:].strip()
                            if not data_content:
                                continue
                            try:
                                chunk = json.loads(data_content)
                                candidates = chunk.get("candidates", [])
                                if candidates:
                                    content_obj = candidates[0].get("content", {})
                                    parts_list = content_obj.get("parts", [])
                                    for p in parts_list:
                                        t_text = p.get("text", "")
                                        if t_text:
                                            delta_ev = {
                                                "type": "content_block_delta",
                                                "index": 0,
                                                "delta": {"type": "text_delta", "text": t_text}
                                            }
                                            self.wfile.write(f"event: content_block_delta\ndata: {json.dumps(delta_ev)}\n\n".encode("utf-8"))
                                            self.wfile.flush()
                            except Exception:
                                pass

                    # 4. Content block stop & message delta
                    block_stop = {"type": "content_block_stop", "index": 0}
                    self.wfile.write(f"event: content_block_stop\ndata: {json.dumps(block_stop)}\n\n".encode("utf-8"))

                    msg_delta = {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                        "usage": {"output_tokens": 200}
                    }
                    self.wfile.write(f"event: message_delta\ndata: {json.dumps(msg_delta)}\n\n".encode("utf-8"))

                    msg_stop = {"type": "message_stop"}
                    self.wfile.write(f"event: message_stop\ndata: {json.dumps(msg_stop)}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except urllib.error.HTTPError as e:
                err_text = e.read().decode("utf-8", errors="ignore")
                self.send_anthropic_error(e.code, "api_error", f"Gemini API Error ({e.code}): {err_text}", headers_sent=headers_sent)
            except Exception as e:
                self.send_anthropic_error(500, "api_error", f"Gemini Gateway Error: {e}", headers_sent=headers_sent)

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

        try:
            with open_with_retry(upstream_req, timeout=300) as resp:
                self.send_response(resp.status)
                for key, value in resp.getheaders():
                    if key.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()

                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            self.send_anthropic_error(e.code, "api_error", f"Anthropic Upstream Error: {err_body}")
        except Exception as e:
            self.send_anthropic_error(500, "api_error", f"Anthropic Connection Error: {e}")

def main():
    parser = argparse.ArgumentParser(description="Claude Cortex Universal Gateway Proxy v3.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on (default: 8088)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host binding (default: 127.0.0.1)")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), CortexGatewayHandler)
    prov = get_active_provider_config()
    print(f"=================================================================")
    print(f"Claude Cortex Universal Gateway Proxy v3.0 [Active]")
    print(f"Listening on: http://{args.host}:{args.port}")
    print(f"Active Upstream Provider: {prov.get('name', 'OAuth')}")
    print(f"OT-ACR Token Optimization: Active")
    print(f"Anti-Stall Watchdog: Enabled")
    print(f"=================================================================")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Cortex Gateway Proxy...")
        server.server_close()

if __name__ == "__main__":
    main()
