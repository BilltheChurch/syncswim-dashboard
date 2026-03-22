# Phase 2: Single-Set Analysis - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

After selecting a recorded set, the training page generates a complete analysis report with: 5-metric scoring card (gauges + numbers), action phase timeline (3 phases with manual slider adjust), keyframe comparison (wireframe overlay), joint angle gauges, IMU waveform charts, and dual-axis sensor fusion chart. Also requires expanding the recording pipeline to save video (MP4) and full 33-landmark data.

</domain>

<decisions>
## Implementation Decisions

### Scoring Card Metrics
- 5 metrics displayed as Plotly gauge charts + small metric numbers below each gauge
- Per-metric FINA deduction shown on each gauge (e.g., "-0.2") + overall estimated score out of 10 at top
- Standard template source: historical best set as default, coach can override target angles per session
- **Leg vertical deviation**: IMU tilt angle vs 90° vertical (from calc_imu_tilt)
- **Leg height index**: MediaPipe hip-to-ankle Y ratio — (ankle_y - water_line) / (hip_y - ankle_y)
- **Shoulder-knee alignment**: angle between shoulder, hip, and knee landmarks from MediaPipe
- **Smoothness**: Jerk metric using combined gyroscope magnitude sqrt(gx²+gy²+gz²) derivative
- **Exhibition hold stability**: standard deviation of tilt angle during exhibition phase

### Phase Detection
- Start with 3 phases: prep / active / recovery (expand to 5 later)
- Auto-detection from IMU signal peaks + manual slider adjustment for fine-tuning boundaries
- Phase quality color coding uses FINA zone colors: green=good / yellow=minor / red=major
- Timeline displayed as horizontal bar chart with colored segments

### Report Layout
- Training page organized as tabs within the page:
  - **Tab 1: Overview** — scoring card (5 gauges) + phase timeline
  - **Tab 2: Visual** — keyframe comparison + skeleton overlay playback
  - **Tab 3: Sensor** — angle gauges + IMU waveform + fusion chart
- Report auto-generates within 3 seconds of set selection

### Claude's Discretion — Scoring Card Persistence
- Whether scoring card appears as persistent header on all tabs or only on Overview tab
- Claude decides based on screen real estate and information density

### Skeleton Overlay
- Re-run MediaPipe on saved video to generate skeleton overlay frames in dashboard
- Keyframe comparison: green wireframe = standard template, red wireframe = actual pose, both overlaid on same video frame, deviation angles labeled
- Displayed via st.image for key frames, frame-by-frame navigation controls

### Video Recording Integration
- sync_recorder.py modified to save MP4 alongside CSVs
- Video starts/stops simultaneously with BLE recording (Button A trigger)
- MP4 file saved in same set directory: `data/set_NNN_YYYYMMDD_HHMMSS/video.mp4`
- Uses OpenCV VideoWriter with H.264 codec on macOS

### Landmark CSV Expansion
- Current vision.csv only saves timestamp + elbow angle — insufficient for skeleton overlay
- Expand to save all 33 MediaPipe landmarks per frame
- CSV format: Claude decides between wide format (100+ columns) or separate landmarks.csv (long format) based on pandas loading efficiency and Plotly rendering needs

### FINA Scoring Display
- Per-metric deduction on each gauge (e.g., "-0.2" annotation)
- Overall estimated execution score out of 10 at top of scoring card
- Score calculated by starting at 10.0, subtracting per-metric deductions based on config.toml thresholds

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — Core value, requirements, FINA scoring rules
- `.planning/REQUIREMENTS.md` — ANAL-01~06, VIZ-01~04 detailed specs
- `.planning/ROADMAP.md` — Phase 2 success criteria (5 items)

### Phase 1 Context
- `.planning/phases/01-foundation-environment/01-CONTEXT.md` — Project structure, shared lib, config decisions

### Research
- `.planning/research/STACK.md` — Plotly 6.5 gauge patterns, pandas integration
- `.planning/research/FEATURES.md` — FINA scoring rules, table stakes features
- `.planning/research/ARCHITECTURE.md` — st.fragment for live updates, component separation

### Existing Code
- `dashboard/core/analysis.py` — calc_imu_tilt(), smooth() already extracted
- `dashboard/core/angles.py` — calc_angle() already extracted
- `dashboard/core/data_loader.py` — load_imu(), load_vision() already built
- `dashboard/config.py` — load_config() for FINA thresholds
- `dashboard/components/__init__.py` — CHART_THEME constant
- `dashboard/pages/training.py` — Existing training page (metadata card, placeholder sections)
- `sync_recorder.py` — Recording pipeline that needs MP4 + landmark expansion
- `vision.py` — MediaPipe detection code (reference for re-running in dashboard)
- `analyze.py` — Original analysis code (reference for correlation computation)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `dashboard/core/analysis.py`: calc_imu_tilt() and smooth() — direct input for leg deviation and smoothness metrics
- `dashboard/core/angles.py`: calc_angle() — reusable for shoulder-knee alignment computation
- `dashboard/core/data_loader.py`: load_imu(), load_vision() — return pandas DataFrames ready for charting
- `dashboard/components/__init__.py`: CHART_THEME — Plotly theme constants for consistent styling
- `dashboard/config.py`: load_config() — FINA thresholds for scoring zones
- `vision.py`: MjpegStreamReader + MediaPipe PoseLandmarker setup — reference for re-running detection in dashboard

### Established Patterns
- Pandas DataFrames for all data (Phase 1 decision)
- Plotly for all charts with CHART_THEME (Phase 1 decision)
- TOML config for thresholds (Phase 1 decision)
- session_state keys for widget state management (Phase 1 fix)
- `st.tabs()` for sub-page organization (new pattern for Phase 2)

### Integration Points
- Training page (`dashboard/pages/training.py`) — report renders below metadata card when set selected
- Config FINA thresholds — scoring card reads `config["fina"]` for zone boundaries
- Data directory — new video.mp4 and expanded landmarks data alongside existing CSVs
- sync_recorder.py — needs modification for MP4 output + landmark CSV (this modifies existing scripts)

</code_context>

<specifics>
## Specific Ideas

- FINA scoring: 10.0 base, subtract deductions per metric based on angle deviation thresholds
- 3-phase detection (prep/active/recovery) is MVP; 5-phase expansion deferred to later iteration
- Coach can override target angles in settings — stored in config.toml alongside FINA thresholds
- Keyframe comparison overlay: green wireframe = ideal, red wireframe = actual, both on same frame

</specifics>

<deferred>
## Deferred Ideas

- 5-phase detection (prep/entry/lift/exhibition/descent) — expand from 3-phase after validating detection algorithm
- Video playback scrubber with synchronized IMU waveform cursor — complex UI, defer to later iteration
- Automatic "best moment" keyframe selection — start with manual frame navigation, auto-select later

</deferred>

---

*Phase: 02-single-set-analysis*
*Context gathered: 2026-03-22*
