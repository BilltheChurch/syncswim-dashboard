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

# Swimmer-tuned tracker config — we tried tweaking ByteTrack thresholds
# (data/tracker_configs/swimmer_bytetrack.yaml v3 dogfood) but it made
# inflation WORSE (14× → 26×). Pivoting to BoT-SORT with default thresholds
# + GMC (Global Motion Compensation), which is the only architectural
# difference that should help with handheld-camera bbox jitter.
SWIMMER_TRACKER_YAML = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "tracker_configs", "swimmer_botsort.yaml"
)

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

# Phase B models emit the swimmer-19 skeleton: COCO-17 + foot_index
# L/R (data/training/phase_b/swimmer_pose19.yaml). The two extra
# points map onto MediaPipe's foot_index slots — which is exactly why
# the custom skeleton was designed as a COCO superset: same pipeline
# serves stock 17-kpt weights and fine-tuned 19-kpt weights.
KPT_TO_MP = {**COCO_TO_MP, 17: 31, 18: 32}   # left/right foot_index


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


def _kpts_to_mp33(
    kp_xy, kp_conf, w: int, h: int,
    x_offset: float = 0.0, y_offset: float = 0.0,
) -> list[_Landmark]:
    """Map one person's model keypoints (17 COCO or 19 swimmer-19,
    pixel coords) into the MP-33 layout, normalizing to [0,1].

    ``x_offset``/``y_offset`` shift crop-relative coords back to
    full-frame (HybridSwimmerDetector's crop→pose path); leave 0 for
    full-frame models. Unknown extra keypoints (beyond the mapping)
    are ignored rather than crashing on future skeleton growth.
    """
    mp33 = _empty_mp33()
    for k in range(kp_xy.shape[0]):
        mp_idx = KPT_TO_MP.get(k)
        if mp_idx is None:
            continue
        mp33[mp_idx] = _Landmark(
            x=(x_offset + float(kp_xy[k, 0])) / max(1, w),
            y=(y_offset + float(kp_xy[k, 1])) / max(1, h),
            visibility=float(kp_conf[k]),
        )
    return mp33


def _apply_kpt_gate(mp33: list[_Landmark], min_conf: float) -> list[_Landmark]:
    """Zero out keypoints below ``min_conf`` so hallucinated joints
    never reach the recorder / frontend.

    COCO-pose has no concept of "this joint is underwater" — it always
    emits 17 coordinates, and for occluded joints it invents plausible
    positions at conf ~0.1-0.4 (Emily dogfood 2026-07: knee/ankle conf
    0.007-0.03 with confident-looking xy). Gating at the source keeps
    landmarks.csv / landmarks_multi.jsonl clean, which matters twice:
    the replay overlay stops drawing garbage, and Phase B pre-annotation
    built from these files doesn't inherit fake points.
    """
    if min_conf <= 0:
        return mp33
    for idx, lm in enumerate(mp33):
        if lm.visibility < min_conf and (lm.x or lm.y or lm.visibility):
            mp33[idx] = _Landmark(0.0, 0.0, 0.0)
    return mp33


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
        imgsz: int = 640,
        kpt_min_conf: float = 0.35,
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
        # Inference resolution. Default 640 matches ultralytics' default.
        # Bumping to 1280 helps small / partial-body targets (e.g. swimmers
        # whose only visible features are ankles/feet at ~40px in a 720p
        # frame): under 640 those features get downsampled to single-digit
        # pixels and the detector misses them entirely. Cost: ~4× wall-time.
        self._imgsz = int(imgsz)
        self._kpt_min_conf = float(kpt_min_conf)

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
                imgsz=self._imgsz,
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

        # kp_xy shape: (N_persons, K, 2) pixel coords — K is 17 for
        # stock COCO weights, 19 for Phase B swimmer weights.
        # kp_cnf shape: (N_persons, K) confidence per keypoint.
        kp_xy = result.keypoints.xy.cpu().numpy()
        kp_conf = (
            result.keypoints.conf.cpu().numpy()
            if result.keypoints.conf is not None
            else np.ones(kp_xy.shape[:2], dtype=np.float32)
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
            mp33 = _kpts_to_mp33(kp_xy[i], kp_conf[i], w, h)
            persons.append(_apply_kpt_gate(mp33, self._kpt_min_conf))
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


class HybridSwimmerDetector:
    """Phase A intermediate: custom-trained DETECTOR + COCO pose KEYPOINTS.

    Why this exists (DEVLOG #33 + #34):
      - COCO YOLO has ~7% recall on water-pose targets — the root
        cause of the 19.8× ID inflation we saw in dogfood.
      - Phase A trains a dedicated YOLOv8s detector on ~150 annotated
        swim frames. mAP@50 ≥ 0.70 is the success criterion (see
        docs/phase-a-annotation.md).
      - But a detector-only model has no keypoint head. So we run two
        models: the custom detector for bboxes (high recall →
        stable BYTETracker IDs), and the original yolov8s-pose.pt
        for keypoints (still COCO-trained — Phase B will fine-tune
        the keypoint head).

    Wiring: same return signature as ``YoloPoseDetector.detect()`` so
    the rest of the pipeline (camera_manager, recorder, frontend)
    doesn't notice the swap. Activated by setting
    ``swimmer_detector`` in config.toml ``[hardware]``.

    Cost: ~6× wall-time vs single-model YoloPoseDetector (one
    detector pass + N pose passes on cropped persons). Only enable
    for offline import; keep single-model for live recording.
    """

    def __init__(
        self,
        swimmer_detector_path: str,
        pose_model_path: str = "yolov8s-pose.pt",
        conf: float = 0.35,
        iou: float = 0.45,
        max_persons: int = 8,
        device: str = "mps",
        imgsz: int = 1280,
        kpt_min_conf: float = 0.35,
    ):
        from ultralytics import YOLO

        if not os.path.exists(swimmer_detector_path):
            raise FileNotFoundError(
                f"Custom swimmer detector not found at "
                f"{swimmer_detector_path}. Train one with:\n"
                f"  python tools/train_detector.py\n"
                f"(see docs/phase-a-annotation.md)"
            )
        if not os.path.exists(pose_model_path):
            raise FileNotFoundError(
                f"Pose model not found at {pose_model_path}. Download with:\n"
                f"  curl -L -o {pose_model_path} "
                f"https://github.com/ultralytics/assets/releases/download/"
                f"v8.3.0/yolov8s-pose.pt"
            )

        self._det_model = YOLO(swimmer_detector_path)   # custom bbox
        self._pose_model = YOLO(pose_model_path)         # COCO keypoints
        # The swimmer-tuned tracker yaml lives in data/ and can be
        # missing on a fresh deploy (kit built before the file was
        # committed). ultralytics .track() with a nonexistent tracker
        # path raises → detect() would return zero persons EVERY frame
        # with no visible error. Fall back to the bundled BoT-SORT
        # defaults instead, loudly.
        if os.path.exists(SWIMMER_TRACKER_YAML):
            self._tracker_yaml = SWIMMER_TRACKER_YAML
        else:
            print(f"[hybrid] WARNING: {SWIMMER_TRACKER_YAML} missing — "
                  f"falling back to bundled botsort.yaml")
            self._tracker_yaml = "botsort.yaml"
        self._conf = float(conf)
        self._iou = float(iou)
        self._max_persons = max(1, int(max_persons))
        self._device = device
        self._imgsz = int(imgsz)
        self._kpt_min_conf = float(kpt_min_conf)

        # Warm-up BOTH models so first real frame isn't stuck behind JIT.
        dummy = np.zeros((320, 320, 3), dtype=np.uint8)
        try:
            self._det_model.predict(
                dummy, verbose=False, conf=self._conf, iou=self._iou,
                device=self._device, max_det=self._max_persons,
            )
            self._pose_model.predict(
                dummy, verbose=False, conf=0.1, max_det=1,
                device=self._device,
            )
        except Exception:
            self._device = "cpu"
            self._det_model.predict(
                dummy, verbose=False, conf=self._conf, iou=self._iou,
                device="cpu", max_det=self._max_persons,
            )
            self._pose_model.predict(
                dummy, verbose=False, conf=0.1, max_det=1, device="cpu",
            )

    def detect(self, frame_bgr: np.ndarray, w: int, h: int):
        """Two-stage detection. See class docstring for rationale.

        1. Custom detector .track() → bboxes + BYTETracker IDs (stable
           because detector now has high recall).
        2. For each tracked bbox: crop → COCO pose model .predict()
           (max_det=1, only the swimmer in this crop) → 17 keypoints.
        3. Map crop-relative keypoints back to full-frame and emit
           an MP-33 landmark list, matching ``YoloPoseDetector.detect``
           output shape.
        """
        try:
            det_out = self._det_model.track(
                frame_bgr,
                verbose=False,
                conf=self._conf,
                iou=self._iou,
                device=self._device,
                max_det=self._max_persons,
                imgsz=self._imgsz,
                persist=True,
                tracker=self._tracker_yaml,  # see module-level docstring
            )
        except Exception:
            return [], []

        if not det_out or det_out[0].boxes is None:
            return [], []
        result = det_out[0]
        boxes_xyxy = result.boxes.xyxy.cpu().numpy()
        n = boxes_xyxy.shape[0]
        if n == 0:
            return [], []

        # Track IDs (None for brand-new detections the tracker hasn't
        # matched yet on this frame).
        track_ids: list[int | None] = [None] * n
        if getattr(result.boxes, "id", None) is not None:
            ids_np = result.boxes.id.cpu().numpy().astype(int)
            if len(ids_np) == n:
                track_ids = [int(x) for x in ids_np]

        persons: list[list[_Landmark]] = []
        for i in range(n):
            x1, y1, x2, y2 = boxes_xyxy[i]
            # Expand the bbox 1.5× around its center before cropping.
            # Phase B training crops are bbox-centered with the subject
            # filling ~2/3 of the crop (tools/build_emily_phase_b_kit.py)
            # — feeding the pose model a TIGHT crop is out of its
            # training distribution and drops keypoint confidence below
            # the draw/record gates (DEVLOG #38: inverted-swimmer frames
            # that worked on val crops failed on tight inference crops).
            bw, bh = x2 - x1, y2 - y1
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            x1, x2 = cx - bw * 0.75, cx + bw * 0.75
            y1, y2 = cy - bh * 0.75, cy + bh * 0.75
            x1i, y1i = max(0, int(x1)), max(0, int(y1))
            x2i, y2i = min(w, int(x2)), min(h, int(y2))
            if x2i <= x1i or y2i <= y1i:
                # Degenerate box — emit empty pose so indices align
                # with track_ids and the bbox is still represented.
                persons.append(_empty_mp33())
                continue

            crop = frame_bgr[y1i:y2i, x1i:x2i]
            mp33 = _empty_mp33()
            try:
                pose_out = self._pose_model.predict(
                    crop,
                    verbose=False,
                    conf=0.1,
                    max_det=1,
                    device=self._device,
                )
            except Exception:
                pose_out = None

            if (
                pose_out
                and pose_out[0].keypoints is not None
                and pose_out[0].keypoints.xy is not None
                and len(pose_out[0].keypoints.xy) > 0
            ):
                # (K, 2) — K = 17 (stock COCO) or 19 (Phase B weights)
                kp_xy = pose_out[0].keypoints.xy[0].cpu().numpy()
                kp_conf = (
                    pose_out[0].keypoints.conf[0].cpu().numpy()
                    if pose_out[0].keypoints.conf is not None
                    else np.ones(kp_xy.shape[0], dtype=np.float32)
                )
                # Crop-relative px → full-frame px → normalize
                mp33 = _kpts_to_mp33(
                    kp_xy, kp_conf, w, h, x_offset=x1i, y_offset=y1i,
                )
            persons.append(_apply_kpt_gate(mp33, self._kpt_min_conf))

        # Sort by bbox area (biggest first) to match
        # YoloPoseDetector.detect() semantics — index 0 is the most
        # prominent athlete.
        if n > 1:
            areas = (boxes_xyxy[:, 2] - boxes_xyxy[:, 0]) * (
                boxes_xyxy[:, 3] - boxes_xyxy[:, 1]
            )
            order = np.argsort(-areas)
            persons = [persons[i] for i in order]
            track_ids = [track_ids[i] for i in order]

        return persons, track_ids

    def reset_tracking(self) -> None:
        """Reset BYTETracker on the DETECTOR model. The pose model
        runs in predict-only mode (no tracking) so it has no state.
        """
        try:
            predictor = getattr(self._det_model, "predictor", None)
            if predictor is None:
                return
            trackers = getattr(predictor, "trackers", None) or []
            for trk in trackers:
                if hasattr(trk, "reset"):
                    trk.reset()
        except Exception as e:
            print(f"[hybrid] tracker reset failed: {e}")


def create_pose_detector(
    *,
    swimmer_detector_path: str | None,
    pose_model_path: str,
    conf: float,
    max_persons: int,
    device: str,
    imgsz: int = 640,
    kpt_min_conf: float = 0.35,
):
    """Factory: pick HybridSwimmerDetector if a custom detector is
    configured, otherwise fall back to the single-model YoloPoseDetector.

    Used by camera_manager.py and tools/import_video.py so the choice
    is config-driven (config.toml ``[hardware] swimmer_detector``)
    instead of hard-coded at each instantiation site.
    """
    if swimmer_detector_path and os.path.exists(swimmer_detector_path):
        print(
            f"[pose] hybrid mode: detector={swimmer_detector_path} "
            f"+ pose={pose_model_path}"
        )
        return HybridSwimmerDetector(
            swimmer_detector_path=swimmer_detector_path,
            pose_model_path=pose_model_path,
            conf=conf,
            max_persons=max_persons,
            device=device,
            imgsz=imgsz,
            kpt_min_conf=kpt_min_conf,
        )
    return YoloPoseDetector(
        model_path=pose_model_path,
        conf=conf,
        max_persons=max_persons,
        device=device,
        imgsz=imgsz,
        kpt_min_conf=kpt_min_conf,
    )
