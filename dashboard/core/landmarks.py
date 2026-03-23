"""Landmark utilities for video frame extraction, MediaPipe re-processing, and CSV loading.

Provides functions to extract individual frames from saved MP4 video,
re-run MediaPipe PoseLandmarker on those frames, and load expanded
landmarks.csv data for skeleton overlay rendering.
"""

from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import pandas as pd
import streamlit as st
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)

# ─── 33 MediaPipe Pose Landmarks ─────────────────────────
# Duplicated from sync_recorder.py for dashboard independence
LANDMARK_NAMES = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]


def get_landmark_csv_header() -> list[str]:
    """Return the 134-column header for the landmarks CSV.

    Format: timestamp_local, frame, then 4 columns per landmark (x, y, z, vis).
    """
    header = ["timestamp_local", "frame"]
    for name in LANDMARK_NAMES:
        header.extend([f"{name}_x", f"{name}_y", f"{name}_z", f"{name}_vis"])
    return header


@st.cache_resource
def get_landmarker() -> PoseLandmarker:
    """Create and cache a MediaPipe PoseLandmarker for IMAGE mode.

    Model path resolved relative to project root (two levels up from this file).
    """
    model_path = Path(__file__).parent.parent.parent / "pose_landmarker_lite.task"
    options = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=RunningMode.IMAGE,
        min_pose_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return PoseLandmarker.create_from_options(options)


def extract_frame(video_path: str, frame_idx: int) -> np.ndarray | None:
    """Extract a single frame from a video file by index.

    Args:
        video_path: Path to the MP4 video file.
        frame_idx: Zero-based frame index to extract.

    Returns:
        BGR numpy array of the frame, or None if extraction fails.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            return None
        return frame
    finally:
        cap.release()


def detect_landmarks(frame: np.ndarray) -> list | None:
    """Run MediaPipe PoseLandmarker on a single BGR frame.

    Args:
        frame: BGR numpy array from OpenCV.

    Returns:
        List of 33 NormalizedLandmark objects, or None if no pose detected.
    """
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    results = get_landmarker().detect(mp_image)
    if results.pose_landmarks and len(results.pose_landmarks) > 0:
        return results.pose_landmarks[0]
    return None


def load_landmarks_csv(set_dir: str) -> pd.DataFrame:
    """Load landmarks.csv from a set directory.

    Args:
        set_dir: Path to the set directory containing landmarks.csv.

    Returns:
        DataFrame with landmark data, or empty DataFrame if file missing.
    """
    csv_path = Path(set_dir) / "landmarks.csv"
    if not csv_path.exists():
        return pd.DataFrame()
    return pd.read_csv(csv_path)


def get_total_frames(video_path: str) -> int:
    """Get total frame count from a video file.

    Args:
        video_path: Path to the MP4 video file.

    Returns:
        Total number of frames, or 0 if video cannot be opened.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()
