"""Tests for phase detection: Butterworth filter and scipy find_peaks."""
import numpy as np
import pandas as pd
import pytest

from dashboard.core.phase_detect import butterworth_filter, detect_phases


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sinusoidal_signal():
    """200-point sinusoidal signal for filter tests."""
    return np.sin(np.linspace(0, 4 * np.pi, 200))


@pytest.fixture
def flat_imu_df():
    """Synthetic IMU DataFrame with flat signal (no peaks) for fallback test."""
    n = 200
    return pd.DataFrame({
        "timestamp_local": np.linspace(0, 3.0, n),
        "ax": np.zeros(n),
        "ay": np.zeros(n),
        "az": np.ones(n) * 9.8,
    })


@pytest.fixture
def peaked_imu_df():
    """Synthetic IMU DataFrame with two clear acceleration peaks."""
    n = 200
    t = np.linspace(0, 3.0, n)
    # Create signal with two clear peaks at t~1.0 and t~2.0
    ax = np.zeros(n)
    # Peak 1 around index 66 (t=1.0)
    ax[60:73] = np.sin(np.linspace(0, np.pi, 13)) * 5.0
    # Peak 2 around index 133 (t=2.0)
    ax[127:140] = np.sin(np.linspace(0, np.pi, 13)) * 5.0

    return pd.DataFrame({
        "timestamp_local": t,
        "ax": ax,
        "ay": np.zeros(n),
        "az": np.ones(n) * 9.8,
    })


# ---------------------------------------------------------------------------
# Butterworth filter tests
# ---------------------------------------------------------------------------

def test_butterworth_filter_returns_same_length(sinusoidal_signal):
    """Filtered output length equals input length."""
    filtered = butterworth_filter(sinusoidal_signal)
    assert len(filtered) == len(sinusoidal_signal)


def test_butterworth_filter_short_data_fallback():
    """Input shorter than padlen returns unfiltered data."""
    short = np.array([1.0, 2.0, 3.0])
    filtered = butterworth_filter(short)
    np.testing.assert_array_equal(filtered, short)


# ---------------------------------------------------------------------------
# Phase detection tests
# ---------------------------------------------------------------------------

def test_detect_phases_returns_three(peaked_imu_df):
    """Returns exactly 3 phase dicts."""
    phases = detect_phases(peaked_imu_df)
    assert len(phases) == 3


def test_detect_phases_keys(peaked_imu_df):
    """Each phase dict has required keys: name, start, end, zone_color."""
    phases = detect_phases(peaked_imu_df)
    required_keys = {"name", "start", "end", "zone_color"}
    for phase in phases:
        assert set(phase.keys()) == required_keys


def test_detect_phases_fallback_equal_thirds(flat_imu_df):
    """With flat signal (no peaks), boundaries are at 1/3 and 2/3 of duration."""
    phases = detect_phases(flat_imu_df)
    assert len(phases) == 3

    t_start = float(flat_imu_df["timestamp_local"].iloc[0])
    t_end = float(flat_imu_df["timestamp_local"].iloc[-1])
    duration = t_end - t_start
    third = duration / 3.0

    # Check boundaries are at equal thirds (with tolerance for float math)
    assert abs(phases[0]["end"] - (t_start + third)) < 0.01
    assert abs(phases[1]["end"] - (t_start + 2 * third)) < 0.01


def test_detect_phases_chinese_names(peaked_imu_df):
    """Phase names are in Chinese: prep/active/recovery."""
    phases = detect_phases(peaked_imu_df)
    names = [p["name"] for p in phases]
    assert names == ["准备", "动作", "恢复"]
