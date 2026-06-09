# Refactoring and Improvement Registry

Canonical, living registry of refactoring/improvement proposals for **conduit**.
Maintained by the embedded junior-engineer review. Update entries in place; never
renumber or reuse `RI-xxx` IDs. Nothing here is implemented until a proposal is
moved to `Approved` → `In Progress` and an engineer is assigned.

## Codebase snapshot

- **Stack:**
  - Frontend: single-file `index.html` — Three.js **r128** (CDN), vanilla JS, no
    build step, no framework. Canvas-texture LED skin, baked FLAME morph targets,
    speech playback, UPLINK fetch client.
  - Backend: `tools/speak_server.py` — stdlib `http.server` (single-threaded),
    `numpy`/`scipy`/`librosa` for audio, FaceFormer (torch) for inference, Ollama
    via stdlib `urllib` for the `/ask` brain. Opt-in Arize Phoenix tracing.
  - Offline bake tools (Python): `convert_flame.py`, `bake_anim.py`,
    `make_templates.py` — generate the committed `head_data.js` / `anim_data.js`.
  - Desktop: native macOS Swift + WKWebView shell (`desktop/ConduitHead.swift`),
    bash build (`desktop/build.sh`).
  - Tests: `tools/test_speak_ask.py` (Python `unittest`, **20** tests, all green),
    `tools/test_frontend.mjs` (Node ESM, **17** assertions, green). Both run with
    stdlib only — heavy deps stubbed.
  - Harness: `Makefile` (`test` / `test-frontend` / `mock` / `serve` / `trace-ui`).
- **Major subsystems:** (1) browser scene + choreography, (2) speech/LLM backend
  server, (3) offline FLAME/FaceFormer bake pipeline, (4) native desktop shell.
- **Key conventions inferred:**
  - stdlib-first; heavy deps are optional and lazily imported; optional features
    ship as **no-op shims** (e.g. `TRACER`, the speech slot) so the base path stays
    dependency-light and the tests import with stdlib alone.
  - Comments document *why* (a decision log in CLAUDE.md mirrors the code);
    intentional broad `except` is annotated `# noqa: BLE001` with a reason.
  - Python is untyped (no annotations), snake_case; JS is terse, ASCII-art section
    banners. Generated `*_data.js` files carry a "do not edit" header.
  - Pure helpers are factored out specifically so they can be unit-tested headlessly
    (`uplinkEndpoint`, `brainCaption`, `_clamp_for_speech`, `_trim_history`).
  - Local-only ethos: inference (#14) and telemetry (#16) never leave the machine.
- **Main risk areas:**
  - Hand-mirrored FaceFormer/transformers compat shims duplicated across the
    server and the run script (divergence = silent wrong/failed inference).
  - Non-deterministic seeding in the head bake tool (committed artifact).
  - A localhost server that fronts a local LLM with wide-open CORS.
- **Last reviewed:** 2026-06-09 (branch `main`, HEAD `583aaf2`). Senior review pass
  recorded below; evidence independently re-verified against the code.

---

## Senior review log — 2026-06-09

Reviewer decisions over the junior-engineer entries. Evidence for every entry was
re-checked against the working tree (line refs, both test suites run: 20 brain /
17 frontend, all green). Entry text is left as authored; statuses below are
authoritative.

- **RI-001 — Approved (High).** Real correctness bug (`hash()` is PYTHONHASHSEED-
  salted → non-reproducible bake). **Gate:** land the seed fix *and* the regenerated
  `head_data.js` in one PR; assign to the FLAME-pkl holder. Code-only merge is not
  acceptable (leaves artifact inconsistent with code).
- **RI-002 — NEEDS REVISION (stays Proposed, Medium).** Duplication is real, but the
  proposed cross-context import would make `run_faceformer.sh` non-standalone in a
  foreign clone — worse than the drift it cures. **Reduce scope:** extract
  `tools/ff_compat.py` for `speak_server.py` only; `run_faceformer.sh` keeps its
  inline copy + a `# MIRROR OF tools/ff_compat.py — keep in sync` header; the
  grep-both-sites drift test is optional/deferred scaffolding, not a blocker.
  Resubmit; confidence rises to High at reduced scope.
- **RI-003 — Approved (Low).** Clean dup; `tools/flame_io.py` is right. **Trim:**
  drop the `parse_head_js` "see also" — different concern, splits unrelated work;
  let it go or move to anti-churn log. Keep `flame_io.py` and `ff_compat.py`
  separate by concern; no grab-bag `utils.py`.
- **RI-004 — Approved (Medium).** Correct and proportionate. **Required edits:**
  (1) validation MUST exercise the WKWebView desktop shell (`loadFileURL` → Origin
  `null`), not just a browser; (2) origin-gate the preflight (`do_OPTIONS` /
  `Allow-Methods`) too, closing the blind-trigger vector for JSON POSTs, not only
  exfiltration; (3) threat note: reflecting `Origin: null` is a smaller residual
  widening, mitigated by the loopback bind — state it.
- **RI-005 — Approved as a RIDER only (Low).** Author-flagged style churn. Do not
  assign an engineer or open a standalone PR; bundle with the RI-004 backend work
  (same file).
- **RI-006 — Approved (Low).** Just do it: fix the two counts (20 / 17), move the
  verified e2e under "Done." Self-printing test counts is optional; don't gold-plate.

**Sequencing.** Dev-sandbox-validatable first (`make test` green): **RI-006 →
RI-004 (+RI-005 rider)**. Offline-rig-gated (need FLAME pkl / FaceFormer box),
batch for the next FaceFormer-machine session: **RI-001, RI-002 (revised),
RI-003**.

**Anti-churn log endorsed** — all five "intentionally NOT proposed" items are
correctly excluded; do not re-raise.

---

## Implementation pass — 2026-06-09 (branch `worktree-refactors-ri`)

Implemented the approved tickets in the senior's sequence. **Two landing batches**
(kept separate — do not co-merge):

- **Batch A — landable now (dev-sandbox-validated):** RI-006, RI-004, RI-005.
  `make test-all` green (**27** brain + **17** frontend). Live mock-server `curl`
  smoke confirms the CORS policy and `maxSeconds: 20.0`. One residual manual check
  on RI-004: a live WKWebView desktop-shell click (the `loadFileURL`→`Origin: null`
  path is covered by unit tests + curl, but the senior asked for a real shell run).
- **Batch B — code staged, NOT landable here (offline-rig-gated):** RI-001, RI-003.
  Code written and unit-validated, but `assets/flame2023_Open.pkl` is absent from
  this sandbox, so `head_data.js`/`templates.pkl` could not be regenerated.
  **Per RI-001's gate, a code-only merge is forbidden** — the FLAME-pkl holder must
  run `python3 tools/convert_flame.py assets/flame2023_Open.pkl`, commit the
  regenerated `head_data.js` in the *same* PR, and run the twice-and-diff +
  visual-distinctness acceptance checks before this batch merges.
- **RI-002 — NOT implemented** (correctly): it is still `Proposed`/NEEDS REVISION,
  never approved. Awaiting resubmission at the reduced scope (server-side
  `ff_compat.py` + MIRROR header). Out of scope for this pass.

---

## Active proposals

### RI-001 Deterministic seeding in `convert_flame.py` (reproducible head bake)
- Status: Approved → **code implemented (batch B, `worktree-refactors-ri`); artifact
  regen GATED** (no FLAME pkl in sandbox — land fix + regenerated `head_data.js` in
  one PR on the FLAME-pkl machine; code-only merge forbidden)
- Priority: High
- Confidence: High
- Category: Reliability / Reproducibility
- Owner:
- Reviewer:
- Created: 2026-06-09
- Last updated: 2026-06-09
- Affected areas: `tools/convert_flame.py:118` (`solve_identities`), output
  `head_data.js` (committed, generated artifact).
- Why this matters: `head_data.js` is a checked-in, "do not edit" generated
  artifact, and the design intent (CLAUDE.md decision #5) is that the five
  identities are *solved and deliberately distinct*, not random draws. The
  mid-band "character" betas are seeded with `np.random.default_rng(abs(hash(name))
  % 2**32)`. Python's `hash()` of a `str` is **salted per process** (PYTHONHASHSEED,
  on by default since 3.3), so the seed — and therefore the baked geometry — is
  **different on every run**. Re-running the documented command
  (`python3 tools/convert_flame.py assets/flame2023_Open.pkl`) silently produces a
  different `head_data.js`, making the bake non-reproducible and any "regenerate and
  diff" verification impossible.
- Evidence: `tools/convert_flame.py:118`
  `rng = np.random.default_rng(abs(hash(name)) % 2**32)`. The leading-PC betas
  (lstsq, deterministic) are fine; only this mid-band sprinkle is affected.
- Proposed change: derive the seed deterministically from the identity name, e.g.
  `seed = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")`
  (add `import hashlib`). One-line, localized to `solve_identities`.
- Expected benefits: byte-stable, reproducible bakes; enables regenerate-and-diff
  verification; matches the "solved, not sampled" intent.
- Risks/tradeoffs: regenerating with the fix changes `head_data.js` **once** vs the
  currently committed version (the committed file came from one arbitrary salt).
  Acceptable and expected; commit the new artifact as the canonical baseline. No
  runtime/page change.
- Acceptance criteria: running the converter twice in separate processes yields
  byte-identical `head_data.js`; the five identities remain visually distinct.
- Validation steps: `for i in 1 2; do python3 tools/convert_flame.py
  assets/flame2023_Open.pkl && cp head_data.js /tmp/h$i.js; done; diff /tmp/h1.js
  /tmp/h2.js` → no diff. (Needs the gitignored FLAME pkl.)
- Implementation notes: kept `BETA_CLIP`/`±2` clamps unchanged; swapped only the
  seed source to `int.from_bytes(hashlib.sha256(name.encode()).digest()[:4],"big")`
  (added `import hashlib`), exactly as proposed — no pushback. **Independently
  verified the determinism without the pkl:** the five identity-name seeds are
  byte-identical across `PYTHONHASHSEED=1` vs `=2` (two separate interpreters),
  whereas the old `abs(hash(name))%2**32` differs between them — confirming both the
  bug and the fix. The pkl-gated half (regenerate `head_data.js`, run the
  twice-and-diff acceptance + eyeball the five forms) MUST be done on the FLAME box
  and committed in the same PR; do not merge the code alone (senior gate).
- Implemented in: `tools/convert_flame.py` (`solve_identities` seed; `import hashlib`),
  branch `worktree-refactors-ri`. `head_data.js` NOT yet regenerated (gated).
- History: 2026-06-09 created; 2026-06-09 code implemented + determinism verified,
  artifact regen pending FLAME pkl.

### RI-002 De-duplicate FaceFormer compat shims + speaker constants
- Status: Proposed (senior review 2026-06-09 — NEEDS REVISION; see Senior review
  log: drop cross-context import, reduce to server-side ff_compat.py + MIRROR header)
- Priority: Medium
- Confidence: Medium
- Category: Duplication / Reliability
- Owner:
- Reviewer:
- Created: 2026-06-09
- Last updated: 2026-06-09
- Affected areas: `tools/speak_server.py` (`FaceFormerPredictor.__init__`,
  ~`:203-247`; `TRAIN_SUBJECTS`/`CONDITION`/`SUBJECT` `:154-159`) and
  `tools/run_faceformer.sh` (embedded python, `:83-118`; `train_subjects`/
  `condition`/`subject` `:127-135`).
- Why this matters: three load-bearing shims are copy-pasted verbatim across the
  server and the run script: (a) the weight-norm key rename
  `pos_conv_embed.conv.weight_g/weight_v → parametrizations.weight.original0/1`,
  (b) the rendering-stack module stubs (`pyrender`, `trimesh`, `cv2`,
  `psbody.mesh`), and (c) the speaker identifiers (`TRAIN_SUBJECTS`, the
  `FaceTalk_..._03279_TA` condition, the `FaceTalk_..._00138_TA` subject). CLAUDE.md
  decision #11 explicitly enumerates these shims as fragile and version-sensitive.
  When `transformers`/`torch` next renames a param (it already happened once) or the
  conditioning speaker is retuned, the two copies will silently drift — one path
  loads correctly while the other throws or, worse, conditions on a different
  speaker and produces subtly wrong lips with no error.
- Evidence: `grep -ln weight_g tools/*` → both `run_faceformer.sh` and
  `speak_server.py`; `grep -ln pyrender tools/*` → same two (plus the requirements
  file). Speaker strings duplicated at the line refs above.
- Proposed change (incremental, smallest-first):
  1. Extract the speaker identifiers into one module-level home in a tiny
     `tools/ff_compat.py` (`TRAIN_SUBJECTS`, `CONDITION`, `SUBJECT`) and import them
     in `speak_server.py`; have `run_faceformer.sh`'s heredoc `sys.path.insert` the
     repo `tools/` and import the same names.
  2. Move the two functions there too: `stub_render_modules()` and
     `rename_weightnorm_keys(state_dict, want)`; call them from both sites.
- Expected benefits: single source of truth for the most fragile, externally-driven
  code in the repo; a future transformers bump is a one-file fix; eliminates the
  silent-drift failure mode.
- Risks/tradeoffs: `run_faceformer.sh` runs **inside the FaceFormer clone** (foreign
  cwd) via a heredoc, so the import must robustly locate the conduit `tools/` dir
  (pass its path as an arg or env var). Must not regress the existing verified
  real-stack run (TODOS: 2026-06-08). Medium confidence precisely because of the
  cross-context import; if that proves brittle, fall back to **at minimum** sharing
  the speaker constants (item 1) and leaving a prominent "MIRROR OF ff_compat.py —
  keep in sync" comment on the shell copy.
- Acceptance criteria: `make test` stays green; a real `make serve` on the
  FaceFormer box still warms and answers (re-run the 2026-06-08 smoke: "capital of
  Peru?"); `run_faceformer.sh` still produces a `(T,15069)` npy.
- Validation steps: unit import of `ff_compat` under stdlib; manual real-stack
  re-run on the FaceFormer machine (cannot be exercised in the dev sandbox — torch
  absent). Flag clearly in the PR that backend e2e needs the FaceFormer host.
- Implementation notes: do NOT touch the requirements file's `pyrender` line (that's
  a real dep pin, not a stub). Keep `# noqa` annotations.
- Implemented in: **not implemented** — NEEDS REVISION, never approved. Skipped in the
  2026-06-09 implementation pass; awaiting resubmission at the reduced scope
  (server-side `tools/ff_compat.py` only + a `# MIRROR OF tools/ff_compat.py — keep
  in sync` header on `run_faceformer.sh`'s inline copy; no cross-context import).
- History: 2026-06-09 created; 2026-06-09 intentionally NOT implemented (still
  Proposed — reduced-scope resubmission pending).

### RI-003 Share the FLAME `.pkl` loader / chumpy shim across bake tools
- Status: Approved → **code implemented (batch B, `worktree-refactors-ri`); artifact
  byte-diff validation GATED** (no FLAME pkl in sandbox)
- Priority: Low
- Confidence: High
- Category: Duplication
- Owner:
- Reviewer:
- Created: 2026-06-09
- Last updated: 2026-06-09
- Affected areas: `tools/convert_flame.py:36-53` (`load_flame`) and
  `tools/make_templates.py:36-46` (inline loader in `main`).
- Why this matters: both tools define an identical `Ch` chumpy-shim class, register
  the same fake `chumpy` / `chumpy.ch` / `chumpy.ch_ops` modules, and
  `pickle.load(f, encoding="latin1")` the FLAME pkl. It's a clean copy-paste; if the
  pkl's chumpy wrapping ever needs a tweak (e.g. another unwrap key), both must
  change in lockstep.
- Evidence: the two cited blocks are structurally identical (`make_templates.py`
  omits only the `unwrap` step it doesn't need).
- Proposed change: add `load_flame(path) -> dict` (the `convert_flame.py` version,
  which already returns unwrapped arrays) to a shared `tools/flame_io.py` and import
  it from both; `make_templates.py` just reads `d["v_template"]`. Net deletion of
  ~12 duplicated lines.
- Expected benefits: one chumpy shim to maintain; less surface for the FLAME-load
  path to drift.
- Risks/tradeoffs: minimal — offline one-shot dev tools, low churn, no runtime
  impact. If RI-002 also lands, `flame_io.py` and `ff_compat.py` could be the same
  small `tools/` support module.
- Acceptance criteria: both tools still emit identical output for the same pkl
  (`head_data.js` unchanged byte-for-byte after RI-001; `templates.pkl` unchanged).
- Validation steps: regenerate both artifacts and diff against current (needs the
  gitignored FLAME pkl).
- Implementation notes: extracted `load_flame` verbatim (the `convert_flame.py`
  version, which returns unwrapped arrays) into a new `tools/flame_io.py`; both
  `convert_flame.py` and `make_templates.py` now `from flame_io import load_flame`
  (identity-checked: both reference the same function). Dropped now-unused imports
  (`pickle`/`types` in `convert_flame`; `types` in `make_templates` — `pickle` stays
  for the `templates.pkl` dump). **Dropped the `parse_head_js` "see also" per the
  senior** (different concern; not folded in). Kept `flame_io.py` standalone by
  concern — no `ff_compat.py` exists (RI-002 unimplemented), and no grab-bag
  `utils.py`. **Validated without the pkl:** `load_flame` round-trips a synthetic
  pickle exercising BOTH the plain-passthrough and the chumpy-`__setstate__` unwrap
  branch; both tools compile + import. The byte-for-byte artifact diff (acceptance
  criterion) needs the FLAME pkl and is deferred to the FLAME box, alongside RI-001.
- Implemented in: `tools/flame_io.py` (new), `tools/convert_flame.py`,
  `tools/make_templates.py`; branch `worktree-refactors-ri`.
- History: 2026-06-09 created; 2026-06-09 code implemented + loader round-trip
  verified, artifact diff pending FLAME pkl.

### RI-004 Restrict CORS on the local speak/LLM server to known local origins
- Status: Approved → **IMPLEMENTED (batch A, `worktree-refactors-ri`); dev-sandbox
  validated** (unit tests + curl smoke). One residual manual check: a live WKWebView
  desktop-shell click.
- Priority: Medium
- Confidence: Medium
- Category: Security
- Owner:
- Reviewer:
- Created: 2026-06-09
- Last updated: 2026-06-09
- Affected areas: `tools/speak_server.py:465` (`_send` sets
  `Access-Control-Allow-Origin: *`); `do_OPTIONS`/all responses.
- Why this matters: the server binds `127.0.0.1` (good — unreachable from the
  network), but `Access-Control-Allow-Origin: *` means **any website open in your
  browser** can issue cross-origin `fetch('http://localhost:8765/ask', {…})`,
  silently drive the head, query your local Ollama model, and — because `*` exposes
  the response body — **read the model's reply**. The whole point of decisions #14
  and #16 is that local inference and conversation data never leave the box; wide-
  open CORS is the one hole that lets an arbitrary web page exfiltrate `/ask`
  answers. Severity is genuinely low for a single-user desktop pet (attacker needs
  you to visit a hostile page while the server runs), but it is squarely off the
  repo's stated local-only thesis.
- Evidence: `tools/speak_server.py:465`
  `self.send_header("Access-Control-Allow-Origin", "*")`; the page is loaded from
  `file://` (Origin `null`) or `http://localhost` per CLAUDE.md, so `*` is broader
  than needed.
- Proposed change: reflect/allow only the origins conduit actually uses. The page is
  opened from `file://` (sends `Origin: null`) or `http(s)://localhost`/`127.0.0.1`;
  echo the request `Origin` only when it is `null` or a localhost/loopback origin,
  else omit the ACAO header (the browser then blocks the cross-origin read). Keep it
  a small allowlist function; no new dependency.
- Expected benefits: arbitrary third-party sites can no longer read local-LLM
  replies; aligns the network surface with the local-only design.
- Risks/tradeoffs: must not break the real page. `file://` origin handling is the
  fiddly part (some browsers send `Origin: null`); verify the desktop shell
  (WKWebView, `loadFileURL`) and a plain `file://` browser session still get the
  UPLINK bar and a working `/ask`. If `null`-origin handling proves browser-
  dependent, document the residual and keep the allowlist for `http(s)` localhost.
- Acceptance criteria: `/ping` and `/ask` still work from the desktop shell and a
  `file://`-opened page; a fetch from an unrelated `https://` origin is blocked from
  reading the response (manual check).
- Validation steps: extend `test_speak_ask.py` with a header-policy assertion
  (allowed vs disallowed `Origin` → correct ACAO), then a manual browser check from
  the desktop shell.
- Implementation notes: added module-level `_allowed_origin(origin)` (echo only
  `null` + localhost/loopback http(s); else `None`) and a `_set_cors` helper used by
  both `_send` and `do_OPTIONS`, replacing the blanket `ACAO:*`. All three senior
  requirements met: **(1)** the `file://` → `Origin: null` path (the desktop shell's
  `loadFileURL`) is allowed and unit-tested + curl-verified — a live WKWebView click
  remains the one manual sign-off; **(2)** the preflight is origin-gated
  (`do_OPTIONS` now emits `Allow-Methods` only for allowed origins, returning a
  bodyless `204`), so a disallowed site's JSON POST never leaves the browser — the
  blind-trigger vector, not just exfiltration; **(3)** the `null`-origin residual
  (shared by every `file://` page, bounded by the loopback bind) is documented in
  `desktop/README.md`. No auth token (proportionate). Also synced the stale
  "CORS open for file://" line in CLAUDE.md. Tests: `CorsPolicyTests` (pure
  allow/deny incl. localhost look-alikes like `localhost.evil.com`) +
  `CorsServerTests` (live `/ping` + `OPTIONS` over a real socket).
- Implemented in: `tools/speak_server.py` (`_allowed_origin`, `_set_cors`,
  `do_OPTIONS`, `_send`), `tools/test_speak_ask.py` (+7 tests), `desktop/README.md`,
  `CLAUDE.md`; branch `worktree-refactors-ri`.
- History: 2026-06-09 created; 2026-06-09 implemented + validated (27/17 green, curl
  smoke); live-shell click pending.

### RI-005 Name the 20 s cap once; link client/server input-length caps
- Status: Approved as a RIDER → **IMPLEMENTED (batch A, bundled with RI-004 as
  directed); validated**
- Priority: Low
- Confidence: High
- Category: Complexity / DX
- Owner:
- Reviewer:
- Created: 2026-06-09
- Last updated: 2026-06-09
- Affected areas: `tools/speak_server.py` — `MAX_FRAMES / FPS` recomputed at
  `:476, :499, :552, :555, :688`; `MAX_INPUT_CHARS` `:295` vs `index.html:132`
  `maxlength="400"`.
- Why this matters: the 20-second speech cap is expressed as the inline expression
  `MAX_FRAMES / FPS` in five places (the guard, `/ping`, two `TooLong` messages, the
  banner). It reads fine but invites drift and re-computation. Separately, the page
  caps the UPLINK input at `maxlength="400"` while the server rejects at
  `MAX_INPUT_CHARS = 600`: two independent magic numbers for "max query length"
  (client stricter, so harmless today, but the coupling is undocumented).
- Evidence: line refs above.
- Proposed change: add `MAX_SECONDS = MAX_FRAMES / FPS` once and reference it; add a
  short comment at `index.html`'s `maxlength` noting it must stay ≤ the server's
  `MAX_INPUT_CHARS`. No behavior change.
- Expected benefits: one place to change the cap; intent is explicit; removes a
  trivial drift risk.
- Risks/tradeoffs: none beyond a tiny diff. Pure readability — borderline "style
  churn", so keep it incidental (bundle with another backend change rather than its
  own PR).
- Acceptance criteria: `make test` green; `/ping` still reports `maxSeconds: 20.0`;
  identical error strings.
- Validation steps: `make test` + a `/ping` smoke in mock mode.
- Implementation notes: added `MAX_SECONDS = MAX_FRAMES / FPS` once and referenced it
  at all five sites (guard, `/ping`, both `TooLong` messages, the banner); `MAX_FRAMES`
  kept where used standalone (`predict`'s `min(MAX_FRAMES, …)`). Added the `index.html`
  `maxlength` comment noting it must stay ≤ the server's `MAX_INPUT_CHARS` (600). No
  behavior change — curl smoke confirms `/ping` still reports `maxSeconds: 20.0` and
  the error strings are byte-identical (`20s`). No pushback.
- Implemented in: `tools/speak_server.py` (`MAX_SECONDS`), `index.html` (maxlength
  comment); branch `worktree-refactors-ri`.
- History: 2026-06-09 created; 2026-06-09 implemented + validated.

### RI-006 Refresh stale counts/status in `TODOS.md`
- Status: Approved → **IMPLEMENTED (batch A); validated**
- Priority: Low
- Confidence: High
- Category: Documentation
- Owner:
- Reviewer:
- Created: 2026-06-09
- Last updated: 2026-06-09
- Affected areas: `TODOS.md:12` (test counts) and `:16-20` (the completed
  real-stack e2e still filed under "Left").
- Why this matters: TODOS.md states "`test_speak_ask.py` (17, brain) +
  `test_frontend.mjs` (10, routing)". Actual today: **20** brain tests
  (`Ran 20 tests … OK`) and **17** frontend assertions. The real-stack e2e is marked
  `[x] … VERIFIED 2026-06-08` but sits under the "**Left**" heading. Small, but the
  doc is the at-a-glance status of the active feature and currently understates test
  coverage and miscategorizes done work.
- Evidence: `python3 tools/test_speak_ask.py` → `Ran 20 tests in …s / OK`;
  `node tools/test_frontend.mjs` → `ok - 17 frontend assertions passed`.
- Proposed change: update the two counts (20 / 17) and move the verified e2e line
  into a "Done" position. Optionally have the test scripts print "N tests" so the
  number is self-evident in CI output.
- Expected benefits: doc matches reality; no false impression of thin coverage.
- Risks/tradeoffs: none.
- Acceptance criteria: counts in TODOS.md equal the live runner output.
- Validation steps: re-run both suites; compare.
- Implementation notes / **pushback on the stated count**: the proposal says set the
  brain count to **20**, but RI-004 (same landable batch A) adds 7 CORS tests, so the
  live runner now prints **27**. The acceptance criterion is "counts equal the live
  runner output," so TODOS.md is set to **27 / 17** (not 20 / 17) — otherwise it would
  be stale the moment RI-004 lands. Also moved the verified e2e from "Left" to "Done"
  and trimmed the now-redundant "(… the real-stack e2e is DONE)" parenthetical.
  Self-printing test counts skipped (senior: optional; don't gold-plate).
- Implemented in: `TODOS.md`; branch `worktree-refactors-ri`.
- History: 2026-06-09 created; 2026-06-09 implemented (counts → 27 / 17 to match the
  post-RI-004 runner; e2e moved to Done).

---

## Considered and intentionally NOT proposed (anti-churn log)

Recorded so future passes don't re-raise these as "findings":

- **Single-threaded `HTTPServer`.** A slow `/ask` blocks other requests. This is a
  *deliberate* invariant (CLAUDE.md decision #15): `Brain.history` is only ever
  touched on the server thread, and the `say`/Ollama timeouts bound the block.
  Swapping to `ThreadingHTTPServer` would break the no-cross-thread-history
  guarantee for concurrent asks. Correct as-is for a single-user pet — leave it.
- **Lazy in-function imports** of `librosa`/`scipy`/`torch`. Intentional so mock
  mode and the stdlib-only tests don't need the heavy stack. Convention, not debt.
- **`new Audio()` per reply in `loadSpeech`.** The previous clip is paused and
  dropped to GC; not an unbounded leak in practice for an interactive pet. Watch,
  don't act.
- **Residual speech-slot deltas across clips.** Verified safe: `loadSpeech` clears
  the slot via `stopSpeech` when a clip is playing, and natural clip-end already
  calls `stopSpeech` (which `fill(0)`s), so no stale pose lingers. No action.
- **`/animate` needs `librosa` even in `--mock`.** True (mock venv has only
  numpy+scipy), but `/animate` is not part of the `--mock` contract (which is
  `/ping` `/ask` `/speak`). Not worth special-casing.

## Closed proposals

_(none yet)_
