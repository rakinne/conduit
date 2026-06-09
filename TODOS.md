# TODOS — conduit

## Local-LLM `/ask` brain (current feature)

**Done**
- `tools/speak_server.py`: `/ask` endpoint, `Brain` + `MockBrain`, DRY
  `_synthesize`, `/ping` status enum, background warm/pull thread, `say`
  subprocess timeout, `--ollama-url`/`--model`/`--no-llm` flags.
- `index.html`: UPLINK wired to `/ask` with `/ping` polling (flips live when the
  brain warms), brain-state UI, `tooLong` + error handling, literal `/speak`
  fallback that is explicit (placeholder/button) not silent.
- Tests: `tools/test_speak_ask.py` (17, brain) + `tools/test_frontend.mjs` (10,
  routing). Mock server contract (`/ping` `/ask` `/speak`) verified end-to-end
  with numpy+scipy only (`make mock`), no FaceFormer/torch/Ollama.

**Left** (browser visual pass + the >20 s path; the real-stack e2e is DONE)
- [x] Real end-to-end on the FaceFormer box — VERIFIED 2026-06-08: "capital of
      Peru?" -> qwen2.5:3b "The capital of Peru is Lima." + 61 FaceFormer frames
      + real `say` audio; follow-up resolved "there" -> Lima (rolling memory
      works); single-threaded server stayed responsive across turns.
- [ ] Confirm a real >20 s reply trips the post-TTS `TooLong` guard (mock audio
      is silence, so this only exercises with real `say`).
- [ ] Browser / desktop-app visual pass: `· THINKING` → `· SPEAKING`,
      `BRAIN ONLINE/LOADING/OFFLINE`, the `tooLong` text display.
- [ ] Tune `SYSTEM_PROMPT` / `MAX_REPLY_WORDS` against a real model's verbosity.

## Observability — LOCAL conversation tracing (Arize Phoenix)

**Done**
- `speak_server.py`: opt-in `CONDUIT_TRACE=1` tracing. Each `/ask` turn → a
  `conduit.ask` chain span (question in / reply out) wrapping an `ollama.chat`
  LLM span (model + prompt/completion token counts from Ollama's own response
  accounting). No-op shim when off or when `arize-phoenix` is absent, so the
  brain stays stdlib-only. `tools/requirements-phoenix.txt`, `make trace-ui`.
  Tests in `test_speak_ask.py` (no-op transparency + error propagation + usage
  capture). Local only — nothing leaves the machine (decision #16).

**Left**
- [ ] Real run: `pip install arize-phoenix` in the faceformer env, `make trace-ui`,
      then `CONDUIT_TRACE=1 make serve`; confirm spans + token counts render for a
      live qwen2.5:3b turn at http://localhost:6006.
- [ ] Optionally extend the `conduit.ask` span with child spans for the speech
      pipeline (TTS + FaceFormer timings, already in `payload.meta.timings`) and
      tag `tooLong` / error turns.
- [ ] Consider a Phoenix service in the Docker phase (compose) so traces persist
      across runs without a separately-launched UI.

## Repeatable backend (Docker) — future phase

Goal: make `speak_server` + Ollama reproducible on any machine. The biggest win
is that the env shims in `run_faceformer.sh` (Python 3.10 pin, weight-norm
rename, tuple patch) become a deterministic Dockerfile instead of per-machine
surgery.

Shape: `docker-compose` with two services —
- `ollama` (official image; model in a named volume),
- `speak-server` (Dockerfile: Python 3.10 + FaceFormer deps + the shims),
  run with `--ollama-url http://ollama:11434`, port 8765 exposed.

Caveats to resolve (see CLAUDE.md decisions #14–15):
- [ ] **macOS `say` does not exist in Linux.** Add a Linux TTS backend (piper:
      small, MIT, CPU) behind the existing `pick_tts()` seam; without it a
      container falls back to silent audio.
- [ ] **Apple-Silicon Docker has no Metal** — CPU-only inference. Docker is for
      reproducibility / Linux-server / CI parity, NOT Mac dev speed (the native
      path stays the fast Mac path).
- [ ] **FaceFormer weights** (`vocaset.pth`, gitignored; upstream links have
      rotted): mount at runtime, do not bake into the image (licensing + size).
- [ ] GPU passthrough for Linux+NVIDIA hosts (Ollama, optionally FaceFormer).
