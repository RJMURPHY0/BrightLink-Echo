"""Every install runs the same Parakeet model, byte for byte.

The download used to take whatever `resolve/main` served and accept any file
over a minimum size. These pin the three guarantees that replaced that: the
shipped version is fetched from a pinned commit, a file is only accepted when
its SHA-256 matches, and an existing install whose files do not match is
repaired rather than loaded. Also that an interrupted download resumes.
"""

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asr_engine

FILES = {
    "encoder-model.int8.onnx": b"E" * 3000,
    "decoder_joint-model.int8.onnx": b"D" * 700,
    "vocab.txt": b"vocab\n" * 20,
    "config.json": b'{"model": "test"}',
}


def _pins(files):
    return {n: (len(b), hashlib.sha256(b).hexdigest()) for n, b in files.items()}


class _Resp(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        p = mock.patch.dict(asr_engine._PINNED_FILES, {"vt": _pins(FILES)})
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(asr_engine._MODEL_FILES,
                            {n: 1 for n in FILES}, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.requests = []

    def serve(self, files=FILES, honour_range=True):
        def fake_urlopen(req, timeout=None):
            name = req.full_url.rsplit("/", 1)[1]
            rng = req.headers.get("Range")
            self.requests.append((name, rng))
            body = files[name]
            if rng and honour_range:
                start = int(rng.split("=")[1].rstrip("-"))
                return _Resp(body[start:], status=206)
            return _Resp(body)
        return mock.patch.object(asr_engine.urllib.request, "urlopen", fake_urlopen)

    def write(self, name, data):
        with open(os.path.join(self.dir, name), "wb") as f:
            f.write(data)


class PinningTests(unittest.TestCase):

    def test_shipped_version_downloads_from_a_pinned_commit(self):
        base = asr_engine._hf_base(asr_engine.DEFAULT_MODEL_VERSION)
        self.assertNotIn("/resolve/main", base)
        self.assertIn(asr_engine._PINNED_REVISION["v2"], base)

    def test_shipped_version_pins_every_file_it_loads(self):
        self.assertEqual(set(asr_engine._PINNED_FILES["v2"]),
                         set(asr_engine._MODEL_FILES))
        for name, (size, digest) in asr_engine._PINNED_FILES["v2"].items():
            self.assertGreaterEqual(size, asr_engine._MODEL_FILES[name], name)
            self.assertRegex(digest, r"^[0-9a-f]{64}$", name)


class DownloadTests(Base):

    def test_fresh_download_is_verified_and_lands(self):
        with self.serve():
            self.assertTrue(asr_engine.download_model(directory=self.dir, version="vt"))
        for name, data in FILES.items():
            with open(os.path.join(self.dir, name), "rb") as f:
                self.assertEqual(f.read(), data)
        self.assertTrue(asr_engine.verify_model_files(self.dir, "vt"))

    def test_a_tampered_file_is_rejected_not_installed(self):
        bad = dict(FILES, **{"vocab.txt": b"x" * len(FILES["vocab.txt"])})
        errors = []
        with self.serve(bad):
            ok = asr_engine.download_model(directory=self.dir, version="vt",
                                           error_out=errors)
        self.assertFalse(ok)
        self.assertIn("SHA-256", errors[0])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "vocab.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "vocab.txt.part")))

    def test_an_interrupted_download_resumes_where_it_stopped(self):
        enc = FILES["encoder-model.int8.onnx"]
        self.write("encoder-model.int8.onnx.part", enc[:1200])
        with self.serve():
            self.assertTrue(asr_engine.download_model(directory=self.dir, version="vt"))
        self.assertIn(("encoder-model.int8.onnx", "bytes=1200-"), self.requests)
        with open(os.path.join(self.dir, "encoder-model.int8.onnx"), "rb") as f:
            self.assertEqual(f.read(), enc)

    def test_a_server_that_ignores_the_range_still_gives_a_whole_file(self):
        enc = FILES["encoder-model.int8.onnx"]
        self.write("encoder-model.int8.onnx.part", enc[:1200])
        with self.serve(honour_range=False):
            self.assertTrue(asr_engine.download_model(directory=self.dir, version="vt"))
        with open(os.path.join(self.dir, "encoder-model.int8.onnx"), "rb") as f:
            self.assertEqual(f.read(), enc)

    def test_a_refused_resume_clears_the_part_for_the_next_attempt(self):
        self.write("encoder-model.int8.onnx.part", b"E" * 1200)

        def refuse(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 416, "Range", {}, None)

        with mock.patch.object(asr_engine.urllib.request, "urlopen", refuse):
            self.assertFalse(asr_engine.download_model(directory=self.dir, version="vt"))
        self.assertFalse(os.path.exists(
            os.path.join(self.dir, "encoder-model.int8.onnx.part")))

    def test_files_already_in_place_are_not_fetched_again(self):
        for name, data in FILES.items():
            self.write(name, data)
        with self.serve():
            self.assertTrue(asr_engine.download_model(directory=self.dir, version="vt"))
        self.assertEqual(self.requests, [])


class VerifyExistingInstallTests(Base):

    def test_a_same_size_wrong_file_is_removed_so_it_redownloads(self):
        for name, data in FILES.items():
            self.write(name, data)
        self.write("decoder_joint-model.int8.onnx", b"Z" * 700)
        self.assertTrue(asr_engine.model_files_present(self.dir, "vt"))
        self.assertFalse(asr_engine.verify_model_files(self.dir, "vt"))
        self.assertFalse(os.path.exists(
            os.path.join(self.dir, "decoder_joint-model.int8.onnx")))
        self.assertFalse(asr_engine.model_files_present(self.dir, "vt"))

    def test_a_wrong_size_is_not_even_present(self):
        for name, data in FILES.items():
            self.write(name, data)
        self.write("vocab.txt", FILES["vocab.txt"] + b"extra")
        self.assertFalse(asr_engine.model_files_present(self.dir, "vt"))

    def test_verified_files_are_not_hashed_again(self):
        for name, data in FILES.items():
            self.write(name, data)
        self.assertTrue(asr_engine.verify_model_files(self.dir, "vt"))
        with open(os.path.join(self.dir, asr_engine._VERIFIED_MARKER)) as f:
            self.assertEqual(set(json.load(f)), set(FILES))
        with mock.patch.object(asr_engine, "_sha256",
                               side_effect=AssertionError("re-hashed")):
            self.assertTrue(asr_engine.verify_model_files(self.dir, "vt"))

    def test_a_file_changed_after_verification_is_checked_again(self):
        for name, data in FILES.items():
            self.write(name, data)
        self.assertTrue(asr_engine.verify_model_files(self.dir, "vt"))
        p = os.path.join(self.dir, "config.json")
        self.write("config.json", b'{"model": "tset"}')
        st = os.stat(p)
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        self.assertFalse(asr_engine.verify_model_files(self.dir, "vt"))


if __name__ == "__main__":
    unittest.main()
