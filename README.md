# 🎮 CHD Batch Converter

**SPDW Factory** · **v2.1.0** · Linux · Python 3.9+

A small terminal tool for scanning a game library recursively and converting supported disc images to CHD with MAME's `chdman`.

## 📸 Quick look

<p align="center">
  <img src="docs/screenshots/01-main-menu.png" alt="Main menu with START selected" width="96%" />
</p>
<p align="center">
  <img src="docs/screenshots/02-extensions.png" alt="Supported file extension selector" width="49%" />
  <img src="docs/screenshots/03-scan-results.png" alt="Recursive scan results and conversion queue" width="49%" />
</p>
<p align="center">
  <img src="docs/screenshots/04-progress.png" alt="Overall and per-title conversion progress" width="96%" />
</p>

*Screens show representative example data. The dependency LED is green when `chdman` is detected.*

## ⚡ What it does

- **START** scans the selected folder and its subfolders; when no folder is selected, it opens the folder browser first.
- Supports `.cue`, `.gdi`, `.toc` and `.iso` descriptors. All four are enabled by default.
- Shows a `READY` / `SKIP` preview before conversion.
- Displays overall batch progress and per-title progress when `chdman` reports it.
- Stores preferences and writes a log for each batch.

## 🚀 Install and run

Debian / Ubuntu / Linux Mint:

```bash
sudo apt update
sudo apt install mame-tools
```

Then run from the extracted project folder:

```bash
python3 chd_batch_converter.py
```

Or use `run_chd_batch_converter.sh`. `install_desktop_launcher.sh` adds a launcher that opens the TUI in a terminal.

## 🕹️ Basic controls

- **START** — scan and convert the selected folder.
- **Select folder** — choose or change the library folder.
- **File extensions** — choose which supported descriptors to search for.
- **SPACE** on source cleanup — toggle deletion for the next batch.
- In scan results: **D** toggles cleanup, **ENTER** starts the reviewed queue, **Q** returns to the menu.

## 🛡️ Source safety

Source deletion is **OFF by default**. To enable it, the app asks for `DELETE` before the batch and asks again after conversion. Only sources belonging to successfully created and verified CHDs are eligible; shared tracks, playlist-backed files and uncertain layouts are preserved. Existing CHDs are never overwritten.

## 🧪 Tests

```bash
python3 -m py_compile chd_batch_converter.py
python3 -m unittest discover -s tests -v
```

No third-party Python packages are required. MAME's `chdman` is the runtime dependency.

---

**SPDW Factory** — *Convert smart. Verify first. Keep your library safe.*
