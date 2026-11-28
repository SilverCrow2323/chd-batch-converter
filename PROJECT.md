# Project brief — CHD Batch Converter

## Purpose

CHD Batch Converter is a local Linux terminal application for discovering disc-image sets and converting supported inputs to MAME CHD files. It reduces repetitive library conversion work while making the source-deletion boundary explicit and reviewable.

## Scope and boundaries

The application scans a user-selected directory recursively, recognizes CUE, GDI, TOC and ISO inputs, resolves referenced tracks, previews the conversion queue, invokes `chdman`, reports batch and per-title progress, and writes preferences and logs.

It does **not** download game content, patch images, scrape metadata, alter emulator configuration, or overwrite an existing CHD. It is not a library manager or a general-purpose archive extractor.

Source cleanup is an opt-in post-conversion operation. Only files owned by successfully created and verified outputs may be considered; shared, playlist-backed, changed, incomplete, external or uncertain sources must be preserved.

## Users and primary workflows

- Retro-library owners converting a folder of disc images in batches.
- Preservation users who need to inspect descriptor/track relationships before conversion.
- Linux handheld and desktop users who prefer a keyboard-driven terminal workflow.

Typical flow: choose a library folder → select supported descriptor types → inspect READY/SKIP reasons → run the queue → review logs and output CHDs → optionally enable the separately confirmed cleanup step.

## Target platform and dependencies

- Linux desktop and handheld distributions with a terminal.
- Python 3.9 or newer; standard-library Python modules only.
- MAME `chdman` is the conversion runtime dependency.
- The project is a terminal UI; no graphical desktop toolkit is required.

## Architecture

- `chd_batch_converter.py`: TUI, preferences, scanning, descriptor parsing, queue orchestration and cleanup policy.
- Descriptor parsers: CUE, GDI and TOC reference resolution; ISO validation is size-based.
- Conversion layer: invokes `chdman` and collects process/progress results.
- Safety layer: path containment, symlink-component checks, output-collision checks, source signatures and shared-track ownership.
- `tests/`: parser, preview, conversion-flow and destructive-cleanup regression tests.
- `packaging/` and shell launch/install helpers: desktop integration and distribution.

## Security, accessibility and localization

- Never follow symlinked descriptors or track references during conversion or cleanup.
- Reject unsafe/incomplete layouts rather than guessing a disc structure.
- Existing output files are preserved; cleanup remains disabled by default and requires explicit confirmation.
- Compare source signatures before deletion and preserve files shared by multiple jobs.
- Keep all actions available through clearly labelled keyboard controls; READY/SKIP explanations must not depend on colour alone.
- UI strings and technical documentation are maintained in English. Any future localization must preserve stable action names and safety warnings.

## Verified baseline and release target

The maintained README identifies the project as v2.1.0 and documents CUE/GDI/TOC/ISO support, preview, progress, logging and guarded cleanup. The current review branch adds descriptor/track symlink rejection and a regression test for a symlinked descriptor. Host CI is the authoritative automated check; no physical handheld test is implied.

**Target:** v2.2.0, after the safety matrix, packaging checks and a clean release build pass.

## Acceptance criteria

1. Supported descriptors resolve only the referenced tracks belonging to the selected job.
2. Missing, malformed, external-unsafe or symlinked references produce an explicit SKIP reason.
3. Existing CHDs are never overwritten.
4. Cleanup is opt-in, double-confirmed, ownership-aware and limited to unchanged sources of verified successful outputs.
5. Cancellation, failed conversion and shared tracks preserve source data.
6. Unit tests pass on supported Python versions and a release package can be reproduced with the documented `chdman` dependency.
