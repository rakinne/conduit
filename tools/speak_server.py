#!/usr/bin/env python3
"""
speak_server.py — on-the-fly text -> talking head for conduit

Runs on YOUR machine (inside the faceformer Python 3.10 env). Loads the
FaceFormer model ONCE at startup, then serves localhost requests from
the conduit page:

  GET  /ping              -> {"ok": true, "mode", "brain": <state>, "model"}
  POST /speak   {"text"}  -> TTS -> FaceFormer -> bake -> ANIM_DATA-shaped
                             JSON + "audioB64" (16 kHz wav)
  POST /animate {"wavB64"}-> same, but you supply the audio
  POST /ask     {"text"}  -> local LLM (Ollama) -> reply -> TTS -> FaceFormer
                             (the head ANSWERS the query aloud). No cloud API.

The conduit page auto-detects this server and shows an UPLINK input bar;
typing text there makes the head speak it (or, with the brain ready, answer it).

TTS backends (auto-picked): macOS `say` (zero deps) -> mock silence.
Hard limit: FaceFormer's positional encoding caps at 600 frames = 20 s
of speech per request; longer audio is rejected with an error message.

Usage (real):
  source .venv-faceformer/bin/activate     # or: conda activate faceformer
  python3 tools/speak_server.py --faceformer ~/Downloads/FaceFormer-main

Usage (plumbing test, no torch/model needed):
  python3 tools/speak_server.py --mock
"""
import argparse
import base64
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from bake_anim import bake, load_head  # noqa: E402

SR = 16000
MAX_FRAMES = 600          # FaceFormer PPE/biased_mask max_seq_len
FPS = 30
TRAIN_SUBJECTS = ("FaceTalk_170728_03272_TA FaceTalk_170904_00128_TA "
                  "FaceTalk_170725_00137_TA FaceTalk_170915_00223_TA "
                  "FaceTalk_170811_03274_TA FaceTalk_170913_03279_TA "
                  "FaceTalk_170904_03276_TA FaceTalk_170912_03278_TA")
CONDITION = "FaceTalk_170913_03279_TA"
SUBJECT = "FaceTalk_170809_00138_TA"


# ----------------------------------------------------------------- TTS
def tts_say(text, voice=None, timeout=30):
    """macOS built-in TTS -> float32 samples @16 kHz. `timeout` guards against a
    hung `say` freezing the single-threaded server."""
    with tempfile.TemporaryDirectory() as td:
        aiff = os.path.join(td, "tts.aiff")
        cmd = ["say", "-o", aiff]
        if voice:
            cmd += ["-v", voice]
        subprocess.run(cmd + [text], check=True, timeout=timeout)
        import librosa
        y, _ = librosa.load(aiff, sr=SR)
        return y.astype(np.float32)


def tts_mock(text, voice=None):
    """Silence sized to the text — lets --mock exercise the whole path."""
    return np.zeros(int(SR * max(1.0, 0.06 * len(text))), np.float32)


def pick_tts():
    try:
        subprocess.run(["say", "-v", "?"], capture_output=True, check=True)
        return tts_say, "say"
    except Exception:
        return tts_mock, "mock-silence"


def wav_b64(samples):
    """float32 @16k -> base64 of a 16-bit wav (for <audio> data URI)."""
    from scipy.io import wavfile
    buf = io.BytesIO()
    wavfile.write(buf, SR, np.clip(samples * 32767, -32768, 32767)
                  .astype(np.int16))
    return base64.b64encode(buf.getvalue()).decode()


# ------------------------------------------------------------ predictor
class FaceFormerPredictor:
    def __init__(self, ff_dir, device=None):
        # stub the rendering stack demo-era modules import at top level
        for mod in ("pyrender", "trimesh", "cv2"):
            sys.modules.setdefault(mod, types.ModuleType(mod))
        psb = types.ModuleType("psbody")
        psm = types.ModuleType("psbody.mesh"); psm.Mesh = object
        sys.modules.setdefault("psbody", psb)
        sys.modules.setdefault("psbody.mesh", psm)
        sys.path.insert(0, ff_dir)

        import pickle
        import torch
        from transformers import Wav2Vec2Processor
        from faceformer import Faceformer
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        args = argparse.Namespace(
            model_name="vocaset", dataset="vocaset", fps=FPS,
            feature_dim=64, period=30, vertice_dim=15069,
            device=self.device, train_subjects=TRAIN_SUBJECTS)
        self.model = Faceformer(args)

        sd = torch.load(os.path.join(ff_dir, "vocaset", "vocaset.pth"),
                        map_location=self.device)
        want = set(self.model.state_dict().keys())
        fixed = {}
        for key, val in sd.items():
            if key not in want:
                key = (key.replace("pos_conv_embed.conv.weight_g",
                                   "pos_conv_embed.conv.parametrizations.weight.original0")
                          .replace("pos_conv_embed.conv.weight_v",
                                   "pos_conv_embed.conv.parametrizations.weight.original1"))
            fixed[key] = val
        self.model.load_state_dict(fixed)
        self.model = self.model.to(self.device).eval()

        self.processor = Wav2Vec2Processor.from_pretrained(
            "facebook/wav2vec2-base-960h")
        with open(os.path.join(ff_dir, "vocaset", "templates.pkl"), "rb") as f:
            templates = pickle.load(f, encoding="latin1")
        self.template = torch.FloatTensor(
            np.asarray(templates[SUBJECT]).reshape(1, -1)).to(self.device)
        subs = TRAIN_SUBJECTS.split()
        one_hot = np.eye(len(subs))[subs.index(CONDITION)]
        self.one_hot = torch.FloatTensor(
            one_hot.reshape(1, -1)).to(self.device)

    def predict(self, samples):
        """float32 @16k -> (T, 15069) FLAME vertex frames."""
        feat = np.squeeze(self.processor(
            samples, sampling_rate=SR).input_values)
        feat = self.torch.FloatTensor(
            feat.reshape(1, -1)).to(self.device)
        with self.torch.no_grad():
            pred = self.model.predict(feat, self.template, self.one_hot)
        return pred.squeeze().detach().cpu().numpy()


class MockPredictor:
    """No torch needed: sinusoidal jaw motion shaped from head_data.js
    geometry, so --mock exercises bake + playback realistically."""
    def __init__(self, head):
        js = open(os.path.join(REPO, "head_data.js")).read()
        hd = json.loads(js[js.index("{"):js.rindex(";")])
        pos = np.frombuffer(base64.b64decode(hd["pos"]), np.float32)\
                .reshape(-1, 3)
        self.orig_idx = head["origIdx"]
        scene_jaw = (pos[:, 1] < -0.35) & (pos[:, 2] > 0.1)
        self.jaw_flame = self.orig_idx[scene_jaw]      # original FLAME ids

    def predict(self, samples):
        T = min(MAX_FRAMES, max(2, int(len(samples) / SR * FPS)))
        frames = np.zeros((T, 5023, 3), np.float32)
        t = np.arange(T)
        amt = 0.008 * np.maximum(0, np.sin(t / FPS * 2 * np.pi * 2.5))
        frames[:, self.jaw_flame, 1] -= amt[:, None]
        return frames.reshape(T, -1)


# ------------------------------------------------------------------- brain
# A local Ollama model answers the user's typed query; the reply is then fed
# through the SAME TTS + FaceFormer path /speak uses. No cloud API call.
#
#   /ask text --> Brain.reply (Ollama /api/chat) --> clamp --> tts --> say/lips
#
DEFAULT_MODEL = "qwen2.5:3b"        # swappable: --model <ollama tag>
SYSTEM_PROMPT = (
    "You are conduit, a terse, dry desktop companion living as a floating 3D "
    "head. Answer in 1-2 short spoken sentences (max ~40 words). Plain "
    "conversational language. No markdown, lists, code blocks, or emoji - your "
    "reply is read aloud."
)
MAX_REPLY_WORDS = 45        # PRE-FILTER only; not a duration guarantee
MAX_INPUT_CHARS = 600       # reject pathological queries before the model
MAX_HISTORY_TURNS = 6       # rolling window (user+assistant = 12 messages)
MAX_HISTORY_CHARS = 4000    # also trim by size so one long turn can't overflow


class OllamaError(Exception):
    """Local model unreachable, timed out, or returned a bad/empty shape."""


class TooLong(Exception):
    """Synthesized speech would exceed the 600-frame / 20 s FaceFormer cap."""
    def __init__(self, secs):
        super().__init__(f"{secs:.1f}s of speech")
        self.secs = secs


def _clamp_for_speech(reply):
    """Pre-filter a model reply toward the speech cap. NOT a guarantee - `say`
    duration depends on numbers/URLs/punctuation, so Handler._synthesize's
    post-TTS duration guard stays the real cap."""
    reply = " ".join(reply.split())            # collapse whitespace/newlines
    words = reply.split(" ")
    if len(words) <= MAX_REPLY_WORDS:
        return reply
    cut = " ".join(words[:MAX_REPLY_WORDS])
    end = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    return cut[:end + 1] if end > 0 else cut   # back up to a sentence end


def _trim_history(history):
    """Bound the rolling window by BOTH turn count and total chars."""
    del history[:-2 * MAX_HISTORY_TURNS]
    while len(history) > 2 and \
            sum(len(m["content"]) for m in history) > MAX_HISTORY_CHARS:
        del history[:2]                        # drop the oldest user+assistant pair


class Brain:
    """Ollama-backed responder. `warm()` runs on a background thread (a first-run
    pull + warm-up can take minutes); `reply()` runs on the server thread only,
    so `history` is never touched cross-thread. The only shared state is the
    `state` string, written by the warm thread and read by /ping and /ask."""

    def __init__(self, url, model):
        self.url = url.rstrip("/")
        self.model = model
        self.state = "offline"      # offline | pulling | warming | ready | error
        self.history = []

    # --- background lifecycle (off the server thread) -------------------
    def warm(self):
        try:
            tags = self._get("/api/tags", timeout=5)
            names = {m.get("name", "") for m in tags.get("models", [])}
            base = self.model.split(":")[0]
            if not any(n == self.model or n.split(":")[0] == base for n in names):
                self.state = "pulling"
                print(f"[brain] pulling {self.model} (first run, multi-GB)...")
                self._pull()
            self.state = "warming"
            print(f"[brain] warming {self.model}...")
            self._chat([{"role": "user", "content": "hi"}],
                       num_predict=1, timeout=120)
            self.state = "ready"
            print(f"[brain] ready ({self.model})")
        except Exception as e:          # noqa: BLE001 - isolate the bg thread
            self.state = "error"
            print(f"[brain] unavailable: {e}")

    def _get(self, path, timeout):
        with urllib.request.urlopen(self.url + path, timeout=timeout) as r:
            return json.loads(r.read())

    def _pull(self):
        body = json.dumps({"name": self.model}).encode()
        req = urllib.request.Request(
            self.url + "/api/pull", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:   # no timeout: a pull can be minutes
            for _ in r:                          # drain the NDJSON progress stream
                pass

    def _chat(self, messages, num_predict=128, timeout=60):
        body = json.dumps({
            "model": self.model, "messages": messages, "stream": False,
            "options": {"num_predict": num_predict},
        }).encode()
        req = urllib.request.Request(
            self.url + "/api/chat", data=body,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                obj = json.loads(r.read())
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            raise OllamaError(f"ollama unreachable/timeout: {getattr(e, 'reason', e)}")
        except json.JSONDecodeError:
            raise OllamaError("ollama returned malformed JSON")
        content = ((obj.get("message") or {}).get("content") or "").strip()
        if not content:
            raise OllamaError(f"ollama bad/empty response: {str(obj)[:160]}")
        return content

    # --- server-thread call ---------------------------------------------
    def reply(self, text):
        msgs = [{"role": "system", "content": SYSTEM_PROMPT},
                *self.history, {"role": "user", "content": text}]
        out = _clamp_for_speech(self._chat(msgs, num_predict=128))
        self.history += [{"role": "user", "content": text},
                         {"role": "assistant", "content": out}]
        _trim_history(self.history)
        return out


class MockBrain:
    """No Ollama: a short FIXED reply (never an echo - tts_mock duration scales
    with len(text), so echoing a long query could itself blow the 20 s cap)."""
    model = "mock"

    def __init__(self):
        self.state = "ready"
        self.history = []

    def warm(self):
        pass

    def reply(self, text):
        out = "Mock brain online. I heard you, but I'm not really thinking yet."
        self.history += [{"role": "user", "content": text},
                         {"role": "assistant", "content": out}]
        _trim_history(self.history)
        return out


# --------------------------------------------------------------- server
def make_handler(predictor, tts, tts_name, head, mode, brain):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _synthesize(self, samples, source, tts_s):
            """samples -> FaceFormer -> bake -> payload dict. Raises TooLong if
            the clip exceeds the 600-frame / 20 s cap. Does NOT call _send - the
            caller owns the response (shared by /speak, /animate, /ask)."""
            secs = len(samples) / SR
            if secs > MAX_FRAMES / FPS:
                raise TooLong(secs)
            t1 = time.time()
            frames = predictor.predict(samples)
            t_pred = time.time() - t1
            t2 = time.time()
            payload = bake(frames, FPS, head, source=source)
            payload["audioB64"] = wav_b64(samples)
            payload["meta"]["timings"] = {
                "tts_s": round(tts_s, 2),
                "inference_s": round(t_pred, 2),
                "bake_s": round(time.time() - t2, 2)}
            print(f"[{source}] {secs:.1f}s audio -> {payload['frames']} frames "
                  f"(tts {tts_s:.1f}s, infer {t_pred:.1f}s)")
            return payload

        def do_OPTIONS(self):
            self._send(200, {})

        def do_GET(self):
            if self.path == "/ping":
                self._send(200, {
                    "ok": True, "mode": mode, "tts": tts_name,
                    "maxSeconds": MAX_FRAMES / FPS,
                    "brain": brain.state if brain else "offline",
                    "model": getattr(brain, "model", None) if brain else None})
            else:
                self._send(404, {"error": "unknown endpoint"})

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                reply = None    # set only on /ask; threaded into the payload

                if self.path == "/speak":
                    text = (req.get("text") or "").strip()
                    if not text:
                        return self._send(400, {"error": "no text"})
                    t0 = time.time()
                    samples = tts(text, req.get("voice"))
                    t_tts = time.time() - t0
                elif self.path == "/animate":
                    import librosa
                    raw = base64.b64decode(req.get("wavB64", ""))
                    t0 = time.time()
                    samples, _ = librosa.load(io.BytesIO(raw), sr=SR)
                    t_tts = time.time() - t0
                elif self.path == "/ask":
                    text = (req.get("text") or "").strip()
                    if not text:
                        return self._send(400, {"error": "no text"})
                    if len(text) > MAX_INPUT_CHARS:
                        return self._send(400, {"error":
                            f"query too long (max {MAX_INPUT_CHARS} chars)"})
                    state = brain.state if brain else "offline"
                    if state != "ready":
                        return self._send(503, {"error": f"brain {state}",
                                                "brain": state})
                    try:
                        reply = brain.reply(text)
                    except OllamaError as e:
                        return self._send(502, {"error": f"brain error: {e}"})
                    t0 = time.time()
                    samples = tts(reply, req.get("voice"))
                    t_tts = time.time() - t0
                else:
                    return self._send(404, {"error": "unknown endpoint"})

                try:
                    payload = self._synthesize(samples, self.path, t_tts)
                except TooLong as e:
                    if self.path == "/ask":
                        # the reply WAS produced - deliver it as text, speak nothing
                        return self._send(200, {"reply": reply, "tooLong": True,
                            "error": f"reply was {e.secs:.0f}s of speech; "
                                     f"cap is {MAX_FRAMES/FPS:.0f}s"})
                    return self._send(400, {"error":
                        f"audio is {e.secs:.1f}s; FaceFormer caps at "
                        f"{MAX_FRAMES/FPS:.0f}s per request — shorten the text"})

                if reply is not None:
                    payload["reply"] = reply
                self._send(200, payload)
            except Exception as e:  # noqa: BLE001
                import traceback; traceback.print_exc()
                self._send(500, {"error": str(e)})

        def log_message(self, *a):   # quiet default access log
            pass
    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--faceformer", help="path to the FaceFormer clone")
    ap.add_argument("--mock", action="store_true",
                    help="no model: sinusoidal jaw, silent TTS, mock brain")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--head", default=os.path.join(REPO, "head_data.js"))
    ap.add_argument("--ollama-url", default="http://localhost:11434",
                    help="local Ollama endpoint for the /ask brain")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="Ollama model tag for /ask (default: %(default)s)")
    ap.add_argument("--no-llm", action="store_true",
                    help="disable the /ask brain (speech only)")
    args = ap.parse_args()

    head = load_head(args.head)
    if args.mock:
        predictor, mode = MockPredictor(head), "mock"
        tts, tts_name = tts_mock, "mock-silence"
    else:
        if not args.faceformer:
            sys.exit("--faceformer DIR required (or use --mock)")
        print("loading FaceFormer (once)…")
        t = time.time()
        predictor, mode = FaceFormerPredictor(args.faceformer), "faceformer"
        print(f"model ready in {time.time()-t:.1f}s")
        tts, tts_name = pick_tts()

    # Brain (Ollama-backed /ask). Warm it on a BACKGROUND thread so a multi-GB
    # first-run pull never blocks the server, which must answer /ping at once.
    if args.no_llm:
        brain = None
    elif args.mock:
        brain = MockBrain()
    else:
        brain = Brain(args.ollama_url, args.model)
        threading.Thread(target=brain.warm, daemon=True).start()

    httpd = HTTPServer(("127.0.0.1", args.port),
                       make_handler(predictor, tts, tts_name, head, mode, brain))
    brain_desc = "off" if brain is None else f"{getattr(brain, 'model', '?')}"
    print(f"conduit speak server on http://localhost:{args.port} "
          f"(mode={mode}, tts={tts_name}, brain={brain_desc}, "
          f"max {MAX_FRAMES/FPS:.0f}s/request)")
    print("open conduit's index.html — the UPLINK bar will appear")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
