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
