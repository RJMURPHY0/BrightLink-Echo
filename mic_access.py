"""
mic_access — name the reason a dictation heard nothing, when Windows is the
reason.

A press that captures pure silence looks exactly like a working app to the
user: the cue plays, the pill shows Recording, and nothing is typed. Fleet data
(2026-10-25) showed a machine whose Realtek mic delivered bit-exact silence for
ten minutes through fourteen reopens. Windows produces that in a few ways that
the app can read for itself, without touching anything:

  * a microphone privacy switch is off (Settings > Privacy & security >
    Microphone): "Microphone access" for the device, "Let apps access your
    microphone", or "Let desktop apps access your microphone";
  * the capture endpoint is muted, or its input volume is 0;
  * none of those, but the stream is still all zeros: a hardware mute key,
    privacy shutter or driver is silencing it.

Everything here is READ ONLY and only runs after a dictation already failed,
so a working setup never sees a prompt. The fix button opens the exact
Settings page. It never flips the privacy switch itself: that switch is the
user's (or their IT's) choice by design, a per-machine one needs admin rights,
and an app rewriting the consent store is the behaviour antivirus flags as
spyware.

Cause codes are logged and may be matched in the error-events dashboard, so
they are short and STABLE: never rename one, only add a new code.
"""

import ctypes
import threading
from ctypes import wintypes

import brand

# ── Cause codes (stable; logged) ─────────────────────────────────────────────
OK = "ok"
DEVICE_ACCESS_OFF = "device_access_off"      # "Microphone access" (whole PC)
APPS_ACCESS_OFF = "apps_access_off"          # "Let apps access your microphone"
DESKTOP_ACCESS_OFF = "desktop_access_off"    # "Let desktop apps access ..."
MUTED = "mic_muted"                          # endpoint mute is on
VOLUME_ZERO = "mic_volume_zero"              # endpoint input volume is 0
DIGITAL_SILENCE = "digital_silence"          # all zeros, nothing above explains it

_PRIVACY_CAUSES = (DEVICE_ACCESS_OFF, APPS_ACCESS_OFF, DESKTOP_ACCESS_OFF)
_BLOCKING = _PRIVACY_CAUSES + (MUTED, VOLUME_ZERO, DIGITAL_SILENCE)

PRIVACY_URI = "ms-settings:privacy-microphone"
SOUND_URI = "ms-settings:sound"

_CONSENT = (r"SOFTWARE\Microsoft\Windows\CurrentVersion"
            r"\CapabilityAccessManager\ConsentStore\microphone")
_POLICY = r"SOFTWARE\Policies\Microsoft\Windows\AppPrivacy"

# Below this the input volume is effectively off (scalar 0..1).
_VOLUME_FLOOR = 0.01
# How long a failed dictation may wait for the endpoint check.
_ENDPOINT_TIMEOUT_S = 1.5


def is_blocking(cause: str) -> bool:
    return cause in _BLOCKING


def is_privacy(cause: str) -> bool:
    return cause in _PRIVACY_CAUSES


# ── Privacy switches (registry, read only) ───────────────────────────────────

def _read_value(root, path: str, name: str):
    try:
        import winreg
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None
    except Exception:
        return None


def privacy_state() -> dict:
    """The three Windows microphone switches plus the IT policy, as Windows
    stores them: "Allow", "Deny", or None when the value is absent (absent
    means the Windows default, which is on)."""
    try:
        import winreg
    except ImportError:
        return {}
    pol = _read_value(winreg.HKEY_LOCAL_MACHINE, _POLICY, "LetAppsAccessMicrophone")
    return {
        "device": _read_value(winreg.HKEY_LOCAL_MACHINE, _CONSENT, "Value"),
        "apps": _read_value(winreg.HKEY_CURRENT_USER, _CONSENT, "Value"),
        "desktop": _read_value(winreg.HKEY_CURRENT_USER, _CONSENT + r"\NonPackaged",
                               "Value"),
        # 0 user decides, 1 forced on, 2 forced off (organisation policy).
        "policy": pol if isinstance(pol, int) else None,
    }


def privacy_cause(state: dict) -> str:
    """The widest switch that is off, else OK. Order matters: with the
    whole-PC switch off the other two are greyed out in Settings."""
    def off(v):
        return isinstance(v, str) and v.strip().lower() == "deny"
    if off(state.get("device")):
        return DEVICE_ACCESS_OFF
    if off(state.get("apps")):
        return APPS_ACCESS_OFF
    if off(state.get("desktop")):
        return DESKTOP_ACCESS_OFF
    return OK


# ── Capture endpoint mute and volume (Core Audio over raw COM) ───────────────
# Private DLL handles: argtypes set on ctypes.windll are shared process-wide
# and once poisoned another module's calls (see memory: ctypes windll cache).

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str):
        super().__init__()
        import uuid
        u = uuid.UUID(text)
        self.Data1, self.Data2, self.Data3 = u.fields[0], u.fields[1], u.fields[2]
        self.Data4[:] = list(u.bytes[8:])


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    # vt + three reserved words, then an 8-byte-aligned 16-byte union. Only
    # the VT_LPWSTR member (pwszVal) is read.
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("pwszVal", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]


_CLSID_MMDeviceEnumerator = "BCDE0395-E52F-467C-8E3D-C4579291692E"  # gitleaks:allow (public Windows COM GUID)
_IID_IMMDeviceEnumerator = "A95664D2-9614-4F35-A746-DE8DB63617E6"  # gitleaks:allow (public Windows COM GUID)
_IID_IAudioEndpointVolume = "5CDF2C82-841E-4546-9722-0CF74078229A"  # gitleaks:allow (public Windows COM GUID)
_PKEY_FRIENDLY_FMTID = "A45C254E-DF1C-4EFD-8020-67D146A850E0"  # gitleaks:allow (public Windows COM GUID)
_PKEY_FRIENDLY_PID = 14
_E_CAPTURE, _E_CONSOLE = 1, 0
_DEVICE_STATE_ACTIVE = 1
_CLSCTX_INPROC_SERVER = 1
_STGM_READ = 0
_VT_LPWSTR = 31


def _method(ptr, index: int, *argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[index])


def _check(hr: int, what: str) -> None:
    if hr < 0:
        raise OSError(f"{what} failed (0x{hr & 0xFFFFFFFF:08X})")


def _release(ptr) -> None:
    if ptr:
        try:
            _method(ptr, 2)(ptr)
        except Exception:
            pass


def _friendly_name(device, ole32) -> str:
    store = ctypes.c_void_p()
    _check(_method(device, 4, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))(
        device, _STGM_READ, ctypes.byref(store)), "OpenPropertyStore")
    try:
        key = _PROPERTYKEY(_GUID(_PKEY_FRIENDLY_FMTID), _PKEY_FRIENDLY_PID)
        pv = _PROPVARIANT()
        _check(_method(store, 5, ctypes.POINTER(_PROPERTYKEY),
                       ctypes.POINTER(_PROPVARIANT))(
            store, ctypes.byref(key), ctypes.byref(pv)), "GetValue")
        try:
            return pv.pwszVal or "" if pv.vt == _VT_LPWSTR else ""
        finally:
            ole32.PropVariantClear(ctypes.byref(pv))
    finally:
        _release(store)


def _volume_state(device) -> tuple:
    vol = ctypes.c_void_p()
    iid = _GUID(_IID_IAudioEndpointVolume)
    _check(_method(device, 3, ctypes.POINTER(_GUID), wintypes.DWORD,
                   ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
        device, ctypes.byref(iid), _CLSCTX_INPROC_SERVER, None,
        ctypes.byref(vol)), "Activate")
    try:
        level = ctypes.c_float()
        muted = wintypes.BOOL()
        _check(_method(vol, 9, ctypes.POINTER(ctypes.c_float))(
            vol, ctypes.byref(level)), "GetMasterVolumeLevelScalar")
        _check(_method(vol, 15, ctypes.POINTER(wintypes.BOOL))(
            vol, ctypes.byref(muted)), "GetMute")
        return bool(muted.value), round(float(level.value), 3)
    finally:
        _release(vol)


def _device_id(device, ole32) -> str:
    pid = ctypes.c_wchar_p()
    try:
        _check(_method(device, 5, ctypes.POINTER(ctypes.c_wchar_p))(
            device, ctypes.byref(pid)), "GetId")
        return pid.value or ""
    except OSError:
        return ""
    finally:
        if pid:
            ole32.CoTaskMemFree(pid)


def capture_endpoints() -> list:
    """Every active capture endpoint: [{"name", "muted", "volume",
    "default"}]. Must run on a thread that may initialise COM (MTA)."""
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p,
                                       wintypes.DWORD, ctypes.POINTER(_GUID),
                                       ctypes.POINTER(ctypes.c_void_p)]
    ole32.PropVariantClear.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    hr = ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
    owns_com = hr >= 0  # S_OK or S_FALSE; RPC_E_CHANGED_MODE still works
    out = []
    enum = ctypes.c_void_p()
    try:
        clsid, iid = _GUID(_CLSID_MMDeviceEnumerator), _GUID(_IID_IMMDeviceEnumerator)
        _check(ole32.CoCreateInstance(ctypes.byref(clsid), None,
                                      _CLSCTX_INPROC_SERVER, ctypes.byref(iid),
                                      ctypes.byref(enum)), "CoCreateInstance")
        default_id = ""
        dflt = ctypes.c_void_p()
        if _method(enum, 4, ctypes.c_int, ctypes.c_int,
                   ctypes.POINTER(ctypes.c_void_p))(
                enum, _E_CAPTURE, _E_CONSOLE, ctypes.byref(dflt)) >= 0:
            default_id = _device_id(dflt, ole32)
            _release(dflt)
        coll = ctypes.c_void_p()
        _check(_method(enum, 3, ctypes.c_int, wintypes.DWORD,
                       ctypes.POINTER(ctypes.c_void_p))(
            enum, _E_CAPTURE, _DEVICE_STATE_ACTIVE, ctypes.byref(coll)),
            "EnumAudioEndpoints")
        try:
            count = wintypes.UINT()
            _check(_method(coll, 3, ctypes.POINTER(wintypes.UINT))(
                coll, ctypes.byref(count)), "GetCount")
            for i in range(count.value):
                dev = ctypes.c_void_p()
                if _method(coll, 4, wintypes.UINT,
                           ctypes.POINTER(ctypes.c_void_p))(
                        coll, i, ctypes.byref(dev)) < 0:
                    continue
                try:
                    entry = {"name": "", "muted": None, "volume": None,
                             "default": False}
                    try:
                        entry["name"] = _friendly_name(dev, ole32)
                    except OSError:
                        pass
                    try:
                        entry["muted"], entry["volume"] = _volume_state(dev)
                    except OSError:
                        pass
                    entry["default"] = bool(default_id) and (
                        _device_id(dev, ole32) == default_id)
                    out.append(entry)
                finally:
                    _release(dev)
        finally:
            _release(coll)
    finally:
        _release(enum)
        if owns_com:
            ole32.CoUninitialize()
    return out


def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())


def match_endpoint(endpoints: list, device_name: str):
    """The endpoint the dictation recorded from, or None when that is not
    certain. PortAudio names can be cut short (MME keeps 31 characters), so a
    prefix either way counts, but only a single match does: blaming the mute
    or volume of a different mic would send the user to fix the wrong thing.
    With no device name the stream follows the Windows default."""
    want = _norm(device_name)
    if want:
        hits = []
        for ep in endpoints:
            have = _norm(ep.get("name"))
            if have and (have == want or have.startswith(want)
                         or want.startswith(have)):
                hits.append(ep)
        return hits[0] if len(hits) == 1 else None
    for ep in endpoints:
        if ep.get("default"):
            return ep
    return endpoints[0] if len(endpoints) == 1 else None


def _endpoints_with_timeout() -> list:
    """capture_endpoints on its own thread: COM gets a clean apartment and a
    hung audio stack can never hold the caller past the timeout."""
    box = {}

    def _run():
        try:
            box["eps"] = capture_endpoints()
        except Exception as e:
            box["err"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=_run, daemon=True, name="mic-endpoints")
    t.start()
    t.join(_ENDPOINT_TIMEOUT_S)
    if t.is_alive():
        raise TimeoutError("endpoint check timed out")
    if "err" in box:
        raise OSError(box["err"])
    return box.get("eps", [])


# ── Diagnosis ────────────────────────────────────────────────────────────────

def diagnose(peak: float, device_name: str = "", *, state=None,
             endpoints=None, privacy_only: bool = False) -> tuple:
    """(cause, detail) for a dictation that came back with no speech.

    peak is the loudest sample of the clip (0..1). Only causes that are
    certain are reported: a privacy switch Windows says is off, an endpoint
    Windows says is muted or at 0, or a clip that is exactly zero. A quiet but
    live mic (peak above zero, everything on) is OK: that is a person not
    speaking, not a broken setup, and gets no prompt.

    privacy_only skips the endpoint scan (registry reads only, no COM).
    state and endpoints can be passed in (tests); otherwise they are read."""
    detail = {"device": device_name or "", "peak": round(float(peak or 0.0), 5)}
    if state is None:
        state = privacy_state()
    detail["privacy"] = state
    cause = privacy_cause(state)
    if cause != OK or privacy_only:
        detail["cause"] = cause
        return cause, detail
    if endpoints is None:
        try:
            endpoints = _endpoints_with_timeout()
        except Exception as e:
            endpoints = []
            detail["endpoint_error"] = str(e)[:200]
    ep = match_endpoint(endpoints, device_name)
    if ep is not None:
        detail["endpoint"] = {k: ep.get(k) for k in ("name", "muted", "volume")}
        if ep.get("muted"):
            cause = MUTED
        elif ep.get("volume") is not None and ep["volume"] < _VOLUME_FLOOR:
            cause = VOLUME_ZERO
    detail["endpoints"] = len(endpoints)
    if cause == OK and float(peak or 0.0) == 0.0:
        cause = DIGITAL_SILENCE
    detail["cause"] = cause
    return cause, detail


def message_for(cause: str, device_name: str = "") -> tuple:
    """(message, button text, settings URI) for the toast. Names the exact
    switch as Windows 11 labels it, so the user can find it at a glance."""
    product = brand.PRODUCT_SHORT_NAME
    mic = f"'{device_name}'" if device_name else "your microphone"
    if cause == DEVICE_ACCESS_OFF:
        return (f"Windows has microphone access turned off, so {product} "
                "can't hear you.\nTurn on 'Microphone access'.",
                "Open setting", PRIVACY_URI)
    if cause == APPS_ACCESS_OFF:
        return (f"Windows is stopping apps using the microphone, so {product} "
                "can't hear you.\nTurn on 'Let apps access your microphone'.",
                "Open setting", PRIVACY_URI)
    if cause == DESKTOP_ACCESS_OFF:
        return (f"Windows is stopping {product} using the microphone.\n"
                "Turn on 'Let desktop apps access your microphone'.",
                "Open setting", PRIVACY_URI)
    if cause == MUTED:
        return (f"{mic[0].upper() + mic[1:]} is muted in Windows, so "
                f"{product} heard nothing.\nUnmute it in Sound settings.",
                "Sound settings", SOUND_URI)
    if cause == VOLUME_ZERO:
        return (f"The input volume of {mic} is at 0, so {product} heard "
                "nothing.\nTurn it up in Sound settings.",
                "Sound settings", SOUND_URI)
    if cause == DIGITAL_SILENCE:
        return (f"{mic[0].upper() + mic[1:]} is sending no sound at all.\n"
                "Check its mute key or switch, or pick another mic.",
                "Sound settings", SOUND_URI)
    return ("", "", "")


def open_settings(uri: str) -> bool:
    """Open a Windows Settings page. ms-settings: URIs go through the shell,
    no console and no PowerShell."""
    if not uri.startswith("ms-settings:"):
        return False
    try:
        import os
        os.startfile(uri)
        return True
    except Exception as e:
        print(f"[MicAccess] Could not open {uri}: {e}")
        return False
