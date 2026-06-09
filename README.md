# conduit

A disembodied, Matrix-green 3D head rendered with Three.js — inspired by the
circuit-skinned face on The Black Eyed Peas' *The E.N.D.* album cover.

## Features

- Procedurally sculpted abstract head (no external model files)
- Animated LED-circuit skin: green banding, hot/dead pixels, upward pulse
- Hollow void eyes with glowing rims, subtle mouth slit
- Matrix rain backdrop, drifting motes, halo glow, scanline overlay
- Cursor-tracking gaze with hard rotation constraints:
  - Yaw clamped to ±57° (a glance past your shoulder, never further)
  - Pitch clamped from a slight upward tilt to ~29° down (consulting a notepad)
- Autonomous idle behavior after 2.5s of inactivity: wandering glances and
  recurring "note-checking" dips
- **Shape-shifting**: the head cycles through five procedurally sculpted
  identities (distinct skulls, brows, noses, cheekbones, jaws, lips) using
  Three.js morph targets. Mid-transition, two noise "chaos" morphs spike so
  the face boils and smears before settling — synced with LED-skin row
  tearing and flicker. Eyes and mouth re-rig per identity. A status line
  reports the current form and announces RESEQUENCING during morphs.

## Run

Open `index.html` in a browser (it loads `head_data.js` alongside it).
Three.js (r128) is loaded from cdnjs, so an internet connection is required.

## FLAME integration (this branch)

The head is no longer a procedural sphere sculpt — it's the **FLAME 2023
Open** statistical head model (5023 verts; eyeballs stripped to 3931 + seam
duplicates), with five identities baked from the 300-component shape space.

Pipeline (`tools/convert_flame.py`):
1. Parse `flame2023_Open.pkl` (chumpy shim → numpy)
2. Split connected components: head + 2 eyeballs
3. Solve five identity beta vectors by least squares against target
   craniofacial metric profiles (face length, cheek width, jaw width, nose
   protrusion, head depth) — deliberate, distinct skulls rather than random
   shape-space draws; betas clipped to ±3σ
4. Bake vertices, strip eyeballs, record per-identity eye centroids/radii
   and a mouth anchor (front-vertex band, neck-safe)
5. Normalize to scene scale, cylindrical UV unwrap with seam-crossing
   vertex duplication
6. Add 2 chaos noise deltas; emit `head_data.js` (base64 buffers + rig JSON)

The runtime builds a `BufferGeometry` with `morphTargetsRelative = true`:
base mesh = identity 0, targets 0–3 = deltas to identities 1–4, targets
4–5 = chaos. The void eyes are black spheres slightly overfilling the now
empty FLAME eye sockets, repositioned per identity by the baked rig.

To regenerate: download FLAME 2023 Open from https://flame.is.tue.mpg.de
(CC-BY-4.0), place the pkl at `assets/flame2023_Open.pkl` (gitignored),
then `python3 tools/convert_flame.py assets/flame2023_Open.pkl`.

## Speech-driven animation (Phase 6)

The page has an optional speech mode: if `anim_data.js` is present, the
status line gains `[SPACE] SPEAKS` and spacebar plays per-frame vertex
motion (one dynamic morph slot at influence 1, composing with the identity
and chaos morphs) in sync with an optional audio file.

Producing `anim_data.js` (on a machine with internet + PyTorch):
1. `git clone https://github.com/EvelynFan/FaceFormer` and install its
   requirements (PyTorch, transformers, librosa — the wav2vec2 audio
   encoder auto-downloads from the Hugging Face Hub on first run)
2. Obtain `vocaset.pth` pretrained weights (README links; they have
   rotted before — see FaceFormer issue #93 for author-provided mirrors)
   and `FLAME_sample.ply` from the VOCA repo as the template
3. Run the vocaset demo command from FaceFormer's README on your .wav —
   it emits a `(T, 15069)` .npy of FLAME-topology vertex frames at 30fps
4. `python3 tools/bake_anim.py prediction.npy --fps 30 --wav speech.wav`
   in this repo — it remaps frames through `origIdx`, applies the scene
   transform from `head_data.js`, quantizes to int16, and writes
   `anim_data.js` (serve gzipped; it compresses ~4x)
5. Put your .wav next to `index.html`, reload, press SPACE

### On-the-fly speech (UPLINK)

`tools/speak_server.py` turns the manual pipeline into a one-keystroke loop.
Run it on your machine inside the faceformer env:

    source .venv-faceformer/bin/activate   # or: conda activate faceformer
    python3 tools/speak_server.py --faceformer ~/Downloads/FaceFormer-main

It loads the model once, then serves localhost:8765. When conduit's page
detects it, an UPLINK input bar appears — type text, hit TRANSMIT, and the
head speaks it with generated voice (macOS `say`) and FaceFormer lips.
`--mock` runs without torch/model for plumbing tests. Limits: 20 s of
speech per request (FaceFormer's positional encoding caps at 600 frames);
expect inference to take roughly real-time-or-slower on CPU. The uplink
only works from pages served over http/file (an https page can't call
http://localhost — mixed content).

### Ask the head (local LLM brain)

The same UPLINK server can give the head a *brain*: with a local LLM running, a
typed question is **answered aloud** instead of just read back. No cloud API, no
per-token cost, fully offline and private.

It runs on **Ollama** with a small open model (default `qwen2.5:3b`, ~2–3 GB,
swap with `--model`):

    ollama pull qwen2.5:3b            # once
    ollama serve                      # if not already running
    python3 tools/speak_server.py --faceformer ~/Downloads/FaceFormer-main

`speak_server` adds a `POST /ask {text}` endpoint that generates a short reply
(1–2 sentences, clamped to the 20 s speech cap), then speaks it through the
FaceFormer pipeline. It keeps a short rolling conversation memory, warms the
model on a background thread (the first pull is multi-GB, and the server stays
responsive throughout), and reports a brain status via `/ping`
(`offline`/`pulling`/`warming`/`ready`/`error`). `--no-llm` disables it;
`--mock` exercises the whole `/ask`→speak loop with no model or torch.

Rejected alternatives (and why): **Haiku** (cloud-only, not downloadable),
**GLM-5.1** (744B params — far too big to run on a desktop), **in-browser
WebLLM** (WKWebView has no WebGPU, so the desktop app would stay brainless), and
**OpenClaw** (its intelligence is Claude over the cloud API — breaks the no-API
constraint).

When the brain is ready the UPLINK bar switches to **ASK** mode (placeholder
`ASK THE HEAD`); while it warms, or with `--no-llm`, it stays a literal **SPEAK**
bar — the mode is shown in the placeholder/button and never silently swapped.

**Status:** server (`/ask`) and page (UPLINK) are wired and tested —
`make test-all` (27 assertions: brain + frontend routing) and the full
`/ping`/`/ask`/`/speak` contract verified end-to-end in mock mode (`make mock`,
numpy+scipy only). Real lips + audio await a run on a FaceFormer machine; see
`TODOS.md`.

#### Dev harness

A `Makefile` runs the backend on any machine, with or without FaceFormer:

    make test-all   # brain + frontend tests (no heavy deps)
    make mock-venv  # one-time: minimal numpy+scipy venv
    make mock       # run the /ask -> speak loop in mock mode
    make serve FACEFORMER=~/Downloads/FaceFormer-main   # the real thing

`bake_anim.js` output is sparse: verts whose peak motion is below
`--min-move` (default 0.3 mm — invisible at typical view size) are dropped,
which cuts file size ~40% with 99.7% of motion energy retained. A baked
demo clip (`anim_data.js`, FaceFormer on its bundled `demo/wav/test.wav`)
is committed so the repo lip-syncs out of the box; drop the matching
`test.wav` next to `index.html` for audio (not committed — it's FaceFormer's
asset).

Any VOCASET-trained vertex-output model works the same way (CodeTalker,
etc.) — the only contract is FLAME topology, `(T, 5023, 3)`.

### Environment gotcha (Python 3.10 only, + setuptools<81)

FaceFormer's `requirements.txt` pins 2021-era versions (`scipy==1.7.1`,
`torch==1.9.0`, `transformers==4.6.1`) with no wheels for Python 3.11/3.12
— that's the `No matching distribution found for scipy==1.7.1` error.
Don't force nearest versions; use a Python 3.10 env instead. Two helpers
in `tools/` automate it:

- `requirements-faceformer-py310.txt` — relaxed, 3.10-compatible, inference
  only (drops the pyrender/trimesh/opencv render stack you don't need, and
  the stray `pickle` line which is stdlib). Copy it into your FaceFormer clone.
- `run_faceformer.sh` — creates the conda env, installs the above, applies a
  one-line patch to `wav2vec.py` (modern `transformers` returns a tuple from
  `feature_projection`), and runs prediction CPU-only, skipping rendering.
  `bash run_faceformer.sh demo/wav/your.wav` → `demo/result/your.npy`.

**`pkg_resources` / `setuptools` trap:** modern setuptools (82+) removed
`pkg_resources`, which the pinned librosa 0.9.2 still imports — so even a
correct 3.10 env fails with `No module named 'pkg_resources'` until you
`pip install "setuptools<81"`. The requirements file now pins it; existing
envs need that one line. And don't try to install on 3.12/3.13 at all: torch
2.2.2 has no wheel there, so pip builds from Rust source and dies on a cargo
`edition2024` error — a red herring; the fix is always Python 3.10.

**Attribution:** head geometry derived from FLAME — T. Li, T. Bolkart,
M. J. Black, H. Li, J. Romero, *Learning a model of facial shape and
expression from 4D scans*, ACM TOG (Proc. SIGGRAPH Asia), 2017.

## Tuning

Key constants live near the top of each section in `index.html`:

- `YAW_MAX`, `PITCH_UP`, `PITCH_DOWN` — rotation limits
- `CELL`, `GAP` — circuit-grid density
- `IDENTITIES` — the five face parameter sets (add/edit skull params and rigs)
- `MORPH_MS`, `holdDur` — transition speed and time between shifts
- `chaos()` amplitudes — how violently the face boils mid-morph
- `idleTargets()` — idle gaze choreography
