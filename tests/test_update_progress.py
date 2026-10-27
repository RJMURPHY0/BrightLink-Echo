"""The Updates card's bar shows only measured numbers.

Pinned here:
  * the download reports real bytes against the release size, and the bar's
    "seconds left" appears only once the speed has been measured;
  * the run in flight owns one shared state, so an Update Now that joins it
    sees the same progress, and every way a run ends clears the bar;
  * staging progress is capped below 100% (it compares against the running
    version's size, an estimate) until the installer returns;
  * the sign-in step bar never passes a step's end before that step finishes.
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import progress_bar  # noqa: E402
import updater  # noqa: E402

from test_update_integrity import _fake_exe, _sha  # noqa: E402


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class ProgressStateTests(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        p = mock.patch.object(updater.time, "monotonic", self.clock)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(updater._set_progress, "")

    def test_fraction_is_bytes_over_the_release_size(self):
        updater._set_progress("download", "v9.9.9", 1_000_000)
        updater._progress_bytes(250_000)
        p = updater.update_progress()
        self.assertEqual(p["phase"], "download")
        self.assertEqual(p["version"], "9.9.9")
        self.assertAlmostEqual(p["fraction"], 0.25)

    def test_no_seconds_left_until_the_speed_is_measured(self):
        updater._set_progress("download", "9.9.9", 10_000_000)
        updater._progress_bytes(10_000)
        self.assertIsNone(updater.update_progress()["seconds_left"])
        self.clock.t += 0.5
        updater._progress_bytes(500_000)          # under a second in
        self.assertIsNone(updater.update_progress()["seconds_left"])
        self.clock.t += 1.5
        updater._progress_bytes(2_000_000)        # 2 MB at ~1 MB/s
        left = updater.update_progress()["seconds_left"]
        self.assertIsNotNone(left)
        self.assertAlmostEqual(left, 8_000_000 / ((2_000_000 - 10_000) / 2.0), places=3)

    def test_a_stalled_download_drops_its_time_left(self):
        updater._set_progress("download", "9.9.9", 10_000_000)
        updater._progress_bytes(0)
        self.clock.t += 1.5
        updater._progress_bytes(3_000_000)
        self.assertIsNotNone(updater.update_progress()["seconds_left"])
        self.clock.t += 1.0                       # no bytes for a second: slower
        slower = updater.update_progress()["seconds_left"]
        self.assertGreater(slower, 7_000_000 / (3_000_000 / 1.5))
        self.clock.t += 55                        # stalled for a minute
        self.assertIsNone(updater.update_progress()["seconds_left"])

    def test_unknown_size_shows_no_fraction(self):
        updater._set_progress("download", "9.9.9", 0)
        updater._progress_bytes(123)
        p = updater.update_progress()
        self.assertIsNone(p["fraction"])
        self.assertIsNone(p["seconds_left"])

    def test_a_new_phase_starts_from_zero(self):
        updater._set_progress("download", "9.9.9", 100)
        updater._progress_bytes(100)
        updater._set_progress("verify")
        p = updater.update_progress()
        self.assertEqual((p["phase"], p["done"], p["version"]), ("verify", 0, "9.9.9"))


class RunProgressTests(unittest.TestCase):
    """Against the real run_auto_update, as test_update_integrity drives it."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.data = _fake_exe()
        self.seen = []
        for p in (mock.patch.object(updater, "_app_data_dir", lambda: self.dir),
                  mock.patch.object(updater, "_cached_release", {
                      "version": "v9.9.9", "download_url": "https://x/FTC-Whisper.exe",
                      "size": len(self.data), "sha256": _sha(self.data)})):
            p.start()
            self.addCleanup(p.stop)
        updater._run_active = False
        updater._apply_now.clear()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _download(self, gate=None, fail=False):
        def fake(url, dest, progress_cb, expected_bytes=0):
            step = len(self.data) // 4
            with open(dest, "wb") as f:
                for i in range(4):
                    chunk = self.data[i * step:(i + 1) * step if i < 3 else None]
                    f.write(chunk)
                    progress_cb(f.tell(), 0)    # proxy stripped Content-Length
                    self.seen.append(updater.update_progress())
                    if gate is not None and i == 1:
                        gate.wait(5)
            if fail:
                raise IOError("network went away")
        return fake

    def _apply(self, new_exe, current_exe, sha256=None):
        self.seen.append(updater.update_progress())

    def _run(self, **kw):
        args = dict(version="v9.9.9", url="https://x/FTC-Whisper.exe",
                    current_exe=os.path.join(self.dir, "cur.exe"),
                    is_idle=lambda: True, apply_fn=self._apply,
                    poll_interval=0.0, idle_samples=1)
        args.update(kw)
        return updater.run_auto_update(**args)

    def test_download_reports_real_bytes_then_installs(self):
        with mock.patch.object(updater, "download_update", self._download()):
            self._run()
        fracs = [p["fraction"] for p in self.seen[:4]]
        self.assertEqual([p["phase"] for p in self.seen[:4]], ["download"] * 4)
        self.assertEqual(fracs, sorted(fracs))
        self.assertAlmostEqual(fracs[-1], 1.0)
        self.assertEqual(self.seen[-1]["phase"], "install")
        self.assertEqual(updater.update_progress()["phase"], "")

    def test_a_joined_update_now_sees_the_same_progress(self):
        gate = threading.Event()
        with mock.patch.object(updater, "download_update", self._download(gate=gate)):
            t = threading.Thread(target=self._run)
            t.start()
            for _ in range(200):
                if updater.update_progress()["done"]:
                    break
                time.sleep(0.01)
            self.assertTrue(self._run(apply_now=True))     # the click joins
            mid = updater.update_progress()
            gate.set()
            t.join(5)
        self.assertEqual(mid["phase"], "download")
        self.assertTrue(mid["running"])
        self.assertAlmostEqual(mid["fraction"], 0.5, places=2)

    def test_a_failed_download_clears_the_bar(self):
        with mock.patch.object(updater, "download_update", self._download(fail=True)), \
                mock.patch.object(updater.time, "sleep", lambda _s: None):
            self.assertFalse(self._run())
        p = updater.update_progress()
        self.assertEqual(p["phase"], "")
        self.assertFalse(p["running"])


class StagingProgressTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(updater._set_progress, "")

    def test_staging_is_capped_below_done_until_the_installer_returns(self):
        with open(os.path.join(self.dir, "big.bin"), "wb") as f:
            f.write(b"x" * 5000)                  # more than the estimate
        updater._set_progress("prepare", "9.9.9", 1000)
        stop = threading.Event()
        with mock.patch.object(updater, "_STAGE_POLL_SECS", 0.01):
            t = threading.Thread(target=updater._watch_staging,
                                 args=(self.dir, 1000, stop))
            t.start()
            time.sleep(0.1)
            stop.set()
            t.join(2)
        self.assertAlmostEqual(updater.update_progress()["fraction"], 0.99)

    def test_layout_size_comes_from_the_manifest(self):
        m = {"exe": {"size": 10}, "files": [{"size": 5}, {"size": 7}]}
        self.assertEqual(updater._layout_bytes(m), 22)
        self.assertEqual(updater._layout_bytes({}), 0)


class DescribeTests(unittest.TestCase):
    def test_download_line(self):
        frac, text = progress_bar.describe_update({
            "phase": "download", "fraction": 0.42, "done": 18_200_000,
            "total": 43_000_000, "seconds_left": 11.2})
        self.assertEqual(frac, 0.42)
        self.assertEqual(text, "Downloading 42% · 18 of 43 MB · about 15 seconds left")

    def test_download_without_a_measured_speed_gives_no_time(self):
        _, text = progress_bar.describe_update({
            "phase": "download", "fraction": 0.01, "done": 400_000,
            "total": 43_000_000, "seconds_left": None})
        self.assertEqual(text, "Downloading 1% · 0 of 43 MB")

    def test_minutes_and_singular(self):
        self.assertEqual(progress_bar._time_left(90), "about 2 minutes left")
        self.assertEqual(progress_bar._time_left(0.4), "about 1 second left")

    def test_prepare_without_a_size_shows_elapsed_time(self):
        _, text = progress_bar.describe_update(
            {"phase": "prepare", "fraction": None, "started": 100.0}, now=112.4)
        self.assertEqual(text, "Preparing… 12 s")

    def test_ready_and_idle_show_no_bar(self):
        self.assertIsNone(progress_bar.describe_update({"phase": "ready"}))
        self.assertIsNone(progress_bar.describe_update({"phase": ""}))


class _FakeBar:
    def __init__(self):
        self.values = []

    def set(self, v):
        self.values.append(v)

    def after(self, _ms, _fn):
        return "job"

    def after_cancel(self, _job):
        pass


class StepProgressTests(unittest.TestCase):
    def test_never_passes_the_step_before_it_finishes(self):
        bar = _FakeBar()
        s = progress_bar.StepProgress(bar, 2)
        s.start()
        for _ in range(500):
            s._tick()
        self.assertLess(max(bar.values), 0.5)     # still inside step one
        s.advance()
        for _ in range(500):
            s._tick()
        self.assertLess(max(bar.values), 1.0)
        s.finish()
        self.assertEqual(bar.values[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
