"""Every scroll of a page of widgets runs through AppWindow._scroll_step, so
the scroll glitch cannot come back through new code.

The glitch (Ryan, repeatedly, last 2026-11-02): scrolling Settings showed
rows stamped twice and cards torn in half for a moment. A ScrollPane moves a
frame of real child windows and Tk draws the uncovered strip later, so each
step copied half-drawn cards along. `_scroll_step` moves, paints at once and
shows the finished frame through the scroll cover; tools/scroll_check.py
proves every frame shown is a clean slice of the page.

So a call that moves a scroll surface (yview_moveto, yview with arguments,
yview_scroll) is only allowed in the methods below. A new site fails here
with the reason.
"""

import ast
import os
import unittest

_SRC = os.path.join(os.path.dirname(__file__), os.pardir, "app_window.py")
_MOVES = {"yview_moveto", "yview_scroll", "yview"}

# Method -> why it may move a scroll surface itself.
_ALLOWED = {
    "_animate_scroll": "inside the _scroll_step lambda",
    "_scrollbar_command": "inside the _scroll_step lambda",
    "_render_history": "History is one canvas with no child windows",
    "_confirm_clear_history": "History is one canvas with no child windows",
    "_apply_settings_search": "inside its _atomic_ui swap (one frame)",
}


def _methods(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield node.name, item


class ScrollGuardTests(unittest.TestCase):
    def setUp(self):
        with open(_SRC, encoding="utf-8-sig") as fh:
            self.tree = ast.parse(fh.read())

    def test_scroll_moves_only_where_allowed(self):
        bad = []
        for cls, fn in _methods(self.tree):
            if cls == "ScrollPane":
                continue        # the surface itself
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in _MOVES):
                    continue
                if node.func.attr == "yview" and not node.args:
                    continue    # reading the position moves nothing
                if fn.name not in _ALLOWED:
                    bad.append(f"{cls}.{fn.name} line {node.lineno}: "
                               f"{node.func.attr}")
        self.assertEqual(
            [], bad, "move scroll surfaces through AppWindow._scroll_step "
            "(or add the method to _ALLOWED with the reason)")

    def test_wheel_and_scrollbar_go_through_scroll_step(self):
        want = {"_animate_scroll", "_scrollbar_command"}
        found = set()
        for _cls, fn in _methods(self.tree):
            if fn.name in want:
                for node in ast.walk(fn):
                    if (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "_scroll_step"):
                        found.add(fn.name)
        self.assertEqual(want, found)

    def test_scroll_step_covers_and_paints(self):
        for _cls, fn in _methods(self.tree):
            if fn.name == "_scroll_step":
                calls = {n.func.attr for n in ast.walk(fn)
                         if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute)}
                self.assertTrue({"_paint_now", "refresh"} <= calls, calls)
                return
        self.fail("AppWindow._scroll_step is gone")


if __name__ == "__main__":
    unittest.main()
