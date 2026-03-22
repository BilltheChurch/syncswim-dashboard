# Coding Conventions

**Analysis Date:** 2026-03-22

## Languages

This is a mixed-language project:
- **Python** (primary): `recorder.py`, `vision.py`, `sync_recorder.py`, `analyze.py`, `scan_ble.py`, `receive_ble.py`
- **C++ / Arduino**: `test_rec.ino` (M5StickC Plus2 firmware)

---

## Naming Patterns

**Files:**
- `snake_case.py` for all Python scripts: `sync_recorder.py`, `scan_ble.py`, `receive_ble.py`
- Descriptive names reflecting purpose: `recorder.py` (BLE+CSV), `vision.py` (camera pipeline), `analyze.py` (data analysis)
- Firmware: single `.ino` file named after the project: `test_rec.ino`

**Functions:**
- `snake_case` for all Python functions: `calc_angle()`, `start_csv()`, `draw_status_bar()`, `find_set_dir()`
- Verb-noun pattern for actions: `start_csv()`, `stop_csv()`, `start_recording()`, `stop_recording()`, `render_display()`
- Private methods prefixed with underscore: `_reader()`, `_signal_handler()`, `_rate_window`
- Async functions follow same naming — no `async_` prefix: `connect_loop()`, `ble_loop()`

**Variables:**
- `snake_case` for local variables: `local_ts`, `set_number`, `fps_timer`, `fps_counter`
- Short descriptive aliases in tight loops: `ax`, `ay`, `az`, `gx`, `gy`, `gz`, `lm`, `p`
- Loop index variables: `i`, `r`, `d`, `f`

**Constants:**
- `SCREAMING_SNAKE_CASE` for all module-level constants:
  ```python
  TARGET_NAME = "NODE_A1"
  CHAR_UUID = "abcd1234-ab12-cd34-ef56-abcdef123456"
  EXPECTED_INTERVAL_MS = 12
  LOSS_THRESHOLD_MS = 100
  HEADER_SIZE = 4
  READING_SIZE = 16
  ```
- ANSI terminal codes are also `SCREAMING_SNAKE_CASE`: `RESET`, `BOLD`, `RED`, `GREEN`, `CLEAR_SCREEN`

**Classes:**
- `PascalCase`: `State`, `SyncState`, `MjpegStreamReader`
- C++/Arduino: `PascalCase` for classes, `camelCase` for member functions: `MyServerCallbacks`, `drawStatusBar()`, `drawRecBar()`
- C++ structs use `PascalCase`: `IMUReading`

**C++ / Arduino specifics:**
- `#define` constants in `SCREAMING_SNAKE_CASE`: `NODE_NAME`, `SERVICE_UUID`, `BATCH_SIZE`, `IMU_INTERVAL_MS`
- Global variables in `camelCase`: `deviceConnected`, `setNumber`, `recStartTime`, `loopCount`
- Functions in `camelCase`: `drawStatusBar()`, `drawIMUData()`, `drawRecBar()`

---

## Code Style

**Formatting:**
- No linting/formatting config files present (no `.flake8`, `.pylintrc`, `pyproject.toml`, `setup.cfg`)
- Consistent 4-space indentation throughout all Python files
- Blank lines used to separate logical sections within functions
- No trailing commas in function argument lists
- Long strings broken across lines with implicit concatenation or `f`-strings

**Line length:**
- Not strictly enforced; some lines exceed 88 chars (especially `f`-string renders in `recorder.py`)

**String formatting:**
- `f`-strings used exclusively for interpolation (no `%` or `.format()`):
  ```python
  f"set_{set_number:03d}_{timestamp}"
  f"{ax:.3f}"
  f"  Saving to: {state.set_dir}/"
  ```
- Format specifiers used for numeric alignment: `{state.current_rate:5.0f}`, `{mins:02d}:{secs:02d}`

---

## Module Structure Pattern

Each Python script follows the same top-level layout:

1. Module docstring (multi-line, describes purpose and features)
2. Standard library imports
3. Third-party imports
4. Module-level constants block (under `# ─── Config ───` section header)
5. Shared state (class or module-level variables)
6. Helper functions grouped by concern under section headers
7. `main()` function
8. `if __name__ == "__main__":` guard

**Section headers use a consistent ASCII box style:**
```python
# ─── Config ───────────────────────────────────────────────
# ─── Shared State ─────────────────────────────────────────
# ─── CSV Management ───────────────────────────────────────
# ─── Terminal Display ─────────────────────────────────────
# ─── BLE Data Handler ─────────────────────────────────────
# ─── Main ─────────────────────────────────────────────────
```

---

## Import Organization

**Order:**
1. Standard library imports (alphabetical): `asyncio`, `csv`, `math`, `os`, `signal`, `struct`, `sys`, `time`, `threading`, `urllib.request`
2. Third-party imports (alphabetical): `cv2`, `mediapipe`, `numpy`, `bleak`
3. Deferred imports inside functions when optional or to avoid circular loading:
   ```python
   # Inside main() in vision.py and sync_recorder.py:
   from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode
   from mediapipe.tasks.python import BaseOptions
   ```

---

## Docstrings

**Module docstrings:** Multi-line at top of every main script; describe purpose and key features:
```python
"""
NODE_A1 BLE Recorder - Phase 1
Single device BLE IMU data collection pipeline.

Features:
- BLE data reception at ~86Hz
- Auto-segmentation by REC/IDLE state
...
"""
```

**Function docstrings:** Single-line for most helpers; multi-line only for algorithms with non-obvious behavior:
```python
def calc_rate(self):
    """Calculate packets/sec from sliding window."""

def calc_imu_tilt(imu_data):
    """
    Compute forearm tilt angle from accelerometer.
    Uses pitch = atan2(ax, sqrt(ay^2 + az^2)) converted to degrees.
    Then maps to 0-180 range to visually compare with elbow angle.
    """
```

**Not all functions have docstrings:** `sync_recorder.py` omits docstrings on most helpers (e.g., `start_recording()`, `stop_recording()`, `handle_ble_notification()`, `calc_angle()`). `recorder.py` is more consistently documented.

---

## Error Handling

**Strategy:** Broad `except Exception` at connection/IO boundaries; no custom exception types.

**Patterns:**

1. **BLE connection loop** — catch-all with message display, then auto-retry:
   ```python
   # recorder.py:329
   except Exception as e:
       set_status(f"Error: {e}")
       render_with_status()
   ```

2. **Background thread catch-all** — silent swallow, set flag, retry:
   ```python
   # sync_recorder.py:216, vision.py:79
   except Exception:
       self.connected = False
       time.sleep(1)
   ```
   (Note: `sync_recorder.py` BLE loop also silently swallows all exceptions with bare `except Exception: pass`)

3. **User interrupt** — `KeyboardInterrupt` caught separately, triggers cleanup via `finally`:
   ```python
   except KeyboardInterrupt:
       pass
   finally:
       if csv_file:
           csv_file.close()
       landmarker.close()
       cap.release()
       cv2.destroyAllWindows()
   ```

4. **Guard clauses** for invalid/short data (return early):
   ```python
   if len(data) < HEADER_SIZE:
       return
   if len(data) < HEADER_SIZE + count * READING_SIZE:
       return
   ```

5. **Arithmetic safety** — zero-division guard before computation:
   ```python
   if mag_ba == 0 or mag_bc == 0:
       return 0.0
   ```

**No use of:** logging module, custom exceptions, typed errors, or error propagation chains.

---

## State Management

**Pattern:** Shared mutable state class with `threading.Lock()` for thread-safe access.

```python
# recorder.py
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.connected = False
        self.recording = False
        ...

state = State()  # module-level singleton

# Usage
with state.lock:
    if is_rec and not state.recording:
        state.recording = True
        ...
```

`SyncState` in `sync_recorder.py` follows the same pattern for the dual-source recorder.

---

## Comments

**Inline comments:** Used freely to explain protocol details, magic numbers, and non-obvious logic:
```python
READING_FMT = '<Ihhhhhh'   # little-endian: uint32 + 6 × int16
# Keep last 2 seconds of timestamps
# Binary protocol: 4-byte header + N × 16-byte readings
```

**Section comments in long functions** — sub-headings with `# ──` style:
```python
# ── State transition: IDLE → REC ──
# ── State transition: REC → IDLE ──
# ── Process each reading in the batch ──
```

**No type annotations** anywhere in Python code (no `->`, no `param: type`).

---

## CSV Output Conventions

All CSV files use consistent column naming and formatting:

**IMU CSV** (`imu_NODE_A1.csv`):
```
timestamp_local, timestamp_device, node, state, set, ax, ay, az, gx, gy, gz
```
- `timestamp_local`: `f"{local_ts:.6f}"` (Unix epoch, 6 decimal places)
- Accel: `f"{ax:.3f}"` (3 decimal places, g units)
- Gyro: `f"{gx:.1f}"` (1 decimal place, deg/s)

**Vision CSV** (`vision.csv`):
```
timestamp_local, frame, joint, angle_deg, visible, fps
```
- `timestamp_local`: same format as IMU
- `angle_deg`: `f"{angle:.2f}"`

---

## Function Design

**Size:** Most functions are 10-30 lines. `handle_notification()` and `main()` are the longest (~50 lines each).

**Parameters:** Minimal — functions mostly access module-level `state` object directly rather than accepting it as a parameter.

**Return values:** Functions either return a value or mutate `state`; rarely both. Guard-clause returns use `None`/`(None, 0, 0)` tuples for failure:
```python
def stop_csv():
    if state.csv_file:
        ...
        return state.set_filepath, state.set_packet_count, size
    return None, 0, 0
```

---

*Convention analysis: 2026-03-22*
