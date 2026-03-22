"""Tests for dashboard/core/angles.py — Joint angle computation."""
import pytest


def test_calc_angle_90_degrees():
    """Right angle at origin: (1,0), (0,0), (0,1) should be ~90 degrees."""
    from dashboard.core.angles import calc_angle

    result = calc_angle((1, 0), (0, 0), (0, 1))
    assert abs(result - 90.0) < 0.01


def test_calc_angle_0_degrees():
    """Same direction: (1,0), (0,0), (1,0) should be ~0 degrees."""
    from dashboard.core.angles import calc_angle

    result = calc_angle((1, 0), (0, 0), (1, 0))
    assert abs(result - 0.0) < 0.01


def test_calc_angle_180_degrees():
    """Opposite direction: (1,0), (0,0), (-1,0) should be ~180 degrees."""
    from dashboard.core.angles import calc_angle

    result = calc_angle((1, 0), (0, 0), (-1, 0))
    assert abs(result - 180.0) < 0.01


def test_calc_angle_zero_length_segment():
    """When points coincide, return 0.0 (guard against division by zero)."""
    from dashboard.core.angles import calc_angle

    result = calc_angle((0, 0), (0, 0), (1, 1))
    assert result == 0.0


def test_calc_angle_returns_float():
    """calc_angle always returns a float."""
    from dashboard.core.angles import calc_angle

    result = calc_angle((3, 4), (0, 0), (4, 3))
    assert isinstance(result, float)
