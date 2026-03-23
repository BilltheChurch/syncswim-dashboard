"""Phase detection from IMU signals.

Uses Butterworth low-pass filter and scipy find_peaks to detect
action phase boundaries from IMU acceleration data. Falls back
to equal-thirds when fewer than 2 peaks are found.
"""
import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, find_peaks


# Phase names in Chinese (prep / active / recovery)
PHASE_NAMES = ("准备", "动作", "恢复")
PHASE_COLORS = ("#09AB3B", "#FACA2B", "#09AB3B")  # green / yellow / green


def butterworth_filter(
    data: np.ndarray,
    cutoff: float = 10.0,
    fs: float = 72.5,
    order: int = 4,
) -> np.ndarray:
    """Apply Butterworth low-pass filter to 1D signal.

    Falls back to returning data unfiltered when input is too short
    for the filter's padding requirements.

    Args:
        data: 1D numpy array of signal values.
        cutoff: Cutoff frequency in Hz.
        fs: Sampling frequency in Hz.
        order: Filter order.

    Returns:
        Filtered array (same length as input).
    """
    nyquist = fs / 2.0
    normalized_cutoff = cutoff / nyquist

    # Clamp to valid range (0, 1) exclusive
    if normalized_cutoff >= 1.0:
        normalized_cutoff = 0.99
    if normalized_cutoff <= 0.0:
        normalized_cutoff = 0.01

    b, a = butter(order, normalized_cutoff, btype="low")

    # filtfilt requires len(data) > 3 * max(len(a), len(b))
    padlen = 3 * max(len(a), len(b))
    if len(data) <= padlen:
        return data

    return filtfilt(b, a, data)


def _equal_thirds(t_start: float, t_end: float) -> list[dict]:
    """Generate 3 equal-duration phase boundaries."""
    duration = t_end - t_start
    third = duration / 3.0
    return [
        {
            "name": PHASE_NAMES[0],
            "start": t_start,
            "end": t_start + third,
            "zone_color": PHASE_COLORS[0],
        },
        {
            "name": PHASE_NAMES[1],
            "start": t_start + third,
            "end": t_start + 2 * third,
            "zone_color": PHASE_COLORS[1],
        },
        {
            "name": PHASE_NAMES[2],
            "start": t_start + 2 * third,
            "end": t_end,
            "zone_color": PHASE_COLORS[2],
        },
    ]


def detect_phases(imu_df: pd.DataFrame, n_phases: int = 3) -> list[dict]:
    """Detect action phases from IMU acceleration data.

    Computes acceleration magnitude, applies Butterworth low-pass filter,
    then uses scipy find_peaks to locate transition boundaries. Falls back
    to equal thirds when fewer than 2 peaks are found.

    Args:
        imu_df: DataFrame with columns timestamp_local, ax, ay, az.
        n_phases: Number of phases (default 3, only 3 supported).

    Returns:
        List of 3 phase dicts with keys: name, start, end, zone_color.
    """
    if imu_df.empty:
        return _equal_thirds(0.0, 1.0)

    timestamps = imu_df["timestamp_local"].values.astype(float)
    t_start = float(timestamps[0])
    t_end = float(timestamps[-1])

    ax = imu_df["ax"].values.astype(float)
    ay = imu_df["ay"].values.astype(float)
    az = imu_df["az"].values.astype(float)

    # Compute acceleration magnitude
    accel_mag = np.sqrt(ax**2 + ay**2 + az**2)

    # Apply Butterworth low-pass filter
    filtered = butterworth_filter(accel_mag)

    # Find peaks in filtered acceleration magnitude
    # distance = ~1 second at 72.5 Hz sampling rate
    peaks, properties = find_peaks(
        filtered, prominence=0.3, distance=max(1, int(72.5))
    )

    if len(peaks) < 2:
        # Not enough peaks -- fallback to equal thirds
        return _equal_thirds(t_start, t_end)

    # Use top-2 most prominent peaks as phase boundaries
    prominences = properties["prominences"]
    top2_idx = np.argsort(prominences)[-2:]
    top2_peaks = sorted(peaks[top2_idx])

    # Convert peak indices to timestamps
    boundary1 = float(timestamps[top2_peaks[0]])
    boundary2 = float(timestamps[top2_peaks[1]])

    return [
        {
            "name": PHASE_NAMES[0],
            "start": t_start,
            "end": boundary1,
            "zone_color": PHASE_COLORS[0],
        },
        {
            "name": PHASE_NAMES[1],
            "start": boundary1,
            "end": boundary2,
            "zone_color": PHASE_COLORS[1],
        },
        {
            "name": PHASE_NAMES[2],
            "start": boundary2,
            "end": t_end,
            "zone_color": PHASE_COLORS[2],
        },
    ]
