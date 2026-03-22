# Testing Patterns

**Analysis Date:** 2026-03-22

## Test Framework

**Runner:** None — no automated test framework is present.

- No `pytest`, `unittest`, `nose2`, or any other test runner is configured.
- No test files exist (`test_*.py`, `*_test.py` patterns yield no results).
- No `pytest.ini`, `setup.cfg`, `tox.ini`, or `pyproject.toml` configuration files.
- No `requirements.txt` or dependency manifest of any kind.

**Assertion Library:** Not applicable.

**Run Commands:** Not applicable — no test suite to run.

---

## Current Verification Approach

All validation is manual and runtime-based. The project documents its verification in `task.md` as acceptance criteria per phase:

- **Phase 1 (BLE):** `72.5Hz / 0% packet loss / 0% duplicates / max gap 23ms` — verified by running `recorder.py` against live hardware and observing terminal dashboard.
- **Phase 2 (Vision):** `~26 FPS / full skeleton detection / microsecond timestamps` — verified by running `vision.py` with DroidCam and observing OpenCV window overlay.
- **Phase 3 (Sync):** `start offset 8.8ms / duration diff 17.6ms` — verified by running `sync_recorder.py` and inspecting CSV output.
- **Phase 4 (Analysis):** `correlation coefficient -0.497` — verified by running `analyze.py` and inspecting the generated `analysis.png` plot.

---

## Test File Organization

**Location:** No test directory exists. No co-located test files exist alongside source files.

**Naming:** No convention established (no test files present).

---

## What Would Be Tested (If Tests Were Added)

Based on the codebase structure, the following units are the most testable in isolation:

**Pure computation functions (highest priority — no I/O dependencies):**

- `calc_angle(a, b, c)` in `vision.py` and `sync_recorder.py`
  - File: `/Users/billthechurch/Downloads/test_rec/vision.py:96`
  - File: `/Users/billthechurch/Downloads/test_rec/sync_recorder.py:276`
  - Takes three `(x, y)` tuples, returns float degrees. Fully deterministic.

- `calc_imu_tilt(imu_data)` in `analyze.py`
  - File: `/Users/billthechurch/Downloads/test_rec/analyze.py:51`
  - Converts list of dicts with `ax/ay/az` keys to numpy array of pitch angles.

- `smooth(data, window)` in `analyze.py`
  - File: `/Users/billthechurch/Downloads/test_rec/analyze.py:66`
  - Moving average over numpy array. Edge case: `len(data) < window`.

- `State.calc_rate()` in `recorder.py`
  - File: `/Users/billthechurch/Downloads/test_rec/recorder.py:61`
  - Sliding window rate calculation. Can be tested with mocked `time.time`.

**CSV parsing functions (medium priority — file I/O):**

- `load_imu(filepath)` in `analyze.py`
  - File: `/Users/billthechurch/Downloads/test_rec/analyze.py:24`
  - Reads CSV, returns list of dicts with float-coerced fields.

- `load_vision(filepath)` in `analyze.py`
  - File: `/Users/billthechurch/Downloads/test_rec/analyze.py:39`
  - Same pattern as `load_imu`.

**Directory/file management (lower priority — filesystem I/O):**

- `find_set_dir(arg)` in `analyze.py`
  - File: `/Users/billthechurch/Downloads/test_rec/analyze.py:74`
  - Finds latest set directory with both CSVs present.

- `start_csv(set_number)` / `stop_csv()` in `recorder.py`
  - File: `/Users/billthechurch/Downloads/test_rec/recorder.py:83`

---

## Mocking Requirements (If Tests Were Added)

**Framework:** `unittest.mock` (stdlib) would be appropriate given no test infra exists.

**What to mock for unit tests:**

- `time.time` — needed for `calc_rate()` and any timestamp-based logic
- `threading.Lock` — for state mutation tests
- File I/O (`open`, `csv.writer`) — for CSV management functions
- `os.makedirs`, `os.path.exists` — for directory management

**What NOT to mock:**
- `calc_angle()`, `calc_imu_tilt()`, `smooth()` — pure math, no mocking needed
- NumPy operations — use real numpy in tests

**BLE/Camera dependencies (require hardware or integration test setup):**
- `bleak.BleakScanner`, `bleak.BleakClient` — require real BLE hardware or complex async mocks
- `MjpegStreamReader` — requires live HTTP stream or mock socket
- MediaPipe `PoseLandmarker` — requires model file `pose_landmarker_lite.task` at `/Users/billthechurch/Downloads/test_rec/pose_landmarker_lite.task`

---

## Test Types

**Unit Tests:** Not present. Pure functions (`calc_angle`, `smooth`, `calc_imu_tilt`) are the natural starting points.

**Integration Tests:** Not present. Would require real hardware (M5StickC Plus2 BLE device) or DroidCam stream.

**E2E Tests:** Not present. Manual only — run full pipeline and inspect CSV/plot output.

---

## Coverage

**Requirements:** None enforced.

**Current coverage:** 0% (no automated tests).

**Highest-risk untested paths:**
- Binary packet parsing in `handle_notification()` — `recorder.py:202` and `handle_ble_notification()` — `sync_recorder.py:129`. Malformed packets or unexpected lengths silently return early.
- State transition logic (IDLE → REC → IDLE) inside the BLE notification callback — tested only by pressing Button A on physical hardware.
- MJPEG frame boundary detection (`\xff\xd8` / `\xff\xd9`) in `MjpegStreamReader._reader()` — `vision.py:57`, `sync_recorder.py:241`.

---

## Recommended Test Setup (If Introducing Tests)

Install pytest as the de-facto standard for Python projects:

```bash
pip install pytest
```

Suggested file layout:
```
test_rec/
├── tests/
│   ├── test_angle.py        # calc_angle() unit tests
│   ├── test_imu_tilt.py     # calc_imu_tilt(), smooth()
│   ├── test_csv_loading.py  # load_imu(), load_vision()
│   └── conftest.py          # shared fixtures (sample CSV files, mock state)
```

Example test pattern for `calc_angle`:
```python
# tests/test_angle.py
import pytest
from vision import calc_angle

def test_straight_arm_180_degrees():
    a = (0, 0)
    b = (1, 0)
    c = (2, 0)
    assert abs(calc_angle(a, b, c) - 180.0) < 0.01

def test_right_angle_90_degrees():
    a = (0, 0)
    b = (1, 0)
    c = (1, 1)
    assert abs(calc_angle(a, b, c) - 90.0) < 0.01

def test_zero_vector_returns_zero():
    a = (1, 0)
    b = (1, 0)  # same as a → zero vector
    c = (2, 0)
    assert calc_angle(a, b, c) == 0.0
```

---

*Testing analysis: 2026-03-22*
