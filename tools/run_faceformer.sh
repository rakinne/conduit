#!/usr/bin/env bash
# run_faceformer.sh — set up FaceFormer and predict FLAME vertices from a wav,
# on a modern machine (Python 3.10), CPU-only, no rendering stack.
#
# Produces demo/result/<wavname>.npy of shape (T, 15069) — exactly what
# conduit's tools/bake_anim.py consumes.
#
# Prereqs you provide:
#   - conda (or another way to get a Python 3.10 interpreter)
#   - FaceFormer cloned, this script run from its root
#   - vocaset.pth placed at  vocaset/vocaset.pth
#   - your audio at           demo/wav/<your>.wav   (16 kHz mono recommended)
#
# Usage:  bash run_faceformer.sh demo/wav/your.wav
set -euo pipefail

WAV="${1:-demo/wav/test.wav}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# 1. environment ------------------------------------------------------------
# Gets a Python 3.10 interpreter via whichever tool is available:
#   conda -> python3.10 on PATH -> uv (which can download 3.10 itself).
# If none exist, prints a one-line install command and exits.
if command -v conda >/dev/null 2>&1; then
  echo "[env] using conda"
  if ! conda env list | grep -q faceformer; then
    conda create -n faceformer python=3.10 -y
  fi
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate faceformer
  PIP="pip"
elif command -v python3.10 >/dev/null 2>&1; then
  echo "[env] using python3.10 venv"
  [ -d .venv-faceformer ] || python3.10 -m venv .venv-faceformer
  # shellcheck disable=SC1091
  source .venv-faceformer/bin/activate
  PIP="pip"
elif command -v uv >/dev/null 2>&1; then
  echo "[env] using uv (downloads Python 3.10 if needed)"
  [ -d .venv-faceformer ] || uv venv .venv-faceformer --python 3.10
  # shellcheck disable=SC1091
  source .venv-faceformer/bin/activate
  PIP="uv pip"
else
  echo "No conda, python3.10, or uv found."
  echo "Quickest fix (no admin rights needed) — install uv, then rerun:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "  (then open a new terminal, or: source \$HOME/.local/bin/env)"
  exit 1
fi

$PIP install -r "${HERE}/requirements-faceformer-py310.txt"

# 2. patch wav2vec.py: feature_projection returns a tuple in modern
#    transformers; FaceFormer assigns it straight to a tensor. Take [0].
#    Idempotent — only patches if the raw assignment is still present.
if grep -q 'hidden_states = self.feature_projection(hidden_states)$' wav2vec.py; then
  sed -i \
    's/hidden_states = self.feature_projection(hidden_states)$/hidden_states = self.feature_projection(hidden_states)\n        if isinstance(hidden_states, tuple): hidden_states = hidden_states[0]/' \
    wav2vec.py
  echo "patched wav2vec.py (feature_projection tuple)"
fi

# 3. predict (NOT render). demo.py defaults --device cuda and also calls
#    render_sequence(), which needs pyrender/mesh libs we skip. We import
#    its test_model directly, forcing CPU, and stop after the .npy is saved.
python - "$WAV" <<'PY'
import sys, types, argparse, os, torch
# stub out rendering imports so `import demo` doesn't require pyrender etc.
for mod in ("pyrender", "trimesh", "cv2"):
    sys.modules.setdefault(mod, types.ModuleType(mod))
sys.modules.setdefault("psbody", types.ModuleType("psbody"))
sys.modules.setdefault("psbody.mesh", types.ModuleType("psbody.mesh"))
sys.modules["psbody.mesh"].Mesh = object

import demo  # noqa: E402

wav = sys.argv[1]
test_name = os.path.splitext(os.path.basename(wav))[0]
a = argparse.Namespace(
    model_name="vocaset", dataset="vocaset",
    fps=30, feature_dim=64, period=30, vertice_dim=15069,
    device="cuda" if torch.cuda.is_available() else "cpu",
    train_subjects=("FaceTalk_170728_03272_TA FaceTalk_170904_00128_TA "
                    "FaceTalk_170725_00137_TA FaceTalk_170915_00223_TA "
                    "FaceTalk_170811_03274_TA FaceTalk_170913_03279_TA "
                    "FaceTalk_170904_03276_TA FaceTalk_170912_03278_TA"),
    test_subjects="FaceTalk_170809_00138_TA FaceTalk_170731_00024_TA",
    wav_path=wav, result_path="demo/result",
    condition="FaceTalk_170913_03279_TA",
    subject="FaceTalk_170809_00138_TA",
    template_path="templates.pkl",
)
print(f"device: {a.device}")
demo.test_model(a)
out = os.path.join(a.result_path, test_name + ".npy")
import numpy as np
print(f"\nSAVED {out}  shape={np.load(out).shape}  (expect (T, 15069))")
print("Next: in your conduit repo, run")
print(f"  python3 tools/bake_anim.py {out} --fps 30 --wav {os.path.basename(wav)}")
PY
