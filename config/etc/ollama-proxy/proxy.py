#!/usr/bin/env python3
"""
ollama-proxy: lightweight HTTP proxy between OpenClaw and Ollama.

Intercepts every POST request and:
  - Caps options.num_ctx at MAX_CTX to prevent KV cache memory pressure
  - Injects think=false to disable qwen3 extended thinking mode
    (OpenClaw cannot set this itself; without it qwen3 generates 200+ thinking
    tokens per tool call which makes each call take 50+ seconds on Pi hardware)
  - Truncates the system message to MAX_SYSTEM_CHARS to reduce prefill time
    (OpenClaw sends ~4,616-token system prompts; Pi 5 prefill at 16.5 t/s makes
    this take ~248s. Truncating to ~500 chars (~125 tokens) brings prefill to ~10s)
  - Logs per-role character counts for /api/chat to diagnose prompt bloat
  - Two-layer prompt injection detection on all /api/chat requests

Configuration via environment variables (set in ollama-proxy.service):
  PROXY_MAX_CTX          — KV cache cap in tokens (default: 4096)
  PROXY_MAX_SYSTEM_CHARS — system message truncation limit in chars (default: 500)
  PROXY_CLASSIFIER_MODEL — model used for LLM injection classification
  PROXY_CLASSIFIER_CTX   — context window for classifier (default: 512)
  PROXY_CLASSIFIER_TIMEOUT — classifier timeout in seconds (default: 20)
  PROXY_PATTERNS_FILE    — path to injection pattern list (default: /etc/ollama-proxy/patterns.conf)
  PROXY_CLASSIFIER_SYSTEM_PROMPT_FILE — path to classifier system prompt (default: /etc/ollama-proxy/classifier-prompt.txt)
  PROXY_OLLAMA_URL       — upstream Ollama URL (default: http://127.0.0.1:11434)
  PROXY_LISTEN_PORT      — port the proxy listens on (required — no default)
  PROXY_MAX_BODY_SIZE    — maximum request body size in bytes (default: 1048576 = 1 MiB)
  PROXY_FORWARD_TIMEOUT  — forward timeout to Ollama in seconds (default: 300)

Injection patterns are loaded from PROXY_PATTERNS_FILE at startup.
The classifier system prompt is loaded from PROXY_CLASSIFIER_SYSTEM_PROMPT_FILE at startup.
The proxy refuses to start if either file is missing, unreadable, or empty.
"""
import json
import os
import socketserver
import http.server
import urllib.request
import urllib.error
import sys

OLLAMA_URL  = os.environ.get("PROXY_OLLAMA_URL",  "http://127.0.0.1:11434")
_proxy_port = os.environ.get("PROXY_LISTEN_PORT")
if _proxy_port is None:
    print("[ollama-proxy] ERROR: PROXY_LISTEN_PORT env var not set — refusing to start", file=sys.stderr)
    sys.exit(1)
LISTEN_PORT = int(_proxy_port)

MAX_CTX          = int(os.environ.get("PROXY_MAX_CTX",          "4096"))
MAX_SYSTEM_CHARS = int(os.environ.get("PROXY_MAX_SYSTEM_CHARS", "500"))
CHARS_PER_TOKEN  = 4  # rough estimate for logging only

CLASSIFIER_MODEL   = os.environ.get("PROXY_CLASSIFIER_MODEL",   "qwen2.5:3b-instruct-q4_K_M")
CLASSIFIER_CTX     = int(os.environ.get("PROXY_CLASSIFIER_CTX",     "512"))
CLASSIFIER_TIMEOUT = int(os.environ.get("PROXY_CLASSIFIER_TIMEOUT", "20"))
PATTERNS_FILE      = os.environ.get("PROXY_PATTERNS_FILE",      "/etc/ollama-proxy/patterns.conf")
CLASSIFIER_PROMPT_FILE = os.environ.get("PROXY_CLASSIFIER_SYSTEM_PROMPT_FILE", "/etc/ollama-proxy/classifier-prompt.txt")

MAX_BODY_SIZE     = int(os.environ.get("PROXY_MAX_BODY_SIZE",   str(1 * 1024 * 1024)))  # 1 MiB
FORWARD_TIMEOUT   = int(os.environ.get("PROXY_FORWARD_TIMEOUT", "300"))


def _load_patterns(path):
    """Load injection detection patterns from file. Exits on missing or empty file."""
    try:
        with open(path) as f:
            patterns = [
                line.strip() for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    except (OSError, IOError) as e:
        print(
            f"[ollama-proxy] ERROR: cannot read patterns file '{path}': {e} — refusing to start",
            file=sys.stderr,
        )
        sys.exit(1)
    if not patterns:
        print(
            f"[ollama-proxy] ERROR: patterns file '{path}' is empty — refusing to start",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[ollama-proxy] loaded {len(patterns)} injection patterns from {path}", file=sys.stderr)
    return patterns


INJECTION_PATTERNS = _load_patterns(PATTERNS_FILE)


def _load_classifier_prompt(path):
    """Load LLM classifier system prompt from file. Exits if missing or empty."""
    try:
        with open(path) as f:
            prompt = f.read().strip()
    except (OSError, IOError) as e:
        print(
            f"[ollama-proxy] ERROR: cannot read classifier prompt file '{path}': {e} — refusing to start",
            file=sys.stderr,
        )
        sys.exit(1)
    if not prompt:
        print(
            f"[ollama-proxy] ERROR: classifier prompt file '{path}' is empty — refusing to start",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[ollama-proxy] loaded classifier prompt from {path}", file=sys.stderr)
    return prompt


# ── Injection detection ──────────────────────────────────────────────────────

CLASSIFIER_SYSTEM_PROMPT = _load_classifier_prompt(CLASSIFIER_PROMPT_FILE)


class OllamaProxyHandler(http.server.BaseHTTPRequestHandler):
    server_version = "ollama-proxy/1.0"

    def _forward(self, method, body=None):
        headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("host", "content-length", "transfer-encoding")
        }
        if body is not None:
            headers["Content-Length"] = str(len(body))

        req = urllib.request.Request(
            OLLAMA_URL + self.path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=FORWARD_TIMEOUT) as resp:
                self.send_response(resp.status)
                for key, val in resp.headers.items():
                    if key.lower() not in ("transfer-encoding",):
                        self.send_header(key, val)
                self.end_headers()
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b"upstream error")

    def do_GET(self):
        self._forward("GET")

    def do_HEAD(self):
        self._forward("HEAD")

    def _block(self, reason: str, detail: str = ""):
        body = json.dumps({"error": reason, "detail": detail}).encode()
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _classify(self, content: str) -> tuple[bool, str]:
        """
        Send content to the classifier model. Returns (is_unsafe, raw_verdict).
        Always returns (False, ...) on any error — fail open.
        """
        payload = {
            "model": CLASSIFIER_MODEL,
            "stream": False,
            "think": False,
            "options": {"num_ctx": CLASSIFIER_CTX},
            "messages": [
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user",   "content": content},
            ],
        }
        req = urllib.request.Request(
            OLLAMA_URL + "/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=CLASSIFIER_TIMEOUT) as resp:
                resp_data = json.loads(resp.read())
            verdict_raw = resp_data["message"]["content"].strip()
        except Exception as e:
            print(f"[proxy] classifier ERROR (fail open): {e} | forwarding", file=sys.stderr)
            return False, str(e)

        try:
            verdict_upper = verdict_raw.upper()
        except Exception:
            print("[proxy] classifier ERROR (fail open): bad verdict | forwarding", file=sys.stderr)
            return False, ""

        if verdict_upper == "UNSAFE":
            return True, verdict_raw
        if verdict_upper != "SAFE":
            print(
                f"[proxy] classifier WARNING: unexpected verdict '{verdict_raw}' (fail open) | forwarding",
                file=sys.stderr,
            )
        return False, verdict_raw

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))

        # Body size guard — prevents memory exhaustion from large POST bodies
        if content_length > MAX_BODY_SIZE:
            self._block("request too large")
            return

        body = self.rfile.read(content_length) if content_length else b""

        if body:
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                pass  # pass non-JSON through unchanged
            else:
                # Cap num_ctx
                opts = data.get("options")
                if isinstance(opts, dict):
                    original_ctx = opts.get("num_ctx", 0)
                    if original_ctx > MAX_CTX:
                        opts["num_ctx"] = MAX_CTX
                        print(
                            f"[proxy] capped num_ctx {original_ctx} → {MAX_CTX}",
                            file=sys.stderr,
                        )

                # Single-pass: log original per-role sizes and truncate system messages
                if self.path == "/api/chat" and "messages" in data:
                    role_chars = {}
                    for msg in data["messages"]:
                        if not isinstance(msg, dict):
                            continue
                        role = msg.get("role", "unknown")
                        content = msg.get("content") or ""
                        orig_len = len(content)
                        role_chars[role] = role_chars.get(role, 0) + orig_len

                        if role == "system" and orig_len > MAX_SYSTEM_CHARS:
                            msg["content"] = content[:MAX_SYSTEM_CHARS]
                            print(
                                f"[proxy] truncated system message "
                                f"{orig_len}ch(~{orig_len//CHARS_PER_TOKEN}tok)"
                                f" → {MAX_SYSTEM_CHARS}ch(~{MAX_SYSTEM_CHARS//CHARS_PER_TOKEN}tok)",
                                file=sys.stderr,
                            )

                    total = sum(role_chars.values())
                    parts = ", ".join(
                        f"{r}:{c}ch(~{c//CHARS_PER_TOKEN}tok)"
                        for r, c in sorted(role_chars.items())
                    )
                    print(
                        f"[proxy] chat prompt breakdown — total:{total}ch(~{total//CHARS_PER_TOKEN}tok) | {parts}",
                        file=sys.stderr,
                    )

                # Disable qwen3 thinking mode (no-op for other models)
                if "think" not in data:
                    data["think"] = False

                body = json.dumps(data).encode()
                # Update Content-Type so Ollama parses correctly
                self.headers["Content-Type"] = "application/json"

                # ── Injection detection ──────────────────────────────────────
                if self.path == "/api/chat" and "messages" in data:
                    scannable = [
                        msg for msg in data["messages"]
                        if isinstance(msg, dict)
                        and msg.get("role") in ("user", "tool")
                        and isinstance(msg.get("content"), str)
                        and msg["content"]
                    ]

                    # Layer 1 — pattern matching (fast, no LLM cost)
                    for msg in scannable:
                        role    = msg.get("role", "unknown")
                        content = msg["content"]
                        lower   = content.lower()
                        for pattern in INJECTION_PATTERNS:
                            if pattern in lower:
                                preview = content[:100].replace("\n", " ")
                                print(
                                    f'[proxy] BLOCKED injection pattern in {role} message: '
                                    f'"{pattern}" | content preview: {preview}',
                                    file=sys.stderr,
                                )
                                self._block("prompt injection detected")
                                return

                    # Layer 2 — LLM classifier (scans all user/tool messages up to
                    # classifier context budget, newest-first, to catch multi-turn poisoning)
                    if scannable:
                        budget_chars = CLASSIFIER_CTX * CHARS_PER_TOKEN
                        combined_parts: list[str] = []
                        used_chars = 0
                        for msg in reversed(scannable):
                            content = msg["content"]
                            remaining = budget_chars - used_chars
                            if remaining <= 0:
                                break
                            if len(content) > remaining:
                                combined_parts.append(content[:remaining])
                                used_chars += remaining
                            else:
                                combined_parts.append(content)
                                used_chars += len(content)
                        combined = "\n---\n".join(reversed(combined_parts))

                        is_unsafe, verdict = self._classify(combined)
                        if is_unsafe:
                            preview = combined[:100].replace("\n", " ")
                            print(
                                f"[proxy] BLOCKED UNSAFE classification | "
                                f"model verdict: {verdict} | content preview: {preview}",
                                file=sys.stderr,
                            )
                            self._block("prompt injection detected", "classifier: UNSAFE")
                            return
                        print(
                            f"[proxy] classifier SAFE | model: {CLASSIFIER_MODEL} | "
                            f"{used_chars}ch ({len(scannable)} messages scanned)",
                            file=sys.stderr,
                        )
                # ── End injection detection ───────────────────────────────────

        self._forward("POST", body)

    def log_message(self, fmt, *args):
        # Only log errors, not every request
        pass


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), OllamaProxyHandler)
    print(
        f"[ollama-proxy] 0.0.0.0:{LISTEN_PORT} → {OLLAMA_URL} "
        f"(max_ctx={MAX_CTX}, max_system={MAX_SYSTEM_CHARS}ch, think=false, "
        f"patterns={len(INJECTION_PATTERNS)}, classifier={CLASSIFIER_MODEL})",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
