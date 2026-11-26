import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chd_batch_converter as app


class FakeScreen:
    def __init__(self):
        self.height = 30
        self.width = 100
        self.timeout_value = -1

    def getmaxyx(self):
        return self.height, self.width

    def addnstr(self, y, x, text, width, attr=0):
        return None

    def erase(self):
        return None

    def refresh(self):
        return None

    def getch(self):
        return -1

    def timeout(self, value):
        self.timeout_value = value


class ParserTests(unittest.TestCase):
    def test_cue_windows_separators_and_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Tracks").mkdir()
            track = root / "Tracks" / "disc track.bin"
            track.write_bytes(b"track")
            cue = root / "game.cue"
            cue.write_text('FILE "Tracks\\disc track.bin" BINARY\n  TRACK 01 MODE1/2352\n', encoding="utf-8")
            refs, complete, notes = app.parse_cue(cue)
            self.assertTrue(complete, notes)
            self.assertEqual(refs, {track.resolve()})

    def test_gdi_quoted_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            track = root / "track one.bin"
            track.write_bytes(b"x")
            gdi = root / "game.gdi"
            gdi.write_text('1\n1 0 4 2352 "track one.bin" 0\n', encoding="utf-8")
            refs, complete, notes = app.parse_gdi(gdi)
            self.assertTrue(complete, notes)
            self.assertEqual(refs, {track.resolve()})

    def test_toc_datafile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            track = root / "data.bin"
            track.write_bytes(b"x")
            toc = root / "game.toc"
            toc.write_text('CD_DA\nDATAFILE "data.bin" 00:00:00\n', encoding="utf-8")
            refs, complete, notes = app.parse_toc(toc)
            self.assertTrue(complete, notes)
            self.assertEqual(refs, {track.resolve()})


class CleanupSafetyTests(unittest.TestCase):
    def _make_two_cues(self, root):
        shared = root / "shared.bin"
        shared.write_bytes(b"shared track")
        cue_a = root / "game-a.cue"
        cue_b = root / "game-b.cue"
        cue_a.write_text('FILE "shared.bin" BINARY\n TRACK 01 MODE1/2352\n', encoding="utf-8")
        cue_b.write_text('FILE "shared.bin" BINARY\n TRACK 01 MODE1/2352\n', encoding="utf-8")
        return shared, app.make_job(cue_a), app.make_job(cue_b)

    def test_shared_track_kept_when_one_conversion_fails_or_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared, first, second = self._make_two_cues(root)
            jobs = [first, second]
            signatures = app.collect_initial_signatures(jobs)
            deleted, preserved, details = app.delete_successful_sources(
                root, jobs, [app.JobResult(first, "SUCCESS")], signatures
            )
            self.assertTrue(shared.exists())
            self.assertTrue(second.descriptor.exists())
            self.assertFalse(first.descriptor.exists(), "successfully converted descriptor is eligible")
            self.assertEqual(deleted, 1)
            self.assertGreaterEqual(preserved, 1)
            self.assertTrue(any("shared with an image" in line for line in details))

    def test_shared_track_deleted_only_when_all_owners_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared, first, second = self._make_two_cues(root)
            jobs = [first, second]
            signatures = app.collect_initial_signatures(jobs)
            deleted, preserved, details = app.delete_successful_sources(
                root, jobs, [app.JobResult(first, "SUCCESS"), app.JobResult(second, "SUCCESS")], signatures
            )
            self.assertEqual(deleted, 3)
            self.assertEqual(preserved, 0)
            self.assertFalse(shared.exists())
            self.assertFalse(first.descriptor.exists())
            self.assertFalse(second.descriptor.exists())

    def test_m3u_backed_descriptor_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared, first, second = self._make_two_cues(root)
            (root / "playlist.m3u").write_text("game-a.cue\n", encoding="utf-8")
            jobs = [first, second]
            app.mark_playlist_dependencies(root, jobs)
            signatures = app.collect_initial_signatures(jobs)
            deleted, preserved, details = app.delete_successful_sources(
                root, jobs, [app.JobResult(first, "SUCCESS")], signatures
            )
            self.assertEqual(deleted, 0)
            self.assertTrue(first.descriptor.exists())
            self.assertTrue(shared.exists())
            self.assertGreaterEqual(preserved, 1)

    def test_changed_source_preserves_entire_disc_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared, descriptor, _other = self._make_two_cues(root)
            jobs = [descriptor]
            signatures = app.collect_initial_signatures(jobs)
            shared.write_bytes(b"changed while conversion was running")
            deleted, preserved, details = app.delete_successful_sources(
                root, jobs, [app.JobResult(descriptor, "SUCCESS")], signatures
            )
            self.assertEqual(deleted, 0)
            self.assertGreaterEqual(preserved, 2)
            self.assertTrue(shared.exists())
            self.assertTrue(descriptor.descriptor.exists())
            self.assertTrue(any("source set changed" in line for line in details))


class ConversionFlowTests(unittest.TestCase):
    def _fake_chdman(self, directory):
        fake = directory / "fake_chdman.py"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, sys\n"
            "args=sys.argv[1:]\n"
            "if args and args[0]=='--help':\n print('chdman createcd createdvd verify'); raise SystemExit(0)\n"
            "if args[0] in ('createcd','createdvd'):\n"
            " out=pathlib.Path(args[args.index('-o')+1]); out.write_bytes(b'fake chd data')\n"
            " print('Compressing, 37.5% complete...'); print('Compressing, 100.0% complete...'); raise SystemExit(0)\n"
            "if args[0]=='verify':\n"
            " print('Verification started')\n"
            " raise SystemExit(1 if os.environ.get('FAKE_CHDMAN_VERIFY_FAIL')=='1' else 0)\n"
            "raise SystemExit(2)\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        return str(fake)

    def test_fake_backend_creates_and_verifies_before_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            iso = root / "disc.iso"
            iso.write_bytes(b"0" * 2048)
            job = app.make_job(iso)
            screen = FakeScreen()
            state = {"index": 1, "total": 1, "completed": 0, "title": str(iso), "title_pct": None, "phase": "Starting", "log": []}
            fake = self._fake_chdman(root)
            colors = {"cyan": 0, "green": 0, "yellow": 0, "red": 0}
            success, canceled, message = app.run_chdman_tui(screen, colors, True, fake, job, state)
            self.assertTrue(success, message)
            self.assertFalse(canceled)
            self.assertTrue((root / "disc.chd").is_file())
            self.assertEqual(state["title_pct"], 100.0)
            self.assertTrue(iso.exists(), "conversion must not delete sources itself")

    def test_failed_verification_never_publishes_final_chd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            iso = root / "disc.iso"
            iso.write_bytes(b"0" * 2048)
            job = app.make_job(iso)
            screen = FakeScreen()
            state = {"index": 1, "total": 1, "completed": 0, "title": str(iso), "title_pct": None, "phase": "Starting", "log": []}
            fake = self._fake_chdman(root)
            previous = os.environ.get("FAKE_CHDMAN_VERIFY_FAIL")
            os.environ["FAKE_CHDMAN_VERIFY_FAIL"] = "1"
            try:
                colors = {"cyan": 0, "green": 0, "yellow": 0, "red": 0}
                success, canceled, message = app.run_chdman_tui(screen, colors, True, fake, job, state)
            finally:
                if previous is None:
                    os.environ.pop("FAKE_CHDMAN_VERIFY_FAIL", None)
                else:
                    os.environ["FAKE_CHDMAN_VERIFY_FAIL"] = previous
            self.assertFalse(success)
            self.assertFalse(canceled)
            self.assertIn("verification failed", message.lower())
            self.assertFalse((root / "disc.chd").exists())
            self.assertTrue(iso.exists())
            self.assertFalse(list(root.glob("*.partial.chd")))



class MainMenuTests(unittest.TestCase):
    def test_start_is_first_menu_item_and_folder_selection_is_separate(self):
        items = app.main_menu_items(app.default_config())
        self.assertTrue(items[0].startswith("START"))
        self.assertEqual(items[1], "Select folder")
        self.assertIn("File extensions", items[2])
        self.assertIn("Delete source files", items[3])
        self.assertEqual(items[-1], "Quit")

    def test_start_reuses_an_already_selected_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screen = FakeScreen()
            with mock.patch.object(app, "folder_picker", side_effect=AssertionError("START should reuse the selected folder")), \
                 mock.patch.object(app, "scan_for_jobs", return_value=([], 1)):
                selected, notice = app.start_conversion_flow(
                    screen, {}, True, "chdman", app.default_config(), root
                )
            self.assertEqual(selected, root)
            self.assertIn("No descriptors matched", notice)


if __name__ == "__main__":
    unittest.main(verbosity=2)
