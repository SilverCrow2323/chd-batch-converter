# CHD Batch Converter

**SPDW Factory** · Version **2.0.0** · Linux-first · Python 3.9+

A recursive game-disc image converter with a full-screen terminal UI. Choose a folder, scan its subfolders, review the conversion queue and convert supported descriptors with MAME's `chdman`.

## Get the release package

The ZIP is stored in ordered binary chunks under `dist/` because the GitHub file connector cannot upload one large binary in a single request.

Clone the repository and reconstruct the exact release archive:

```bash
git clone https://github.com/SilverCrow2323/chd-batch-converter.git
cd chd-batch-converter
bash assemble_release.sh
```

The script concatenates the chunks and runs `unzip -t` before reporting success. The resulting archive is:

`dist/CHD_Batch_Converter_Linux_v2.0.0.zip`

## Features

- Animated ASCII startup and branded SPDW Factory TUI.
- Application/Python version information and a green/red `chdman` dependency LED.
- Built-in terminal folder browser and recursive scanning.
- Extension checklist; `.cue`, `.gdi`, `.toc` and `.iso` are enabled by default.
- Preview screen with READY/SKIP results and reasons.
- Configurable ISO mode: automatic size heuristic, force CD or force DVD.
- Overall batch progress by processed title and current `chdman` stage progress when reported by the backend.
- Live backend output, final summary and persistent batch logs.
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

## Run

```bash
python3 chd_batch_converter.py
```

For desktop integration, the package includes `install_desktop_launcher.sh`. See the bundled README for key bindings, cleanup guarantees, supported formats and test instructions.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Conversion-flow tests use a fake `chdman` executable. A real MAME end-to-end conversion should still be tested on the target system.

---

**SPDW Factory** — *Convert smart. Verify first. Keep your library safe.*
