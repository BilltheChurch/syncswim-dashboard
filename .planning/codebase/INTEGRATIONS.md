# External Integrations

**Analysis Date:** 2026-03-22

## APIs & External Services

**IP Camera (DroidCam):**
- DroidCam app (iOS/Android) - Streams live video from phone camera as MJPEG over HTTP
  - Stream URL: `http://192.168.66.169:4747/video` (hardcoded in `vision.py` and `sync_recorder.py`)
  - Protocol: MJPEG over HTTP; OpenCV's `VideoCapture` is bypassed due to macOS ARM limitation
  - Client: Custom `MjpegStreamReader` class using `urllib.request` + manual JPEG boundary parsing (`\xff\xd8` / `\xff\xd9`)
  - Auth: None — open HTTP stream on local WiFi network

**Google MediaPipe:**
- MediaPipe Pose Landmarker (Tasks API) - On-device ML pose estimation; no network call at inference time
  - SDK: `mediapipe` 0.10.33 (`mediapipe.tasks.python.vision`)
  - Model file: `pose_landmarker_lite.task` (binary, present at project root; loaded via `BaseOptions(model_asset_path=...)`)
  - Used in: `vision.py`, `sync_recorder.py`
  - Auth: None

## Data Storage

**Databases:**
- None — no database used anywhere in the codebase

**File Storage:**
- Local filesystem only
  - Output directory: `data/` relative to script working directory
  - Per-set subdirectory naming: `set_{NNN}_{YYYYMMDD_HHMMSS}/`
  - IMU data: `imu_NODE_A1.csv` — columns: `timestamp_local, timestamp_device, node, state, set, ax, ay, az, gx, gy, gz`
  - Vision data: `vision.csv` — columns: `timestamp_local, frame, joint, angle_deg, visible, fps`
  - Analysis output: `analysis.png` (matplotlib figure, 150 DPI)
  - CSV files written incrementally with periodic `flush()` every 100 IMU packets or 30 vision frames

**Caching:**
- None

## Authentication & Identity

**Auth Provider:**
- None — no user authentication, sessions, or identity management

## Monitoring & Observability

**Error Tracking:**
- None — no external error tracking

**Logs:**
- Terminal stdout only; `recorder.py` uses ANSI escape codes for a live dashboard (cursor control, color codes)
- `sync_recorder.py` uses OpenCV `imshow` window with on-screen display (OSD) overlay for live status
- No structured logging, no log files written to disk

## Hardware Integration

**BLE Device (M5StickC Plus2 — NODE_A1):**
- Protocol: Bluetooth Low Energy (BLE) notify characteristic
- Service UUID: `12345678-1234-1234-1234-123456789abc`
- Characteristic UUID: `abcd1234-ab12-cd34-ef56-abcdef123456`
- Transport: Binary batch packets — 4-byte header + 3 × 16-byte IMU readings per notification
- Packet format: `[state:u8, set_number:u8, count:u8, reserved:u8]` + `[timestamp:u32, ax:i16, ay:i16, az:i16, gx:i16, gy:i16, gz:i16]` × 3
- IMU sensor: MPU6886 (built into M5StickC Plus2), sampled at ~72.5 Hz
- Python client: `bleak` library (`BleakScanner`, `BleakClient`) — used in `recorder.py`, `sync_recorder.py`, `receive_ble.py`, `scan_ble.py`
- Auto-reconnect: implemented in `recorder.py` and `sync_recorder.py` with 3-second retry delay
- Recording trigger: Button A on hardware device toggles REC/IDLE state, encoded in BLE packet header byte 0

## CI/CD & Deployment

**Hosting:**
- Not applicable — local desktop tool, no server deployment

**CI Pipeline:**
- None

## Environment Configuration

**Required env vars:**
- None — all configuration is hardcoded as constants in each script

**Secrets location:**
- Not applicable — no secrets, API keys, or credentials used

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None — system is entirely local; no network calls leave the machine except to the DroidCam stream on the LAN

---

*Integration audit: 2026-03-22*
