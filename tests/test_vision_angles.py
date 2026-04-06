"""Tests for dashboard/core/vision_angles.py — Vision-based angle metrics."""

import numpy as np
import pandas as pd
import pytest

from dashboard.core.vision_angles import (
    _angle_from_vertical,
    calc_knee_extension,
    calc_leg_deviation_vision,
    calc_leg_symmetry,
    calc_shoulder_knee_angle,
    calc_trunk_vertical,
)


# ---------------------------------------------------------------------------
# Helper: synthetic landmarks DataFrame
# ---------------------------------------------------------------------------

def _make_landmarks_df(n_frames: int = 10, **overrides) -> pd.DataFrame:
    """Generate a synthetic landmarks DataFrame with an upright standing pose.

    Normalised coordinates (0-1), y increases downward.

    Default layout (per frame):
        shoulders  y=0.3   left x=0.45, right x=0.55
        hips       y=0.5   left x=0.45, right x=0.55
        knees      y=0.7   left x=0.45, right x=0.55
        ankles     y=0.9   left x=0.45, right x=0.55
        visibility = 0.9 everywhere
    """
    defaults = {
        # Left side
        "left_shoulder_x": 0.45,
        "left_shoulder_y": 0.3,
        "left_hip_x": 0.45,
        "left_hip_y": 0.5,
        "left_knee_x": 0.45,
        "left_knee_y": 0.7,
        "left_ankle_x": 0.45,
        "left_ankle_y": 0.9,
        # Right side
        "right_shoulder_x": 0.55,
        "right_shoulder_y": 0.3,
        "right_hip_x": 0.55,
        "right_hip_y": 0.5,
        "right_knee_x": 0.55,
        "right_knee_y": 0.7,
        "right_ankle_x": 0.55,
        "right_ankle_y": 0.9,
        # Visibility
        "left_shoulder_visibility": 0.9,
        "left_hip_visibility": 0.9,
        "left_knee_visibility": 0.9,
        "left_ankle_visibility": 0.9,
        "right_shoulder_visibility": 0.9,
        "right_hip_visibility": 0.9,
        "right_knee_visibility": 0.9,
        "right_ankle_visibility": 0.9,
    }
    defaults.update(overrides)
    data = {col: [val] * n_frames for col, val in defaults.items()}
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# TestLegDeviation
# ---------------------------------------------------------------------------

class TestLegDeviation:
    """calc_leg_deviation_vision tests."""

    def test_vertical_leg_near_zero(self):
        """Straight vertical hip→ankle should give ~0°."""
        df = _make_landmarks_df()
        result = calc_leg_deviation_vision(df, side="right")
        assert all(abs(v) < 1.0 for v in result)

    def test_angled_leg_above_30(self):
        """Ankle shifted sideways should give >30°."""
        df = _make_landmarks_df(right_ankle_x=0.55 + 0.4)
        result = calc_leg_deviation_vision(df, side="right")
        assert all(v > 30.0 for v in result)

    def test_missing_columns_returns_zeros(self):
        """Missing landmark columns should return all zeros."""
        df = pd.DataFrame({"dummy": [1, 2, 3]})
        result = calc_leg_deviation_vision(df, side="right")
        np.testing.assert_array_equal(result, np.zeros(3))

    def test_left_side(self):
        """Left side works identically when columns present."""
        df = _make_landmarks_df()
        result = calc_leg_deviation_vision(df, side="left")
        assert all(abs(v) < 1.0 for v in result)


# ---------------------------------------------------------------------------
# TestKneeExtension
# ---------------------------------------------------------------------------

class TestKneeExtension:
    """calc_knee_extension tests."""

    def test_straight_leg_near_180(self):
        """Straight leg (hip-knee-ankle collinear) should be ~180°."""
        df = _make_landmarks_df()
        result = calc_knee_extension(df, side="right")
        assert all(abs(v - 180.0) < 1.0 for v in result)

    def test_bent_knee_below_170(self):
        """Knee shifted sideways should give <170°."""
        df = _make_landmarks_df(right_knee_x=0.55 + 0.15)
        result = calc_knee_extension(df, side="right")
        assert all(v < 170.0 for v in result)

    def test_missing_columns_returns_180(self):
        """Missing columns should return 180.0 for every frame."""
        df = pd.DataFrame({"dummy": [1, 2, 3]})
        result = calc_knee_extension(df, side="right")
        np.testing.assert_array_equal(result, np.full(3, 180.0))


# ---------------------------------------------------------------------------
# TestShoulderKneeAngle
# ---------------------------------------------------------------------------

class TestShoulderKneeAngle:
    """calc_shoulder_knee_angle tests."""

    def test_straight_body_near_180(self):
        """Shoulder-hip-knee collinear should be ~180°."""
        df = _make_landmarks_df()
        result = calc_shoulder_knee_angle(df, side="right")
        assert all(abs(v - 180.0) < 1.0 for v in result)

    def test_missing_columns_returns_180(self):
        """Missing columns should return 180.0 for every frame."""
        df = pd.DataFrame({"dummy": [1, 2]})
        result = calc_shoulder_knee_angle(df, side="right")
        np.testing.assert_array_equal(result, np.full(2, 180.0))


# ---------------------------------------------------------------------------
# TestLegSymmetry
# ---------------------------------------------------------------------------

class TestLegSymmetry:
    """calc_leg_symmetry tests."""

    def test_symmetric_near_zero(self):
        """Both legs vertical → symmetry ~0°."""
        df = _make_landmarks_df()
        result = calc_leg_symmetry(df)
        assert all(abs(v) < 1.0 for v in result)

    def test_asymmetric_above_20(self):
        """One leg angled, other vertical → symmetry >20°."""
        df = _make_landmarks_df(right_ankle_x=0.55 + 0.4)
        result = calc_leg_symmetry(df)
        assert all(v > 20.0 for v in result)


# ---------------------------------------------------------------------------
# TestTrunkVertical
# ---------------------------------------------------------------------------

class TestTrunkVertical:
    """calc_trunk_vertical tests."""

    def test_upright_near_zero(self):
        """Upright torso (shoulder directly above hip) should be ~0°."""
        df = _make_landmarks_df()
        result = calc_trunk_vertical(df, side="right")
        assert all(abs(v) < 1.0 for v in result)

    def test_leaning_above_10(self):
        """Shoulder shifted sideways should give >10°."""
        df = _make_landmarks_df(right_shoulder_x=0.55 + 0.1)
        result = calc_trunk_vertical(df, side="right")
        assert all(v > 10.0 for v in result)

    def test_missing_columns_returns_zeros(self):
        """Missing columns should return all zeros."""
        df = pd.DataFrame({"dummy": [1, 2, 3]})
        result = calc_trunk_vertical(df, side="right")
        np.testing.assert_array_equal(result, np.zeros(3))
