"""Data loading layer for CSV sensor data.

Provides pandas DataFrame loading with caching, and a sessions.json
index that auto-rebuilds when the data/ directory changes.
"""
import glob as _glob
import json
import os
from pathlib import Path

import pandas as pd


def load_imu(set_dir: str, node: str = "NODE_A1") -> pd.DataFrame:
    """Load IMU CSV as DataFrame for a specific sensor node.

    Args:
        set_dir: Path to the set directory (e.g. 'data/set_002_20260319_165319').
        node: IMU node identifier (default ``NODE_A1`` for backward compat).

    Returns:
        DataFrame with columns: timestamp_local, timestamp_device, node, state,
        set, ax, ay, az, gx, gy, gz. Empty DataFrame if file missing or corrupt.
    """
    path = os.path.join(set_dir, f"imu_{node}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path, on_bad_lines="warn")
    except Exception:
        return pd.DataFrame()


def load_all_imus(set_dir: str) -> dict[str, pd.DataFrame]:
    """Load all IMU CSV files found in *set_dir*.

    Scans for ``imu_*.csv`` files and returns one DataFrame per node.

    Args:
        set_dir: Path to the set directory.

    Returns:
        Dict mapping node name (e.g. ``NODE_A1``) to its DataFrame.
        Empty dict when no IMU files are present.
    """
    result: dict[str, pd.DataFrame] = {}
    pattern = os.path.join(set_dir, "imu_*.csv")
    for path in sorted(_glob.glob(pattern)):
        fname = os.path.basename(path)  # e.g. "imu_NODE_A1.csv"
        node = fname[len("imu_"):-len(".csv")]  # strip prefix & suffix
        try:
            result[node] = pd.read_csv(path, on_bad_lines="warn")
        except Exception:
            result[node] = pd.DataFrame()
    return result


def load_vision(set_dir: str) -> pd.DataFrame:
    """Load vision CSV as DataFrame.

    Args:
        set_dir: Path to the set directory.

    Returns:
        DataFrame with columns: timestamp_local, frame, joint, angle_deg,
        visible, fps. Empty DataFrame if file missing or corrupt.
    """
    path = os.path.join(set_dir, "vision.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path, on_bad_lines="warn")
    except Exception:
        return pd.DataFrame()


def build_sessions_index(data_dir: str) -> list[dict]:
    """Scan data/ and build metadata for each set directory.

    Parses set_NNN_YYYYMMDD_HHMMSS directory names.

    Args:
        data_dir: Path to the data root directory.

    Returns:
        List of dicts with keys: name, path, set_number, date, time,
        duration_sec, imu_rows, vision_rows, has_imu, has_vision.
    """
    if not os.path.isdir(data_dir):
        return []

    sessions = []
    for name in sorted(os.listdir(data_dir)):
        if not name.startswith("set_") or not os.path.isdir(os.path.join(data_dir, name)):
            continue
        set_dir = os.path.join(data_dir, name)

        # Parse set_NNN_YYYYMMDD_HHMMSS
        parts = name.split("_")
        if len(parts) < 4:
            continue
        try:
            set_num = int(parts[1])
        except ValueError:
            continue
        date_str = parts[2]  # YYYYMMDD
        time_str = parts[3]  # HHMMSS

        # Detect all imu_*.csv files and extract node names
        imu_files = sorted(_glob.glob(os.path.join(set_dir, "imu_*.csv")))
        imu_nodes: list[str] = []
        for imu_path in imu_files:
            fname = os.path.basename(imu_path)
            imu_nodes.append(fname[len("imu_"):-len(".csv")])

        has_imu = len(imu_nodes) > 0
        has_vision = os.path.exists(os.path.join(set_dir, "vision.csv"))
        has_video = os.path.exists(os.path.join(set_dir, "video.mp4"))
        has_landmarks = os.path.exists(os.path.join(set_dir, "landmarks.csv"))

        imu_rows = 0
        vis_rows = 0
        duration = 0.0

        if has_imu:
            # Use the first available IMU file for row count and duration
            try:
                with open(imu_files[0]) as f:
                    lines = f.readlines()
                    imu_rows = max(0, len(lines) - 1)
                if imu_rows > 1:
                    first_t = float(lines[1].split(",")[0])
                    last_t = float(lines[-1].split(",")[0])
                    duration = last_t - first_t
            except (ValueError, IndexError, OSError):
                pass

        if has_vision:
            try:
                with open(os.path.join(set_dir, "vision.csv")) as f:
                    vis_rows = max(0, len(f.readlines()) - 1)
            except OSError:
                pass

        sessions.append({
            "name": name,
            "path": set_dir,
            "set_number": set_num,
            "date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}",
            "time": f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}",
            "duration_sec": round(duration, 1),
            "imu_rows": imu_rows,
            "vision_rows": vis_rows,
            "has_imu": has_imu,
            "has_vision": has_vision,
            "has_video": has_video,
            "has_landmarks": has_landmarks,
            "imu_nodes": imu_nodes,
        })
    return sessions


def load_or_rebuild_index(data_dir: str) -> list[dict]:
    """Load sessions.json if fresh, rebuild if stale.

    Staleness is determined by comparing the modification time of
    sessions.json against the data directory itself.

    Args:
        data_dir: Path to the data root directory.

    Returns:
        List of session metadata dicts.
    """
    if not os.path.isdir(data_dir):
        return []

    index_path = os.path.join(data_dir, "sessions.json")

    try:
        data_mtime = os.path.getmtime(data_dir)
    except OSError:
        return build_sessions_index(data_dir)

    if os.path.exists(index_path):
        try:
            index_mtime = os.path.getmtime(index_path)
            if index_mtime >= data_mtime:
                with open(index_path) as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    # Rebuild
    sessions = build_sessions_index(data_dir)
    try:
        with open(index_path, "w") as f:
            json.dump(sessions, f, indent=2)
    except OSError:
        pass  # Non-fatal -- index is a cache, not required
    return sessions
