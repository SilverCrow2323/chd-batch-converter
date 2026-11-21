#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DIST="$ROOT/dist"
OUTPUT="$DIST/CHD_Batch_Converter_Linux_v2.0.0.zip"
mkdir -p "$DIST"
cat \
  "$DIST/CHD_Batch_Converter_Linux_v2.0.0.zip.part00" \
  "$DIST/CHD_Batch_Converter_Linux_v2.0.0.zip.part01" \
  "$DIST/CHD_Batch_Converter_Linux_v2.0.0.zip.part02" \
  "$DIST/CHD_Batch_Converter_Linux_v2.0.0.zip.part03" \
  "$DIST/CHD_Batch_Converter_Linux_v2.0.0.zip.part04" \
  "$DIST/CHD_Batch_Converter_Linux_v2.0.0.zip.part05" \
  "$DIST/CHD_Batch_Converter_Linux_v2.0.0.zip.part06" \
  "$DIST/CHD_Batch_Converter_Linux_v2.0.0.zip.part07" \
  "$DIST/CHD_Batch_Converter_Linux_v2.0.0.zip.part08" > "$OUTPUT"
unzip -t "$OUTPUT"
echo "Release package reconstructed: $OUTPUT"
