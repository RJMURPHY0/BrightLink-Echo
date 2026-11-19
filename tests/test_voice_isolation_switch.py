"""Settings > Voice Isolation off must be exactly how Echo was before it.

Pinned here, at the app level (the engine and session halves are pinned in
tests/test_voice_filter.py):
  * the switch exists in Settings, default on, and is synced like any setting;
  * off at start-up: the voice model is never loaded and nothing learns;
  * off: every dictation gets no voice track, so nothing is judged while
    talking and nothing is cut (the session then calls the engine exactly as
    v1.8.40 did);
  * switching off at runtime stops it at once and deletes the voiceprint;
  * on with no voiceprint yet: no track, so the dictation runs as if off.
"""

import ast
import os
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app  # noqa: E402
import config as config_mod  # noqa: E402
import voice_filter as vf  # noqa: E402


def _src(name: str) -> str:
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class _Stub:
    """Only what the voice isolation methods of WhisperFlowApp touch."""

    def __init__(self, on: bool, vi=None):
        self.config = types.SimpleNamespace(voice_isolation=on)
        self._voice_isolation = vi
        self.parakeet = types.SimpleNamespace(is_loaded=True)
        self.started = 0
        self.stopped = 0

    def _start_voice_isolation(self):
        self.started += 1

    def _stop_voice_isolation(self):
        self.stopped += 1


class _ReadyIsolation:
    def __init__(self):
        self.tracks = 0

    def new_track(self):
        self.tracks += 1
        return object()


class SwitchTests(unittest.TestCase):
    def test_setting_exists_default_on_and_synced(self):
        self.assertTrue(config_mod.Config().voice_isolation)
        self.assertIn('"voice_isolation", "Voice Isolation"', _src("app_window.py"))
        import cloud_sync
        self.assertIn("voice_isolation", cloud_sync.SYNCED_SETTINGS)

    def test_off_gives_no_track_and_never_asks_the_isolation(self):
        vi = _ReadyIsolation()
        stub = _Stub(on=False, vi=vi)
        self.assertIsNone(app.WhisperFlowApp._new_voice_track(stub, live=False))
        self.assertEqual(vi.tracks, 0)

    def test_live_typing_gives_no_track(self):
        vi = _ReadyIsolation()
        stub = _Stub(on=True, vi=vi)
        self.assertIsNone(app.WhisperFlowApp._new_voice_track(stub, live=True))
        self.assertEqual(vi.tracks, 0)

    def test_on_and_ready_gives_a_track(self):
        stub = _Stub(on=True, vi=_ReadyIsolation())
        self.assertIsNotNone(app.WhisperFlowApp._new_voice_track(stub, live=False))

    def test_on_with_no_voiceprint_yet_gives_no_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            class _NoModel:
                def embed_many(self, clips):
                    raise AssertionError("the voice model was used with no voiceprint")
            vi = vf.VoiceIsolation(tmp, os.path.join(tmp, "vp.json"), tmp,
                                   embedder=_NoModel())
            stub = _Stub(on=True, vi=vi)
            self.assertIsNone(app.WhisperFlowApp._new_voice_track(stub, live=False))

    def test_switching_off_stops_it_and_on_starts_it(self):
        stub = _Stub(on=True)
        app.WhisperFlowApp._apply_runtime_setting(stub, "voice_isolation", False)
        self.assertEqual((stub.started, stub.stopped), (0, 1))
        app.WhisperFlowApp._apply_runtime_setting(stub, "voice_isolation", True)
        self.assertEqual((stub.started, stub.stopped), (1, 1))

    def test_stop_deletes_the_voiceprint_even_if_never_started(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, vf.PROFILE_FILE)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{}")
            stub = _Stub(on=False)
            orig = app.data_paths.local_dir
            app.data_paths.local_dir = lambda: tmp
            try:
                app.WhisperFlowApp._stop_voice_isolation(stub)
            finally:
                app.data_paths.local_dir = orig
            self.assertFalse(os.path.exists(path))

    def test_start_up_only_starts_it_when_the_setting_is_on(self):
        # The only start-up call must sit under the setting, so with it off
        # the voice model is never downloaded, loaded or used.
        tree = ast.parse(_src("app.py"))
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                guarded = "voice_isolation" in ast.unparse(node.test)
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") \
                            == "_start_voice_isolation":
                        calls.append((sub.lineno, guarded or
                                      "value" in ast.unparse(node.test)))
        self.assertTrue(calls, "start-up call not found")
        lines = {ln for ln, _ in calls}
        guarded = {ln for ln, ok in calls if ok}
        self.assertEqual(lines, guarded, "voice isolation can start with the setting off")

    def test_voice_filter_is_never_imported_at_app_start(self):
        # app.py imports voice_filter only inside the start method, so an
        # install with the setting off never loads it.
        tree = ast.parse(_src("app.py"))
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
                self.assertNotIn("voice_filter", names)
                self.assertNotIn("speaker_embed", names)


if __name__ == "__main__":
    unittest.main()
