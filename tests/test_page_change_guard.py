"""Every page-sized change runs behind a cover, so the tab glitch cannot come
back through new code.

The glitch (Ryan, repeatedly, last 2026-10-28): clicking a tab showed the old
page's cards morphing into the new one. Tk child windows keep no pixels, so a
change that maps or unmaps a block of widgets draws over several passes of
the event loop and Windows shows each pass; the WM_SETREDRAW freeze
(`_atomic_ui`) cannot stop that. `_covered_change` can (SnapshotCover over
the old page until the new one has stopped changing).

So: hiding or showing a page-level block is only allowed in a method that
goes through `_covered_change`, and `_atomic_ui` is only allowed at the call
sites below, each proven one frame on the frame recorder
(tools/page_change_check.py) or typing-driven, where a cover would hide the
keystrokes. A new site fails here with the reason.
"""

import ast
import os
import unittest

_SRC = os.path.join(os.path.dirname(__file__), os.pardir, "app_window.py")

# Method -> why its _atomic_ui is not a page-sized swap.
_ATOMIC_ALLOWED = {
    "_covered_change": "the fallback when no cover can be made (hidden "
                       "window, Win32 failure)",
    "_switch_to_dashboard": "runs behind its own SnapshotCover",
    "_toggle_range_panel": "the OPEN path paints one canvas: one frame on "
                           "the recorder; close is covered",
    "_open_impact_detail": "paints one canvas: one frame on the recorder; "
                           "close is covered",
    "_apply_settings_search": "typing-driven filter: a cover would hide the "
                              "keystrokes",
    "_render_library": "typing-driven list filter; inside a page change it "
                       "joins the cover",
    "_render_phrases": "list redraw; inside a page change it joins the cover",
}

# Blocks whose hiding or showing is a page-sized change.
_PAGE_BLOCKS = {
    "_home_frame", "_hotkey_frame", "_history_frame", "_learning_frame",
    "_settings_frame", "_vocabulary_frame", "_snippets_frame",
    "_phrases_frame", "_dash_frame", "_login_frame", "_signing_in_frame",
    "_header_outer", "_impact_today_card", "_impact_row", "_impact_detail",
    "_impact_range_panel",
}
_HIDE_SHOW = {"grid_remove", "grid_forget", "pack_forget", "place_forget",
              "grid", "pack", "place", "tkraise", "lift"}

# Methods allowed to move page blocks outside _covered_change.
_MOVE_ALLOWED = {
    "_build_dashboard": "first build, before anything is on screen",
    "_switch_to_dashboard": "runs behind its own SnapshotCover",
    "_warm_page": "lays a hidden page out below the visible area (clipped, "
                  "never on screen; recorder shows 0 changed frames)",
    "_toggle_range_panel": "open path is one canvas; close is covered",
    "_open_impact_detail": "one canvas: one frame on the recorder",
    "_show_dashboard": "only called inside _switch_to_dashboard's cover "
                       "(pinned below)",
}


def _methods():
    with open(_SRC, encoding="utf-8-sig") as fh:
        tree = ast.parse(fh.read())
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "AppWindow":
            for node in cls.body:
                if isinstance(node, ast.FunctionDef):
                    yield node


def _calls(node, attr):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


class PageChangeGuardTests(unittest.TestCase):
    def test_atomic_ui_is_only_used_where_a_cover_is_not_needed(self):
        for m in _methods():
            if _calls(m, "_atomic_ui"):
                self.assertIn(
                    m.name, _ATOMIC_ALLOWED,
                    f"AppWindow.{m.name} uses _atomic_ui. A change that shows "
                    "or hides a block of widgets must use _covered_change, or "
                    "the tab glitch comes back. If it really is one canvas or "
                    "typing-driven, prove it on tools/page_change_check.py and "
                    "add it to _ATOMIC_ALLOWED with the reason.")

    def test_page_blocks_only_move_behind_a_cover(self):
        for m in _methods():
            moves = []
            for call in ast.walk(m):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr in _HIDE_SHOW):
                    target = call.func.value
                    if (isinstance(target, ast.Attribute)
                            and target.attr in _PAGE_BLOCKS):
                        moves.append(target.attr)
            if not moves or m.name.startswith("_build_"):
                continue
            covered = bool(_calls(m, "_covered_change"))
            self.assertTrue(
                covered or m.name in _MOVE_ALLOWED,
                f"AppWindow.{m.name} shows or hides {sorted(set(moves))} "
                "without _covered_change: that is the tab glitch. Wrap the "
                "change in self._covered_change(fn).")

    def test_show_dashboard_only_runs_under_the_hand_over_cover(self):
        callers = {m.name for m in _methods()
                   if _calls(m, "_show_dashboard")}
        # _show_login_screen is an old, unused route (no callers).
        self.assertLessEqual(callers, {"_switch_to_dashboard",
                                       "_show_login_screen"})

    def test_the_allow_lists_name_real_methods(self):
        names = {m.name for m in _methods()}
        for name in list(_ATOMIC_ALLOWED) + list(_MOVE_ALLOWED):
            self.assertIn(name, names, f"stale allow-list entry {name}")

    def test_every_tab_change_goes_through_switch_dash_tab(self):
        # The tab strip, the gear, Back buttons and the search jumps all call
        # _switch_dash_tab; it is the one place a tab page is shown.
        for m in _methods():
            if m.name in ("_switch_dash_tab", "_warm_page") or \
                    m.name.startswith("_build_"):
                continue
            for call in ast.walk(m):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr in ("grid", "tkraise")):
                    t = call.func.value
                    name = getattr(t, "attr", "")
                    self.assertFalse(
                        name.endswith("_frame") and name in _PAGE_BLOCKS
                        and name not in ("_dash_frame", "_login_frame",
                                         "_signing_in_frame"),
                        f"AppWindow.{m.name} shows tab page {name} itself; "
                        "use _switch_dash_tab.")


if __name__ == "__main__":
    unittest.main()
