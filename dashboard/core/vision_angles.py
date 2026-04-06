"""Vision-based angle calculations from MediaPipe landmarks.

Computes artistic-swimming-specific metrics such as leg deviation from
vertical, knee extension, shoulder-knee angle, leg symmetry, and trunk
verticality.  All public functions accept a DataFrame whose columns
follow the ``{side}_{joint}_{x|y}`` naming convention produced by
MediaPipe pose estimation.
"""

import math

import numpy as np
import pandas as pd

from dashboard.core.angles import calc_angle


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------

def _angle_from_vertical(x1: float, y1: float, x2: float, y2: float) -> float:
    """Return the angle (degrees) between line (x1,y1)→(x2,y2) and vertical.

    In image coordinates the vertical axis runs along y (downward).
    0° means the line is perfectly vertical.

    Returns 0.0 when the two points coincide (zero-length segment).
    """
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return 0.0
    cos_angle = abs(dy) / length
    # Clamp for floating-point safety
    cos_angle = min(max(cos_angle, -1.0), 1.0)
    return math.degrees(math.acos(cos_angle))


# ---------------------------------------------------------------------------
# Public per-frame metric functions
# ---------------------------------------------------------------------------

def calc_leg_deviation_vision(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Hip→Ankle line vs vertical reference.

    0° = perfectly vertical (ideal ballet leg).
    Returns an array of zeros when required columns are missing.
    """
    cols = [f"{side}_hip_x", f"{side}_hip_y",
            f"{side}_ankle_x", f"{side}_ankle_y"]
    if not all(c in df.columns for c in cols):
        return np.zeros(len(df))

    results = []
    for _, row in df.iterrows():
        angle = _angle_from_vertical(
            row[cols[0]], row[cols[1]],
            row[cols[2]], row[cols[3]],
        )
        results.append(angle)
    return np.array(results)


def calc_knee_extension(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Hip→Knee→Ankle angle via calc_angle.

    180° = fully extended leg.
    Returns 180.0 for every frame when required columns are missing.
    """
    cols = [f"{side}_hip_x", f"{side}_hip_y",
            f"{side}_knee_x", f"{side}_knee_y",
            f"{side}_ankle_x", f"{side}_ankle_y"]
    if not all(c in df.columns for c in cols):
        return np.full(len(df), 180.0)

    results = []
    for _, row in df.iterrows():
        a = (row[cols[0]], row[cols[1]])  # hip
        b = (row[cols[2]], row[cols[3]])  # knee (vertex)
        c = (row[cols[4]], row[cols[5]])  # ankle
        results.append(calc_angle(a, b, c))
    return np.array(results)


def calc_shoulder_knee_angle(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Shoulder→Hip→Knee angle via calc_angle.

    180° = body in a straight line.
    Returns 180.0 for every frame when required columns are missing.
    """
    cols = [f"{side}_shoulder_x", f"{side}_shoulder_y",
            f"{side}_hip_x", f"{side}_hip_y",
            f"{side}_knee_x", f"{side}_knee_y"]
    if not all(c in df.columns for c in cols):
        return np.full(len(df), 180.0)

    results = []
    for _, row in df.iterrows():
        a = (row[cols[0]], row[cols[1]])  # shoulder
        b = (row[cols[2]], row[cols[3]])  # hip (vertex)
        c = (row[cols[4]], row[cols[5]])  # knee
        results.append(calc_angle(a, b, c))
    return np.array(results)


def calc_leg_symmetry(df: pd.DataFrame) -> np.ndarray:
    """Absolute difference between left and right leg deviation.

    0° = perfect symmetry.
    """
    left = calc_leg_deviation_vision(df, side="left")
    right = calc_leg_deviation_vision(df, side="right")
    return np.abs(left - right)


def calc_trunk_vertical(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Shoulder→Hip line vs vertical reference using _angle_from_vertical.

    0° = trunk perfectly vertical.
    Returns zeros when required columns are missing.
    """
    cols = [f"{side}_shoulder_x", f"{side}_shoulder_y",
            f"{side}_hip_x", f"{side}_hip_y"]
    if not all(c in df.columns for c in cols):
        return np.zeros(len(df))

    results = []
    for _, row in df.iterrows():
        angle = _angle_from_vertical(
            row[cols[0]], row[cols[1]],
            row[cols[2]], row[cols[3]],
        )
        results.append(angle)
    return np.array(results)
