---
paths: ["recorder.py", "feedback.py", "stream_session.py", "memory_guard.py", "hotkey_manager.py"]
---
# Audio capture and hotkeys

Full history: docs/decisions/audio-capture-hotkeys.md

- Warm mic is always on. The settings toggle stays removed.
- Mic auto-selection is evidence-based. Never capture from several mics at once.
- The start cue fires at the key press, not after the mic verify loop.
- The keyboard-hook hotkey fallback must suppress the base key.
- **The start/stop cue in `feedback.py` is FINAL.** Ryan's explicit instruction (2026-08-19): "the beep sound absolutely must stay exactly as it is". It took five attempts to land and was settled by measuring Glaido's own embedded WAVs rather than guessing. Never touch `_recipe()`, `_tap()`, `_two_tap()`, the `_TAP_*` constants, `_SR`, or the cue pitches / order. When a report says the cue feels late, the answer is upstream (capture, VAD, press-path latency) — it is never the sound
- The whisper caption loop paces on `_caption_stop_event` (CLEAR while running) — never wait on `_caption_loop_running`, which is SET while running so `Event.wait()` returns immediately (busy-spin bug)
- Never judge mic stream health by `.active` — only by callback heartbeat age. Never call `_refresh_portaudio()` with any stream open (monitor open/close is serialised under `_stream_lifecycle_lock` for exactly this reason)
- The popup's voice-prompt mic must NEVER open its own sounddevice stream (use `Recorder.start_aux_capture()`) — a rogue stream records the Windows default mic instead of the configured device and can be killed mid-read by the watchdog's PortAudio re-init
