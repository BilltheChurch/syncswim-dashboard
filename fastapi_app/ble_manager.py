"""BLE Manager — dual BLE connection manager for Coach Workstation.

Manages connections to M5StickC Plus2 IMU nodes (NODE_A1 forearm,
NODE_A2 shin) and exposes parsed IMU data via callbacks.

Ported from sync_recorder.py into a reusable class for the FastAPI backend.
"""

import asyncio
import math
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner

from dashboard.config import load_config

# BLE binary protocol constants
HEADER_SIZE = 4
READING_SIZE = 16
READING_FMT = "<Ihhhhhh"


@dataclass
class NodeState:
    """Per-node BLE connection and telemetry state."""

    name: str
    connected: bool = False
    rate: float = 0.0
    total_packets: int = 0
    set_packets: int = 0
    lost: int = 0
    last_device_ts: Optional[int] = None
    last_imu: Optional[dict] = None
    tilt: float = 0.0
    _rate_window: list = field(default_factory=list, repr=False)

    def calc_rate(self) -> None:
        """Update packet rate using a 2-second sliding window."""
        now = time.time()
        self._rate_window.append(now)
        cutoff = now - 2.0
        self._rate_window = [t for t in self._rate_window if t > cutoff]
        if len(self._rate_window) > 1:
            span = self._rate_window[-1] - self._rate_window[0]
            self.rate = (len(self._rate_window) - 1) / span if span > 0 else 0.0
        else:
            self.rate = 0.0


class BleManager:
    """Manages dual BLE connections to M5StickC Plus2 IMU nodes.

    Args:
        on_imu_data: Callback(node_name, local_ts, readings_list) for each
            BLE notification.  Each reading in readings_list is a dict with
            keys: device_ts, ax, ay, az, gx, gy, gz.
        on_state_change: Callback(dev_state, set_n) when the master node
            reports a recording-state transition ("REC" / "IDLE").
    """

    def __init__(
        self,
        on_imu_data: Optional[Callable] = None,
        on_state_change: Optional[Callable] = None,
    ) -> None:
        cfg = load_config()
        hw = cfg.get("hardware", {})

        self.node_names: list[str] = hw.get("imu_nodes", ["NODE_A1", "NODE_A2"])
        self.master_node: str = self.node_names[0]
        self.char_uuid: str = hw.get(
            "ble_char_uuid", "abcd1234-ab12-cd34-ef56-abcdef123456"
        )

        self.on_imu_data = on_imu_data
        self.on_state_change = on_state_change

        self.nodes: dict[str, NodeState] = {
            name: NodeState(name=name) for name in self.node_names
        }
        self.lock = threading.Lock()
        self.running = False
        self._threads: list[threading.Thread] = []

    # ── public API ────────────────────────────────────────────

    def start(self) -> None:
        """Launch one daemon thread per BLE node."""
        self.running = True
        for name in self.node_names:
            t = threading.Thread(
                target=self._node_thread, args=(name,), daemon=True
            )
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        """Signal all node threads to stop."""
        self.running = False

    def get_status(self) -> dict:
        """Return a snapshot of every node's status.

        Returns:
            {node_name: {connected, rate, tilt, packets, lost}, ...}
        """
        with self.lock:
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

    # ── internal ──────────────────────────────────────────────

    def _make_handler(self, node_name: str):
        """Create a BLE notification handler for *node_name*.

        The handler parses the binary protocol, updates NodeState, and
        invokes the on_imu_data / on_state_change callbacks.
        """

        def handle_notification(_sender, data: bytearray) -> None:
            if len(data) < HEADER_SIZE:
                return

            dev_state = "REC" if data[0] == 1 else "IDLE"
            set_n = data[1]
            count = data[2]
            local_ts = time.time()

            if len(data) < HEADER_SIZE + count * READING_SIZE:
                return

            node = self.nodes[node_name]
            readings: list[dict] = []

            with self.lock:
                # Master node drives recording state transitions
                # Only fire callback on actual state CHANGE (not every packet)
                if node_name == self.master_node and self.on_state_change:
                    if not hasattr(node, '_last_dev_state') or node._last_dev_state != dev_state:
                        node._last_dev_state = dev_state
                        self.on_state_change(dev_state, set_n)

                for i in range(count):
                    offset = HEADER_SIZE + i * READING_SIZE
                    ts, ax_i, ay_i, az_i, gx_i, gy_i, gz_i = struct.unpack_from(
                        READING_FMT, data, offset
                    )
                    ax = ax_i / 1000.0
                    ay = ay_i / 1000.0
                    az = az_i / 1000.0
                    gx = gx_i / 10.0
                    gy = gy_i / 10.0
                    gz = gz_i / 10.0

                    node.total_packets += 1
                    node.calc_rate()

                    # Packet-loss detection
                    if node.last_device_ts is not None:
                        gap = ts - node.last_device_ts
                        if gap > 100:
                            node.lost += max(0, int(gap / 12) - 1)
                    node.last_device_ts = ts

                    # Tilt from accelerometer
                    node.tilt = math.degrees(
                        math.atan2(ax, math.sqrt(ay**2 + az**2))
                    )

                    node.last_imu = {
                        "device_ts": ts,
                        "ax": ax,
                        "ay": ay,
                        "az": az,
                        "gx": gx,
                        "gy": gy,
                        "gz": gz,
                    }

                    readings.append(
                        {
                            "device_ts": ts,
                            "ax": ax,
                            "ay": ay,
                            "az": az,
                            "gx": gx,
                            "gy": gy,
                            "gz": gz,
                        }
                    )

            if readings and self.on_imu_data:
                self.on_imu_data(node_name, local_ts, readings)

        return handle_notification

    def _node_thread(self, node_name: str) -> None:
        """Run the async scan-connect-subscribe loop for one node."""
        handler = self._make_handler(node_name)
        node = self.nodes[node_name]

        async def _loop() -> None:
            while self.running:
                try:
                    node.connected = False
                    devices = await BleakScanner.discover(5.0, return_adv=True)
                    target = None
                    for _addr, (d, _adv) in devices.items():
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

        asyncio.run(_loop())
