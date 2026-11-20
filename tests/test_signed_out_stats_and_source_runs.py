"""Signed-out dictations, source runs and the Sign In window (20 Nov 2026).

After a restart Windows started a chat's preview copy of Echo (a source run)
instead of the installed app, because every launch, source runs included,
pointed Start with Windows and the logon task at itself. That copy had no
server settings, so it showed the person signed out (their time saved and
streak looked reset), refused their BrightLink password, and its Sign In
dialog sat over the dashboard with the dashboard's title bar showing above.
"""
import inspect
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stats
from stats import StatsStore

UID = "e5aa513d-e52f-48a3-a4c6-0409bc0c49e7"


def _store(users):
    s = StatsStore()
    s._data = {"version": 1, "users": users}
    return s


class SignedOutDaysJoinTheAccount(unittest.TestCase):
    def setUp(self):
        # Never the real stats.json (tests must not touch real data).
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(stats, "_stats_path",
                              lambda: os.path.join(self.tmp, "stats.json"))
        p.start()
        self.addCleanup(p.stop)
        s = mock.patch.object(StatsStore, "_start_sync", lambda self, uid: None)
        s.start()
        self.addCleanup(s.stop)

    def test_signed_out_words_add_to_the_same_day(self):
        s = _store({
            "local": {"days": {"2026-11-20": {"w": 2296, "s": 956.0, "v": 669.49, "vw": 2296}},
                      "seeded": False, "carry_saved_min": 0.0, "carry_words": 0},
            UID: {"days": {"2026-11-20": {"w": 1000, "s": 400.0, "v": 300.0, "vw": 1000,
                                          "r": 2, "rs": 10.0, "rp": 16, "rv": 0},
                           "2026-11-19": {"w": 50, "s": 20.0}},
                  "seeded": True, "carry_saved_min": 5.0, "carry_words": 100},
        })
        s.set_user(UID)
        day = s._data["users"][UID]["days"]["2026-11-20"]
        self.assertEqual(day["w"], 3296)
        self.assertAlmostEqual(day["s"], 1356.0)
        self.assertAlmostEqual(day["v"], 969.49)
        self.assertEqual(day["vw"], 3296)
        self.assertEqual(day["r"], 2)  # refine fields kept, not lost
        self.assertEqual(s._data["users"][UID]["days"]["2026-11-19"]["w"], 50)
        self.assertEqual(s._data["users"]["local"]["days"], {})

    def test_a_day_only_used_signed_out_keeps_the_streak(self):
        s = _store({
            "local": {"days": {"2026-11-08": {"w": 10, "s": 5.0}}},
            UID: {"days": {"2026-11-07": {"w": 1, "s": 1.0}}, "seeded": True},
        })
        s.set_user(UID)
        self.assertIn("2026-11-08", s._data["users"][UID]["days"])

    def test_signing_in_twice_never_counts_twice(self):
        s = _store({
            "local": {"days": {"2026-11-20": {"w": 10, "s": 5.0}}},
            UID: {"days": {}, "seeded": True},
        })
        s.set_user(UID)
        s.set_user(None)
        s.set_user(UID)
        self.assertEqual(s._data["users"][UID]["days"]["2026-11-20"]["w"], 10)

    def test_merge_is_saved_to_disk(self):
        s = _store({
            "local": {"days": {"2026-11-20": {"w": 10, "s": 5.0}}},
            UID: {"days": {}, "seeded": True},
        })
        s.set_user(UID)
        fresh = StatsStore()
        fresh._load_locked()
        self.assertEqual(fresh._data["users"][UID]["days"]["2026-11-20"]["w"], 10)
        self.assertEqual(fresh._data["users"]["local"]["days"], {})

    def test_nothing_signed_out_changes_nothing(self):
        s = _store({UID: {"days": {"2026-11-20": {"w": 7, "s": 3.0}}, "seeded": True}})
        with mock.patch.object(s, "_save_locked") as save:
            s.set_user(UID)
        save.assert_not_called()
        self.assertEqual(s._data["users"][UID]["days"]["2026-11-20"]["w"], 7)


class SourceRunsNeverTakeOverWindows(unittest.TestCase):
    def setUp(self):
        import app as app_mod
        self.app = app_mod

    def test_source_run_leaves_start_with_windows_alone(self):
        fake_winreg = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"winreg": fake_winreg}), \
             mock.patch.object(self.app.sys, "frozen", False, create=True), \
             mock.patch.object(self.app, "_ensure_logon_task") as ensure, \
             mock.patch.object(self.app, "_remove_logon_task") as remove:
            self.app._sync_startup(True)
            self.app._sync_startup(False)
        fake_winreg.SetValueEx.assert_not_called()
        fake_winreg.CreateKey.assert_not_called()
        ensure.assert_not_called()
        remove.assert_not_called()

    def test_source_run_leaves_the_url_links_alone(self):
        fake_winreg = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"winreg": fake_winreg}), \
             mock.patch.object(self.app.sys, "frozen", False, create=True):
            self.app._register_url_protocol()
        fake_winreg.SetValueEx.assert_not_called()


class SignInIsOneWindow(unittest.TestCase):
    def test_sign_in_hides_the_dashboard_instead_of_stacking_a_dialog(self):
        import app_window
        src = inspect.getsource(app_window.AppWindow._do_sign_in)
        self.assertIn("_show_login_screen", src)
        self.assertNotIn("run(parent=self._root)", src)


if __name__ == "__main__":
    unittest.main()
