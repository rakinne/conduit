# desktop — Conduit Head as a floating macOS app

Wraps the repo's `index.html` in a native, lightweight macOS shell so the head
lives on your desktop: a **borderless, transparent, always-on-top** window that
**watches your cursor anywhere on screen** while you work in other apps.

No Chromium bundled — it uses the system `WKWebView` (the same WebKit macOS
already runs), so the on-disk app is ~9 MB and the dedicated process is ~80 MB
of RAM, versus a typical Electron build's ~150 MB on disk plus its own bundled
Chromium in memory.

## Build & run

```bash
bash desktop/build.sh
open desktop/build/ConduitHead.app
```

`build.sh` vendors three.js r128 into `desktop/vendor/` (downloaded once,
cached, offline thereafter), copies `index.html` + `head_data.js` +
`anim_data.js` into the bundle, rewrites the page's three.js `<script src>` to
the local copy, writes `Info.plist`, and compiles `ConduitHead.swift` with
`swiftc`. Output is `desktop/build/ConduitHead.app` (both ignored by git).

Requires the Swift toolchain (Xcode or Command Line Tools). macOS 11+.

## Using it

| Action | How |
| --- | --- |
| **Grab ⇄ click-through** | `⌥⌘H` (global) — or the menu-bar `◉` → *Grab / Release* |
| **Move it** | grab, then drag anywhere on the head |
| **Fade it** | grab, then scroll up/down — or the menu-bar opacity slider |
| **Reset position** | menu-bar `◉` → *Reset Position* |
| **Quit** | menu-bar `◉` → *Quit* |
| **Speak** (if a clip is baked) | grab, then `SPACE`; or run the UPLINK server and type |
| **Ask** (local LLM) | run the UPLINK server + Ollama, grab, then type a question — the head answers aloud |

**Click-through is the default.** Mouse clicks pass straight through to whatever
is behind the head, so it never blocks your work — it just floats there and
watches the cursor. Hit `⌥⌘H` to "grab" it when you want to drag, fade, or talk
to it; click away (or `⌥⌘H` again) and it returns to click-through.

The window position and opacity persist across launches (UserDefaults). There's
no Dock icon — the app lives in the menu bar (`LSUIElement`).

## Speech and the LLM brain

`SPACE` plays a baked clip. For live speech — or to **ask the head questions** —
run the UPLINK server (`tools/speak_server.py`) on localhost; the bundle's
`Info.plist` already permits `http://localhost` (`NSAllowsLocalNetworking`), so
no extra config is needed. The `/ask` brain additionally needs Ollama running
with a small model pulled. See the repo README's *"Ask the head"* section for
the full setup. When the brain is ready the UPLINK bar switches to **ASK** mode;
otherwise it stays a literal **SPEAK** bar. (Verified end-to-end in mock mode;
real lips + audio await a run on a FaceFormer machine — see the repo `TODOS.md`.)

## How it works

- **`ConduitHead.swift`** — an `NSApplication` accessory app. A borderless
  `NSWindow` (`isOpaque=false`, `backgroundColor=.clear`, `level=.floating`,
  `collectionBehavior` spanning all Spaces) hosts a `WKWebView` with
  `drawsBackground=false`, so the page's transparent areas show the desktop
  through. A `WKUserScript` sets `window.__CONDUIT_OVERLAY=true` before the page
  runs. Global + local `NSEvent` monitors (mouse-move, **permission-free**) feed
  the cursor as normalized coords to `window.__conduitPoint()`. A Carbon
  `RegisterEventHotKey` provides the global `⌥⌘H` (no Accessibility permission).
- **`index.html` overlay mode** — when `__CONDUIT_OVERLAY` (or `?overlay=1`) is
  set, the page hides the matrix-rain box / vignette / scanlines / chrome and
  drives the head purely from `__conduitPoint()`. The WebGL renderer was already
  created with `alpha:true`, so the canvas itself is transparent. Normal browser
  sessions are completely unaffected.

## Tuning

- **Default size / position** — `defaultSize` and `savedFrameOrDefault()` in
  `ConduitHead.swift`.
- **How far the cursor must travel for a full turn** — the `0.42` screen-fraction
  factors in `feedCursor()` (smaller = more sensitive).
- **Opacity floor** — `0.15` in `setOpacity()`.
- **Hotkey** — `kVK_ANSI_H` + `optionKey | cmdKey` in `registerHotKey()`.
