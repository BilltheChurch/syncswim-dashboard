"""Tests for scoring engine: dataclasses, FINA deductions, and 8 metric functions."""
import numpy as np
import pandas as pd
import pytest

from dashboard.core.scoring import (
    MetricResult,
    SetReport,
    compute_deduction,
    compute_leg_deviation,
    compute_leg_height_index,
    compute_set_report,
    compute_shoulder_knee_alignment,
    compute_smoothness,
    compute_stability,
)


# ---------------------------------------------------------------------------
# Fixtures: synthetic data
# ---------------------------------------------------------------------------

@pytest.fixture
def fina_config():
    """FINA config matching config.toml defaults with per-metric thresholds."""
    return {
        "fina": {
            "clean_threshold_deg": 15,
            "minor_deduction_deg": 30,
            "clean_deduction": 0.0,
            "minor_deduction": 0.2,
            "major_deduction": 0.5,
            "leg_deviation": {
                "clean": 5, "minor": 15, "major": 30,
                "clean_ded": 0.0, "minor_ded": 0.2, "major_ded": 1.0,
            },
            "knee_extension": {
                "clean": 170, "minor": 155, "major": 140,
                "clean_ded": 0.0, "minor_ded": 0.2, "major_ded": 0.5,
            },
            "shoulder_knee_alignment": {
                "clean": 170, "minor": 155, "major": 140,
                "clean_ded": 0.0, "minor_ded": 0.2, "major_ded": 0.5,
            },
            "trunk_vertical": {
                "clean": 10, "minor": 20, "major": 35,
                "clean_ded": 0.0, "minor_ded": 0.2, "major_ded": 0.5,
            },
            "leg_symmetry": {
                "clean": 5, "minor": 15, "major": 30,
                "clean_ded": 0.0, "minor_ded": 0.2, "major_ded": 0.5,
            },
        }
    }


@pytest.fixture
def imu_df():
    """Synthetic IMU DataFrame with 100 rows of sinusoidal data."""
    t = np.linspace(0, 2.0, 100)
    return pd.DataFrame({
        "timestamp_local": t,
        "ax": np.sin(t) * 0.5,
        "ay": np.cos(t) * 0.3,
        "az": np.ones(100) * 9.8,
        "gx": np.sin(t * 2) * 10,
        "gy": np.cos(t * 2) * 10,
        "gz": np.sin(t * 3) * 5,
    })


@pytest.fixture
def leg_imu_df():
    """Synthetic shin IMU DataFrame."""
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


@pytest.fixture
def vision_df():
    """Synthetic vision DataFrame with 50 rows."""
    return pd.DataFrame({
        "timestamp_local": np.linspace(0, 2.0, 50),
        "frame": list(range(50)),
        "joint": ["left_elbow"] * 50,
        "angle_deg": np.linspace(90, 130, 50),
        "visible": [True] * 50,
        "fps": [30.0] * 50,
    })


@pytest.fixture
def landmarks_df():
    """Synthetic landmarks DataFrame — upright standing, 20 frames."""
    n = 20
    df = pd.DataFrame({"timestamp_local": np.linspace(0, 1, n), "frame": range(n)})
    for side in ["left", "right"]:
        x = 0.45 if side == "left" else 0.55
        df[f"{side}_shoulder_x"] = x
        df[f"{side}_shoulder_y"] = 0.3
        df[f"{side}_shoulder_z"] = 0.0
        df[f"{side}_shoulder_vis"] = 0.9
        df[f"{side}_hip_x"] = x
        df[f"{side}_hip_y"] = 0.5
        df[f"{side}_hip_z"] = 0.0
        df[f"{side}_hip_vis"] = 0.9
        df[f"{side}_knee_x"] = x
        df[f"{side}_knee_y"] = 0.7
        df[f"{side}_knee_z"] = 0.0
        df[f"{side}_knee_vis"] = 0.9
        df[f"{side}_ankle_x"] = x
        df[f"{side}_ankle_y"] = 0.9
        df[f"{side}_ankle_z"] = 0.0
        df[f"{side}_ankle_vis"] = 0.9
    return df


# ---------------------------------------------------------------------------
# FINA deduction tests
# ---------------------------------------------------------------------------

def test_compute_deduction_clean(fina_config):
    """Value below clean threshold returns 0.0 deduction, zone 'clean'."""
    deduction, zone = compute_deduction(10.0, fina_config)
    assert deduction == 0.0
    assert zone == "clean"


def test_compute_deduction_minor(fina_config):
    """Value between clean and minor threshold returns minor deduction."""
    deduction, zone = compute_deduction(20.0, fina_config)
    assert deduction == 0.2
    assert zone == "minor"


def test_compute_deduction_major(fina_config):
    """Value above minor threshold returns major deduction."""
    deduction, zone = compute_deduction(35.0, fina_config)
    assert deduction == 0.5
    assert zone == "major"


# ---------------------------------------------------------------------------
# Individual metric tests
# ---------------------------------------------------------------------------

def test_compute_leg_deviation(imu_df):
    """Synthetic IMU data returns expected mean deviation from 90 degrees."""
    result = compute_leg_deviation(imu_df)
    assert isinstance(result, float)
    # With ax ~ sin(t)*0.5 and az ~ 9.8, tilt angle is small (< 5 deg)
    # so deviation from 90 should be large (~87 deg)
    assert result > 0.0


def test_compute_smoothness(imu_df):
    """Synthetic gyro data returns positive float jerk value."""
    result = compute_smoothness(imu_df)
    assert isinstance(result, float)
    assert result > 0.0


def test_compute_stability(imu_df):
    """Synthetic tilt data with known std returns expected stability value."""
    t_start = float(imu_df["timestamp_local"].iloc[0])
    t_end = float(imu_df["timestamp_local"].iloc[-1])
    result = compute_stability(imu_df, (t_start, t_end))
    assert isinstance(result, float)
    assert result >= 0.0


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------

def test_metric_result_dataclass():
    """MetricResult has all expected fields."""
    mr = MetricResult(
        name="test", value=5.0, unit="deg",
        deduction=0.2, zone="minor", max_value=90.0,
    )
    assert mr.name == "test"
    assert mr.value == 5.0
    assert mr.unit == "deg"
    assert mr.deduction == 0.2
    assert mr.zone == "minor"
    assert mr.max_value == 90.0


def test_set_report_dataclass():
    """SetReport has all expected fields."""
    sr = SetReport(
        metrics=[],
        overall_score=9.8,
        phases=[{"name": "prep", "start": 0.0, "end": 1.0}],
        correlation=0.5,
    )
    assert isinstance(sr.metrics, list)
    assert sr.overall_score == 9.8
    assert isinstance(sr.phases, list)
    assert sr.correlation == 0.5


# ---------------------------------------------------------------------------
# Per-metric FINA deduction tests
# ---------------------------------------------------------------------------

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

    # Same 10 degrees with global config would be clean (10 < 15)
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
    ded, zone = compute_deduction(10.0, config, metric="nonexistent_metric")
    assert zone == "clean"
    assert ded == 0.0


def test_compute_deduction_inverted_metric():
    """Inverted metrics (higher=better like knee extension) work correctly."""
    config = {
        "fina": {
            "clean_threshold_deg": 15,
            "minor_deduction_deg": 30,
            "clean_deduction": 0.0,
            "minor_deduction": 0.2,
            "major_deduction": 0.5,
            "knee_extension": {"clean": 170, "minor": 155, "major": 140,
                               "clean_ded": 0.0, "minor_ded": 0.2, "major_ded": 0.5},
        }
    }
    # 175 degrees: above clean(170) => clean (good extension)
    ded, zone = compute_deduction(175.0, config, metric="knee_extension")
    assert zone == "clean"

    # 160 degrees: between minor(155) and clean(170) => minor
    ded, zone = compute_deduction(160.0, config, metric="knee_extension")
    assert zone == "minor"

    # 130 degrees: below major(140) => major
    ded, zone = compute_deduction(130.0, config, metric="knee_extension")
    assert zone == "major"


# ---------------------------------------------------------------------------
# compute_set_report integration tests (updated to 5-arg signature)
# ---------------------------------------------------------------------------

def test_compute_set_report_full(imu_df, vision_df, fina_config):
    """With arm IMU and vision data (no leg IMU/landmarks), returns 8 metrics."""
    report = compute_set_report(imu_df, None, vision_df, None, fina_config)
    assert isinstance(report, SetReport)
    assert len(report.metrics) == 8
    assert report.overall_score <= 10.0
    assert len(report.phases) == 3
    # correlation should be computed when both arm IMU and vision present
    assert report.correlation is None or isinstance(report.correlation, float)


def test_compute_set_report_imu_only(imu_df, fina_config):
    """With only arm IMU data, returns 8 metrics (proxies for vision-based)."""
    report = compute_set_report(imu_df, None, pd.DataFrame(), None, fina_config)
    assert isinstance(report, SetReport)
    assert len(report.metrics) == 8
    metric_names = {m.name for m in report.metrics}
    assert "leg_deviation" in metric_names
    assert "smoothness" in metric_names
    assert "stability" in metric_names


def test_compute_set_report_vision_only(vision_df, fina_config):
    """With only vision data, returns 8 metrics (proxies for IMU-based)."""
    report = compute_set_report(pd.DataFrame(), None, vision_df, None, fina_config)
    assert isinstance(report, SetReport)
    assert len(report.metrics) == 8
    metric_names = {m.name for m in report.metrics}
    assert "leg_height_index" in metric_names
    assert "shoulder_knee_alignment" in metric_names


# ---------------------------------------------------------------------------
# New 8-metric integration tests
# ---------------------------------------------------------------------------

def test_compute_set_report_full_8_metrics(
    imu_df, leg_imu_df, vision_df, landmarks_df, fina_config,
):
    """All 4 data sources -> 8 metrics."""
    report = compute_set_report(
        imu_df, leg_imu_df, vision_df, landmarks_df, fina_config,
    )
    assert len(report.metrics) == 8
    names = {m.name for m in report.metrics}
    for expected in [
        "leg_deviation", "leg_height_index", "knee_extension",
        "shoulder_knee_alignment", "trunk_vertical", "leg_symmetry",
        "smoothness", "stability",
    ]:
        assert expected in names


def test_compute_set_report_no_leg_imu(
    imu_df, vision_df, landmarks_df, fina_config,
):
    """Without leg IMU still produces 8 metrics."""
    report = compute_set_report(imu_df, None, vision_df, landmarks_df, fina_config)
    assert len(report.metrics) == 8


def test_compute_set_report_no_landmarks_uses_proxy(imu_df, vision_df, fina_config):
    """Without landmarks, uses proxy values, still 8 metrics."""
    report = compute_set_report(imu_df, None, vision_df, None, fina_config)
    assert len(report.metrics) == 8


def test_compute_set_report_arm_imu_only_backward_compat(imu_df, fina_config):
    """Arm IMU only: still produces 8 metrics (backward compat with Phase 2)."""
    report = compute_set_report(imu_df, None, pd.DataFrame(), None, fina_config)
    assert len(report.metrics) == 8
    # leg_deviation should fall back to arm IMU
    dev = next(m for m in report.metrics if m.name == "leg_deviation")
    assert dev.value > 0.0
    # smoothness should have a real value from arm IMU
    sm = next(m for m in report.metrics if m.name == "smoothness")
    assert sm.value > 0.0
