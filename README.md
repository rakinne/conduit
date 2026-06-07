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

Open `index.html` in a browser. Three.js (r128) is loaded from cdnjs, so an
internet connection is required.

## Tuning

Key constants live near the top of each section in `index.html`:

- `YAW_MAX`, `PITCH_UP`, `PITCH_DOWN` — rotation limits
- `CELL`, `GAP` — circuit-grid density
- `IDENTITIES` — the five face parameter sets (add/edit skull params and rigs)
- `MORPH_MS`, `holdDur` — transition speed and time between shifts
- `chaos()` amplitudes — how violently the face boils mid-morph
- `idleTargets()` — idle gaze choreography
