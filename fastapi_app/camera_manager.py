"""Camera MJPEG stream reader with MediaPipe pose detection.

Ported from sync_recorder.py for the Coach Workstation FastAPI backend.
Reads MJPEG from DroidCam, runs MediaPipe PoseLandmarker (IMAGE mode),
computes biomechanical angles, and exposes thread-safe latest frame/results.
"""

import math
import os
import threading
import time
import urllib.request

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)

from dashboard.config import load_config
from dashboard.core.angles import calc_angle

# Skeleton connections for rendering (same as sync_recorder.py)
POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26),
    (25, 27), (26, 28),
]

# MediaPipe model path (project root)
_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "pose_landmarker_lite.task"
)


# ---------------------------------------------------------------------------
# MJPEG Stream Reader (background thread)
# ---------------------------------------------------------------------------

class _MjpegStreamReader:
    """Reads MJPEG frames from a DroidCam URL in a daemon thread.

    Parses JPEG boundaries (0xFFD8 .. 0xFFD9) from the raw HTTP stream
    and keeps only the latest decoded frame.
    """

    def __init__(self, url: str):
        self.url = url
        self.frame: np.ndarray | None = None
        self.lock = threading.Lock()
        self.running = True
        self.connected = False
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while self.running:
            try:
                stream = urllib.request.urlopen(self.url, timeout=5)
                self.connected = True
                buf = b""
                while self.running:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    start = buf.find(b"\xff\xd8")
                    end = buf.find(b"\xff\xd9")
                    if start != -1 and end != -1 and end > start:
                        jpg = buf[start:end + 2]
                        buf = buf[end + 2:]
                        arr = np.frombuffer(jpg, dtype=np.uint8)
                        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if frame is not None:
                            with self.lock:
                                self.frame = frame
            except Exception:
                self.connected = False
                if self.running:
                    time.sleep(1)

    def read(self) -> tuple[bool, np.ndarray | None]:
        with self.lock:
            if self.frame is not None:
                return True, self.frame.copy()
            return False, None

    def release(self):
        self.running = False


# ---------------------------------------------------------------------------
# Angle helpers (single-frame, from normalized landmarks)
# ---------------------------------------------------------------------------

def _angle_from_vertical(x1: float, y1: float, x2: float, y2: float) -> float:
    """Angle between line (x1,y1)->(x2,y2) and the vertical axis (degrees).

    0 degrees = perfectly vertical. Uses image coordinates where y runs down.
    """
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return 0.0
    cos_angle = min(max(abs(dy) / length, -1.0), 1.0)
    return math.degrees(math.acos(cos_angle))


def _compute_angles(landmarks, w: int, h: int) -> dict:
    """Compute biomechanical angles from a single set of 33 landmarks.

    Args:
        landmarks: MediaPipe NormalizedLandmarkList (33 points).
        w: Frame width in pixels (for denormalization).
        h: Frame height in pixels (for denormalization).

    Returns:
        Dict with angle names -> float values.
    """
    lm = landmarks

    # Helper to extract pixel coords
    def pt(idx):
        return (lm[idx].x * w, lm[idx].y * h)

    # Helper to extract normalized coords
    def ptn(idx):
        return (lm[idx].x, lm[idx].y)

    angles = {}

    # leg_deviation: hip(24) -> ankle(28) vs vertical (normalized coords)
    hip24 = ptn(24)
    ankle28 = ptn(28)
    angles["leg_deviation"] = _angle_from_vertical(
        hip24[0], hip24[1], ankle28[0], ankle28[1]
    )

    # knee_extension: calc_angle(hip24, knee26, ankle28) in pixel coords
    angles["knee_extension"] = calc_angle(pt(24), pt(26), pt(28))

    # shoulder_knee_angle: calc_angle(shoulder12, hip24, knee26) in pixel coords
    angles["shoulder_knee_angle"] = calc_angle(pt(12), pt(24), pt(26))

    # trunk_vertical: shoulder(12) -> hip(24) vs vertical (normalized coords)
    shoulder12 = ptn(12)
    angles["trunk_vertical"] = _angle_from_vertical(
        shoulder12[0], shoulder12[1], hip24[0], hip24[1]
    )

    # elbow: calc_angle(shoulder12, elbow14, wrist16) in pixel coords
    angles["elbow"] = calc_angle(pt(12), pt(14), pt(16))

    return angles


# ---------------------------------------------------------------------------
# CameraManager
# ---------------------------------------------------------------------------

class CameraManager:
    """Manages camera MJPEG streaming and MediaPipe pose detection.

    Usage::

        cam = CameraManager()
        cam.start()
        # ... later ...
        result = cam.get_latest()  # dict with jpeg, landmarks, angles
        cam.stop()
    """

    def __init__(self, camera_url: str | None = None):
        if camera_url is None:
            cfg = load_config()
            camera_url = cfg.get("hardware", {}).get(
                "camera_url", "http://192.168.66.169:4747/video"
            )
        self._camera_url = camera_url
        self._rotation = 0

        # Internal state
        self._stream: _MjpegStreamReader | None = None
        self._landmarker: PoseLandmarker | None = None
        self._thread: threading.Thread | None = None
        self._running = False

        # Thread-safe latest result buffer
        self._lock = threading.Lock()
        self._latest: dict | None = None

    # -- Properties ---------------------------------------------------------

    @property
    def rotation(self) -> int:
        """Current frame rotation in degrees (0, 90, 180, 270)."""
        return self._rotation

    @rotation.setter
    def rotation(self, value: int):
        value = value % 360
        if value not in (0, 90, 180, 270):
            raise ValueError(f"Rotation must be 0, 90, 180, or 270; got {value}")
        self._rotation = value

    # -- Public API ---------------------------------------------------------

    def set_url(self, url: str) -> None:
        """Change camera URL. Restarts the stream if already running."""
        self._camera_url = url
        if self._running:
            self.stop()
            self.start()

    def start(self) -> None:
        """Launch the background processing thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread and release resources."""
        self._running = False

        if self._stream is not None:
            self._stream.release()
            self._stream = None

        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None

        with self._lock:
            self._latest = None

    def get_latest(self) -> dict | None:
        """Return the latest processed frame, or None if unavailable.

        Returns:
            Dict with keys:
                - ``jpeg``: JPEG-encoded frame bytes
                - ``raw_frame``: BGR numpy array (for video recording)
                - ``landmarks``: list of [x, y, visibility] for 33 points
                - ``angles``: dict of angle name -> float
            Returns None when no frame has been processed yet.
        """
        with self._lock:
            return self._latest

    # -- Background processing loop -----------------------------------------

    def _run(self):
        """Main camera + MediaPipe processing loop (runs in a thread)."""
        # Create MJPEG reader
        self._stream = _MjpegStreamReader(self._camera_url)

        # Wait briefly for first frame
        for _ in range(50):
            if not self._running:
                return
            if self._stream.connected:
                ret, _ = self._stream.read()
                if ret:
                    break
            time.sleep(0.1)

        # Create MediaPipe PoseLandmarker
        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_MODEL_PATH),
            running_mode=RunningMode.IMAGE,
            min_pose_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = PoseLandmarker.create_from_options(options)

        while self._running:
            ret, frame = self._stream.read()
            if not ret:
                time.sleep(0.01)
                continue

            # Apply rotation
            if self._rotation == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif self._rotation == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif self._rotation == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)

            h, w = frame.shape[:2]

            # MediaPipe detection
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            results = self._landmarker.detect(mp_image)

            # Build landmarks list and angles
            landmarks_list: list[list[float]] = []
            angles: dict[str, float] = {
                "leg_deviation": 0.0,
                "knee_extension": 180.0,
                "shoulder_knee_angle": 180.0,
                "trunk_vertical": 0.0,
                "elbow": 0.0,
            }

            if results.pose_landmarks and len(results.pose_landmarks) > 0:
                lm = results.pose_landmarks[0]
                landmarks_list = [
                    [l.x, l.y, l.visibility] for l in lm
                ]
                angles = _compute_angles(lm, w, h)

            # JPEG encode
            ok, jpeg_buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
            )
            if not ok:
                continue

            result = {
                "jpeg": jpeg_buf.tobytes(),
                "raw_frame": frame,
                "landmarks": landmarks_list,
                "angles": angles,
            }

            with self._lock:
                self._latest = result
