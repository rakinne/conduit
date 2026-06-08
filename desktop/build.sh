#!/usr/bin/env bash
# Build ConduitHead.app — a self-contained macOS bundle wrapping the repo's
# index.html as a floating, transparent, always-on-top desktop head.
#
#   bash desktop/build.sh         # build it
#   open desktop/build/ConduitHead.app
#
# Self-contained: vendors three.js r128 locally (cached in desktop/vendor) so
# the app needs no network, and embeds head_data.js / anim_data.js.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BUILD="$HERE/build"
APP="$BUILD/ConduitHead.app"
WEB="$APP/Contents/Resources/web"
MACOS="$APP/Contents/MacOS"
VENDOR="$HERE/vendor"
THREE_URL="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
THREE_CACHE="$VENDOR/three.min.js"

log() { printf '\033[0;32m▸\033[0m %s\n' "$*"; }
die() { printf '\033[0;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- 1. vendor three.js r128 (offline-robust) -------------------------------
mkdir -p "$VENDOR"
if [[ ! -s "$THREE_CACHE" ]]; then
  log "Downloading three.js r128 → $THREE_CACHE"
  curl -fsSL "$THREE_URL" -o "$THREE_CACHE" \
    || die "Could not download three.js. Connect to a network once, or place three.min.js (r128) at $THREE_CACHE"
fi
grep -q "REVISION" "$THREE_CACHE" || die "Cached three.min.js looks corrupt; delete $THREE_CACHE and retry."

# --- 2. clean + scaffold the bundle -----------------------------------------
log "Assembling $APP"
rm -rf "$APP"
mkdir -p "$MACOS" "$WEB"

# --- 3. web assets (rewrite the three.js <script src> to the local copy) -----
cp "$ROOT/index.html"   "$WEB/index.html"
cp "$ROOT/head_data.js" "$WEB/head_data.js"
cp "$ROOT/anim_data.js" "$WEB/anim_data.js" 2>/dev/null || log "(no anim_data.js — speech clip optional)"
cp "$THREE_CACHE"       "$WEB/three.min.js"

# python rewrite (BSD sed is unreliable for this per CLAUDE.md)
python3 - "$WEB/index.html" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
needle = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
if needle not in s:
    sys.exit("three.js CDN <script src> not found in index.html — did the markup change?")
open(p, "w", encoding="utf-8").write(s.replace(needle, "three.min.js"))
PY
log "Vendored three.js into the page"

# --- 4. Info.plist -----------------------------------------------------------
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>            <string>Conduit Head</string>
  <key>CFBundleDisplayName</key>     <string>Conduit Head</string>
  <key>CFBundleIdentifier</key>      <string>com.conduit.head</string>
  <key>CFBundleExecutable</key>      <string>ConduitHead</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>CFBundleShortVersionString</key> <string>1.0</string>
  <key>CFBundleVersion</key>         <string>1</string>
  <key>LSMinimumSystemVersion</key>  <string>11.0</string>
  <key>NSHighResolutionCapable</key> <true/>
  <key>NSPrincipalClass</key>        <string>NSApplication</string>
  <!-- accessory app: no Dock icon, lives in the menu bar -->
  <key>LSUIElement</key>             <true/>
  <!-- allow the optional UPLINK speech server on http://localhost -->
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST

# --- 5. compile the Swift shell ---------------------------------------------
log "Compiling ConduitHead.swift"
swiftc -O "$HERE/ConduitHead.swift" -o "$MACOS/ConduitHead" \
  -framework Cocoa -framework WebKit -framework Carbon \
  || die "swiftc failed."

# --- 6. done -----------------------------------------------------------------
SIZE=$(du -sh "$APP" | cut -f1)
log "Built $APP  ($SIZE)"
cat <<EOF

  Run it:     open "$APP"
  Hotkey:     ⌥⌘H  toggles grab (interact / drag / scroll-to-fade) vs click-through
  Controls:   menu-bar ◉  →  opacity slider, reset position, quit

EOF
