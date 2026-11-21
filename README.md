# CHD Batch Converter

**SPDW Factory** · Version **2.0.0** · Linux-first · Python 3.9+

A recursive game-disc image converter with a full-screen terminal UI. Choose a folder, scan its subfolders, review the conversion queue and convert supported descriptors with MAME's `chdman`.

## Features

- Animated ASCII startup and SPDW Factory branding.
- Version information and a green/red `chdman` dependency LED.
- Built-in terminal folder browser and recursive scanning.
- Extension checklist; `.cue`, `.gdi`, `.toc` and `.iso` are enabled by default.
- Preview screen with READY/SKIP results and reasons.
- Configurable ISO mode: automatic size heuristic, force CD or force DVD.
- Overall batch progress and current-title progress reported by `chdman`.
- Live backend output, final summary, persistent preferences and batch logs.
- Source deletion OFF by default, guarded by two explicit `DELETE` confirmations.
- Shared tracks, M3U-backed files, incomplete layouts, external sources and unsupported sidecars receive conservative protection.
- No third-party Python packages are required.

## Requirements

- Linux, Python 3.9+ and a terminal with curses support.
- MAME `chdman` executable.

Debian/Ubuntu/Linux Mint:

```bash
sudo apt update
sudo apt install mame-tools
```

## Run from source

```bash
git clone https://github.com/SilverCrow2323/chd-batch-converter.git
cd chd-batch-converter
python3 chd_batch_converter.py
```

Or use the terminal launcher:

```bash
chmod +x run_chd_batch_converter.sh
./run_chd_batch_converter.sh
```

To install a desktop launcher:

```bash
bash install_desktop_launcher.sh
```

## Build the release ZIP

```bash
bash assemble_release.sh
```

The script builds `dist/CHD_Batch_Converter_Linux_v2.0.0.zip` from the checked-in source and runs `unzip -t` before reporting success.

## Tests

```bash
python3 -m py_compile chd_batch_converter.py
python3 -m unittest discover -s tests -v
```

The automated conversion-flow tests use a fake `chdman` executable. Run an end-to-end conversion with a real MAME installation on the target system before processing an important library.

---

**SPDW Factory** — *Convert smart. Verify first. Keep your library safe.*
