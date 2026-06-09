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
- **answers**: a local LLM brain (Ollama + a small model) turns a typed
  question into a short spoken reply through the speech path above — no
  cloud API. Server (`/ask`) + page (UPLINK) wired; verified end-to-end in
  mock mode. Real lips/audio await a run on the FaceFormer machine (see
  `TODOS.md`).

## Branches

- `main` — original procedural head (sphere sculpt, self-contained)
- `feature/flame-integration` — head is the FLAME 2023 Open statistical
  model; adds the offline-bake pipelines below
- `feature/desktop-overlay` — current work: native macOS shell + the
  local-LLM `/ask` brain

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
| `tools/speak_server.py` | localhost server: typed text → speech (`/speak`) **and** query → spoken answer (`/ask`, local LLM via Ollama) |
| `tools/test_speak_ask.py` | unit tests for the `/ask` brain (stubs numpy + Ollama; runs in any env) |
| `tools/test_frontend.mjs` | headless Node test of `index.html`'s UPLINK routing (`/ask` only when brain ready) |
| `tools/requirements-mock.txt` | numpy+scipy — the minimal env to run `--mock` without FaceFormer |
| `tools/requirements-phoenix.txt` | optional dep for LOCAL `/ask` conversation tracing (Arize Phoenix) |
| `Makefile` | repeatable dev harness: `make test` / `test-frontend` / `mock-venv` / `mock` / `serve` / `trace-ui` |
| `TODOS.md` | remaining `/ask` validation + the future Docker/repeatability phase |
| `desktop/ConduitHead.swift` | native macOS shell — floating, transparent, always-on-top head |
| `desktop/build.sh` | builds `ConduitHead.app` (vendors three.js, rewrites src, compiles Swift) |
| `desktop/README.md` | desktop shell usage + tuning |
| `assets/flame2023_Open.pkl` | gitignored (53 MB); download from flame.is.tue.mpg.de |

## Commands

```bash
# regenerate head geometry (needs the gitignored FLAME pkl)
python3 tools/convert_flame.py assets/flame2023_Open.pkl

# bake a speech clip from a FaceFormer prediction
python3 tools/bake_anim.py prediction.npy --fps 30 --wav speech.wav

# on the user's machine, inside a FaceFormer clone:
bash run_faceformer.sh demo/wav/your.wav   # → demo/result/your.npy

# speech + LLM brain server, via the Makefile dev harness:
# /ask needs Ollama running; pull a small model once: `ollama pull qwen2.5:3b`
make serve FACEFORMER=~/Downloads/FaceFormer-main   # real server (faceformer env)
make mock-venv && make mock                         # mock loop: no FaceFormer/torch/Ollama
make test-all                                       # brain + frontend tests (no heavy deps)
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

**`tools/speak_server.py` endpoints** (localhost:8765, CORS restricted to local
origins — `file://`/`Origin: null` + localhost/loopback only, not `*`; `_allowed_origin`):
- `GET /ping` → `{ok, mode, brain, model, maxSeconds}`. `brain` is a status
  enum the page polls: `offline | pulling | warming | ready | error`.
- `POST /speak {text}` / `POST /animate {wavB64}` → ANIM_DATA-shaped payload +
  `audioB64`. `POST /ask {text}` → same payload **plus** `reply`; requires
  `brain == "ready"` (else 503), 502 on an Ollama error.
- All three share `Handler._synthesize(samples, source, tts_s)`, which returns
  the payload and raises `TooLong` past the 600-frame/20s cap (the caller
  sends). `/ask` length safety is **two layers**: a word pre-clamp AND the
  post-TTS duration guard — word count is not a duration proxy. On too-long,
  `/ask` returns `{reply, tooLong:true}` (text delivered, nothing spoken).

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
12. **Desktop shell = native Swift + WKWebView, not Electron/Tauri.** The
    head can run as a floating, transparent, always-on-top macOS app
    (`desktop/`). Swift over Electron (no bundled Chromium; ~9 MB app,
    ~80 MB dedicated RAM vs Electron's far heavier footprint — the user's
    stated resource concern) and over Tauri (Rust build + plugin needed
    for the one feature that matters here). The signature feature —
    **the head watches the cursor anywhere on screen, even unfocused** —
    is a few lines of AppKit (`NSEvent` global mouse monitor, which needs
    *no* Accessibility permission; only keyboard monitors do). Window
    opacity = `NSWindow.alphaValue`; always-on-top = `.floating` level +
    all-Spaces `collectionBehavior`; click-through = `ignoresMouseEvents`,
    toggled by a Carbon global hotkey (`⌥⌘H`, also permission-free).
13. **Overlay mode is additive to `index.html`, not a fork.** The shell
    sets `window.__CONDUIT_OVERLAY` (a `WKUserScript` at documentStart;
    `?overlay=1` works in a browser too). That hides the framed box and
    swaps the page's own mouse listeners for shell-driven hooks —
    `window.__conduitPoint(nx,ny)` (normalized, page convention: +x right
    / +y down) and `window.__conduitGrab(bool)`. The renderer was already
    `alpha:true`, so the canvas is transparent for free. Normal browser
    sessions are byte-for-byte unaffected (the gate is false). **New
    integration contract**: keep these three globals stable — the Swift
    shell calls them by name.
14. **Query answering = local LLM, no cloud API.** A small open model
    (default `qwen2.5:3b`) runs under **Ollama** on localhost; the head
    answers typed questions aloud through the existing speech path. Rejected:
    **Haiku** (cloud-only, can't be downloaded/run local), **GLM-5.1** (744B
    MoE, ~176 GB even quantized — "cheap to call in the cloud" ≠ "small enough
    to run local"), **in-browser WebLLM/WebGPU** (WKWebView ships no WebGPU,
    so the *desktop* pet would stay brainless), and **OpenClaw as the brain**
    (it orchestrates Claude Code over the Anthropic cloud API — breaks the
    no-API constraint, and heavyweight agent turns are the wrong shape for
    snappy ≤20s replies). The brain is a *responder* inserted into the
    existing `speak_server` UPLINK pattern, not a new service.
15. **Brain runtime contract (Codex-hardened).** The model warms on a
    **background daemon thread** so a multi-GB first pull never blocks the
    single-threaded `HTTPServer` (which must answer `/ping` at once);
    `brain_state` is the one cross-thread flag. Ollama is reached via stdlib
    `urllib` with **explicit timeouts** + response-shape validation, and `say`
    runs under a subprocess timeout — on a single-threaded server any hang
    freezes the whole UPLINK. History is a rolling window bounded by BOTH
    turns (~6) and chars. When the brain is not `ready`, the page must show
    `BRAIN OFFLINE/LOADING` and disable ask — it must NOT silently speak the
    user's question back (that was the original glib "fall back to /speak").
16. **Observability = LOCAL tracing only (Arize Phoenix), never cloud.** The
    `/ask` conversation can be traced for observability, but the trace data — the
    user's questions + the head's replies — must stay on the machine. This
    extends #14's local-only *inference* ethos to *telemetry*. **Rejected
    LangSmith**: both the cloud SaaS (conversation logs would leave the box) and
    self-hosting it (too heavyweight). Phoenix runs a localhost collector
    (`:6006`), stores traces on-disk, needs no account, speaks OpenTelemetry/
    OpenInference. Integration is **opt-in and inert by default**: `CONDUIT_TRACE=1`
    (exported, or in the repo `.env` — the server loads it at startup via a tiny
    stdlib loader, no python-dotenv) turns it on; otherwise (or with
    `arize-phoenix` absent) `TRACER` is a no-op
    shim and the brain stays a stdlib-only, no-extra-dep path — tests import the
    module with stdlib alone. Each turn is a `conduit.ask` chain span
    (question→reply) wrapping an `ollama.chat` LLM span (model + token counts from
    Ollama's own `/api/chat` accounting). Override the collector with
    `PHOENIX_COLLECTOR_ENDPOINT`, the project name with `CONDUIT_TRACE_PROJECT`.

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
- Local `/ask` tracing is opt-in: `CONDUIT_TRACE=1` (set it in the repo `.env`,
  auto-loaded by the server, or export it) traces each turn to a localhost Arize
  Phoenix collector. Off by default, no cloud, no-op without the client package
  (decision #16). The endpoint alone (`PHOENIX_COLLECTOR_ENDPOINT`) does nothing
  without `CONDUIT_TRACE`. View at http://localhost:6006. Gotchas that cause a
  silent "waiting for traces":
  - **`phoenix.otel.register()` defaults to gRPC on `:4317` and ignores
    `PHOENIX_COLLECTOR_ENDPOINT`.** `_make_tracer` pins the HTTP collector
    explicitly (`http://localhost:6006/v1/traces`) so spans hit the same port as
    the UI. Don't "simplify" that back to a bare `register(project_name=...)`.
  - **Packaging is split.** The *server* only needs the light client
    `arize-phoenix-otel` (`tools/requirements-phoenix.txt`; `make trace-deps`
    installs it into the mock venv — the faceformer conda env usually already has
    phoenix). The *UI* needs the full `arize-phoenix` (`make trace-ui`, run from
    system python). If the startup log says `Phoenix unavailable`, the client is
    missing from *that* env; if no `[trace]` line prints at all, `CONDUIT_TRACE`
    isn't set.
- Serve `*_data.js` gzipped in production; int16 base64 compresses ~4×.
- Status line vocabulary: `FORM XX · STABLE` / `RESEQUENCING → FORM XX`
  / `· SPEAKING` / `· THINKING` / `BRAIN ONLINE (model)` / `BRAIN LOADING`
  / `BRAIN OFFLINE` / `BRAIN ERROR: …`. Keep the register.
- The `/ask` brain is optional: `--no-llm` disables it, and the page stays
  speech-only if `brain` never reaches `ready`. It needs Ollama running
  locally (`ollama serve`) with the model pulled (`ollama pull qwen2.5:3b`).
  An `https` page can't call `http://localhost` (mixed content) — open the
  page from `file://`/`http`, which the desktop shell does.
