"""Vision-based angle calculations from MediaPipe landmarks.

Computes artistic-swimming-specific metrics such as leg deviation from
vertical, knee extension, shoulder-knee angle, leg symmetry, and trunk
verticality.  All public functions accept a DataFrame whose columns
follow the ``{side}_{joint}_{x|y|vis}`` naming convention produced by
MediaPipe pose estimation.

Visibility gating
-----------------
When any joint required for a metric has ``visibility < VIS_THRESHOLD``
the corresponding frame returns ``NaN`` so downstream code can skip
occluded frames instead of trusting MediaPipe's extrapolation of
invisible keypoints. Callers should aggregate with ``np.nanmean`` etc.
"""

import math

import numpy as np
import pandas as pd

from dashboard.core.angles import calc_angle

# Joints with visibility below this are treated as unknown.
VIS_THRESHOLD = 0.5


def _has_cols(df: pd.DataFrame, cols: list[str]) -> bool:
    return all(c in df.columns for c in cols)


def _vis(row: pd.Series, key: str) -> float:
    """Return visibility for ``{key}_vis`` column, or 1.0 if the column
    is missing (backward compatibility for older CSVs).
    """
    vc = f"{key}_vis"
    if vc not in row.index:
        return 1.0
    try:
        v = float(row[vc])
        return v if not np.isnan(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _angle_from_vertical(x1: float, y1: float, x2: float, y2: float) -> float:
    """Return the angle (degrees) between line (x1,y1)→(x2,y2) and vertical.

    In image coordinates the vertical axis runs along y (downward).
    0° means the line is perfectly vertical.
    """
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return 0.0
    cos_angle = abs(dy) / length
    cos_angle = min(max(cos_angle, -1.0), 1.0)
    return math.degrees(math.acos(cos_angle))


# ---------------------------------------------------------------------------
# Public per-frame metric functions
# ---------------------------------------------------------------------------

def calc_leg_deviation_vision(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Hip→Ankle line vs vertical reference.

    Returns NaN for frames where hip or ankle is occluded (visibility <
    ``VIS_THRESHOLD``).
    """
    cols = [f"{side}_hip_x", f"{side}_hip_y",
            f"{side}_ankle_x", f"{side}_ankle_y"]
    if not _has_cols(df, cols):
        return np.full(len(df), np.nan)

    results = np.empty(len(df))
    for i, (_, row) in enumerate(df.iterrows()):
        if _vis(row, f"{side}_hip") < VIS_THRESHOLD or _vis(row, f"{side}_ankle") < VIS_THRESHOLD:
            results[i] = np.nan
            continue
        results[i] = _angle_from_vertical(
            row[cols[0]], row[cols[1]],
            row[cols[2]], row[cols[3]],
        )
    return results


def calc_knee_extension(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Hip→Knee→Ankle angle. 180° = fully extended leg.

    Returns NaN for frames where hip/knee/ankle is occluded.
    """
    cols = [f"{side}_hip_x", f"{side}_hip_y",
            f"{side}_knee_x", f"{side}_knee_y",
            f"{side}_ankle_x", f"{side}_ankle_y"]
    if not _has_cols(df, cols):
        return np.full(len(df), np.nan)

    results = np.empty(len(df))
    for i, (_, row) in enumerate(df.iterrows()):
        if (_vis(row, f"{side}_hip") < VIS_THRESHOLD or
                _vis(row, f"{side}_knee") < VIS_THRESHOLD or
                _vis(row, f"{side}_ankle") < VIS_THRESHOLD):
            results[i] = np.nan
            continue
        a = (row[cols[0]], row[cols[1]])
        b = (row[cols[2]], row[cols[3]])
        c = (row[cols[4]], row[cols[5]])
        results[i] = calc_angle(a, b, c)
    return results


def calc_shoulder_knee_angle(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Shoulder→Hip→Knee angle. 180° = body in a straight line."""
    cols = [f"{side}_shoulder_x", f"{side}_shoulder_y",
            f"{side}_hip_x", f"{side}_hip_y",
            f"{side}_knee_x", f"{side}_knee_y"]
    if not _has_cols(df, cols):
        return np.full(len(df), np.nan)

    results = np.empty(len(df))
    for i, (_, row) in enumerate(df.iterrows()):
        if (_vis(row, f"{side}_shoulder") < VIS_THRESHOLD or
                _vis(row, f"{side}_hip") < VIS_THRESHOLD or
                _vis(row, f"{side}_knee") < VIS_THRESHOLD):
            results[i] = np.nan
            continue
        a = (row[cols[0]], row[cols[1]])
        b = (row[cols[2]], row[cols[3]])
        c = (row[cols[4]], row[cols[5]])
        results[i] = calc_angle(a, b, c)
    return results


def calc_leg_symmetry(df: pd.DataFrame) -> np.ndarray:
    """Absolute difference between left and right leg deviation.

    NaN propagates — if either leg is occluded on a frame the symmetry
    for that frame is also NaN.
    """
    left = calc_leg_deviation_vision(df, side="left")
    right = calc_leg_deviation_vision(df, side="right")
    return np.abs(left - right)


def calc_trunk_vertical(df: pd.DataFrame, side: str = "right") -> np.ndarray:
    """Shoulder→Hip line vs vertical. 0° = perfectly vertical trunk."""
    cols = [f"{side}_shoulder_x", f"{side}_shoulder_y",
            f"{side}_hip_x", f"{side}_hip_y"]
    if not _has_cols(df, cols):
        return np.full(len(df), np.nan)

    results = np.empty(len(df))
    for i, (_, row) in enumerate(df.iterrows()):
        if _vis(row, f"{side}_shoulder") < VIS_THRESHOLD or _vis(row, f"{side}_hip") < VIS_THRESHOLD:
            results[i] = np.nan
            continue
        results[i] = _angle_from_vertical(
            row[cols[0]], row[cols[1]],
            row[cols[2]], row[cols[3]],
        )
    return results


def visibility_ratio(df: pd.DataFrame, joints: list[str]) -> float:
    """Return the fraction of frames where all joints are visible.

    ``joints`` takes full column prefixes like ``right_hip``.
    """
    if df.empty or not joints:
        return 0.0
    mask = np.ones(len(df), dtype=bool)
    for j in joints:
        col = f"{j}_vis"
        if col not in df.columns:
            return 0.0
        mask &= df[col].astype(float).fillna(0.0).values >= VIS_THRESHOLD
    return float(mask.mean())
