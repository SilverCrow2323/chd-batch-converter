#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DIST="$ROOT/dist"
STAGING="$(mktemp -d)"
OUTPUT="$DIST/CHD_Batch_Converter_Linux_v2.1.0.zip"
trap 'rm -rf "$STAGING"' EXIT

mkdir -p "$DIST" "$STAGING/tests" "$STAGING/docs/screenshots"
cp "$ROOT/chd_batch_converter.py" "$ROOT/README.md" "$ROOT/CHANGELOG.md" \
   "$ROOT/RELEASE_NOTES_v2.1.0.md" "$ROOT/LICENSE" "$ROOT/requirements.txt" \
   "$ROOT/run_chd_batch_converter.sh" "$ROOT/install_desktop_launcher.sh" "$STAGING/"
cp "$ROOT/tests/test_converter.py" "$STAGING/tests/"
cp "$ROOT/docs/screenshots/"*.svg "$STAGING/docs/screenshots/"

rm -f "$OUTPUT"
(
  cd "$STAGING"
  zip -qr "$OUTPUT" .
)
unzip -t "$OUTPUT"
sha256sum "$OUTPUT"
printf 'Release package built: %s\n' "$OUTPUT"
