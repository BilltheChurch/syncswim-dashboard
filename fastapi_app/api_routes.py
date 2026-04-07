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
