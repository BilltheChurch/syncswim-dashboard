"""WebSocket endpoint for real-time video + skeleton data."""
import asyncio
import base64

from fastapi import WebSocket, WebSocketDisconnect


async def video_ws(websocket: WebSocket, camera_manager):
    """Push JPEG frames + pose landmarks for up to N persons.

    Critical: each send is wrapped in ``asyncio.wait_for`` with a 1-s
    timeout. Without this, if the browser freezes (e.g. dev-tools open
    + heavy Canvas rendering backlog), the TCP send-buffer fills up,
    ``websocket.send_json`` blocks forever, and the whole uvicorn
    asyncio loop wedges — Ctrl+C stops responding, no other HTTP
    request gets served. Dropping frames is always the right answer
    here; the user sees "slightly stuttery live preview" instead of
    "entire dashboard frozen".
    """
    await websocket.accept()
    dropped = 0
    try:
        while True:
            data = camera_manager.get_latest()
            if data and data["jpeg"]:
                frame_b64 = base64.b64encode(data["jpeg"]).decode("utf-8")
                # ``track_ids`` is the parallel BYTETracker ID stream
                # (phase 7.1) — same length as ``all_landmarks``, each
                # entry an int (stable across frames) or null. The
                # client uses it to bind a per-athlete colour and to
                # show ``#3``-style labels so the coach can verify ID
                # stability live before relying on it for downstream
                # bindings (athlete-name mapping, cross-Set comparison).
                msg = {
                    "frame": f"data:image/jpeg;base64,{frame_b64}",
                    "landmarks": data.get("landmarks") or [],
                    "all_landmarks": data.get("all_landmarks") or [],
                    "all_angles": data.get("all_angles") or [],
                    "track_ids": data.get("track_ids") or [],
                    "person_count": data.get("person_count", 0),
                    "angles": data.get("angles"),
                }
                try:
                    await asyncio.wait_for(websocket.send_json(msg), timeout=1.0)
                    dropped = 0
                except asyncio.TimeoutError:
                    dropped += 1
                    # 5 consecutive 1-s timeouts = browser is dead. Close
                    # so uvicorn can release the connection and let the
                    # client reconnect from scratch.
                    if dropped >= 5:
                        break
                    continue
            # ~15 fps — cuts browser-side Canvas workload nearly in half
            # vs the previous 25 fps (40 ms), which relieves the slow
            # consumers that were causing the wedge.
            await asyncio.sleep(0.067)
    except (WebSocketDisconnect, Exception):
        pass
