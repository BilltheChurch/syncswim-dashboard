# Codebase Concerns

**Analysis Date:** 2026-03-22

## Tech Debt

**No requirements.txt or dependency lockfile:**
- Issue: No `requirements.txt`, `pyproject.toml`, or `Pipfile` exists. The exact working dependency combination (numpy<2, opencv-python<4.11, mediapipe 0.10.33, tensorflow-macos 2.15.0) was discovered through painful trial-and-error (documented in `DEVLOG.md` problem #10) but never captured in a machine-readable form.
- Files: project root (missing file)
- Impact: Any new machine setup will re-encounter the three-way numpy/opencv/mediapipe/tensorflow version conflict. The fix is known but not codified.
- Fix approach: Create `requirements.txt` pinning at minimum: `numpy<2`, `opencv-python<4.11`, `mediapipe==0.10.33`, `bleak>=0.21`, `matplotlib`.

**Duplicated code across recorder.py and sync_recorder.py:**
- Issue: `MjpegStreamReader` class is copy-pasted verbatim between `vision.py` (lines 44-93) and `sync_recorder.py` (lines 231-274). BLE notification handler logic (`handle_notification` / `handle_ble_notification`) is also substantially duplicated between `recorder.py` and `sync_recorder.py`. The packet-loss detection magic numbers (`gap > 100`, `int(gap / 12)`) are hardcoded inline in `sync_recorder.py` (lines 170-172) while `recorder.py` uses named constants (`LOSS_THRESHOLD_MS`, `EXPECTED_INTERVAL_MS`).
- Files: `recorder.py`, `sync_recorder.py`, `vision.py`
- Impact: Any bug fix or protocol change must be applied in multiple places. The inconsistency between named constants in `recorder.py` and magic numbers in `sync_recorder.py` already exists.
- Fix approach: Extract `MjpegStreamReader` and BLE handler into a shared `utils.py` or `ble_utils.py` module. Replace magic numbers in `sync_recorder.py` lines 170-172 with the same named constants used in `recorder.py`.

**receive_ble.py uses obsolete text protocol:**
- Issue: `receive_ble.py` (lines 37-44) decodes BLE data as UTF-8 text (`data.decode("utf-8")`) and parses comma-separated fields. All other scripts use the binary batch protocol. This script is a dead leftover from before the protocol migration.
- Files: `receive_ble.py`
- Impact: Running `receive_ble.py` against the current firmware will produce garbage or crash. It gives a false impression of compatibility.
- Fix approach: Either update to parse the binary protocol or delete the file after confirming it is only a diagnostic artifact.

**Hard-coded camera IP address:**
- Issue: `CAMERA_URL = "http://192.168.66.169:4747/video"` is hard-coded in both `vision.py` (line 27) and `sync_recorder.py` (line 29). This is a specific device's local IP that changes when the phone reconnects to Wi-Fi or moves to a different network.
- Files: `vision.py:27`, `sync_recorder.py:29`
- Impact: Script fails silently on any machine/network other than the one where this was developed. The error message (line 158 of `vision.py`) helpfully lists troubleshooting steps but not how to change the URL.
- Fix approach: Accept the camera URL as a CLI argument with the current value as default, e.g. `python3 vision.py --camera http://...`.

**Mediapipe imports deferred inside main():**
- Issue: In both `vision.py` (lines 171-172) and `sync_recorder.py` (lines 351-352), `from mediapipe.tasks.python.vision import ...` is placed inside the `main()` function body rather than at the module top level.
- Files: `vision.py:171-172`, `sync_recorder.py:351-352`
- Impact: Import errors surface only after the camera connects and setup proceeds, rather than at startup. Also unusual and inconsistent with how `mediapipe` itself is imported at the top of the same files (lines 22).
- Fix approach: Move these imports to the module top-level alongside the existing `import mediapipe as mp` statement.

---

## Known Bugs

**vision.py reconnect fallback uses cv2.VideoCapture (broken on macOS ARM):**
- Symptoms: When a frame grab fails during recording in `vision.py`, the reconnect path (lines 202-205) calls `cap = cv2.VideoCapture(CAMERA_URL)`, replacing the working `MjpegStreamReader` instance with an OpenCV `VideoCapture` object that is known to fail on macOS ARM (this is the exact issue documented as problem #8 in `DEVLOG.md`).
- Files: `vision.py:202-205`
- Trigger: Any transient Wi-Fi hiccup during a recording session causes the camera object to be silently replaced by a broken one. All subsequent `cap.read()` calls return `False`, causing an infinite reconnect loop printing "Frame grab failed, reconnecting..." without ever recovering.
- Workaround: Restart `vision.py`. The `MjpegStreamReader` class already handles reconnect internally in its `_reader` thread — the outer reconnect block in `main()` is redundant and incorrect.

**analyze.py: `corr` variable used before assignment in plot title:**
- Symptoms: If `mask.sum() <= 10` (fewer than 10 visible vision frames), the `corr` variable is never assigned. Line 178 references `corr` in an f-string conditional (`if mask.sum() > 10 else 'Overlay Comparison'`), but Python evaluates both branches of the ternary for syntax purposes — the f-string will raise `NameError: name 'corr' is not defined` at render time even when the `else` branch would be taken.
- Files: `analyze.py:178`
- Trigger: Analyzing a recording set where the subject was not visible to the camera for most frames (e.g. poor lighting, camera angle).
- Workaround: Assign `corr = float('nan')` as a default before the conditional block.

**sync_recorder.py: silent swallowing of BLE errors:**
- Symptoms: The BLE reconnect loop in `sync_recorder.py` (lines 216-217) catches all exceptions with `except Exception: pass`, discarding any error information. If BLE fails for a non-transient reason (firmware change, UUID mismatch, Bluetooth stack crash), the loop silently retries forever with no feedback to the user.
- Files: `sync_recorder.py:216-217`
- Trigger: Any BLE-layer error during the sync session.
- Workaround: None — user must infer failure from the OSD showing `BLE:--` indefinitely. Compare with `recorder.py` which at least surfaces the error string via `set_status(f"Error: {e}")`.

---

## Security Considerations

**No input validation on BLE packet set_number field:**
- Risk: The `set_n` byte from the BLE packet header (byte index 1) is used directly as the set directory name component without bounds checking in `recorder.py` (lines 209, 222) and `sync_recorder.py` (lines 134, 147). The firmware casts `setNumber` to `uint8_t` (max 255) before transmitting (`test_rec.ino:263`), so after 255 sets the counter wraps to 0 and a new recording would be written into directory `set_000_...`, shadowing the first session's data.
- Files: `test_rec.ino:263`, `recorder.py:209`, `sync_recorder.py:134`
- Current mitigation: None.
- Recommendations: Either use the Python-side `state.set_number` counter (which is unbounded) rather than the device-reported byte for directory naming, or add an overflow guard in the firmware.

**MJPEG buffer grows unboundedly on slow/corrupt streams:**
- Risk: In both `vision.py` (line 67) and `sync_recorder.py` (line 251), the MJPEG parser appends to `buf` with `buf += chunk`. If the JPEG end marker `\xff\xd9` is never found (e.g. corrupt stream, partial frame at stream start), `buf` grows without bound, consuming all available RAM.
- Files: `vision.py:57-81`, `sync_recorder.py:241-264`
- Current mitigation: None — there is no maximum buffer size check.
- Recommendations: Add a `MAX_BUF_SIZE` cap (e.g. 5 MB) and reset `buf = b""` if exceeded.

---

## Performance Bottlenecks

**MediaPipe running in IMAGE mode (no temporal tracking):**
- Problem: Both `vision.py` (line 178) and `sync_recorder.py` (line 358) configure `PoseLandmarker` with `running_mode=RunningMode.IMAGE`. This mode performs full pose detection from scratch on every single frame with no temporal continuity.
- Files: `vision.py:175-180`, `sync_recorder.py:355-360`
- Cause: `RunningMode.VIDEO` or `RunningMode.LIVE_STREAM` would leverage inter-frame tracking, reducing compute load and improving stability of landmark positions.
- Improvement path: Switch to `RunningMode.VIDEO` and provide monotonically increasing timestamps per frame. This would also improve angle stability for the elbow tracking use case.

**Per-frame RGB conversion copying the full frame:**
- Problem: Every frame processed by MediaPipe requires `cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)` which allocates a full-frame copy. At 26 FPS and ~640x480 resolution this is ~24 MB/s of memory allocation pressure.
- Files: `vision.py:228-230`, `sync_recorder.py:400-402`
- Cause: OpenCV reads in BGR; MediaPipe requires SRGB. The conversion is unavoidable but the copy is.
- Improvement path: Minor — acceptable for current use but worth noting if frame resolution increases.

**Rate window uses list rebuild on every packet:**
- Problem: `State.calc_rate()` in `recorder.py` (lines 61-75) and the equivalent in `sync_recorder.py` (lines 78-87) rebuild the entire `_rate_window` list by filtering on every single packet (~86 Hz). At scale this is O(n) per packet.
- Files: `recorder.py:61-75`, `sync_recorder.py:78-87`
- Cause: Simple implementation choice.
- Improvement path: Use `collections.deque` with a `maxlen` or a bisect-based approach to avoid full list reconstruction.

---

## Fragile Areas

**Threading between BLE callback and vision main loop in sync_recorder.py:**
- Files: `sync_recorder.py`
- Why fragile: The BLE notification callback (`handle_ble_notification`) runs in a separate asyncio thread and acquires `state.lock` to write CSV rows and update state. The vision main loop also acquires `state.lock` to write the vision CSV. The BLE thread (`ble_thread_func`) runs its own asyncio event loop via `asyncio.run()` in a daemon thread. If either thread holds the lock during a slow I/O operation (CSV write, file flush), the other stalls. There is also no protection against `stop_recording()` being called from both the BLE thread (on BLE disconnect) and the main thread (on KeyboardInterrupt) simultaneously — both paths set `state.recording = False` and call `stop_recording()`, which closes and nulls the file handles. A race here would call `f.close()` twice or write after close.
- Safe modification: Always check file handle is not None before flushing/closing. Add a guard flag `stop_in_progress` or use the existing lock more carefully around the full `recording=False` + `stop_recording()` sequence.
- Test coverage: No tests exist.

**set_number overflow wrapping to 0 after 255 sets:**
- Files: `test_rec.ino:263`, `recorder.py:207-222`, `sync_recorder.py:134-147`
- Why fragile: The device transmits `set_number` as a single `uint8_t` byte. After 255 button presses it wraps to 0. Python receives 0 and opens a new directory `set_000_...` — potentially overwriting the first session if the same timestamp second is reused, or simply being confusing.
- Safe modification: Track set count on the Python side independently of the device byte (Python `state.set_number` is already a separate counter in `recorder.py` but is overwritten by device value at line 222).

**Model file path resolution with empty `__file__`:**
- Files: `vision.py:174`, `sync_recorder.py:354`
- Why fragile: `os.path.dirname(__file__) or "."` handles the case where `__file__` is empty, but if the script is run from a directory other than the project root, `pose_landmarker_lite.task` will not be found. There is no clear error — MediaPipe will raise a generic model load error.
- Safe modification: Use `pathlib.Path(__file__).parent / "pose_landmarker_lite.task"` which always resolves relative to the script location regardless of working directory.

---

## Scaling Limits

**Single-joint, single-person tracking:**
- Current capacity: The system tracks exactly one joint (right elbow, landmark indices 12/14/16) on exactly one person (`results.pose_landmarks[0]`).
- Limit: Adding a second joint or second person requires modifying `JOINT_A/B/C` constants and adding a second CSV column set; the current data schema has no joint-name multiplexing.
- Scaling path: Parameterize joint selection at runtime; expand CSV schema to support multiple joints per frame row or multiple row types.

**Single BLE node:**
- Current capacity: Both `recorder.py` and `sync_recorder.py` connect to exactly one hardcoded device (`TARGET_NAME = "NODE_A1"`).
- Limit: Multi-person or full-body capture (Phase 5+) would require N concurrent BLE connections with N CSV files. The current `State` class is designed for one device.
- Scaling path: Refactor `State` into a per-device instance; run one asyncio task per device; merge results by local timestamp.

---

## Dependencies at Risk

**Pinned to numpy<2 / opencv-python<4.11 combination:**
- Risk: The working dependency set (documented in `DEVLOG.md` problem #10) requires pinning OpenCV below 4.11 to stay on numpy 1.x. This locks out security patches and new features in both libraries.
- Impact: Any `pip install --upgrade` in the project environment will break the install.
- Migration plan: Wait for tensorflow-macos to release a numpy 2.x-compatible build, then upgrade all three packages together. Alternatively, isolate ML inference into a separate venv from the BLE/CV capture pipeline.

**mediapipe 0.10.x tasks API stability:**
- Risk: MediaPipe's tasks API (`mediapipe.tasks.python.vision`) is relatively new and has already had one major breaking API change (removal of `solutions` API). The `pose_landmarker_lite.task` model binary is an external file dependency not tracked by any package manager.
- Impact: If `pose_landmarker_lite.task` is missing or wrong version, the failure is a runtime crash inside `PoseLandmarker.create_from_options()` with a non-obvious error.
- Migration plan: Document the exact model download URL and version in a `README.md` or `requirements.txt` comment. Consider checking for the model file at startup and printing a clear error with download instructions.

---

## Missing Critical Features

**No requirements.txt / setup instructions:**
- Problem: There is no documented way to reproduce the working Python environment. The exact combination that works is buried in `DEVLOG.md` prose, not in any machine-readable file.
- Blocks: Anyone else setting up the project, or the original developer on a new machine, will re-hit the numpy/opencv/mediapipe version conflict from scratch.

**No data validation on CSV load in analyze.py:**
- Problem: `load_imu()` and `load_vision()` in `analyze.py` (lines 24-48) perform direct `float()` and `int()` casts on all CSV values with no error handling. An interrupted recording that produces a truncated or malformed CSV will raise an unhandled `ValueError` with no indication of which file or row is corrupt.
- Blocks: Post-hoc analysis of any partially-written recording set.

**No test coverage:**
- Problem: There are zero test files in the project. Core logic including binary packet parsing (`struct.unpack_from` in `recorder.py:234`), packet-loss estimation (`recorder.py:251-253`), angle calculation (`vision.py:96-110`), IMU tilt calculation (`analyze.py:51-63`), and CSV alignment (`analyze.py:111-138`) have no automated verification.
- Blocks: Confident refactoring or extension of any of the above.
- Priority: High for `calc_angle()` and `calc_imu_tilt()` — these are the scientific outputs of the system.

---

*Concerns audit: 2026-03-22*
