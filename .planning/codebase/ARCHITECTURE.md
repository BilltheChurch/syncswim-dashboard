# Architecture

**Analysis Date:** 2026-03-22

## Pattern Overview

**Overall:** Multi-phase pipeline — hardware firmware → wireless transport → host-side Python scripts → offline analysis. Each phase is a standalone script that builds on the previous. There is no framework, web server, or persistent process manager; each Python file is a self-contained runnable program.

**Key Characteristics:**
- Firmware (C++/Arduino) runs on M5StickC Plus2 hardware; Python scripts run on macOS host
- BLE is the transport layer between hardware and host (one-way: device notifies host)
- All coordination state is held in a single shared-state object per script, protected by `threading.Lock`
- Recording is triggered by a physical button on the hardware device; the host software reacts to state signals embedded in BLE packets
- Timestamps are Unix wall-clock (`time.time()`) applied on the host side; device timestamps are milliseconds-since-boot used for gap detection only
- Data lands in CSV files organised by set directory; no database

## Layers

**Firmware Layer:**
- Purpose: Reads IMU sensor, manages recording state, transmits over BLE
- Location: `test_rec.ino`
- Contains: BLE server setup, IMU polling loop, batch packet builder, display rendering
- Depends on: M5StickCPlus2, BLEDevice, MPU6886 IMU (built-in)
- Used by: All Python host scripts via BLE notification characteristic

**BLE Transport Layer:**
- Purpose: Delivers binary-packed IMU batch packets from device to host at ~72 Hz
- Protocol: 4-byte header `[state(u8), set_number(u8), count(u8), reserved(u8)]` + N × 16-byte `IMUReading` structs (`uint32 timestamp + 6 × int16`)
- Characteristic UUID: `abcd1234-ab12-cd34-ef56-abcdef123456`
- Service UUID: `12345678-1234-1234-1234-123456789abc`
- Used by: `recorder.py`, `sync_recorder.py`, `receive_ble.py`

**Host Utility Scripts (diagnostic):**
- Purpose: One-shot tools for discovery and raw protocol inspection
- Location: `scan_ble.py`, `receive_ble.py`
- Contains: BLE scanner, raw CSV-text callback printer (legacy UTF-8 protocol, pre-dates binary format)
- Depends on: `bleak`

**Phase 1 — BLE Recorder:**
- Purpose: Receives IMU data over BLE and saves to CSV; no vision
- Location: `recorder.py`
- Contains: `State` class (shared state), `handle_notification()` (BLE callback), `connect_loop()` (async reconnect loop), terminal dashboard renderer
- Depends on: `bleak`, Python stdlib (`asyncio`, `csv`, `struct`, `threading`, `signal`)
- Used by: Standalone, or superseded by `sync_recorder.py`

**Phase 2 — Vision Pipeline:**
- Purpose: Reads IP camera MJPEG stream, runs MediaPipe pose estimation, outputs per-frame joint angle to CSV
- Location: `vision.py`
- Contains: `MjpegStreamReader` class (daemon thread MJPEG parser), `calc_angle()`, `draw_status_bar()`, recording loop
- Depends on: `cv2` (OpenCV), `mediapipe`, `numpy`, `pose_landmarker_lite.task` model file
- Used by: Standalone, or superseded by `sync_recorder.py`

**Phase 3 — Synchronized Recorder:**
- Purpose: Combines BLE IMU and vision pipelines; device Button A starts/stops both simultaneously
- Location: `sync_recorder.py`
- Contains: `SyncState` class, `handle_ble_notification()`, `ble_thread_func()` (runs asyncio BLE loop in a background thread), `MjpegStreamReader` class (duplicate of `vision.py`), `draw_osd()`, main vision loop
- Depends on: `bleak`, `cv2`, `mediapipe`, `numpy`, `pose_landmarker_lite.task`
- Used by: Primary recording entrypoint

**Phase 4 — Offline Analysis:**
- Purpose: Reads a completed set's CSVs, aligns by local timestamp, plots IMU tilt vs MediaPipe elbow angle, computes correlation
- Location: `analyze.py`
- Contains: `load_imu()`, `load_vision()`, `calc_imu_tilt()`, `smooth()`, `find_set_dir()`
- Depends on: `matplotlib`, `numpy`, Python stdlib (`csv`, `math`)

## Data Flow

**IMU Recording Flow (sync_recorder.py):**

1. M5StickC Plus2 reads MPU6886 IMU every 10 ms; buffers 3 readings
2. BLE notification sent as 52-byte binary packet when batch is full
3. `handle_ble_notification()` callback fires on BLE thread (bleak asyncio event loop running in daemon thread via `ble_thread_func`)
4. Callback acquires `state.lock`, detects REC/IDLE state change, opens/closes CSV files accordingly
5. Each reading is unpacked (`struct.unpack_from`), scaled (ax÷1000, gx÷10), written to `imu_NODE_A1.csv`
6. Main thread runs vision loop: reads MJPEG frame from `MjpegStreamReader` daemon thread, runs MediaPipe `PoseLandmarker.detect()`, writes per-frame angle to `vision.csv`
7. Both streams use `time.time()` local timestamps; alignment is post-hoc via timestamp interpolation

**Vision-Only Flow (vision.py):**

1. `MjpegStreamReader` daemon thread reads JPEG boundaries from HTTP MJPEG stream into `self.frame`
2. Main loop calls `cam.read()`, applies rotation, converts BGR→RGB, runs MediaPipe detection
3. If joints visible, `calc_angle(shoulder, elbow, wrist)` computes dot-product angle
4. Skeleton and angle drawn on frame with OpenCV; frame displayed via `cv2.imshow`
5. On key `R`: opens CSV in `data/set_NNN_TIMESTAMP/vision.csv`; writes one row per frame

**Analysis Flow (analyze.py):**

1. `find_set_dir()` locates latest set directory containing both `imu_NODE_A1.csv` and `vision.csv`
2. Both CSVs loaded with `csv.DictReader`, timestamps normalised to a common t=0
3. IMU tilt angle computed per row via `atan2(ax, sqrt(ay²+az²))`; smoothed with 15-point moving average
4. Vision angles filtered to visible-only frames (NaN for invisible)
5. IMU resampled onto vision timestamps via `np.interp`; Pearson correlation computed
6. Three-panel matplotlib figure saved as `analysis.png` in the set directory

**State Management:**
- Each script holds a single module-level state instance (`state = State()` or `state = SyncState()`)
- `threading.Lock` (`state.lock`) guards all mutable fields accessed from both BLE callback thread and main/vision thread
- Recording state transitions (IDLE→REC, REC→IDLE) are detected inside the BLE callback by comparing `dev_state` from packet header against `state.recording`
- CSV file handles are stored on the state object; opened/closed atomically inside the lock

## Key Abstractions

**State Object (`State` / `SyncState`):**
- Purpose: Single shared mutable context for connection status, recording flag, set number, packet counters, CSV handles, and display data
- Examples: `recorder.py` line 39 (`class State`), `sync_recorder.py` line 48 (`class SyncState`)
- Pattern: Plain class with `threading.Lock`; no properties or encapsulation — fields accessed directly

**MjpegStreamReader:**
- Purpose: Background daemon thread that continuously reads MJPEG HTTP stream and exposes latest frame via `read()` method; required because OpenCV's `VideoCapture` cannot handle HTTP streams on macOS ARM
- Examples: `vision.py` line 44, `sync_recorder.py` line 231 (duplicated implementation)
- Pattern: Thread-per-reader with internal `threading.Lock` on `self.frame`

**BLE Notification Callback (`handle_notification` / `handle_ble_notification`):**
- Purpose: Parses binary batch packets, drives REC/IDLE state machine, writes CSV rows
- Examples: `recorder.py` line 202, `sync_recorder.py` line 129
- Pattern: Synchronous callback called by bleak's asyncio loop; acquires `state.lock` for the entire packet

**Set Directory:**
- Purpose: Atomic unit of a recording session; named `set_NNN_YYYYMMDD_HHMMSS`, contains all CSVs for that recording
- Examples: `data/set_002_20260319_165319/`
- Contains: `imu_NODE_A1.csv`, `vision.csv`, optionally `analysis.png`

## Entry Points

**`recorder.py`:**
- Location: `/Users/billthechurch/Downloads/test_rec/recorder.py`
- Triggers: `python3 recorder.py` — BLE-only recording
- Responsibilities: Scan → connect → stream → auto-segment by device state → write IMU CSV → display terminal dashboard

**`vision.py`:**
- Location: `/Users/billthechurch/Downloads/test_rec/vision.py`
- Triggers: `python3 vision.py` — camera-only recording
- Responsibilities: Open MJPEG stream → detect pose → display skeleton overlay → write vision CSV on keypress

**`sync_recorder.py`:**
- Location: `/Users/billthechurch/Downloads/test_rec/sync_recorder.py`
- Triggers: `python3 sync_recorder.py` — primary dual-source recording
- Responsibilities: Spawn BLE daemon thread + MJPEG reader thread → synchronise recording start/stop via device button → write both CSVs to same set directory

**`analyze.py`:**
- Location: `/Users/billthechurch/Downloads/test_rec/analyze.py`
- Triggers: `python3 analyze.py [set_dir]` — post-hoc analysis
- Responsibilities: Load CSVs → compute IMU tilt angle → align with vision → plot and save `analysis.png`

**`scan_ble.py`:**
- Location: `/Users/billthechurch/Downloads/test_rec/scan_ble.py`
- Triggers: `python3 scan_ble.py` — diagnostic only
- Responsibilities: 5-second BLE scan, print NODE devices found

**`receive_ble.py`:**
- Location: `/Users/billthechurch/Downloads/test_rec/receive_ble.py`
- Triggers: `python3 receive_ble.py` — diagnostic only, legacy protocol
- Responsibilities: Connect to NODE_A1, print raw CSV-text packets for 30 seconds

**`test_rec.ino`:**
- Location: `/Users/billthechurch/Downloads/test_rec/test_rec.ino`
- Triggers: Flash to M5StickC Plus2 via Arduino IDE
- Responsibilities: Read MPU6886 IMU, batch into BLE notifications, manage recording state via Button A, render display

## Error Handling

**Strategy:** Best-effort with silent recovery. Scripts do not crash on transient errors; they log to the terminal and retry.

**Patterns:**
- BLE connection failures: caught by bare `except Exception` in `connect_loop()`/`ble_loop()`; reconnect after 3-second sleep
- Camera disconnection: `MjpegStreamReader._reader()` catches all exceptions, sleeps 1 second, and retries
- Incomplete BLE packets: early `return` if `len(data) < HEADER_SIZE` or insufficient payload bytes
- CSV flush: periodic flush every 100 IMU packets or 30 vision frames to limit data loss on crash
- Disconnection while recording: `finally` block in connect loop closes CSV if `state.recording` is True
- `analyze.py`: explicit error message and early return if set directory or files not found; no exception handling around CSV parsing

## Cross-Cutting Concerns

**Logging:** `print()` to stdout only; no logging framework. `recorder.py` uses an ANSI terminal dashboard instead of print lines.

**Validation:** None — BLE packet length checked before unpacking; no schema validation on CSV load in `analyze.py`.

**Authentication:** Not applicable — BLE device is identified by advertised name (`NODE_A1`); no pairing or authentication.

**Concurrency Model:**
- `recorder.py`: single asyncio event loop; BLE callback runs in the loop; display refresh runs in the loop
- `sync_recorder.py`: BLE asyncio loop runs in a daemon thread (`ble_thread_func`); MJPEG reader runs in a daemon thread; main thread runs vision/display loop; all share `SyncState` via `threading.Lock`
- `vision.py`: MJPEG reader in daemon thread; everything else in main thread

---

*Architecture analysis: 2026-03-22*
