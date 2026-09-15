#!/usr/bin/env python3
"""
Lightweight Anthropic-to-Google Gemini AI Studio Proxy v2.0
Translates Anthropic Messages API requests (/v1/messages) to Google Gemini API
and streams SSE responses (or non-streaming JSON) back to Claude Code CLI.

Features:
- ThreadingHTTPServer for concurrent non-blocking request handling
- Full SSE streaming with graceful client disconnect handling (BrokenPipeError)
- Non-streaming mode support (stream: false)
- Anthropic-compliant JSON error responses for upstream API errors (400, 401, 429, 500)
- Configurable port and model via CLI arguments or environment variables
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

DEFAULT_PORT = int(os.environ.get("GEMINI_PROXY_PORT", 8088))
DEFAULT_KEY = os.environ.get("GEMINI_API_KEY", "")
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")

# Map common Anthropic model aliases to Gemini models
MODEL_MAPPING = {
    "claude-sonnet-5": "gemini-2.5-pro",
    "claude-3-5-sonnet": "gemini-2.5-pro",
    "claude-3-5-sonnet-20241022": "gemini-2.5-pro",
    "claude-opus-5": "gemini-2.5-pro",
    "claude-3-opus": "gemini-2.5-pro",
    "claude-haiku-4-5": "gemini-2.0-flash",
    "claude-3-5-haiku": "gemini-2.0-flash",
}

class GeminiProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Connection", "close")
        self.end_headers()
        res = {
            "status": "ok",
            "service": "Claude-to-Gemini-Proxy",
            "version": "2.0",
            "default_model": DEFAULT_MODEL
        }
        try:
            self.wfile.write(json.dumps(res, indent=2).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_anthropic_error(self, status_code, err_type, message, headers_sent=False):
        """Formats and sends an Anthropic-compliant error payload."""
        err_payload = {
            "type": "error",
            "error": {
                "type": err_type,
                "message": str(message)
            }
        }
        if headers_sent:
            # If SSE headers were already sent, deliver as an SSE error event
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
                self.wfile.write(b"Claude Code Gemini Proxy is Active.")
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

        api_key = self.headers.get("x-api-key") or DEFAULT_KEY
        if not api_key:
            self.send_anthropic_error(401, "authentication_error", "Missing GEMINI_API_KEY in environment or x-api-key header")
            return

        raw_model = req_data.get("model", DEFAULT_MODEL)
        gemini_model = MODEL_MAPPING.get(raw_model.lower(), DEFAULT_MODEL)
        if "claude" in raw_model.lower() and raw_model.lower() not in MODEL_MAPPING:
            gemini_model = DEFAULT_MODEL
        elif not raw_model.startswith("claude"):
            gemini_model = raw_model

        # Translate Anthropic messages to Gemini contents
        gemini_contents = []
        system_instruction = None
        if req_data.get("system"):
            sys_text = req_data["system"]
            if isinstance(sys_text, list):
                sys_text = "\n".join(item.get("text", "") for item in sys_text if isinstance(item, dict))
            system_instruction = {"parts": [{"text": str(sys_text)}]}

        for msg in req_data.get("messages", []):
            role = "user" if msg.get("role") == "user" else "model"
            parts = []
            c = msg.get("content", "")
            if isinstance(c, str):
                parts.append({"text": c})
            elif isinstance(c, list):
                for item in c:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append({"text": item.get("text", "")})
            if parts:
                gemini_contents.append({"role": role, "parts": parts})

        payload = {"contents": gemini_contents}
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        stream_requested = req_data.get("stream", True)
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
                with urllib.request.urlopen(gemini_req) as resp:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    headers_sent = True

                    # 1. Send initial Anthropic message_start event
                    start_ev = {
                        "type": "message_start",
                        "message": {
                            "id": f"msg_gemini_{os.urandom(6).hex()}",
                            "type": "message",
                            "role": "assistant",
                            "model": raw_model,
                            "content": [],
                            "usage": {"input_tokens": 100, "output_tokens": 0}
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

                    # 3. Stream content deltas
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
                                    parts = candidates[0].get("content", {}).get("parts", [])
                                    for part in parts:
                                        text_delta = part.get("text", "")
                                        if text_delta:
                                            delta_ev = {
                                                "type": "content_block_delta",
                                                "index": 0,
                                                "delta": {"type": "text_delta", "text": text_delta}
                                            }
                                            self.wfile.write(f"event: content_block_delta\ndata: {json.dumps(delta_ev)}\n\n".encode("utf-8"))
                                            self.wfile.flush()
                            except Exception:
                                pass

                    # 4. Content block stop & message stop
                    block_stop = {"type": "content_block_stop", "index": 0}
                    self.wfile.write(f"event: content_block_stop\ndata: {json.dumps(block_stop)}\n\n".encode("utf-8"))
                    msg_stop = {"type": "message_stop"}
                    self.wfile.write(f"event: message_stop\ndata: {json.dumps(msg_stop)}\n\n".encode("utf-8"))
                    self.wfile.flush()

            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Client disconnected or interrupted stream - handle gracefully
                pass
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                err_type = "rate_limit_error" if e.code == 429 else ("authentication_error" if e.code == 401 else "api_error")
                self.send_anthropic_error(e.code, err_type, f"Gemini API Error ({e.code}): {err_body}", headers_sent=headers_sent)
            except Exception as e:
                self.send_anthropic_error(500, "api_error", f"Proxy internal error: {e}", headers_sent=headers_sent)

        else:
            # Non-streaming response
            gemini_url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}"
                f":generateContent?key={api_key}"
            )
            gemini_req = urllib.request.Request(
                gemini_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            try:
                with urllib.request.urlopen(gemini_req) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    full_text = ""
                    candidates = resp_data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            full_text += part.get("text", "")

                    anthropic_resp = {
                        "id": f"msg_gemini_{os.urandom(6).hex()}",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "text", "text": full_text}],
                        "model": raw_model,
                        "stop_reason": "end_turn",
                        "stop_sequence": None,
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": max(1, len(full_text.split()))
                        }
                    }
                    body = json.dumps(anthropic_resp).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            except (BrokenPipeError, ConnectionResetError):
                pass
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                err_type = "rate_limit_error" if e.code == 429 else ("authentication_error" if e.code == 401 else "api_error")
                self.send_anthropic_error(e.code, err_type, f"Gemini API Error ({e.code}): {err_body}", headers_sent=False)
            except Exception as e:
                self.send_anthropic_error(500, "api_error", f"Proxy internal error: {e}", headers_sent=False)

    def log_message(self, format, *args):
        # Suppress routine request logging to prevent terminal clutter
        pass

def run(port=DEFAULT_PORT, model=DEFAULT_MODEL):
    global DEFAULT_MODEL
    DEFAULT_MODEL = model

    # Try binding to requested port with fallback to adjacent ports if busy
    server = None
    target_port = port
    for attempt in range(5):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", target_port), GeminiProxyHandler)
            break
        except OSError as e:
            if "Address already in use" in str(e) or e.errno == 98:
                target_port = port + attempt + 1
            else:
                print(f"Error binding to port {target_port}: {e}", file=sys.stderr)
                sys.exit(1)

    if not server:
        print(f"Error: Could not bind to port {port} or adjacent ports (8088-8093).", file=sys.stderr)
        sys.exit(1)

    print(f"Gemini Proxy running on http://127.0.0.1:{target_port} (model: {DEFAULT_MODEL})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

def main():
    parser = argparse.ArgumentParser(description="Anthropic-to-Google Gemini API Proxy")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT, help="Port to listen on (default: 8088)")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL, help="Default Gemini model (default: gemini-2.5-pro)")
    args = parser.parse_args()
    run(port=args.port, model=args.model)

if __name__ == "__main__":
    main()
