import unittest
from types import SimpleNamespace

from app_window import AppWindow, DASH_H, MIN_H, MIN_W, WINDOW_W


class _FakeRoot:
    def __init__(self, w=500, h=700, state="normal",
                 screen_w=1920, screen_h=1080):
        self._w, self._h = w, h
        self._state = state
        self._screen_w, self._screen_h = screen_w, screen_h
        self.jobs = []
        self.cancelled = set()
        self.geometry_calls = []

    def winfo_width(self):
        return self._w

    def winfo_height(self):
        return self._h

    def winfo_screenwidth(self):
        return self._screen_w

    def winfo_screenheight(self):
        return self._screen_h

    def state(self):
        return self._state

    def geometry(self, spec):
        self.geometry_calls.append(spec)

    def after(self, delay, callback, *args):
        job = len(self.jobs) + 1
        self.jobs.append((job, delay, callback, args))
        return job

    def after_cancel(self, job):
        self.cancelled.add(job)

    def run_jobs(self):
        while self.jobs:
            job, _delay, callback, args = self.jobs.pop(0)
            if job not in self.cancelled:
                callback(*args)


class _FakeConfig(SimpleNamespace):
    def __init__(self, **kw):
        super().__init__(window_sizes={}, **kw)
        self.saves = 0

    def save_async(self):
        self.saves += 1


class _FakeDb:
    def __init__(self):
        self.pushed = []

    def set_app_setting(self, key, value):
        self.pushed.append((key, value))

    def fetch_app_setting(self, _key):
        return ""


def _window(email="user@example.com", config=None, root=None, db=None):
    window = object.__new__(AppWindow)
    window._auth = SimpleNamespace(user_email=email)
    window._config = config if config is not None else _FakeConfig()
    window._root = root if root is not None else _FakeRoot()
    window._db = db
    window._applied_size = None
    window._dash_visible = True
    window._win_save_job = None
    window._install_default_checked = False
    return window


class ParseSizeTests(unittest.TestCase):
    def test_valid_and_invalid_inputs(self):
        self.assertEqual((420, 640), AppWindow._parse_size("420x640"))
        self.assertEqual((500, 900), AppWindow._parse_size("500X900"))
        self.assertIsNone(AppWindow._parse_size(""))
        self.assertIsNone(AppWindow._parse_size(None))
        self.assertIsNone(AppWindow._parse_size("wide"))
        self.assertIsNone(AppWindow._parse_size("420x"))
        self.assertIsNone(AppWindow._parse_size("420x640x2"))

    def test_out_of_range_sizes_are_rejected(self):
        self.assertIsNone(AppWindow._parse_size("10x10"))
        self.assertIsNone(AppWindow._parse_size("9000x9000"))
        self.assertIsNone(AppWindow._parse_size(f"{MIN_W - 1}x{MIN_H}"))


class SavedDashSizeTests(unittest.TestCase):
    def test_account_size_beats_install_default_beats_builtin(self):
        config = _FakeConfig()
        window = _window(config=config)

        self.assertEqual((WINDOW_W, DASH_H), window._saved_dash_size())

        config.window_sizes = {"_default": "460x700"}
        self.assertEqual((460, 700), window._saved_dash_size())

        config.window_sizes["user@example.com"] = "520x800"
        self.assertEqual((520, 800), window._saved_dash_size())

    def test_saved_size_is_clamped_to_screen(self):
        config = _FakeConfig()
        config.window_sizes = {"user@example.com": "3000x2000"}
        window = _window(config=config,
                         root=_FakeRoot(screen_w=1280, screen_h=720))
        self.assertEqual((1280, 720 - 40), window._saved_dash_size())

    def test_signed_out_uses_default_bucket(self):
        config = _FakeConfig()
        config.window_sizes = {"_default": "460x700"}
        window = _window(email="", config=config)
        self.assertEqual("_default", window._account_size_key())
        self.assertEqual((460, 700), window._saved_dash_size())


class PersistWindowSizeTests(unittest.TestCase):
    def test_persists_current_size_for_the_account(self):
        config = _FakeConfig()
        window = _window(config=config, root=_FakeRoot(w=510, h=730))

        window._persist_window_size()

        self.assertEqual("510x730", config.window_sizes["user@example.com"])
        self.assertEqual(1, config.saves)
        self.assertEqual((510, 730), window._applied_size)

    def test_maximised_state_is_never_persisted(self):
        config = _FakeConfig()
        window = _window(config=config,
                         root=_FakeRoot(w=1920, h=1040, state="zoomed"))

        window._persist_window_size()

        self.assertEqual({}, config.window_sizes)
        self.assertEqual(0, config.saves)

    def test_unchanged_size_does_not_rewrite(self):
        config = _FakeConfig()
        config.window_sizes = {"user@example.com": "510x730"}
        window = _window(config=config, root=_FakeRoot(w=510, h=730))

        window._persist_window_size()

        self.assertEqual(0, config.saves)

    def test_super_admin_resize_pushes_the_install_default(self):
        config = _FakeConfig()
        db = _FakeDb()
        window = _window(email="Ryan.Murphy@ftc-ss.com", config=config,
                         root=_FakeRoot(w=444, h=666), db=db)

        window._persist_window_size()

        self.assertEqual("444x666", config.window_sizes["ryan.murphy@ftc-ss.com"])
        self.assertEqual([("default_window_size", "444x666")], db.pushed)

    def test_normal_account_never_pushes_the_install_default(self):
        db = _FakeDb()
        window = _window(config=_FakeConfig(),
                         root=_FakeRoot(w=444, h=666), db=db)

        window._persist_window_size()

        self.assertEqual([], db.pushed)


class RootConfigureTests(unittest.TestCase):
    def test_programmatic_resize_echo_is_ignored(self):
        root = _FakeRoot()
        window = _window(root=root)
        window._applied_size = (500, 700)

        window._on_root_configure(
            SimpleNamespace(widget=root, width=500, height=700))

        # The echo must never arm the size-SAVE debounce. A repaint-heal job
        # is allowed: _on_root_configure deliberately schedules a debounced
        # _repaint_all on every real size change (login→dashboard jump ghost).
        self.assertIsNone(window._win_save_job)
        self.assertNotIn(window._persist_window_size,
                         [job[2] for job in root.jobs])

    def test_child_configure_events_are_ignored(self):
        root = _FakeRoot()
        window = _window(root=root)

        window._on_root_configure(
            SimpleNamespace(widget=object(), width=100, height=100))

        self.assertIsNone(window._win_save_job)

    def test_user_resize_debounces_to_one_save_job(self):
        root = _FakeRoot()
        window = _window(root=root)
        window._applied_size = (420, 640)

        window._on_root_configure(
            SimpleNamespace(widget=root, width=430, height=640))
        first = window._win_save_job
        window._on_root_configure(
            SimpleNamespace(widget=root, width=440, height=640))

        self.assertIn(first, root.cancelled)
        self.assertIsNotNone(window._win_save_job)

    def test_login_screen_resizes_are_not_persisted(self):
        root = _FakeRoot()
        window = _window(root=root)
        window._dash_visible = False

        window._on_root_configure(
            SimpleNamespace(widget=root, width=430, height=640))

        self.assertIsNone(window._win_save_job)


class InstallDefaultTests(unittest.TestCase):
    def test_adopt_stores_default_only_when_no_size_exists(self):
        config = _FakeConfig()
        root = _FakeRoot()
        window = _window(config=config, root=root)
        window._applied_size = (WINDOW_W, DASH_H)

        window._adopt_install_default((480, 720))

        self.assertEqual({"_default": "480x720"}, config.window_sizes)
        # The freshly-adopted default is applied to the live window.
        self.assertIn("480x720", root.geometry_calls[-1])

    def test_adopt_never_overwrites_an_existing_size(self):
        config = _FakeConfig()
        config.window_sizes = {"user@example.com": "510x730"}
        window = _window(config=config)

        window._adopt_install_default((480, 720))

        self.assertEqual({"user@example.com": "510x730"}, config.window_sizes)

    def test_fetch_is_skipped_once_any_size_exists(self):
        config = _FakeConfig()
        config.window_sizes = {"_default": "480x720"}
        db = _FakeDb()
        window = _window(config=config, db=db)

        window._maybe_fetch_install_default()

        self.assertTrue(window._install_default_checked)


class ResizeDeferralTests(unittest.TestCase):
    """Resizing the window while WM_SETREDRAW is frozen (inside _atomic_ui)
    leaves the just-packed frame UNMAPPED — the previous frame's stale pixels
    plus a white strip where the window grew (the sign-in 'white box' and the
    login↔dashboard size-jump ghost). So _resize must defer geometry() while
    `_in_atomic`, and _atomic_ui applies it once redraw is back on."""

    def test_resize_applies_immediately_outside_atomic(self):
        root = _FakeRoot(screen_w=1920, screen_h=1080)
        window = _window(root=root)
        window._resize(440, 660)
        self.assertEqual((440, 660), window._applied_size)
        self.assertIn("440x660", root.geometry_calls[-1])

    def test_resize_is_deferred_while_in_atomic(self):
        root = _FakeRoot(screen_w=1920, screen_h=1080)
        window = _window(root=root)
        window._in_atomic = True
        window._resize(440, 660)
        # Size is recorded now (so the <Configure> echo guard still matches)…
        self.assertEqual((440, 660), window._applied_size)
        # …but the actual geometry() call is held back until the freeze lifts.
        self.assertEqual([], root.geometry_calls)
        self.assertIn("440x660", window._pending_geometry)


class CompactLayoutMigrationTests(unittest.TestCase):
    """Sizes saved against the old, ~140px taller dashboard are clamped to
    DASH_H exactly once; a later drag is the user's choice and survives."""

    def test_tall_saved_heights_are_clamped_once(self):
        config = _FakeConfig(window_layout_rev=0)
        config.window_sizes = {"user@example.com": "433x705",
                               "_default": "470x723",
                               "small@example.com": "420x530"}
        window = _window(config=config)
        window._migrate_window_sizes()
        self.assertEqual(f"433x{DASH_H}", config.window_sizes["user@example.com"])
        self.assertEqual(f"470x{DASH_H}", config.window_sizes["_default"])
        self.assertEqual("420x530", config.window_sizes["small@example.com"])
        self.assertGreaterEqual(config.window_layout_rev, 1)
        self.assertEqual(1, config.saves)

        # Dragged taller after the migration: that is kept.
        config.window_sizes["user@example.com"] = "433x760"
        window._migrate_window_sizes()
        self.assertEqual("433x760", config.window_sizes["user@example.com"])
        self.assertEqual(1, config.saves)

    def test_super_admin_pushes_the_clamped_default(self):
        from app_window import SUPER_ADMIN_EMAIL
        config = _FakeConfig(window_layout_rev=0)
        config.window_sizes = {SUPER_ADMIN_EMAIL: "433x705"}
        db = _FakeDb()
        window = _window(email=SUPER_ADMIN_EMAIL, config=config, db=db)
        window._migrate_window_sizes()
        self.assertEqual([("default_window_size", f"433x{DASH_H}")], db.pushed)

    def test_other_accounts_push_nothing(self):
        config = _FakeConfig(window_layout_rev=0)
        config.window_sizes = {"user@example.com": "433x705"}
        db = _FakeDb()
        _window(config=config, db=db)._migrate_window_sizes()
        self.assertEqual([], db.pushed)


class HomeFitsDefaultHeightTests(unittest.TestCase):
    """Live Tk: at WINDOW_W x DASH_H every Home card is on screen with no
    scrolling (Home has no ScrollPane), with a little room under the cards."""

    def test_home_fits_the_default_height(self):
        import tkinter as tk
        import types
        import app_window as aw
        try:
            root = tk.Tk()
        except Exception as e:                       # no window station (CI)
            raise unittest.SkipTest(f"Tk unavailable: {e}")
        self.addCleanup(root.destroy)
        # Mapped (off screen), not withdrawn: the rounded cards size their
        # canvases from the realised width, which a withdrawn root never has.
        root.geometry("+-3000+-3000")
        w = AppWindow.__new__(AppWindow)
        w._root = root
        w._config = types.SimpleNamespace(impact_range="all", mode="toggle",
                                          save_async=lambda: None)
        w._stats = None
        w._hotkey, w._refine_hotkey, w._ptt_hotkey = "ALT+V", "ALT+R", "ALT+C"
        w._switch_dash_tab = lambda *_a: None
        w._build_header()
        w._header_outer.pack(fill="x")
        # The dashboard chrome between the header and the tab content,
        # measured off the real widgets rather than assumed.
        dash = tk.Frame(root, bg=aw.C["bg"])
        dash.pack(fill="x")
        w._search_catalogue, w._page_search = [], {}
        w._build_universal_search(dash)
        tk.Frame(dash, height=1).pack(fill="x", pady=(10, 0))
        import bookmark_tabs
        bookmark_tabs.BookmarkTabs(dash, AppWindow._DASH_TABS,
                                   on_select=lambda *_a: None,
                                   bg=aw.C["bg"], line=aw.C["border"]).pack(
            fill="x", pady=(8, 0))
        home = tk.Frame(root, bg=aw.C["bg"])
        home.pack(fill="x", pady=(8, 0))
        w._build_home_tab(home)
        footer = tk.Frame(root, padx=24, pady=6)
        tk.Label(footer, text="x", font=("Segoe UI", 9)).pack()
        footer.pack(fill="x")
        root.geometry(f"{WINDOW_W}x{DASH_H}")
        root.update()
        root.update()
        need = (w._header_outer.winfo_reqheight() + dash.winfo_reqheight()
                + 8 + home.winfo_reqheight() + footer.winfo_reqheight() + 1)
        self.assertLessEqual(need + 8, DASH_H,
                             f"Home needs {need}px; DASH_H={DASH_H} clips it")


if __name__ == "__main__":
    unittest.main()
