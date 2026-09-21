"""The BrightLink | Echo artwork: header lockup, popup badge, window icon.

The lockup is composed at runtime from the CRM's wordmark and the Echo
wordmark, so the things that can quietly go wrong are pinned: the two words
standing on different baselines, the lockup growing wider than the narrowest
window leaves room for, the icons drifting from the chain mark, and a build
that ships without the artwork (every surface would fall back to plain text).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import brand  # noqa: E402
import logo_cache  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    with open(os.path.join(HERE, name), encoding="utf-8-sig") as f:
        return f.read()


class ArtworkTests(unittest.TestCase):
    def test_every_asset_is_present_and_transparent(self):
        for name in (logo_cache.MARK, logo_cache.WORDMARK, logo_cache.ECHO,
                     logo_cache.BADGE):
            img = logo_cache._asset(name)
            self.assertIsNotNone(img, name)
            self.assertEqual(img.getpixel((0, 0))[3], 0, f"{name} has a background")

    def test_both_words_stand_on_one_baseline(self):
        img = logo_cache.lockup_image(46)
        a = np.asarray(img)[..., 3] > 128
        s1 = 46 / 250
        # "B" of BrightLink, and the "E" of Echo (the last ~quarter of the image).
        b_x0, b_x1 = int(367 * s1) + 1, int(453 * s1) - 1
        b_bottom = np.where(a[:, b_x0:b_x1].any(1))[0].max()
        e_cols = np.where(a.any(0))[0]
        e_x0 = e_cols.max() - int(0.24 * (e_cols.max() - e_cols.min()))
        # The E is the first glyph after the divider gap: find it from the right.
        echo_start = None
        for x in range(e_x0, 0, -1):
            if not a[:, x].any():
                echo_start = x + 1
                break
        e_bottom = np.where(a[:, echo_start:echo_start + 6].any(1))[0].max()
        self.assertLessEqual(abs(int(b_bottom) - int(e_bottom)), 1)

    def test_the_lockup_clears_the_gear_at_the_narrowest_window(self):
        # Centred on the window, so the gear (~46px wide plus its 4px inset)
        # costs both sides. 10px more to its hit area, ~22px to the glyph
        # itself, keeps Echo from reading as part of the gear. At 46px the
        # lockup cleared by 1px and did exactly that.
        import app_window
        img = logo_cache.lockup_image(42)
        self.assertLessEqual(img.width, app_window.MIN_W - 2 * (50 + 10))

    def test_badge_is_the_requested_height(self):
        self.assertEqual(logo_cache.badge_image(28).height, 28)

    def test_missing_artwork_degrades_to_none(self):
        saved = dict(logo_cache._images)
        try:
            logo_cache._images[logo_cache.WORDMARK] = None
            self.assertIsNone(logo_cache.lockup_image(46))
            self.assertIsNone(logo_cache.get_lockup_photo(None, "#0d0d0d"))
        finally:
            logo_cache._images.clear()
            logo_cache._images.update(saved)


class IconTests(unittest.TestCase):
    def test_shipped_icons_are_the_chain_mark(self):
        expected = {f.size: np.asarray(f) for f in logo_cache.icon_frames()}
        for name in ("logo.ico", "exe_icon.ico"):
            ico = Image.open(os.path.join(HERE, name))
            sizes = ico.info["sizes"]
            for s in (16, 32, 48, 256):
                self.assertIn((s, s), sizes, name)
            ico.size = (32, 32)
            got = np.asarray(ico.convert("RGBA"), dtype=int)
            diff = np.abs(got - expected[(32, 32)].astype(int)).max()
            self.assertLessEqual(diff, 2, f"{name} is not built from the chain mark; "
                                          "regenerate with logo_cache.write_icon")

    def test_echo_is_in_the_icon_where_it_can_be_read(self):
        # Orange text sits in the lower part of the tile from TEXT_MIN_PX up;
        # below that the frame is the chain alone.
        def orange_rows(size):
            a = np.asarray(logo_cache.app_icon_image(size).convert("RGB"), dtype=int)
            r, g, b = a[..., 0], a[..., 1], a[..., 2]
            lower = (r > 180) & (b < 90) & (r - g > 60)
            return lower[int(size * 0.62):].sum()
        self.assertGreater(orange_rows(32), 8)
        self.assertGreater(orange_rows(48), 20)
        self.assertLess(orange_rows(16), orange_rows(32))

    def test_own_app_history_icon_is_the_app_icon(self):
        got = np.asarray(Image.open(os.path.join(
            HERE, "assets", "brand_icons", "ftcwhisper.png")).convert("RGBA"), dtype=int)
        want = np.asarray(logo_cache.app_icon_image(256), dtype=int)
        self.assertLessEqual(np.abs(got - want).max(), 2)

    def test_installer_builds_the_same_icon(self):
        self.assertIn("logo_cache.write_icon(LOGO_ICO)", _src("installer.py"))


class WiringTests(unittest.TestCase):
    def test_every_surface_uses_the_new_artwork(self):
        aw = _src("app_window.py")
        self.assertEqual(aw.count("get_lockup_photo(self._root, C[\"bg\"], height=42)"), 2)
        self.assertIn("get_lockup_photo(self._root, C[\"bg\"], height=42)",
                      _src("login_window.py"))
        self.assertIn("get_badge_photo(self.root, CP[\"bg\"], height=28)",
                      _src("popup.py"))

    def test_the_gear_does_not_push_the_lockup_off_centre(self):
        aw = _src("app_window.py")
        self.assertIn('self._gear_btn.place(relx=1.0, rely=0.5, x=-4, anchor="e")', aw)
        self.assertNotIn('self._gear_btn.pack(side="right"', aw)

    def test_title_bar_reads_brightlink_dash_echo(self):
        self.assertEqual(brand.WINDOW_TITLE, "BrightLink - Echo")
        self.assertIn("self._root.title(brand.WINDOW_TITLE)", _src("app_window.py"))
        self.assertIn("self._root.title(brand.WINDOW_TITLE)", _src("login_window.py"))

    def test_badge_text_fallback_comes_from_brand(self):
        self.assertEqual(brand.PRODUCT_SHORT_NAME, "Echo")
        self.assertIn("text=brand.PRODUCT_SHORT_NAME", _src("popup.py"))

    def test_the_build_ships_the_artwork(self):
        spec = _src("ftc_whisper.spec")
        self.assertIn("os.path.join(APP_DIR, 'assets', 'brand', '*.png')", spec)
        self.assertIn("datas.append((_p, os.path.join('assets', 'brand')))", spec)


if __name__ == "__main__":
    unittest.main()
