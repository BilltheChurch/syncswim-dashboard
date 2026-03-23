# Phase 2: Single-Set Analysis - Research

**Researched:** 2026-03-23
**Domain:** Post-recording biomechanical analysis dashboard (Plotly gauges, scipy signal processing, OpenCV video, MediaPipe skeleton overlay)
**Confidence:** HIGH

## Summary

Phase 2 transforms the training page from a metadata-only display into a full analysis report with three tabs (Overview, Visual, Sensor). The core technical challenges are: (1) computing 5 biomechanical metrics from existing IMU and vision CSV data, (2) detecting action phases from IMU acceleration peaks via scipy, (3) modifying sync_recorder.py to save MP4 video and expanded 33-landmark CSV, (4) re-running MediaPipe on saved video for skeleton overlay in the dashboard, and (5) building Plotly gauge charts with FINA zone coloring plus a dual-axis fusion chart.

All required libraries are already installed in the .venv (Python 3.12.13): scipy 1.15.3, plotly 6.3.0 (requirements.txt pins 6.6.0), streamlit 1.49.1 (requirements.txt pins 1.55.0), mediapipe 0.10.33, opencv-contrib-python 4.10.0, pandas 2.2.3, numpy 1.26.4. The `avc1` (H.264) codec has been verified working on this macOS Apple Silicon system with opencv-contrib-python, producing compact MP4 files. No new PyPI packages are needed for Phase 2.

**Primary recommendation:** Build in layers -- first the scoring engine (pure computation, testable), then the recording pipeline modifications (sync_recorder.py), then the visualization components (Plotly charts), and finally the training page integration (st.tabs layout). This allows each layer to be tested independently before wiring into the UI.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- 5 metrics displayed as Plotly gauge charts + small metric numbers below each gauge
- Per-metric FINA deduction shown on each gauge (e.g., "-0.2") + overall estimated score out of 10 at top
- Standard template source: historical best set as default, coach can override target angles per session
- **Leg vertical deviation**: IMU tilt angle vs 90 deg vertical (from calc_imu_tilt)
- **Leg height index**: MediaPipe hip-to-ankle Y ratio -- (ankle_y - water_line) / (hip_y - ankle_y)
- **Shoulder-knee alignment**: angle between shoulder, hip, and knee landmarks from MediaPipe
- **Smoothness**: Jerk metric using combined gyroscope magnitude sqrt(gx^2+gy^2+gz^2) derivative
- **Exhibition hold stability**: standard deviation of tilt angle during exhibition phase
- Start with 3 phases: prep / active / recovery (expand to 5 later)
- Auto-detection from IMU signal peaks + manual slider adjustment for fine-tuning boundaries
- Phase quality color coding uses FINA zone colors: green=good / yellow=minor / red=major
- Training page organized as tabs: Tab 1: Overview, Tab 2: Visual, Tab 3: Sensor
- Report auto-generates within 3 seconds of set selection
- Re-run MediaPipe on saved video to generate skeleton overlay frames in dashboard
- Keyframe comparison: green wireframe = standard template, red wireframe = actual pose
- sync_recorder.py modified to save MP4 alongside CSVs
- Video starts/stops simultaneously with BLE recording (Button A trigger)
- MP4 file saved in same set directory: data/set_NNN_YYYYMMDD_HHMMSS/video.mp4
- Uses OpenCV VideoWriter with H.264 codec on macOS
- Expand vision.csv to save all 33 MediaPipe landmarks per frame (format: Claude decides)
- Per-metric deduction on each gauge, overall estimated execution score out of 10 at top
- Score calculated by starting at 10.0, subtracting per-metric deductions based on config.toml thresholds

### Claude's Discretion
- Whether scoring card appears as persistent header on all tabs or only on Overview tab -- **DECIDED in UI-SPEC: Persistent header above tabs**
- Landmark CSV format: wide (100+ columns) vs separate landmarks.csv (long format) -- Claude decides based on pandas loading efficiency and Plotly rendering needs

### Deferred Ideas (OUT OF SCOPE)
- 5-phase detection (prep/entry/lift/exhibition/descent) -- expand from 3-phase after validating detection algorithm
- Video playback scrubber with synchronized IMU waveform cursor -- complex UI, defer to later iteration
- Automatic "best moment" keyframe selection -- start with manual frame navigation, auto-select later
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ANAL-01 | Quantitative scoring card -- 5 metrics: leg vertical deviation, leg height index, shoulder-knee alignment, smoothness (Jerk), exhibition hold stability | Metric formulas defined below in Architecture Patterns. Existing `calc_imu_tilt()` and `calc_angle()` are reusable. New computations needed: leg height ratio, gyro jerk, tilt stability (std dev). |
| ANAL-02 | FINA deduction rule mapping -- <15 deg=clean, 15-30 deg=0.2 deduction, >30 deg=0.5+ deduction, auto-scored per set | Thresholds already in config.toml (`fina.clean_threshold_deg`, `fina.minor_deduction_deg`). Scoring engine reads config, applies thresholds, sums deductions from 10.0 base. |
| ANAL-03 | Action phase timeline -- horizontal bar with prep/active/recovery phases, color-coded quality per phase | `scipy.signal.find_peaks` on IMU acceleration magnitude for transition detection. Plotly `go.Bar(orientation="h", barmode="stack")` for visualization. Manual slider for boundary adjustment. |
| ANAL-04 | Phase detection from IMU signals -- acceleration peaks for transitions, jerk plateau for holds | Butterworth low-pass filter (4th order, 10Hz cutoff) on accel magnitude, then `find_peaks(prominence=..., distance=...)`. Jerk = np.gradient of smoothed accel for plateau detection. |
| ANAL-05 | Keyframe comparison -- exhibition pose vs standard template side-by-side, deviation angles marked in red | Requires expanded landmarks.csv (33 landmarks per frame). OpenCV renders green wireframe (template) + red wireframe (actual) on same frame. Displayed via `st.image`. |
| ANAL-06 | Post-set report auto-generation -- triggered on set selection, 2-3 second render | Streamlit reruns page on `selected_set` change. All computations cached with `@st.cache_data`. 3-second budget achievable: CSV load <100ms, metric computation <200ms, chart rendering <2s. |
| VIZ-01 | Joint angle gauges with FINA zone coloring -- green/yellow/red circular indicators (Plotly go.Indicator) | `go.Indicator(mode="gauge+number")` with `gauge.steps` for three color zones. Zone thresholds from config.toml. Gauge height 200px, `displayModeBar: False`. |
| VIZ-02 | IMU waveform display -- accel/gyro scrolling time-series curves + fused tilt angle | `go.Scatter` with three traces: accel magnitude (blue), gyro magnitude (orange), fused tilt (purple). Existing `calc_imu_tilt()` provides tilt. Chart height 300px. |
| VIZ-03 | Skeleton overlay on recorded video frames -- MediaPipe bones rendered on playback frames via st.image | Requires video.mp4 from modified sync_recorder.py. Re-run MediaPipe PoseLandmarker in dashboard to get landmarks per frame. OpenCV draws skeleton, `st.image` displays. Frame navigation via session_state. |
| VIZ-04 | IMU + Vision fusion chart -- dual-axis Plotly showing both sensor angles on same timeline with correlation coefficient | `plotly.subplots.make_subplots(specs=[[{"secondary_y": True}]])`. Left Y = vision angle (green), Right Y = IMU tilt (blue). `np.corrcoef` for correlation. Already validated in analyze.py (r=-0.497). |
</phase_requirements>

## Standard Stack

### Core (Already Installed)

| Library | Installed Version | Pinned Version | Purpose | Why Standard |
|---------|-------------------|----------------|---------|--------------|
| plotly | 6.3.0 | 6.6.0 | Gauge charts, time-series, fusion chart | `go.Indicator` for gauges, `make_subplots` for dual-axis, `go.Bar` for timeline. Native Streamlit integration via `st.plotly_chart`. |
| scipy | 1.15.3 | 1.15.3 | Signal processing, peak detection | `scipy.signal.find_peaks` for phase boundary detection. `scipy.signal.butter` + `filtfilt` for Butterworth filtering of IMU noise. |
| mediapipe | 0.10.33 | 0.10.33 | Pose landmark detection | PoseLandmarker Tasks API for re-running detection on saved video frames in dashboard. 33-landmark model already used in sync_recorder.py. |
| opencv-contrib-python | 4.10.0 | 4.10.0.84 | Video read/write, skeleton drawing | `cv2.VideoWriter` with `avc1` fourcc for MP4 recording. `cv2.VideoCapture` for frame extraction. `cv2.line`/`cv2.circle` for skeleton overlay rendering. |
| pandas | 2.2.3 | 2.2.3 | DataFrame operations | CSV loading, landmark data manipulation, metric aggregation. Existing `load_imu()` and `load_vision()` return DataFrames. |
| numpy | 1.26.4 | 2.2.6 | Array math, derivatives | `np.gradient` for jerk computation, `np.std` for stability, `np.corrcoef` for correlation, `np.interp` for time alignment. |
| streamlit | 1.49.1 | 1.55.0 | Dashboard UI | `st.tabs`, `st.columns`, `st.plotly_chart`, `st.image`, `st.slider`, `st.session_state`. |

### Supporting (No New Dependencies)

| Library | Purpose | When to Use |
|---------|---------|-------------|
| tomllib (stdlib) | Read config.toml FINA thresholds | Scoring engine reads threshold values at analysis time |
| math (stdlib) | Trigonometry for angle calculations | `atan2`, `acos`, `degrees` in metric computations |
| pathlib (stdlib) | Path handling | File path construction for video/landmark files |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| scipy.signal.find_peaks | Custom peak detection | find_peaks is battle-tested with prominence/distance params; custom code adds bugs |
| OpenCV skeleton rendering | Plotly scatter skeleton | OpenCV is faster for per-frame rendering; Plotly would be slow for 800+ frames |
| Wide-format landmarks CSV | Long-format (row per landmark) | Wide is 100+ columns but one row per frame; long is 33 rows per frame (26x more rows). Wide wins for pandas loading and Plotly rendering speed. |

**No new pip install needed.** All Phase 2 dependencies are already in requirements.txt.

## Architecture Patterns

### Recommended Project Structure (Phase 2 additions)

```
dashboard/
  core/
    analysis.py          # Existing: calc_imu_tilt(), smooth()
    angles.py            # Existing: calc_angle()
    data_loader.py       # Existing: load_imu(), load_vision()
    scoring.py           # NEW: ScoringEngine class, FINA deduction logic
    phase_detect.py      # NEW: detect_phases() using scipy find_peaks
    landmarks.py         # NEW: load_landmarks(), skeleton rendering helpers
    metrics.py           # NEW: compute_all_metrics() orchestrator
  components/
    __init__.py          # Existing: CHART_THEME
    gauge_chart.py       # NEW: build_gauge_figure(), build_scoring_card()
    timeline_chart.py    # NEW: build_phase_timeline()
    waveform_chart.py    # NEW: build_imu_waveform(), build_fusion_chart()
    skeleton_renderer.py # NEW: render_skeleton_frame(), render_keyframe_comparison()
  pages/
    training.py          # MODIFY: add scoring card + 3-tab report layout
sync_recorder.py         # MODIFY: add VideoWriter + expanded landmark CSV
```

### Pattern 1: Scoring Engine (Pure Computation)

**What:** A `ScoringEngine` class that takes raw DataFrames and config dict, returns a structured `SetReport` with all 5 metric values, deductions, phase boundaries, and overall score.
**When to use:** Called once per set selection, result cached.
**Why:** Separating computation from visualization makes it testable without Streamlit. The engine can be unit-tested with synthetic data.

```python
# dashboard/core/scoring.py
from dataclasses import dataclass
import numpy as np
from dashboard.core.analysis import calc_imu_tilt, smooth
from dashboard.core.angles import calc_angle

@dataclass
class MetricResult:
    name: str           # Chinese display name
    value: float        # Raw metric value
    unit: str           # "deg", "ratio", "score"
    deduction: float    # FINA deduction (0.0, 0.2, 0.5)
    zone: str           # "clean", "minor", "major"
    max_value: float    # Gauge range max

@dataclass
class SetReport:
    metrics: list[MetricResult]   # 5 metrics
    overall_score: float          # 10.0 - sum(deductions)
    phases: list[dict]            # [{name, start_sec, end_sec, quality_zone}]
    correlation: float | None     # IMU-vision correlation coefficient

def compute_leg_deviation(imu_df) -> float:
    """Mean absolute tilt deviation from 90 deg vertical during active phase."""
    tilt = calc_imu_tilt(imu_df.to_dict('records'))
    tilt_smooth = smooth(tilt, window=15)
    return float(np.mean(np.abs(tilt_smooth - 90.0)))

def compute_smoothness(imu_df) -> float:
    """Jerk metric: mean absolute derivative of combined gyro magnitude."""
    gx, gy, gz = imu_df["gx"].values, imu_df["gy"].values, imu_df["gz"].values
    gyro_mag = np.sqrt(gx**2 + gy**2 + gz**2)
    gyro_smooth = smooth(gyro_mag, window=5)
    jerk = np.gradient(gyro_smooth)
    return float(np.mean(np.abs(jerk)))

def compute_stability(imu_df, phase_bounds: tuple) -> float:
    """Std dev of tilt angle during exhibition/active phase."""
    start, end = phase_bounds
    mask = (imu_df["timestamp_local"] >= start) & (imu_df["timestamp_local"] <= end)
    phase_data = imu_df[mask]
    if len(phase_data) < 2:
        return 0.0
    tilt = calc_imu_tilt(phase_data.to_dict('records'))
    return float(np.std(tilt))
```

**Confidence:** HIGH -- uses existing validated functions, pure numpy computation.

### Pattern 2: Phase Detection via scipy

**What:** Detect 3 action phases (prep/active/recovery) from IMU acceleration magnitude peaks.
**When to use:** Called during report generation for each set.

```python
# dashboard/core/phase_detect.py
import numpy as np
from scipy.signal import find_peaks, butter, filtfilt

def butterworth_filter(data: np.ndarray, cutoff: float = 10.0,
                       fs: float = 72.5, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth low-pass filter for IMU data."""
    nyquist = fs / 2
    if cutoff >= nyquist:
        cutoff = nyquist * 0.9
    b, a = butter(order, cutoff / nyquist, btype='low')
    if len(data) < 3 * max(len(a), len(b)):
        return data  # Too short for filtfilt
    return filtfilt(b, a, data)

def detect_phases(imu_df, n_phases: int = 3) -> list[dict]:
    """Detect prep/active/recovery phase boundaries from IMU accel peaks.

    Algorithm:
    1. Compute acceleration magnitude sqrt(ax^2 + ay^2 + az^2)
    2. Butterworth low-pass filter at 10Hz (removes sensor noise)
    3. find_peaks on filtered signal with prominence and distance thresholds
    4. Use two most prominent peaks as phase boundaries
    5. Fall back to equal thirds if < 2 peaks found
    """
    ax = imu_df["ax"].values.astype(float)
    ay = imu_df["ay"].values.astype(float)
    az = imu_df["az"].values.astype(float)
    timestamps = imu_df["timestamp_local"].values.astype(float)

    accel_mag = np.sqrt(ax**2 + ay**2 + az**2)
    filtered = butterworth_filter(accel_mag)

    # Find peaks with minimum prominence and distance
    peaks, properties = find_peaks(
        filtered,
        prominence=0.3,      # Minimum peak prominence (g units)
        distance=int(72.5),  # At least 1 second apart
    )

    if len(peaks) >= 2:
        # Sort peaks by prominence, take top 2
        sorted_idx = np.argsort(properties["prominences"])[::-1][:2]
        boundary_indices = sorted(peaks[sorted_idx])
        t1 = timestamps[boundary_indices[0]]
        t2 = timestamps[boundary_indices[1]]
    else:
        # Fallback: equal thirds
        t_start, t_end = timestamps[0], timestamps[-1]
        duration = t_end - t_start
        t1 = t_start + duration / 3
        t2 = t_start + 2 * duration / 3

    t_start, t_end = timestamps[0], timestamps[-1]
    return [
        {"name": "准备", "start": t_start, "end": t1, "zone_color": "#09AB3B"},
        {"name": "动作", "start": t1, "end": t2, "zone_color": "#FACA2B"},
        {"name": "恢复", "start": t2, "end": t_end, "zone_color": "#09AB3B"},
    ]
```

**Confidence:** HIGH -- scipy.signal.find_peaks is the standard approach for IMU peak detection in sports biomechanics.

### Pattern 3: Landmark CSV Format Decision

**Decision: Wide format with separate landmarks.csv file.**

Rationale:
- The expanded landmarks.csv is a NEW file alongside the existing vision.csv (which continues to store the single-joint angle for backward compatibility)
- Wide format: one row per frame, columns: `timestamp_local,frame,lm_0_x,lm_0_y,lm_0_z,lm_0_vis,lm_1_x,...,lm_32_vis`
- That is 33 landmarks x 4 values = 132 landmark columns + 2 metadata columns = 134 columns total
- At 26fps for 30 seconds = ~780 rows -- trivially small for pandas
- Wide format enables instant frame lookup: `df.iloc[frame_idx]` returns all landmarks for one frame
- Long format would be 780 x 33 = 25,740 rows requiring groupby per frame -- slower for rendering

```python
# Landmark CSV header construction
LANDMARK_NAMES = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]

def get_landmark_csv_header() -> list[str]:
    header = ["timestamp_local", "frame"]
    for name in LANDMARK_NAMES:
        header.extend([f"{name}_x", f"{name}_y", f"{name}_z", f"{name}_vis"])
    return header
```

**Confidence:** HIGH -- wide format is the standard for pose landmark export; matches how OpenPose and MMPose export data.

### Pattern 4: MP4 Recording in sync_recorder.py

**What:** Add `cv2.VideoWriter` to sync_recorder.py that records H.264 MP4 simultaneously with CSV data.
**Key findings from codec verification:**
- `avc1` fourcc verified working on this macOS Apple Silicon system with opencv-contrib-python 4.10.0
- Produces smallest files (best compression) compared to mp4v, MJPG, XVID
- No additional dependencies or compilation needed

```python
# In sync_recorder.py start_recording():
video_path = os.path.join(set_dir, "video.mp4")
fourcc = cv2.VideoWriter_fourcc(*"avc1")
# Frame size must match camera output after rotation
state.video_writer = cv2.VideoWriter(video_path, fourcc, 25.0, (frame_w, frame_h))

# In main loop, after processing frame:
with state.lock:
    if state.recording and state.video_writer:
        state.video_writer.write(frame)  # Write BGR frame (before OSD overlay)

# In stop_recording():
if state.video_writer:
    state.video_writer.release()
    state.video_writer = None
```

**Critical detail:** Write the CLEAN frame (before OSD overlay is drawn) to video.mp4. The OSD is for the live OpenCV window only; the saved video should be clean for MediaPipe re-processing in the dashboard.

**Confidence:** HIGH -- codec verified on this exact system.

### Pattern 5: MediaPipe Re-Processing in Dashboard

**What:** Re-run MediaPipe PoseLandmarker on saved video.mp4 frames in the dashboard for skeleton overlay.
**When:** On the Visual tab when user navigates frames.
**Why:** Cannot store pre-rendered skeleton frames (would double storage). Re-running detection per-frame is fast (~30ms) and provides fresh landmark data.

```python
# dashboard/core/landmarks.py
import cv2
import mediapipe as mp
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode
from mediapipe.tasks.python import BaseOptions
import streamlit as st

@st.cache_resource
def get_landmarker():
    """Cached MediaPipe PoseLandmarker instance."""
    model_path = "pose_landmarker_lite.task"
    options = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.IMAGE,
        min_pose_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return PoseLandmarker.create_from_options(options)

def extract_frame(video_path: str, frame_idx: int) -> np.ndarray | None:
    """Extract a single frame from video by index."""
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None
```

**Note on performance:** Opening VideoCapture per frame is acceptable for frame-by-frame navigation (user clicks prev/next). For future video playback scrubbing, consider caching the VideoCapture object. This is adequate for Phase 2 manual frame navigation.

**Confidence:** MEDIUM -- MediaPipe re-processing is straightforward, but `st.cache_resource` for the PoseLandmarker model needs validation (resource cleanup on session end).

### Anti-Patterns to Avoid

- **Running MediaPipe on every Streamlit rerun:** Cache the landmarker with `@st.cache_resource`. Never create a new PoseLandmarker instance inside the page body.
- **Loading entire video into memory:** Use `cv2.VideoCapture.set(CAP_PROP_POS_FRAMES, idx)` to seek to specific frames. Never read all frames into a list.
- **Computing metrics without caching:** Wrap `compute_all_metrics(set_dir)` with `@st.cache_data` keyed on set directory path. Metrics do not change for a completed recording.
- **Writing OSD overlay to saved MP4:** The saved video must be clean for MediaPipe re-processing. Draw OSD only on the display frame, not the recorded frame.
- **Mixing tab content outside `with tab:` blocks:** All content for a tab must be inside its `with tab:` context manager. Content outside runs on every tab.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| IMU noise filtering | Custom averaging filter | `scipy.signal.butter` + `filtfilt` (4th order, 10Hz) | Zero-phase distortion, standard in biomechanics, handles edge effects |
| Peak detection | Threshold-based peak finder | `scipy.signal.find_peaks(prominence=, distance=)` | Handles noise, provides peak properties (prominence, width), battle-tested |
| Gauge charts | HTML/CSS gauge + st.markdown | `plotly.graph_objects.Indicator(mode="gauge+number")` | Native Streamlit integration, interactive hover, FINA zone coloring via `gauge.steps` |
| Dual-axis chart | Two separate charts side-by-side | `plotly.subplots.make_subplots(specs=[[{"secondary_y": True}]])` | Shared X-axis with automatic alignment, professional dual-axis rendering |
| Video frame extraction | Manual byte-level MP4 parsing | `cv2.VideoCapture` + `CAP_PROP_POS_FRAMES` | Handles all codecs, hardware-accelerated seek on macOS |
| Correlation coefficient | Manual Pearson formula | `numpy.corrcoef(x, y)[0, 1]` | Handles NaN, numerical stability, one-line |
| Jerk computation | Manual finite differences | `numpy.gradient(signal)` | Handles uneven timesteps, second-order accurate central differences |
| Config threshold reading | Hardcoded values | `dashboard.config.load_config()["fina"]` | Already built in Phase 1, persists to config.toml, editable from dashboard sidebar |

**Key insight:** Phase 2 is primarily an integration and visualization phase. The hard math (tilt calculation, angle computation, correlation) was already solved in Phase 1 and the original analyze.py. Phase 2 composes these existing primitives into new metrics, adds scipy for signal processing, and wraps everything in Plotly visualizations.

## Common Pitfalls

### Pitfall 1: Butterworth Filter Crash on Short Data

**What goes wrong:** `scipy.signal.filtfilt` crashes with `ValueError: The length of the input vector x must be greater than padlen` when the IMU data has fewer samples than the filter's pad length (3 * max(len(a), len(b))).
**Why it happens:** Very short recordings (< 1 second) or corrupted CSVs with few rows.
**How to avoid:** Check `len(data) < 3 * max(len(a), len(b))` before calling filtfilt. Return unfiltered data as fallback.
**Warning signs:** Sets with < 200 IMU rows (< 3 seconds of data at 72.5Hz).

### Pitfall 2: VideoWriter Frame Size Mismatch

**What goes wrong:** `cv2.VideoWriter` silently produces 0-byte files if the frame dimensions passed to `.write()` don't match the dimensions specified in the constructor.
**Why it happens:** Camera rotation changes frame dimensions (e.g., 640x480 becomes 480x640 after 90-degree rotation). If VideoWriter is initialized before rotation is known, sizes mismatch.
**How to avoid:** Initialize VideoWriter AFTER the first frame is captured and rotated, using the actual frame dimensions. Store frame size as `(frame.shape[1], frame.shape[0])` -- note width-then-height order for VideoWriter.
**Warning signs:** video.mp4 file exists but is 0 bytes or unplayable.

### Pitfall 3: Streamlit st.tabs Rerun Behavior

**What goes wrong:** All tab content code runs on every rerun, not just the visible tab. Expensive computations inside a tab block still execute even when that tab is not displayed.
**Why it happens:** Streamlit renders all tab content server-side and sends it to the frontend; the frontend only shows the active tab but the server runs everything.
**How to avoid:** Move expensive computation OUTSIDE the tab blocks into cached functions. Only put rendering code (st.plotly_chart, st.image) inside tabs.
**Warning signs:** Report generation takes >3 seconds despite caching; the overhead is from multiple tabs all rendering.

### Pitfall 4: Session State Key Collision in Frame Navigation

**What goes wrong:** Frame navigation buttons (prev/next) don't work or jump to wrong frames because the session_state key `current_frame` conflicts with other widgets or is reset on tab switch.
**Why it happens:** Streamlit reruns the entire page on any interaction, including tab switches. If `current_frame` is not properly initialized or is overwritten by widget defaults.
**How to avoid:** Use namespaced session_state keys (e.g., `p2_current_frame`) and initialize them at the top of the page, outside tab blocks. Use callback functions for button clicks instead of checking `st.button` return values.
**Warning signs:** Frame counter resets to 0 when switching tabs; prev/next buttons require double-click.

### Pitfall 5: Timestamps Not Aligned Between IMU and Vision

**What goes wrong:** Fusion chart shows misaligned IMU and vision data; correlation coefficient is near 0 despite both signals being valid.
**Why it happens:** IMU timestamps start from BLE connection time; vision timestamps start from camera first frame. There is typically a small offset (10-100ms) between them.
**How to avoid:** Normalize both timestamp series to a common t=0 origin (the minimum timestamp across both files), exactly as analyze.py already does: `t0 = min(imu_t[0], vis_t[0])`. Use `np.interp` to resample IMU onto vision timestamps for correlation.
**Warning signs:** Fusion chart traces are visually similar in shape but horizontally offset.

### Pitfall 6: MediaPipe Model Path Resolution in Dashboard Context

**What goes wrong:** MediaPipe PoseLandmarker fails with "Cannot find model file" when running from `streamlit run dashboard/app.py` because the working directory differs from the project root.
**Why it happens:** The model file `pose_landmarker_lite.task` is at project root but Streamlit may change the CWD.
**How to avoid:** Use an absolute path resolved relative to the project root: `Path(__file__).parent.parent.parent / "pose_landmarker_lite.task"`. Or resolve relative to `dashboard/app.py` location.
**Warning signs:** `FileNotFoundError` for `pose_landmarker_lite.task` only when running via Streamlit, not in pytest.

## Code Examples

### Gauge Chart with FINA Zone Coloring

```python
# Source: Plotly official docs (plotly.com/python/gauge-charts/) + UI-SPEC contract
import plotly.graph_objects as go
from dashboard.components import CHART_THEME
from dashboard.config import load_config

def build_gauge(metric_name: str, value: float, max_value: float,
                target: float | None = None) -> go.Figure:
    """Build a single FINA-colored gauge chart."""
    cfg = load_config()["fina"]
    clean_thresh = cfg["clean_threshold_deg"]
    minor_thresh = cfg["minor_deduction_deg"]

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"font": {"size": 28, "family": "Source Sans Pro"}},
        title={"text": metric_name, "font": {"size": 14}},
        gauge={
            "axis": {"range": [0, max_value], "tickfont": {"size": 11}},
            "bar": {"color": "#0068C9"},
            "steps": [
                {"range": [0, clean_thresh], "color": "#09AB3B"},
                {"range": [clean_thresh, minor_thresh], "color": "#FACA2B"},
                {"range": [minor_thresh, max_value], "color": "#FF4B4B"},
            ],
            "threshold": {
                "line": {"color": "#262730", "width": 2},
                "thickness": 0.75,
                "value": target or 0,
            } if target else {},
        },
    ))
    fig.update_layout(
        height=200,
        margin={"l": 0, "r": 0, "t": 24, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        font_family=CHART_THEME["font_family"],
        font_color=CHART_THEME["font_color"],
    )
    return fig
```

### Fusion Dual-Axis Chart

```python
# Source: Plotly official docs (plotly.com/python/multiple-axes/)
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import numpy as np

def build_fusion_chart(time: np.ndarray, vision_angle: np.ndarray,
                       imu_tilt: np.ndarray) -> tuple[go.Figure, float]:
    """Build dual-axis fusion chart with correlation coefficient."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Scatter(
        x=time, y=vision_angle, name="视觉关节角度",
        line={"color": "#09AB3B", "width": 2},
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=time, y=imu_tilt, name="IMU 倾斜角",
        line={"color": "#0068C9", "width": 2},
    ), secondary_y=True)

    fig.update_layout(
        height=350,
        xaxis_title="时间 (秒)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        **{k: CHART_THEME[k] for k in ["template", "font_family", "font_color",
           "paper_bgcolor", "plot_bgcolor"]},
        margin={"l": 32, "r": 32, "t": 24, "b": 24},
    )
    fig.update_yaxes(title_text="视觉关节角度 (°)", secondary_y=False,
                     title_font_size=14, title_font_color="#09AB3B")
    fig.update_yaxes(title_text="IMU 倾斜角 (°)", secondary_y=True,
                     title_font_size=14, title_font_color="#0068C9")

    # Correlation: only where both have valid data
    mask = ~np.isnan(vision_angle) & ~np.isnan(imu_tilt)
    corr = float(np.corrcoef(vision_angle[mask], imu_tilt[mask])[0, 1]) if mask.sum() > 10 else None

    return fig, corr
```

### Skeleton Overlay Rendering

```python
# Source: Existing sync_recorder.py skeleton drawing pattern
import cv2
import numpy as np

POSE_CONNECTIONS = [
    (11,12),(11,13),(13,15),(12,14),(14,16),
    (11,23),(12,24),(23,24),(23,25),(24,26),
    (25,27),(26,28)
]

def render_skeleton_on_frame(frame: np.ndarray, landmarks: list,
                              color: tuple = (0, 255, 0),
                              line_width: int = 2) -> np.ndarray:
    """Draw MediaPipe pose skeleton on an OpenCV frame.

    Args:
        frame: BGR image (H, W, 3)
        landmarks: List of 33 landmarks with .x, .y, .visibility attributes
                   OR list of dicts with x, y, visibility keys (from CSV)
        color: BGR color tuple for skeleton lines
        line_width: Line thickness in pixels
    """
    h, w = frame.shape[:2]
    out = frame.copy()

    # Draw joints
    for lm in landmarks:
        x_val = lm.x if hasattr(lm, 'x') else lm['x']
        y_val = lm.y if hasattr(lm, 'y') else lm['y']
        vis = lm.visibility if hasattr(lm, 'visibility') else lm['vis']
        if vis > 0.5:
            px, py = int(x_val * w), int(y_val * h)
            cv2.circle(out, (px, py), 6, color, -1)

    # Draw connections
    for c1, c2 in POSE_CONNECTIONS:
        lm1, lm2 = landmarks[c1], landmarks[c2]
        vis1 = lm1.visibility if hasattr(lm1, 'visibility') else lm1['vis']
        vis2 = lm2.visibility if hasattr(lm2, 'visibility') else lm2['vis']
        if vis1 > 0.3 and vis2 > 0.3:
            x1 = lm1.x if hasattr(lm1, 'x') else lm1['x']
            y1 = lm1.y if hasattr(lm1, 'y') else lm1['y']
            x2 = lm2.x if hasattr(lm2, 'x') else lm2['x']
            y2 = lm2.y if hasattr(lm2, 'y') else lm2['y']
            p1 = (int(x1 * w), int(y1 * h))
            p2 = (int(x2 * w), int(y2 * h))
            cv2.line(out, p1, p2, color, line_width)

    return out
```

### 5-Metric Computation Orchestrator

```python
# dashboard/core/metrics.py
import numpy as np
import pandas as pd
from dashboard.core.analysis import calc_imu_tilt, smooth
from dashboard.core.angles import calc_angle

def compute_leg_height_index(landmarks_df: pd.DataFrame, frame_idx: int) -> float:
    """Compute leg height index from landmarks at a specific frame.

    Ratio: (ankle_y - reference) / (hip_y - ankle_y)
    In MediaPipe, Y increases downward. Higher ankle_y = lower physical position.
    For vertical legs: ankle is above hip, so ankle_y < hip_y in normalized coords.
    """
    row = landmarks_df.iloc[frame_idx]
    # Use right side (indices 24=hip, 28=ankle)
    hip_y = row["right_hip_y"]
    ankle_y = row["right_ankle_y"]

    if abs(hip_y - ankle_y) < 0.01:
        return 0.0

    # Higher ratio = better extension (ankle farther from hip)
    return float(abs(hip_y - ankle_y))

def compute_shoulder_knee_alignment(landmarks_df: pd.DataFrame, frame_idx: int) -> float:
    """Angle between shoulder-hip-knee line. 180 = perfectly straight."""
    row = landmarks_df.iloc[frame_idx]
    shoulder = (row["right_shoulder_x"], row["right_shoulder_y"])
    hip = (row["right_hip_x"], row["right_hip_y"])
    knee = (row["right_knee_x"], row["right_knee_y"])
    return calc_angle(shoulder, hip, knee)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| analyze.py matplotlib static plots | Plotly interactive dashboard charts | Phase 2 (now) | Coach can zoom, hover, interact with data instead of viewing static PNG |
| Single elbow angle in vision.csv | Full 33-landmark landmarks.csv | Phase 2 (now) | Enables skeleton overlay, keyframe comparison, multiple joint metrics |
| No video recording | MP4 saved alongside CSVs | Phase 2 (now) | Enables visual analysis tab, skeleton overlay playback in dashboard |
| Manual `python analyze.py` CLI | Auto-generated report on set selection | Phase 2 (now) | Zero-friction analysis workflow for coaches |
| Raw angle values only | FINA deduction mapping with zone colors | Phase 2 (now) | Translates engineering data into coaching/judging language |

**Deprecated/outdated:**
- `analyze.py` static matplotlib plot: Still works for CLI use but dashboard replaces it for interactive analysis
- `vision.csv` single-angle format: Kept for backward compatibility but `landmarks.csv` is the new primary vision data file

## Open Questions

1. **VideoWriter frame size with rotation**
   - What we know: Camera outputs at one resolution, user rotates with F key, rotation changes dimensions
   - What's unclear: Whether to initialize VideoWriter after first rotation is applied, or store rotation and apply on playback
   - Recommendation: Initialize VideoWriter lazily after first rotated frame is captured. Store the actual frame dimensions used.

2. **Leg height index water line reference**
   - What we know: CONTEXT.md specifies `(ankle_y - water_line) / (hip_y - ankle_y)` but there is no water_line sensor
   - What's unclear: How to determine water_line without explicit sensor data
   - Recommendation: For MVP, use the hip Y position as the reference baseline (hip-to-ankle distance ratio). The water line detection can be added later via image segmentation or manual config. Document this simplification.

3. **Standard template for keyframe comparison**
   - What we know: "Historical best + coach override" is the template source
   - What's unclear: How to identify "historical best" automatically before there is trend data (Phase 3)
   - Recommendation: For Phase 2, start with a configurable target angle set in config.toml (e.g., `fina.target_leg_deviation_deg = 5`). Add historical best selection in Phase 3 when multi-set data is available.

4. **Plotly version gap: installed 6.3.0 vs pinned 6.6.0**
   - What we know: requirements.txt pins 6.6.0 but .venv has 6.3.0. Both support go.Indicator gauge mode.
   - What's unclear: Whether the venv will be updated before Phase 2 execution
   - Recommendation: Run `pip install -r requirements.txt` at the start of Phase 2 to ensure pinned versions match. The gauge API is stable across 6.x.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 (installed in .venv) |
| Config file | None (implicit discovery; tests/ directory) |
| Quick run command | `.venv/bin/python -m pytest tests/ -x -q` |
| Full suite command | `.venv/bin/python -m pytest tests/ -v` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ANAL-01 | 5 metric computation returns valid floats | unit | `.venv/bin/python -m pytest tests/test_scoring.py -x` | No -- Wave 0 |
| ANAL-02 | FINA deduction thresholds applied correctly | unit | `.venv/bin/python -m pytest tests/test_scoring.py::test_fina_deductions -x` | No -- Wave 0 |
| ANAL-03 | Phase timeline produces 3 segments | unit | `.venv/bin/python -m pytest tests/test_phase_detect.py -x` | No -- Wave 0 |
| ANAL-04 | Phase detection finds peaks in synthetic IMU | unit | `.venv/bin/python -m pytest tests/test_phase_detect.py::test_detect_phases_synthetic -x` | No -- Wave 0 |
| ANAL-05 | Keyframe comparison renders overlay image | integration | `.venv/bin/python -m pytest tests/test_skeleton.py -x` | No -- Wave 0 |
| ANAL-06 | Report generation completes under 3 seconds | integration | `.venv/bin/python -m pytest tests/test_scoring.py::test_report_timing -x` | No -- Wave 0 |
| VIZ-01 | Gauge chart builds with valid Plotly figure | unit | `.venv/bin/python -m pytest tests/test_charts.py::test_gauge_chart -x` | No -- Wave 0 |
| VIZ-02 | IMU waveform chart has 3 traces | unit | `.venv/bin/python -m pytest tests/test_charts.py::test_imu_waveform -x` | No -- Wave 0 |
| VIZ-03 | Skeleton overlay renders on frame | unit | `.venv/bin/python -m pytest tests/test_skeleton.py::test_render_skeleton -x` | No -- Wave 0 |
| VIZ-04 | Fusion chart has dual Y-axes and correlation | unit | `.venv/bin/python -m pytest tests/test_charts.py::test_fusion_chart -x` | No -- Wave 0 |

### Sampling Rate

- **Per task commit:** `.venv/bin/python -m pytest tests/ -x -q`
- **Per wave merge:** `.venv/bin/python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_scoring.py` -- covers ANAL-01, ANAL-02, ANAL-06 (scoring engine, FINA deductions, timing)
- [ ] `tests/test_phase_detect.py` -- covers ANAL-03, ANAL-04 (phase detection, peak finding)
- [ ] `tests/test_skeleton.py` -- covers ANAL-05, VIZ-03 (skeleton rendering, keyframe comparison)
- [ ] `tests/test_charts.py` -- covers VIZ-01, VIZ-02, VIZ-04 (gauge, waveform, fusion charts)
- [ ] `tests/test_landmarks.py` -- covers landmark CSV format, load/save roundtrip
- [ ] `tests/conftest.py` -- shared fixtures: synthetic IMU DataFrame, synthetic landmarks DataFrame, sample config dict

## Sources

### Primary (HIGH confidence)
- [Plotly Gauge Charts](https://plotly.com/python/gauge-charts/) -- go.Indicator gauge mode, steps, threshold
- [Plotly Multiple Axes](https://plotly.com/python/multiple-axes/) -- make_subplots secondary_y
- [Plotly go.Indicator API Reference](https://plotly.github.io/plotly.py-docs/generated/plotly.graph_objects.Indicator.html) -- full parameter documentation
- [SciPy find_peaks](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html) -- prominence, distance, width parameters
- [SciPy Butterworth](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html) -- filter design for IMU
- [MediaPipe Pose Landmarks](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker) -- 33 landmark indices and names
- [MediaPipe Python PoseLandmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python) -- Tasks API usage
- [Streamlit st.tabs](https://docs.streamlit.io/develop/api-reference/layout/st.tabs) -- tab layout API
- [Streamlit Session State](https://docs.streamlit.io/develop/concepts/architecture/session-state) -- state management
- [Streamlit Caching](https://docs.streamlit.io/develop/concepts/architecture/caching) -- cache_data, cache_resource

### Secondary (MEDIUM confidence)
- [OpenCV VideoWriter macOS codecs](https://gist.github.com/takuma7/44f9ecb028ff00e2132e) -- macOS codec compatibility (verified on this system)
- [Generating MP4s with avc1 codec](https://swiftlane.com/blog/generating-mp4s-using-opencv-python-with-the-avc1-codec/) -- avc1 fourcc usage pattern
- [Gyroscope Vector Magnitude](https://www.medrxiv.org/content/10.1101/2022.10.05.22280752v1.full) -- GVM for biomechanics angular velocity
- [IMU Step Detection](https://dganesan.github.io/mhealth-course/chapter2-steps/ch2-stepcounter.html) -- find_peaks on accelerometer data

### Tertiary (LOW confidence)
- [Movement smoothness Python repo](https://github.com/siva82kb/smoothness) -- jerk-based smoothness metrics (academic, not verified against this use case)

### Local Verification (HIGH confidence)
- Codec test: `avc1` fourcc verified working with opencv-contrib-python 4.10.0 on macOS Apple Silicon (2026-03-23)
- Installed packages verified: scipy 1.15.3, plotly 6.3.0, mediapipe 0.10.33, pandas 2.2.3, numpy 1.26.4
- Existing tests: 20 tests passing in tests/ directory (test_analysis, test_angles, test_config, test_data_loader, test_scaffold)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and verified working
- Architecture: HIGH -- patterns build directly on existing Phase 1 code with well-documented library APIs
- Pitfalls: HIGH -- identified from direct code inspection and Streamlit/OpenCV documentation
- Scoring engine: MEDIUM -- metric formulas are well-defined but some require real data validation (leg height index water line simplification)
- Phase detection: MEDIUM -- find_peaks parameters (prominence=0.3, distance=72) need tuning on real swimming IMU data

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (30 days -- stable stack, no fast-moving dependencies)
