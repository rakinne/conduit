# CLAUDE.md — conduit

Context file for AI-assisted work on this repo. Read this before changing
anything; the decision log explains *why* the current shape exists.

## What this is

A single-page Three.js (r128) scene: a disembodied, Matrix-green 3D head
in the style of The Black Eyed Peas' *The E.N.D.* album cover. The head:

- wears an animated LED-circuit skin (canvas texture: green banding,
  hot/dead pixels, upward pulse, glitch row-tearing)
- has hollow void eyes (black spheres overfilling empty eye sockets) and
  a mouth slit
- tracks the cursor within hard rotation limits and has autonomous idle
  behavior (shoulder glances, "notepad" dips)
- **shape-shifts** between five baked identities through a turbulent
  mid-morph (the reference: a face-A → boiling smear → face-B GIF)
- **speaks**: plays back speech-driven facial animation (FaceFormer)
  synced to audio, composing with everything above

## Branches

- `main` — original procedural head (sphere sculpt, self-contained)
- `feature/flame-integration` — current work: head is the FLAME 2023
  Open statistical model; adds the offline-bake pipelines below

## File map

| File | Role |
| --- | --- |
| `index.html` | entire runtime (scene, texture, morph choreography, constraints, speech playback) |
| `head_data.js` | generated — baked head geometry + morph deltas + rigs (base64) |
| `anim_data.js` | generated — baked speech clip, sparse int16 (base64) |
| `tools/convert_flame.py` | FLAME pkl → `head_data.js` |
| `tools/bake_anim.py` | FaceFormer .npy → `anim_data.js` |
| `tools/make_templates.py` | synthesizes FaceFormer's `vocaset/templates.pkl` from FLAME |
| `tools/templates.pkl` | pre-generated output of the above |
| `tools/run_faceformer.sh` | env setup + patched CPU inference on the user's machine |
| `tools/requirements-faceformer-py310.txt` | relaxed FaceFormer deps for Python 3.10 |
| `assets/flame2023_Open.pkl` | gitignored (53 MB); download from flame.is.tue.mpg.de |

## Commands

```bash
# regenerate head geometry (needs the gitignored FLAME pkl)
python3 tools/convert_flame.py assets/flame2023_Open.pkl

# bake a speech clip from a FaceFormer prediction
python3 tools/bake_anim.py prediction.npy --fps 30 --wav speech.wav

# on the user's machine, inside a FaceFormer clone:
bash run_faceformer.sh demo/wav/your.wav   # → demo/result/your.npy
```

## Key integration contracts

**`head_data.js`** (`const HEAD_DATA = {...}`):
- `pos`/`uv`/`idx`: base mesh, base64 Float32/Float32/Uint16. Base mesh
  IS identity 0.
- `targets[0..3]`: per-vertex deltas to identities 1–4 (morphTargetsRelative).
  `targets[4..5]`: chaos noise fields used mid-morph.
- `rigs[i]`: per-identity eye centroids/radii + mouth anchor (eyes/mouth
  are separate props, repositioned by lerping rigs during morphs).
- `origIdx`: original FLAME vertex index (0–5022) per final vertex —
  threaded through the eyeball strip and UV-seam duplication. **This is
  the animation handshake**: any FLAME-topology (5023-vert) animation
  maps onto our mesh through it.
- `xform`: {center, scale} normalization applied at convert time; baked
  animation deltas must be multiplied by `scale` (centers cancel).

**`anim_data.js`** (`const ANIM_DATA = {...}`):
- sparse format: `sparseIdx` (Uint16 vert ids into OUR mesh) +
  `data` (Int16, frames × sparse × 3) × `scale` (dequant factor).
- deltas are vs **frame 0** of the prediction → the model's subject
  template cancels; that's why a synthetic templates.pkl is valid.

**Morph slot budget (hard limit)** — three r128 standard materials
support 8 morph influences (no morphNormals enabled):
slots 0–3 identities, 4–5 chaos, 6 speech, 7 free. Adding targets beyond
8 requires custom shader work.

## Key decisions (chronological, with rationale)

1. **Rotation constraints**: yaw ±1.0 rad (~57°, "glance past your
   shoulder"), pitch −0.12…+0.50 rad ("consult a notepad"). Hard-clamped
   every frame; user-specified and load-bearing for the character.
2. **Shape-shift = morph targets + chaos spike**, not a clean lerp. Two
   noise targets pulse on a sine bump mid-transition while the LED skin
   tears — reproduces the reference frames' stable → boil → stable arc.
3. **No real faces / no face datasets.** Identities are statistical or
   procedural, never likenesses. (Original ask referenced training-set
   faces; replaced with parameterized/sampled skulls by design.)
4. **Procedural → FLAME 2023 Open** when the user supplied the pkl.
   Chosen because CC-BY-4.0 (first FLAME release without the
   non-commercial restriction). Cite Li et al., SIGGRAPH Asia 2017.
5. **Identities are *solved*, not sampled**: least squares over the
   leading 20 shape PCs against five opposed craniofacial metric
   profiles (face length, cheek width, jaw width, nose protrusion,
   head depth), betas clipped to ±3σ. Distinct on purpose.
6. **Eyeballs stripped via connected components** (FLAME = head + 2
   eyeball components); void-eye props overfill the empty sockets.
7. **Embedded base64 JS instead of glTF**: no GLTFLoader dependency, no
   fetch/CORS issues when opened from file://, single-file previews
   possible. Cylindrical UVs with seam-crossing vertex duplication
   (indices must stay < 65536 — currently ~3970).
8. **Speech: offline inference → baked playback.** No inference server,
   no browser ML. FaceFormer chosen over VOCA (TF1-era) and GAGAvatar
   (different problem) because it outputs **vertices on FLAME topology**
   (15069 = 5023×3); param-output models (ARTalk etc.) would need a
   FLAME decoder in the browser.
9. **Speech composes via a 7th morph slot** held at influence 1, with
   frames lerped into its attribute each tick — so the head can keep
   talking through an identity morph. Static mouth-slit prop hides while
   speaking (FLAME's real lips animate).
10. **Sparse anim format** (`--min-move`, default 0.3 mm): speech models
    micro-jitter every vertex; sub-threshold motion is invisible but was
    ~40% of file size. 99.7% of motion energy retained on the test clip.
11. **FaceFormer-on-modern-machines shims** (all in `run_faceformer.sh`):
    Python 3.10 env (upstream pins have no 3.11/3.12 wheels; never pip
    install the stray `pickle` line), `feature_projection` tuple patch,
    `torch.load` map_location for CPU-only, weight-norm key rename
    (`weight_g/weight_v` → `parametrizations.weight.original0/1`),
    rendering stack stubbed out (only the .npy matters). Patches are
    python-based — BSD sed on macOS broke the sed version.

## Conventions & gotchas

- Three.js r128 from cdnjs; no OrbitControls, no CapsuleGeometry in this
  environment. Materials need `morphTargets: true` (r128 API).
- Validate headlessly before shipping: extract runtime sections from
  `index.html` and run them in Node against `three@0.128.0` (see git
  history for the test pattern). There is no browser in the dev sandbox.
- Single-file previews are built by inlining `head_data.js`/`anim_data.js`
  (and audio as a data URI) into `index.html` — keep the script-src lines
  exactly as-is; the build does string replacement on them.
- `test.wav` (FaceFormer's demo audio) is deliberately not committed.
- Serve `*_data.js` gzipped in production; int16 base64 compresses ~4×.
- Status line vocabulary: `FORM XX · STABLE` / `RESEQUENCING → FORM XX`
  / `· SPEAKING`. Keep the register.
