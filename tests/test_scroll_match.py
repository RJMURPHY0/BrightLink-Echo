"""The visual verifier must distinguish repeated rows with equal grey means."""
import ast
from pathlib import Path
import unittest
import itertools
import numpy as np

source = Path(__file__).resolve().parents[1] / "tools" / "scroll_check.py"
# Load just the pure matcher. Importing the script itself opens a Tk window.
node = next(n for n in ast.parse(source.read_text(encoding="utf-8")).body
            if isinstance(n, ast.FunctionDef) and n.name == "_match")
namespace = {"_PIXEL_TOL": 24}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
match = namespace["_match"]


class ScrollMatchTests(unittest.TestCase):
    def test_identical_row_averages_do_not_select_the_wrong_library_row(self):
        rng = np.random.default_rng(7)
        base = rng.integers(0, 40, size=(10, 16), dtype=np.int16)
        blocks = []
        for points in list(itertools.combinations(range(8), 4))[:40]:
            block = base.copy()
            block[2, :8] = 0
            block[2, list(points)] = 255
            blocks.append(block)
        reference = np.concatenate(blocks)
        fraction, y = match(reference, reference.mean(axis=1), blocks[35])
        self.assertEqual(fraction, 0)
        self.assertEqual(y, 350)

    def test_a_torn_frame_is_still_rejected(self):
        rng = np.random.default_rng(8)
        reference = rng.integers(0, 255, size=(160, 40), dtype=np.int16)
        torn = np.concatenate((reference[10:20], reference[70:80]))
        fraction, _ = match(reference, reference.mean(axis=1), torn)
        self.assertGreater(fraction, 0.2)
