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

## Run

Open `index.html` in a browser. Three.js (r128) is loaded from cdnjs, so an
internet connection is required.

## Tuning

Key constants live near the top of each section in `index.html`:

- `YAW_MAX`, `PITCH_UP`, `PITCH_DOWN` — rotation limits
- `CELL`, `GAP` — circuit-grid density
- `idleTargets()` — idle gaze choreography
