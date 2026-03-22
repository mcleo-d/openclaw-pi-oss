#!/usr/bin/env python3
"""
Test suite for openclaw-proxy (minimal variant).

Runs an in-process proxy server and a fake Ollama server on random ports.
No HTTP mocking required — the proxy makes real connections to the fake server,
which captures the transformed request and returns a canned response.

Run with:
    python -m pytest tests/test_openclaw_proxy.py         # if pytest installed
    python -m unittest tests.test_openclaw_proxy          # stdlib only
    python tests/test_openclaw_proxy.py                   # direct
"""
import http.client
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

# ── Fake Ollama server ───────────────────────────────────────────────────────
# Must start before proxy is imported so we know the port to pass via env var.

class _FakeOllamaHandler(BaseHTTPRequestHandler):
    """
    Captures the most recent request received from the proxy.
    Stores it in the class-level `last_request` dict; tests read from there.
    """
    last_request: dict = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            _FakeOllamaHandler.last_request["body"] = json.loads(body)
        except Exception:
            _FakeOllamaHandler.last_request["raw"] = body
        _FakeOllamaHandler.last_request["path"] = self.path
        _FakeOllamaHandler.last_request["method"] = "POST"

        resp_body = b'{"done":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    def do_GET(self):
        _FakeOllamaHandler.last_request["method"] = "GET"
        _FakeOllamaHandler.last_request["path"] = self.path
        _FakeOllamaHandler.last_request["raw"] = b""

        resp_body = b'{"models":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    def log_message(self, fmt, *args):
        pass  # suppress access log noise


_fake_ollama = HTTPServer(("127.0.0.1", 0), _FakeOllamaHandler)
_fake_ollama_port = _fake_ollama.server_address[1]
threading.Thread(target=_fake_ollama.serve_forever, daemon=True).start()


# ── Test fixture setup ──────────────────────────────────────────────────────
# Must happen before proxy is imported (module-level globals load at import time).

os.environ.update({
    "PROXY_BIND_HOST":         "127.0.0.1",
    "PROXY_BIND_PORT":         "0",                       # OS assigns random port
    "PROXY_OLLAMA_HOST":       "127.0.0.1",
    "PROXY_OLLAMA_PORT":       str(_fake_ollama_port),    # proxy → fake Ollama
    "PROXY_MAX_CTX":           "4096",
    "PROXY_MAX_SYSTEM_CHARS":  "50",                      # small for truncation tests
    "PROXY_MAX_MESSAGES":      "2",                       # small for history capping tests
})

# Load the openclaw-proxy module under a unique name to avoid colliding with
# the "proxy" module name used by test_proxy.py (ollama-proxy variant).
# Both files are imported in the same process by `unittest discover`, so a plain
# `import proxy` would return whichever variant was cached first in sys.modules.
import importlib.util as _ilu  # noqa: E402

_proxy_path = os.path.join(
    os.path.dirname(__file__), "..", "config", "etc", "openclaw-proxy", "proxy.py"
)
_spec = _ilu.spec_from_file_location("openclaw_proxy", _proxy_path)
import types as _types  # noqa: E402
_proxy = _types.ModuleType("openclaw_proxy")
sys.modules["openclaw_proxy"] = _proxy
_spec.loader.exec_module(_proxy)  # type: ignore[union-attr]
ProxyHandler = _proxy.ProxyHandler


# ── Proxy server ────────────────────────────────────────────────────────────

_server = HTTPServer(("127.0.0.1", 0), ProxyHandler)
_server_port = _server.server_address[1]
threading.Thread(target=_server.serve_forever, daemon=True).start()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _post(path, data):
    """POST JSON to the test proxy server."""
    conn = http.client.HTTPConnection("127.0.0.1", _server_port, timeout=10)
    body = json.dumps(data).encode()
    hdrs = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    conn.request("POST", path, body, hdrs)
    resp = conn.getresponse()
    resp_body = resp.read()
    return resp, resp_body


def _post_raw(path, raw_body):
    """POST raw bytes to the test proxy server (for non-JSON tests)."""
    conn = http.client.HTTPConnection("127.0.0.1", _server_port, timeout=10)
    hdrs = {"Content-Length": str(len(raw_body))}
    conn.request("POST", path, raw_body, hdrs)
    resp = conn.getresponse()
    resp_body = resp.read()
    return resp, resp_body


def _get(path):
    conn = http.client.HTTPConnection("127.0.0.1", _server_port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    resp_body = resp.read()
    return resp, resp_body


def _captured():
    """Return the request captured by the fake Ollama server."""
    return _FakeOllamaHandler.last_request


def _clear():
    """Clear the fake Ollama server's captured request."""
    _FakeOllamaHandler.last_request.clear()


# ── Tests ───────────────────────────────────────────────────────────────────

class TestContextCapping(unittest.TestCase):

    def setUp(self):
        _clear()

    def test_num_ctx_capped_when_over_limit(self):
        resp, _ = _post("/api/chat", {
            "model": "test",
            "options": {"num_ctx": 16384},
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertEqual(resp.status, 200)
        self.assertEqual(_captured()["body"]["options"]["num_ctx"], _proxy.MAX_CTX)

    def test_num_ctx_unchanged_when_under_limit(self):
        resp, _ = _post("/api/chat", {
            "model": "test",
            "options": {"num_ctx": 512},
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertEqual(resp.status, 200)
        self.assertEqual(_captured()["body"]["options"]["num_ctx"], 512)

    def test_options_without_num_ctx_defaults_to_max_ctx(self):
        """options block present but no num_ctx key — should default to MAX_CTX."""
        resp, _ = _post("/api/chat", {
            "model": "test",
            "options": {"num_predict": 100},
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertEqual(resp.status, 200)
        self.assertEqual(_captured()["body"]["options"]["num_ctx"], _proxy.MAX_CTX)

    def test_no_options_block_gets_one_added_with_num_ctx(self):
        """Requests without an options block should have one added with num_ctx set."""
        resp, _ = _post("/api/chat", {
            "model": "test",
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertEqual(resp.status, 200)
        self.assertEqual(_captured()["body"]["options"]["num_ctx"], _proxy.MAX_CTX)


class TestThinkInjection(unittest.TestCase):

    def setUp(self):
        _clear()

    def test_think_false_injected_when_absent(self):
        _post("/api/chat", {
            "model": "test",
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertIs(_captured()["body"]["think"], False)

    def test_think_true_overridden_to_false(self):
        """
        openclaw-proxy hard-overrides think=False even when the client sends True.
        This differs from ollama-proxy which only injects if the key is absent.
        """
        _post("/api/chat", {
            "model": "test",
            "think": True,
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertIs(_captured()["body"]["think"], False)


class TestSystemMessageTruncation(unittest.TestCase):

    def setUp(self):
        _clear()

    def test_system_message_truncated_when_over_limit(self):
        long_system = "A" * 200  # > MAX_SYSTEM_CHARS (50 in test config)
        _post("/api/chat", {
            "model": "test",
            "messages": [
                {"role": "system", "content": long_system},
                {"role": "user",   "content": "hello"},
            ],
        })
        system_msgs = [m for m in _captured()["body"]["messages"] if m["role"] == "system"]
        self.assertEqual(len(system_msgs[0]["content"]), _proxy.MAX_SYSTEM_CHARS)

    def test_system_message_unchanged_when_under_limit(self):
        short_system = "Short."
        _post("/api/chat", {
            "model": "test",
            "messages": [
                {"role": "system", "content": short_system},
                {"role": "user",   "content": "hello"},
            ],
        })
        system_msgs = [m for m in _captured()["body"]["messages"] if m["role"] == "system"]
        self.assertEqual(system_msgs[0]["content"], short_system)

    def test_system_message_with_none_content_does_not_crash(self):
        """content=None in a system message must not raise an exception."""
        try:
            resp, _ = _post("/api/chat", {
                "model": "test",
                "messages": [
                    {"role": "system", "content": None},
                    {"role": "user",   "content": "hello"},
                ],
            })
            self.assertLess(resp.status, 500)
        except Exception as e:
            self.fail(f"None content raised: {e}")


class TestHistoryCapping(unittest.TestCase):

    def setUp(self):
        _clear()

    def test_history_capped_to_max_messages(self):
        """4 non-system messages with MAX_MESSAGES=2 → only the last 2 are forwarded."""
        _post("/api/chat", {
            "model": "test",
            "messages": [
                {"role": "user",      "content": "msg1"},
                {"role": "assistant", "content": "rsp1"},
                {"role": "user",      "content": "msg2"},
                {"role": "assistant", "content": "rsp2"},
            ],
        })
        non_system = [m for m in _captured()["body"]["messages"] if m["role"] != "system"]
        self.assertEqual(len(non_system), _proxy.MAX_MESSAGES)
        self.assertEqual(non_system[0]["content"], "msg2")
        self.assertEqual(non_system[1]["content"], "rsp2")

    def test_system_messages_preserved_after_capping(self):
        """System messages must survive history capping."""
        _post("/api/chat", {
            "model": "test",
            "messages": [
                {"role": "system",    "content": "You are a helpful assistant."},
                {"role": "user",      "content": "msg1"},
                {"role": "assistant", "content": "rsp1"},
                {"role": "user",      "content": "msg2"},
                {"role": "assistant", "content": "rsp2"},
            ],
        })
        msgs = _captured()["body"]["messages"]
        system_msgs = [m for m in msgs if m["role"] == "system"]
        non_system  = [m for m in msgs if m["role"] != "system"]
        self.assertEqual(len(system_msgs), 1)
        self.assertEqual(len(non_system), _proxy.MAX_MESSAGES)


class TestMaxMessagesZeroEdgeCase(unittest.TestCase):

    def setUp(self):
        _clear()

    def test_max_messages_zero_clears_all_non_system_history(self):
        """PROXY_MAX_MESSAGES=0 must clear all non-system messages."""
        with patch.object(_proxy, "MAX_MESSAGES", 0):
            _post("/api/chat", {
                "model": "test",
                "messages": [
                    {"role": "system",    "content": "You are helpful."},
                    {"role": "user",      "content": "msg1"},
                    {"role": "assistant", "content": "rsp1"},
                ],
            })
        msgs = _captured()["body"]["messages"]
        non_system = [m for m in msgs if m["role"] != "system"]
        self.assertEqual(non_system, [])

    def test_empty_messages_list_does_not_crash(self):
        """An empty messages array must not raise an exception."""
        try:
            resp, _ = _post("/api/chat", {"model": "test", "messages": []})
            self.assertLess(resp.status, 500)
        except Exception as e:
            self.fail(f"Empty messages raised: {e}")


class TestInjectPaths(unittest.TestCase):

    def setUp(self):
        _clear()

    def test_api_chat_gets_all_transforms_including_history_capping(self):
        """/api/chat should receive think, num_ctx, truncation, AND history capping."""
        _post("/api/chat", {
            "model": "test",
            "options": {"num_ctx": 16384},
            "messages": [
                {"role": "system",    "content": "S"},
                {"role": "user",      "content": "msg1"},
                {"role": "assistant", "content": "rsp1"},
                {"role": "user",      "content": "msg2"},
                {"role": "assistant", "content": "rsp2"},
            ],
        })
        body = _captured()["body"]
        self.assertIs(body["think"], False)
        self.assertEqual(body["options"]["num_ctx"], _proxy.MAX_CTX)
        non_system = [m for m in body["messages"] if m["role"] != "system"]
        self.assertEqual(len(non_system), _proxy.MAX_MESSAGES)

    def test_api_generate_gets_think_and_num_ctx_but_not_history_capping(self):
        """/api/generate is in INJECT_PATHS → think + num_ctx applied.
        History capping applies only to /api/chat — messages forwarded unmodified.
        """
        original_messages = [
            {"role": "user",      "content": "msg1"},
            {"role": "assistant", "content": "rsp1"},
            {"role": "user",      "content": "msg2"},
            {"role": "assistant", "content": "rsp2"},
        ]
        resp, _ = _post("/api/generate", {
            "model": "test",
            "options": {"num_ctx": 16384},
            "messages": list(original_messages),
        })
        self.assertEqual(resp.status, 200)
        body = _captured()["body"]
        self.assertIs(body["think"], False)
        self.assertEqual(body["options"]["num_ctx"], _proxy.MAX_CTX)
        # Messages must be forwarded intact — no history capping on /api/generate
        self.assertEqual(body["messages"], original_messages)

    def test_get_request_forwarded_with_empty_body(self):
        """GET requests must be forwarded unchanged with an empty body."""
        resp, _ = _get("/api/tags")
        self.assertEqual(resp.status, 200)
        self.assertEqual(_captured().get("method"), "GET")
        self.assertEqual(_captured().get("raw", b""), b"")

    def test_non_json_body_on_inject_path_passes_through_without_crashing(self):
        """Non-JSON body on /api/chat must not crash the proxy."""
        try:
            resp, _ = _post_raw("/api/chat", b"not json at all")
            self.assertLess(resp.status, 500)
        except Exception as e:
            self.fail(f"Non-JSON body raised: {e}")


if __name__ == "__main__":
    unittest.main()
