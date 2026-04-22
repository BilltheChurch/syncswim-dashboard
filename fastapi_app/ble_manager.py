"""BLE Manager — dual BLE connection manager for Coach Workstation.

Manages connections to M5StickC Plus2 IMU nodes (NODE_A1 forearm,
NODE_A2 shin) and exposes parsed IMU data via callbacks.

Ported from sync_recorder.py into a reusable class for the FastAPI backend.
"""

import asyncio
import atexit
import logging
import math
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner

from dashboard.config import load_config

# Log BLE events to stderr so they appear in uvicorn's terminal output.
# Makes "why didn't it reconnect?" diagnosable without a debugger.
log = logging.getLogger("ble_manager")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [BLE %(levelname)s] %(message)s",
                                      datefmt="%H:%M:%S"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)

# BLE binary protocol constants
HEADER_SIZE = 4
READING_SIZE = 16
READING_FMT = "<Ihhhhhh"

# Characteristic the server writes the authoritative set number to.
# Firmware displays this value on the M5 screen (see test_rec.ino,
# MySetnumCallbacks). Lets the coach see the same number that's being
# stored on disk, even after M5 power-cycles (which reset M5's own
# local setNumber counter).
SETNUM_CHAR_UUID = "abcd5678-ab12-cd34-ef56-abcdef123456"


@dataclass
class NodeState:
    """Per-node BLE connection and telemetry state."""

    name: str
    connected: bool = False
    # "scanning" | "connected" | "waiting" | "stopped" — surfaced to the
    # frontend via /api/ble/status so the dashboard can show what each
    # node is actually doing right now.
    phase: str = "scanning"
    scan_attempts: int = 0
    rate: float = 0.0
    total_packets: int = 0
    set_packets: int = 0
    lost: int = 0
    last_device_ts: Optional[int] = None
    last_imu: Optional[dict] = None
    tilt: float = 0.0
    # Set to True by the /api/ble/reconnect endpoint to force the
    # node's asyncio loop to drop the current client and rescan.
    force_reconnect: bool = False
    # Pending set-number write. Set by BleManager.write_set_number();
    # the node's asyncio loop consumes it on its next tick by writing
    # to SETNUM_CHAR_UUID so the M5's display shows the authoritative
    # server-assigned number.
    pending_set_number: Optional[int] = None
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
        """Launch one daemon thread per BLE node.

        Registers an atexit hook that signals stop() — this runs even
        when FastAPI's own shutdown event doesn't fire (e.g., SIGKILL
        or uncaught exception at module-import time). With this, every
        clean-ish exit lets the BLE thread disconnect properly so the
        firmware's onDisconnect callback fires and advertising resumes
        immediately (see DEVLOG #5).
        """
        self.running = True
        for name in self.node_names:
            t = threading.Thread(
                target=self._node_thread, args=(name,), daemon=True
            )
            t.start()
            self._threads.append(t)
        atexit.register(self._atexit_cleanup)
        log.info("started — %d nodes: %s", len(self.node_names), self.node_names)

    def _atexit_cleanup(self) -> None:
        """Last-ditch cleanup if no other code called stop()."""
        if self.running:
            log.info("atexit: forcing BLE disconnect")
            try:
                self.stop(grace=3.0)
            except Exception as e:
                log.warning("atexit: stop failed: %s", e)

    def stop(self, grace: float = 4.0) -> None:
        """Signal all node threads to stop.

        Waits up to *grace* seconds so each node's asyncio loop can
        drop out of ``async with BleakClient`` cleanly and send a
        proper BLE disconnect.  Without this the firmware thinks the
        link is still alive and refuses new connections until its
        supervision timeout fires (~30 s).
        """
        self.running = False
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=grace)
        self._threads.clear()

    def write_set_number(self, n: int) -> None:
        """Queue a server-assigned set number for every connected node.

        The node's asyncio loop picks this up on its next tick and
        writes to SETNUM_CHAR_UUID. The firmware's BLE callback sets
        its ``displayedSetNumber`` so the M5 screen shows what the
        server actually saved on disk — not the M5's local counter.
        """
        n_clamped = max(0, min(255, int(n)))
        with self.lock:
            for node in self.nodes.values():
                node.pending_set_number = n_clamped

    def get_status(self) -> dict:
        """Return a snapshot of every node's status.

        ``phase`` tells the dashboard what the node's loop is doing
        right now: "scanning", "connected", "waiting", "stopped".
        """
        with self.lock:
            return {
                name: {
                    "connected": node.connected,
                    "phase": node.phase,
                    "scan_attempts": node.scan_attempts,
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
                # Master node drives recording state transitions.
                # Two-step gate:
                #   1. On the very first packet after connect, we DON'T
                #      fire — we just remember the state. Otherwise a
                #      device that reconnects while still in REC would
                #      cause us to auto-start a recording the user
                #      never asked for.
                #   2. After that, fire only on actual state changes.
                if node_name == self.master_node and self.on_state_change:
                    if not hasattr(node, '_last_dev_state'):
                        node._last_dev_state = dev_state  # baseline, no fire
                    elif node._last_dev_state != dev_state:
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
        """Run the async scan-connect-subscribe loop for one node.

        Every state transition is logged to stderr so restart / reconnect
        bugs can be diagnosed from the uvicorn terminal output.

        Key timing constants (important for recovery after an unclean
        shutdown, see DEVLOG #5 and #16):

        * Initial scan is **6s** — long enough to catch an M5 that's
          still inside its BLE supervision-timeout window (~6-20s)
          after a prior process was killed.
        * Every scan is **5s** — shorter rounds trip up bleak on macOS.
        * Backoff between failed scans is 1s → 5s max.
        * Keeps trying forever (no give-up) because the M5 will
          eventually re-advertise once supervision-timeout fires.
        """
        handler = self._make_handler(node_name)
        node = self.nodes[node_name]

        async def _loop() -> None:
            backoff = 1.0
            first_scan = True
            while self.running:
                try:
                    node.connected = False
                    node.phase = "scanning"
                    node.scan_attempts += 1
                    scan_time = 6.0 if first_scan else 5.0
                    first_scan = False
                    log.info(
                        "[%s] scan #%d (%.1fs)...", node_name, node.scan_attempts, scan_time,
                    )
                    devices = await BleakScanner.discover(scan_time, return_adv=True)
                    target = None
                    for _addr, (d, _adv) in devices.items():
                        if d.name == node_name:
                            target = d
                            break

                    if not target:
                        log.warning(
                            "[%s] not advertising yet — retry in %.1fs "
                            "(M5 BLE supervision timeout can last up to 20s "
                            "after an unclean shutdown)",
                            node_name, min(backoff, 5.0),
                        )
                        node.phase = "waiting"
                        await asyncio.sleep(min(backoff, 5.0))
                        backoff = min(backoff * 1.5, 5.0)
                        continue
                    backoff = 1.0
                    log.info("[%s] found %s — connecting", node_name, target.address)

                    async with BleakClient(target.address) as client:
                        node.connected = True
                        node.phase = "connected"
                        node.force_reconnect = False
                        log.info("[%s] connected ✓", node_name)
                        await client.start_notify(self.char_uuid, handler)
                        while (
                            client.is_connected
                            and self.running
                            and not node.force_reconnect
                        ):
                            # Flush any pending set-number write so the
                            # firmware's display matches the server.
                            if node.pending_set_number is not None:
                                try:
                                    await client.write_gatt_char(
                                        SETNUM_CHAR_UUID,
                                        bytes([node.pending_set_number]),
                                        response=False,
                                    )
                                    log.info("[%s] set_number written: %d",
                                             node_name, node.pending_set_number)
                                    node.pending_set_number = None
                                except Exception as e:
                                    log.warning("[%s] set_number write failed: %s",
                                                node_name, e)
                                    node.pending_set_number = None
                            await asyncio.sleep(0.2)
                        log.info(
                            "[%s] disconnecting (running=%s, force_reconnect=%s)",
                            node_name, self.running, node.force_reconnect,
                        )
                        try:
                            await client.stop_notify(self.char_uuid)
                        except Exception as e:
                            log.warning("[%s] stop_notify failed: %s", node_name, e)
                        if client.is_connected:
                            try:
                                await client.disconnect()
                            except Exception as e:
                                log.warning("[%s] disconnect failed: %s", node_name, e)
                    log.info("[%s] disconnected ✓", node_name)

                except Exception as e:
                    log.warning("[%s] loop error: %s: %s", node_name, type(e).__name__, e)
                finally:
                    node.connected = False

                if self.running:
                    node.phase = "waiting"
                    await asyncio.sleep(1.0)
            node.phase = "stopped"
            log.info("[%s] loop exited", node_name)

        try:
            asyncio.run(_loop())
        except Exception as e:
            log.error("[%s] fatal loop crash: %s", node_name, e)
