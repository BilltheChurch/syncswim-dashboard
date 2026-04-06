"""WebSocket endpoint for real-time video + skeleton data."""
import asyncio
import base64

from fastapi import WebSocket, WebSocketDisconnect


async def video_ws(websocket: WebSocket, camera_manager):
    """Push JPEG frames + landmark data to connected clients at ~25fps."""
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
    except (WebSocketDisconnect, Exception):
        pass
