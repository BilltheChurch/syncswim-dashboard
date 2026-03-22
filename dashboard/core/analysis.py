"""IMU signal analysis functions.

Extracted from analyze.py for shared use by dashboard and CLI.
"""
import math
import numpy as np


def calc_imu_tilt(imu_data: list[dict]) -> np.ndarray:
    """Compute forearm tilt angle from accelerometer data.

    Uses pitch = atan2(ax, sqrt(ay^2 + az^2)) converted to degrees.
    Maps to 0-180 range for visual comparison with elbow angle.

    Args:
        imu_data: List of dicts with keys 'ax', 'ay', 'az' (float values).

    Returns:
        numpy array of pitch angles in degrees.
    """
    angles = []
    for r in imu_data:
        ax, ay, az = r["ax"], r["ay"], r["az"]
        pitch = math.degrees(math.atan2(ax, math.sqrt(ay**2 + az**2)))
        angles.append(pitch)
    return np.array(angles)


def smooth(data: np.ndarray, window: int = 5) -> np.ndarray:
    """Simple moving average smoothing.

    Args:
        data: 1D numpy array of values.
        window: Number of points for averaging kernel.

    Returns:
        Smoothed array (same length, mode='same').
    """
    if len(data) < window:
        return data
    kernel = np.ones(window) / window
    return np.convolve(data, kernel, mode="same")
