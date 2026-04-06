"""WebSocket endpoint for real-time IMU metrics."""
import asyncio

from fastapi import WebSocket, WebSocketDisconnect


async def metrics_ws(websocket: WebSocket, ble_manager, recorder):
    """Push BLE node status + recording state at 5Hz."""
    await websocket.accept()
    try:
        while True:
            msg = {
                "nodes": ble_manager.get_status(),
                "recording": recorder.recording,
                "set_number": recorder.set_number,
                "elapsed": round(recorder.elapsed, 1),
            }
            await websocket.send_json(msg)
            await asyncio.sleep(0.2)
    except (WebSocketDisconnect, Exception):
        pass
