"""YOLOv8-pose backend for multi-person pose estimation.

Used as a drop-in replacement for MediaPipe Pose Landmarker when the
config says ``pose_backend = "yolo"``. YOLOv8-pose handles 2-10
people in frame reliably — MediaPipe 0.10's multi-pose support is
known to be unstable (see DEVLOG).

Output format is adapted to match MediaPipe's 33-point layout so the
rest of the pipeline (angle calc, visibility gate, CSV writer, UI) is
unchanged. COCO-17 points from YOLO fill the MP slots we actually
use (shoulders, elbows, wrists, hips, knees, ankles, nose, eyes,
ears); slots we don't use (mouth, pinky, thumb, heel, foot_index)
get visibility 0 and are transparently skipped downstream.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

# COCO-17 index → MediaPipe-33 index. Every COCO keypoint maps to an
# MP keypoint with the same semantic meaning.
#   COCO indexing:  nose=0, L/R eye=1/2, L/R ear=3/4, L/R shoulder=5/6,
#                   L/R elbow=7/8, L/R wrist=9/10, L/R hip=11/12,
#                   L/R knee=13/14, L/R ankle=15/16
#   MP-33 indexing: see the LANDMARK_NAMES list in api_routes.py.
COCO_TO_MP = {
    0:  0,   # nose
    1:  2,   # left_eye
    2:  5,   # right_eye
    3:  7,   # left_ear
    4:  8,   # right_ear
    5:  11,  # left_shoulder
    6:  12,  # right_shoulder
    7:  13,  # left_elbow
    8:  14,  # right_elbow
    9:  15,  # left_wrist
    10: 16,  # right_wrist
    11: 23,  # left_hip
    12: 24,  # right_hip
    13: 25,  # left_knee
    14: 26,  # right_knee
    15: 27,  # left_ankle
    16: 28,  # right_ankle
}


@dataclass
class _Landmark:
    """Minimal landmark with the same attributes as MediaPipe's
    NormalizedLandmark, so _compute_angles(...) works unchanged.
    """
    x: float
    y: float
    visibility: float


def _empty_mp33() -> list[_Landmark]:
    return [_Landmark(0.0, 0.0, 0.0) for _ in range(33)]


class YoloPoseDetector:
    """Wraps Ultralytics YOLOv8-pose into a MediaPipe-compatible API.

    Typical use::
        det = YoloPoseDetector(model_path="yolov8n-pose.pt", conf=0.35)
        persons = det.detect(frame_bgr, w, h)
        # persons: list[list[_Landmark]]  — each inner list has 33 entries
    """

    def __init__(
        self,
        model_path: str = "yolov8n-pose.pt",
        conf: float = 0.35,
        iou: float = 0.45,
        max_persons: int = 8,
        device: str = "mps",
    ):
        from ultralytics import YOLO

        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"YOLO pose model not found at {model_path}. Download with:\n"
                f"  curl -L -o {model_path} "
                f"https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n-pose.pt"
            )

        # mps = Apple Metal; cuda for NVIDIA; cpu fallback. Ultralytics
        # auto-falls-back to cpu if the chosen device isn't available.
        self._model = YOLO(model_path)
        self._conf = float(conf)
        self._iou = float(iou)
        self._max_persons = max(1, int(max_persons))
        self._device = device

        # Warm-up: run once on a tiny dummy frame so the first real
        # inference isn't stuck behind model compile / JIT / kernel cache.
        dummy = np.zeros((320, 320, 3), dtype=np.uint8)
        try:
            self._model.predict(
                dummy, verbose=False, conf=self._conf, iou=self._iou,
                device=self._device, max_det=self._max_persons,
            )
        except Exception:
            # If mps unavailable etc., retry on cpu
            self._device = "cpu"
            self._model.predict(
                dummy, verbose=False, conf=self._conf, iou=self._iou,
                device="cpu", max_det=self._max_persons,
            )

    def detect(self, frame_bgr: np.ndarray, w: int, h: int):
        """Detect + track up to ``max_persons`` poses in the BGR frame.

        Returns ``(persons, track_ids)`` where:
          * ``persons`` is a list of lists-of-33-_Landmark, sorted by
            bounding-box area (biggest-first).
          * ``track_ids`` is a list of the same length, with each entry
            either an ``int`` (stable BYTETracker ID across frames) or
            ``None`` if the tracker has not yet assigned an ID this
            frame (e.g. brand-new detection on the very first frame).

        Uses ``model.track(persist=True)`` with the bundled
        ``bytetrack.yaml`` config so the same swimmer keeps the same
        ID frame-to-frame — required for cross-Set comparison and for
        the analysis page to bind a per-athlete colour without losing
        identity when someone briefly leaves the frame.
        """
        try:
            out = self._model.track(
                frame_bgr,
                verbose=False,
                conf=self._conf,
                iou=self._iou,
                device=self._device,
                max_det=self._max_persons,
                persist=True,
                tracker="bytetrack.yaml",
            )
        except Exception:
            return [], []

        if not out:
            return [], []
        result = out[0]
        if result.keypoints is None or result.keypoints.xy is None:
            return [], []

        # kp_xy shape: (N_persons, 17, 2)   pixel coords
        # kp_cnf shape: (N_persons, 17)     confidence per keypoint
        kp_xy = result.keypoints.xy.cpu().numpy()
        kp_conf = (
            result.keypoints.conf.cpu().numpy()
            if result.keypoints.conf is not None
            else np.ones((kp_xy.shape[0], 17), dtype=np.float32)
        )
        if kp_xy.shape[0] == 0:
            return [], []

        # BYTETracker IDs (same length as persons; None when the tracker
        # hasn't matched a brand-new detection yet).
        track_ids: list[int | None] = [None] * kp_xy.shape[0]
        if (
            result.boxes is not None
            and getattr(result.boxes, "id", None) is not None
        ):
            ids_np = result.boxes.id.cpu().numpy().astype(int)
            if len(ids_np) == kp_xy.shape[0]:
                track_ids = [int(x) for x in ids_np]

        # Sort persons by bounding-box area (biggest first) so index 0
        # is the most prominent athlete — matches the previous
        # "primary person" semantics. Reorder track_ids in lock-step.
        if result.boxes is not None and len(result.boxes) == kp_xy.shape[0]:
            areas = []
            for b in result.boxes.xyxy.cpu().numpy():
                areas.append((b[2] - b[0]) * (b[3] - b[1]))
            order = np.argsort(-np.array(areas))
            kp_xy = kp_xy[order]
            kp_conf = kp_conf[order]
            track_ids = [track_ids[i] for i in order]

        persons: list[list[_Landmark]] = []
        for i in range(kp_xy.shape[0]):
            mp33 = _empty_mp33()
            for coco_idx in range(17):
                x_px = float(kp_xy[i, coco_idx, 0])
                y_px = float(kp_xy[i, coco_idx, 1])
                c = float(kp_conf[i, coco_idx])
                mp_idx = COCO_TO_MP[coco_idx]
                # Normalize to [0,1] so downstream code treats it the
                # same way as MediaPipe's NormalizedLandmark.
                mp33[mp_idx] = _Landmark(
                    x=x_px / max(1, w),
                    y=y_px / max(1, h),
                    visibility=c,
                )
            persons.append(mp33)
        return persons, track_ids

    def reset_tracking(self) -> None:
        """Reset BYTETracker state so the next ``detect()`` starts IDs
        from 1 again.

        Called at recording start so IDs don't leak across Sets — if
        last Set ended with #5, this Set's primary swimmer would
        otherwise be #6 (confusing for the coach and breaks the "ID
        is stable WITHIN one Set" assumption that 7.2 athlete-binding
        depends on).
        """
        try:
            predictor = getattr(self._model, "predictor", None)
            if predictor is None:
                return
            trackers = getattr(predictor, "trackers", None) or []
            for trk in trackers:
                if hasattr(trk, "reset"):
                    trk.reset()
        except Exception as e:
            print(f"[yolo_pose] tracker reset failed: {e}")
