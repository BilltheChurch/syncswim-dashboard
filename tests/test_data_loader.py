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
    assert len(sessions) == 9  # 9 set directories
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
    """set_002 entries should have both IMU and vision data."""
    from dashboard.core.data_loader import build_sessions_index

    sessions = build_sessions_index(DATA_DIR)
    set_002 = [s for s in sessions if s["set_number"] == 2]
    assert len(set_002) == 2  # two set_002 recordings
    for s in set_002:
        assert s["has_imu"] is True
        assert s["has_vision"] is True
        assert s["imu_rows"] > 0
        assert s["vision_rows"] > 0


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


# --- Dual-IMU tests ---


def test_load_imu_with_node_param(tmp_path):
    """load_imu with explicit node='NODE_L1' loads the correct file."""
    from dashboard.core.data_loader import load_imu

    csv = tmp_path / "imu_NODE_L1.csv"
    csv.write_text("timestamp_local,ax,ay,az,gx,gy,gz\n1.0,0,0,0,0,0,0\n")
    df = load_imu(str(tmp_path), node="NODE_L1")
    assert not df.empty
    assert "ax" in df.columns
    assert len(df) == 1


def test_load_imu_default_node_backward_compat(tmp_path):
    """load_imu without node param still defaults to NODE_A1."""
    from dashboard.core.data_loader import load_imu

    csv = tmp_path / "imu_NODE_A1.csv"
    csv.write_text("timestamp_local,ax,ay,az,gx,gy,gz\n2.0,1,1,1,1,1,1\n")
    df = load_imu(str(tmp_path))
    assert not df.empty
    assert len(df) == 1


def test_load_imu_missing_node_returns_empty(tmp_path):
    """load_imu for a node with no file returns empty DataFrame."""
    from dashboard.core.data_loader import load_imu

    df = load_imu(str(tmp_path), node="NODE_X9")
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_load_all_imus(tmp_path):
    """load_all_imus returns dict with all detected nodes."""
    from dashboard.core.data_loader import load_all_imus

    header = "timestamp_local,ax,ay,az,gx,gy,gz\n"
    (tmp_path / "imu_NODE_A1.csv").write_text(header + "1.0,0,0,0,0,0,0\n")
    (tmp_path / "imu_NODE_L1.csv").write_text(header + "1.0,1,1,1,1,1,1\n")

    result = load_all_imus(str(tmp_path))
    assert isinstance(result, dict)
    assert set(result.keys()) == {"NODE_A1", "NODE_L1"}
    assert len(result["NODE_A1"]) == 1
    assert len(result["NODE_L1"]) == 1


def test_load_all_imus_partial(tmp_path):
    """load_all_imus with only one node file returns single-entry dict."""
    from dashboard.core.data_loader import load_all_imus

    header = "timestamp_local,ax,ay,az,gx,gy,gz\n"
    (tmp_path / "imu_NODE_A1.csv").write_text(header + "1.0,0,0,0,0,0,0\n")

    result = load_all_imus(str(tmp_path))
    assert isinstance(result, dict)
    assert list(result.keys()) == ["NODE_A1"]
    assert len(result["NODE_A1"]) == 1
