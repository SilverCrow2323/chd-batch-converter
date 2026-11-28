# Roadmap — CHD Batch Converter

## Phase 0 — Baseline and safety contract

**Status:** implementation exists; this review cycle is closing the descriptor-path boundary.

- Keep CUE, GDI, TOC and ISO parsing deterministic.
- Reject symlink components in both descriptor paths and referenced tracks.
- Preserve explicit READY/SKIP reasons in the preview.
- Keep source deletion disabled by default.

**Acceptance:** parser fixtures pass; symlinked descriptors and tracks are rejected before conversion; target files remain untouched.

## Phase 1 — Conversion and cleanup integrity

- Verify that only successful, verified CHD outputs make their source set eligible for cleanup.
- Preserve tracks shared by failed, skipped or playlist-backed jobs.
- Recheck file signatures immediately before deletion.
- Preserve existing outputs and all uncertain source layouts.

**Acceptance:** tests cover failed/skipped jobs, shared tracks, changed sources, playlists, output collisions and cancellation. No cleanup test may depend on deleting files outside a temporary fixture.

## Phase 2 — Operational UX

- Keep queue previews and failure messages actionable.
- Verify progress parsing against representative `chdman` output and the no-progress fallback.
- Keep preferences and logs recoverable after an interrupted batch.
- Retain the keyboard-only workflow and readable READY/SKIP status text.

**Acceptance:** automated TUI/flow tests pass; manual terminal review confirms navigation, cancellation and error reporting on a Linux desktop.

## Phase 3 — Packaging and stable release

- Verify launcher/install scripts and Debian-family packaging.
- Document Python and MAME versions used for the release.
- Build from a clean checkout and record artifact checksums.
- Publish only after review and explicit release authorization.

**Acceptance:** clean build, test suite and package inspection pass; release notes identify supported descriptors, dependency requirements and cleanup safeguards.

## Test matrix

| Layer | Automated checks | Manual checks |
|---|---|---|
| Parsing | CUE/GDI/TOC references, quoted paths, separators, missing tracks | Inspect representative library layouts |
| Safety | Symlink paths, path containment, shared tracks, source mutation, output collisions | Confirm preview never proposes unsafe cleanup |
| Conversion | Fake/controlled `chdman` results, failure and cancellation paths | Run a small user-owned sample set |
| UI | Navigation and state/preview tests | Terminal readability and keyboard flow |
| Packaging | Syntax, package contents and launcher checks | Install/uninstall on supported Linux distributions |

## Dependencies and risks

- MAME `chdman` behaviour and version compatibility are external dependencies.
- Descriptor formats permit ambiguous or incomplete layouts; uncertain inputs must be skipped, not guessed.
- Source cleanup is destructive by nature and remains the final, separately confirmed operation.
- Large libraries need bounded scanning and cancellation that does not leave partially trusted cleanup state.
