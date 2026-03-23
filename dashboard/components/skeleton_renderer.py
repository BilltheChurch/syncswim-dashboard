"""Skeleton overlay rendering for keyframe comparison.

Draws green wireframe (standard template) and red wireframe (actual pose)
on video frames with deviation angle annotations at joints exceeding
the clean threshold.
"""

import math

import cv2
import numpy as np

# Same connections as sync_recorder.py POSE_CONNECTIONS
POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26),
    (25, 27), (26, 28),
]

# Joint triplets for angle computation (parent, joint, child)
_ANGLE_JOINTS = [
    (11, 13, 15),  # left elbow
    (12, 14, 16),  # right elbow
    (23, 25, 27),  # left knee
    (24, 26, 28),  # right knee
    (11, 23, 25),  # left hip
    (12, 24, 26),  # right hip
]


def _landmark_to_pixel(landmark, h: int, w: int) -> tuple[int, int]:
    """Convert normalized landmark coordinates to pixel position."""
    return (int(landmark.x * w), int(landmark.y * h))


def _calc_angle_3pt(a, b, c) -> float:
    """Calculate angle at point b formed by points a-b-c in pixel coords."""
    ba = np.array([a[0] - b[0], a[1] - b[1]], dtype=float)
    bc = np.array([c[0] - b[0], c[1] - b[1]], dtype=float)
    dot = np.dot(ba, bc)
    mag = np.linalg.norm(ba) * np.linalg.norm(bc)
    if mag == 0:
        return 0.0
    return math.degrees(math.acos(np.clip(dot / mag, -1.0, 1.0)))


def render_skeleton_frame(
    frame: np.ndarray,
    landmarks: list,
    color: tuple = (0, 255, 0),
    line_width: int = 2,
) -> np.ndarray:
    """Draw skeleton wireframe on a frame copy.

    Args:
        frame: BGR numpy array (original frame).
        landmarks: List of 33 landmarks with x, y, z, visibility attributes.
        color: BGR color tuple for skeleton lines and circles.
        line_width: Width of skeleton connection lines.

    Returns:
        Annotated frame copy with skeleton overlay.
    """
    out = frame.copy()
    h, w = out.shape[:2]

    # Draw connections
    for c1, c2 in POSE_CONNECTIONS:
        if c1 < len(landmarks) and c2 < len(landmarks):
            if landmarks[c1].visibility > 0.3 and landmarks[c2].visibility > 0.3:
                p1 = _landmark_to_pixel(landmarks[c1], h, w)
                p2 = _landmark_to_pixel(landmarks[c2], h, w)
                cv2.line(out, p1, p2, color, line_width)

    # Draw joint circles
    for lm in landmarks:
        if lm.visibility > 0.3:
            px = _landmark_to_pixel(lm, h, w)
            cv2.circle(out, px, 6, color, -1)

    return out


def render_keyframe_comparison(
    frame: np.ndarray,
    actual_landmarks: list,
    template_landmarks: list,
    config: dict,
) -> np.ndarray:
    """Render keyframe comparison with template (green) and actual (red) skeletons.

    Draws both skeletons on the same frame. For each angle joint, computes
    the deviation between actual and template. If deviation exceeds the
    clean threshold, draws a red annotation label at that joint.

    Args:
        frame: BGR numpy array (video frame).
        actual_landmarks: List of 33 landmarks from actual pose detection.
        template_landmarks: List of 33 landmarks from standard template.
        config: Config dict with config["fina"]["clean_threshold_deg"].

    Returns:
        Annotated frame with both skeletons and deviation callouts.
    """
    clean_threshold = config.get("fina", {}).get("clean_threshold_deg", 15)

    # Draw template skeleton in green (standard pose)
    out = render_skeleton_frame(frame, template_landmarks, color=(0, 255, 0), line_width=2)
    # Draw actual skeleton in red (measured pose) on top
    out = render_skeleton_frame(out, actual_landmarks, color=(0, 0, 255), line_width=2)

    h, w = out.shape[:2]

    # Compute and annotate deviation angles at key joints
    for a_idx, b_idx, c_idx in _ANGLE_JOINTS:
        if (a_idx >= len(actual_landmarks) or b_idx >= len(actual_landmarks)
                or c_idx >= len(actual_landmarks)):
            continue
        if (a_idx >= len(template_landmarks) or b_idx >= len(template_landmarks)
                or c_idx >= len(template_landmarks)):
            continue

        # Check visibility
        if (actual_landmarks[b_idx].visibility < 0.3
                or template_landmarks[b_idx].visibility < 0.3):
            continue

        # Compute angles
        actual_a = _landmark_to_pixel(actual_landmarks[a_idx], h, w)
        actual_b = _landmark_to_pixel(actual_landmarks[b_idx], h, w)
        actual_c = _landmark_to_pixel(actual_landmarks[c_idx], h, w)
        actual_angle = _calc_angle_3pt(actual_a, actual_b, actual_c)

        template_a = _landmark_to_pixel(template_landmarks[a_idx], h, w)
        template_b = _landmark_to_pixel(template_landmarks[b_idx], h, w)
        template_c = _landmark_to_pixel(template_landmarks[c_idx], h, w)
        template_angle = _calc_angle_3pt(template_a, template_b, template_c)

        deviation = abs(actual_angle - template_angle)

        if deviation > clean_threshold:
            # Draw deviation annotation at the joint position
            joint_px = _landmark_to_pixel(actual_landmarks[b_idx], h, w)
            label = f"{deviation:.1f} deg"

            # White background rectangle for readability
            (text_w, text_h), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            rect_x = joint_px[0] + 10
            rect_y = joint_px[1] - 10
            cv2.rectangle(
                out,
                (rect_x - 2, rect_y - text_h - 2),
                (rect_x + text_w + 2, rect_y + baseline + 2),
                (255, 255, 255),
                -1,
            )
            # Red text for deviation
            cv2.putText(
                out,
                label,
                (rect_x, rect_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255),
                1,
            )

    return out
