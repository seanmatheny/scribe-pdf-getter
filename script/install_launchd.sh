#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/com.scribepdfgetter.watcher.plist"
PYTHON_BIN="$(command -v python3)"
SCRIPT_PATH="$REPO_ROOT/script/scribe_watcher_macos.py"
CONFIG_PATH="$REPO_ROOT/settings/config_macos.json"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.scribepdfgetter.watcher</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$SCRIPT_PATH</string>
    <string>watch</string>
    <string>--config</string>
    <string>$CONFIG_PATH</string>
  </array>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>$REPO_ROOT/settings/scribe_watcher.stdout.log</string>

  <key>StandardErrorPath</key>
  <string>$REPO_ROOT/settings/scribe_watcher.stderr.log</string>
</dict>
</plist>
EOF

if launchctl list | grep -q "com.scribepdfgetter.watcher"; then
  launchctl unload "$PLIST_PATH" || true
fi

launchctl load "$PLIST_PATH"
echo "Installed and loaded launch agent: $PLIST_PATH"
echo "To stop: launchctl unload $PLIST_PATH"
