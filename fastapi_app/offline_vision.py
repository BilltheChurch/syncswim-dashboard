"""Offline (post-recording) vision analysis — DEVLOG #37 architecture pivot.

2026-07-30 role change: the live path no longer runs ANY pose inference
(pose_backend = "none"); the live page shows camera + IMU only. All
vision work happens here, after recording ends, where we can afford the
heavy configuration — hybrid swimmer detector + COCO pose at imgsz 1280,
unbounded wall-time — instead of whatever fits in a real-time budget.

``analyze_set()`` re-reads a set's video.mp4, runs the detector on every
frame and atomically REWRITES the set's three vision files:

    vision.csv              — primary person elbow angle, 1:1 with frames
    landmarks.csv           — 33 keypoints per frame, 1:1 with frames
    landmarks_multi.jsonl   — all persons + tracker IDs per frame

Timestamps are the alignment anchor with the IMU CSVs: for live-recorded
sets we REUSE the wall-clock timestamps the recorder wrote at capture
time (vision.csv is 1:1 with video frames — DEVLOG #13), so IMU↔vision
sync survives re-analysis. Imported/legacy sets without usable
timestamps fall back to synthetic ``first_ts + i/fps``.

A tiny in-process job registry lets the dashboard kick analysis in a
background thread and poll progress (`/api/sets/{name}/analyze`).
"""

from __future__ import annotations

import csv
import json
import os
import threading
import time

import cv2

from dashboard.config import load_config
from fastapi_app.camera_manager import _compute_angles
from fastapi_app.recorder import LANDMARK_NAMES, VISION_HEADER

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

def resolve_analysis_config() -> dict:
    """Effective offline-analysis settings.

    Reads the optional ``[analysis]`` section of config.toml, falling
    back to ``[hardware]`` values where sharing makes sense. Defaults
    follow the dogfood-tuned offline profile (DEVLOG #33): conf 0.15,
    imgsz 1280 — quality over speed, this is not a real-time path.
    """
    cfg = load_config()
    hw = cfg.get("hardware", {})
    an = cfg.get("analysis", {})

    def _res(path: str | None) -> str | None:
        if not path:
            return None
        return path if os.path.isabs(path) else os.path.join(_PROJECT_ROOT, path)

    model = an.get("model", hw.get("yolo_model", "yolov8s-pose.pt"))
    sd = an.get("swimmer_detector", hw.get("swimmer_detector"))
    # Smart conf default (validated on Emily set_013, 2026-07-30):
    # - single-model COCO pose: 0.15 — water poses inherently score low
    #   (DEVLOG #33), higher thresholds throw away real swimmers.
    # - hybrid (custom swimmer detector): 0.35 — the fine-tuned detector
    #   IS confident on swimmers; 0.15 admits lane buoys/reflections as
    #   false-positive tracks (27 IDs vs 21 for one swimmer) while only
    #   adding 2.4pp detection (98.0% → 95.6%).
    sd_path = _res(sd)
    default_conf = 0.35 if sd_path and os.path.exists(sd_path) else 0.15
    return {
        "model_path": _res(model) or model,
        "swimmer_detector_path": sd_path,
        "conf": float(an.get("conf", default_conf)),
        "imgsz": int(an.get("imgsz", 1280)),
        "device": str(an.get("device", hw.get("yolo_device", "mps"))),
        "kpt_min_conf": float(an.get("kpt_min_conf",
                                     hw.get("kpt_min_conf", 0.35))),
        "max_persons": int(an.get("max_persons", hw.get("num_poses", 8))),
    }


def _build_detector(cfg: dict):
    """Instantiate the pose detector (separate fn so tests can stub)."""
    from fastapi_app.yolo_pose import create_pose_detector
    return create_pose_detector(
        swimmer_detector_path=cfg.get("swimmer_detector_path"),
        pose_model_path=cfg["model_path"],
        conf=cfg["conf"],
        max_persons=cfg["max_persons"],
        device=cfg["device"],
        imgsz=cfg["imgsz"],
        kpt_min_conf=cfg["kpt_min_conf"],
    )


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _landmark_csv_header() -> list[str]:
    h = ["timestamp_local", "frame"]
    for name in LANDMARK_NAMES:
        h.extend([f"{name}_x", f"{name}_y", f"{name}_z", f"{name}_vis"])
    return h


def _load_existing_timestamps(set_dir: str) -> list[float]:
    """Wall-clock timestamps the live recorder captured, one per video
    frame (vision.csv is 1:1 with video.mp4 — DEVLOG #13). These are
    the IMU-alignment anchor and MUST survive re-analysis."""
    path = os.path.join(set_dir, "vision.csv")
    if not os.path.exists(path):
        return []
    out: list[float] = []
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    out.append(float(row["timestamp_local"]))
                except (TypeError, ValueError, KeyError):
                    # Torn final row (recorder flushes every ~30 rows;
                    # a crash mid-recording can truncate the last line).
                    # Keep the good prefix — timestamps are per-frame
                    # prefix-aligned, so partial reuse is still correct.
                    break
    except Exception:
        return []
    return out


def analyze_set(
    set_dir: str,
    *,
    detector=None,
    cfg: dict | None = None,
    progress_cb=None,
) -> dict:
    """Run offline vision analysis over ``set_dir/video.mp4`` and
    atomically rewrite vision.csv / landmarks.csv / landmarks_multi.jsonl.

    ``detector``: pre-built detector (tests / reuse); built from ``cfg``
    when None. ``progress_cb(done, total)``: optional progress hook.

    Returns a summary dict (frames, detection %, unique track IDs...).
    Raises on unrecoverable errors (missing video, unreadable stream);
    the original files are left untouched in that case (tmp + replace).
    """
    video_path = os.path.join(set_dir, "video.mp4")
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"video.mp4 not found in {set_dir}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if detector is None:
        cfg = cfg or resolve_analysis_config()
        detector = _build_detector(cfg)
    # Fresh tracker state per set — IDs must not leak across analyses
    # (same contract as live recording start, DEVLOG #25).
    if hasattr(detector, "reset_tracking"):
        detector.reset_tracking()

    # Timestamp strategy: reuse the recorder's wall-clock stamps when
    # they line up 1:1 with the video; otherwise synthesize from the
    # first known stamp (keeps IMU alignment plausible for legacy sets
    # whose row count drifted) or from zero for imported videos.
    recorded_ts = _load_existing_timestamps(set_dir)
    base_ts = recorded_ts[0] if recorded_ts else 0.0
    if recorded_ts and abs(len(recorded_ts) - total) > max(5, total * 0.02):
        # Row count drifted too far from the video — per-index reuse
        # would attribute wrong wall-clock times to frames. Synthesize
        # the whole timeline from the first known stamp instead.
        print(f"[offline_vision] WARNING: vision.csv rows ({len(recorded_ts)}) "
              f"!= video frames ({total}) — synthesizing timestamps "
              f"from {base_ts:.3f}")
        recorded_ts = []

    def ts_for(i: int) -> float:
        if i < len(recorded_ts):
            return recorded_ts[i]
        return base_ts + i / max(1.0, fps)

    vis_tmp = os.path.join(set_dir, "vision.csv.tmp")
    lm_tmp = os.path.join(set_dir, "landmarks.csv.tmp")
    multi_tmp = os.path.join(set_dir, "landmarks_multi.jsonl.tmp")

    seen_ids: set[int] = set()
    frames_with_detection = 0
    persons_total = 0
    frame_idx = 0

    try:
        with open(vis_tmp, "w", newline="") as vf, \
             open(lm_tmp, "w", newline="") as lf, \
             open(multi_tmp, "w") as mf:
            vw = csv.writer(vf)
            vw.writerow(VISION_HEADER)
            lw = csv.writer(lf)
            lw.writerow(_landmark_csv_header())

            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                h, w = frame.shape[:2]
                persons, track_ids = detector.detect(frame, w, h)
                local_ts = ts_for(frame_idx)
                frame_no = frame_idx + 1

                primary = persons[0] if persons else []
                if primary:
                    angles = _compute_angles(primary, w, h)
                    elbow = float(angles.get("elbow", 0.0))
                    visible = "elbow" in angles
                else:
                    elbow, visible = 0.0, False
                vw.writerow([
                    f"{local_ts:.6f}", frame_no, "R_Elbow",
                    f"{elbow:.2f}", 1 if visible else 0, f"{fps:.1f}",
                ])

                lm_row: list = [f"{local_ts:.6f}", frame_no]
                if primary:
                    for lm in primary:
                        lm_row.extend([f"{lm.x:.6f}", f"{lm.y:.6f}",
                                       "0.0", f"{lm.visibility:.4f}"])
                else:
                    lm_row.extend([0.0] * (33 * 4))
                lw.writerow(lm_row)

                payload, kept = [], []
                for oi, lm_list in enumerate(persons):
                    if not lm_list or len(lm_list) != 33:
                        continue
                    payload.append([[round(lm.x, 4), round(lm.y, 4),
                                     round(lm.visibility, 3)]
                                    for lm in lm_list])
                    kept.append(oi)
                ids = [(int(track_ids[i]) if (i < len(track_ids)
                                              and track_ids[i] is not None)
                        else None) for i in kept]
                mf.write(json.dumps({
                    "ts": round(local_ts, 3),
                    "frame": frame_no,
                    "persons": payload,
                    "ids": ids,
                }, separators=(",", ":")) + "\n")

                persons_total += len(payload)
                if any(t is not None for t in ids):
                    frames_with_detection += 1
                    seen_ids.update(t for t in ids if t is not None)
                elif payload:
                    frames_with_detection += 1

                frame_idx += 1
                if progress_cb and (frame_idx % 10 == 0 or frame_idx == total):
                    progress_cb(frame_idx, max(total, frame_idx))
        # cv2 reports decode failures as a plain EOF (`ok == False`) —
        # a corrupt/truncated video would otherwise "succeed" short and
        # overwrite good data (for Emily's legacy sets these files are
        # the ONLY copy of the recorded landmarks). Refuse to commit
        # when the decode falls short of the container's declared frame
        # count beyond the same drift tolerance used for timestamps;
        # decoding MORE than declared is fine (some containers
        # under-report).
        if frame_idx == 0:
            raise RuntimeError(
                f"no frames decoded from {video_path} "
                f"(container declares {total}) — refusing to overwrite "
                f"existing analysis files"
            )
        if total > 0 and (total - frame_idx) > max(5, total * 0.02):
            raise RuntimeError(
                f"decoded only {frame_idx}/{total} frames — video tail "
                f"corrupt? refusing to overwrite existing analysis files"
            )

        # Atomic swap-in: readers (analysis page endpoints) either see
        # the complete old files or the complete new ones, never a torn
        # state. Kept inside the cleanup scope so a failed replace still
        # removes leftover tmp files.
        os.replace(vis_tmp, os.path.join(set_dir, "vision.csv"))
        os.replace(lm_tmp, os.path.join(set_dir, "landmarks.csv"))
        os.replace(multi_tmp, os.path.join(set_dir, "landmarks_multi.jsonl"))
    except BaseException:
        # Leave the set as untouched as possible — remove partial tmp
        # files (replaces that already happened cannot be undone, but
        # each replaced file is individually complete).
        for p in (vis_tmp, lm_tmp, multi_tmp):
            try:
                os.remove(p)
            except OSError:
                pass
        raise
    finally:
        cap.release()

    return {
        "frames": frame_idx,
        "frames_with_detection": frames_with_detection,
        "detection_pct": round(100.0 * frames_with_detection
                               / max(1, frame_idx), 1),
        "persons_total": persons_total,
        "unique_track_ids": len(seen_ids),
        "timestamps_reused": bool(recorded_ts),
    }


# ---------------------------------------------------------------------------
# Background job registry (one analysis at a time per process)
# ---------------------------------------------------------------------------

_jobs_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def job_status(set_name: str) -> dict:
    with _jobs_lock:
        st = _jobs.get(set_name)
        return dict(st) if st else {"state": "idle"}


def any_job_running() -> str | None:
    """Name of the set currently being analyzed, if any. The heavy
    models saturate the CPU — one analysis at a time keeps the
    dashboard (and a possibly-active recording) responsive."""
    with _jobs_lock:
        for name, st in _jobs.items():
            if st.get("state") == "running":
                return name
    return None


def start_job(set_name: str, set_dir: str, on_done=None) -> tuple[bool, str]:
    """Kick a background analysis. Returns (started, reason).

    ``on_done()`` (optional) fires after the job leaves the running
    state — success OR failure. Used by the API layer to invalidate
    the sessions index at the moment the on-disk files actually
    changed (clearing it at start would let a mid-run rebuild go
    permanently stale).
    """
    with _jobs_lock:
        running = [n for n, s in _jobs.items() if s.get("state") == "running"]
        if running:
            return False, f"analysis already running for {running[0]}"
        _jobs[set_name] = {
            "state": "running", "progress": 0,
            "frames_done": 0, "frames_total": 0,
            "started_at": time.time(), "error": None, "summary": None,
        }

    def _progress(done: int, total: int):
        with _jobs_lock:
            st = _jobs.get(set_name)
            if st is not None:
                st["frames_done"] = done
                st["frames_total"] = total
                st["progress"] = int(100 * done / max(1, total))

    def _run():
        try:
            summary = analyze_set(set_dir, progress_cb=_progress)
            with _jobs_lock:
                _jobs[set_name].update(
                    state="done", progress=100, summary=summary,
                    finished_at=time.time(),
                )
        except Exception as e:
            print(f"[offline_vision] analysis of {set_name} FAILED: {e!r}")
            with _jobs_lock:
                _jobs[set_name].update(
                    state="error", error=f"{type(e).__name__}: {e}",
                    finished_at=time.time(),
                )
        if on_done is not None:
            try:
                on_done()
            except Exception as e:
                print(f"[offline_vision] on_done hook failed: {e!r}")

    threading.Thread(target=_run, daemon=True,
                     name=f"analyze-{set_name}").start()
    return True, "started"
