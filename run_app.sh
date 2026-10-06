#!/bin/bash
# Rebuild the SwiftUI app into a proper .app bundle and relaunch it.
# Claude runs this after each app change — no Xcode needed.
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/ReaperApp" || exit 1

swift build 2>&1 | tail -6
rc=${PIPESTATUS[0]}
if [ "$rc" -ne 0 ]; then
    echo "BUILD FAILED — app not relaunched"
    exit 1
fi

APP="$ROOT/REAPER.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp .build/debug/ReaperApp "$APP/Contents/MacOS/ReaperApp"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>ReaperApp</string>
  <key>CFBundleIdentifier</key><string>com.reaper.combat</string>
  <key>CFBundleName</key><string>REAPER</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

pkill -x ReaperApp 2>/dev/null
sleep 0.4
open "$APP"
echo "REAPER.app rebuilt and relaunched"
