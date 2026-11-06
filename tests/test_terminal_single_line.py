"""Hardening: AI output pasted into a terminal window goes in on one line."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import injector as I


class OneLineTests(unittest.TestCase):
    def test_breaks_become_single_spaces(self):
        self.assertEqual(I._one_line("ls\nrm x\r\n\r\n  done"), "ls rm x done")

    def test_plain_text_unchanged(self):
        self.assertEqual(I._one_line("hello world"), "hello world")

    def test_terminal_paste_flattens_only_when_asked(self):
        for single, expected in ((True, "a b"), (False, "a\nb")):
            inj = I.Injector()
            inj._single_line = single
            seen = []
            with mock.patch.object(I.Injector, "_clipboard_set",
                                   staticmethod(lambda t, bump=True: (seen.append(t), (False, ""))[1])):
                inj._terminal_paste("a\nb")
            self.assertEqual(seen, [expected])

    def test_flag_is_cleared_after_inject(self):
        inj = I.Injector()
        with mock.patch.object(I.Injector, "_inject", return_value=True):
            inj.inject("x", single_line=True)
        self.assertFalse(inj._single_line)


if __name__ == "__main__":
    unittest.main()
