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
    if dev_state == "REC" and not recorder.recording:
        _manual_recording = False
        recorder.start_recording(set_number)
    elif dev_state == "IDLE" and recorder.recording and not _manual_recording:
        recorder.stop_recording()


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

        # Write landmarks CSV
        # camera_manager returns landmarks as [[x, y, vis], ...] (lists)
        # recorder.write_landmarks expects [{'x': .., 'y': .., 'z': .., 'visibility': ..}, ...]
        if data["landmarks"] and len(data["landmarks"]) == 33:
            lm_dicts = [
                {"x": l[0], "y": l[1], "z": 0.0, "visibility": l[2]}
                for l in data["landmarks"]
            ]
            recorder.write_landmarks(local_ts, frame_count, lm_dicts)

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
    ble_manager.stop()
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
