#!/usr/bin/env python3
"""Unit tests for the /ask brain in speak_server.py.

Runs in ANY Python (no numpy / torch / Ollama needed): the heavy deps that
speak_server imports at module load (numpy, bake_anim) are stubbed before
import, and Ollama is replaced by a fake localhost HTTP server. Covers the
Codex-flagged correctness points: the speech clamp is a pre-filter (not a
duration guarantee), history is bounded by turns AND chars, and the Ollama
client validates shape / handles refused / malformed / empty / timeout.

    python3 tools/test_speak_ask.py
"""
import json
import sys
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

# --- stub the heavy deps so importing speak_server needs no numpy/torch -----
sys.modules.setdefault("numpy", types.ModuleType("numpy"))
_bake = types.ModuleType("bake_anim")
_bake.bake = lambda *a, **k: {"frames": 0, "meta": {}}
_bake.load_head = lambda *a, **k: {}
sys.modules.setdefault("bake_anim", _bake)

import speak_server as ss  # noqa: E402


# --- a controllable fake Ollama ---------------------------------------------
class FakeOllama:
    """Serves /api/tags, /api/chat, /api/pull with test-controlled behavior."""
    def __init__(self):
        self.tags = ["qwen2.5:3b"]
        self.chat = {"message": {"content": "Lima is the capital of Peru."}}
        self.raw = None        # if set, return this exact bytes (e.g. malformed)
        self.sleep = 0.0       # delay before responding (timeout tests)
        self.pulled = False
        cfg = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj):
                body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if cfg.sleep:
                    time.sleep(cfg.sleep)
                if self.path == "/api/tags":
                    self._json({"models": [{"name": n} for n in cfg.tags]})
                else:
                    self.send_response(404); self.end_headers()

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                if cfg.sleep:
                    time.sleep(cfg.sleep)
                if self.path == "/api/pull":
                    cfg.pulled = True
                    self._json(b'{"status":"success"}\n')
                elif self.path == "/api/chat":
                    self._json(cfg.raw if cfg.raw is not None else cfg.chat)
                else:
                    self.send_response(404); self.end_headers()

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()


class ClampTests(unittest.TestCase):
    def test_short_reply_unchanged(self):
        self.assertEqual(ss._clamp_for_speech("Lima."), "Lima.")

    def test_collapses_whitespace(self):
        self.assertEqual(ss._clamp_for_speech("  a\n\n b   c "), "a b c")

    def test_long_reply_trimmed_to_word_cap(self):
        words = " ".join(f"w{i}" for i in range(100)) + "."
        out = ss._clamp_for_speech(words)
        self.assertLessEqual(len(out.split(" ")), ss.MAX_REPLY_WORDS)

    def test_backs_up_to_sentence_boundary(self):
        body = " ".join(f"w{i}" for i in range(40))
        text = body + ". " + " ".join(f"x{i}" for i in range(40))
        out = ss._clamp_for_speech(text)
        self.assertTrue(out.endswith("."))
        self.assertNotIn("x", out)            # everything after the period dropped

    def test_no_punctuation_still_caps(self):
        out = ss._clamp_for_speech(" ".join(f"w{i}" for i in range(80)))
        self.assertEqual(len(out.split(" ")), ss.MAX_REPLY_WORDS)


class HistoryTests(unittest.TestCase):
    def test_trims_to_turn_cap(self):
        h = []
        for i in range(20):
            h += [{"role": "user", "content": str(i)},
                  {"role": "assistant", "content": str(i)}]
        ss._trim_history(h)
        self.assertEqual(len(h), 2 * ss.MAX_HISTORY_TURNS)

    def test_trims_by_char_budget(self):
        big = "x" * 3000
        h = [{"role": "user", "content": big},
             {"role": "assistant", "content": big},
             {"role": "user", "content": "hi"},
             {"role": "assistant", "content": "yo"}]
        ss._trim_history(h)
        self.assertLessEqual(sum(len(m["content"]) for m in h),
                             ss.MAX_HISTORY_CHARS)
        self.assertEqual(h[-1]["content"], "yo")   # newest pair survives


class MockBrainTests(unittest.TestCase):
    def test_short_fixed_reply_not_echo(self):
        b = ss.MockBrain()
        long_q = "tell me everything " * 50
        out = b.reply(long_q)
        self.assertNotIn("tell me everything", out)     # must not echo
        self.assertLess(len(out), 120)
        self.assertEqual(b.state, "ready")


class BrainTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama()

    def tearDown(self):
        self.fake.stop()

    def test_reply_parses_and_clamps_and_records(self):
        b = ss.Brain(self.fake.url, "qwen2.5:3b")
        out = b.reply("capital of Peru?")
        self.assertEqual(out, "Lima is the capital of Peru.")
        self.assertEqual(len(b.history), 2)
        self.assertEqual(b.history[0]["content"], "capital of Peru?")

    def test_warm_ready_when_model_present(self):
        b = ss.Brain(self.fake.url, "qwen2.5:3b")
        b.warm()
        self.assertEqual(b.state, "ready")
        self.assertFalse(self.fake.pulled)       # already present -> no pull

    def test_warm_pulls_when_model_absent(self):
        self.fake.tags = ["something-else:latest"]
        b = ss.Brain(self.fake.url, "qwen2.5:3b")
        b.warm()
        self.assertEqual(b.state, "ready")
        self.assertTrue(self.fake.pulled)

    def test_empty_content_raises(self):
        self.fake.chat = {"message": {"content": "   "}}
        b = ss.Brain(self.fake.url, "qwen2.5:3b")
        with self.assertRaises(ss.OllamaError):
            b.reply("hi")

    def test_malformed_json_raises(self):
        self.fake.raw = b"{not json"
        b = ss.Brain(self.fake.url, "qwen2.5:3b")
        with self.assertRaises(ss.OllamaError):
            b.reply("hi")

    def test_missing_message_key_raises(self):
        self.fake.chat = {"done": True}
        b = ss.Brain(self.fake.url, "qwen2.5:3b")
        with self.assertRaises(ss.OllamaError):
            b.reply("hi")

    def test_connection_refused_raises(self):
        b = ss.Brain("http://127.0.0.1:1", "qwen2.5:3b")   # nothing listening
        with self.assertRaises(ss.OllamaError):
            b.reply("hi")

    def test_timeout_raises(self):
        self.fake.sleep = 1.0
        b = ss.Brain(self.fake.url, "qwen2.5:3b")
        with self.assertRaises(ss.OllamaError):
            b._chat([{"role": "user", "content": "hi"}], timeout=0.2)

    def test_warm_error_state_when_ollama_down(self):
        b = ss.Brain("http://127.0.0.1:1", "qwen2.5:3b")
        b.warm()
        self.assertEqual(b.state, "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
