#!/usr/bin/env bash
# Builds Zuse.app from the SwiftPM package — no Xcode required, CLT only.
# Never calls xcodebuild (the shim errors without a full Xcode install).
#
# Usage: ./build-app.sh          → macos/ZuseApp/dist/Zuse.app
# Orphaned backend after an app crash? → pkill -f zuse-web
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="Zuse"
DIST="dist"
BUNDLE="$DIST/$APP_NAME.app"
LOGO="../../assets/zuse-logo.png"

echo "→ swift build -c release"
swift build -c release

BIN=".build/release/$APP_NAME"
[ -x "$BIN" ] || { echo "✗ Build-Artefakt fehlt: $BIN" >&2; exit 1; }

echo "→ Assembling $BUNDLE"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cp "$BIN" "$BUNDLE/Contents/MacOS/$APP_NAME"
cp Info.plist.template "$BUNDLE/Contents/Info.plist"
printf 'APPL????' > "$BUNDLE/Contents/PkgInfo"

# Optional icon from the repo logo (square-pad → iconset → icns). Non-fatal.
if [ -f "$LOGO" ] && command -v sips >/dev/null && command -v iconutil >/dev/null; then
  echo "→ Building icon from $LOGO"
  ICONSET="$DIST/$APP_NAME.iconset"
  rm -rf "$ICONSET" && mkdir -p "$ICONSET"
  if sips -z 1024 1024 "$LOGO" --padToHeightWidth 1024 1024 \
       --out "$DIST/icon-1024.png" >/dev/null 2>&1; then
    for size in 16 32 64 128 256 512; do
      sips -z "$size" "$size" "$DIST/icon-1024.png" \
        --out "$ICONSET/icon_${size}x${size}.png" >/dev/null 2>&1 || true
      sips -z "$((size*2))" "$((size*2))" "$DIST/icon-1024.png" \
        --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null 2>&1 || true
    done
    cp "$DIST/icon-1024.png" "$ICONSET/icon_512x512@2x.png" 2>/dev/null || true
    if iconutil -c icns "$ICONSET" -o "$BUNDLE/Contents/Resources/$APP_NAME.icns" 2>/dev/null; then
      echo "✓ Icon eingebettet"
    else
      echo "⚠ iconutil fehlgeschlagen — App nutzt das generische Icon"
    fi
  else
    echo "⚠ sips fehlgeschlagen — App nutzt das generische Icon"
  fi
  rm -rf "$ICONSET" "$DIST/icon-1024.png"
fi

echo "→ Ad-hoc codesign"
codesign --force --deep -s - "$BUNDLE"
codesign --verify --verbose=2 "$BUNDLE"

echo ""
echo "✓ Fertig: $(pwd)/$BUNDLE"
echo "  Öffnen mit: open \"$(pwd)/$BUNDLE\""
