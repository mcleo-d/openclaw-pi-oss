#!/usr/bin/env python3
"""
openclaw-proxy — minimal Ollama shim for OpenClaw Pi

Intercepts /api/generate and /api/chat requests from OpenClaw and:
  - Injects think:false to disable Qwen3 chain-of-thought mode
  - Caps num_ctx at MAX_CTX to prevent KV cache overflow on Pi 5

All other requests and responses are forwarded unchanged.
No security scanning, no prompt injection detection — home lab use only.

Configuration (via environment variables):
  PROXY_BIND_HOST   — listen address (default: 0.0.0.0)
  PROXY_BIND_PORT   — listen port (default: 11435)
  PROXY_OLLAMA_HOST — Ollama host (default: 127.0.0.1)
  PROXY_OLLAMA_PORT — Ollama port (default: 11434)
  PROXY_MAX_CTX     — max num_ctx to allow (default: 4096)
"""

import http.client
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

OLLAMA_HOST = os.getenv("PROXY_OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.getenv("PROXY_OLLAMA_PORT", "11434"))
BIND_HOST = os.getenv("PROXY_BIND_HOST", "0.0.0.0")
BIND_PORT = int(os.getenv("PROXY_BIND_PORT", "11435"))
MAX_CTX = int(os.getenv("PROXY_MAX_CTX", "4096"))

INJECT_PATHS = frozenset({"/api/generate", "/api/chat"})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("openclaw-proxy")


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress per-request access log; errors go to stderr → journald

    def _forward(self, method: str, body: bytes, content_type: str) -> None:
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }
        try:
            conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=300)
            conn.request(method, self.path, body, headers)
            resp = conn.getresponse()

            self.send_response(resp.status)
            for key, val in resp.getheaders():
                if key.lower() not in ("transfer-encoding",):
                    self.send_header(key, val)
            self.end_headers()

            # Stream response chunks — handles both streaming and non-streaming Ollama responses
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
            conn.close()
        except Exception as exc:  # noqa: BLE001
            log.error("forward error: %s", exc)
            try:
                self.send_error(502, f"Ollama unreachable: {exc}")
            except Exception:
                pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "application/json")

        if self.path in INJECT_PATHS:
            try:
                payload = json.loads(body)
                opts = payload.setdefault("options", {})
                # Inject think:false — disables Qwen3 chain-of-thought on every call
                opts.setdefault("think", False)
                # Cap num_ctx — prevents KV cache overflow on Cortex-A76
                ctx = opts.get("num_ctx", MAX_CTX)
                opts["num_ctx"] = min(ctx, MAX_CTX)
                body = json.dumps(payload).encode()
                log.debug("injected think=false num_ctx=%d path=%s", opts["num_ctx"], self.path)
            except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                log.warning("could not parse body for injection — forwarding unchanged path=%s err=%s",
                            self.path, exc)

        self._forward("POST", body, content_type)

    def do_GET(self) -> None:
        self._forward("GET", b"", self.headers.get("Content-Type", "application/json"))


if __name__ == "__main__":
    log.info(
        "openclaw-proxy listening on %s:%d → %s:%d (MAX_CTX=%d)",
        BIND_HOST, BIND_PORT, OLLAMA_HOST, OLLAMA_PORT, MAX_CTX,
    )
    server = HTTPServer((BIND_HOST, BIND_PORT), ProxyHandler)
    server.serve_forever()
