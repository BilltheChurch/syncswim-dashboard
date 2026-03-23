"""Tests for landmark utilities and skeleton rendering modules."""

import numpy as np
import pandas as pd
import pytest


class TestLandmarkNames:
    """Tests for LANDMARK_NAMES constant."""

    def test_landmark_names_length(self):
        from dashboard.core.landmarks import LANDMARK_NAMES
        assert len(LANDMARK_NAMES) == 33

    def test_landmark_csv_header_length(self):
        from dashboard.core.landmarks import get_landmark_csv_header
        header = get_landmark_csv_header()
        assert len(header) == 134

    def test_landmark_csv_header_starts_with_timestamp(self):
        from dashboard.core.landmarks import get_landmark_csv_header
        header = get_landmark_csv_header()
        assert header[0] == "timestamp_local"
        assert header[1] == "frame"


class TestPoseConnections:
    """Tests for POSE_CONNECTIONS constant."""

    def test_pose_connections_valid(self):
        from dashboard.components.skeleton_renderer import POSE_CONNECTIONS
        for c1, c2 in POSE_CONNECTIONS:
            assert 0 <= c1 <= 32, f"Connection index {c1} out of range"
            assert 0 <= c2 <= 32, f"Connection index {c2} out of range"


class TestSkeletonRenderer:
    """Tests for skeleton rendering functions."""

    def _make_fake_landmarks(self, h=480, w=640):
        """Create synthetic landmark list with x, y, z, visibility attrs."""

        class FakeLandmark:
            def __init__(self, x, y, z, visibility):
                self.x = x
                self.y = y
                self.z = z
                self.visibility = visibility

        landmarks = []
        for i in range(33):
            landmarks.append(FakeLandmark(
                x=(i * 0.03) % 1.0,
                y=(i * 0.03) % 1.0,
                z=0.0,
                visibility=0.9,
            ))
        return landmarks

    def test_render_skeleton_frame_returns_ndarray(self):
        from dashboard.components.skeleton_renderer import render_skeleton_frame
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        landmarks = self._make_fake_landmarks()
        result = render_skeleton_frame(frame, landmarks)
        assert isinstance(result, np.ndarray)
        assert result.shape[2] == 3  # BGR channels
        assert result.shape == (480, 640, 3)

    def test_render_keyframe_comparison_returns_ndarray(self):
        from dashboard.components.skeleton_renderer import render_keyframe_comparison
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        actual = self._make_fake_landmarks()
        template = self._make_fake_landmarks()
        config = {
            "fina": {
                "clean_threshold_deg": 15,
                "minor_deduction_deg": 30,
            }
        }
        result = render_keyframe_comparison(frame, actual, template, config)
        assert isinstance(result, np.ndarray)
        assert result.shape[2] == 3


class TestFrameExtraction:
    """Tests for video frame extraction."""

    def test_extract_frame_nonexistent_video(self):
        from dashboard.core.landmarks import extract_frame
        result = extract_frame("/nonexistent/path/video.mp4", 0)
        assert result is None


class TestLandmarkCSVLoading:
    """Tests for landmark CSV loading."""

    def test_load_landmarks_csv_missing(self):
        from dashboard.core.landmarks import load_landmarks_csv
        result = load_landmarks_csv("/nonexistent/path")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
