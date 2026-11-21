# CHD Batch Converter 2.0.0

**SPDW Factory**

CHD Batch Converter 2.0.0 introduces the full-screen terminal workflow for safer recursive game-disc conversion.

## Highlights

- Animated ASCII startup and SPDW Factory branding.
- Version display and a green/red `chdman` dependency indicator.
- Terminal folder browser and recursive scan.
- Configurable extension selection, with CUE, GDI, TOC and ISO enabled by default.
- Scan preview with READY/SKIP states and reasons.
- ISO CD/DVD mode selection.
- Overall batch progress and per-title progress.
- Persistent preferences, live log output and final summary.
- Source deletion disabled by default and protected by two explicit confirmations.
- Conservative handling of shared tracks, M3U playlists and incomplete layouts.
- Automated tests for parsers, cleanup safety, conversion and verification flow.

## Install

Debian/Ubuntu/Linux Mint:

```bash
sudo apt update
sudo apt install mame-tools
```

Extract the attached ZIP and run `chd_batch_converter.py` in a terminal.

## Safety

A CHD is published only after `chdman verify` succeeds. Existing outputs are not overwritten. Source files are eligible for cleanup only after successful verification and the required user confirmations.

The automated test suite uses a simulated `chdman` executable. Real hardware/library end-to-end testing remains recommended.

**SPDW Factory** — *Convert smart. Verify first. Keep your library safe.*
