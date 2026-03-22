"""
Dual-Source Synchronized Recorder - Phase 3
BLE IMU + Vision pipeline in one script.

Button A on device triggers both streams to record/stop simultaneously.
Both data sources use local timestamps for post-hoc alignment.
"""

import asyncio
import csv
import math
import os
import signal
import struct
import sys
import threading
import time
import urllib.request
from datetime import datetime

import cv2
import mediapipe as mp
import numpy as np
from bleak import BleakClient, BleakScanner

# ─── Config ───────────────────────────────────────────────
TARGET_NAME = "NODE_A1"
CHAR_UUID = "abcd1234-ab12-cd34-ef56-abcdef123456"
CAMERA_URL = "http://192.168.66.169:4747/video"
DATA_DIR = "data"

# BLE binary protocol
HEADER_SIZE = 4
READING_SIZE = 16
READING_FMT = '<Ihhhhhh'

# MediaPipe joint config (right elbow)
JOINT_A, JOINT_B, JOINT_C = 12, 14, 16
JOINT_NAME = "R_Elbow"

POSE_CONNECTIONS = [
    (11,12),(11,13),(13,15),(12,14),(14,16),
    (11,23),(12,24),(23,24),(23,25),(24,26),
    (25,27),(26,28)
]

# ─── Shared State ─────────────────────────────────────────
class SyncState:
    def __init__(self):
        self.lock = threading.Lock()
        # BLE
        self.ble_connected = False
        self.ble_rate = 0.0
        self.ble_total_packets = 0
        self.ble_set_packets = 0
        self.ble_lost = 0
        self.last_device_ts = None
        self.last_imu_parts = None
        self._rate_window = []
        # Recording (controlled by device Button A)
        self.recording = False
        self.set_number = 0
        self.set_start_time = None
        self.set_dir = None
        # CSV writers
        self.imu_file = None
        self.imu_writer = None
        self.vision_file = None
        self.vision_writer = None
        self.vision_frame_count = 0
        # Vision
        self.current_angle = 0.0
        self.vision_fps = 0.0
        # Control
        self.running = True
        self.rotation = 0

    def calc_ble_rate(self):
        now = time.time()
        self._rate_window.append(now)
        cutoff = now - 2.0
        self._rate_window = [t for t in self._rate_window if t > cutoff]
        if len(self._rate_window) > 1:
            span = self._rate_window[-1] - self._rate_window[0]
            self.ble_rate = (len(self._rate_window) - 1) / span if span > 0 else 0
        else:
            self.ble_rate = 0.0

state = SyncState()

# ─── CSV Management ───────────────────────────────────────
def start_recording(set_n):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    set_dir = os.path.join(DATA_DIR, f"set_{set_n:03d}_{ts}")
    os.makedirs(set_dir, exist_ok=True)
    state.set_dir = set_dir
    state.set_start_time = time.time()
    state.ble_set_packets = 0
    state.ble_lost = 0
    state.vision_frame_count = 0
    state.last_device_ts = None

    # IMU CSV
    f1 = open(os.path.join(set_dir, f"imu_{TARGET_NAME}.csv"), "w", newline="")
    w1 = csv.writer(f1)
    w1.writerow(["timestamp_local", "timestamp_device", "node", "state", "set",
                 "ax", "ay", "az", "gx", "gy", "gz"])
    state.imu_file = f1
    state.imu_writer = w1

    # Vision CSV
    f2 = open(os.path.join(set_dir, "vision.csv"), "w", newline="")
    w2 = csv.writer(f2)
    w2.writerow(["timestamp_local", "frame", "joint", "angle_deg", "visible", "fps"])
    state.vision_file = f2
    state.vision_writer = w2

def stop_recording():
    for f in [state.imu_file, state.vision_file]:
        if f:
            f.flush()
            f.close()
    state.imu_file = None
    state.imu_writer = None
    state.vision_file = None
    state.vision_writer = None

# ─── BLE Handler ──────────────────────────────────────────
def handle_ble_notification(sender, data):
    if len(data) < HEADER_SIZE:
        return

    dev_state = "REC" if data[0] == 1 else "IDLE"
    set_n = data[1]
    count = data[2]
    local_ts = time.time()

    if len(data) < HEADER_SIZE + count * READING_SIZE:
        return

    with state.lock:
        is_rec = (dev_state == "REC")

        # State transitions
        if is_rec and not state.recording:
            state.recording = True
            state.set_number = set_n
            start_recording(set_n)
        elif not is_rec and state.recording:
            state.recording = False
            stop_recording()

        # Process readings
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

            state.ble_total_packets += 1
            state.calc_ble_rate()

            # Packet loss
            if state.last_device_ts is not None:
                gap = ts - state.last_device_ts
                if gap > 100:
                    state.ble_lost += max(0, int(gap / 12) - 1)
            state.last_device_ts = ts

            # Display data
            state.last_imu_parts = [
                f"{ax:.3f}", f"{ay:.3f}", f"{az:.3f}",
                f"{gx:.1f}", f"{gy:.1f}", f"{gz:.1f}"
            ]

            # Write CSV
            if state.recording and state.imu_writer:
                state.imu_writer.writerow([
                    f"{local_ts:.6f}", ts, TARGET_NAME, dev_state, set_n,
                    f"{ax:.3f}", f"{ay:.3f}", f"{az:.3f}",
                    f"{gx:.1f}", f"{gy:.1f}", f"{gz:.1f}"
                ])
                state.ble_set_packets += 1
                if state.ble_set_packets % 100 == 0:
                    state.imu_file.flush()

# ─── BLE Thread ───────────────────────────────────────────
def ble_thread_func():
    async def ble_loop():
        while state.running:
            try:
                state.ble_connected = False
                devices = await BleakScanner.discover(5.0, return_adv=True)
                target = None
                for addr, (d, adv) in devices.items():
                    if d.name == TARGET_NAME:
                        target = d
                        break

                if not target:
                    await asyncio.sleep(3)
                    continue

                async with BleakClient(target.address) as client:
                    state.ble_connected = True
                    await client.start_notify(CHAR_UUID, handle_ble_notification)
                    while client.is_connected and state.running:
                        await asyncio.sleep(0.25)
                    await client.stop_notify(CHAR_UUID)

            except Exception:
                pass
            finally:
                state.ble_connected = False
                with state.lock:
                    if state.recording:
                        state.recording = False
                        stop_recording()

            if state.running:
                await asyncio.sleep(3)

    asyncio.run(ble_loop())

# ─── MJPEG Stream Reader ─────────────────────────────────
class MjpegStreamReader:
    def __init__(self, url):
        self.url = url
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        self.connected = False
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while self.running:
            try:
                stream = urllib.request.urlopen(self.url, timeout=5)
                self.connected = True
                buf = b""
                while self.running:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    start = buf.find(b"\xff\xd8")
                    end = buf.find(b"\xff\xd9")
                    if start != -1 and end != -1 and end > start:
                        jpg = buf[start:end + 2]
                        buf = buf[end + 2:]
                        arr = np.frombuffer(jpg, dtype=np.uint8)
                        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if frame is not None:
                            with self.lock:
                                self.frame = frame
            except Exception:
                self.connected = False
                time.sleep(1)

    def read(self):
        with self.lock:
            if self.frame is not None:
                return True, self.frame.copy()
            return False, None

    def release(self):
        self.running = False

# ─── Angle Calculation ────────────────────────────────────
def calc_angle(a, b, c):
    ba = np.array([a[0] - b[0], a[1] - b[1]])
    bc = np.array([c[0] - b[0], c[1] - b[1]])
    dot = np.dot(ba, bc)
    mag = np.linalg.norm(ba) * np.linalg.norm(bc)
    if mag == 0:
        return 0.0
    return math.degrees(math.acos(np.clip(dot / mag, -1.0, 1.0)))

# ─── OSD Drawing ──────────────────────────────────────────
def draw_osd(frame):
    h, w = frame.shape[:2]

    # Top bar background
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 60), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    # Line 1: Recording + BLE status
    rec_text = "REC" if state.recording else "IDLE"
    rec_color = (0, 0, 255) if state.recording else (0, 255, 0)
    ble_text = "BLE:ON" if state.ble_connected else "BLE:--"
    ble_color = (0, 255, 0) if state.ble_connected else (0, 0, 255)

    cv2.putText(frame, rec_text, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, rec_color, 2)
    cv2.putText(frame, f"Set#{state.set_number}", (80, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(frame, ble_text, (170, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, ble_color, 1)

    if state.recording and state.set_start_time:
        elapsed = time.time() - state.set_start_time
        mins, secs = int(elapsed) // 60, int(elapsed) % 60
        cv2.putText(frame, f"{mins:02d}:{secs:02d}", (w - 80, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

    # Line 2: Rates + angle
    cv2.putText(frame, f"IMU:{state.ble_rate:.0f}Hz", (10, 48),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    cv2.putText(frame, f"VIS:{state.vision_fps:.0f}fps", (120, 48),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    cv2.putText(frame, f"{JOINT_NAME}:{state.current_angle:.0f}deg", (230, 48),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    cv2.putText(frame, f"Lost:{state.ble_lost}", (w - 90, 48),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

# ─── Main ─────────────────────────────────────────────────
def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print("=== Dual-Source Synchronized Recorder ===")
    print(f"  BLE target: {TARGET_NAME}")
    print(f"  Camera: {CAMERA_URL}")
    print()

    # Start BLE thread
    print("Starting BLE thread...")
    ble_t = threading.Thread(target=ble_thread_func, daemon=True)
    ble_t.start()

    # Start camera
    print("Connecting to camera...")
    cam = MjpegStreamReader(CAMERA_URL)
    for _ in range(50):
        if cam.connected:
            ret, _ = cam.read()
            if ret:
                break
        time.sleep(0.1)

    if not cam.connected:
        print("ERROR: Cannot connect to camera.")
        state.running = False
        return

    print("Camera connected!")

    # MediaPipe setup
    from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode
    from mediapipe.tasks.python import BaseOptions

    model_path = os.path.join(os.path.dirname(__file__) or ".", "pose_landmarker_lite.task")
    options = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.IMAGE,
        min_pose_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    landmarker = PoseLandmarker.create_from_options(options)

    print()
    print("Controls:")
    print("  Button A on device = Start/stop BOTH streams")
    print("  F = Rotate video")
    print("  Q = Quit")
    print()

    frame_count = 0
    fps_counter = 0
    fps_timer = time.time()

    try:
        while state.running:
            ret, frame = cam.read()
            if not ret:
                time.sleep(0.01)
                continue

            # Rotation
            if state.rotation == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif state.rotation == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif state.rotation == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)

            frame_count += 1
            local_ts = time.time()

            # FPS
            fps_counter += 1
            if local_ts - fps_timer >= 1.0:
                state.vision_fps = fps_counter / (local_ts - fps_timer)
                fps_counter = 0
                fps_timer = local_ts

            # MediaPipe
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            results = landmarker.detect(mp_image)

            angle = 0.0
            visible = False
            h, w = frame.shape[:2]

            if results.pose_landmarks and len(results.pose_landmarks) > 0:
                lm = results.pose_landmarks[0]

                vis_a = lm[JOINT_A].visibility
                vis_b = lm[JOINT_B].visibility
                vis_c = lm[JOINT_C].visibility

                if vis_a > 0.5 and vis_b > 0.5 and vis_c > 0.5:
                    visible = True
                    a = (lm[JOINT_A].x * w, lm[JOINT_A].y * h)
                    b = (lm[JOINT_B].x * w, lm[JOINT_B].y * h)
                    c = (lm[JOINT_C].x * w, lm[JOINT_C].y * h)
                    angle = calc_angle(a, b, c)
                    state.current_angle = angle

                    # Draw angle at joint
                    bpx = (int(b[0]), int(b[1]))
                    cv2.circle(frame, bpx, 6, (0, 255, 255), -1)
                    cv2.putText(frame, f"{angle:.0f}",
                                (bpx[0] + 12, bpx[1] - 12),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                # Draw skeleton
                for i, l in enumerate(lm):
                    if l.visibility > 0.5:
                        cv2.circle(frame, (int(l.x * w), int(l.y * h)), 3, (0, 255, 0), -1)
                for c1, c2 in POSE_CONNECTIONS:
                    if lm[c1].visibility > 0.3 and lm[c2].visibility > 0.3:
                        p1 = (int(lm[c1].x * w), int(lm[c1].y * h))
                        p2 = (int(lm[c2].x * w), int(lm[c2].y * h))
                        cv2.line(frame, p1, p2, (255, 255, 255), 2)

            # OSD
            draw_osd(frame)

            # Write vision CSV
            with state.lock:
                if state.recording and state.vision_writer:
                    state.vision_writer.writerow([
                        f"{local_ts:.6f}", frame_count, JOINT_NAME,
                        f"{angle:.2f}", 1 if visible else 0,
                        f"{state.vision_fps:.1f}"
                    ])
                    state.vision_frame_count += 1
                    if state.vision_frame_count % 30 == 0:
                        state.vision_file.flush()

            cv2.imshow("Sync Recorder", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('f'):
                state.rotation = (state.rotation + 90) % 360

    except KeyboardInterrupt:
        pass
    finally:
        state.running = False
        with state.lock:
            if state.recording:
                state.recording = False
                stop_recording()
        landmarker.close()
        cam.release()
        cv2.destroyAllWindows()

        print(f"\n{'='*50}")
        print(f"Session Summary")
        print(f"  BLE packets: {state.ble_total_packets}")
        print(f"  Sets recorded: {state.set_number}")
        if state.set_dir:
            print(f"  Last set: {state.set_dir}/")
        print(f"{'='*50}")

if __name__ == "__main__":
    main()
