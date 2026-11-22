# CHD Batch Converter 2.1.0

**SPDW Factory** · *Make START the obvious button.*

## What's new

- Added **START** as the first item in the main TUI menu.
- Split folder selection into its own **Select folder** action.
- START reuses the selected folder, or opens the folder browser when none has been selected.
- Refreshed the README with four concise TUI screenshots and shorter setup instructions.
- Added two automated tests for the new START workflow.

## Install

Debian / Ubuntu / Linux Mint:

```bash
sudo apt update
sudo apt install mame-tools
```

Run `python3 chd_batch_converter.py` from the extracted folder.

## Safety

Source deletion remains OFF by default and requires two explicit `DELETE` confirmations. A CHD is published only after `chdman verify` succeeds.

**SPDW Factory** — *Convert smart. Verify first. Keep your library safe.*
