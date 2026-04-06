# Coach Workstation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Streamlit with a FastAPI + HTML/JS coach workstation featuring real-time video with skeleton overlay, dashboard-controlled recording, and post-recording analysis with keyframe comparison.

**Architecture:** FastAPI backend serves a single-page HTML/JS frontend. BLE and camera managers run as background threads. WebSocket pushes live video frames + skeleton data to the browser. REST API handles recording control and analysis reports. All existing `dashboard/core/` scoring/analysis modules are reused directly.

**Tech Stack:** FastAPI, uvicorn, WebSocket, HTML5 Canvas, vanilla JS, existing MediaPipe/BLE/scoring modules

---

### Task 1: Install Dependencies + Create Directory Structure

**Files:**
- Modify: `requirements.txt`
- Create: `fastapi_app/__init__.py`
- Create: `fastapi_app/main.py`

**Step 1: Install FastAPI dependencies**

Run: `.venv/bin/pip install fastapi uvicorn[standard] python-multipart websockets`

**Step 2: Add to requirements.txt**

Append these lines:
```
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
python-multipart>=0.0.20
websockets>=15.0
```

**Step 3: Create directory structure**

```bash
mkdir -p fastapi_app/static
touch fastapi_app/__init__.py
```

**Step 4: Create minimal main.py that starts**

```python
# fastapi_app/main.py
"""Coach Workstation — FastAPI backend."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

app = FastAPI(title="SyncSwim Coach Station")

# Serve static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
async def index():
    return FileResponse(str(static_dir / "index.html"))

@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

Create minimal `fastapi_app/static/index.html`:
```html
<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><title>SyncSwim Coach Station</title></head>
<body><h1>SyncSwim Coach Station</h1><p>Loading...</p></body>
</html>
```

**Step 5: Verify it starts**

Run: `.venv/bin/uvicorn fastapi_app.main:app --host 0.0.0.0 --port 8000 &`
Run: `curl -s http://localhost:8000/api/health`
Expected: `{"status":"ok"}`
Kill: `pkill -f uvicorn`

**Step 6: Commit**

```bash
git add requirements.txt fastapi_app/
git commit -m "feat: FastAPI skeleton with static file serving"
```

---

### Task 2: BLE Manager Module

**Files:**
- Create: `fastapi_app/ble_manager.py`

**Step 1: Create BLE manager**

Port the BLE logic from `sync_recorder.py` into a class-based manager. This module manages dual BLE connections and exposes state for WebSocket and API consumers.

```python
# fastapi_app/ble_manager.py
"""Dual-node BLE connection manager.

Manages BLE connections to NODE_A1 (forearm) and NODE_A2 (shin).
NODE_A1 is the master node that controls recording state via Button A.
"""
import asyncio
import struct
import threading
import time
from dataclasses import dataclass, field

from bleak import BleakClient, BleakScanner

from dashboard.config import load_config

# BLE binary protocol constants
HEADER_SIZE = 4
READING_SIZE = 16
READING_FMT = '<Ihhhhhh'


@dataclass
class NodeState:
    """Per-node BLE state."""
    name: str
    connected: bool = False
    rate: float = 0.0
    total_packets: int = 0
    set_packets: int = 0
    lost: int = 0
    last_device_ts: int | None = None
    last_imu: dict = field(default_factory=dict)
    tilt: float = 0.0
    _rate_window: list = field(default_factory=list)

    def calc_rate(self):
        now = time.time()
        self._rate_window.append(now)
        cutoff = now - 2.0
        self._rate_window = [t for t in self._rate_window if t > cutoff]
        if len(self._rate_window) > 1:
            span = self._rate_window[-1] - self._rate_window[0]
            self.rate = (len(self._rate_window) - 1) / span if span > 0 else 0
        else:
            self.rate = 0.0


class BleManager:
    """Manages dual BLE node connections."""

    def __init__(self, on_imu_data=None, on_state_change=None):
        config = load_config()
        hw = config.get("hardware", {})
        self.node_names = hw.get("imu_nodes", ["NODE_A1", "NODE_A2"])
        self.master_node = self.node_names[0]
        self.char_uuid = hw.get("ble_char_uuid", "abcd1234-ab12-cd34-ef56-abcdef123456")

        self.nodes: dict[str, NodeState] = {
            name: NodeState(name=name) for name in self.node_names
        }
        self.running = False
        self._threads: list[threading.Thread] = []

        # Callbacks
        self.on_imu_data = on_imu_data  # (node_name, local_ts, readings_list)
        self.on_state_change = on_state_change  # (dev_state, set_number)

    def start(self):
        """Start BLE connection threads for all nodes."""
        self.running = True
        for name in self.node_names:
            t = threading.Thread(target=self._node_thread, args=(name,), daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        """Stop all BLE connections."""
        self.running = False

    def get_status(self) -> dict:
        """Return current status of all nodes."""
        return {
            name: {
                "connected": node.connected,
                "rate": round(node.rate, 1),
                "tilt": round(node.tilt, 1),
                "packets": node.total_packets,
                "lost": node.lost,
            }
            for name, node in self.nodes.items()
        }

    def _make_handler(self, node_name: str):
        """Create BLE notification handler for a specific node."""
        import math
        node = self.nodes[node_name]

        def handler(sender, data):
            if len(data) < HEADER_SIZE:
                return

            dev_state = "REC" if data[0] == 1 else "IDLE"
            set_n = data[1]
            count = data[2]
            local_ts = time.time()

            if len(data) < HEADER_SIZE + count * READING_SIZE:
                return

            # Master node controls recording
            if node_name == self.master_node and self.on_state_change:
                self.on_state_change(dev_state, set_n)

            readings = []
            for i in range(count):
                offset = HEADER_SIZE + i * READING_SIZE
                ts, ax_i, ay_i, az_i, gx_i, gy_i, gz_i = struct.unpack_from(
                    READING_FMT, data, offset)
                ax = ax_i / 1000.0
                ay = ay_i / 1000.0
                az = az_i / 1000.0
                gx = gx_i / 10.0
                gy = gy_i / 10.0
                gz = gz_i / 10.0

                node.total_packets += 1
                node.calc_rate()

                # Packet loss detection
                if node.last_device_ts is not None:
                    gap = ts - node.last_device_ts
                    if gap > 100:
                        node.lost += max(0, int(gap / 12) - 1)
                node.last_device_ts = ts

                # Compute tilt
                node.tilt = math.degrees(math.atan2(ax, math.sqrt(ay**2 + az**2)))

                node.last_imu = {"ax": ax, "ay": ay, "az": az, "gx": gx, "gy": gy, "gz": gz}

                readings.append({
                    "ts": ts, "local_ts": local_ts, "node": node_name,
                    "state": dev_state, "set": set_n,
                    "ax": ax, "ay": ay, "az": az, "gx": gx, "gy": gy, "gz": gz,
                })

            if self.on_imu_data:
                self.on_imu_data(node_name, local_ts, readings)

        return handler

    def _node_thread(self, node_name: str):
        """BLE connection loop for one node."""
        node = self.nodes[node_name]
        handler = self._make_handler(node_name)

        async def loop():
            while self.running:
                try:
                    node.connected = False
                    devices = await BleakScanner.discover(5.0, return_adv=True)
                    target = None
                    for addr, (d, adv) in devices.items():
                        if d.name == node_name:
                            target = d
                            break

                    if not target:
                        await asyncio.sleep(3)
                        continue

                    async with BleakClient(target.address) as client:
                        node.connected = True
                        await client.start_notify(self.char_uuid, handler)
                        while client.is_connected and self.running:
                            await asyncio.sleep(0.25)
                        await client.stop_notify(self.char_uuid)
                except Exception:
                    pass
                finally:
                    node.connected = False
                if self.running:
                    await asyncio.sleep(3)

        asyncio.run(loop())
```

**Step 2: Verify import works**

Run: `.venv/bin/python -c "from fastapi_app.ble_manager import BleManager; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add fastapi_app/ble_manager.py
git commit -m "feat: BLE manager module with dual-node support"
```

---

### Task 3: Camera Manager + MediaPipe Processing

**Files:**
- Create: `fastapi_app/camera_manager.py`

**Step 1: Create camera manager**

Port camera + MediaPipe logic from sync_recorder.py. Processes frames and exposes latest frame + landmarks for WebSocket consumers.

Key responsibilities:
- MJPEG stream reading (reuse MjpegStreamReader pattern)
- MediaPipe pose detection per frame
- Compute vision angles from landmarks
- Expose `get_latest()` returning `{jpeg_bytes, landmarks_33, angles_dict}`
- Thread-safe frame buffer

The camera manager should:
- Import and use `dashboard/core/angles.py:calc_angle` for angle computation
- Import `dashboard/core/vision_angles.py` functions for computing leg deviation, knee extension etc from raw landmark coords per-frame
- Run MediaPipe in a background thread, store latest results
- Provide `get_jpeg_and_data()` method that returns base64 JPEG + landmark array + angles dict

**Step 2: Verify import**

Run: `.venv/bin/python -c "from fastapi_app.camera_manager import CameraManager; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add fastapi_app/camera_manager.py
git commit -m "feat: camera manager with MediaPipe pose detection"
```

---

### Task 4: Recorder Module (CSV/MP4 Writing)

**Files:**
- Create: `fastapi_app/recorder.py`

**Step 1: Create recorder module**

Port recording logic from sync_recorder.py. Manages recording state, CSV writers, video writer.

Key responsibilities:
- `start_recording(set_number)` — create set directory, open CSV writers for all IMU nodes + vision + landmarks
- `stop_recording()` — flush and close all files
- `write_imu(node_name, readings)` — write IMU data rows
- `write_vision(local_ts, frame_count, angle, visible, fps)` — write vision row
- `write_landmarks(local_ts, frame_count, landmarks)` — write landmark row
- `write_video_frame(frame)` — write frame to MP4
- Properties: `recording`, `set_number`, `set_dir`, `elapsed`

Uses same CSV formats as sync_recorder.py for backward compatibility with dashboard/core/data_loader.py.

**Step 2: Verify import**

Run: `.venv/bin/python -c "from fastapi_app.recorder import Recorder; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add fastapi_app/recorder.py
git commit -m "feat: recorder module for CSV/MP4 writing"
```

---

### Task 5: WebSocket Endpoints + REST API

**Files:**
- Create: `fastapi_app/ws_video.py`
- Create: `fastapi_app/ws_metrics.py`
- Create: `fastapi_app/api_routes.py`
- Modify: `fastapi_app/main.py`

**Step 1: Create WebSocket video endpoint**

```python
# fastapi_app/ws_video.py
"""WebSocket endpoint for real-time video + skeleton data."""
import asyncio
import base64
import json

from fastapi import WebSocket, WebSocketDisconnect


async def video_ws(websocket: WebSocket, camera_manager):
    """Push JPEG frames + landmark data to connected clients."""
    await websocket.accept()
    try:
        while True:
            data = camera_manager.get_latest()
            if data and data["jpeg"]:
                frame_b64 = base64.b64encode(data["jpeg"]).decode("utf-8")
                msg = {
                    "frame": f"data:image/jpeg;base64,{frame_b64}",
                    "landmarks": data["landmarks"],
                    "angles": data["angles"],
                }
                await websocket.send_json(msg)
            await asyncio.sleep(0.04)  # ~25fps
    except WebSocketDisconnect:
        pass
```

**Step 2: Create WebSocket metrics endpoint**

```python
# fastapi_app/ws_metrics.py
"""WebSocket endpoint for real-time IMU metrics."""
import asyncio
from fastapi import WebSocket, WebSocketDisconnect


async def metrics_ws(websocket: WebSocket, ble_manager, recorder):
    """Push BLE node status + recording state."""
    await websocket.accept()
    try:
        while True:
            msg = {
                "nodes": ble_manager.get_status(),
                "recording": recorder.recording,
                "set_number": recorder.set_number,
                "elapsed": recorder.elapsed,
            }
            await websocket.send_json(msg)
            await asyncio.sleep(0.2)  # 5Hz
    except WebSocketDisconnect:
        pass
```

**Step 3: Create REST API routes**

```python
# fastapi_app/api_routes.py
"""REST API routes for recording control and analysis."""
from fastapi import APIRouter
from dashboard.core.data_loader import load_or_rebuild_index
from dashboard.core.metrics import compute_all_metrics

router = APIRouter(prefix="/api")

# These will be set by main.py at startup
_ble_manager = None
_camera_manager = None
_recorder = None

def init(ble, camera, recorder):
    global _ble_manager, _camera_manager, _recorder
    _ble_manager = ble
    _camera_manager = camera
    _recorder = recorder

@router.get("/ble/status")
async def ble_status():
    return _ble_manager.get_status()

@router.post("/recording/start")
async def start_recording():
    if _recorder.recording:
        return {"error": "Already recording"}
    _recorder.start_manual()
    return {"status": "recording", "set_number": _recorder.set_number}

@router.post("/recording/stop")
async def stop_recording():
    if not _recorder.recording:
        return {"error": "Not recording"}
    _recorder.stop_recording()
    return {"status": "stopped", "set_dir": _recorder.last_set_dir}

@router.get("/sets")
async def list_sets():
    sessions = load_or_rebuild_index("data")
    return sessions

@router.get("/sets/{name}/report")
async def set_report(name: str):
    set_dir = f"data/{name}"
    report = compute_all_metrics(set_dir)
    if report is None:
        return {"error": "No data"}
    return {
        "overall_score": report.overall_score,
        "metrics": [
            {"name": m.name, "value": round(m.value, 1), "unit": m.unit,
             "deduction": m.deduction, "zone": m.zone}
            for m in report.metrics
        ],
        "phases": report.phases,
        "correlation": report.correlation,
    }

@router.post("/camera/config")
async def camera_config(url: str = "", rotation: int = 0):
    if url:
        _camera_manager.set_url(url)
    if rotation in (0, 90, 180, 270):
        _camera_manager.rotation = rotation
    return {"status": "ok"}
```

**Step 4: Wire everything together in main.py**

Update `fastapi_app/main.py` to:
- Create BleManager, CameraManager, Recorder instances on startup
- Wire BLE callbacks to recorder (master node state changes → start/stop recording, IMU data → write CSV)
- Wire camera callbacks to recorder (vision data + landmarks → write CSV/MP4)
- Mount WebSocket endpoints and API router
- Use `@app.on_event("startup")` to start BLE + camera threads
- Use `@app.on_event("shutdown")` to stop them

**Step 5: Verify server starts with all endpoints**

Run: `.venv/bin/uvicorn fastapi_app.main:app --host 0.0.0.0 --port 8000 &`
Run: `curl -s http://localhost:8000/api/health && curl -s http://localhost:8000/api/sets | head -c 200`
Kill: `pkill -f uvicorn`

**Step 6: Commit**

```bash
git add fastapi_app/
git commit -m "feat: WebSocket video/metrics + REST API routes + main wiring"
```

---

### Task 6: Frontend — Live Monitoring View

**Files:**
- Modify: `fastapi_app/static/index.html`
- Create: `fastapi_app/static/app.js`
- Create: `fastapi_app/static/style.css`

**Step 1: Create index.html**

Single-page app with 3 tab views. Header with nav buttons. Main content area that switches views.

Structure:
```html
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SyncSwim Coach Station</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <header>
        <h1>SyncSwim Coach Station</h1>
        <nav>
            <button class="tab active" data-view="live">实时</button>
            <button class="tab" data-view="analysis">分析</button>
            <button class="tab" data-view="settings">设置</button>
        </nav>
    </header>
    <main>
        <!-- Live View -->
        <div id="view-live" class="view active">
            <div class="live-layout">
                <div class="video-container">
                    <canvas id="video-canvas"></canvas>
                    <div class="controls">
                        <button id="btn-start">开始录制</button>
                        <button id="btn-stop" disabled>停止</button>
                        <button id="btn-rotate">旋转</button>
                    </div>
                </div>
                <div class="side-panel">
                    <div id="ble-status"></div>
                    <div id="live-metrics"></div>
                    <div id="rec-status"></div>
                </div>
            </div>
        </div>
        <!-- Analysis View -->
        <div id="view-analysis" class="view"></div>
        <!-- Settings View -->
        <div id="view-settings" class="view"></div>
    </main>
    <script src="/static/app.js"></script>
</body>
</html>
```

**Step 2: Create app.js**

Core JS functionality:
- Tab switching
- WebSocket connection to `/ws/video` — receive frames, draw on Canvas, draw skeleton overlay
- WebSocket connection to `/ws/metrics` — update BLE status panel, recording status
- Recording control buttons — call `/api/recording/start` and `/api/recording/stop`
- Skeleton rendering: draw 12 connection lines + 33 joint dots + angle labels at key joints
- Color-coded angle values (green < clean threshold, yellow < minor, red >= major)

Key canvas rendering logic:
```javascript
// Draw video frame
const img = new Image();
img.onload = () => {
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    if (landmarks) drawSkeleton(ctx, landmarks, angles);
};
img.src = data.frame;

// Draw skeleton connections
const CONNECTIONS = [
    [11,12],[11,13],[13,15],[12,14],[14,16],
    [11,23],[12,24],[23,24],[23,25],[24,26],
    [25,27],[26,28]
];

function drawSkeleton(ctx, landmarks, angles) {
    // Draw lines
    ctx.strokeStyle = '#00ff00';
    ctx.lineWidth = 2;
    CONNECTIONS.forEach(([i, j]) => {
        if (landmarks[i][2] > 0.3 && landmarks[j][2] > 0.3) {
            ctx.beginPath();
            ctx.moveTo(landmarks[i][0] * canvas.width, landmarks[i][1] * canvas.height);
            ctx.lineTo(landmarks[j][0] * canvas.width, landmarks[j][1] * canvas.height);
            ctx.stroke();
        }
    });
    // Draw angle labels at key joints
    // ...
}
```

**Step 3: Create style.css**

Dark theme, flexbox layout:
- Header: fixed top, dark background
- `.live-layout`: flex row, video 70% width, side panel 30%
- Canvas: maintain aspect ratio, max height viewport
- Side panel: BLE indicators with colored dots, metric values with colored backgrounds
- Controls: large touch-friendly buttons
- Responsive: stack vertically on mobile

**Step 4: Manual verification**

Run: `.venv/bin/uvicorn fastapi_app.main:app --host 0.0.0.0 --port 8000`
Open: `http://localhost:8000`
Verify:
- Video canvas shows live camera feed with skeleton overlay
- BLE status shows node connections
- Start/Stop buttons work
- Angle values update in real-time

**Step 5: Commit**

```bash
git add fastapi_app/static/
git commit -m "feat: frontend live monitoring with Canvas skeleton overlay"
```

---

### Task 7: Frontend — Analysis View

**Files:**
- Modify: `fastapi_app/static/app.js`
- Modify: `fastapi_app/api_routes.py` (add keyframe endpoint)

**Step 1: Add keyframe extraction API**

In `api_routes.py`, add endpoint that extracts 3 keyframes from video.mp4 (at prep/exhibition/recovery phases), overlays skeleton, and returns as JPEG images.

Uses existing `dashboard/core/landmarks.py:extract_frame` and `dashboard/components/skeleton_renderer.py:render_skeleton_frame`.

```python
@router.get("/sets/{name}/keyframes/{index}")
async def get_keyframe(name: str, index: int):
    # Extract frame from video, overlay skeleton, return JPEG
    ...
```

**Step 2: Add analysis view JS**

When switching to analysis tab:
- Fetch `/api/sets` to populate dropdown (default: latest)
- Fetch `/api/sets/{name}/report` for metrics
- Fetch `/api/sets/{name}/keyframes/0,1,2` for keyframe images
- Render: score bar, 3 keyframe images, metric list with zone colors
- Auto-switch to this view when recording stops

**Step 3: Commit**

```bash
git add fastapi_app/
git commit -m "feat: analysis view with keyframes and scoring report"
```

---

### Task 8: Frontend — Settings View + Final Polish

**Files:**
- Modify: `fastapi_app/static/app.js`
- Modify: `fastapi_app/api_routes.py`

**Step 1: Settings view**

- Camera URL input + save button (calls `/api/camera/config`)
- Rotation selector (0/90/180/270)
- BLE device info (read-only display from `/api/ble/status`)
- FINA thresholds display (from config.toml)

**Step 2: Add config read/write API**

```python
@router.get("/api/config")
async def get_config():
    return load_config()

@router.post("/api/config")
async def save_config(config: dict):
    save_config(config)
    return {"status": "saved"}
```

**Step 3: Auto-switch to analysis on recording stop**

In the metrics WebSocket handler in app.js, detect when `recording` transitions from `true` to `false`, automatically switch to analysis view and load the latest set.

**Step 4: Update task.md**

Add Coach Workstation section documenting FastAPI + frontend completion.

**Step 5: Commit and push**

```bash
git add fastapi_app/ task.md
git commit -m "feat: settings view, auto-switch on recording stop, task.md update"
git push origin main
```

---

## Execution Order

```
Task 1 (skeleton) → Task 2 (BLE) → Task 3 (camera) → Task 4 (recorder)
    → Task 5 (API + WebSocket + wiring) → Task 6 (frontend live)
    → Task 7 (frontend analysis) → Task 8 (settings + polish)
```

All sequential — each task depends on the previous.

Parallelizable within tasks:
- Task 2, 3, 4 are independent modules but Task 5 needs all three
- Task 6, 7, 8 are sequential frontend builds
