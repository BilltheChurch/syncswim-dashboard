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

# MediaPipe model path (project root).
#   - lite:  ~6 MB, fastest, lowest accuracy
#   - full:  ~10 MB, balanced (not bundled by default)
#   - heavy: ~30 MB, highest accuracy — recommended for artistic swimming
# Choice is driven by config.hardware.pose_model_size ("heavy" | "lite").
_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))


def _resolve_model_path(size_pref: str = "heavy") -> str:
    """Return path to the preferred MediaPipe pose model, falling back to lite."""
    candidates = []
    if size_pref == "heavy":
        candidates = ["pose_landmarker_heavy.task", "pose_landmarker_full.task",
                      "pose_landmarker_lite.task"]
    elif size_pref == "full":
        candidates = ["pose_landmarker_full.task", "pose_landmarker_heavy.task",
                      "pose_landmarker_lite.task"]
    else:
        candidates = ["pose_landmarker_lite.task", "pose_landmarker_full.task",
                      "pose_landmarker_heavy.task"]
    for fname in candidates:
        p = os.path.join(_PROJECT_ROOT, fname)
        if os.path.exists(p):
            return p
    # Last-ditch fallback (will fail-fast at Landmarker creation)
    return os.path.join(_PROJECT_ROOT, "pose_landmarker_lite.task")


_MODEL_PATH = _resolve_model_path(
    load_config().get("hardware", {}).get("pose_model_size", "heavy")
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


# Only report an angle when ALL joints required for it have
# visibility >= this threshold.  MediaPipe invents plausible coordinates
# for occluded joints, so without this gate the dashboard shows fake
# values for body parts that never entered the frame.
LIVE_VIS_THRESHOLD = 0.5


def _compute_angles(landmarks, w: int, h: int) -> dict:
    """Compute biomechanical angles from a single set of 33 landmarks.

    Returns only the metrics whose underlying joints are actually visible
    (``visibility >= LIVE_VIS_THRESHOLD``).  Occluded metrics are simply
    omitted from the dict so callers can display ``"--"`` instead of a
    fabricated number.
    """
    lm = landmarks

    def v(idx):
        return getattr(lm[idx], "visibility", 1.0)

    def ok(*idxs):
        return all(v(i) >= LIVE_VIS_THRESHOLD for i in idxs)

    def pt(idx):
        return (lm[idx].x * w, lm[idx].y * h)

    def ptn(idx):
        return (lm[idx].x, lm[idx].y)

    angles: dict[str, float] = {}

    # leg_deviation: hip(24) → ankle(28) vs vertical
    if ok(24, 28):
        hip24 = ptn(24); ankle28 = ptn(28)
        angles["leg_deviation"] = _angle_from_vertical(
            hip24[0], hip24[1], ankle28[0], ankle28[1],
        )

    # knee_extension: hip(24) → knee(26) → ankle(28)
    if ok(24, 26, 28):
        angles["knee_extension"] = calc_angle(pt(24), pt(26), pt(28))

    # shoulder_knee_angle: shoulder(12) → hip(24) → knee(26)
    if ok(12, 24, 26):
        angles["shoulder_knee_angle"] = calc_angle(pt(12), pt(24), pt(26))

    # trunk_vertical: shoulder(12) → hip(24)
    if ok(12, 24):
        shoulder12 = ptn(12); hip24 = ptn(24)
        angles["trunk_vertical"] = _angle_from_vertical(
            shoulder12[0], shoulder12[1], hip24[0], hip24[1],
        )

    # elbow: shoulder(12) → elbow(14) → wrist(16)
    if ok(12, 14, 16):
        angles["elbow"] = calc_angle(pt(12), pt(14), pt(16))

    # Left-side mirror (useful when body faces the other way in side view)
    if ok(11, 13, 15):
        angles["elbow_left"] = calc_angle(pt(11), pt(13), pt(15))
    if ok(23, 27):
        hipL = ptn(23); ankleL = ptn(27)
        angles["leg_deviation_left"] = _angle_from_vertical(
            hipL[0], hipL[1], ankleL[0], ankleL[1],
        )
    if ok(23, 25, 27):
        angles["knee_extension_left"] = calc_angle(pt(23), pt(25), pt(27))

    # Shoulder line horizontality (useful in side view to detect body roll)
    if ok(11, 12):
        l = ptn(11); r = ptn(12)
        angles["shoulder_line"] = _angle_from_vertical(l[0], l[1], r[0], r[1])

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

    def __init__(self, camera_url: str | None = None, rotation: int | None = None):
        cfg_hw = load_config().get("hardware", {})
        if camera_url is None:
            camera_url = cfg_hw.get("camera_url", "http://192.168.66.169:4747/video")
        if rotation is None:
            rotation = int(cfg_hw.get("camera_rotation", 0))
            if rotation not in (0, 90, 180, 270):
                rotation = 0
        self._camera_url = camera_url
        self._rotation = rotation

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

    def reset_tracking(self) -> None:
        """Reset the per-person tracker so the next frame's BYTETracker
        IDs start at 1 again. Called at recording start so IDs don't
        leak across Sets — see ``YoloPoseDetector.reset_tracking``.
        Safe no-op when running on the MediaPipe backend.
        """
        if self._backend == "yolo" and self._yolo is not None:
            self._yolo.reset_tracking()

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

        # Pose detection config, tunable from config.toml:
        #
        # * `num_poses`          up to 8 for team free routines
        # * `pose_mode`          "video" (smoother, tracks through occlusion,
        #                        but re-detection relies on face cues)
        #                        or "image" (every-frame independent detection,
        #                        more robust to face occlusion but jittery)
        # * `pose_det_conf`      min confidence to START a detection
        #                        (lower = more chance of locking onto a body
        #                        whose face is blocked)
        # * `pose_track_conf`    min confidence to KEEP tracking. Low values
        #                        let the pose persist through occlusion rather
        #                        than popping in/out.
        cfg_hw = load_config().get("hardware", {})
        num_poses = max(1, min(10, int(cfg_hw.get("num_poses", 8))))
        mode_str = str(cfg_hw.get("pose_mode", "video")).lower()
        det_conf = float(cfg_hw.get("pose_det_conf", 0.5))
        pres_conf = float(cfg_hw.get("pose_pres_conf", 0.5))
        trk_conf = float(cfg_hw.get("pose_track_conf", 0.4))
        backend = str(cfg_hw.get("pose_backend", "mediapipe")).lower()

        self._backend = backend
        self._num_poses = num_poses
        self._pose_mode = mode_str

        # ────────── YOLO backend ──────────
        # Reliable multi-person detection (MediaPipe 0.10 num_poses>1 is
        # flaky on non-square frames — see DEVLOG).
        if backend == "yolo":
            from fastapi_app.yolo_pose import create_pose_detector
            yolo_model = cfg_hw.get(
                "yolo_model", os.path.join(_PROJECT_ROOT, "yolov8n-pose.pt")
            )
            yolo_conf = float(cfg_hw.get("yolo_conf", 0.35))
            yolo_device = str(cfg_hw.get("yolo_device", "mps"))
            yolo_imgsz = int(cfg_hw.get("yolo_imgsz", 640))
            # Phase A: optional custom-trained detector. When set, the
            # factory returns a HybridSwimmerDetector (custom bbox +
            # COCO keypoints). Path is resolved relative to project root.
            sd_raw = cfg_hw.get("swimmer_detector")
            sd_path: str | None = None
            if sd_raw:
                sd_path = (
                    sd_raw if os.path.isabs(sd_raw)
                    else os.path.join(_PROJECT_ROOT, sd_raw)
                )
            self._yolo = create_pose_detector(
                swimmer_detector_path=sd_path,
                pose_model_path=yolo_model,
                conf=yolo_conf,
                max_persons=num_poses,
                device=yolo_device,
                imgsz=yolo_imgsz,
            )
            self._landmarker = None
            print(
                f"[camera] pose_backend=yolo model={yolo_model} "
                f"conf={yolo_conf} device={self._yolo._device} "
                f"max_persons={num_poses}"
            )
        else:
            # ────────── MediaPipe backend (legacy) ──────────
            # Auto-override: VIDEO mode's tracking keeps locking onto the
            # first-seen pose and rarely re-detects to pick up a second
            # or third swimmer entering frame. For any num_poses > 1 we
            # force IMAGE mode so every frame does fresh full-body
            # detection — slower but actually returns N poses.
            if num_poses > 1 and mode_str != "image":
                mode_str = "image"
                self._pose_mode = mode_str
                print(f"[camera] num_poses={num_poses} → forcing IMAGE mode "
                      f"for true multi-person detection")
            running_mode = RunningMode.IMAGE if mode_str == "image" else RunningMode.VIDEO

            options = PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=_MODEL_PATH),
                running_mode=running_mode,
                num_poses=num_poses,
                min_pose_detection_confidence=det_conf,
                min_pose_presence_confidence=pres_conf,
                min_tracking_confidence=trk_conf,
                output_segmentation_masks=False,
            )
            self._landmarker = PoseLandmarker.create_from_options(options)
            self._yolo = None

        no_frame_counter = 0
        print(f"[camera] entering main loop — backend={self._backend}")
        while self._running:
            ret, frame = self._stream.read()
            if not ret:
                no_frame_counter += 1
                if no_frame_counter % 200 == 1:
                    print(f"[camera] no frames from stream (x{no_frame_counter}) — "
                          f"DroidCam might be disconnected")
                time.sleep(0.01)
                continue
            if no_frame_counter > 0:
                print(f"[camera] stream recovered after {no_frame_counter} empty reads")
                no_frame_counter = 0

            # Apply rotation
            if self._rotation == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif self._rotation == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif self._rotation == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)

            h, w = frame.shape[:2]

            # Build landmarks list(s) + angles.
            # `angles` is the primary person's angles (backward compat);
            # `all_angles` parallels `all_landmarks` — one dict per
            # detected person — so the dashboard can show each athlete's
            # numbers separately.
            landmarks_list: list[list[float]] = []
            all_landmarks: list[list[list[float]]] = []
            all_angles: list[dict] = []
            # Stable per-person tracking IDs from BYTETracker (yolo
            # backend only — MediaPipe has no built-in tracker, so
            # those entries stay None and the analysis page falls back
            # to array-order colouring).
            track_ids: list[int | None] = []
            angles: dict[str, float] | None = None

            if self._backend == "yolo" and self._yolo is not None:
                # ── YOLOv8-pose: reliable multi-person. Returns
                # ``(persons, track_ids)`` — both lists are
                # area-sorted (biggest-first) and aligned by index.
                persons, track_ids = self._yolo.detect(frame, w, h)
                if persons:
                    for lm_list in persons:
                        all_landmarks.append(
                            [[l.x, l.y, l.visibility] for l in lm_list]
                        )
                        all_angles.append(_compute_angles(lm_list, w, h))
                    landmarks_list = all_landmarks[0]
                    angles = all_angles[0]
            else:
                # ── MediaPipe backend (pad-to-square work-around for
                # the NORM_RECT multi-person projection bug).
                if h != w:
                    sz = max(h, w)
                    square = np.zeros((sz, sz, 3), dtype=frame.dtype)
                    square[:h, :w] = frame
                    x_scale = sz / w
                    y_scale = sz / h
                    det_frame = square
                else:
                    x_scale = y_scale = 1.0
                    det_frame = frame

                rgb = cv2.cvtColor(det_frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                if self._pose_mode == "image":
                    results = self._landmarker.detect(mp_image)
                else:
                    ts_ms = int(time.time() * 1000)
                    results = self._landmarker.detect_for_video(mp_image, ts_ms)

                if results.pose_landmarks and len(results.pose_landmarks) > 0:
                    class _LM:
                        __slots__ = ("x", "y", "visibility")
                        def __init__(self, x, y, v):
                            self.x = x; self.y = y; self.visibility = v
                    for lm in results.pose_landmarks:
                        adjusted = [
                            [l.x * x_scale, l.y * y_scale, l.visibility]
                            for l in lm
                        ]
                        all_landmarks.append(adjusted)
                        # Compute angles for this person from the
                        # rescaled coords (same coord system the
                        # frontend will render in).
                        adj_objs = [_LM(p[0], p[1], p[2]) for p in adjusted]
                        all_angles.append(_compute_angles(adj_objs, w, h))
                    landmarks_list = all_landmarks[0]
                    angles = all_angles[0]
                    # MediaPipe doesn't track — fill with Nones so the
                    # frame dict stays uniform regardless of backend.
                    track_ids = [None] * len(all_landmarks)

            # Periodic debug log of how many people were detected.
            self._mp_log_counter = getattr(self, "_mp_log_counter", 0) + 1
            if self._mp_log_counter % 60 == 1:   # ~2.5s at 25fps
                print(f"[camera] person_count={len(all_landmarks)} "
                      f"frame={w}x{h} backend={self._backend}")

            # JPEG encode
            ok, jpeg_buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
            )
            if not ok:
                continue

            # Defensive normalisation: track_ids must always be the
            # same length as all_landmarks, otherwise downstream
            # writers can mis-align IDs to bodies (a really nasty
            # silent bug — wrong athlete's IMU pairs to wrong skeleton).
            if len(track_ids) != len(all_landmarks):
                track_ids = [None] * len(all_landmarks)

            result = {
                "jpeg": jpeg_buf.tobytes(),
                "raw_frame": frame,
                "landmarks": landmarks_list,
                "all_landmarks": all_landmarks,
                "all_angles": all_angles,          # per-person angles, parallel to all_landmarks
                "track_ids": track_ids,            # parallel to all_landmarks; None for MP backend / new detections
                "person_count": len(all_landmarks),
                "angles": angles,                  # primary person, backward-compat
            }

            with self._lock:
                self._latest = result
