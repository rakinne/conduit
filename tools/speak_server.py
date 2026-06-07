#!/usr/bin/env python3
"""
speak_server.py — on-the-fly text -> talking head for conduit

Runs on YOUR machine (inside the faceformer Python 3.10 env). Loads the
FaceFormer model ONCE at startup, then serves localhost requests from
the conduit page:

  GET  /ping              -> {"ok": true, "mode": "faceformer"|"mock"}
  POST /speak   {"text"}  -> TTS -> FaceFormer -> bake -> ANIM_DATA-shaped
                             JSON + "audioB64" (16 kHz wav)
  POST /animate {"wavB64"}-> same, but you supply the audio

The conduit page auto-detects this server and shows an UPLINK input bar;
typing text there makes the head speak it with generated voice + lips.

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
import subprocess
import sys
import tempfile
import time
import types
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
def tts_say(text, voice=None):
    """macOS built-in TTS -> float32 samples @16 kHz."""
    with tempfile.TemporaryDirectory() as td:
        aiff = os.path.join(td, "tts.aiff")
        cmd = ["say", "-o", aiff]
        if voice:
            cmd += ["-v", voice]
        subprocess.run(cmd + [text], check=True)
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


# --------------------------------------------------------------- server
def make_handler(predictor, tts, tts_name, head, mode):
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

        def do_OPTIONS(self):
            self._send(200, {})

        def do_GET(self):
            if self.path == "/ping":
                self._send(200, {"ok": True, "mode": mode, "tts": tts_name,
                                 "maxSeconds": MAX_FRAMES / FPS})
            else:
                self._send(404, {"error": "unknown endpoint"})

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                t0 = time.time()
                if self.path == "/speak":
                    text = (req.get("text") or "").strip()
                    if not text:
                        return self._send(400, {"error": "no text"})
                    samples = tts(text, req.get("voice"))
                elif self.path == "/animate":
                    import librosa
                    raw = base64.b64decode(req.get("wavB64", ""))
                    samples, _ = librosa.load(io.BytesIO(raw), sr=SR)
                else:
                    return self._send(404, {"error": "unknown endpoint"})
                t_tts = time.time() - t0

                secs = len(samples) / SR
                if secs > MAX_FRAMES / FPS:
                    return self._send(400, {"error":
                        f"audio is {secs:.1f}s; FaceFormer caps at "
                        f"{MAX_FRAMES/FPS:.0f}s per request — shorten the text"})

                t1 = time.time()
                frames = predictor.predict(samples)
                t_pred = time.time() - t1
                t2 = time.time()
                payload = bake(frames, FPS, head, source=self.path)
                payload["audioB64"] = wav_b64(samples)
                payload["meta"]["timings"] = {
                    "tts_s": round(t_tts, 2),
                    "inference_s": round(t_pred, 2),
                    "bake_s": round(time.time() - t2, 2)}
                print(f"[{self.path}] {secs:.1f}s audio -> "
                      f"{payload['frames']} frames "
                      f"(tts {t_tts:.1f}s, infer {t_pred:.1f}s)")
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
                    help="no model: sinusoidal jaw, silent TTS")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--head", default=os.path.join(REPO, "head_data.js"))
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

    httpd = HTTPServer(("127.0.0.1", args.port),
                       make_handler(predictor, tts, tts_name, head, mode))
    print(f"conduit speak server on http://localhost:{args.port} "
          f"(mode={mode}, tts={tts_name}, max {MAX_FRAMES/FPS:.0f}s/request)")
    print("open conduit's index.html — the UPLINK bar will appear")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
