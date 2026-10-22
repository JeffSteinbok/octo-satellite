#!/usr/bin/env bash
set -euo pipefail

# Installs (or reinstalls) the Octo Satellite LaunchDaemon so it starts at boot
# (no login needed), running as the current user. Prompts for sudo.
label="com.jeffsteinbok.octo-satellite"
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
plist="/Library/LaunchDaemons/$label.plist"
user="$(id -un)"

if [[ $EUID -eq 0 ]]; then
    echo "Run this as your normal user, not with sudo; it calls sudo itself." >&2
    exit 1
fi

mkdir -p "$HOME/Library/Logs"
chmod +x "$project_dir/deploy/macos/run.sh"

# Remove the old per-login LaunchAgent so it can't start a second copy on port 9000
old_agent="$HOME/Library/LaunchAgents/$label.plist"
if [[ -f "$old_agent" ]]; then
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    rm "$old_agent"
    echo "Removed old LaunchAgent $old_agent"
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sed -e "s|__PROJECT_DIR__|$project_dir|g" -e "s|__HOME__|$HOME|g" -e "s|__USER__|$user|g" \
    "$project_dir/deploy/macos/$label.plist" > "$tmp"
plutil -lint "$tmp" >/dev/null

sudo launchctl bootout "system/$label" 2>/dev/null || true
sudo install -m 644 -o root -g wheel "$tmp" "$plist"
sudo launchctl bootstrap system "$plist"

printf 'Installed %s (runs as %s at boot; logs: ~/Library/Logs/octo-satellite.log)\n' "$label" "$user"
