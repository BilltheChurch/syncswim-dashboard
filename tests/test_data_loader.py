"""Tests for dashboard/core/data_loader.py — CSV loading and sessions index."""
import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = str(PROJECT_ROOT / "data")


def test_load_imu_real_data():
    """load_imu on set_002 returns DataFrame with 'ax' column."""
    from dashboard.core.data_loader import load_imu

    set_dir = os.path.join(DATA_DIR, "set_002_20260319_165319")
    df = load_imu(set_dir)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "ax" in df.columns


def test_load_imu_has_expected_columns():
    """IMU DataFrame has all expected columns."""
    from dashboard.core.data_loader import load_imu

    set_dir = os.path.join(DATA_DIR, "set_002_20260319_165319")
    df = load_imu(set_dir)
    expected = ["timestamp_local", "ax", "ay", "az", "gx", "gy", "gz"]
    for col in expected:
        assert col in df.columns, f"Missing column: {col}"


def test_load_vision_real_data():
    """load_vision on set_002 returns DataFrame with 'angle_deg' column."""
    from dashboard.core.data_loader import load_vision

    set_dir = os.path.join(DATA_DIR, "set_002_20260319_165319")
    df = load_vision(set_dir)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "angle_deg" in df.columns


def test_load_imu_nonexistent():
    """load_imu on nonexistent path returns empty DataFrame."""
    from dashboard.core.data_loader import load_imu

    df = load_imu("/tmp/nonexistent_set_dir_12345")
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_load_vision_nonexistent():
    """load_vision on nonexistent path returns empty DataFrame."""
    from dashboard.core.data_loader import load_vision

    df = load_vision("/tmp/nonexistent_set_dir_12345")
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_build_sessions_index():
    """build_sessions_index on real data/ returns correct number of entries."""
    from dashboard.core.data_loader import build_sessions_index

    sessions = build_sessions_index(DATA_DIR)
    assert isinstance(sessions, list)
    assert len(sessions) == 6  # 6 set directories
    # Each session has expected keys
    for s in sessions:
        assert "name" in s
        assert "path" in s
        assert "set_number" in s
        assert "has_imu" in s
        assert "has_vision" in s


def test_build_sessions_index_nonexistent():
    """build_sessions_index on nonexistent dir returns empty list."""
    from dashboard.core.data_loader import build_sessions_index

    result = build_sessions_index("/tmp/nonexistent_data_12345")
    assert result == []


def test_build_sessions_index_set_002_metadata():
    """set_002 should have both IMU and vision data."""
    from dashboard.core.data_loader import build_sessions_index

    sessions = build_sessions_index(DATA_DIR)
    set_002 = [s for s in sessions if s["set_number"] == 2]
    assert len(set_002) == 1
    assert set_002[0]["has_imu"] is True
    assert set_002[0]["has_vision"] is True
    assert set_002[0]["imu_rows"] > 0
    assert set_002[0]["vision_rows"] > 0


def test_load_or_rebuild_index():
    """load_or_rebuild_index returns sessions list."""
    from dashboard.core.data_loader import load_or_rebuild_index

    sessions = load_or_rebuild_index(DATA_DIR)
    assert isinstance(sessions, list)
    assert len(sessions) >= 1


def test_load_or_rebuild_index_nonexistent():
    """load_or_rebuild_index on nonexistent dir returns empty list."""
    from dashboard.core.data_loader import load_or_rebuild_index

    result = load_or_rebuild_index("/tmp/nonexistent_data_12345")
    assert result == []
