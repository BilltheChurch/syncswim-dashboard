# Phase 1: Foundation & Environment - Research

**Researched:** 2026-03-22
**Domain:** Python environment setup, Streamlit multipage app skeleton, CSV data loading, TOML configuration
**Confidence:** HIGH

## Summary

Phase 1 establishes the entire foundation: upgrading from Python 3.10 to 3.12, creating a clean virtual environment with pinned dependencies, building the Streamlit multipage app skeleton with 5 views grouped into 3 pages, implementing CSV data loading with a sessions.json index, extracting shared analysis code from existing scripts into a reusable `core/` module, and creating a TOML-based configuration system with in-dashboard editing.

The critical insight is that MediaPipe 0.10.33 does NOT depend on tensorflow -- its only dependencies are `absl-py`, `numpy`, `sounddevice`, `flatbuffers`, `opencv-contrib-python`, and `matplotlib`. This means dropping `tensorflow-macos` is safe and unblocks numpy 2.x, scipy 1.15+, and all modern packages. The Python 3.12 upgrade path is clear. The second critical finding is that `opencv-contrib-python` (required by mediapipe) and `opencv-python` conflict -- only `opencv-contrib-python` should be installed.

**Primary recommendation:** Create a fresh Python 3.12 venv, install `opencv-contrib-python` (NOT `opencv-python`), and use `tomllib` (stdlib) for reading config + `tomli-w` for writing config back. Build the app with `st.navigation()` + `st.Page()` using the explicit routing pattern, not the deprecated `pages/` directory convention.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Dashboard code lives in `dashboard/` subdirectory -- clean separation from existing recorder/analyze scripts
- Multi-page app: `dashboard/app.py` as entry point, `dashboard/pages/` for page files
- Computation logic in `dashboard/core/`, reusable chart builders in `dashboard/components/`
- 5 views grouped into 3 Streamlit pages by workflow:
  - `pages/training.py` -- Live Monitor (View 1) + Set Report (View 2)
  - `pages/analysis.py` -- Progress Tracking (View 3) + AI Analysis (View 4)
  - `pages/team.py` -- Team Synchronization (View 5)
- Extract core math functions from `analyze.py` into shared `core/` module: `calc_imu_tilt()`, `calc_angle()`, `smooth()`, correlation computation
- Both `analyze.py` (existing CLI) and dashboard import from the same shared module
- Existing scripts must continue working after extraction (backward compatible imports)
- Use `venv`: `python3.12 -m venv .venv`
- Drop `tensorflow-macos` dependency -- MediaPipe 0.10.33 on Python 3.12 doesn't require it
- Generate `requirements.txt` with pinned versions for reproducibility
- Build a `sessions.json` index file with set metadata (set#, date, time, duration, sample count, has_vision, has_imu)
- Index auto-rebuilds on dashboard startup if stale (new sets detected)
- Use pandas DataFrames for data loading
- Graceful degradation: show partial data + yellow warning badge when CSV missing/corrupted
- TOML format (`config.toml`) -- Python 3.12 has built-in `tomllib`, human-readable
- Stores: FINA thresholds, hardware config (camera URL, BLE UUIDs, device names), dashboard preferences
- Dashboard settings page in sidebar -- edit FINA thresholds and hardware config from within UI
- Settings page writes back to `config.toml` so changes persist across restarts

### Claude's Discretion
- Whether to also extract `MjpegStreamReader` and BLE protocol parsing now vs. deferring to Phase 5/6
- Claude decides based on code coupling analysis and phase dependency needs

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-01 | Streamlit multi-page app skeleton with 5 views + sidebar navigation | `st.navigation()` + `st.Page()` API verified (Streamlit 1.55.0); 3-page grouping pattern with `position="sidebar"` documented |
| INFRA-02 | Coach/athlete view toggle via sidebar switch (UI-only, no auth) | `st.sidebar.selectbox` or `st.sidebar.toggle` stores role in `st.session_state["role"]`; pages conditionally shown via `visibility` param on `st.Page()` |
| INFRA-03 | CSV data loading layer -- scan data/ directory, parse set metadata from filenames | pandas `read_csv` for data loading; `sessions.json` index pattern with auto-rebuild on stale detection; existing CSV schemas documented (IMU: 11 columns, Vision: 6 columns) |
| INFRA-04 | Session/set selector -- dropdown to pick which recording to analyze | `st.sidebar.selectbox` populated from `sessions.json` index; selection stored in `st.session_state["selected_set"]`; `@st.cache_data(ttl=60)` for CSV loading |
| INFRA-05 | Python 3.12 environment upgrade + requirements.txt with pinned versions | Full dependency tree verified: mediapipe 0.10.33 has NO tensorflow dependency; numpy 2.2.6, scipy 1.15.3, opencv-contrib-python 4.10+ all support Python 3.12; version pins documented |
| INFRA-06 | Configuration module -- FINA thresholds, camera URL, BLE UUIDs as editable config | `tomllib` (stdlib, read-only) + `tomli-w` 1.2.0 (write); `config.toml` structure designed; settings page pattern documented |
</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| streamlit | 1.55.0 | Web dashboard framework | Latest stable. `st.navigation()` for multipage, `st.fragment()` for real-time, `st.cache_data` for caching. Project constraint. |
| pandas | 2.2.3 | DataFrame operations, CSV I/O | Standard for tabular data in Streamlit ecosystem. ~2300 IMU rows and ~800 vision rows per set is well within pandas sweet spot. |
| numpy | 2.2.6 | Array math, signal processing | Unlocked by dropping tensorflow-macos. ARM NEON vectorization on Apple Silicon. Required by mediapipe, scipy, pandas. |
| plotly | 6.6.0 | Interactive charting | `go.Indicator` for gauges, `go.Scatter` for waveforms. Native `st.plotly_chart()` integration. WebGL rendering for large datasets. |
| scipy | 1.15.3 | Signal processing, Butterworth filtering | `signal.butter`, `signal.filtfilt`, `signal.find_peaks`. Standard for biomechanics. Note: latest is 1.15.3 not 1.17 (research/STACK.md had a stale version). |
| mediapipe | 0.10.33 | Pose landmark detection | Existing in project. Tasks API PoseLandmarker. No tensorflow dependency on 0.10.33. |
| opencv-contrib-python | 4.10.0.84 | Frame processing, skeleton overlay | Required by mediapipe (its actual dependency). Do NOT also install opencv-python -- they conflict on the `cv2` namespace. |
| bleak | 2.1.1 | BLE communication | Already in project. Latest version, supports Python 3.12, macOS ARM. |
| matplotlib | 3.10.0 | Static export charts (analyze.py) | Existing dependency. Keep for CLI `analyze.py`; dashboard uses Plotly. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tomli-w | 1.2.0 | Write TOML config files | Settings page needs to write back to `config.toml`. `tomllib` (stdlib) is read-only. |
| ruff | latest | Linting and formatting | Dev dependency. Fast Python linter. |
| pytest | latest | Test framework | Dev dependency. For validation tests. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| tomli-w | toml (PyPI) | `toml` package is older, less maintained. `tomli-w` is the official write companion to `tomllib`. |
| pandas | polars | Overkill at ~3000 rows per set. Poor Streamlit/Plotly integration. |
| st.navigation | pages/ directory | Deprecated convention. `st.navigation` gives explicit control over page visibility, grouping, and role-based filtering. |

**Installation:**
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install streamlit==1.55.0 plotly==6.6.0 pandas==2.2.3 scipy==1.15.3 numpy==2.2.6 \
  mediapipe==0.10.33 opencv-contrib-python==4.10.0.84 bleak==2.1.1 matplotlib==3.10.0 \
  tomli-w==1.2.0
```

**Version verification:** All versions confirmed against PyPI on 2026-03-22:
- streamlit: 1.55.0 (latest)
- plotly: 6.6.0 (latest)
- pandas: 2.2.3 (latest stable; 2.3.3 exists but 2.2.x is safer for initial setup)
- scipy: 1.15.3 (latest; NOT 1.17 as previously researched -- that version does not exist yet)
- numpy: 2.2.6 (latest)
- mediapipe: 0.10.33 (latest, confirmed NO tensorflow dependency)
- opencv-contrib-python: 4.10.0.84 (match existing; 4.13 available but mediapipe pins compatibility)
- bleak: 2.1.1 (latest)
- tomli-w: 1.2.0 (latest)

**CRITICAL version correction:** The earlier research (`.planning/research/STACK.md`) listed `scipy>=1.17.1` and `numpy>=2.4.0` -- these versions do NOT exist on PyPI as of 2026-03-22. The actual latest versions are scipy 1.15.3 and numpy 2.2.6. The planner MUST use the verified versions above.

## Architecture Patterns

### Recommended Project Structure

```
test_rec/
  dashboard/                    # NEW: All dashboard code
    app.py                      # Streamlit entrypoint (router only)
    pages/
      training.py               # View 1 (Live Monitor) + View 2 (Set Report)
      analysis.py               # View 3 (Progress Tracking) + View 4 (AI Analysis)
      team.py                   # View 5 (Team Synchronization)
    core/                       # Shared computation logic
      __init__.py
      analysis.py               # calc_imu_tilt(), smooth(), correlation
      angles.py                 # calc_angle() (dot-product joint angle)
      data_loader.py            # CSV loading, pandas conversion, sessions.json
    components/                 # Reusable chart builders (Phase 2+)
      __init__.py
    config.py                   # TOML config read/write module
  config.toml                   # Project-level config (FINA thresholds, hardware)
  requirements.txt              # Pinned dependencies
  data/                         # Existing CSV data (unchanged)
  analyze.py                    # Existing CLI (imports from dashboard/core/)
  sync_recorder.py              # Existing recorder (unchanged)
  vision.py                     # Existing vision (unchanged)
  recorder.py                   # Existing BLE recorder (unchanged)
```

### Pattern 1: st.navigation Router with Page Grouping

**What:** `app.py` uses `st.navigation()` with a dict to group pages by workflow section. Each page is a `st.Page()` pointing to a file in `dashboard/pages/`.
**When to use:** Always -- this is the official Streamlit multipage pattern.
**Example:**
```python
# dashboard/app.py
import streamlit as st

st.set_page_config(page_title="SyncSwim Dashboard", layout="wide")

# Role toggle in sidebar
role = st.sidebar.radio("View as", ["Coach", "Athlete"], horizontal=True)
st.session_state["role"] = role

# Page definitions with grouping
training_pages = [
    st.Page("pages/training.py", title="Training", icon=":material/fitness_center:", default=True),
]
analysis_pages = [
    st.Page("pages/analysis.py", title="Analysis", icon=":material/analytics:"),
]
team_pages = [
    st.Page("pages/team.py", title="Team Sync", icon=":material/group:",
            visibility="visible" if role == "Coach" else "hidden"),
]

pg = st.navigation({
    "Training": training_pages,
    "Analysis": analysis_pages,
    "Team": team_pages,
})
pg.run()
```

**Source:** [Streamlit st.navigation docs](https://docs.streamlit.io/develop/api-reference/navigation/st.navigation)
**Confidence:** HIGH

### Pattern 2: Shared Session State Initialization

**What:** Initialize all session state variables in `app.py` before `pg.run()`. Never rely on widget keys for persistent state across pages.
**When to use:** Always -- prevents state loss on page navigation.
**Example:**
```python
# In app.py, BEFORE pg.run()
defaults = {
    "role": "Coach",
    "selected_set": None,
    "selected_set_dir": None,
    "sessions_index": None,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val
```

**Source:** [Streamlit session state docs](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state), [Community discussion on state persistence](https://discuss.streamlit.io/t/session-state-how-to-use-it-to-save-values-while-navigating-through-a-multi-page-app/62001)
**Confidence:** HIGH

### Pattern 3: Service Layer with Cache Decorators

**What:** All CSV loading goes through functions decorated with `@st.cache_data`. Cached functions return copies (safe for DataFrames). Use `ttl` to auto-expire.
**When to use:** Every data load operation.
**Example:**
```python
# dashboard/core/data_loader.py
import streamlit as st
import pandas as pd
import os
import json

@st.cache_data(ttl=60)
def load_imu(set_dir: str) -> pd.DataFrame:
    """Load IMU CSV as DataFrame. Cached 60s."""
    path = os.path.join(set_dir, "imu_NODE_A1.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)

@st.cache_data(ttl=60)
def load_vision(set_dir: str) -> pd.DataFrame:
    """Load vision CSV as DataFrame. Cached 60s."""
    path = os.path.join(set_dir, "vision.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)
```

**Source:** [Streamlit st.cache_data API](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)
**Confidence:** HIGH -- `st.cache_data` returns copies, safe for DataFrame mutation.

### Pattern 4: TOML Config Read/Write

**What:** Use `tomllib` (stdlib, Python 3.11+) for reading and `tomli_w` for writing. Wrap in a config module that provides typed access.
**When to use:** All config access (FINA thresholds, hardware config, dashboard preferences).
**Example:**
```python
# dashboard/config.py
import tomllib
import tomli_w
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.toml"

def load_config() -> dict:
    """Read config.toml. Returns dict."""
    if not CONFIG_PATH.exists():
        return get_defaults()
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)

def save_config(config: dict) -> None:
    """Write config dict back to config.toml."""
    with open(CONFIG_PATH, "wb") as f:
        tomli_w.dump(config, f)

def get_defaults() -> dict:
    """Default configuration values."""
    return {
        "fina": {
            "clean_threshold_deg": 15,
            "minor_deduction_deg": 30,
            "clean_deduction": 0.0,
            "minor_deduction": 0.2,
            "major_deduction": 0.5,
        },
        "hardware": {
            "camera_url": "http://192.168.66.169:4747/video",
            "ble_device_name": "NODE_A1",
            "ble_char_uuid": "abcd1234-ab12-cd34-ef56-abcdef123456",
        },
        "dashboard": {
            "default_role": "Coach",
            "data_dir": "data",
        },
    }
```

**Source:** [Python tomllib docs](https://docs.python.org/3/library/tomllib.html), [tomli-w PyPI](https://pypi.org/project/tomli-w/)
**Confidence:** HIGH

### Pattern 5: sessions.json Index with Staleness Detection

**What:** Build a JSON index of all set directories with metadata. Rebuild automatically if directory modification time is newer than index file.
**When to use:** Dashboard startup and set selector dropdown.
**Example:**
```python
# dashboard/core/data_loader.py
import json
import os
from datetime import datetime

def build_sessions_index(data_dir: str) -> list[dict]:
    """Scan data/ and build metadata for each set directory."""
    sessions = []
    for name in sorted(os.listdir(data_dir)):
        if not name.startswith("set_") or not os.path.isdir(os.path.join(data_dir, name)):
            continue
        set_dir = os.path.join(data_dir, name)
        # Parse set_NNN_YYYYMMDD_HHMMSS
        parts = name.split("_")
        set_num = int(parts[1])
        date_str = parts[2]  # YYYYMMDD
        time_str = parts[3]  # HHMMSS

        has_imu = os.path.exists(os.path.join(set_dir, "imu_NODE_A1.csv"))
        has_vision = os.path.exists(os.path.join(set_dir, "vision.csv"))

        imu_rows = 0
        vis_rows = 0
        duration = 0.0
        if has_imu:
            # Count lines (minus header)
            with open(os.path.join(set_dir, "imu_NODE_A1.csv")) as f:
                lines = f.readlines()
                imu_rows = max(0, len(lines) - 1)
            if imu_rows > 1:
                # Duration from first to last timestamp
                first_t = float(lines[1].split(",")[0])
                last_t = float(lines[-1].split(",")[0])
                duration = last_t - first_t
        if has_vision:
            with open(os.path.join(set_dir, "vision.csv")) as f:
                vis_rows = max(0, len(f.readlines()) - 1)

        sessions.append({
            "name": name,
            "path": set_dir,
            "set_number": set_num,
            "date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}",
            "time": f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}",
            "duration_sec": round(duration, 1),
            "imu_rows": imu_rows,
            "vision_rows": vis_rows,
            "has_imu": has_imu,
            "has_vision": has_vision,
        })
    return sessions

def load_or_rebuild_index(data_dir: str) -> list[dict]:
    """Load sessions.json if fresh, rebuild if stale."""
    index_path = os.path.join(data_dir, "sessions.json")
    data_mtime = os.path.getmtime(data_dir)

    if os.path.exists(index_path):
        index_mtime = os.path.getmtime(index_path)
        if index_mtime >= data_mtime:
            with open(index_path) as f:
                return json.load(f)

    # Rebuild
    sessions = build_sessions_index(data_dir)
    with open(index_path, "w") as f:
        json.dump(sessions, f, indent=2)
    return sessions
```

**Confidence:** HIGH -- standard file-based index pattern; `os.path.getmtime` is reliable for staleness detection.

### Anti-Patterns to Avoid

- **Installing both opencv-python AND opencv-contrib-python:** They share the `cv2` namespace and conflict. MediaPipe depends on `opencv-contrib-python`. Use ONLY `opencv-contrib-python`.
- **Using the `pages/` directory convention:** When `st.navigation()` is used, Streamlit ignores the `pages/` directory. But naming the folder `pages/` inside `dashboard/` is fine since Streamlit only looks for a top-level `pages/` folder.
- **Putting config.toml inside dashboard/:** Keep it at project root so both CLI scripts and dashboard can access it.
- **Using module-level globals for state:** Streamlit reruns the entire page script on every interaction. Use `st.session_state` for all mutable state.
- **Importing dashboard modules without `__init__.py`:** Ensure `dashboard/core/__init__.py` and `dashboard/components/__init__.py` exist for proper Python package resolution.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TOML writing | Custom string formatter | `tomli_w.dump()` | Handles escaping, nested tables, arrays-of-tables correctly |
| CSV to DataFrame | Custom dict-based loader | `pd.read_csv()` | Handles encoding, dtypes, missing values, large files efficiently |
| Multipage routing | Custom if/elif page switcher | `st.navigation()` + `st.Page()` | Handles URL routing, browser history, page title, sidebar menu |
| Config defaults merging | Custom nested dict merge | `dict | defaults` (Python 3.9+ merge) | Clean, one-liner, handles nested keys |
| Set directory parsing | Regex on filenames | `str.split("_")` on known format | Format is fixed (`set_NNN_YYYYMMDD_HHMMSS`), split is cleaner and faster |

**Key insight:** This phase is mostly wiring and plumbing. The complexity is in getting the environment right and the architecture patterns correct. Almost every component has a standard library or well-known package solution.

## Common Pitfalls

### Pitfall 1: opencv-python / opencv-contrib-python Conflict

**What goes wrong:** Both packages install the `cv2` module. Having both causes import errors, version mismatches, or subtle runtime bugs where the wrong module loads.
**Why it happens:** The existing environment has both installed (confirmed: both at 4.10.0.84). MediaPipe depends on `opencv-contrib-python`, but developers often also `pip install opencv-python`.
**How to avoid:** In `requirements.txt`, specify ONLY `opencv-contrib-python`. Never add `opencv-python`. Add a comment explaining why.
**Warning signs:** `ImportError: numpy.core.multiarray failed to import`, module attribute errors in cv2.

### Pitfall 2: Session State Loss on Page Navigation

**What goes wrong:** Navigating between pages can lose `st.session_state` values, especially widget-keyed state.
**Why it happens:** Widget keys are tied to their page's lifecycle. When navigating away, widgets are garbage-collected and their keys may disappear.
**How to avoid:** Initialize all critical state in `app.py` before `pg.run()`. Use callback functions to copy widget values into persistent state keys. Never rely on widget keys for cross-page data.
**Warning signs:** Selected set resets to None when switching pages; role toggle resets.

### Pitfall 3: Stale scipy/numpy Version References

**What goes wrong:** Using version numbers from training data or earlier research that don't exist on PyPI.
**Why it happens:** The earlier research (STACK.md) listed scipy>=1.17.1 and numpy>=2.4.0. These versions do NOT exist as of 2026-03-22. Actual latest: scipy 1.15.3, numpy 2.2.6.
**How to avoid:** Always verify versions against PyPI before pinning. Use `pip3 index versions <pkg>` to check.
**Warning signs:** `pip install` fails with "no matching distribution found".

### Pitfall 4: Shared Module Import Path Issues

**What goes wrong:** After extracting code to `dashboard/core/`, existing `analyze.py` at project root cannot import it.
**Why it happens:** `dashboard/core/` is not on Python's default import path when running `python3 analyze.py` from project root.
**How to avoid:** Two approaches: (1) Add `sys.path.insert(0, os.path.dirname(__file__))` in `analyze.py`, or (2) create a minimal `pyproject.toml` and use `pip install -e .` for editable install. Option 2 is cleaner but adds setup complexity. Option 1 is pragmatic for this phase.
**Warning signs:** `ModuleNotFoundError: No module named 'dashboard'`.

### Pitfall 5: config.toml Path Resolution

**What goes wrong:** `config.toml` not found when running `streamlit run dashboard/app.py` because the working directory may vary.
**Why it happens:** Relative paths resolve from CWD, not from the script location. If Streamlit is launched from a different directory, the config path breaks.
**How to avoid:** Use `pathlib.Path(__file__).parent.parent / "config.toml"` for script-relative resolution. This pattern already exists in the codebase for the MediaPipe model file.
**Warning signs:** FileNotFoundError on app startup; config silently falls back to defaults.

### Pitfall 6: pandas read_csv on Corrupted/Truncated CSVs

**What goes wrong:** A recording interrupted mid-write produces a truncated CSV. `pd.read_csv()` raises `ParserError` and the entire page crashes.
**Why it happens:** Recording scripts flush CSV periodically (every 100 packets) but a crash between flushes leaves partial rows.
**How to avoid:** Wrap `pd.read_csv()` in try/except. Use `on_bad_lines="warn"` parameter (pandas 1.3+) to skip corrupted rows instead of crashing. Show a yellow warning badge for degraded data.
**Warning signs:** `ParserError: Error tokenizing data` in the console.

## Code Examples

Verified patterns from official sources:

### Streamlit Multipage with Grouped Navigation

```python
# Source: https://docs.streamlit.io/develop/api-reference/navigation/st.navigation
import streamlit as st

# Dict keys become section headers in sidebar
pg = st.navigation({
    "Training": [
        st.Page("pages/training.py", title="Training", icon=":material/fitness_center:", default=True),
    ],
    "Analysis": [
        st.Page("pages/analysis.py", title="Analysis", icon=":material/analytics:"),
    ],
    "Team": [
        st.Page("pages/team.py", title="Team Sync", icon=":material/group:"),
    ],
})
pg.run()
```

### TOML Config Round-Trip (Read + Write)

```python
# Source: https://docs.python.org/3/library/tomllib.html + https://pypi.org/project/tomli-w/
import tomllib
import tomli_w

# Read
with open("config.toml", "rb") as f:
    config = tomllib.load(f)

# Modify
config["fina"]["clean_threshold_deg"] = 12

# Write back
with open("config.toml", "wb") as f:
    tomli_w.dump(config, f)
```

### Cached DataFrame Loading with Graceful Degradation

```python
# Source: https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data
import streamlit as st
import pandas as pd

@st.cache_data(ttl=60)
def load_set_data(set_dir: str) -> dict:
    """Load a set's CSVs as DataFrames. Returns dict with 'imu' and 'vision' keys."""
    result = {"imu": pd.DataFrame(), "vision": pd.DataFrame(), "warnings": []}
    imu_path = f"{set_dir}/imu_NODE_A1.csv"
    vis_path = f"{set_dir}/vision.csv"

    try:
        if os.path.exists(imu_path):
            result["imu"] = pd.read_csv(imu_path, on_bad_lines="warn")
    except Exception as e:
        result["warnings"].append(f"IMU data load error: {e}")

    try:
        if os.path.exists(vis_path):
            result["vision"] = pd.read_csv(vis_path, on_bad_lines="warn")
    except Exception as e:
        result["warnings"].append(f"Vision data load error: {e}")

    return result
```

### Backward-Compatible Shared Module Import in analyze.py

```python
# At top of existing analyze.py, add:
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Then import from shared module:
from dashboard.core.analysis import calc_imu_tilt, smooth
from dashboard.core.angles import calc_angle
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `pages/` directory convention | `st.navigation()` + `st.Page()` | Streamlit 1.36 (2024) | Explicit routing, page grouping, role-based visibility, URL control |
| `st.experimental_memo` | `st.cache_data` | Streamlit 1.18 (2023) | Stable API, ttl support, persist to disk option |
| `tensorflow-macos` required by mediapipe | No tensorflow dependency | MediaPipe 0.10.31+ (2024) | Unblocks numpy 2.x, simplifies dependency tree dramatically |
| `toml` package (PyPI) | `tomllib` (stdlib) + `tomli-w` | Python 3.11 (2022) | No external dependency for reading; `tomli-w` only needed for writing |
| numpy 1.x pinned | numpy 2.x compatible | mediapipe 0.10.31+ | 2x performance on Apple Silicon ARM NEON, modern API |

**Deprecated/outdated:**
- `st.experimental_memo` / `st.experimental_singleton` -- replaced by `st.cache_data` / `st.cache_resource`
- `pages/` directory auto-discovery -- still works but `st.navigation()` is recommended
- `toml` package -- stdlib `tomllib` is preferred for reading
- `tensorflow-macos` -- no longer needed by mediapipe 0.10.33

## Claude's Discretion: MjpegStreamReader and BLE Extraction

**Recommendation: DEFER MjpegStreamReader and BLE protocol extraction to Phase 5.**

Reasoning:
1. The dashboard in Phase 1 does NOT use `MjpegStreamReader` or BLE protocol parsing. It reads CSV files from disk.
2. `MjpegStreamReader` is only needed for live video in Phase 5 (Real-Time Monitoring).
3. BLE protocol parsing is only relevant for Phase 5 (process isolation) and Phase 6 (multi-person).
4. Extracting them now would require modifying `sync_recorder.py` and `vision.py` to import from the shared module, which adds risk to working scripts with no immediate benefit.
5. The core math functions (`calc_imu_tilt`, `calc_angle`, `smooth`) are the ones that the dashboard Phase 1 actually needs for the data loading and metadata computation layer.

**Extract NOW (Phase 1):** `calc_imu_tilt()`, `calc_angle()`, `smooth()`, correlation computation, `load_imu()`, `load_vision()`, `find_set_dir()`.

**Defer to Phase 5/6:** `MjpegStreamReader`, BLE notification handler, binary packet parser.

## Open Questions

1. **pandas version pinning: 2.2.3 vs 2.3.3?**
   - What we know: Both exist on PyPI. 2.2.3 is the latest in the 2.2.x series; 2.3.3 is the latest overall.
   - What's unclear: Whether 2.3.x introduces breaking changes affecting Streamlit integration.
   - Recommendation: Use 2.2.3 for stability. The phase does basic `read_csv` only -- no advanced features needed.

2. **opencv-contrib-python version: pin to 4.10.0.84 or allow 4.13?**
   - What we know: mediapipe 0.10.33 depends on `opencv-contrib-python` without a version pin. Current install is 4.10.0.84. Latest is 4.13.0.92.
   - What's unclear: Whether 4.13 introduces breaking changes with mediapipe 0.10.33.
   - Recommendation: Pin to `>=4.10.0,<5.0` to allow patch updates but avoid major breaks.

3. **Streamlit `position="sidebar"` vs `position="top"` for navigation?**
   - What we know: CONTEXT.md specifies sidebar. `position="sidebar"` is the default.
   - Recommendation: Use default (sidebar). Matches the coach/athlete toggle placement.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (latest) |
| Config file | none -- Wave 0 |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFRA-01 | App skeleton launches with st.navigation and 3 pages | smoke | `python -c "from dashboard.app import *"` (import check) | No -- Wave 0 |
| INFRA-02 | Coach/athlete toggle changes session_state role | unit | `pytest tests/test_app.py::test_role_toggle -x` | No -- Wave 0 |
| INFRA-03 | CSV loading returns valid DataFrames with correct columns | unit | `pytest tests/test_data_loader.py -x` | No -- Wave 0 |
| INFRA-04 | Session selector populates from sessions.json index | unit | `pytest tests/test_data_loader.py::test_sessions_index -x` | No -- Wave 0 |
| INFRA-05 | All dependencies importable on Python 3.12 | smoke | `python -c "import streamlit, plotly, pandas, scipy, numpy, mediapipe, cv2, bleak"` | No -- Wave 0 |
| INFRA-06 | Config loads/saves TOML round-trip correctly | unit | `pytest tests/test_config.py -x` | No -- Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/` directory -- create at project root
- [ ] `tests/test_config.py` -- covers INFRA-06: TOML read/write/defaults round-trip
- [ ] `tests/test_data_loader.py` -- covers INFRA-03, INFRA-04: CSV loading, sessions index build
- [ ] `tests/test_core_analysis.py` -- covers shared module extraction: calc_imu_tilt, smooth, calc_angle
- [ ] `tests/conftest.py` -- shared fixtures (sample CSV data, temp directories, config fixtures)
- [ ] pytest install: `pip install pytest` (add to dev dependencies)

## Sources

### Primary (HIGH confidence)
- [Streamlit st.navigation API](https://docs.streamlit.io/develop/api-reference/navigation/st.navigation) - page routing, grouping, position parameter
- [Streamlit st.Page API](https://docs.streamlit.io/develop/api-reference/navigation/st.page) - page parameter types (str/Path/callable), icon, visibility, default
- [Streamlit st.cache_data API](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data) - ttl, max_entries, persist, hash_funcs, scope
- [Streamlit session state](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state) - persistence model, widget key lifecycle
- [Python tomllib docs](https://docs.python.org/3/library/tomllib.html) - stdlib TOML parser (read-only)
- [tomli-w PyPI](https://pypi.org/project/tomli-w/) - TOML writer, v1.2.0
- [mediapipe PyPI](https://pypi.org/project/mediapipe/0.10.33/) - dependency list verified: NO tensorflow
- PyPI version checks (2026-03-22): streamlit 1.55.0, plotly 6.6.0, pandas 2.2.3/2.3.3, scipy 1.15.3, numpy 2.2.6, bleak 2.1.1, tomli-w 1.2.0

### Secondary (MEDIUM confidence)
- [Streamlit community: session state across pages](https://discuss.streamlit.io/t/session-state-how-to-use-it-to-save-values-while-navigating-through-a-multi-page-app/62001) - verified state persistence works with st.navigation
- [opencv-python conflict docs](https://pypi.org/project/opencv-contrib-python/) - cannot install both opencv-python and opencv-contrib-python
- [Real Python: Python and TOML](https://realpython.com/python-toml/) - tomllib + tomli_w patterns

### Tertiary (LOW confidence)
- None -- all findings verified against primary sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all versions verified against PyPI, mediapipe dependency tree confirmed via dry-run install
- Architecture: HIGH - st.navigation/st.Page API verified from official docs, patterns from project research
- Pitfalls: HIGH - opencv conflict confirmed from actual environment inspection, session state issues from Streamlit docs + community
- Config approach: HIGH - tomllib is stdlib, tomli_w verified on PyPI

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (30 days -- stable ecosystem, all major versions verified)
