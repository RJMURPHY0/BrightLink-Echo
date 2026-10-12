"""A screenshot on the clipboard must not turn a dictation into typing.

Reported 2026-10-12: an email dictated into Outlook went in character by
character, each line break a separate Enter, because the clipboard held an
image and the native-app path typed the text to protect it. The paste has
restored every clipboard format (images included) since v1.6.93, so a native
target pastes first and types only when the paste fails.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import injector


class PasteFirstTests(unittest.TestCase):
    def _run(self, paste_ok: bool):
        inj = injector.Injector("clipboard")
        with mock.patch.object(injector, "_release_modifiers"), \
             mock.patch.object(injector, "_get_fg_class", return_value="OpusApp"), \
             mock.patch.object(injector, "_get_fg_exe", return_value="outlook.exe"), \
             mock.patch.object(injector, "_log_inject_failure"), \
             mock.patch.object(injector.Injector, "_clipboard_has_nontext",
                               return_value=True), \
             mock.patch.object(inj, "_clipboard_paste", return_value=paste_ok) as paste, \
             mock.patch.object(inj, "_direct_inject", return_value=True) as typed:
            ok = inj._inject("Hi Ryan,\n\nThanks.\n\nKind regards,\nRyan")
        return ok, paste, typed

    def test_image_on_clipboard_still_pastes(self):
        ok, paste, typed = self._run(paste_ok=True)
        self.assertTrue(ok)
        paste.assert_called_once()
        typed.assert_not_called()

    def test_types_only_when_the_paste_fails(self):
        ok, paste, typed = self._run(paste_ok=False)
        self.assertTrue(ok)
        paste.assert_called_once()
        typed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
