"""REST API routes for Coach Workstation.

Endpoints:
  Recording:   POST /api/recording/start | stop
  Sets:        GET  /api/sets
               GET  /api/sets/{name}/report
               DEL  /api/sets/{name}
               GET  /api/sets/{name}/timeseries
               GET  /api/sets/{name}/frame/{time_sec}
               GET  /api/sets/{name}/keyframes/{index}   (back-compat 3 positions)
               GET  /api/sets/{name}/video               (Range-aware)
  Camera:      POST /api/camera/config
               POST /api/camera/test
               GET  /api/camera/snapshot
  BLE:         GET  /api/ble/status
               POST /api/ble/reconnect
  Config:      GET  /api/config
               POST /api/config
  Misc:        GET  /api/health
               GET  /api/data/stats
"""
import json
import os
import shutil
import urllib.request
from typing import Optional

import cv2
import numpy as np
import pandas as pd
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from dashboard.config import load_config, save_config
from dashboard.core.analysis import calc_imu_tilt
from dashboard.core.data_loader import load_all_imus, load_or_rebuild_index, load_vision
from dashboard.core.landmarks import load_landmarks_csv
from dashboard.core.metrics import compute_all_metrics
from dashboard.core.vision_angles import (
    calc_knee_extension,
    calc_leg_deviation_vision,
    calc_leg_symmetry,
    calc_shoulder_knee_angle,
    calc_trunk_vertical,
)

from .athlete_store import AthleteStore

router = APIRouter(prefix="/api")

# Module-level references, set by init()
_ble = None
_camera = None
_recorder = None
_set_manual_recording = None
_athletes: AthleteStore | None = None

_DATA_DIR = "data"

LANDMARK_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26),
    (25, 27), (26, 28),
]

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

SKELETON_COLOR_BGR = (246, 130, 59)  # matches frontend primary blue


def init(ble_manager, camera_manager, recorder, set_manual_recording=None):
    global _ble, _camera, _recorder, _set_manual_recording, _DATA_DIR, _athletes
    _ble = ble_manager
    _camera = camera_manager
    _recorder = recorder
    _set_manual_recording = set_manual_recording
    _DATA_DIR = getattr(recorder, "_data_dir", "data")
    # Athlete bindings live next to the Set directories so the data
    # folder is self-contained — easy to back up or move as a unit.
    _athletes = AthleteStore(os.path.join(_DATA_DIR, "athletes.json"))


# ── Helpers ────────────────────────────────────────────────────

def _set_dir(name: str) -> str:
    return os.path.join(_DATA_DIR, name)


def _clear_sessions_cache() -> None:
    try:
        os.remove(os.path.join(_DATA_DIR, "sessions.json"))
    except OSError:
        pass


def _visibility_stats(set_dir: str) -> dict:
    """Aggregate per-joint-group visibility across the recorded landmarks.

    Lets the dashboard honestly show the coach *why* a metric is no_data
    ("下半身 2% 可见" rather than just "无数据"). Values are 0-100 (%).
    """
    lm_path = os.path.join(set_dir, "landmarks.csv")
    if not os.path.exists(lm_path):
        return {"available": False}
    try:
        df = pd.read_csv(lm_path)
    except Exception:
        return {"available": False}
    if len(df) == 0:
        return {"available": False}

    groups = {
        "face":    ["nose", "left_eye", "right_eye", "left_ear", "right_ear"],
        "upper":   ["left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
                    "left_wrist", "right_wrist"],
        "trunk":   ["left_hip", "right_hip"],
        "lower":   ["left_knee", "right_knee", "left_ankle", "right_ankle"],
    }
    group_pct = {}
    for gname, joints in groups.items():
        cols = [f"{j}_vis" for j in joints if f"{j}_vis" in df.columns]
        if not cols:
            group_pct[gname] = None
            continue
        vals = df[cols].astype(float).values
        # "frame-level visible" = avg vis of joints in this group ≥ 0.5
        per_frame_avg = np.nanmean(vals, axis=1)
        group_pct[gname] = round(float((per_frame_avg >= 0.5).mean()) * 100, 1)

    # Per-joint average visibility across the whole set
    per_joint: dict[str, float] = {}
    for name in LANDMARK_NAMES:
        col = f"{name}_vis"
        if col in df.columns:
            per_joint[name] = round(float(df[col].astype(float).mean()), 3)

    return {
        "available": True,
        "frames": int(len(df)),
        "groups": group_pct,          # {face: 99.2, upper: 95.1, trunk: 2.3, lower: 0.0}
        "joints": per_joint,          # full 33-point mean vis
    }


def _imu_summary(set_dir: str) -> dict:
    summary: dict = {}
    for node, df in load_all_imus(set_dir).items():
        if df.empty:
            continue
        try:
            packets = int(len(df))
            ts_local = df["timestamp_local"].values.astype(float)
            duration = float(ts_local[-1] - ts_local[0]) if len(ts_local) > 1 else 0.0
            rate = packets / duration if duration > 0 else 0.0
            tilt = calc_imu_tilt(df[["ax", "ay", "az"]].to_dict("records"))
            tilt_mean = float(np.mean(tilt))
            tilt_std = float(np.std(tilt))
            # packet-loss estimate: gaps > 3x median interval in device timestamp
            dev_ts = df["timestamp_device"].values.astype(float)
            intervals = np.diff(dev_ts) if len(dev_ts) > 1 else np.array([])
            med = float(np.median(intervals)) if len(intervals) else 0.0
            lost = 0
            if med > 0:
                big = intervals[intervals > med * 3]
                if len(big):
                    lost = int(np.sum(np.round(big / med) - 1))
            summary[node] = {
                "packets": packets,
                "rate": round(rate, 1),
                "duration": round(duration, 2),
                "tilt_mean": round(tilt_mean, 2),
                "tilt_std": round(tilt_std, 2),
                "lost": lost,
                "loss_pct": round(100.0 * lost / max(packets + lost, 1), 2),
            }
        except Exception:
            summary[node] = {
                "packets": int(len(df)), "rate": 0.0, "duration": 0.0,
                "tilt_mean": 0.0, "tilt_std": 0.0, "lost": 0, "loss_pct": 0.0,
            }
    return summary


def _score_breakdown(metrics: list[dict]) -> dict:
    """Group metrics into 4 dimensions. Excludes no_data metrics entirely
    so empty groups show 'no_data' instead of a fabricated perfect score.
    """
    mmap = {m["name"]: m for m in metrics}

    def grp(names, weight: float = 1.0) -> dict:
        # Only count metrics that actually had data
        present = [mmap[n] for n in names if n in mmap and mmap[n].get("zone") != "no_data"]
        if not present:
            return {
                "score": None,
                "zone": "no_data",
                "contributors": [n for n in names if n in mmap],
                "weight": weight,
            }
        ded = sum(m["deduction"] for m in present)
        score = round(max(0.0, 10.0 - ded * 2.0), 1)
        if score >= 8: zone = "clean"
        elif score >= 6: zone = "minor"
        else: zone = "major"
        return {
            "score": score,
            "zone": zone,
            "contributors": [m["name"] for m in present],
            "weight": weight,
        }

    # Groupings cross-reference two papers:
    #   posture   — static geometry (Edriss 2024: shoulder-knee r=-0.444)
    #   extension — leg reach / vertical thrust (Yue 2023: leg_height_index β=0.393)
    #   symmetry  — left/right balance
    #   motion    — temporal dynamics (Yue 2023: movement β=0.345, rotation β=0.149)
    #   power     — our unique IMU dimension
    return {
        "posture":   grp(["leg_deviation", "trunk_vertical", "shoulder_knee_alignment"], 1.0),
        "extension": grp(["knee_extension", "leg_height_index"], 0.8),
        "symmetry":  grp(["leg_symmetry"], 0.7),
        "motion":    grp(["smoothness", "stability", "movement_frequency",
                          "rotation_frequency", "mean_pattern_duration"], 0.9),
        "power":     grp(["explosive_power", "energy_index", "motion_complexity"], 0.6),
    }


def _draw_skeleton_on_frame(frame, row) -> None:
    h, w = frame.shape[:2]

    def get_pt(idx):
        nm = LANDMARK_NAMES[idx]
        x = float(row.get(f"{nm}_x", 0) or 0)
        y = float(row.get(f"{nm}_y", 0) or 0)
        v = float(row.get(f"{nm}_vis", 0) or 0)
        return (int(x * w), int(y * h)), v

    for c1, c2 in LANDMARK_CONNECTIONS:
        p1, v1 = get_pt(c1)
        p2, v2 = get_pt(c2)
        if v1 > 0.3 and v2 > 0.3:
            cv2.line(frame, p1, p2, SKELETON_COLOR_BGR, 2, lineType=cv2.LINE_AA)
    for i in range(33):
        pt, v = get_pt(i)
        if v > 0.3:
            cv2.circle(frame, pt, 5, SKELETON_COLOR_BGR, -1, lineType=cv2.LINE_AA)
            cv2.circle(frame, pt, 2, (255, 255, 255), -1, lineType=cv2.LINE_AA)


def _draw_skeleton_live(frame, landmarks: list) -> None:
    if len(landmarks) != 33:
        return
    h, w = frame.shape[:2]

    def pt(i):
        return (int(landmarks[i][0] * w), int(landmarks[i][1] * h)), landmarks[i][2]

    for c1, c2 in LANDMARK_CONNECTIONS:
        p1, v1 = pt(c1)
        p2, v2 = pt(c2)
        if v1 > 0.3 and v2 > 0.3:
            cv2.line(frame, p1, p2, SKELETON_COLOR_BGR, 2, lineType=cv2.LINE_AA)
    for i in range(33):
        p, v = pt(i)
        if v > 0.3:
            cv2.circle(frame, p, 5, SKELETON_COLOR_BGR, -1, lineType=cv2.LINE_AA)
            cv2.circle(frame, p, 2, (255, 255, 255), -1, lineType=cv2.LINE_AA)


# ── Health & BLE ───────────────────────────────────────────────
@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/ble/status")
async def ble_status():
    return _ble.get_status()


@router.post("/ble/reconnect")
async def ble_reconnect():
    # Signal every node loop to drop its current BleakClient cleanly
    # and rescan.  The clean disconnect lets the firmware restart its
    # advertiser immediately, so the central (this process) sees the
    # node on the next scan round.
    for node in _ble.nodes.values():
        node.force_reconnect = True
    return {"status": "reconnecting"}


# ── Recording ──────────────────────────────────────────────────
@router.post("/recording/start")
async def start_recording():
    if _recorder.recording:
        return {"error": "Already recording"}
    if _set_manual_recording:
        _set_manual_recording(True)
    _recorder.start_manual()
    # Reset BYTETracker so this Set's IDs start at #1 (otherwise
    # tracker state carries over from the last Set and the coach sees
    # confusing high-number IDs like #14 / #15 on what is logically
    # the first swimmer of a fresh recording).
    try:
        _camera.reset_tracking()
    except Exception:
        pass
    # Push authoritative set number to M5 display
    try:
        _ble.write_set_number(_recorder.set_number)
    except Exception:
        pass
    return {"status": "recording", "set_number": _recorder.set_number}


@router.post("/recording/stop")
async def stop_recording():
    if not _recorder.recording:
        return {"error": "Not recording"}
    if _set_manual_recording:
        _set_manual_recording(False)
    _recorder.stop_recording()
    _clear_sessions_cache()
    # Tell M5 we stopped (0 = inactive on display)
    try:
        _ble.write_set_number(0)
    except Exception:
        pass
    return {"status": "stopped", "set_dir": _recorder.last_set_dir}


# ── Sets list + report ────────────────────────────────────────
@router.get("/sets")
async def list_sets():
    return load_or_rebuild_index(_DATA_DIR)


@router.get("/sets/{name}/report")
async def set_report(name: str):
    set_dir = _set_dir(name)
    if not os.path.isdir(set_dir):
        return JSONResponse({"error": "Set not found"}, status_code=404)
    report = compute_all_metrics(set_dir)
    if report is None:
        return JSONResponse({"error": "No data"}, status_code=404)

    metrics_json = [
        {
            "name": m.name,
            "value": (round(m.value, 2) if m.value is not None else None),
            "unit": m.unit,
            "deduction": m.deduction,
            "zone": m.zone,
            "max_value": m.max_value,
        }
        for m in report.metrics
    ]

    # Duration — prefer IMU (highest sample rate, most precise), but
    # fall back to vision / landmarks / video when the node wasn't
    # connected. Without this fallback a video-only set shows
    # ``时长 --:--  0.0s`` even though we clearly have 30 s of
    # footage, which confused coaches (DEVLOG #13).
    duration = 0.0
    for df in load_all_imus(set_dir).values():
        if not df.empty and "timestamp_local" in df.columns:
            ts = df["timestamp_local"].values.astype(float)
            if len(ts) > 1:
                duration = max(duration, float(ts[-1] - ts[0]))

    # Vision stats
    vision_df = load_vision(set_dir)
    vision_rows = int(len(vision_df))
    fps_mean = (
        float(vision_df["fps"].mean())
        if "fps" in vision_df.columns and not vision_df.empty
        else 0.0
    )

    if duration <= 0.0 and not vision_df.empty and "timestamp_local" in vision_df.columns:
        ts = vision_df["timestamp_local"].values.astype(float)
        if len(ts) > 1:
            duration = float(ts[-1] - ts[0])

    if duration <= 0.0:
        lm_path = os.path.join(set_dir, "landmarks.csv")
        if os.path.exists(lm_path):
            try:
                lm_ts = pd.read_csv(lm_path, usecols=["timestamp_local"])[
                    "timestamp_local"
                ].values.astype(float)
                if len(lm_ts) > 1:
                    duration = float(lm_ts[-1] - lm_ts[0])
            except Exception:
                pass

    # Video frame count
    frame_count = 0
    video_fps = 25.0
    video_path = os.path.join(set_dir, "video.mp4")
    if os.path.exists(video_path):
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            vf = cap.get(cv2.CAP_PROP_FPS)
            if vf and vf > 0:
                video_fps = float(vf)
        cap.release()

    # Last-ditch fallback: video container duration
    if duration <= 0.0 and frame_count > 0:
        duration = frame_count / video_fps

    return {
        "name": name,
        "overall_score": (round(report.overall_score, 1)
                          if report.overall_score is not None else None),
        "metrics": metrics_json,
        "phases": report.phases,
        "correlation": report.correlation,
        "duration": round(duration, 2),
        "vision_rows": vision_rows,
        "fps_mean": round(fps_mean, 1),
        "frame_count": frame_count,
        "imu_summary": _imu_summary(set_dir),
        "visibility": _visibility_stats(set_dir),
        "score_breakdown": _score_breakdown(metrics_json),
        "has_video": os.path.exists(video_path),
        "has_landmarks": os.path.exists(os.path.join(set_dir, "landmarks.csv")),
    }


@router.delete("/sets/{name}")
async def delete_set(name: str):
    set_dir = _set_dir(name)
    if not os.path.isdir(set_dir):
        return JSONResponse({"error": "Set not found"}, status_code=404)
    real = os.path.realpath(set_dir)
    root = os.path.realpath(_DATA_DIR)
    if not real.startswith(root + os.sep):
        return JSONResponse({"error": "Invalid set path"}, status_code=400)
    shutil.rmtree(set_dir)
    _clear_sessions_cache()
    return {"status": "deleted", "name": name}


# ── Time series ───────────────────────────────────────────────
@router.get("/sets/{name}/timeseries")
async def set_timeseries(name: str, resample: int = 200):
    """Return resampled time-series for IMU tilt + vision angles.

    Returns::
        {
            "time": [0, 0.005, ..., 1.0],          # normalized 0..1
            "duration": 12.3,                       # seconds
            "series": {
                "tilt_NODE_A1": [..],
                "tilt_NODE_A2": [..],
                "elbow": [..],
                "leg_deviation": [..],
                ...
            }
        }
    """
    set_dir = _set_dir(name)
    if not os.path.isdir(set_dir):
        return JSONResponse({"error": "Set not found"}, status_code=404)

    n = max(50, min(1000, resample))
    series: dict[str, list[float]] = {}

    # IMU tilt per node
    duration = 0.0
    for node, df in load_all_imus(set_dir).items():
        if df.empty:
            continue
        try:
            tilt = calc_imu_tilt(df[["ax", "ay", "az"]].to_dict("records"))
            if len(tilt) == 0:
                continue
            idx = np.linspace(0, len(tilt) - 1, n).astype(int)
            series[f"tilt_{node}"] = [round(float(tilt[i]), 2) for i in idx]
            if "timestamp_local" in df.columns:
                ts = df["timestamp_local"].values.astype(float)
                if len(ts) > 1:
                    duration = max(duration, float(ts[-1] - ts[0]))
        except Exception:
            pass

    # Vision angles from landmarks.csv — NaN on occluded frames, serialized as null
    lm_df = load_landmarks_csv(set_dir)
    if not lm_df.empty:
        computers = {
            "leg_deviation": calc_leg_deviation_vision,
            "knee_extension": calc_knee_extension,
            "trunk_vertical": calc_trunk_vertical,
            "shoulder_knee_alignment": calc_shoulder_knee_angle,
            "leg_symmetry": calc_leg_symmetry,
        }
        for key, fn in computers.items():
            try:
                arr = np.asarray(fn(lm_df), dtype=float)
                if len(arr) == 0:
                    continue
                idx = np.linspace(0, len(arr) - 1, n).astype(int)
                series[key] = [
                    None if np.isnan(arr[i]) else round(float(arr[i]), 2)
                    for i in idx
                ]
            except Exception:
                pass

    # Vision elbow (pre-computed during recording)
    vision_df = load_vision(set_dir)
    if not vision_df.empty and "angle_deg" in vision_df.columns:
        arr = vision_df["angle_deg"].values.astype(float)
        if len(arr) > 0:
            idx = np.linspace(0, len(arr) - 1, n).astype(int)
            series["elbow"] = [round(float(arr[i]), 2) for i in idx]

    return {
        "time": np.linspace(0.0, 1.0, n).round(4).tolist(),
        "duration": round(duration, 2),
        "series": series,
    }


# ── Landmarks for video overlay ────────────────────────────────
@router.get("/sets/{name}/landmarks")
async def set_landmarks(name: str):
    """Return a compact landmarks stream for client-side skeleton overlay.

    Response::
        {
            "fps": 25.0,                # nominal
            "times": [t0, t1, ...],     # seconds relative to start
            "frames": [[[x,y,v], ... 33], ...]  # normalized coords + visibility
        }

    Keypoints below VIS_THRESHOLD remain in the stream so the client can
    decide how to render (e.g. dim or hide).
    """
    set_dir = _set_dir(name)
    lm_path = os.path.join(set_dir, "landmarks.csv")
    if not os.path.exists(lm_path):
        return JSONResponse({"error": "No landmarks"}, status_code=404)
    try:
        df = pd.read_csv(lm_path)
    except Exception:
        return JSONResponse({"error": "Corrupt landmarks"}, status_code=500)
    if len(df) == 0:
        return JSONResponse({"error": "Empty landmarks"}, status_code=404)

    times: list[float] = []
    if "timestamp_local" in df.columns and len(df) > 0:
        t0 = float(df["timestamp_local"].iloc[0])
        times = [round(float(t) - t0, 3) for t in df["timestamp_local"].values]

    frames: list[list[list[float]]] = []
    for _, row in df.iterrows():
        pts = []
        for name_i in LANDMARK_NAMES:
            try:
                x = float(row.get(f"{name_i}_x", 0) or 0)
                y = float(row.get(f"{name_i}_y", 0) or 0)
                v = float(row.get(f"{name_i}_vis", 0) or 0)
            except (TypeError, ValueError):
                x = y = v = 0.0
            pts.append([round(x, 4), round(y, 4), round(v, 3)])
        frames.append(pts)

    # Infer fps from average time delta
    fps = 25.0
    if len(times) > 2:
        deltas = [times[i + 1] - times[i] for i in range(len(times) - 1)]
        deltas = [d for d in deltas if d > 0]
        if deltas:
            fps = round(1.0 / (sum(deltas) / len(deltas)), 2)

    # Multi-person stream (optional) — 1:1 aligned with ``frames``
    # when the set was recorded with the new pipeline. Older sets
    # without landmarks_multi.jsonl simply won't include this key,
    # and the client falls back to single-person rendering.
    #
    # ``all_ids`` is the parallel BYTETracker ID stream (added in
    # phase 7.1). For each frame it's a list the same length as that
    # frame's ``persons`` list — each entry an ``int`` (stable across
    # frames) or ``None`` (older recordings, MP backend, or a brand
    # new detection). Frontend uses ``id`` when present and falls back
    # to array-order colouring when not.
    all_frames: list[list[list[list[float]]]] | None = None
    all_ids: list[list[int | None]] | None = None
    multi_path = os.path.join(set_dir, "landmarks_multi.jsonl")
    if os.path.exists(multi_path):
        try:
            parsed_persons: list[list[list[list[float]]]] = []
            parsed_ids: list[list[int | None]] = []
            with open(multi_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    persons = obj.get("persons") or []
                    parsed_persons.append(persons)
                    raw_ids = obj.get("ids")
                    if isinstance(raw_ids, list) and len(raw_ids) == len(persons):
                        parsed_ids.append([
                            (int(x) if isinstance(x, (int, float)) else None)
                            for x in raw_ids
                        ])
                    else:
                        # Older recordings: no ids field. Pad with None
                        # so the frontend can rely on length alignment.
                        parsed_ids.append([None] * len(persons))
            # Only return if the file actually has data and roughly
            # matches the primary stream length (tolerate off-by-one
            # from the final flush).
            if parsed_persons and abs(len(parsed_persons) - len(frames)) <= 2:
                all_frames = parsed_persons
                all_ids = parsed_ids
        except Exception:
            all_frames = None
            all_ids = None

    payload = {
        "fps": fps,
        "duration": times[-1] if times else 0.0,
        "times": times,
        "frames": frames,
    }
    if all_frames is not None:
        payload["all_frames"] = all_frames
    if all_ids is not None:
        payload["all_ids"] = all_ids

    # Athlete name + colour overrides keyed by track_id (phase 7.2).
    # The frontend uses this to render "张三" / "李四" labels above
    # each skeleton instead of raw "#3" tags. Empty when no bindings
    # exist for this Set, in which case the frontend falls back to
    # ``#${track_id}`` and the auto-derived colour from
    # ``TEAM_COLORS[id % 8]``.
    if _athletes is not None:
        athlete_map = _athletes.lookup_for_set(name)
        # Stringify keys for JSON; frontend normalises back to int.
        payload["athlete_map"] = {str(k): v for k, v in athlete_map.items()}
    return payload


# ── Frame extraction ───────────────────────────────────────────
@router.get("/sets/{name}/frame/{time_sec}")
async def set_frame_at_time(name: str, time_sec: float, skeleton: int = 1):
    """Extract a single frame at `time_sec` seconds, optionally draw skeleton.

    Any unreadable or corrupt video returns 404 so the UI gracefully
    shows "no keyframe available" instead of a loud 500 error banner.
    Typical corruption cause: previous server process was killed
    while recording → ``VideoWriter.release()`` never ran → missing
    moov atom.
    """
    set_dir = _set_dir(name)
    video_path = os.path.join(set_dir, "video.mp4")
    if not os.path.exists(video_path):
        return JSONResponse({"error": "No video"}, status_code=404)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        return JSONResponse(
            {"error": "Corrupt video (missing moov atom — previous recording didn't finish cleanly)"},
            status_code=404,
        )

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        return JSONResponse({"error": "Empty video"}, status_code=404)
    target = max(0, min(total - 1, int(time_sec * fps)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return JSONResponse({"error": "Cannot read frame"}, status_code=404)

    if skeleton:
        lm_path = os.path.join(set_dir, "landmarks.csv")
        if os.path.exists(lm_path):
            try:
                lm_df = pd.read_csv(lm_path)
                if len(lm_df) > 0 and total > 0:
                    idx = max(0, min(int(len(lm_df) * target / total), len(lm_df) - 1))
                    _draw_skeleton_on_frame(frame, lm_df.iloc[idx])
            except Exception:
                pass

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        return JSONResponse({"error": "Encode failed"}, status_code=500)
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.get("/sets/{name}/keyframes/{index}")
async def get_keyframe(name: str, index: int, count: int = 3):
    """Legacy & flexible keyframes. count=3 -> 10/50/90%, count=6 -> evenly spaced."""
    set_dir = _set_dir(name)
    video_path = os.path.join(set_dir, "video.mp4")
    if not os.path.exists(video_path):
        return JSONResponse({"error": "No video"}, status_code=404)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        # Treat "can't open" as "no video" for the UI — usually means
        # the prior recording crashed and left a corrupt file.
        return JSONResponse(
            {"error": "Corrupt video (previous recording didn't finish cleanly)"},
            status_code=404,
        )
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.release()
    if total <= 0:
        return JSONResponse({"error": "Empty video"}, status_code=404)

    n = max(1, min(9, count))
    if n == 3:
        positions = [0.1, 0.5, 0.9]
    else:
        positions = [(i + 0.5) / n for i in range(n)]
    if index < 0 or index >= len(positions):
        index = 0
    t = (total * positions[index]) / fps if fps > 0 else 0.0
    return await set_frame_at_time(name, t, 1)


# ── Video streaming ────────────────────────────────────────────
@router.get("/sets/{name}/video")
async def stream_video(name: str, request: Request):
    set_dir = _set_dir(name)
    video_path = os.path.join(set_dir, "video.mp4")
    if not os.path.exists(video_path):
        return JSONResponse({"error": "No video"}, status_code=404)

    file_size = os.path.getsize(video_path)
    range_header = request.headers.get("range")
    if range_header:
        try:
            m = range_header.replace("bytes=", "").split("-")
            start = int(m[0]) if m[0] else 0
            end = int(m[1]) if len(m) > 1 and m[1] else file_size - 1
        except ValueError:
            start, end = 0, file_size - 1
        end = min(end, file_size - 1)
        length = max(1, end - start + 1)

        def iterfile(s: int, ln: int):
            with open(video_path, "rb") as f:
                f.seek(s)
                remaining = ln
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iterfile(start, length),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )
    return FileResponse(video_path, media_type="video/mp4")


# ── Camera ─────────────────────────────────────────────────────
class CameraConfigRequest(BaseModel):
    url: Optional[str] = None
    rotation: Optional[int] = None


@router.post("/camera/config")
async def camera_config(req: CameraConfigRequest):
    cfg = load_config()
    hw = cfg.get("hardware", {})
    if req.url is not None and req.url:
        _camera.set_url(req.url)
        hw["camera_url"] = req.url
    if req.rotation is not None and req.rotation in (0, 90, 180, 270):
        _camera.rotation = req.rotation
        hw["camera_rotation"] = req.rotation
    cfg["hardware"] = hw
    try:
        save_config(cfg)
    except Exception:
        pass
    return {"status": "ok"}


@router.post("/camera/test")
async def camera_test(req: CameraConfigRequest):
    """Probe the given URL for a JPEG start marker (quick liveness check)."""
    url = (req.url or "").strip()
    if not url:
        return JSONResponse({"error": "No URL"}, status_code=400)
    try:
        s = urllib.request.urlopen(url, timeout=3)
        b = s.read(65536)
        return {"ok": b.find(b"\xff\xd8") >= 0, "bytes": len(b)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/camera/snapshot")
async def camera_snapshot(skeleton: int = 1):
    data = _camera.get_latest()
    if not data or not data.get("jpeg"):
        return JSONResponse({"error": "No frame"}, status_code=404)
    if not skeleton or data.get("raw_frame") is None:
        return Response(content=data["jpeg"], media_type="image/jpeg")
    frame = data["raw_frame"].copy()
    _draw_skeleton_live(frame, data.get("landmarks") or [])
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        return JSONResponse({"error": "Encode failed"}, status_code=500)
    return Response(content=buf.tobytes(), media_type="image/jpeg")


# ── Config ─────────────────────────────────────────────────────
@router.get("/config")
async def get_config():
    return load_config()


class ConfigUpdate(BaseModel):
    fina: Optional[dict] = None
    hardware: Optional[dict] = None
    dashboard: Optional[dict] = None


@router.post("/config")
async def post_config(req: ConfigUpdate):
    cfg = load_config()
    if req.fina is not None:
        cfg.setdefault("fina", {})
        for k, v in req.fina.items():
            if isinstance(v, dict) and isinstance(cfg["fina"].get(k), dict):
                cfg["fina"][k].update(v)
            else:
                cfg["fina"][k] = v
    if req.hardware is not None:
        cfg.setdefault("hardware", {}).update(req.hardware)
    if req.dashboard is not None:
        cfg.setdefault("dashboard", {}).update(req.dashboard)
    save_config(cfg)
    return {"status": "ok"}


# ── Data stats ─────────────────────────────────────────────────
# ── Athlete bindings (phase 7.2) ───────────────────────────────
# Coach assigns a stable name (e.g. "张三") to a BYTETracker ID
# inside a specific Set. Bindings are per-Set because BYTETracker
# state resets between Sets (see DEVLOG #25), so the same swimmer
# gets a fresh ID in every recording.

class _AthleteCreate(BaseModel):
    name: str
    color: Optional[str] = None


class _AthleteUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class _BindReq(BaseModel):
    set: str
    track_id: int


@router.get("/athletes")
async def list_athletes():
    if _athletes is None:
        return {"athletes": []}
    return {"athletes": _athletes.list_athletes()}


@router.post("/athletes")
async def create_athlete(req: _AthleteCreate):
    if _athletes is None:
        return JSONResponse({"error": "store not ready"}, status_code=503)
    try:
        ath = _athletes.create_athlete(req.name, req.color)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return ath


@router.patch("/athletes/{athlete_id}")
async def update_athlete(athlete_id: str, req: _AthleteUpdate):
    if _athletes is None:
        return JSONResponse({"error": "store not ready"}, status_code=503)
    ath = _athletes.update_athlete(athlete_id, name=req.name, color=req.color)
    if ath is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return ath


@router.delete("/athletes/{athlete_id}")
async def delete_athlete(athlete_id: str):
    if _athletes is None:
        return JSONResponse({"error": "store not ready"}, status_code=503)
    if not _athletes.delete_athlete(athlete_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"status": "deleted", "id": athlete_id}


@router.post("/athletes/{athlete_id}/bind")
async def bind_track(athlete_id: str, req: _BindReq):
    if _athletes is None:
        return JSONResponse({"error": "store not ready"}, status_code=503)
    if not req.set or req.track_id < 0:
        return JSONResponse({"error": "invalid set/track_id"}, status_code=400)
    # Sanity: refuse to bind to a Set that doesn't exist on disk.
    # Stops typos / stale frontend state from creating bindings for
    # phantom Sets that would never resolve in lookup_for_set.
    if not os.path.isdir(_set_dir(req.set)):
        return JSONResponse(
            {"error": f"set not found: {req.set}"}, status_code=404
        )
    ath = _athletes.bind_track(athlete_id, req.set, int(req.track_id))
    if ath is None:
        return JSONResponse({"error": "athlete not found"}, status_code=404)
    return ath


@router.post("/athletes/{athlete_id}/unbind")
async def unbind_track(athlete_id: str, req: _BindReq):
    """Remove an athlete's binding for ``(set, track_id)``.

    Modeled as POST rather than DELETE-with-body because some HTTP
    clients (notably ``httpx.Client.delete`` and a number of CDN/proxy
    layers) silently drop bodies on DELETE — POST is universally safe
    and the operation isn't idempotent enough to need DELETE semantics.
    """
    if _athletes is None:
        return JSONResponse({"error": "store not ready"}, status_code=503)
    ok = _athletes.unbind_track(athlete_id, req.set, int(req.track_id))
    if not ok:
        return JSONResponse({"error": "binding not found"}, status_code=404)
    return {"status": "unbound", "set": req.set, "track_id": req.track_id}


# ── Cross-Set comparison (phase 7.3) ───────────────────────────
# These endpoints power the "对比" tab. They reuse the per-Set
# report path so the metric values shown in comparison are
# byte-identical to what each Set's analysis page shows — no
# divergent scoring logic to keep in sync.

@router.get("/athletes/{athlete_id}/sets")
async def athlete_sets(athlete_id: str):
    """List every (set, track_id) binding for ``athlete_id``.

    Used by the compare-tab Set picker so the coach can pick
    "all of 张三's training sessions" with one click.
    """
    if _athletes is None:
        return {"sets": []}
    ath = _athletes.get_athlete(athlete_id)
    if ath is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "athlete_id": ath["id"],
        "name": ath["name"],
        "color": ath.get("color"),
        "bindings": ath.get("bindings", []),
    }


@router.get("/compare")
async def compare_sets(sets: str = ""):
    """Batch-fetch slim Set reports for cross-Set visualisation.

    ``sets`` is a comma-separated list of Set names. Each entry in
    the response is the same metric / overall_score / duration
    structure used by ``/api/sets/{name}/report`` — minus the heavy
    ``phases`` field which the compare view doesn't use — plus an
    ``athletes`` list mapping track_ids to athlete names that the
    coach has bound for this Set (phase 7.2).

    Sets that don't exist are reported individually as
    ``{"name": ..., "error": "not found"}`` rather than failing
    the whole request, so the frontend can render a partial
    comparison even when one of N selected Sets has been deleted.
    """
    set_names = [s.strip() for s in sets.split(",") if s.strip()]
    if not set_names:
        return JSONResponse({"error": "sets parameter required"},
                            status_code=400)
    if len(set_names) > 20:
        return JSONResponse({"error": "max 20 sets per request"},
                            status_code=400)

    results = []
    for name in set_names:
        rep = await set_report(name)
        if isinstance(rep, JSONResponse):
            results.append({"name": name, "error": "not found"})
            continue
        slim = {
            "name": name,
            "overall_score": rep.get("overall_score"),
            "duration": rep.get("duration"),
            "metrics": rep.get("metrics"),
            "imu_summary": rep.get("imu_summary"),
            "fps_mean": rep.get("fps_mean"),
            "frame_count": rep.get("frame_count"),
            "has_video": rep.get("has_video"),
            "athletes": [],
        }
        if _athletes is not None:
            ath_map = _athletes.lookup_for_set(name)
            slim["athletes"] = [
                {
                    "track_id": tid,
                    "name": v["name"],
                    "athlete_id": v["athlete_id"],
                    "color": v.get("color"),
                }
                for tid, v in sorted(ath_map.items())
            ]
        results.append(slim)
    return {"sets": results}


@router.get("/data/stats")
async def data_stats():
    sessions = load_or_rebuild_index(_DATA_DIR)
    total_size = 0
    if os.path.isdir(_DATA_DIR):
        for name in os.listdir(_DATA_DIR):
            p = os.path.join(_DATA_DIR, name)
            if os.path.isdir(p):
                for root, _dirs, files in os.walk(p):
                    for f in files:
                        try:
                            total_size += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
    return {
        "set_count": len(sessions),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "data_dir": _DATA_DIR,
    }
