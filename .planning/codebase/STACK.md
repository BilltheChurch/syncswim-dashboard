# Technology Stack

**Analysis Date:** 2026-03-22

## Languages

**Primary:**
- Python 3.10.16 - All host-side data collection, vision processing, and analysis scripts
- C++ (Arduino/ESP32) - Embedded firmware for M5StickC Plus2 hardware node (`test_rec.ino`)

## Runtime

**Environment:**
- macOS (ARM/Apple Silicon) - Development and runtime platform (noted explicitly in `vision.py`: "OpenCV's FFmpeg on macOS ARM can't handle HTTP video capture")

**Package Manager:**
- pip (system Python) - No requirements.txt present; packages installed directly in environment
- Lockfile: Not present

## Frameworks

**Core:**
- asyncio (stdlib) - Async BLE event loop in `recorder.py`, `receive_ble.py`, `scan_ble.py`
- threading (stdlib) - Concurrent BLE + vision threads in `sync_recorder.py`

**Computer Vision:**
- OpenCV 4.10.0 (`cv2`) - Frame capture, image decode, skeleton overlay, display window (`vision.py`, `sync_recorder.py`)
- MediaPipe 0.10.33 - Pose landmark detection using Tasks API with `PoseLandmarker` (`vision.py`, `sync_recorder.py`)

**BLE Communication:**
- bleak - Async BLE client for scanning and connecting to Nordic/ESP32 peripherals (`recorder.py`, `receive_ble.py`, `scan_ble.py`, `sync_recorder.py`)

**Data Analysis:**
- matplotlib 3.10.0 - 3-panel time-series plot generation, PNG export (`analyze.py`)
- numpy 1.26.4 - Array operations, signal smoothing, correlation, interpolation (`analyze.py`, `vision.py`, `sync_recorder.py`)

**Firmware (Arduino):**
- M5StickCPlus2.h - M5Stack device HAL for display, IMU, buttons, power, speaker
- BLEDevice / BLEServer / BLEUtils / BLE2902 - ESP32 BLE stack (notify characteristic)
- M5Canvas - Double-buffered sprite rendering for flicker-free display

## Key Dependencies

**Critical:**
- `bleak` - Sole BLE transport layer; all IMU data flows through it. Version unknown (not in lockfile).
- `mediapipe` 0.10.33 - Uses new Tasks API (`mediapipe.tasks.python.vision.PoseLandmarker`), not legacy API. Model file `pose_landmarker_lite.task` must be present at project root.
- `opencv-python` 4.10.0 - Used as `cv2`; HTTP video capture is bypassed in favor of manual MJPEG parsing due to macOS ARM limitation.
- `numpy` 1.26.4 - Used across vision, sync recorder, and analysis scripts.
- `matplotlib` 3.10.0 - Required only for `analyze.py`.

**Infrastructure:**
- `urllib.request` (stdlib) - Manual MJPEG stream reading from DroidCam IP camera (`vision.py`, `sync_recorder.py`)
- `struct` (stdlib) - Binary packet unpacking from BLE notifications (`recorder.py`, `sync_recorder.py`)
- `csv` (stdlib) - All data persistence; no database used

## Configuration

**Environment:**
- No `.env` files or environment variables used
- Configuration is hardcoded at the top of each script as constants:
  - `TARGET_NAME = "NODE_A1"` - BLE device name
  - `CHAR_UUID = "abcd1234-ab12-cd34-ef56-abcdef123456"` - BLE characteristic UUID
  - `CAMERA_URL = "http://192.168.66.169:4747/video"` - DroidCam MJPEG stream URL (IP hardcoded)
  - `DATA_DIR = "data"` - Output directory for CSV files
  - BLE protocol constants: `HEADER_SIZE=4`, `READING_SIZE=16`, `READING_FMT='<Ihhhhhh'`

**Build:**
- No build system for Python scripts; run directly with `python3`
- Arduino firmware: compiled and flashed via Arduino IDE or PlatformIO (no build config files present in repo)
- MediaPipe model: `pose_landmarker_lite.task` binary file must exist at project root (present in repo)

## Platform Requirements

**Development:**
- macOS (ARM tested; HTTP video capture workaround is macOS ARM-specific)
- Python 3.10+
- Bluetooth hardware enabled
- WiFi connectivity (same network as DroidCam phone)
- Required packages: `bleak`, `opencv-python`, `mediapipe`, `matplotlib`, `numpy`

**Production:**
- Same as development — scripts run directly on the recording laptop
- No deployment infrastructure; this is a local data collection tool
- Hardware: M5StickC Plus2 flashed with `test_rec.ino`, iOS/Android phone running DroidCam

---

*Stack analysis: 2026-03-22*
