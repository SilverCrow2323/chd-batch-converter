#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APP_DIR"
LAUNCHER="$APP_DIR/spdw-chd-batch-converter.desktop"
cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Name=CHD Batch Converter
Comment=Recursively convert game-disc images to CHD
Exec=python3 "$SCRIPT_DIR/chd_batch_converter.py"
Path=$SCRIPT_DIR
Icon=utilities-terminal
Terminal=true
Categories=Utility;Game;
EOF
chmod 644 "$LAUNCHER"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi
printf 'Desktop launcher installed: %s\n' "$LAUNCHER"
