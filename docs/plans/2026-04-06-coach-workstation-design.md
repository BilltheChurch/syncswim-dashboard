# Coach Workstation — Design Document

**Date**: 2026-04-06
**Status**: Approved
**Approach**: FastAPI + Custom Frontend (Plan C)
**Previous UI**: Streamlit (kept but no longer primary)

## Problem

The current Streamlit dashboard requires:
1. Manually running sync_recorder.py in a separate terminal
2. Manually selecting recorded datasets after each recording
3. Abstract gauge/radar charts that don't give coaches intuitive feedback

Coaches need a single-window workstation: press a button to start, see live video with skeleton overlay, auto-generate analysis when recording stops.

## Architecture

### Single-Process Backend (FastAPI)

```
fastapi_app/
├── main.py              # FastAPI entry, mount routes + static files
├── ble_manager.py       # Dual-node BLE connection (reuse sync_recorder logic)
├── camera_manager.py    # Camera + MediaPipe processing
├── recorder.py          # Recording state (CSV/MP4/landmarks write)
├── ws_video.py          # WebSocket /ws/video — push frame + skeleton data
├── ws_metrics.py        # WebSocket /ws/metrics — push real-time metrics
├── api_routes.py        # REST API routes
└── static/              # Frontend HTML/JS/CSS
    ├── index.html
    ├── app.js
    └── style.css
```

### Core Logic Reuse

These modules are imported directly, no rewrite needed:

- `dashboard/core/scoring.py` — 8-metric scoring engine
- `dashboard/core/vision_angles.py` — vision angle calculations
- `dashboard/core/analysis.py` — IMU signal analysis
- `dashboard/core/data_loader.py` — CSV data loading
- `dashboard/core/phase_detect.py` — phase detection
- `dashboard/core/angles.py` — joint angle math
- `dashboard/core/landmarks.py` — landmark utilities
- `dashboard/config.py` — config load/save
- `config.toml` — FINA thresholds + hardware config

### API Design

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ws/video` | WebSocket | Real-time: JPEG frame + 33-point skeleton coords + angles |
| `/ws/metrics` | WebSocket | Real-time: IMU rates, angles, connection status |
| `/api/ble/status` | GET | Node connection status |
| `/api/recording/start` | POST | Start recording |
| `/api/recording/stop` | POST | Stop recording |
| `/api/sets` | GET | List all recorded datasets |
| `/api/sets/{name}/report` | GET | 8-metric analysis report JSON |
| `/api/sets/{name}/keyframes` | GET | Key frame images (JPEG) |
| `/api/camera/config` | POST | Camera URL, rotation |

### WebSocket Message Formats

```javascript
// /ws/video — per frame (~25fps)
{
  "frame": "data:image/jpeg;base64,...",
  "landmarks": [[x, y, vis], ...],  // 33 points, normalized
  "angles": {
    "leg_deviation": 8.2,
    "knee_extension": 174,
    "elbow": 142
  }
}

// /ws/metrics — every 200ms
{
  "nodes": {
    "NODE_A1": {"connected": true, "rate": 72.1, "tilt": 45.2},
    "NODE_A2": {"connected": true, "rate": 71.8, "tilt": 88.5}
  },
  "recording": true,
  "set_number": 3,
  "elapsed": 23.4
}
```

## Frontend Design

### Single-page app, 3 views:

**Header:** `SyncSwim Coach Station  [实时] [分析] [设置]`

### View 1: Live Monitoring

```
┌─────────────────────────────┬──────────────────┐
│                             │  BLE Status       │
│   Live Video (Canvas)       │  A1: ● 72Hz forearm│
│   Skeleton lines drawn      │  A2: ● 71Hz shin  │
│   by frontend JS            │                   │
│   Angle numbers at joints   │  Live Metrics     │
│                             │  Leg vertical: 8.2°│
│                             │  Knee ext: 172°   │
│                             │  Trunk: 3.1°      │
├─────────────────────────────┤                   │
│  [Start] [Stop] [Rotate]    │  ● REC 00:23      │
└─────────────────────────────┴──────────────────┘
```

- Video area is main content, Canvas rendering
- Skeleton drawn on Canvas by frontend (backend pushes 33 landmark coords)
- Right panel: BLE status + 3-4 key angles with green/yellow/red color
- Bottom: recording control buttons
- When recording stops, auto-switch to analysis view

### View 2: Post-Recording Analysis

```
┌──────────────────────────────────────────────────┐
│  Dataset: [set_003_20260406 ▼]  (auto-load latest)│
├──────────────────────────────────────────────────┤
│  Score: 8.2/10  ■■■■■■■■□□                       │
│                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Keyframe 1│ │ Keyframe 2│ │ Keyframe 3│        │
│  │ Prep      │ │ Exhibition│ │ Recovery  │        │
│  │ skeleton  │ │ skeleton  │ │ skeleton  │        │
│  │ overlay   │ │ + std ref │ │           │        │
│  └──────────┘ └──────────┘ └──────────┘          │
│                                                  │
│  Metrics:                                        │
│  Leg deviation   5.2°  ✅ Clean                   │
│  Knee extension  174°  ✅ Clean                   │
│  Shoulder-knee   168°  ⚠️ Minor                  │
│  Leg symmetry    12°   ❌ Major                   │
│  Trunk vertical  3.1°  ✅ Clean                   │
│  Smoothness      2.4   ✅ Clean                   │
│  Stability       1.8°  ✅ Clean                   │
└──────────────────────────────────────────────────┘
```

- Auto-loads latest recorded dataset
- Keyframe images: extracted from video.mp4, skeleton overlay + standard pose comparison
- Metrics as simple number + color + text, no gauges
- Future: multi-set comparison, trend charts

### View 3: Settings

- Camera URL, rotation
- BLE device names and UUIDs
- FINA thresholds per metric

### Frontend Skeleton Rendering

Skeleton drawn on frontend Canvas, not baked into video:
- Backend pushes 33 normalized landmark coordinates
- Frontend JS draws connection lines + angle annotations at key joints
- Benefits: interactive (hover for details), good performance, flexible layout

## Data Flow

```
Camera (MJPEG) → camera_manager → MediaPipe
                                   ├→ WebSocket /ws/video: {jpeg, landmarks, angles}
                                   └→ When recording: video.mp4 + landmarks.csv + vision.csv

M5StickC A1 ──BLE→ ble_manager ──→ WebSocket /ws/metrics
M5StickC A2 ──BLE→ ble_manager     When recording: imu_NODE_A1.csv, imu_NODE_A2.csv
```

## Migration Strategy

### Phase 1: FastAPI backend + minimal frontend (live video + skeleton + recording)
- Port BLE/MediaPipe/recording logic from sync_recorder.py to FastAPI modules
- Simplest HTML/JS, get data flow working first

### Phase 2: Analysis view (keyframes + scoring report)
- Reuse scoring.py, vision_angles.py
- Backend API returns JSON, frontend renders

### Phase 3: UI polish + team sync
- Multi-person skeleton overlay/split-screen
- Responsive layout, dark theme
- DTW synchronization visualization

### What stays
- Streamlit dashboard kept but not primary UI
- All `dashboard/core/` modules reused via import
- All tests still pass
- config.toml unchanged

## Dependencies to Add

```
fastapi
uvicorn[standard]
python-multipart
websockets
```
