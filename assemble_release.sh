#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DIST="$ROOT/dist"
STAGING="$(mktemp -d)"
OUTPUT="$DIST/CHD_Batch_Converter_Linux_v2.0.0.zip"
trap 'rm -rf "$STAGING"' EXIT

mkdir -p "$DIST" "$STAGING/tests"
cp "$ROOT/chd_batch_converter.py" "$ROOT/README.md" "$ROOT/CHANGELOG.md" \
   "$ROOT/LICENSE" "$ROOT/requirements.txt" "$ROOT/run_chd_batch_converter.sh" \
   "$ROOT/install_desktop_launcher.sh" "$STAGING/"
cp "$ROOT/tests/test_converter.py" "$STAGING/tests/"

rm -f "$OUTPUT"
(
  cd "$STAGING"
  zip -qr "$OUTPUT" .
)
unzip -t "$OUTPUT"
sha256sum "$OUTPUT"
printf 'Release package built: %s\n' "$OUTPUT"
