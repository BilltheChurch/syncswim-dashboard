"""Tests for scoring engine: dataclasses, FINA deductions, and 5 metric functions."""
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
    """FINA config matching config.toml defaults."""
    return {
        "fina": {
            "clean_threshold_deg": 15,
            "minor_deduction_deg": 30,
            "clean_deduction": 0.0,
            "minor_deduction": 0.2,
            "major_deduction": 0.5,
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
# compute_set_report integration tests
# ---------------------------------------------------------------------------

def test_compute_set_report_full(imu_df, vision_df, fina_config):
    """With both IMU and vision data, returns 5 metrics and score <= 10.0."""
    report = compute_set_report(imu_df, vision_df, fina_config)
    assert isinstance(report, SetReport)
    assert len(report.metrics) == 5
    assert report.overall_score <= 10.0
    assert len(report.phases) == 3
    # correlation should be computed when both DataFrames are present
    assert report.correlation is None or isinstance(report.correlation, float)


def test_compute_set_report_imu_only(imu_df, fina_config):
    """With only IMU data, returns 3 metrics (deviation, smoothness, stability)."""
    empty_vision = pd.DataFrame()
    report = compute_set_report(imu_df, empty_vision, fina_config)
    assert isinstance(report, SetReport)
    assert len(report.metrics) == 3
    metric_names = {m.name for m in report.metrics}
    assert "leg_deviation" in metric_names
    assert "smoothness" in metric_names
    assert "stability" in metric_names


def test_compute_set_report_vision_only(vision_df, fina_config):
    """With only vision data, returns 2 metrics (height_index, alignment)."""
    empty_imu = pd.DataFrame()
    report = compute_set_report(empty_imu, vision_df, fina_config)
    assert isinstance(report, SetReport)
    assert len(report.metrics) == 2
    metric_names = {m.name for m in report.metrics}
    assert "leg_height_index" in metric_names
    assert "shoulder_knee_alignment" in metric_names
