#!/usr/bin/env python3
"""CHD Batch Converter - SPDW Factory.

A Linux-first, terminal UI for recursively converting game-disc images to CHD.
Only the Python standard library is required. MAME's chdman is required.

Supported descriptors: CUE, GDI, TOC and ISO. Source files are only eligible
for deletion after successful conversion AND CHD verification. Cleanup is
confirmed twice and is deferred until the complete batch has finished.
"""
from __future__ import annotations

import curses
import json
import os
import platform
import re
import selectors
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

APP_NAME = "CHD Batch Converter"
APP_VERSION = "2.1.0"
FACTORY = "SPDW Factory"
MIN_PYTHON = (3, 9)
SUPPORTED_EXTENSIONS = (".cue", ".gdi", ".toc", ".iso")
DEFAULT_EXTENSIONS = (".cue", ".gdi", ".toc", ".iso")
TRACK_FILE_EXTENSIONS = {".bin", ".raw", ".img", ".wav", ".iso", ".mp3", ".flac", ".aiff", ".ape"}
AUTO_DVD_THRESHOLD = 900 * 1024 * 1024  # Heuristic only; ISO has no reliable CD/DVD marker.
CONFIG_DIR = Path.home() / ".config" / "spdw-factory"
CONFIG_FILE = CONFIG_DIR / "chd-batch-converter.json"
LOG_DIR = Path.home() / ".local" / "share" / "spdw-factory" / "chd-batch-converter" / "logs"


@dataclass
class DiscJob:
    descriptor: Path
    command: str
    sources: Set[Path] = field(default_factory=set)
    references_complete: bool = True
    iso_mode: Optional[str] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class JobResult:
    job: DiscJob
    status: str
    message: str = ""
    output: Optional[Path] = None


@dataclass
class PreviewEntry:
    job: DiscJob
    ready: bool
    reason: str = ""


def default_config() -> Dict[str, object]:
    return {"extensions": list(DEFAULT_EXTENSIONS), "delete_sources": False, "iso_mode": "auto"}


def load_config() -> Dict[str, object]:
    config = default_config()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            exts = data.get("extensions")
            if isinstance(exts, list):
                config["extensions"] = [e for e in SUPPORTED_EXTENSIONS if e in exts]
            if isinstance(data.get("delete_sources"), bool):
                config["delete_sources"] = data["delete_sources"]
            if data.get("iso_mode") in ("auto", "cd", "dvd"):
                config["iso_mode"] = data["iso_mode"]
    except (OSError, ValueError, TypeError):
        pass
    return config


def save_config(config: Dict[str, object]) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        temporary = CONFIG_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, CONFIG_FILE)
    except OSError:
        # Preferences are helpful, but a read-only home directory must not stop conversion.
        pass


def find_chdman() -> Optional[str]:
    found = shutil.which("chdman")
    if found:
        return found
    script_dir = Path(__file__).resolve().parent
    for candidate in (script_dir / "chdman", script_dir / "chdman.AppImage"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def probe_chdman(chdman: Optional[str]) -> Tuple[bool, str]:
    if sys.version_info < MIN_PYTHON:
        return False, "Python 3.9 or newer is required."
    if not chdman:
        return False, "chdman was not found. Install MAME command-line tools (Debian/Ubuntu: sudo apt install mame-tools)."
    try:
        result = subprocess.run(
            [chdman, "--help"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", timeout=10, check=False,
        )
        if not (result.stdout or "").strip():
            return False, "chdman was found but returned no help text. Check that it is executable."
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, "chdman could not be started: " + str(exc)
    return True, chdman


def read_text_compat(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
        return stream.read()


def parse_cue(path: Path) -> Tuple[Set[Path], bool, List[str]]:
    references: Set[Path] = set()
    complete = True
    notes: List[str] = []
    try:
        lines = read_text_compat(path).splitlines()
    except OSError as exc:
        return references, False, ["Could not read CUE sheet: " + str(exc)]
    for line_number, line in enumerate(lines, 1):
        if not re.match(r"^\s*FILE\s+", line, flags=re.IGNORECASE):
            continue
        try:
            tokens = shlex.split(line.replace("\\", "/"), posix=True)
            if len(tokens) < 3 or tokens[0].upper() != "FILE" or not tokens[1]:
                raise ValueError("invalid FILE declaration")
            candidate = Path(tokens[1].replace("\\", os.sep))
            if not candidate.is_absolute():
                candidate = path.parent / candidate
            references.add(Path(os.path.abspath(candidate)))
        except (ValueError, OSError) as exc:
            complete = False
            notes.append("CUE line %d: could not parse FILE path (%s)." % (line_number, exc))
    if not references:
        complete = False
        notes.append("No FILE entries were found in the CUE sheet.")
    return references, complete, notes


def parse_gdi(path: Path) -> Tuple[Set[Path], bool, List[str]]:
    references: Set[Path] = set()
    complete = True
    notes: List[str] = []
    try:
        lines = read_text_compat(path).splitlines()
    except OSError as exc:
        return references, False, ["Could not read GDI sheet: " + str(exc)]
    if not lines or not lines[0].strip().isdigit():
        complete = False
        notes.append("GDI track-count header is missing or invalid.")
    for line_number, line in enumerate([x for x in lines[1:] if x.strip()], 2):
        try:
            tokens = shlex.split(line.replace("\\", "/"), posix=True)
            if len(tokens) < 5 or not tokens[0].isdigit():
                raise ValueError("invalid GDI track row")
            candidate = Path(tokens[4].replace("\\", os.sep))
            if not candidate.is_absolute():
                candidate = path.parent / candidate
            references.add(candidate.resolve(strict=False))
        except (ValueError, OSError) as exc:
            complete = False
            notes.append("GDI line %d: could not parse track path (%s)." % (line_number, exc))
    if not references:
        complete = False
        notes.append("No track files were found in the GDI sheet.")
    return references, complete, notes


def parse_toc(path: Path) -> Tuple[Set[Path], bool, List[str]]:
    references: Set[Path] = set()
    complete = True
    notes: List[str] = []
    try:
        lines = read_text_compat(path).splitlines()
    except OSError as exc:
        return references, False, ["Could not read TOC sheet: " + str(exc)]
    file_commands = {"FILE", "DATAFILE", "AUDIOFILE", "FIFO"}
    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        try:
            tokens = shlex.split(stripped.replace("\\", "/"), posix=True)
            if not tokens or tokens[0].upper() not in file_commands:
                continue
            if len(tokens) < 2:
                raise ValueError("missing file path")
            candidate = Path(tokens[1].replace("\\", os.sep))
            if not candidate.is_absolute():
                candidate = path.parent / candidate
            references.add(candidate.resolve(strict=False))
        except (ValueError, OSError) as exc:
            complete = False
            notes.append("TOC line %d: could not parse source path (%s)." % (line_number, exc))
    if not references:
        complete = False
        notes.append("No source-file entries were found in the TOC sheet.")
    return references, complete, notes


def make_job(descriptor: Path) -> DiscJob:
    extension = descriptor.suffix.lower()
    if extension == ".cue":
        refs, complete, notes = parse_cue(descriptor)
        return DiscJob(descriptor, "createcd", refs, complete, notes=notes)
    if extension == ".gdi":
        refs, complete, notes = parse_gdi(descriptor)
        return DiscJob(descriptor, "createcd", refs, complete, notes=notes)
    if extension == ".toc":
        refs, complete, notes = parse_toc(descriptor)
        return DiscJob(descriptor, "createcd", refs, complete, notes=notes)
    if extension == ".iso":
        return DiscJob(descriptor, "createdvd", {descriptor.resolve(strict=False)}, True)
    raise ValueError("Unsupported input type: " + descriptor.suffix)


def scan_for_jobs(root: Path, on_progress: Optional[Callable[[int, str], None]] = None) -> Tuple[List[DiscJob], int]:
    descriptors: List[Path] = []
    walked_dirs = 0
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirnames[:] = sorted(
            [name for name in dirnames if not (current_path / name).is_symlink()], key=str.casefold
        )
        walked_dirs += 1
        if on_progress and (walked_dirs == 1 or walked_dirs % 12 == 0):
            on_progress(walked_dirs, str(current_path))
        for filename in filenames:
            candidate = current_path / filename
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
                descriptors.append(candidate.resolve())
    descriptors.sort(key=lambda p: (str(p.parent).casefold(), p.name.casefold()))
    if on_progress:
        on_progress(walked_dirs, str(root))
    return [make_job(path) for path in descriptors], walked_dirs


def choose_iso_modes(jobs: Sequence[DiscJob], mode: str) -> None:
    for job in jobs:
        if job.descriptor.suffix.lower() != ".iso":
            continue
        if mode == "cd":
            job.command, job.iso_mode = "createcd", "CD (manual)"
        elif mode == "dvd":
            job.command, job.iso_mode = "createdvd", "DVD (manual)"
        else:
            try:
                size = job.descriptor.stat().st_size
            except OSError:
                size = 0
            if size > AUTO_DVD_THRESHOLD:
                job.command, job.iso_mode = "createdvd", "DVD (auto, size heuristic)"
            else:
                job.command, job.iso_mode = "createcd", "CD (auto, size heuristic)"


def mark_playlist_dependencies(root: Path, jobs: Sequence[DiscJob]) -> None:
    playlist_targets: Set[Path] = set()
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirnames[:] = [name for name in dirnames if not (current_path / name).is_symlink()]
        for filename in filenames:
            playlist = current_path / filename
            if playlist.suffix.lower() not in (".m3u", ".m3u8") or playlist.is_symlink():
                continue
            try:
                lines = read_text_compat(playlist).splitlines()
            except OSError:
                continue
            for line in lines:
                item = line.strip()
                if not item or item.startswith("#"):
                    continue
                candidate = Path(item.replace("\\", os.sep))
                if not candidate.is_absolute():
                    candidate = playlist.parent / candidate
                playlist_targets.add(candidate.resolve(strict=False))
    for job in jobs:
        if job.descriptor.resolve(strict=False) in playlist_targets:
            job.references_complete = False
            job.notes.append("Referenced by an M3U playlist; original files will be kept so the playlist remains usable.")


def is_inside(path: Path, root: Path) -> bool:
    try:
        Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(root)))
        return True
    except (ValueError, OSError):
        return False


def has_symlink_component(path: Path, root: Path) -> bool:
    """Fail closed if the lexical path or any component below root is a symlink."""
    try:
        absolute = Path(os.path.abspath(path))
        relative = absolute.relative_to(Path(os.path.abspath(root)))
    except (ValueError, OSError):
        return True
    current = Path(os.path.abspath(root))
    for part in relative.parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def check_job_structure(job: DiscJob, root: Path) -> Optional[str]:
    if has_symlink_component(job.descriptor, root):
        return "Descriptor path contains a symbolic link; refusing automatic conversion and cleanup."
    try:
        size = job.descriptor.stat().st_size
    except OSError as exc:
        return "Cannot stat source descriptor: " + str(exc)
    if size == 0:
        return "Source descriptor is empty."
    if job.descriptor.suffix.lower() == ".iso":
        if size % 2048 != 0:
            return "ISO size (%s bytes) is not a multiple of 2048; refusing to guess its layout." % format(size, ",")
        return None
    if not job.references_complete:
        job.notes.append("Automatic source deletion is disabled because the descriptor references are incomplete or playlist-backed.")
    missing = [p for p in job.sources if not p.is_file()]
    if missing:
        return "Missing referenced track file(s): " + ", ".join(str(p) for p in missing[:3])
    if not job.sources:
        return "No referenced track files were identified."
    for source in job.sources:
        if has_symlink_component(source, root):
            return "Referenced track path contains a symbolic link; refusing automatic conversion and cleanup."
        if not is_inside(source, root):
            job.references_complete = False
            job.notes.append("External source will be preserved: " + str(source))
    return None


def output_for(job: DiscJob) -> Path:
    return job.descriptor.with_suffix(".chd")


def prepare_preview(selected_jobs: Sequence[DiscJob], all_jobs: Sequence[DiscJob], root: Path) -> List[PreviewEntry]:
    output_owners: Dict[Path, List[DiscJob]] = defaultdict(list)
    for job in all_jobs:
        output_owners[output_for(job).resolve(strict=False)].append(job)
    entries: List[PreviewEntry] = []
    for job in selected_jobs:
        reason = check_job_structure(job, root)
        output = output_for(job)
        if len(output_owners[output.resolve(strict=False)]) > 1:
            reason = "Output filename collision: multiple discovered descriptors would create this CHD."
        elif output.exists():
            reason = "Output already exists; it will not be overwritten."
        entries.append(PreviewEntry(job, reason is None, reason or ""))
    return entries


def file_signature(path: Path) -> Optional[Tuple[int, int, int]]:
    try:
        stat = os.stat(path, follow_symlinks=False)
        if not path.is_file() or path.is_symlink():
            return None
        return stat.st_size, stat.st_mtime_ns, stat.st_ino
    except OSError:
        return None


def collect_initial_signatures(jobs: Sequence[DiscJob]) -> Dict[Path, Optional[Tuple[int, int, int]]]:
    candidates: Set[Path] = set()
    for job in jobs:
        candidates.add(job.descriptor)
        candidates.update(job.sources)
    return {path: file_signature(path) for path in candidates}


def has_unsupported_sidecar(source: Path) -> bool:
    if source.suffix.lower() not in {".bin", ".img", ".raw"}:
        return False
    try:
        siblings = list(source.parent.iterdir())
    except OSError:
        return True
    sidecars = {".ccd", ".mds", ".nrg", ".cdi"}
    for child in siblings:
        if child.stem.casefold() == source.stem.casefold() and child.suffix.lower() in sidecars:
            return True
        if child.name.casefold() == (source.name + ".ecm").casefold():
            return True
    return False


def delete_successful_sources(
    root: Path,
    all_jobs: Sequence[DiscJob],
    results: Sequence[JobResult],
    signatures: Dict[Path, Optional[Tuple[int, int, int]]],
) -> Tuple[int, int, List[str]]:
    successful = {result.job.descriptor for result in results if result.status == "SUCCESS"}
    owners: Dict[Path, Set[Path]] = defaultdict(set)
    job_lookup = {job.descriptor: job for job in all_jobs}
    for job in all_jobs:
        for source in job.sources:
            owners[source].add(job.descriptor)
    deletion_candidates: Set[Path] = set()
    protected: Dict[Path, str] = {}

    # Every discovered descriptor participates in ownership checks, even if its extension was unchecked.
    for job in all_jobs:
        if not job.references_complete:
            protected[job.descriptor] = "source layout is incomplete or playlist-backed"
            for source in job.sources:
                if is_inside(source, root):
                    protected[source] = "belongs to an uncertain or playlist-backed source set"
            try:
                siblings = list(job.descriptor.parent.iterdir())
            except OSError:
                siblings = []
            for sibling in siblings:
                if sibling.is_file() and sibling.suffix.lower() in TRACK_FILE_EXTENSIONS and is_inside(sibling, root):
                    protected.setdefault(sibling, "same folder as an uncertain source set")

    for descriptor in successful:
        job = job_lookup[descriptor]
        if not job.references_complete:
            continue
        if descriptor not in protected and is_inside(descriptor, root):
            deletion_candidates.add(descriptor)
        else:
            protected.setdefault(descriptor, "outside the selected folder or protected by another rule")
        for source in job.sources:
            if not is_inside(source, root):
                protected[source] = "outside the selected folder"
                continue
            if source in protected:
                continue
            source_owners = owners.get(source, set())
            all_owners_safe = bool(source_owners) and all(
                owner in successful and owner in job_lookup and job_lookup[owner].references_complete
                for owner in source_owners
            )
            if not all_owners_safe:
                protected[source] = "shared with an image that was skipped, unchecked, or failed"
            elif has_unsupported_sidecar(source):
                protected[source] = "matching sidecar suggests another unsupported image set may use this track"
            else:
                deletion_candidates.add(source)

    deleted = 0
    details: List[str] = []
    for path in sorted(deletion_candidates, key=lambda p: str(p).casefold()):
        before = signatures.get(path)
        after = file_signature(path)
        if before is None or after != before:
            protected[path] = "source changed or could not be checked during the batch"
            continue
        try:
            path.unlink()
            deleted += 1
            details.append("DELETED  " + str(path))
        except OSError as exc:
            protected[path] = "could not be deleted: " + str(exc)
    preserved_paths = sorted((p for p in protected if p.exists()), key=lambda p: str(p).casefold())
    for path in preserved_paths:
        details.append("KEPT     %s -- %s" % (path, protected[path]))
    return deleted, len(preserved_paths), details


def bar(value: float, width: int) -> str:
    width = max(5, width)
    filled = int(max(0.0, min(100.0, value)) * width / 100.0)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def safe_add(stdscr, y: int, x: int, value: str, width: int, attr: int = 0) -> None:
    if y < 0 or x < 0 or width <= 0:
        return
    try:
        stdscr.addnstr(y, x, str(value), width, attr)
    except (curses.error, UnicodeEncodeError):
        try:
            cleaned = str(value).encode("ascii", "replace").decode("ascii")
            stdscr.addnstr(y, x, cleaned, width, attr)
        except curses.error:
            pass


def init_colors() -> Dict[str, int]:
    colors: Dict[str, int] = {}
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_RED, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(6, curses.COLOR_WHITE, -1)
        colors = {"green": curses.color_pair(1), "red": curses.color_pair(2),
                  "yellow": curses.color_pair(3), "cyan": curses.color_pair(4),
                  "selected": curses.color_pair(5), "white": curses.color_pair(6)}
    except curses.error:
        colors = {key: 0 for key in ("green", "red", "yellow", "cyan", "selected", "white")}
    return colors


def header(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str], subtitle: str = "") -> int:
    height, width = stdscr.getmaxyx()
    safe_add(stdscr, 0, 2, "SPDW FACTORY  //  CHD BATCH CONVERTER", max(1, width - 4), curses.A_BOLD | colors.get("cyan", 0))
    version = "v" + APP_VERSION
    safe_add(stdscr, 0, max(2, width - len(version) - 3), version, len(version) + 1, curses.A_BOLD)
    safe_add(stdscr, 1, 2, "Recursive game-disc conversion utility", max(1, width - 4), colors.get("white", 0))
    led = "●" if dependency_ok else "●"
    status = "CHDMAN ONLINE" if dependency_ok else "CHDMAN MISSING"
    led_attr = colors.get("green" if dependency_ok else "red", 0) | curses.A_BOLD
    safe_add(stdscr, 1, max(2, width - len(status) - 7), led, 2, led_attr)
    safe_add(stdscr, 1, max(4, width - len(status) - 5), status, len(status) + 1, led_attr)
    safe_add(stdscr, 2, 2, "-" * max(1, width - 4), max(1, width - 4), colors.get("cyan", 0))
    if subtitle:
        safe_add(stdscr, 3, 2, subtitle, max(1, width - 4), curses.A_BOLD)
    return height


def footer(stdscr, message: str) -> None:
    height, width = stdscr.getmaxyx()
    safe_add(stdscr, height - 2, 2, "-" * max(1, width - 4), max(1, width - 4))
    safe_add(stdscr, height - 1, 2, message, max(1, width - 4), curses.A_DIM)


def screen_too_small(stdscr) -> bool:
    height, width = stdscr.getmaxyx()
    if height >= 24 and width >= 72:
        return False
    stdscr.erase()
    safe_add(stdscr, 1, 2, APP_NAME + " v" + APP_VERSION, max(1, width - 4), curses.A_BOLD)
    safe_add(stdscr, 3, 2, "Please enlarge the terminal to at least 72 columns x 24 rows.", max(1, width - 4))
    safe_add(stdscr, 5, 2, "Press Q to quit.", max(1, width - 4))
    stdscr.refresh()
    return True


def boot_animation(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str]) -> None:
    frames = ["[          ]", "[##        ]", "[####      ]", "[######    ]", "[########  ]", "[##########]"]
    for frame in frames:
        stdscr.erase()
        header(stdscr, colors, dependency_ok, chdman, "INITIALIZING CONVERSION ENVIRONMENT")
        safe_add(stdscr, 7, 4, "   ____ _   _ ____", 48, curses.A_BOLD | colors.get("cyan", 0))
        safe_add(stdscr, 8, 4, '  / ___| | | |  _ \\', 48, curses.A_BOLD | colors.get("cyan", 0))
        safe_add(stdscr, 9, 4, " | |   | |_| | | | |", 48, curses.A_BOLD | colors.get("cyan", 0))
        safe_add(stdscr, 10, 4, " | |___|  _  | |_| |", 48, curses.A_BOLD | colors.get("cyan", 0))
        safe_add(stdscr, 11, 4, "  \\____|_| |_|____/", 48, curses.A_BOLD | colors.get("cyan", 0))
        safe_add(stdscr, 13, 4, "SPDW Factory", 40, curses.A_BOLD)
        safe_add(stdscr, 15, 4, frame, 20, colors.get("green", 0))
        safe_add(stdscr, 16, 4, "Loading safe conversion modules...", 50)
        stdscr.refresh()
        time.sleep(0.055)


def main_menu_items(config: Dict[str, object]) -> List[str]:
    """Return the main menu in display order; START is always the primary action."""
    delete_label = "ON  (requires two confirmations)" if config.get("delete_sources") else "OFF (recommended)"
    iso_mode = str(config.get("iso_mode", "auto")).upper()
    ext_count = len(config.get("extensions", []))
    return [
        "START  - Scan and convert selected folder",
        "Select folder",
        "File extensions  [%d/%d enabled]" % (ext_count, len(SUPPORTED_EXTENSIONS)),
        "Delete source files after verification  [%s]" % delete_label,
        "ISO interpretation  [%s]" % iso_mode,
        "About / safety information",
        "Quit",
    ]


def draw_menu(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str], config: Dict[str, object], selected: int, folder: Optional[Path], notice: str) -> None:
    stdscr.erase()
    header(stdscr, colors, dependency_ok, chdman, "MAIN MENU")
    width = stdscr.getmaxyx()[1]
    safe_add(stdscr, 5, 4, "Choose an operation:", width - 8, curses.A_BOLD)
    items = main_menu_items(config)
    for i, item in enumerate(items):
        attr = colors.get("selected", 0) | curses.A_BOLD if i == selected else 0
        prefix = "> " if i == selected else "  "
        safe_add(stdscr, 6 + i, 5, prefix + item, width - 10, attr)
    safe_add(stdscr, 15, 4, "Selected folder:", width - 8, curses.A_BOLD)
    safe_add(stdscr, 16, 4, str(folder) if folder else "(not selected - choose a folder, then press START)", width - 8)
    safe_add(stdscr, 17, 4, "Python %s  |  %s  |  Standard library only" % (platform.python_version(), platform.system()), width - 8, curses.A_DIM)
    if not dependency_ok:
        safe_add(stdscr, 18, 4, "DEPENDENCY ERROR: " + (notice or "Install MAME tools to enable conversion."), width - 8, colors.get("red", 0) | curses.A_BOLD)
    elif notice:
        safe_add(stdscr, 18, 4, notice, width - 8, colors.get("yellow", 0))
    elif chdman:
        safe_add(stdscr, 18, 4, "chdman: " + chdman, width - 8, curses.A_DIM)
    footer(stdscr, "UP/DOWN: move   ENTER: select   SPACE: toggle cleanup   Q: quit")
    stdscr.refresh()


def folder_picker(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str]) -> Optional[Path]:
    current = Path.home().resolve()
    selected = 0
    scroll = 0
    while True:
        stdscr.erase()
        width = stdscr.getmaxyx()[1]
        header(stdscr, colors, dependency_ok, chdman, "FOLDER BROWSER")
        safe_add(stdscr, 5, 3, "Current directory:", width - 6, curses.A_BOLD)
        safe_add(stdscr, 6, 3, str(current), width - 6)
        safe_add(stdscr, 8, 3, "Directories  |  ENTER: open  |  BACKSPACE: parent", width - 6, curses.A_UNDERLINE)
        dirs: List[Optional[Path]] = [None]
        try:
            with os.scandir(current) as iterator:
                children = []
                for entry in iterator:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            children.append(Path(entry.path))
                    except OSError:
                        continue
            dirs.extend(sorted(children, key=lambda p: (p.name.casefold(), p.name)))
        except OSError as exc:
            safe_add(stdscr, 10, 3, "Cannot read this folder: " + str(exc), width - 6, colors.get("red", 0))
        height = stdscr.getmaxyx()[0]
        visible = max(1, height - 13)
        selected = max(0, min(selected, len(dirs) - 1))
        if selected < scroll:
            scroll = selected
        elif selected >= scroll + visible:
            scroll = selected - visible + 1
        for row, idx in enumerate(range(scroll, min(len(dirs), scroll + visible))):
            item = dirs[idx]
            label = "[..] Parent directory" if item is None else "[DIR] " + item.name + "/"
            attr = colors.get("selected", 0) | curses.A_BOLD if idx == selected else 0
            safe_add(stdscr, 10 + row, 5, ("> " if idx == selected else "  ") + label, width - 10, attr)
        footer(stdscr, "S: select current folder   Q/ESC: cancel   Hidden folders are included")
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = min(len(dirs) - 1, selected + 1)
        elif key in (curses.KEY_PPAGE,):
            selected = max(0, selected - visible)
        elif key in (curses.KEY_NPAGE,):
            selected = min(len(dirs) - 1, selected + visible)
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if current.parent != current:
                current = current.parent
                selected = scroll = 0
        elif key in (curses.KEY_ENTER, 10, 13):
            if dirs[selected] is None:
                if current.parent != current:
                    current = current.parent
                    selected = scroll = 0
            else:
                current = dirs[selected].resolve()
                selected = scroll = 0
        elif key in (ord("s"), ord("S"), ord(" ")):
            return current
        elif key in (ord("q"), ord("Q"), 27):
            return None


def extension_menu(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str], config: Dict[str, object]) -> None:
    selected_exts = set(config.get("extensions", DEFAULT_EXTENSIONS))
    cursor = 0
    while True:
        stdscr.erase()
        width = stdscr.getmaxyx()[1]
        header(stdscr, colors, dependency_ok, chdman, "SEARCH EXTENSIONS")
        safe_add(stdscr, 5, 4, "Select the disc-image descriptors to include in recursive scans.", width - 8)
        safe_add(stdscr, 7, 4, "These are supported input formats, not raw track files.", width - 8, curses.A_DIM)
        for index, ext in enumerate(SUPPORTED_EXTENSIONS):
            checked = "[x]" if ext in selected_exts else "[ ]"
            attr = colors.get("selected", 0) | curses.A_BOLD if cursor == index else 0
            safe_add(stdscr, 10 + index * 2, 6, ("> " if cursor == index else "  ") + checked + "  " + ext.upper(), width - 12, attr)
        safe_add(stdscr, 19, 4, "Raw .BIN/.IMG tracks are discovered through their descriptor and are never scanned alone.", width - 8, curses.A_DIM)
        footer(stdscr, "UP/DOWN: move   SPACE: toggle   A: all   D: defaults   ENTER: save   ESC: back")
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(SUPPORTED_EXTENSIONS)
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(SUPPORTED_EXTENSIONS)
        elif key == ord(" "):
            ext = SUPPORTED_EXTENSIONS[cursor]
            if ext in selected_exts:
                if len(selected_exts) > 1:
                    selected_exts.remove(ext)
            else:
                selected_exts.add(ext)
        elif key in (10, 13):
            config["extensions"] = [ext for ext in SUPPORTED_EXTENSIONS if ext in selected_exts]
            save_config(config)
            return
        elif key in (ord("a"), ord("A")):
            selected_exts = set(SUPPORTED_EXTENSIONS)
        elif key in (ord("d"), ord("D")):
            selected_exts = set(DEFAULT_EXTENSIONS)
        elif key in (27, ord("q"), ord("Q")):
            if selected_exts:
                config["extensions"] = [ext for ext in SUPPORTED_EXTENSIONS if ext in selected_exts]
                save_config(config)
            return


def iso_menu(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str], config: Dict[str, object]) -> None:
    modes = ["auto", "cd", "dvd"]
    current = str(config.get("iso_mode", "auto"))
    cursor = modes.index(current) if current in modes else 0
    labels = [
        "Auto-detect using file size (recommended; heuristic)",
        "Treat every ISO as a CD image",
        "Treat every ISO as a DVD image",
    ]
    while True:
        stdscr.erase()
        width = stdscr.getmaxyx()[1]
        header(stdscr, colors, dependency_ok, chdman, "ISO HANDLING")
        safe_add(stdscr, 5, 4, "ISO does not reliably indicate whether the source is a CD or DVD.", width - 8)
        for index, label in enumerate(labels):
            attr = colors.get("selected", 0) | curses.A_BOLD if index == cursor else 0
            safe_add(stdscr, 8 + index * 2, 5, ("> " if cursor == index else "  ") + label, width - 10, attr)
        safe_add(stdscr, 16, 4, "Auto mode uses 900 MiB as a practical size heuristic, not a guarantee.", width - 8, colors.get("yellow", 0))
        footer(stdscr, "UP/DOWN: choose   ENTER: save   ESC: back")
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % 3
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % 3
        elif key in (10, 13):
            config["iso_mode"] = modes[cursor]
            save_config(config)
            return
        elif key in (27, ord("q"), ord("Q")):
            return


def about_screen(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str]) -> None:
    stdscr.erase()
    width = stdscr.getmaxyx()[1]
    header(stdscr, colors, dependency_ok, chdman, "ABOUT / SAFETY")
    lines = [
        "SPDW Factory presents CHD Batch Converter v" + APP_VERSION,
        "",
        "SUPPORTED INPUTS: .CUE / .GDI / .TOC / .ISO",
        "Conversion backend: MAME chdman (createcd / createdvd / verify).",
        "No third-party Python packages are required.",
        "",
        "SAFETY RULES",
        "- Existing CHD files are never overwritten.",
        "- Output is created as a temporary file and verified before publishing.",
        "- Source deletion is OFF by default and requires two confirmations.",
        "- Cleanup happens only after the complete batch succeeds or finishes.",
        "- Shared tracks are kept if any discovered image is skipped or fails.",
        "- M3U-backed files, external tracks and uncertain layouts are preserved.",
        "- Symlink directories and symlink files are not followed.",
        "",
        "Overall progress counts processed titles; each title's progress is read",
        "from chdman's own output when the installed version reports it.",
        "",
        "SPDW Factory",
    ]
    for i, line in enumerate(lines):
        safe_add(stdscr, 4 + i, 4, line, width - 8, curses.A_BOLD if line in ("SAFETY RULES", "SPDW Factory") else 0)
    footer(stdscr, "Press any key to return")
    stdscr.refresh()
    stdscr.getch()


def draw_scanning(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str], root: Path, dirs: int, current: str) -> None:
    stdscr.erase()
    width = stdscr.getmaxyx()[1]
    header(stdscr, colors, dependency_ok, chdman, "SCANNING GAME LIBRARY")
    safe_add(stdscr, 6, 4, "Selected folder:", width - 8, curses.A_BOLD)
    safe_add(stdscr, 7, 4, str(root), width - 8)
    safe_add(stdscr, 10, 4, "Directories visited: %d" % dirs, width - 8, colors.get("cyan", 0))
    safe_add(stdscr, 12, 4, "Current location:", width - 8, curses.A_BOLD)
    safe_add(stdscr, 13, 4, current, width - 8)
    safe_add(stdscr, 16, 4, "Searching recursively. Hidden folders are included; symlink folders are skipped.", width - 8)
    stdscr.refresh()


def draw_results(
    stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str], root: Path,
    entries: Sequence[PreviewEntry], cursor: int, scroll: int, delete_sources: bool, folders_scanned: int,
) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    header(stdscr, colors, dependency_ok, chdman, "SCAN RESULTS / CONVERSION QUEUE")
    ready = sum(1 for e in entries if e.ready)
    skipped = len(entries) - ready
    safe_add(stdscr, 5, 3, "Folder: " + str(root), width - 6)
    safe_add(stdscr, 6, 3, "Directories: %d  |  Found: %d  |  Ready: %d  |  Skipped: %d" % (folders_scanned, len(entries), ready, skipped), width - 6, curses.A_BOLD)
    cleanup_text = "[x] DELETE SOURCES after successful verification" if delete_sources else "[ ] DELETE SOURCES after successful verification"
    safe_add(stdscr, 8, 3, cleanup_text, width - 6, colors.get("red" if delete_sources else "green", 0) | curses.A_BOLD)
    safe_add(stdscr, 9, 3, "Source cleanup: %s" % ("ARMED - extra confirmation required" if delete_sources else "OFF - originals will be kept"), width - 6, colors.get("yellow" if delete_sources else "green", 0))
    list_top = 12
    visible = max(1, height - 17)
    if cursor < scroll:
        scroll = cursor
    elif cursor >= scroll + visible:
        scroll = cursor - visible + 1
    if not entries:
        safe_add(stdscr, list_top, 5, "No supported descriptors were found for the selected extensions.", width - 10)
    for row, idx in enumerate(range(scroll, min(len(entries), scroll + visible))):
        entry = entries[idx]
        state = "READY" if entry.ready else "SKIP "
        name = str(entry.job.descriptor.relative_to(root)) if is_inside(entry.job.descriptor, root) else str(entry.job.descriptor)
        suffix = " -> " + output_for(entry.job).name if entry.ready else " -- " + entry.reason
        text = "[%s] %s%s" % (state, name, suffix)
        attr = colors.get("green" if entry.ready else "red", 0)
        if idx == cursor:
            attr |= curses.A_REVERSE | curses.A_BOLD
        safe_add(stdscr, list_top + row, 4, text, width - 8, attr)
    footer(stdscr, "UP/DOWN: inspect   D: toggle cleanup   ENTER: start   Q/ESC: back to menu")
    stdscr.refresh()


def confirm_cleanup_arm(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str]) -> bool:
    stdscr.erase()
    width = stdscr.getmaxyx()[1]
    header(stdscr, colors, dependency_ok, chdman, "ENABLE SOURCE CLEANUP?")
    lines = [
        "WARNING: enabling cleanup allows the program to permanently delete original source files.",
        "Only files belonging to successfully created AND verified CHDs can qualify.",
        "Shared tracks, playlist-backed files, uncertain descriptors and external files are kept.",
        "Cleanup is deferred until every conversion has finished.",
        "",
        "Type DELETE and press ENTER to arm cleanup for this batch.",
        "You will be asked again after conversion, immediately before deletion.",
    ]
    for i, line in enumerate(lines):
        safe_add(stdscr, 6 + i * 2, 4, line, width - 8, colors.get("red", 0) if i == 0 else 0)
    safe_add(stdscr, 22, 4, "Confirmation: ", width - 8, curses.A_BOLD)
    stdscr.refresh()
    try:
        curses.echo()
        curses.curs_set(1)
        raw = stdscr.getstr(22, 18, 20)
        answer = raw.decode("utf-8", "replace").strip()
    except curses.error:
        answer = ""
    finally:
        curses.noecho()
        try:
            curses.curs_set(0)
        except curses.error:
            pass
    return answer == "DELETE"


def confirm_cleanup_final(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str], results: Sequence[JobResult]) -> bool:
    successful = sum(1 for r in results if r.status == "SUCCESS")
    stdscr.erase()
    width = stdscr.getmaxyx()[1]
    header(stdscr, colors, dependency_ok, chdman, "FINAL SOURCE DELETION CONFIRMATION")
    safe_add(stdscr, 6, 4, "%d CHD image(s) were created and verified." % successful, width - 8, curses.A_BOLD)
    safe_add(stdscr, 8, 4, "Original descriptors and referenced tracks may now be deleted.", width - 8, colors.get("red", 0) | curses.A_BOLD)
    safe_add(stdscr, 10, 4, "The safety rules will preserve shared, uncertain and playlist-backed files.", width - 8)
    safe_add(stdscr, 13, 4, "Type DELETE to permanently remove eligible originals.", width - 8)
    safe_add(stdscr, 16, 4, "Confirmation: ", width - 8, curses.A_BOLD)
    stdscr.refresh()
    try:
        curses.echo()
        curses.curs_set(1)
        raw = stdscr.getstr(16, 18, 20)
        answer = raw.decode("utf-8", "replace").strip()
    except curses.error:
        answer = ""
    finally:
        curses.noecho()
        try:
            curses.curs_set(0)
        except curses.error:
            pass
    return answer == "DELETE"


def run_monitored_command(
    stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str],
    command: Sequence[str], phase: str, state: Dict[str, object],
) -> Tuple[int, bool]:
    """Run chdman without blocking the UI; parse its reported percentage if available."""
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    except OSError as exc:
        state["log"] = ["Could not start chdman: " + str(exc)]
        return 127, False
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    try:
        stdscr.timeout(0)
    except curses.error:
        pass
    fd = process.stdout.fileno()
    os.set_blocking(fd, False)
    selector.register(fd, selectors.EVENT_READ)
    pending = ""
    canceled = False
    last_draw = 0.0
    try:
        while True:
            for key, _mask in selector.select(timeout=0.08):
                try:
                    chunk = os.read(key.fd, 8192)
                except BlockingIOError:
                    continue
                if not chunk:
                    try:
                        selector.unregister(key.fd)
                    except Exception:
                        pass
                    continue
                decoded = chunk.decode("utf-8", "replace")
                pending += decoded
                parts = re.split(r"[\r\n]", pending)
                pending = parts.pop() if parts else ""
                for line in parts:
                    cleaned = line.strip()
                    if cleaned:
                        logs = state.setdefault("log", [])
                        logs.append(cleaned)
                        del logs[:-3]
                    match = re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%", line)
                    if match:
                        try:
                            pct = max(0.0, min(100.0, float(match[-1])))
                            state["title_pct"] = pct
                        except ValueError:
                            pass
            if pending.strip():
                match = re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%", pending)
                if match:
                    try:
                        pct = max(0.0, min(100.0, float(match[-1])))
                        state["title_pct"] = pct
                    except ValueError:
                        pass
            now = time.monotonic()
            if now - last_draw >= 0.10:
                draw_progress_screen(stdscr, colors, dependency_ok, chdman, state)
                last_draw = now
            keypress = stdscr.getch()
            if keypress in (ord("q"), ord("Q"), 27) and process.poll() is None:
                canceled = True
                state["phase"] = "Stopping current chdman process..."
                try:
                    process.terminate()
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                break
            if process.poll() is not None and not selector.get_map():
                break
        if pending.strip():
            logs = state.setdefault("log", [])
            logs.append(pending.strip())
            del logs[:-3]
        return process.wait(), canceled
    except KeyboardInterrupt:
        try:
            process.terminate()
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        raise
    finally:
        selector.close()
        process.stdout.close()
        try:
            stdscr.timeout(-1)
        except curses.error:
            pass


def draw_progress_screen(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str], state: Dict[str, object]) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    header(stdscr, colors, dependency_ok, chdman, "CONVERSION IN PROGRESS")
    index = int(state.get("index", 0))
    total = max(1, int(state.get("total", 1)))
    completed = int(state.get("completed", 0))
    pct_obj = state.get("title_pct")
    pct = float(pct_obj) if isinstance(pct_obj, (float, int)) else None
    overall = completed / total * 100.0
    safe_add(stdscr, 5, 3, "Overall batch progress: %d/%d titles processed" % (completed, total), width - 6, curses.A_BOLD)
    safe_add(stdscr, 6, 3, bar(overall, max(10, width - 25)) + "  %5.1f%%" % overall, width - 6, colors.get("cyan", 0) | curses.A_BOLD)
    safe_add(stdscr, 9, 3, "Current title: %d/%d" % (index, total), width - 6, curses.A_BOLD)
    safe_add(stdscr, 10, 3, str(state.get("title", "")), width - 6)
    pct_text = "%5.1f%%" % pct if pct is not None else "  --  "
    safe_add(stdscr, 12, 3, "Title progress: " + pct_text, width - 6, curses.A_BOLD)
    safe_add(stdscr, 13, 3, bar(pct or 0.0, max(10, width - 25)), width - 6, colors.get("green", 0))
    safe_add(stdscr, 15, 3, "Stage: " + str(state.get("phase", "Preparing")), width - 6, colors.get("yellow", 0))
    safe_add(stdscr, 17, 3, "chdman output:", width - 6, curses.A_BOLD)
    logs = state.get("log", [])
    for line_index, line in enumerate(logs[-3:]):
        safe_add(stdscr, 18 + line_index, 5, line, width - 10, curses.A_DIM)
    safe_add(stdscr, min(height - 3, 21), 3, "Overall advances per processed title; current-stage percent is from chdman.", width - 6, curses.A_DIM)
    footer(stdscr, "Q/ESC: stop current conversion (all source files will be kept)")
    stdscr.refresh()


def run_chdman_tui(
    stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: str, job: DiscJob,
    state: Dict[str, object],
) -> Tuple[bool, bool, str]:
    output = output_for(job)
    temporary = output.with_name(".%s.%s.partial.chd" % (output.stem, uuid.uuid4().hex[:10]))
    if output.exists():
        return False, False, "Output already exists; refusing to overwrite."
    create_cmd = [chdman, job.command, "-i", str(job.descriptor), "-o", str(temporary)]
    state["phase"] = "Creating CHD"
    state["title_pct"] = None
    try:
        code, canceled = run_monitored_command(stdscr, colors, dependency_ok, chdman, create_cmd, "create", state)
    except KeyboardInterrupt:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    if canceled:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False, True, "Canceled by user. Original files were kept."
    if code != 0:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False, False, "chdman %s failed with exit code %d. Sources were kept." % (job.command, code)
    try:
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("no usable output was produced")
    except (OSError, RuntimeError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False, False, "Temporary CHD check failed: " + str(exc)
    state["phase"] = "Verifying CHD integrity"
    state["title_pct"] = None
    verify_cmd = [chdman, "verify", "-i", str(temporary)]
    try:
        code, canceled = run_monitored_command(stdscr, colors, dependency_ok, chdman, verify_cmd, "verify", state)
    except KeyboardInterrupt:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    if canceled:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False, True, "Verification canceled. Original files were kept."
    if code != 0:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False, False, "CHD verification failed with exit code %d. Sources were kept." % code
    if output.exists():
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False, False, "Output appeared during conversion; refusing to overwrite."
    try:
        os.link(temporary, output)
    except FileExistsError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False, False, "Output appeared during conversion; refusing to overwrite."
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False, False, "Could not safely publish verified CHD: " + str(exc)
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass
    state["title_pct"] = 100.0
    state["phase"] = "CHD created and verified"
    return True, False, "CHD created and verified."


def write_batch_log(root: Path, results: Sequence[JobResult], deleted: int, preserved: int, details: Sequence[str], interrupted: bool) -> Optional[Path]:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = LOG_DIR / ("batch_" + stamp + ".log")
        lines = [APP_NAME + " v" + APP_VERSION, FACTORY, "Date: " + datetime.now().isoformat(timespec="seconds"), "Folder: " + str(root), "Interrupted: " + str(interrupted), ""]
        for result in results:
            lines.append("[%s] %s -> %s" % (result.status, result.job.descriptor, output_for(result.job)))
            lines.append("  " + result.message)
        lines.extend(["", "Deleted source files: %d" % deleted, "Preserved source files: %d" % preserved, ""])
        lines.extend(details)
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return destination
    except OSError:
        return None


def draw_summary(stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str], results: Sequence[JobResult], deleted: int, preserved: int, cleanup_enabled: bool, interrupted: bool, log_path: Optional[Path], cleanup_details: Sequence[str]) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    header(stdscr, colors, dependency_ok, chdman, "BATCH SUMMARY")
    success = sum(1 for r in results if r.status == "SUCCESS")
    failed = sum(1 for r in results if r.status == "FAILED")
    safe_add(stdscr, 5, 4, "Converted and verified: %d" % success, width - 8, colors.get("green", 0) | curses.A_BOLD)
    safe_add(stdscr, 6, 4, "Failed: %d" % failed, width - 8, colors.get("red", 0) if failed else 0)
    safe_add(stdscr, 7, 4, "Interrupted: %s" % ("YES - cleanup disabled" if interrupted else "NO"), width - 8)
    if cleanup_enabled and not interrupted:
        safe_add(stdscr, 9, 4, "Source files deleted: %d" % deleted, width - 8, colors.get("yellow", 0) | curses.A_BOLD)
        safe_add(stdscr, 10, 4, "Source files preserved: %d" % preserved, width - 8)
    else:
        safe_add(stdscr, 9, 4, "Source cleanup: OFF - all original files kept", width - 8, colors.get("green", 0))
    safe_add(stdscr, 12, 4, "Per-title results:", width - 8, curses.A_BOLD)
    for index, result in enumerate(results[:max(1, height - 18)]):
        mark = "OK" if result.status == "SUCCESS" else "FAIL"
        attr = colors.get("green" if mark == "OK" else "red", 0)
        safe_add(stdscr, 13 + index, 6, "[%s] %s" % (mark, result.job.descriptor.name), width - 12, attr)
    if log_path:
        safe_add(stdscr, min(height - 5, 22), 4, "Log saved: " + str(log_path), width - 8, curses.A_DIM)
    if cleanup_details:
        safe_add(stdscr, min(height - 4, 23), 4, "Cleanup detail lines: %d (full list in log)" % len(cleanup_details), width - 8, curses.A_DIM)
    footer(stdscr, "Press any key to return to the main menu")
    stdscr.refresh()
    stdscr.getch()


def run_batch(
    stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: str, root: Path,
    runnable: Sequence[DiscJob], all_jobs: Sequence[DiscJob], delete_sources: bool,
) -> None:
    signatures = collect_initial_signatures(all_jobs)
    results: List[JobResult] = []
    total = len(runnable)
    interrupted = False
    for index, job in enumerate(runnable, 1):
        state: Dict[str, object] = {
            "index": index, "total": total, "completed": index - 1,
            "title": str(job.descriptor), "title_pct": None, "phase": "Starting chdman", "log": [],
        }
        draw_progress_screen(stdscr, colors, dependency_ok, chdman, state)
        try:
            success, canceled, message = run_chdman_tui(stdscr, colors, dependency_ok, chdman, job, state)
        except KeyboardInterrupt:
            success, canceled, message = False, True, "Interrupted by user. Sources were kept."
        results.append(JobResult(job, "SUCCESS" if success else "FAILED", message, output_for(job) if success else None))
        state["completed"] = index
        state["phase"] = "CHD created and verified" if success else "Conversion failed"
        if success:
            state["title_pct"] = 100.0
        else:
            state["title_pct"] = None
        draw_progress_screen(stdscr, colors, dependency_ok, chdman, state)
        time.sleep(0.12)
        if canceled:
            interrupted = True
            break
    deleted = 0
    preserved = 0
    cleanup_details: List[str] = []
    cleanup_enabled = delete_sources and not interrupted
    if cleanup_enabled and any(r.status == "SUCCESS" for r in results):
        if confirm_cleanup_final(stdscr, colors, dependency_ok, chdman, results):
            deleted, preserved, cleanup_details = delete_successful_sources(root, all_jobs, results, signatures)
        else:
            cleanup_enabled = False
            cleanup_details.append("Cleanup canceled at final confirmation; every original file was kept.")
    elif delete_sources and interrupted:
        cleanup_details.append("Cleanup disabled because the batch was interrupted.")
    elif delete_sources and not any(r.status == "SUCCESS" for r in results):
        cleanup_enabled = False
        cleanup_details.append("No verified CHDs were produced; no source files were eligible for deletion.")
    log_path = write_batch_log(root, results, deleted, preserved, cleanup_details, interrupted)
    draw_summary(stdscr, colors, dependency_ok, chdman, results, deleted, preserved, cleanup_enabled, interrupted, log_path, cleanup_details)


def start_conversion_flow(
    stdscr, colors: Dict[str, int], dependency_ok: bool, chdman: Optional[str],
    config: Dict[str, object], selected_folder: Optional[Path],
) -> Tuple[Optional[Path], str]:
    """Scan the selected folder and run the reviewed conversion queue."""
    if not dependency_ok:
        return selected_folder, "Install MAME tools before starting a conversion."

    root = selected_folder
    if root is None:
        root = folder_picker(stdscr, colors, dependency_ok, chdman)
        if root is None:
            return None, "Folder selection canceled. Choose a folder before pressing START."
    try:
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(str(root))
    except OSError as exc:
        return None, "Selected folder is not accessible: " + str(exc)

    def update_scan(count: int, location: str) -> None:
        draw_scanning(stdscr, colors, dependency_ok, chdman, root, count, location)

    all_jobs, folders_scanned = scan_for_jobs(root, update_scan)
    mark_playlist_dependencies(root, all_jobs)
    selected_exts = set(config.get("extensions", DEFAULT_EXTENSIONS))
    selected_jobs = [job for job in all_jobs if job.descriptor.suffix.lower() in selected_exts]
    choose_iso_modes(all_jobs, str(config.get("iso_mode", "auto")))
    entries = prepare_preview(selected_jobs, all_jobs, root)
    if not entries:
        return root, "No descriptors matched the selected extensions. Adjust File extensions and press START again."

    runnable = [entry.job for entry in entries if entry.ready]
    cursor = 0
    scroll = 0
    delete_for_batch = bool(config.get("delete_sources", False))
    while True:
        draw_results(stdscr, colors, dependency_ok, chdman, root, entries, cursor, scroll, delete_for_batch, folders_scanned)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            cursor = max(0, cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = min(len(entries) - 1, cursor + 1)
        elif key in (ord("d"), ord("D")):
            delete_for_batch = not delete_for_batch
        elif key in (ord("q"), ord("Q"), 27):
            return root, "Scan results dismissed. No files were changed."
        elif key in (10, 13):
            if not runnable:
                return root, "No eligible conversions. Nothing was changed."
            if delete_for_batch and not confirm_cleanup_arm(stdscr, colors, dependency_ok, chdman):
                return root, "Cleanup was not armed. No files were changed."
            config["delete_sources"] = delete_for_batch
            save_config(config)
            run_batch(stdscr, colors, dependency_ok, chdman or "chdman", root, runnable, all_jobs, delete_for_batch)
            return root, "Batch finished. Review the summary and log."


def run_app(stdscr) -> None:
    colors = init_colors()
    try:
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.timeout(-1)
    except curses.error:
        pass
    config = load_config()
    chdman = find_chdman()
    dependency_ok, dependency_message = probe_chdman(chdman)
    boot_animation(stdscr, colors, dependency_ok, chdman)
    selected = 0
    selected_folder: Optional[Path] = None
    notice = dependency_message if not dependency_ok else ""
    menu_size = len(main_menu_items(config))
    while True:
        if screen_too_small(stdscr):
            key = stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return
            continue
        draw_menu(stdscr, colors, dependency_ok, chdman, config, selected, selected_folder, notice)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % menu_size
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % menu_size
        elif key in (ord("q"), ord("Q"), 27):
            return
        elif key == ord(" ") and selected == 3:
            config["delete_sources"] = not bool(config.get("delete_sources", False))
            save_config(config)
            notice = "Source cleanup set to %s." % ("ON" if config["delete_sources"] else "OFF")
        elif key in (10, 13):
            if selected == 0:
                selected_folder, notice = start_conversion_flow(
                    stdscr, colors, dependency_ok, chdman, config, selected_folder
                )
            elif selected == 1:
                root = folder_picker(stdscr, colors, dependency_ok, chdman)
                if root is None:
                    notice = "Folder selection canceled."
                else:
                    try:
                        root = root.resolve(strict=True)
                        if not root.is_dir():
                            raise NotADirectoryError(str(root))
                        selected_folder = root
                        notice = "Folder selected. Press START to scan and convert."
                    except OSError as exc:
                        notice = "Selected folder is not accessible: " + str(exc)
            elif selected == 2:
                extension_menu(stdscr, colors, dependency_ok, chdman, config)
                notice = "Extension preferences saved."
            elif selected == 3:
                config["delete_sources"] = not bool(config.get("delete_sources", False))
                save_config(config)
                notice = "Source cleanup set to %s." % ("ON" if config["delete_sources"] else "OFF")
            elif selected == 4:
                iso_menu(stdscr, colors, dependency_ok, chdman, config)
                notice = "ISO handling preference saved."
            elif selected == 5:
                about_screen(stdscr, colors, dependency_ok, chdman)
            elif selected == 6:
                return


def launch_terminal_if_needed() -> bool:
    if sys.stdin.isatty() and sys.stdout.isatty():
        return True
    script = str(Path(__file__).resolve())
    python = sys.executable or "python3"
    candidates: List[List[str]] = []
    if shutil.which("x-terminal-emulator"):
        candidates.append(["x-terminal-emulator", "-e", python, script, "--in-terminal"])
    if shutil.which("xfce4-terminal"):
        candidates.append(["xfce4-terminal", "--disable-server", "--command", shlex.join([python, script, "--in-terminal"])])
    if shutil.which("gnome-terminal"):
        candidates.append(["gnome-terminal", "--wait", "--", python, script, "--in-terminal"])
    if shutil.which("konsole"):
        candidates.append(["konsole", "-e", python, script, "--in-terminal"])
    if shutil.which("kitty"):
        candidates.append(["kitty", "--", python, script, "--in-terminal"])
    if shutil.which("alacritty"):
        candidates.append(["alacritty", "-e", python, script, "--in-terminal"])
    if shutil.which("xterm"):
        candidates.append(["xterm", "-e", python, script, "--in-terminal"])
    for command in candidates:
        try:
            subprocess.Popen(command, start_new_session=True)
            return False
        except (OSError, subprocess.SubprocessError):
            continue
    print(APP_NAME + " needs an interactive terminal.")
    print("Open a terminal in this folder and run: python3 " + shlex.quote(script))
    try:
        input("Press Enter to close...")
    except (EOFError, KeyboardInterrupt):
        pass
    return False


def main() -> int:
    if not launch_terminal_if_needed():
        return 0
    if curses is None:
        print("This Python installation does not include curses. Install the system Python curses module.")
        input("Press Enter to close...")
        return 1
    try:
        curses.wrapper(run_app)
    except KeyboardInterrupt:
        return 130
    except curses.error as exc:
        print("Terminal UI error: " + str(exc))
        try:
            input("Press Enter to close...")
        except (EOFError, KeyboardInterrupt):
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())