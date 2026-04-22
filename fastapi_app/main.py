"""Coach Workstation — FastAPI backend.

Single-process server: BLE + camera + recording + WebSocket + REST API.
"""
import threading
import time

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from fastapi_app.ble_manager import BleManager
from fastapi_app.camera_manager import CameraManager
from fastapi_app.recorder import Recorder
from fastapi_app.ws_video import video_ws
from fastapi_app.ws_metrics import metrics_ws
from fastapi_app import api_routes

app = FastAPI(title="SyncSwim Coach Station")

# --- Shared instances ---
recorder = Recorder(data_dir="data")
ble_manager = BleManager(
    on_imu_data=None,  # wired in startup
    on_state_change=None,
)
camera_manager = CameraManager()


# --- BLE callbacks ---
_manual_recording = False  # True when recording started from web UI

def on_ble_state_change(dev_state: str, set_number: int):
    """Master node Button A triggers recording start/stop.

    Manual recordings (started from web UI) are not interrupted by BLE IDLE.
    Only a BLE REC->IDLE transition stops a BLE-initiated recording.
    """
    global _manual_recording
    import logging
    logging.info(f"BLE state: {dev_state}, set={set_number}, manual={_manual_recording}, recording={recorder.recording}")

    # If manual recording is active, ignore all BLE state changes
    if _manual_recording:
        return

    if dev_state == "REC" and not recorder.recording:
        # Don't trust M5's set_number — the firmware resets its counter
        # to 0 on every power-cycle, so every session would start at
        # set_001 and clash with prior ones. The server is the source
        # of truth: scan data/ for the next free number.
        recorder.start_manual()
        # Push the authoritative number back to the M5 so its display
        # shows what the server actually saved (B-protocol).
        ble_manager.write_set_number(recorder.set_number)
    elif dev_state == "IDLE" and recorder.recording:
        recorder.stop_recording()
        ble_manager.write_set_number(0)  # 0 = "no active set" on M5 display
        # Clear sessions cache so new recording appears immediately
        import os
        try:
            os.remove(os.path.join(recorder._data_dir, "sessions.json"))
        except OSError:
            pass


def on_ble_imu_data(node_name: str, local_ts: float, readings: list):
    """Write IMU data to CSV when recording.

    Bridge between BleManager callback format and Recorder.write_imu format.
    BleManager readings have: device_ts, ax, ay, az, gx, gy, gz
    Recorder expects: local_ts, ts, node, state, set, ax, ay, az, gx, gy, gz
    """
    if not recorder.recording:
        return
    rows = []
    for r in readings:
        rows.append({
            "local_ts": local_ts,
            "ts": r["device_ts"],
            "node": node_name,
            "state": "REC",
            "set": recorder.set_number,
            "ax": r["ax"],
            "ay": r["ay"],
            "az": r["az"],
            "gx": r["gx"],
            "gy": r["gy"],
            "gz": r["gz"],
        })
    recorder.write_imu(node_name, rows)


# --- Vision writer (background thread, Option B: polling) ---
_vision_writer_running = False


def _vision_writer_loop():
    """Background thread: poll camera, write to recorder when recording."""
    frame_count = 0
    while _vision_writer_running:
        time.sleep(0.04)  # ~25fps
        if not recorder.recording:
            continue
        data = camera_manager.get_latest()
        if not data or not data["jpeg"]:
            continue
        frame_count += 1
        local_ts = time.time()

        # Write vision CSV
        elbow = data["angles"].get("elbow", 0.0) if data["angles"] else 0.0
        has_pose = bool(
            data["landmarks"]
            and any(l[2] > 0.3 for l in data["landmarks"])
        )
        recorder.write_vision(
            local_ts, frame_count, "R_Elbow", elbow, 1 if has_pose else 0, 25.0
        )

        # Write landmarks CSV — ALWAYS one row per video frame, even
        # when no pose is detected. Keeping the landmark row count 1:1
        # with the video frame count is what lets the analysis page
        # map ``video.currentTime`` → skeleton index by linear ratio
        # without drift. Previously we skipped the row on no-pose
        # frames, which made landmarks.csv shorter than video.mp4 and
        # caused the skeleton to race ahead during playback. (DEVLOG #13)
        #
        # recorder.write_landmarks expects [{'x': .., 'y': .., 'z': .., 'visibility': ..}, ...]
        lm_list = data.get("landmarks") or []
        if lm_list and len(lm_list) == 33:
            lm_dicts = [
                {"x": l[0], "y": l[1], "z": 0.0, "visibility": l[2]}
                for l in lm_list
            ]
        else:
            lm_dicts = []
        recorder.write_landmarks(local_ts, frame_count, lm_dicts)

        # Multi-person landmarks (JSONL) — persist every athlete per
        # frame so the analysis page can render dual-/team-person
        # skeletons, not just the primary swimmer.
        recorder.write_landmarks_multi(
            local_ts, frame_count, data.get("all_landmarks") or []
        )

        # Write video frame
        if data.get("raw_frame") is not None:
            recorder.write_video_frame(data["raw_frame"])


# --- Startup / Shutdown ---
@app.on_event("startup")
async def startup():
    global _vision_writer_running

    # Wire callbacks
    ble_manager.on_imu_data = on_ble_imu_data
    ble_manager.on_state_change = on_ble_state_change

    # Init API routes with shared instances
    def set_manual(val):
        global _manual_recording
        _manual_recording = val
    api_routes.init(ble_manager, camera_manager, recorder, set_manual_recording=set_manual)

    # Start services
    ble_manager.start()
    camera_manager.start()

    # Start vision writer background thread
    _vision_writer_running = True
    t = threading.Thread(target=_vision_writer_loop, daemon=True)
    t.start()


@app.on_event("shutdown")
async def shutdown():
    global _vision_writer_running

    _vision_writer_running = False
    camera_manager.stop()
    # 6 s grace is a compromise: long enough to cover a BleakScanner
    # scan round (5 s) + a BleakClient disconnect (~1 s), short enough
    # that uvicorn doesn't look hung. Every clean disconnect here means
    # the M5 gets its onDisconnect callback immediately and resumes
    # advertising — so the next server start finds it without a manual
    # device reboot (DEVLOG #5 / #16).
    ble_manager.stop(grace=6.0)
    if recorder.recording:
        recorder.stop_recording()


# --- Mount routes ---
app.include_router(api_routes.router)


# --- WebSocket endpoints ---
@app.websocket("/ws/video")
async def ws_video(websocket: WebSocket):
    await video_ws(websocket, camera_manager)


@app.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket):
    await metrics_ws(websocket, ble_manager, recorder)


# --- Static files (must be last) ---
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(static_dir / "index.html"))
