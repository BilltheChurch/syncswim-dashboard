"""Tests for dashboard/core/analysis.py — IMU tilt and smoothing functions."""
import numpy as np
import pytest


def test_calc_imu_tilt_zero_ax():
    """When ax=0, pitch should be ~0 degrees (arm horizontal)."""
    from dashboard.core.analysis import calc_imu_tilt

    result = calc_imu_tilt([{"ax": 0, "ay": 0, "az": 1.0}])
    assert isinstance(result, np.ndarray)
    assert len(result) == 1
    assert abs(result[0] - 0.0) < 0.01


def test_calc_imu_tilt_90_degrees():
    """When ax=1, ay=0, az=0, pitch should be ~90 degrees (arm vertical)."""
    from dashboard.core.analysis import calc_imu_tilt

    result = calc_imu_tilt([{"ax": 1.0, "ay": 0, "az": 0}])
    assert abs(result[0] - 90.0) < 0.01


def test_calc_imu_tilt_multiple_readings():
    """Multiple readings produce array of same length."""
    from dashboard.core.analysis import calc_imu_tilt

    data = [
        {"ax": 0, "ay": 0, "az": 1.0},
        {"ax": 1.0, "ay": 0, "az": 0},
        {"ax": 0, "ay": 1.0, "az": 0},
    ]
    result = calc_imu_tilt(data)
    assert len(result) == 3


def test_calc_imu_tilt_empty():
    """Empty input returns empty array."""
    from dashboard.core.analysis import calc_imu_tilt

    result = calc_imu_tilt([])
    assert isinstance(result, np.ndarray)
    assert len(result) == 0


def test_smooth_basic():
    """Smooth with window=3 returns array of same length."""
    from dashboard.core.analysis import smooth

    data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    result = smooth(data, window=3)
    assert len(result) == 5


def test_smooth_short_data():
    """When data is shorter than window, return data unchanged."""
    from dashboard.core.analysis import smooth

    data = np.array([1.0, 2.0])
    result = smooth(data, window=5)
    assert np.array_equal(result, data)


def test_smooth_values():
    """Check actual smoothing produces reasonable values."""
    from dashboard.core.analysis import smooth

    data = np.array([0.0, 0.0, 10.0, 0.0, 0.0])
    result = smooth(data, window=3)
    # Middle value should be reduced from 10
    assert result[2] < 10.0
    # But still positive
    assert result[2] > 0.0
