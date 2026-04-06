# Artistic Swimming Pose Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the dashboard from single-elbow-angle analysis to full artistic swimming pose detection with dual IMU fusion and 8 biomechanical metrics based on FINA scoring rules.

**Architecture:** Four-layer upgrade: (1) data_loader supports dual IMU nodes, (2) new vision angle calculations from landmarks.csv, (3) scoring engine expands from 5 to 8 metrics with per-metric FINA thresholds, (4) training page reorganized into 4 tabs with body-part-focused analysis. Each layer is independently testable and backward compatible when data sources are missing.

**Tech Stack:** Python 3.12, Streamlit, MediaPipe PoseLandmarker, Plotly, NumPy, pandas, scipy, pytest

---

### Task 1: Dual IMU Data Loader

**Files:**
- Modify: `dashboard/core/data_loader.py:13-29` (load_imu function)
- Modify: `dashboard/core/data_loader.py:83-84,92-101` (build_sessions_index IMU detection)
- Modify: `config.toml`
- Test: `tests/test_data_loader.py`

**Step 1: Write the failing tests**

```python
# tests/test_data_loader.py — add these tests

def test_load_imu_with_node_param(tmp_path):
    """load_imu with node parameter loads the correct file."""
    csv = tmp_path / "imu_NODE_L1.csv"
    csv.write_text("timestamp_local,ax,ay,az,gx,gy,gz\n1.0,0.1,0.2,9.8,1,2,3\n")
    df = load_imu(str(tmp_path), node="NODE_L1")
    assert len(df) == 1
    assert df["ax"].iloc[0] == pytest.approx(0.1)


def test_load_imu_default_node_backward_compat(tmp_path):
    """load_imu without node parameter defaults to NODE_A1."""
    csv = tmp_path / "imu_NODE_A1.csv"
    csv.write_text("timestamp_local,ax,ay,az,gx,gy,gz\n1.0,0.5,0.3,9.8,10,10,5\n")
    df = load_imu(str(tmp_path))
    assert len(df) == 1


def test_load_imu_missing_node_returns_empty(tmp_path):
    """load_imu for non-existent node returns empty DataFrame."""
    df = load_imu(str(tmp_path), node="NODE_L1")
    assert df.empty


def test_load_all_imus(tmp_path):
    """load_all_imus returns dict of node_name -> DataFrame."""
    for node in ["NODE_A1", "NODE_L1"]:
        csv = tmp_path / f"imu_{node}.csv"
        csv.write_text("timestamp_local,ax,ay,az,gx,gy,gz\n1.0,0.1,0.2,9.8,1,2,3\n")
    result = load_all_imus(str(tmp_path))
    assert "NODE_A1" in result
    assert "NODE_L1" in result
    assert len(result["NODE_A1"]) == 1


def test_load_all_imus_partial(tmp_path):
    """load_all_imus with only one node file returns only that node."""
    csv = tmp_path / "imu_NODE_A1.csv"
    csv.write_text("timestamp_local,ax,ay,az,gx,gy,gz\n1.0,0.1,0.2,9.8,1,2,3\n")
    result = load_all_imus(str(tmp_path))
    assert "NODE_A1" in result
    assert "NODE_L1" not in result
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/billthechurch/Downloads/test_rec && python -m pytest tests/test_data_loader.py -v -k "node" 2>&1 | tail -20`
Expected: FAIL — `load_imu() got unexpected keyword argument 'node'`

**Step 3: Implement dual IMU loader**

In `dashboard/core/data_loader.py`, change `load_imu`:

```python
def load_imu(set_dir: str, node: str = "NODE_A1") -> pd.DataFrame:
    """Load IMU CSV as DataFrame for a specific node.

    Args:
        set_dir: Path to the set directory.
        node: IMU node name (default "NODE_A1" for backward compatibility).

    Returns:
        DataFrame with IMU columns. Empty DataFrame if file missing.
    """
    path = os.path.join(set_dir, f"imu_{node}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path, on_bad_lines="warn")
    except Exception:
        return pd.DataFrame()


def load_all_imus(set_dir: str) -> dict[str, pd.DataFrame]:
    """Load all available IMU CSVs from a set directory.

    Scans for files matching imu_*.csv pattern.

    Returns:
        Dict mapping node name to DataFrame. Only includes nodes with data.
    """
    result = {}
    set_path = Path(set_dir)
    for csv_file in sorted(set_path.glob("imu_*.csv")):
        node_name = csv_file.stem.replace("imu_", "")  # "imu_NODE_A1" -> "NODE_A1"
        try:
            df = pd.read_csv(str(csv_file), on_bad_lines="warn")
            if not df.empty:
                result[node_name] = df
        except Exception:
            continue
    return result
```

Update `build_sessions_index` to detect both IMU nodes: change `has_imu` logic to scan for all `imu_*.csv` files and store node names, and update duration calculation to use any available IMU file.

**Step 4: Update config.toml**

```toml
[hardware]
camera_url = "http://192.168.66.169:4747/video"
ble_device_name = "NODE_A1"
ble_char_uuid = "abcd1234-ab12-cd34-ef56-abcdef123456"
imu_nodes = ["NODE_A1", "NODE_L1"]
node_placement = { NODE_A1 = "forearm", NODE_L1 = "shin" }
```

**Step 5: Run tests to verify they pass**

Run: `cd /Users/billthechurch/Downloads/test_rec && python -m pytest tests/test_data_loader.py -v 2>&1 | tail -20`
Expected: All PASS

**Step 6: Commit**

```bash
git add dashboard/core/data_loader.py tests/test_data_loader.py config.toml
git commit -m "feat: dual IMU data loader with node parameter and load_all_imus"
```

---

### Task 2: Vision Angle Calculations from Landmarks

**Files:**
- Create: `dashboard/core/vision_angles.py`
- Test: `tests/test_vision_angles.py`

**Step 1: Write the failing tests**

```python
# tests/test_vision_angles.py
"""Tests for vision-based angle calculations from landmarks DataFrame."""
import numpy as np
import pandas as pd
import pytest

from dashboard.core.vision_angles import (
    calc_leg_deviation_vision,
    calc_knee_extension,
    calc_shoulder_knee_angle,
    calc_leg_symmetry,
    calc_trunk_vertical,
)


def _make_landmarks_df(n_frames=10, **overrides):
    """Create a synthetic landmarks DataFrame.

    Default: person standing upright (shoulder above hip above knee above ankle).
    Normalized coords (0-1), y increases downward in image.
    """
    df = pd.DataFrame({"timestamp_local": np.linspace(0, 1, n_frames), "frame": range(n_frames)})

    # Default: upright standing pose (all frames identical)
    defaults = {
        "left_shoulder_x": 0.45, "left_shoulder_y": 0.3, "left_shoulder_z": 0, "left_shoulder_vis": 0.9,
        "right_shoulder_x": 0.55, "right_shoulder_y": 0.3, "right_shoulder_z": 0, "right_shoulder_vis": 0.9,
        "left_hip_x": 0.45, "left_hip_y": 0.5, "left_hip_z": 0, "left_hip_vis": 0.9,
        "right_hip_x": 0.55, "right_hip_y": 0.5, "right_hip_z": 0, "right_hip_vis": 0.9,
        "left_knee_x": 0.45, "left_knee_y": 0.7, "left_knee_z": 0, "left_knee_vis": 0.9,
        "right_knee_x": 0.55, "right_knee_y": 0.7, "right_knee_z": 0, "right_knee_vis": 0.9,
        "left_ankle_x": 0.45, "left_ankle_y": 0.9, "left_ankle_z": 0, "left_ankle_vis": 0.9,
        "right_ankle_x": 0.55, "right_ankle_y": 0.9, "right_ankle_z": 0, "right_ankle_vis": 0.9,
    }
    defaults.update(overrides)
    for col, val in defaults.items():
        df[col] = val
    return df


class TestLegDeviation:
    def test_vertical_leg_zero_deviation(self):
        """Leg pointing straight down (standing) has ~0 deviation from vertical."""
        df = _make_landmarks_df()
        result = calc_leg_deviation_vision(df)
        assert isinstance(result, np.ndarray)
        assert len(result) == 10
        assert np.all(result < 5.0)  # nearly vertical

    def test_angled_leg_nonzero_deviation(self):
        """Leg angled 45 degrees from vertical has ~45 degree deviation."""
        df = _make_landmarks_df(
            right_hip_x=0.5, right_hip_y=0.5,
            right_ankle_x=0.8, right_ankle_y=0.8,  # 45 deg diagonal
        )
        result = calc_leg_deviation_vision(df)
        assert np.mean(result) > 30.0  # clearly angled


class TestKneeExtension:
    def test_straight_leg_near_180(self):
        """Hip-knee-ankle in a straight line gives ~180 degrees."""
        df = _make_landmarks_df()  # default: all aligned vertically
        result = calc_knee_extension(df)
        assert np.all(result > 170.0)

    def test_bent_knee_less_than_180(self):
        """Bent knee gives angle less than 180."""
        df = _make_landmarks_df(
            right_knee_x=0.65, right_knee_y=0.7,  # knee pushed outward
        )
        result = calc_knee_extension(df)
        assert np.mean(result) < 170.0


class TestShoulderKneeAngle:
    def test_straight_body_near_180(self):
        """Shoulder-hip-knee aligned gives ~180."""
        df = _make_landmarks_df()
        result = calc_shoulder_knee_angle(df)
        assert np.all(result > 170.0)


class TestLegSymmetry:
    def test_symmetric_legs_near_zero(self):
        """Symmetric leg positions give ~0 difference."""
        df = _make_landmarks_df()
        result = calc_leg_symmetry(df)
        assert np.all(result < 5.0)

    def test_asymmetric_legs_nonzero(self):
        """One leg angled, other straight, gives nonzero difference."""
        df = _make_landmarks_df(
            right_ankle_x=0.8, right_ankle_y=0.8,  # right leg angled
            # left leg stays vertical
        )
        result = calc_leg_symmetry(df)
        assert np.mean(result) > 20.0


class TestTrunkVertical:
    def test_upright_trunk_near_zero(self):
        """Shoulder directly above hip gives ~0 deviation."""
        df = _make_landmarks_df()
        result = calc_trunk_vertical(df)
        assert np.all(result < 5.0)

    def test_leaning_trunk_nonzero(self):
        """Shoulder offset from hip gives nonzero deviation."""
        df = _make_landmarks_df(
            right_shoulder_x=0.75, right_shoulder_y=0.25,  # leaning
        )
        result = calc_trunk_vertical(df)
        assert np.mean(result) > 10.0
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/billthechurch/Downloads/test_rec && python -m pytest tests/test_vision_angles.py -v 2>&1 | tail -20`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.core.vision_angles'`

**Step 3: Implement vision angle calculations**

```python
# dashboard/core/vision_angles.py
"""Vision-based angle calculations from landmarks DataFrame.

Computes biomechanical angles for artistic swimming analysis using
MediaPipe 33-point pose landmarks stored in landmarks.csv.
"""
import math

import numpy as np
import pandas as pd

from dashboard.core.angles import calc_angle


def _angle_from_vertical(x1: float, y1: float, x2: float, y2: float) -> float:
    """Compute angle between line (x1,y1)-(x2,y2) and vertical axis.

    In image coordinates, vertical is along y-axis (downward).

    Returns:
        Angle in degrees. 0 = perfectly vertical.
    """
    dx = x2 - x1
    dy = y2 - y1
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-9:
        return 0.0
    # angle between vector and (0, 1) i.e. straight down
    cos_angle = abs(dy) / length
    return math.degrees(math.acos(min(cos_angle, 1.0)))


def _per_frame_angle(df: pd.DataFrame, joint_cols: list[tuple[str, str, str, str, str, str]],
                     func) -> np.ndarray:
    """Apply a function per frame using specified landmark columns.

    Args:
        df: landmarks DataFrame
        joint_cols: column name groups to extract
        func: function that takes extracted values and returns angle

    Returns:
        numpy array of angles, one per frame
    """
    angles = []
    for _, row in df.iterrows():
        angles.append(func(row))
    return np.array(angles)


def calc_leg_deviation_vision(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Compute leg deviation from vertical for each frame.

    Measures angle between Hip->Ankle line and vertical axis.
    0 degrees = leg perfectly vertical (ideal for ballet leg/barracuda).

    Args:
        df: landmarks DataFrame with hip and ankle columns.
        side: "right" or "left" (default "right").

    Returns:
        numpy array of deviation angles in degrees.
    """
    hip_x = f"{side}_hip_x"
    hip_y = f"{side}_hip_y"
    ankle_x = f"{side}_ankle_x"
    ankle_y = f"{side}_ankle_y"

    required = [hip_x, hip_y, ankle_x, ankle_y]
    if not all(c in df.columns for c in required):
        return np.zeros(len(df))

    angles = []
    for _, row in df.iterrows():
        angles.append(_angle_from_vertical(
            row[hip_x], row[hip_y], row[ankle_x], row[ankle_y]
        ))
    return np.array(angles)


def calc_knee_extension(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Compute knee extension angle (Hip->Knee->Ankle) for each frame.

    180 degrees = fully extended leg.

    Args:
        df: landmarks DataFrame.
        side: "right" or "left".

    Returns:
        numpy array of knee angles in degrees.
    """
    hip_x, hip_y = f"{side}_hip_x", f"{side}_hip_y"
    knee_x, knee_y = f"{side}_knee_x", f"{side}_knee_y"
    ankle_x, ankle_y = f"{side}_ankle_x", f"{side}_ankle_y"

    required = [hip_x, hip_y, knee_x, knee_y, ankle_x, ankle_y]
    if not all(c in df.columns for c in required):
        return np.full(len(df), 180.0)

    angles = []
    for _, row in df.iterrows():
        a = (row[hip_x], row[hip_y])
        b = (row[knee_x], row[knee_y])
        c = (row[ankle_x], row[ankle_y])
        angles.append(calc_angle(a, b, c))
    return np.array(angles)


def calc_shoulder_knee_angle(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Compute shoulder-hip-knee angle for each frame.

    180 degrees = body in a straight line (shoulder, hip, knee aligned).

    Args:
        df: landmarks DataFrame.
        side: "right" or "left".

    Returns:
        numpy array of angles in degrees.
    """
    sh_x, sh_y = f"{side}_shoulder_x", f"{side}_shoulder_y"
    hip_x, hip_y = f"{side}_hip_x", f"{side}_hip_y"
    knee_x, knee_y = f"{side}_knee_x", f"{side}_knee_y"

    required = [sh_x, sh_y, hip_x, hip_y, knee_x, knee_y]
    if not all(c in df.columns for c in required):
        return np.full(len(df), 180.0)

    angles = []
    for _, row in df.iterrows():
        a = (row[sh_x], row[sh_y])
        b = (row[hip_x], row[hip_y])
        c = (row[knee_x], row[knee_y])
        angles.append(calc_angle(a, b, c))
    return np.array(angles)


def calc_leg_symmetry(df: pd.DataFrame) -> np.ndarray:
    """Compute leg symmetry as difference between left and right leg deviation.

    0 degrees = perfect symmetry. Used for barracuda scoring.

    Returns:
        numpy array of absolute difference in degrees.
    """
    left = calc_leg_deviation_vision(df, side="left")
    right = calc_leg_deviation_vision(df, side="right")
    return np.abs(left - right)


def calc_trunk_vertical(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Compute trunk deviation from vertical (Shoulder->Hip vs vertical).

    0 degrees = trunk perfectly vertical.

    Args:
        df: landmarks DataFrame.
        side: "right" or "left".

    Returns:
        numpy array of deviation angles in degrees.
    """
    sh_x = f"{side}_shoulder_x"
    sh_y = f"{side}_shoulder_y"
    hip_x = f"{side}_hip_x"
    hip_y = f"{side}_hip_y"

    required = [sh_x, sh_y, hip_x, hip_y]
    if not all(c in df.columns for c in required):
        return np.zeros(len(df))

    angles = []
    for _, row in df.iterrows():
        angles.append(_angle_from_vertical(
            row[sh_x], row[sh_y], row[hip_x], row[hip_y]
        ))
    return np.array(angles)
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/billthechurch/Downloads/test_rec && python -m pytest tests/test_vision_angles.py -v 2>&1 | tail -30`
Expected: All PASS (10+ tests)

**Step 5: Commit**

```bash
git add dashboard/core/vision_angles.py tests/test_vision_angles.py
git commit -m "feat: vision angle calculations for artistic swimming (leg deviation, knee extension, shoulder-knee, symmetry, trunk)"
```

---

### Task 3: Per-Metric FINA Thresholds in Config

**Files:**
- Modify: `config.toml`
- Modify: `dashboard/core/scoring.py:45-62` (compute_deduction)
- Modify: `dashboard/config.py`
- Test: `tests/test_scoring.py`

**Step 1: Write the failing tests**

```python
# tests/test_scoring.py — add these tests

def test_compute_deduction_per_metric_config():
    """Per-metric FINA config overrides global thresholds."""
    config = {
        "fina": {
            "clean_threshold_deg": 15,
            "minor_deduction_deg": 30,
            "clean_deduction": 0.0,
            "minor_deduction": 0.2,
            "major_deduction": 0.5,
            "leg_deviation": {"clean": 5, "minor": 15, "major": 30,
                              "clean_ded": 0.0, "minor_ded": 0.2, "major_ded": 1.0},
        }
    }
    # 10 degrees: above per-metric clean(5) but below minor(15) => minor
    ded, zone = compute_deduction(10.0, config, metric="leg_deviation")
    assert zone == "minor"
    assert ded == 0.2

    # Same value with global config would be clean (10 < 15)
    ded_global, zone_global = compute_deduction(10.0, config)
    assert zone_global == "clean"


def test_compute_deduction_fallback_to_global():
    """Without per-metric config, falls back to global thresholds."""
    config = {
        "fina": {
            "clean_threshold_deg": 15,
            "minor_deduction_deg": 30,
            "clean_deduction": 0.0,
            "minor_deduction": 0.2,
            "major_deduction": 0.5,
        }
    }
    ded, zone = compute_deduction(10.0, config, metric="knee_extension")
    assert zone == "clean"
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/billthechurch/Downloads/test_rec && python -m pytest tests/test_scoring.py::test_compute_deduction_per_metric_config -v 2>&1 | tail -10`
Expected: FAIL — `compute_deduction() got unexpected keyword argument 'metric'`

**Step 3: Implement per-metric deduction logic**

Update `compute_deduction` in `dashboard/core/scoring.py`:

```python
def compute_deduction(value: float, config: dict, metric: str = "") -> tuple[float, str]:
    """Apply FINA threshold rules to a metric value.

    If config["fina"][metric] exists, uses per-metric thresholds.
    Otherwise falls back to global thresholds.

    Args:
        value: The metric value.
        config: Full config dict.
        metric: Optional metric name for per-metric thresholds.

    Returns:
        Tuple of (deduction_amount, zone_name).
    """
    fina = config["fina"]

    # Per-metric thresholds
    if metric and metric in fina and isinstance(fina[metric], dict):
        m = fina[metric]
        if value < m["clean"]:
            return (m.get("clean_ded", 0.0), "clean")
        if value < m["minor"]:
            return (m.get("minor_ded", 0.2), "minor")
        return (m.get("major_ded", 0.5), "major")

    # Global fallback
    if value < fina["clean_threshold_deg"]:
        return (fina["clean_deduction"], "clean")
    if value < fina["minor_deduction_deg"]:
        return (fina["minor_deduction"], "minor")
    return (fina["major_deduction"], "major")
```

Update `config.toml` with per-metric sections:

```toml
[fina]
clean_threshold_deg = 15
minor_deduction_deg = 30
clean_deduction = 0.0
minor_deduction = 0.2
major_deduction = 0.9

[fina.leg_deviation]
clean = 5
minor = 15
major = 30
clean_ded = 0.0
minor_ded = 0.2
major_ded = 1.0

[fina.knee_extension]
clean = 170
minor = 155
major = 140
clean_ded = 0.0
minor_ded = 0.2
major_ded = 0.5

[fina.leg_symmetry]
clean = 5
minor = 15
major = 30
clean_ded = 0.0
minor_ded = 0.2
major_ded = 0.5

[fina.shoulder_knee_alignment]
clean = 170
minor = 155
major = 140
clean_ded = 0.0
minor_ded = 0.2
major_ded = 0.5

[fina.trunk_vertical]
clean = 10
minor = 20
major = 35
clean_ded = 0.0
minor_ded = 0.2
major_ded = 0.5
```

**Step 4: Run all scoring tests**

Run: `cd /Users/billthechurch/Downloads/test_rec && python -m pytest tests/test_scoring.py -v 2>&1 | tail -20`
Expected: All PASS (existing + new tests)

**Step 5: Commit**

```bash
git add dashboard/core/scoring.py config.toml tests/test_scoring.py
git commit -m "feat: per-metric FINA thresholds with global fallback"
```

---

### Task 4: Scoring Engine — 8 Metrics

**Files:**
- Modify: `dashboard/core/scoring.py:69-284` (metric functions + compute_set_report)
- Modify: `dashboard/core/metrics.py` (orchestrator)
- Test: `tests/test_scoring.py`

**Step 1: Write the failing tests**

```python
# tests/test_scoring.py — add these tests

@pytest.fixture
def landmarks_df():
    """Synthetic landmarks DataFrame — upright standing, 20 frames."""
    n = 20
    df = pd.DataFrame({"timestamp_local": np.linspace(0, 1, n), "frame": range(n)})
    # Upright pose: shoulder above hip above knee above ankle
    for side in ["left", "right"]:
        x_offset = 0.45 if side == "left" else 0.55
        df[f"{side}_shoulder_x"] = x_offset
        df[f"{side}_shoulder_y"] = 0.3
        df[f"{side}_shoulder_z"] = 0.0
        df[f"{side}_shoulder_vis"] = 0.9
        df[f"{side}_hip_x"] = x_offset
        df[f"{side}_hip_y"] = 0.5
        df[f"{side}_hip_z"] = 0.0
        df[f"{side}_hip_vis"] = 0.9
        df[f"{side}_knee_x"] = x_offset
        df[f"{side}_knee_y"] = 0.7
        df[f"{side}_knee_z"] = 0.0
        df[f"{side}_knee_vis"] = 0.9
        df[f"{side}_ankle_x"] = x_offset
        df[f"{side}_ankle_y"] = 0.9
        df[f"{side}_ankle_z"] = 0.0
        df[f"{side}_ankle_vis"] = 0.9
    return df


@pytest.fixture
def leg_imu_df():
    """Synthetic shin IMU DataFrame with 100 rows."""
    t = np.linspace(0, 2.0, 100)
    return pd.DataFrame({
        "timestamp_local": t,
        "ax": np.sin(t) * 0.3,
        "ay": np.cos(t) * 0.2,
        "az": np.ones(100) * 9.8,
        "gx": np.sin(t * 2) * 8,
        "gy": np.cos(t * 2) * 8,
        "gz": np.sin(t * 3) * 4,
    })


def test_compute_set_report_full_8_metrics(imu_df, leg_imu_df, vision_df, landmarks_df, fina_config):
    """With all 4 data sources, returns 8 metrics."""
    report = compute_set_report(imu_df, leg_imu_df, vision_df, landmarks_df, fina_config)
    assert isinstance(report, SetReport)
    assert len(report.metrics) == 8
    assert report.overall_score <= 10.0
    metric_names = {m.name for m in report.metrics}
    assert "leg_deviation" in metric_names
    assert "leg_height_index" in metric_names
    assert "knee_extension" in metric_names
    assert "shoulder_knee_alignment" in metric_names
    assert "trunk_vertical" in metric_names
    assert "leg_symmetry" in metric_names
    assert "smoothness" in metric_names
    assert "stability" in metric_names


def test_compute_set_report_no_leg_imu(imu_df, vision_df, landmarks_df, fina_config):
    """Without leg IMU, leg_deviation uses vision only. Still 8 metrics."""
    report = compute_set_report(imu_df, None, vision_df, landmarks_df, fina_config)
    assert len(report.metrics) == 8


def test_compute_set_report_no_landmarks(imu_df, leg_imu_df, vision_df, fina_config):
    """Without landmarks, vision metrics use proxy values. Returns 8 metrics."""
    report = compute_set_report(imu_df, leg_imu_df, vision_df, None, fina_config)
    assert len(report.metrics) == 8


def test_compute_set_report_backward_compat_arm_imu_only(imu_df, fina_config):
    """With only arm IMU (Phase 2 backward compat), returns IMU-only metrics."""
    report = compute_set_report(imu_df, None, pd.DataFrame(), None, fina_config)
    assert len(report.metrics) >= 3
    metric_names = {m.name for m in report.metrics}
    assert "leg_deviation" in metric_names
    assert "smoothness" in metric_names
    assert "stability" in metric_names
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/billthechurch/Downloads/test_rec && python -m pytest tests/test_scoring.py::test_compute_set_report_full_8_metrics -v 2>&1 | tail -10`
Expected: FAIL — `compute_set_report() takes 3 positional arguments but 5 were given`

**Step 3: Refactor scoring engine**

Refactor `compute_set_report` in `dashboard/core/scoring.py` to accept 4 data sources and compute 8 metrics. Key changes:

1. Change signature to `(arm_imu_df, leg_imu_df, vision_df, landmarks_df, config)`
2. Add `compute_leg_deviation` that fuses shin IMU + vision when both available
3. Replace proxy `compute_leg_height_index` with real landmarks-based calculation (fallback to proxy)
4. Add `compute_knee_extension_metric`, `compute_trunk_vertical_metric`, `compute_leg_symmetry_metric`
5. Replace proxy `compute_shoulder_knee_alignment` with real landmarks-based calculation
6. Extend `compute_smoothness` and `compute_stability` to combine both IMU nodes

Also update `dashboard/core/metrics.py`:

```python
def compute_all_metrics(set_dir: str) -> SetReport | None:
    """Load data and compute all metrics for a recorded set."""
    from dashboard.core.data_loader import load_imu, load_vision
    from dashboard.core.landmarks import load_landmarks_csv

    arm_imu_df = load_imu(set_dir, node="NODE_A1")
    leg_imu_df = load_imu(set_dir, node="NODE_L1")
    vision_df = load_vision(set_dir)
    landmarks_df = load_landmarks_csv(set_dir)

    # Check if we have any data at all
    has_any = (not arm_imu_df.empty or not leg_imu_df.empty
               or not vision_df.empty or not landmarks_df.empty)
    if not has_any:
        return None

    config = load_config()
    leg_imu = leg_imu_df if not leg_imu_df.empty else None
    landmarks = landmarks_df if not landmarks_df.empty else None
    return compute_set_report(arm_imu_df, leg_imu, vision_df, landmarks, config)
```

**Step 4: Fix existing tests**

Update existing `test_compute_set_report_full`, `test_compute_set_report_imu_only`, and `test_compute_set_report_vision_only` to match new signature (add `leg_imu_df=None` and `landmarks_df=None` params).

**Step 5: Run all tests**

Run: `cd /Users/billthechurch/Downloads/test_rec && python -m pytest tests/test_scoring.py -v 2>&1 | tail -30`
Expected: All PASS

**Step 6: Commit**

```bash
git add dashboard/core/scoring.py dashboard/core/metrics.py tests/test_scoring.py
git commit -m "feat: 8-metric scoring engine with dual IMU + landmarks support"
```

---

### Task 5: Waveform Chart — Dual IMU Support

**Files:**
- Modify: `dashboard/components/waveform_chart.py`
- Test: `tests/test_chart_builders.py`

**Step 1: Write the failing test**

```python
# tests/test_chart_builders.py — add this test

def test_build_imu_waveform_dual_node():
    """Waveform chart accepts optional second node data for overlay."""
    t = np.linspace(0, 2, 50)
    fig = build_imu_waveform(
        time=t,
        accel_mag=np.ones(50),
        gyro_mag=np.ones(50) * 2,
        tilt_angle=np.ones(50) * 45,
        node_label="forearm",
        time2=t,
        accel_mag2=np.ones(50) * 0.8,
        tilt_angle2=np.ones(50) * 60,
        node_label2="shin",
    )
    assert fig is not None
    # Should have traces for both nodes
    assert len(fig.data) >= 4
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/billthechurch/Downloads/test_rec && python -m pytest tests/test_chart_builders.py::test_build_imu_waveform_dual_node -v 2>&1 | tail -10`
Expected: FAIL

**Step 3: Add dual-node support to waveform chart**

Add optional `time2`, `accel_mag2`, `tilt_angle2`, `node_label`, `node_label2` parameters to `build_imu_waveform`. When second node data provided, add dashed traces for the second node with a distinct color.

**Step 4: Run tests**

Run: `cd /Users/billthechurch/Downloads/test_rec && python -m pytest tests/test_chart_builders.py -v 2>&1 | tail -20`
Expected: All PASS

**Step 5: Commit**

```bash
git add dashboard/components/waveform_chart.py tests/test_chart_builders.py
git commit -m "feat: dual-node IMU waveform chart with overlay support"
```

---

### Task 6: Training Page — 4-Tab Reorganization

**Files:**
- Modify: `dashboard/pages/training.py`
- Modify: `dashboard/components/gauge_chart.py` (8-gauge layout)

**Step 1: Update gauge chart for 8 metrics**

Modify `build_gauges` to handle 8 metrics grouped into rows:
- Row 1: Leg metrics (deviation, height, knee, symmetry)
- Row 2: Body metrics (shoulder-knee, trunk vertical, smoothness, stability)

**Step 2: Restructure training.py tabs**

Change from 3 tabs to 4 tabs:

```python
tab_overview, tab_legs, tab_arms, tab_fusion = st.tabs([
    "概览", "腿部分析", "手臂分析", "传感器融合"
])
```

- **概览 tab**: 8 gauges + phase timeline + overall score (similar to current)
- **腿部分析 tab**: Leg deviation time series, knee extension chart, leg symmetry chart, shin IMU vs vision fusion, lower-body skeleton overlay
- **手臂分析 tab**: Elbow angle time series, shoulder-knee alignment, trunk verticality, forearm IMU vs vision fusion, upper-body skeleton overlay
- **传感器融合 tab**: Dual IMU waveform overlay, IMU-vision correlation matrix, data quality panel, "Advanced Fusion — Coming Soon" placeholder

**Step 3: Update data flow in training page**

The training page currently calls `compute_all_metrics(set_dir)`. Update it to also load raw DataFrames for chart building:

```python
arm_imu_df = load_imu(set_dir, node="NODE_A1")
leg_imu_df = load_imu(set_dir, node="NODE_L1")
landmarks_df = load_landmarks_csv(set_dir)
```

**Step 4: Manual verification**

Run: `cd /Users/billthechurch/Downloads/test_rec && python -m streamlit run dashboard/app.py`
Verify:
- 4 tabs visible
- Gauges show 8 metrics when data available
- Graceful fallback when leg IMU or landmarks missing
- Skeleton overlay works in both leg and arm tabs

**Step 5: Commit**

```bash
git add dashboard/pages/training.py dashboard/components/gauge_chart.py
git commit -m "feat: 4-tab training page with leg/arm/fusion analysis views"
```

---

### Task 7: Update task.md and DEVLOG

**Files:**
- Modify: `task.md`
- Modify: `DEVLOG.md` (if exists)

**Step 1: Update task.md**

Add a new section documenting the artistic swimming pose detection upgrade:
- Dual IMU support (NODE_A1 forearm + NODE_L1 shin)
- 8 biomechanical metrics
- Vision angle calculations from landmarks
- 4-tab training page

**Step 2: Commit**

```bash
git add task.md DEVLOG.md
git commit -m "docs: update task.md with artistic swimming pose detection milestone"
```

---

## Execution Order

```
Task 1 (data_loader)
  ↓
Task 2 (vision_angles) ← independent of Task 1, can run in parallel
  ↓
Task 3 (per-metric FINA config) ← independent, can run in parallel
  ↓
Task 4 (scoring engine) ← depends on Tasks 1, 2, 3
  ↓
Task 5 (waveform chart) ← independent of Task 4, can run in parallel
  ↓
Task 6 (training page) ← depends on Tasks 4, 5
  ↓
Task 7 (docs) ← depends on Task 6
```

Parallelizable groups:
- **Wave 1**: Tasks 1, 2, 3 (all independent)
- **Wave 2**: Tasks 4, 5 (4 depends on 1-3, 5 is independent)
- **Wave 3**: Task 6 (depends on 4-5)
- **Wave 4**: Task 7 (docs)
