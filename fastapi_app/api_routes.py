"""REST API routes for recording control and analysis."""
import os

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api")

# Module-level references, set by init()
_ble = None
_camera = None
_recorder = None
_set_manual_recording = None  # callback to set manual recording flag


def init(ble_manager, camera_manager, recorder, set_manual_recording=None):
    global _ble, _camera, _recorder, _set_manual_recording
    _ble = ble_manager
    _camera = camera_manager
    _recorder = recorder
    _set_manual_recording = set_manual_recording


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/ble/status")
async def ble_status():
    return _ble.get_status()


@router.post("/recording/start")
async def start_recording():
    if _recorder.recording:
        return {"error": "Already recording"}
    if _set_manual_recording:
        _set_manual_recording(True)
    _recorder.start_manual()
    return {"status": "recording", "set_number": _recorder.set_number}


@router.post("/recording/stop")
async def stop_recording():
    if not _recorder.recording:
        return {"error": "Not recording"}
    if _set_manual_recording:
        _set_manual_recording(False)
    _recorder.stop_recording()
    # Clear sessions cache so new recording appears immediately
    import os
    try:
        os.remove(os.path.join(_recorder._data_dir, "sessions.json"))
    except OSError:
        pass
    return {"status": "stopped", "set_dir": _recorder.last_set_dir}


@router.get("/sets")
async def list_sets():
    from dashboard.core.data_loader import load_or_rebuild_index
    return load_or_rebuild_index("data")


@router.get("/sets/{name}/report")
async def set_report(name: str):
    from dashboard.core.metrics import compute_all_metrics
    set_dir = os.path.join("data", name)
    if not os.path.isdir(set_dir):
        return {"error": "Set not found"}
    report = compute_all_metrics(set_dir)
    if report is None:
        return {"error": "No data"}
    return {
        "overall_score": round(report.overall_score, 1),
        "metrics": [
            {"name": m.name, "value": round(m.value, 1), "unit": m.unit,
             "deduction": m.deduction, "zone": m.zone}
            for m in report.metrics
        ],
        "phases": report.phases,
        "correlation": report.correlation,
    }


@router.get("/sets/{name}/keyframes/{index}")
async def get_keyframe(name: str, index: int):
    """Extract a keyframe from video.mp4 and return as JPEG with skeleton overlay."""
    import cv2
    import base64
    from fastapi.responses import JSONResponse

    set_dir = os.path.join("data", name)
    video_path = os.path.join(set_dir, "video.mp4")

    if not os.path.exists(video_path):
        return JSONResponse({"error": "No video"}, status_code=404)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return JSONResponse({"error": "Cannot open video"}, status_code=500)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return JSONResponse({"error": "Empty video"}, status_code=404)

    # Extract frame at 3 positions: 10%, 50%, 90% of video
    positions = [0.1, 0.5, 0.9]
    if index < 0 or index >= len(positions):
        index = 0
    target_frame = int(total_frames * positions[index])
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        return JSONResponse({"error": "Cannot read frame"}, status_code=500)

    # Try to overlay skeleton from landmarks.csv
    try:
        import pandas as pd
        import numpy as np
        landmarks_path = os.path.join(set_dir, "landmarks.csv")
        if os.path.exists(landmarks_path):
            lm_df = pd.read_csv(landmarks_path)
            if len(lm_df) > 0:
                # Find closest landmark row to target frame position
                lm_idx = min(int(len(lm_df) * positions[index]), len(lm_df) - 1)
                row = lm_df.iloc[lm_idx]
                h, w = frame.shape[:2]

                # Draw skeleton connections
                CONNECTIONS = [
                    (11,12),(11,13),(13,15),(12,14),(14,16),
                    (11,23),(12,24),(23,24),(23,25),(24,26),(25,27),(26,28)
                ]
                LANDMARK_NAMES = [
                    "nose","left_eye_inner","left_eye","left_eye_outer",
                    "right_eye_inner","right_eye","right_eye_outer",
                    "left_ear","right_ear","mouth_left","mouth_right",
                    "left_shoulder","right_shoulder","left_elbow","right_elbow",
                    "left_wrist","right_wrist","left_pinky","right_pinky",
                    "left_index","right_index","left_thumb","right_thumb",
                    "left_hip","right_hip","left_knee","right_knee",
                    "left_ankle","right_ankle","left_heel","right_heel",
                    "left_foot_index","right_foot_index",
                ]

                def get_pt(idx):
                    name = LANDMARK_NAMES[idx]
                    x = row.get(f"{name}_x", 0)
                    y = row.get(f"{name}_y", 0)
                    vis = row.get(f"{name}_vis", 0)
                    return (int(float(x) * w), int(float(y) * h)), float(vis)

                for c1, c2 in CONNECTIONS:
                    p1, v1 = get_pt(c1)
                    p2, v2 = get_pt(c2)
                    if v1 > 0.3 and v2 > 0.3:
                        cv2.line(frame, p1, p2, (59, 130, 246), 2)

                for i in range(33):
                    pt, vis = get_pt(i)
                    if vis > 0.3:
                        cv2.circle(frame, pt, 4, (59, 130, 246), -1)
                        cv2.circle(frame, pt, 2, (255, 255, 255), -1)
    except Exception:
        pass  # Return frame without skeleton if anything fails

    # Encode as JPEG
    ok, jpeg_buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return JSONResponse({"error": "Encode failed"}, status_code=500)

    from fastapi.responses import Response
    return Response(content=jpeg_buf.tobytes(), media_type="image/jpeg")


class CameraConfigRequest(BaseModel):
    url: str = ""
    rotation: int = 0


@router.post("/camera/config")
async def camera_config(req: CameraConfigRequest):
    if req.url:
        _camera.set_url(req.url)
    if req.rotation in (0, 90, 180, 270):
        _camera.rotation = req.rotation
    return {"status": "ok"}
