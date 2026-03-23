"""Phase detection from IMU signals.

Stub implementation for Task 1 -- returns equal-thirds phases.
Task 2 will replace with Butterworth filter + scipy find_peaks.
"""
import numpy as np
import pandas as pd


def butterworth_filter(
    data: np.ndarray, cutoff: float = 10.0, fs: float = 72.5, order: int = 4
) -> np.ndarray:
    """Butterworth low-pass filter (stub -- returns data unchanged)."""
    return data


def detect_phases(imu_df: pd.DataFrame, n_phases: int = 3) -> list[dict]:
    """Detect action phases from IMU data.

    Stub: returns 3 equal-thirds phases based on timestamp range.

    Args:
        imu_df: DataFrame with timestamp_local column.
        n_phases: Number of phases (default 3).

    Returns:
        List of 3 phase dicts with keys: name, start, end, zone_color.
    """
    if imu_df.empty:
        return [
            {"name": "准备", "start": 0.0, "end": 0.33, "zone_color": "#09AB3B"},
            {"name": "动作", "start": 0.33, "end": 0.66, "zone_color": "#FACA2B"},
            {"name": "恢复", "start": 0.66, "end": 1.0, "zone_color": "#09AB3B"},
        ]

    t_start = float(imu_df["timestamp_local"].iloc[0])
    t_end = float(imu_df["timestamp_local"].iloc[-1])
    duration = t_end - t_start
    third = duration / 3.0

    return [
        {"name": "准备", "start": t_start, "end": t_start + third, "zone_color": "#09AB3B"},
        {"name": "动作", "start": t_start + third, "end": t_start + 2 * third, "zone_color": "#FACA2B"},
        {"name": "恢复", "start": t_start + 2 * third, "end": t_end, "zone_color": "#09AB3B"},
    ]
