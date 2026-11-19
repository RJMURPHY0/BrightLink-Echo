"""
Speaker embeddings: a fixed-length "voiceprint" vector for a stretch of audio.

Used by voice isolation (voice_filter.py) to tell the user's own voice from a
colleague talking nearby. Runs on CPU through onnxruntime, which Echo already
ships for Parakeet, with the model's input features computed in numpy, so it
adds no new dependency to the build.

The model is NVIDIA TitaNet-Small (English, 40 MB), the smaller sibling of
the TitaNet-Large BrightLink Notetaker uses for voice ID, in the sherpa-onnx
export. Picked by measurement (tools/crosstalk_bench.py, 2026-11-13): on 3 s
windows of Ryan's own dictations it scored about 0.63 against his voiceprint
and other speakers about 0, where CAM++ and WeSpeaker overlapped, and it is
3x faster than Large (0.15 s against 0.47 s per window) for the same split. The features below reproduce
sherpa-onnx's NeMo extractor (checked to cosine 0.999+ on real clips).

It is downloaded once over plain HTTPS beside the speech model and checked
against a pinned SHA-256 before it is ever loaded. Every entry point fails
soft: no model, a bad file or an inference error means no embedding, and
voice isolation then does nothing.
"""

from __future__ import annotations

import hashlib
import os
import threading
import urllib.request
from typing import Optional

import numpy as np

SAMPLE_RATE = 16000

MODEL_FILE = "titanet_small_en.onnx"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             "speaker-recongition-models/nemo_en_titanet_small.onnx")
MODEL_SHA256 = "ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e"
MODEL_BYTES = 40257283
MODEL_TAG = "titanet-small-v1"   # stored with every voiceprint; never compare across tags
EMBED_DIM = 192

# sherpa-onnx's NeMo features: 25 ms periodic Hann window, 10 ms hop, frames
# snipped at the edges, no DC removal, 0.97 pre-emphasis per frame, 512-point
# power spectrum, 80 Slaney-normalised Slaney-scale mel bands 0-7600 Hz, log,
# then each band normalised to zero mean and unit variance over the clip.
_FRAME = 400
_HOP = 160
_NFFT = 512
_NMEL = 80
_PREEMPH = 0.97
_HIGH_HZ = SAMPLE_RATE / 2.0 - 400.0

_F_SP = 200.0 / 3
_MIN_LOG_HZ = 1000.0
_MIN_LOG_MEL = _MIN_LOG_HZ / _F_SP
_LOGSTEP = np.log(6.4) / 27.0


def _hz_to_mel(f: float) -> float:
    return f / _F_SP if f < _MIN_LOG_HZ else _MIN_LOG_MEL + np.log(f / _MIN_LOG_HZ) / _LOGSTEP


def _mel_to_hz(m: float) -> float:
    return m * _F_SP if m < _MIN_LOG_MEL else _MIN_LOG_HZ * np.exp(_LOGSTEP * (m - _MIN_LOG_MEL))


def _mel_bank() -> np.ndarray:
    lo, hi = _hz_to_mel(0.0), _hz_to_mel(_HIGH_HZ)
    delta = (hi - lo) / (_NMEL + 1)
    freqs = np.arange(_NFFT // 2 + 1) * SAMPLE_RATE / _NFFT
    bank = np.zeros((_NMEL, _NFFT // 2 + 1), dtype=np.float64)
    for b in range(_NMEL):
        l_hz = _mel_to_hz(lo + b * delta)
        c_hz = _mel_to_hz(lo + (b + 1) * delta)
        r_hz = _mel_to_hz(lo + (b + 2) * delta)
        inside = (freqs > l_hz) & (freqs < r_hz)
        up = (freqs - l_hz) / (c_hz - l_hz)
        down = (r_hz - freqs) / (r_hz - c_hz)
        w = np.where(freqs <= c_hz, up, down)
        bank[b] = np.where(inside, w, 0.0) * (2.0 / (r_hz - l_hz))
    return bank.astype(np.float32)


_BANK = _mel_bank()
_WINDOW = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(_FRAME) / _FRAME)).astype(np.float32)


def features(audio: np.ndarray) -> np.ndarray:
    """(T, 80) normalised log-mel features of 16 kHz float audio in [-1, 1]."""
    x = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(x) < _FRAME:
        return np.zeros((0, _NMEL), dtype=np.float32)
    n = 1 + (len(x) - _FRAME) // _HOP
    idx = np.arange(_FRAME)[None, :] + _HOP * np.arange(n)[:, None]
    frames = x[idx]
    prev = np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)
    frames = (frames - _PREEMPH * prev) * _WINDOW
    spec = np.fft.rfft(frames, n=_NFFT, axis=1)
    power = (spec.real ** 2 + spec.imag ** 2).astype(np.float32)
    logmel = np.log(np.maximum(power @ _BANK.T, np.finfo(np.float32).eps))
    mean = logmel.mean(axis=0, keepdims=True)
    std = np.sqrt(np.mean(np.square(logmel - mean), axis=0, keepdims=True))
    return ((logmel - mean) / (std + 1e-5)).astype(np.float32)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class SpeakerEmbedder:
    """Loads the model lazily; embed() returns a unit vector or None."""

    def __init__(self, model_dir: str, model_path: str = "",
                 expected_sha256: str = MODEL_SHA256, threads: int = 2):
        self._dir = model_dir
        self._path = model_path or os.path.join(model_dir, MODEL_FILE)
        self._sha = expected_sha256
        self._threads = threads
        self._session = None
        self._failed = False
        self._lock = threading.Lock()
        self.last_error = ""

    @property
    def path(self) -> str:
        return self._path

    def is_downloaded(self) -> bool:
        return os.path.isfile(self._path)

    def download(self, url: str = MODEL_URL, expected_bytes: int = MODEL_BYTES) -> bool:
        """Fetch the model once over plain HTTPS, the same way the speech
        model is fetched (asr_engine.download_model): streamed to a .part
        file, then checked against its pinned size and SHA-256 before it is
        renamed into place. A file that fails either check is deleted."""
        if self.is_downloaded():
            return True
        os.makedirs(self._dir, exist_ok=True)
        tmp = self._path + ".part"
        try:
            import brand
            req = urllib.request.Request(url, headers={"User-Agent": brand.HTTP_USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as fh:
                while True:
                    block = resp.read(1 << 19)
                    if not block:
                        break
                    fh.write(block)
            size = os.path.getsize(tmp)
            if expected_bytes and size != expected_bytes:
                os.remove(tmp)
                self.last_error = (f"voice model download incomplete "
                                   f"({size} of {expected_bytes} bytes)")
                return False
            got = _sha256(tmp)
            if got != self._sha:
                os.remove(tmp)
                self.last_error = f"voice model hash mismatch ({got[:12]})"
                return False
            os.replace(tmp, self._path)
            return True
        except Exception as e:
            self.last_error = f"voice model download failed: {e}"
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    def _load(self) -> bool:
        if self._session is not None:
            return True
        if self._failed or not self.is_downloaded():
            return False
        try:
            if self._sha and _sha256(self._path) != self._sha:
                self.last_error = "voice model on disk does not match its hash"
                self._failed = True
                return False
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = self._threads
            opts.inter_op_num_threads = 1
            self._session = ort.InferenceSession(
                self._path, sess_options=opts, providers=["CPUExecutionProvider"])
            return True
        except Exception as e:
            self.last_error = f"voice model failed to load: {e}"
            self._failed = True
            return False

    def _run(self, feats: list) -> np.ndarray:
        """One batch of equal-length feature matrices -> raw embeddings."""
        t = feats[0].shape[0]
        pad = (16 - t % 16) % 16
        x = np.stack([np.pad(f, ((0, pad), (0, 0))) for f in feats])
        x = np.ascontiguousarray(x.transpose(0, 2, 1))          # (B, 80, T)
        lens = np.full((len(feats),), t, dtype=np.int64)
        outs = self._session.run(["embs"], {"audio_signal": x, "length": lens})
        return np.asarray(outs[0], dtype=np.float32).reshape(len(feats), -1)

    def embed_many(self, clips: list) -> Optional[np.ndarray]:
        """Unit embeddings, one row per clip (equal lengths run as one batch);
        None when the model is unavailable or fails."""
        if not clips:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)
        with self._lock:
            if not self._load():
                return None
            feats = [features(c) for c in clips]
            if any(len(f) == 0 for f in feats):
                return None
            try:
                if len({len(f) for f in feats}) == 1:
                    out = self._run(feats)
                else:
                    out = np.concatenate([self._run([f]) for f in feats])
            except Exception as e:
                self.last_error = f"voice model inference failed: {e}"
                return None
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)

    def embed(self, audio: np.ndarray) -> Optional[np.ndarray]:
        res = self.embed_many([audio])
        return None if res is None else res[0]
