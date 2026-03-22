"""
NODE_A1 BLE Recorder - Phase 1
Single device BLE IMU data collection pipeline.

Features:
- BLE data reception at ~86Hz
- Auto-segmentation by REC/IDLE state
- Per-set CSV files with timestamps
- Terminal dashboard with live stats
- Auto-reconnect on disconnect
- Packet loss detection
"""

import asyncio
import csv
import os
import signal
import struct
import sys
import time
import threading
from datetime import datetime
from bleak import BleakClient, BleakScanner

# ─── Config ───────────────────────────────────────────────
TARGET_NAME = "NODE_A1"
CHAR_UUID = "abcd1234-ab12-cd34-ef56-abcdef123456"
DATA_DIR = "data"
EXPECTED_INTERVAL_MS = 12   # ~86Hz
LOSS_THRESHOLD_MS = 100     # Only flag real drops
DISPLAY_REFRESH_HZ = 4      # terminal refresh rate
RECONNECT_DELAY_S = 3
# Binary protocol: 4-byte header + N × 16-byte readings
HEADER_SIZE = 4
READING_SIZE = 16           # uint32 + 6 × int16 (packed)
READING_FMT = '<Ihhhhhh'   # little-endian: uint32 + 6 × int16

# ─── Shared State ─────────────────────────────────────────
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.connected = False
        self.recording = False
        self.set_number = 0
        self.set_start_time = None
        self.set_packet_count = 0
        self.total_packets = 0
        self.lost_packets = 0
        self.set_lost = 0
        self.last_device_ts = None
        self.current_rate = 0.0
        self.last_data_parts = None
        self.csv_writer = None
        self.csv_file = None
        self.set_dir = None
        self.set_filepath = None
        self.running = True
        # Rate calculation
        self._rate_window = []

    def calc_rate(self):
        """Calculate packets/sec from sliding window."""
        now = time.time()
        self._rate_window.append(now)
        # Keep last 2 seconds of timestamps
        cutoff = now - 2.0
        self._rate_window = [t for t in self._rate_window if t > cutoff]
        if len(self._rate_window) > 1:
            span = self._rate_window[-1] - self._rate_window[0]
            if span > 0:
                self.current_rate = (len(self._rate_window) - 1) / span
            else:
                self.current_rate = 0.0
        else:
            self.current_rate = 0.0

state = State()

# ─── CSV Management ───────────────────────────────────────
def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def start_csv(set_number):
    """Open a new CSV file for this recording set."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    set_dir = os.path.join(DATA_DIR, f"set_{set_number:03d}_{timestamp}")
    os.makedirs(set_dir, exist_ok=True)
    filepath = os.path.join(set_dir, f"imu_{TARGET_NAME}.csv")
    f = open(filepath, "w", newline="")
    writer = csv.writer(f)
    writer.writerow([
        "timestamp_local", "timestamp_device", "node", "state", "set",
        "ax", "ay", "az", "gx", "gy", "gz"
    ])
    state.csv_file = f
    state.csv_writer = writer
    state.set_dir = set_dir
    state.set_filepath = filepath
    state.set_packet_count = 0
    state.set_lost = 0
    state.last_device_ts = None
    return filepath

def stop_csv():
    """Close current CSV file and print summary."""
    if state.csv_file:
        state.csv_file.flush()
        state.csv_file.close()
        state.csv_file = None
        writer = state.csv_writer
        state.csv_writer = None
        if state.set_filepath:
            size = os.path.getsize(state.set_filepath)
            return state.set_filepath, state.set_packet_count, size
    return None, 0, 0

# ─── Terminal Display ─────────────────────────────────────
# ANSI escape codes
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"
CLEAR_SCREEN = "\033[2J"
HOME = "\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_LINE = "\033[K"

def render_display():
    """Render terminal dashboard (flicker-free via HOME cursor reset)."""
    lines = []

    # Header
    lines.append(f"{BOLD}{'═' * 58}{RESET}")
    lines.append(f"{BOLD}  {TARGET_NAME} Recorder{RESET}")
    lines.append(f"{'═' * 58}")

    # Connection
    if state.connected:
        conn = f"{GREEN}{BOLD}CONNECTED{RESET}"
    else:
        conn = f"{RED}{BOLD}DISCONNECTED{RESET}"
    lines.append(f"  Connection : {conn}")

    # Recording state
    if state.recording:
        rec = f"{RED}{BOLD}● REC{RESET}"
        elapsed = time.time() - (state.set_start_time or time.time())
        mins, secs = int(elapsed) // 60, int(elapsed) % 60
        duration = f"{mins:02d}:{secs:02d}"
    else:
        rec = f"{GREEN}■ IDLE{RESET}"
        duration = "--:--"
    lines.append(f"  State      : {rec}  │  Set: #{state.set_number}  │  Duration: {duration}")

    # Stats
    rate_color = GREEN if state.current_rate > 70 else (YELLOW if state.current_rate > 30 else RED)
    if not state.connected:
        rate_color = DIM
    lines.append(
        f"  Rate       : {rate_color}{state.current_rate:5.0f} Hz{RESET}  │  "
        f"Packets: {state.set_packet_count}  │  "
        f"Lost: {state.set_lost}"
    )

    lines.append(f"{'─' * 58}")

    # Latest IMU data
    if state.last_data_parts:
        p = state.last_data_parts
        lines.append(
            f"  {CYAN}ACCEL{RESET}  X:{p[4]:>8}  Y:{p[5]:>8}  Z:{p[6]:>8}  g"
        )
        lines.append(
            f"  {YELLOW}GYRO {RESET}  X:{p[7]:>8}  Y:{p[8]:>8}  Z:{p[9]:>8}  d/s"
        )
    else:
        lines.append(f"  {DIM}Waiting for data...{RESET}")
        lines.append("")

    lines.append(f"{'═' * 58}")

    # Save info
    if state.recording and state.set_dir:
        lines.append(f"  {DIM}Saving to: {state.set_dir}/{RESET}")
    elif not state.recording and state.set_number > 0:
        lines.append(f"  {DIM}Last set saved. Press Button A on device for next set.{RESET}")
    else:
        lines.append(f"  {DIM}Press Button A on device to start recording.{RESET}")

    lines.append(f"  {DIM}Ctrl+C to quit{RESET}")
    lines.append("")

    # Write all at once for flicker-free update, CLEAR_LINE prevents ghost chars
    sys.stdout.write(HOME + (CLEAR_LINE + "\n").join(lines) + "\033[J")
    sys.stdout.flush()

# ─── BLE Data Handler ─────────────────────────────────────
def handle_notification(sender, data):
    """BLE notification callback - parses binary batch packets."""
    if len(data) < HEADER_SIZE:
        return

    # Parse header: [state, set_number, count, reserved]
    dev_state = "REC" if data[0] == 1 else "IDLE"
    set_n = data[1]
    count = data[2]
    local_ts = time.time()

    if len(data) < HEADER_SIZE + count * READING_SIZE:
        return

    with state.lock:
        is_rec = (dev_state == "REC")

        # ── State transition: IDLE → REC ──
        if is_rec and not state.recording:
            state.recording = True
            state.set_number = set_n
            state.set_start_time = time.time()
            start_csv(set_n)

        # ── State transition: REC → IDLE ──
        elif not is_rec and state.recording:
            state.recording = False
            stop_csv()

        # ── Process each reading in the batch ──
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

            state.total_packets += 1
            state.calc_rate()

            # Packet loss detection
            if state.last_device_ts is not None:
                gap = ts - state.last_device_ts
                if gap > LOSS_THRESHOLD_MS:
                    estimated_lost = max(0, int(gap / EXPECTED_INTERVAL_MS) - 1)
                    state.lost_packets += estimated_lost
                    state.set_lost += estimated_lost
            state.last_device_ts = ts

            # Update display data
            state.last_data_parts = [
                TARGET_NAME, dev_state, str(set_n), str(ts),
                f"{ax:.3f}", f"{ay:.3f}", f"{az:.3f}",
                f"{gx:.1f}", f"{gy:.1f}", f"{gz:.1f}"
            ]

            # Write CSV row if recording
            if state.recording and state.csv_writer:
                state.csv_writer.writerow([
                    f"{local_ts:.6f}", ts, TARGET_NAME, dev_state, set_n,
                    f"{ax:.3f}", f"{ay:.3f}", f"{az:.3f}",
                    f"{gx:.1f}", f"{gy:.1f}", f"{gz:.1f}"
                ])
                state.set_packet_count += 1

        # Flush periodically
        if state.recording and state.csv_file and state.set_packet_count % 100 < count:
            state.csv_file.flush()

# ─── Status Message ───────────────────────────────────────
_status_msg = "Initializing..."

def set_status(msg):
    global _status_msg
    _status_msg = msg

def render_with_status():
    """Render display + status message at bottom."""
    render_display()
    sys.stdout.write(f"\n  {DIM}{_status_msg}{RESET}\033[J\n")
    sys.stdout.flush()

# ─── Main Connection Loop ─────────────────────────────────
async def connect_loop():
    """Scan, connect, receive. Auto-reconnect on failure."""
    while state.running:
        try:
            # Scan phase - show display while scanning
            state.connected = False
            set_status(f"Scanning for {TARGET_NAME}...")
            render_with_status()

            devices = await BleakScanner.discover(5.0, return_adv=True)
            target = None
            for addr, (d, adv) in devices.items():
                if d.name == TARGET_NAME:
                    target = d
                    break

            if not target:
                set_status(f"{TARGET_NAME} not found. Retrying in {RECONNECT_DELAY_S}s...")
                render_with_status()
                await asyncio.sleep(RECONNECT_DELAY_S)
                continue

            # Connect phase
            set_status(f"Found {TARGET_NAME} at {target.address}, connecting...")
            render_with_status()

            async with BleakClient(target.address) as client:
                state.connected = True
                set_status("Connected. Waiting for data...")
                await client.start_notify(CHAR_UUID, handle_notification)

                # Stay connected, refresh display
                while client.is_connected and state.running:
                    set_status("Streaming live data.")
                    render_with_status()
                    await asyncio.sleep(1.0 / DISPLAY_REFRESH_HZ)

                await client.stop_notify(CHAR_UUID)

        except Exception as e:
            set_status(f"Error: {e}")
            render_with_status()
        finally:
            state.connected = False
            # If was recording when disconnected, close CSV
            with state.lock:
                if state.recording:
                    state.recording = False
                    stop_csv()

        if state.running:
            set_status(f"Connection lost. Reconnecting in {RECONNECT_DELAY_S}s...")
            render_with_status()
            await asyncio.sleep(RECONNECT_DELAY_S)

async def main():
    ensure_data_dir()
    sys.stdout.write(HIDE_CURSOR + CLEAR_SCREEN)
    sys.stdout.flush()

    # Graceful shutdown: Ctrl+C sets flag, loop exits cleanly
    loop = asyncio.get_event_loop()
    def _signal_handler():
        state.running = False
    loop.add_signal_handler(signal.SIGINT, _signal_handler)

    await connect_loop()

    # Cleanup
    with state.lock:
        stop_csv()
    sys.stdout.write(SHOW_CURSOR + "\n")
    sys.stdout.flush()

    # Final summary
    print(f"\n{BOLD}Session Summary{RESET}")
    print(f"  Total packets received: {state.total_packets}")
    print(f"  Total packets lost:     {state.lost_packets}")
    print(f"  Sets recorded:          {state.set_number}")
    if state.set_number > 0:
        print(f"  Data saved in:          {DATA_DIR}/")
    print()

if __name__ == "__main__":
    asyncio.run(main())
