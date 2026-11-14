#!/bin/sh
# One-line installer for running Home Hub from Home Assistant's Terminal add-on
# (works from a phone). Usage, pasted into the terminal:
#   sh -c "$(curl -fsSL https://raw.githubusercontent.com/wlukaz/Claude/ccr-72ad690a-51r2a3/home-dashboard/get.sh)"
# Undo later with the same line followed by:  _ restore
# Extra options also go after the _ , e.g.:  _ install --no-full-backup
set -e
BASE=https://raw.githubusercontent.com/wlukaz/Claude/ccr-72ad690a-51r2a3/home-dashboard

# Keep the tool and its backups in HA's config folder so they survive restarts.
if [ -d /config ]; then DIR=/config/home-hub; else DIR="$HOME/home-hub"; fi
mkdir -p "$DIR"
cd "$DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Installing Python (one time)..."
  apk add --no-cache python3 >/dev/null
fi

for f in ha_dashboard.py ha_client.py; do
  curl -fsSL "$BASE/$f" -o "$f"
done

echo "Home Hub files are in $DIR"
echo "When asked for the address, just press Enter."
[ $# -eq 0 ] && set -- install
python3 ha_dashboard.py "$@"
