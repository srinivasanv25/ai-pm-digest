#!/bin/bash
# Install (or update) a macOS launchd job that runs the digest daily.
#   ./scripts/install_schedule.sh          # 07:00 every day
#   ./scripts/install_schedule.sh 6 30     # 06:30 every day
#   ./scripts/install_schedule.sh --remove
# If the Mac is asleep at the scheduled time, launchd runs the job when it wakes.
set -euo pipefail

LABEL="com.aipmdigest.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv || true)"

if [[ "${1:-}" == "--remove" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $LABEL"
  exit 0
fi

[[ -n "$UV" ]] || { echo "uv not found on PATH" >&2; exit 1; }
HOUR="${1:-7}"
MINUTE="${2:-0}"
mkdir -p "$PROJECT/logs" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV</string><string>run</string><string>python</string><string>run_digest.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
  <key>StandardOutPath</key><string>$PROJECT/logs/digest.log</string>
  <key>StandardErrorPath</key><string>$PROJECT/logs/digest.log</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$(dirname "$UV"):/usr/bin:/bin</string></dict>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
printf 'Scheduled %s daily at %02d:%02d\n  plist: %s\n  logs:  %s/logs/digest.log\n  run now: launchctl kickstart gui/%s/%s\n' \
  "$LABEL" "$HOUR" "$MINUTE" "$PLIST" "$PROJECT" "$(id -u)" "$LABEL"
