# Artistic Swimming Pose Detection — Design Document

**Date**: 2026-04-06
**Status**: Approved
**Approach**: Plan B (dual IMU + vision independent calculation, fusion at scoring/visualization layer)
**Ultimate Goal**: Plan C (Kalman filter deep fusion, to be built on top of Plan B)

## Context

### Problem
Current system only calculates right elbow angle (Shoulder→Elbow→Wrist). Scoring engine uses proxy values for leg and alignment metrics. Academic papers on artistic swimming demonstrate that **leg deviation angle** and **leg height index** are the strongest predictors of competition scores.

### Hardware
- **NODE_A1**: M5StickC Plus2, worn on **forearm**, 72.5Hz IMU
- **NODE_L1**: M5StickC Plus2, worn on **shin** (new), 72.5Hz IMU
- **Camera**: DroidCam iOS, ~26fps via MJPEG stream
- **Pose Model**: MediaPipe PoseLandmarker Lite (33 landmarks)

### Papers Referenced
1. Cao & Sun (2024) — Swim training with MediaPipe for dive starts (arm/leg angles, launch angle)
2. Edriss et al. (2024) — MediaPipe validation for ballet leg and barracuda (leg deviation, shoulder-knee angle)
3. Yue et al. (2023) — Hybrid figures in team free routines (leg height index, leg angle deviation, movement frequency)

## Module 1: Hardware & Data Layer

### Dual IMU Support

Data directory structure change:
```
set_001_YYYYMMDD_HHMMSS/
  imu_NODE_A1.csv     # forearm IMU (existing)
  imu_NODE_L1.csv     # shin IMU (new)
  vision.csv          # vision data (existing)
  landmarks.csv       # 33-point skeleton (existing)
  video.mp4           # video (existing)
```

### data_loader Changes

```python
# Current: hardcoded single IMU
load_imu(set_dir) → DataFrame

# New: node-aware loading
load_imu(set_dir, node="NODE_A1") → DataFrame
load_imu(set_dir, node="NODE_L1") → DataFrame
load_all_imus(set_dir) → dict[str, DataFrame]
```

### config.toml Additions

```toml
[hardware]
imu_nodes = ["NODE_A1", "NODE_L1"]
node_placement = { NODE_A1 = "forearm", NODE_L1 = "shin" }
```

## Module 2: Angle Calculation Engine

### 2.1 IMU Angle Calculations (Two Independent Streams)

```python
# Forearm IMU (NODE_A1) — existing
calc_forearm_tilt(imu_df) → np.ndarray
  # atan2(ax, sqrt(ay² + az²)) → forearm tilt angle
  # Maps to: elbow flexion/extension

# Shin IMU (NODE_L1) — new
calc_shin_tilt(imu_df) → np.ndarray
  # Same tilt formula
  # Maps to: leg vertical deviation (90° = perfectly vertical)
```

Both reuse the existing `calc_imu_tilt()` with semantic naming.

### 2.2 Vision Angle Calculations (Upgrade from Proxy to Real)

New functions operating on landmarks.csv:

```python
calc_leg_deviation_angle(landmarks_df) → np.ndarray
  # Hip(23/24) → Ankle(27/28) vs vertical reference line
  # 0° = perfect vertical

calc_knee_extension(landmarks_df) → np.ndarray
  # Hip(23/24) → Knee(25/26) → Ankle(27/28)
  # 180° = fully extended

calc_shoulder_knee_angle(landmarks_df) → np.ndarray
  # Shoulder(11/12) → Hip(23/24) → Knee(25/26)
  # 180° = straight body line

calc_leg_symmetry(landmarks_df) → np.ndarray
  # |left leg deviation - right leg deviation|
  # 0° = perfect symmetry (for barracuda)

calc_trunk_vertical(landmarks_df) → np.ndarray
  # Shoulder(11/12) → Hip(23/24) vs vertical reference
  # Measures trunk verticality
```

### 2.3 Data Source Priority

| Metric | Primary Source | Fallback | Fusion |
|--------|---------------|----------|--------|
| Leg vertical deviation | Shin IMU (72Hz) | Vision Hip→Ankle | Cross-validate correlation |
| Arm/elbow angle | Forearm IMU (72Hz) | Vision Shoulder→Elbow→Wrist | Already implemented |
| Knee extension | Vision only | — | — |
| Leg symmetry | Vision only | — | — |
| Trunk vertical | Vision only | — | — |
| Smoothness | Dual IMU | — | — |
| Stability | Dual IMU | — | — |

## Module 3: Scoring Engine Refactoring

### 3.1 Metric System: 5 → 8 Metrics

| # | Metric | Source | Calculation | Paper Reference |
|---|--------|--------|-------------|-----------------|
| 1 | Leg vertical deviation | Shin IMU + Vision | IMU shin tilt deviation from 90° + Vision Hip→Ankle deviation | Papers 2&3 core |
| 2 | Leg height index | Vision | Pixel ratio knee-to-toe above water (AB/AC) | Paper 3 strongest predictor |
| 3 | Knee extension | Vision | Hip→Knee→Ankle angle, 180°=full marks | Paper 2 implicit |
| 4 | Shoulder-knee alignment | Vision | Shoulder→Hip→Knee angle, 180°=straight line | Paper 2 r=-0.444 |
| 5 | Trunk verticality | Vision | Shoulder→Hip vs vertical reference | Paper 2 body stability |
| 6 | Leg symmetry | Vision | Left-right leg deviation difference | Barracuda scoring |
| 7 | Movement smoothness | Dual IMU | Gyroscope jerk (existing logic, extended to dual node) | IMU advantage |
| 8 | Pose stability | Dual IMU | Tilt angle std dev during exhibition phase (existing, extended) | IMU advantage |

### 3.2 Per-Metric FINA Thresholds

```toml
[fina.leg_deviation]
clean = 5
minor = 15
major = 30

[fina.knee_extension]
clean = 170    # >170° = nearly straight
minor = 155
major = 140

[fina.leg_symmetry]
clean = 5
minor = 15
major = 30
```

### 3.3 Scoring Engine Interface

```python
# Current
compute_set_report(imu_df, vision_df, config) → SetReport

# New
compute_set_report(
    arm_imu_df,       # forearm IMU (NODE_A1)
    leg_imu_df,       # shin IMU (NODE_L1), may be None
    vision_df,        # vision.csv
    landmarks_df,     # landmarks.csv, may be None
    config,
) → SetReport
```

Graceful degradation when data sources are missing.

## Module 4: Fusion Visualization

### 4.1 Chart Changes

**Modified charts:**
- IMU waveform: single node → dual node toggle/overlay (NODE_A1 or NODE_L1)
- Fusion chart: new shin IMU tilt vs vision Hip→Ankle fusion comparison
- Gauge charts: 5 → 8 gauges, grouped by category

**New charts:**
- Body alignment diagram: simplified stick figure with color-coded joint deviations
- Dual-source comparison panel: IMU value vs vision value side-by-side + correlation badge

### 4.2 Training Page Tab Reorganization

```
Current: [Overview] [Visual Analysis] [Sensors]
New:     [Overview] [Leg Analysis] [Arm Analysis] [Sensor Fusion]
```

| Tab | Content |
|-----|---------|
| Overview | 8-metric scoring card + phase timeline + total score |
| Leg Analysis | Leg deviation time series, knee extension, leg symmetry, skeleton overlay (lower body focus), shin IMU vs vision fusion |
| Arm Analysis | Elbow angle, shoulder-knee alignment, trunk verticality, skeleton overlay (upper body focus), forearm IMU vs vision fusion |
| Sensor Fusion | Dual IMU waveform overlay, IMU-vision correlation matrix, data quality metrics (sampling rate, packet loss, coverage) |

### 4.3 Plan C Transition Placeholder

Reserve area in Sensor Fusion tab:
```
[Advanced Fusion] — Plan C phase
  - Kalman filter optimal angle estimate vs raw values
  - Fusion gain visualization (IMU contribution vs vision contribution weights)
```

Shows "Coming Soon" during Plan B phase.

## Graceful Degradation Matrix

| Available Data | Behavior |
|----------------|----------|
| All 4 sources (arm IMU + leg IMU + vision + landmarks) | Full 8-metric scoring + all fusion charts |
| No leg IMU | Leg deviation from vision only, smoothness/stability from arm IMU only |
| No landmarks.csv | Use vision.csv angle_deg as proxy (current behavior) |
| No vision at all | IMU-only metrics (deviation, smoothness, stability), skip visual metrics |
| Only arm IMU | Current Phase 2 behavior (backward compatible) |

## Implementation Scope

This design affects:
- `dashboard/core/data_loader.py` — dual IMU loading
- `dashboard/core/analysis.py` — new vision angle functions
- `dashboard/core/scoring.py` — 8-metric engine refactor
- `dashboard/core/landmarks.py` — landmark-based angle extraction
- `dashboard/components/waveform_chart.py` — dual node support
- `dashboard/components/gauge_chart.py` — 8 gauge layout
- `dashboard/pages/training.py` — 4-tab reorganization
- `config.toml` — per-metric FINA thresholds + dual IMU config
- `tests/` — new tests for all new calculations
