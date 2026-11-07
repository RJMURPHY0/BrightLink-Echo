"""Crash, hang and error watch: nothing that stops Echo goes unseen.

A process that dies cannot report itself, so each run keeps a small state file
it refreshes while alive. The next run reads it and decides what ended the last
one: a deliberate exit, a machine restart, or a crash. Reports wait in a file
until a signed-in reporter accepts them, so an offline start loses nothing.

Reports carry no dictated text: event names, numbers, code locations and the
tail of echo.log, which runtime_log has already scrubbed.
"""

import ctypes
import faulthandler
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import traceback

STATE_FILE = "run-state.json"
NATIVE_FILE = "crash-native.log"
HANG_FILE = "hang-stacks.log"
PENDING_FILE = "crash-pending.json"
RESTARTS_FILE = "crash-restarts.json"

BEAT_S = 15.0
TK_BEAT_MS = 5000
HANG_REPORT_S = 60.0
HANG_RESTART_S = 600.0
# The watch thread waking this late means the whole machine stalled or slept,
# so a stale Tk beat says nothing about Tk.
STALL_S = 30.0
EXIT_MARK_EXPIRY_S = 300.0
MAX_RESTARTS_PER_HOUR = 3
MAX_PENDING = 20
MAX_ERRORS_PER_RUN = 20
LOG_TAIL_LINES = 40
TEXT_CAP = 2500

# What goes in the BrightLink error log as well as error_events.
LOGGED_KINDS = {"app_crashed", "ui_hang", "ui_error", "thread_error"}


def boot_wall_time() -> float:
    """When this machine last started, as a wall-clock time."""
    try:
        k32 = ctypes.WinDLL("kernel32")
        k32.GetTickCount64.restype = ctypes.c_ulonglong
        return time.time() - k32.GetTickCount64() / 1000.0
    except Exception:
        return 0.0


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        print(f"[CrashWatch] Could not read {os.path.basename(path)}: {e}")
        return default


def _write_json(path: str, data) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _read_tail(path: str, cap: int = TEXT_CAP) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - cap))
            return f.read().decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _log_tail(folder: str) -> str:
    text = _read_tail(os.path.join(folder, "echo.log"), cap=TEXT_CAP * 2)
    return "\n".join(text.splitlines()[-LOG_TAIL_LINES:])[-TEXT_CAP:]


def classify_previous(state, boot_time: float, native_trace: str = "") -> str:
    """How the last run ended: none, clean, machine_restart, native_crash or
    vanished (killed, or died without a trace)."""
    if not state:
        return "none"
    if state.get("exit"):
        return "clean"
    if boot_time and boot_time > float(state.get("beat") or 0):
        return "machine_restart"
    return "native_crash" if native_trace else "vanished"


def exception_summary(exc_type, exc_value, exc_tb) -> dict:
    """Type and code locations only: an exception's message can quote text."""
    frames = [f"{os.path.basename(f.filename)}:{f.lineno} {f.name}"
              for f in traceback.extract_tb(exc_tb)][-12:]
    name = getattr(exc_type, "__name__", str(exc_type))
    signature = hashlib.sha1(("|".join(frames) + name).encode()).hexdigest()[:12]
    return {"exception": name, "frames": frames, "signature": signature}


class CrashWatch:
    def __init__(self, folder: str, version: str, frozen: bool = False,
                 boot_time=boot_wall_time, restart_fn=None):
        self.folder = folder
        self.version = version
        self.frozen = frozen
        self._boot_time = boot_time
        self._restart_fn = restart_fn or self._relaunch
        self._lock = threading.RLock()
        self._reporter = None
        self._busy = lambda: False
        self._seen = set()
        self._errors = 0
        self._exit = None
        self._exit_at = 0.0
        self._started = time.time()
        self._native = None
        self._tk_beat = None
        self._hang_reported = False
        self._stop = threading.Event()

    def _path(self, name: str) -> str:
        return os.path.join(self.folder, name)

    # ── Start ────────────────────────────────────────────────────────────

    def start(self) -> str:
        """Judge the last run, then begin watching this one. Returns the
        verdict. Call only once this process owns the single-instance mutex."""
        os.makedirs(self.folder, exist_ok=True)
        verdict = self._judge_previous()
        self._write_state()
        self._enable_native_trace()
        self._register_windows_restart()
        threading.Thread(target=self._loop, daemon=True, name="crash-watch").start()
        print(f"[CrashWatch] Watching v{self.version}; last run ended: {verdict}.")
        return verdict

    def _judge_previous(self) -> str:
        state = _read_json(self._path(STATE_FILE), None)
        trace = _read_tail(self._path(NATIVE_FILE))
        verdict = classify_previous(state, self._boot_time(), trace)
        if verdict in ("native_crash", "vanished"):
            detail = {
                "cause": verdict,
                "version": state.get("version"),
                "ran_s": int(float(state.get("beat") or 0) - float(state.get("started") or 0)),
                "memory_load": state.get("memory_load"),
                "avail_phys_mb": state.get("avail_phys_mb"),
                "log_tail": _log_tail(self.folder),
            }
            if trace:
                detail["native_trace"] = trace
            self._queue("app_crashed", detail)
        if trace:
            try:
                os.remove(self._path(NATIVE_FILE))
            except OSError as e:
                print(f"[CrashWatch] Could not clear the native trace: {e}")
        return verdict

    def _enable_native_trace(self) -> None:
        try:
            self._native = open(self._path(NATIVE_FILE), "a", encoding="utf-8")
            faulthandler.enable(file=self._native, all_threads=True)
        except Exception as e:
            print(f"[CrashWatch] Native crash trace is off: {e}")

    def _register_windows_restart(self) -> None:
        """Windows relaunches the app after a crash or hang, with no helper
        process. Restarts for patches and reboots stay off: the sign-in
        launcher handles those. Only the installed build registers."""
        if not self.frozen:
            return
        try:
            restart_no_patch, restart_no_reboot = 4, 8
            k32 = ctypes.WinDLL("kernel32")
            k32.RegisterApplicationRestart.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong]
            k32.RegisterApplicationRestart.restype = ctypes.c_long
            result = k32.RegisterApplicationRestart(
                "--startup", restart_no_patch | restart_no_reboot)
            if result != 0:
                print(f"[CrashWatch] Windows restart registration refused: {result}")
        except Exception as e:
            print(f"[CrashWatch] Windows restart registration failed: {e}")

    # ── Exits and state ──────────────────────────────────────────────────

    def mark_exit(self, reason: str) -> None:
        """A deliberate exit is about to happen, so the next run must not call
        it a crash. A mark outlives a failed update by EXIT_MARK_EXPIRY_S only."""
        with self._lock:
            self._exit = reason
            self._exit_at = time.time()
            self._safe_write_state()

    def _write_state(self) -> None:
        state = {"pid": os.getpid(), "version": self.version,
                 "started": self._started, "beat": time.time(),
                 "exit": self._exit}
        try:
            from memory_guard import sample_memory
            memory = sample_memory() or {}
            state["memory_load"] = memory.get("memory_load")
            state["avail_phys_mb"] = memory.get("avail_phys_mb")
        except Exception:
            pass
        _write_json(self._path(STATE_FILE), state)

    def _safe_write_state(self) -> None:
        try:
            self._write_state()
        except Exception as e:
            print(f"[CrashWatch] Could not write the run state: {e}")

    # ── Reports ──────────────────────────────────────────────────────────

    def set_reporter(self, reporter) -> None:
        """reporter(kind, detail) -> True once the report is stored remotely."""
        self._reporter = reporter
        threading.Thread(target=self.flush, daemon=True, name="crash-flush").start()

    def set_busy_check(self, busy) -> None:
        self._busy = busy

    def _queue(self, kind: str, detail: dict) -> None:
        with self._lock:
            pending = _read_json(self._path(PENDING_FILE), [])
            pending.append({"kind": kind, "detail": detail, "version": self.version,
                            "at": time.time()})
            try:
                _write_json(self._path(PENDING_FILE), pending[-MAX_PENDING:])
            except Exception as e:
                print(f"[CrashWatch] Could not save a {kind} report: {e}")

    def flush(self) -> int:
        """Send waiting reports. A refused report stays for the next try."""
        reporter = self._reporter
        if reporter is None:
            return 0
        with self._lock:
            pending = _read_json(self._path(PENDING_FILE), [])
            kept, sent = [], 0
            for item in pending:
                try:
                    ok = reporter(item["kind"], item["detail"])
                except Exception as e:
                    print(f"[CrashWatch] Report failed: {e}")
                    ok = False
                if ok:
                    sent += 1
                else:
                    kept.append(item)
            if pending:
                try:
                    if kept:
                        _write_json(self._path(PENDING_FILE), kept)
                    else:
                        os.remove(self._path(PENDING_FILE))
                except OSError as e:
                    print(f"[CrashWatch] Could not update the report queue: {e}")
            return sent

    def note_exception(self, kind: str, exc_type, exc_value, exc_tb) -> None:
        """A caught-at-the-top error. Each distinct one reports once per run."""
        try:
            summary = exception_summary(exc_type, exc_value, exc_tb)
            with self._lock:
                if summary["signature"] in self._seen or self._errors >= MAX_ERRORS_PER_RUN:
                    return
                self._seen.add(summary["signature"])
                self._errors += 1
            self._queue(kind, summary)
            threading.Thread(target=self.flush, daemon=True, name="crash-flush").start()
        except Exception as e:
            print(f"[CrashWatch] Could not record an error: {e}")

    def on_fatal(self, exc: BaseException) -> None:
        """The main thread is about to die with an uncaught exception."""
        detail = {"cause": "main_thread_exception", "version": self.version,
                  "ran_s": int(time.time() - self._started),
                  "log_tail": _log_tail(self.folder)}
        detail.update(exception_summary(type(exc), exc, exc.__traceback__))
        self._queue("app_crashed", detail)
        self.mark_exit("fatal_reported")
        self._restart("fatal")

    # ── Tk ───────────────────────────────────────────────────────────────

    def watch_tk(self, root) -> None:
        """Report Tk callback errors and keep a beat that proves the UI loop
        is alive. Runs on the Tk thread."""
        previous = root.report_callback_exception

        def _report(exc_type, exc_value, exc_tb):
            self.note_exception("ui_error", exc_type, exc_value, exc_tb)
            previous(exc_type, exc_value, exc_tb)

        root.report_callback_exception = _report

        def _beat():
            self._tk_beat = time.monotonic()
            try:
                root.after(TK_BEAT_MS, _beat)
            except Exception:
                self._tk_beat = None

        _beat()

    def check_hang(self, now: float) -> None:
        beat = self._tk_beat
        if beat is None:
            return
        stale = now - beat
        if stale < HANG_REPORT_S:
            if self._hang_reported:
                self._hang_reported = False
                print("[CrashWatch] The window came back.")
            return
        if not self._hang_reported:
            self._hang_reported = True
            self._queue("ui_hang", {"stale_s": int(stale), "stacks": self._dump_stacks(),
                                    "log_tail": _log_tail(self.folder)})
            self.flush()
        if stale >= HANG_RESTART_S and not self._busy():
            self._queue("app_crashed", {"cause": "hang_restart", "version": self.version,
                                        "stale_s": int(stale)})
            self.flush()
            self.mark_exit("hang_restart")
            self._restart("hang")

    def _dump_stacks(self) -> str:
        path = self._path(HANG_FILE)
        try:
            with open(path, "w", encoding="utf-8") as f:
                faulthandler.dump_traceback(file=f, all_threads=True)
            return _read_tail(path)
        except Exception as e:
            return f"stacks unavailable: {e}"

    # ── Restart ──────────────────────────────────────────────────────────

    def _restart_allowed(self) -> bool:
        """At most MAX_RESTARTS_PER_HOUR, so a crash loop cannot run forever."""
        path = self._path(RESTARTS_FILE)
        now = time.time()
        recent = [t for t in _read_json(path, []) if now - t < 3600]
        if len(recent) >= MAX_RESTARTS_PER_HOUR:
            self._queue("app_crashed", {"cause": "restart_limit_reached",
                                        "version": self.version,
                                        "restarts_last_hour": len(recent)})
            return False
        recent.append(now)
        try:
            _write_json(path, recent)
        except Exception as e:
            print(f"[CrashWatch] Could not record a restart: {e}")
        return True

    def _restart(self, why: str) -> None:
        if not self._restart_allowed():
            print(f"[CrashWatch] Not restarting after {why}: limit reached.")
            return
        self._restart_fn(why)

    def _relaunch(self, why: str) -> None:
        if not self.frozen:
            print(f"[CrashWatch] Source run: no relaunch after {why}.")
            return
        import pyi_runtime
        print(f"[CrashWatch] Relaunching after {why}.")
        subprocess.Popen([sys.executable, "--startup"],
                         close_fds=True, env=pyi_runtime.clean_launch_env(),
                         creationflags=subprocess.CREATE_NO_WINDOW)
        os._exit(1)

    # ── Loop ─────────────────────────────────────────────────────────────

    def _tick(self, now: float, gap: float) -> None:
        with self._lock:
            if self._exit and time.time() - self._exit_at > EXIT_MARK_EXPIRY_S:
                self._exit = None
            self._safe_write_state()
        if gap > STALL_S:
            # Slept or stalled: give Tk a fresh window to prove itself.
            if self._tk_beat is not None:
                self._tk_beat = now
            return
        self.check_hang(now)
        self.flush()

    def _loop(self) -> None:
        last = time.monotonic()
        while not self._stop.wait(BEAT_S):
            now = time.monotonic()
            try:
                self._tick(now, now - last)
            except Exception as e:
                print(f"[CrashWatch] Watch pass failed: {e}")
            last = now

    def stop(self) -> None:
        self._stop.set()
        try:
            faulthandler.disable()
            if self._native:
                self._native.close()
        except Exception as e:
            print(f"[CrashWatch] Stop failed: {e}")


instance = None


def start(folder: str, version: str, frozen: bool = False):
    global instance
    instance = CrashWatch(folder, version, frozen=frozen)
    instance.start()
    return instance


def get():
    return instance
