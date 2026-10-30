"""Guard: no em or en dash in the text people read.

An em dash (U+2014) or en dash (U+2013) is the quickest giveaway that AI wrote
something. The modules below hold the on-screen text, messages and AI prompts,
so no string in them may carry one (docstrings and comments are ignored), and
neither may the README. Fix the string; never widen the lists to make this pass.
"""
import io
import re
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH = re.compile("[\u2013\u2014]")

MODULES = [
    "ai_refiner.py", "app.py", "app_window.py", "popup.py", "login_window.py", "auth.py",
    "updater.py", "installer.py", "tray.py", "stats.py", "speech_health.py", "config.py",
    "supabase_client.py", "recorder.py", "av_report.py",
]
# Strings that must hold a dash because they match one in someone else's data.
ALLOWED = {
    ("app_window.py", "--- boot: returning user \u2014 restoring saved session ---"),
}


def _string_dashes(path: Path):
    src = path.read_text(encoding="utf-8")
    toks = [t for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type not in (tokenize.COMMENT, tokenize.NL)]
    for i, t in enumerate(toks):
        if t.type != tokenize.STRING or not DASH.search(t.string):
            continue
        before = toks[i - 1].type if i else tokenize.NEWLINE
        after = toks[i + 1].type if i + 1 < len(toks) else tokenize.NEWLINE
        is_docstring = before in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT) and after == tokenize.NEWLINE
        if not is_docstring:
            yield t.start[0], t.string


class NoAiTellsTests(unittest.TestCase):
    def test_no_dash_in_user_facing_strings(self):
        found = []
        for name in MODULES:
            for line, text in _string_dashes(ROOT / name):
                if not any(name == n and frag in text for n, frag in ALLOWED):
                    found.append(f"{name}:{line}: {text[:70]}")
        self.assertEqual([], found)

    def test_readme_has_no_dash(self):
        self.assertIsNone(DASH.search((ROOT / "README.md").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
