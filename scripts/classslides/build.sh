#!/usr/bin/env bash
# Build + sign ClassSlides.app (Teams-window-only slide capture, see main.swift header).
#
#   scripts/classslides/build.sh
#
# Signed ad-hoc with a FIXED bundle id so macOS keeps a stable identity across rebuilds.
# Entitlements are the security boundary, enforced by the OS, not by this code:
#   app-sandbox           : on
#   network               : NONE (no network.client / network.server) -> cannot send anything
#   files                 : read-write ONLY under ~/class-notes/.frames (home-relative exception)
#                           -- a staging folder; capture-slides.sh moves frames out of it, so a
#                           compromised app cannot edit scripts that later run outside the sandbox
#   hardened runtime      : on (no code injection / unsigned libraries)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/ClassSlides.app"
BUILD="$HERE/.build"
mkdir -p "$BUILD"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>local.classnotes.classslides</string>
  <key>CFBundleName</key><string>ClassSlides</string>
  <key>CFBundleExecutable</key><string>ClassSlides</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>15.2</string>
  <key>LSUIElement</key><true/>
</dict></plist>
EOF

cat > "$BUILD/ClassSlides.entitlements" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.app-sandbox</key><true/>
  <key>com.apple.security.temporary-exception.files.home-relative-path.read-write</key>
  <array><string>/class-notes/.frames/</string></array>
</dict></plist>
EOF

swiftc -O -swift-version 5 -target arm64-apple-macosx15.2 \
  -o "$APP/Contents/MacOS/ClassSlides" "$HERE/main.swift"

codesign --force --sign - --options runtime \
  --identifier local.classnotes.classslides \
  --entitlements "$BUILD/ClassSlides.entitlements" "$APP"

codesign --verify --strict "$APP"
echo ">> built $APP"
echo ">> entitlements:"
codesign -d --entitlements - --xml "$APP" 2>/dev/null | plutil -p - 2>/dev/null || codesign -d --entitlements - "$APP"
