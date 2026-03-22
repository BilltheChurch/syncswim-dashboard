"""Joint angle computation functions.

Extracted from vision.py / sync_recorder.py for shared use.
"""
import math
import numpy as np


def calc_angle(a: tuple, b: tuple, c: tuple) -> float:
    """Calculate angle at point b given three (x, y) points.

    Uses the dot-product formula: angle = acos(dot(BA, BC) / (|BA| * |BC|)).

    Args:
        a: (x, y) tuple for first point.
        b: (x, y) tuple for vertex point (angle measured here).
        c: (x, y) tuple for third point.

    Returns:
        Angle in degrees (0-180). Returns 0.0 if any segment has zero length.
    """
    ba = np.array([a[0] - b[0], a[1] - b[1]])
    bc = np.array([c[0] - b[0], c[1] - b[1]])

    dot = np.dot(ba, bc)
    mag_ba = np.linalg.norm(ba)
    mag_bc = np.linalg.norm(bc)

    if mag_ba == 0 or mag_bc == 0:
        return 0.0

    cosine = np.clip(dot / (mag_ba * mag_bc), -1.0, 1.0)
    return math.degrees(math.acos(cosine))
