"""
Vision Pipeline - Phase 2
IP camera + MediaPipe skeleton + joint angle extraction.

Features:
- DroidCam HTTP stream via OpenCV
- MediaPipe Pose landmark detection
- Real-time elbow angle calculation
- Skeleton overlay with angle display
- Per-frame angle data saved to CSV
"""

import csv
import math
import os
import sys
import time
import urllib.request
import threading
from datetime import datetime

import cv2
import mediapipe as mp
import numpy as np

# ─── Config ───────────────────────────────────────────────
CAMERA_URL = "http://192.168.66.169:4747/video"
DATA_DIR = "data"
WINDOW_NAME = "Vision Pipeline"

# MediaPipe Pose landmarks for elbow angle
# Right arm: shoulder(12) -> elbow(14) -> wrist(16)
# Left arm:  shoulder(11) -> elbow(13) -> wrist(15)
# Right leg: hip(24) -> knee(26) -> ankle(28)
# Left leg:  hip(23) -> knee(25) -> ankle(27)

# We'll track RIGHT ELBOW by default
JOINT_A = 12  # right shoulder
JOINT_B = 14  # right elbow (vertex)
JOINT_C = 16  # right wrist
JOINT_NAME = "R_Elbow"

# ─── MJPEG Stream Reader (bypass OpenCV HTTP issue) ───────
class MjpegStreamReader:
    """Manually parse MJPEG stream from DroidCam since OpenCV's
    FFmpeg on macOS ARM can't handle HTTP video capture."""

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
                    # Find JPEG boundaries
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

    def isOpened(self):
        return self.connected

    def release(self):
        self.running = False

# ─── Angle Calculation ────────────────────────────────────
def calc_angle(a, b, c):
    """Calculate angle at point b given three (x,y) points."""
    ba = np.array([a[0] - b[0], a[1] - b[1]])
    bc = np.array([c[0] - b[0], c[1] - b[1]])

    dot = np.dot(ba, bc)
    mag_ba = np.linalg.norm(ba)
    mag_bc = np.linalg.norm(bc)

    if mag_ba == 0 or mag_bc == 0:
        return 0.0

    cos_angle = np.clip(dot / (mag_ba * mag_bc), -1.0, 1.0)
    angle = math.degrees(math.acos(cos_angle))
    return angle

# ─── Drawing Helpers ──────────────────────────────────────
def draw_angle_arc(frame, center, angle, radius=40):
    """Draw angle arc and value near the joint."""
    color = (0, 255, 255)  # cyan
    cv2.putText(frame, f"{angle:.0f} deg",
                (center[0] + 15, center[1] - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    # Small filled circle at joint
    cv2.circle(frame, center, 6, color, -1)

def draw_status_bar(frame, fps, frame_count, recording, angle):
    """Draw status bar at top of frame."""
    h, w = frame.shape[:2]
    # Semi-transparent bar
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 36), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    # Status text
    status = "REC" if recording else "PREVIEW"
    status_color = (0, 0, 255) if recording else (0, 255, 0)
    cv2.putText(frame, status, (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
    cv2.putText(frame, f"FPS:{fps:.0f}", (110, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    cv2.putText(frame, f"{JOINT_NAME}:{angle:.0f}deg", (220, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)
    cv2.putText(frame, f"F:{frame_count}", (w - 120, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)

# ─── Main ─────────────────────────────────────────────────
def main():
    print(f"Connecting to camera at {CAMERA_URL}...")
    cap = MjpegStreamReader(CAMERA_URL)

    # Wait for first frame
    for _ in range(50):  # 5 seconds max
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                break
        time.sleep(0.1)

    if not cap.isOpened():
        print("ERROR: Cannot connect to camera.")
        print("  - Is DroidCam running on the phone?")
        print("  - Are phone and Mac on the same WiFi?")
        print(f"  - Check URL: {CAMERA_URL}")
        cap.release()
        return

    print("Camera connected!")
    print("Controls:")
    print("  R  = Start/stop recording")
    print("  F  = Rotate video (0/90/180/270)")
    print("  Q  = Quit")
    print()

    # MediaPipe Pose Landmarker (new tasks API)
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

    # State
    rotation = 0  # 0, 90, 180, 270 degrees
    recording = False
    csv_file = None
    csv_writer = None
    set_number = 0
    frame_count = 0
    rec_frame_count = 0
    fps = 0.0
    fps_timer = time.time()
    fps_counter = 0
    current_angle = 0.0

    os.makedirs(DATA_DIR, exist_ok=True)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Frame grab failed, reconnecting...")
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(CAMERA_URL)
                continue

            # Apply rotation
            if rotation == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif rotation == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif rotation == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)

            frame_count += 1
            local_ts = time.time()

            # FPS calculation
            fps_counter += 1
            elapsed = local_ts - fps_timer
            if elapsed >= 1.0:
                fps = fps_counter / elapsed
                fps_counter = 0
                fps_timer = local_ts

            # MediaPipe pose detection (tasks API)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            results = landmarker.detect(mp_image)

            angle = 0.0
            joint_px = (0, 0)
            landmarks_visible = False
            h, w = frame.shape[:2]

            if results.pose_landmarks and len(results.pose_landmarks) > 0:
                lm = results.pose_landmarks[0]  # first person

                # Check visibility of target joints
                vis_a = lm[JOINT_A].visibility
                vis_b = lm[JOINT_B].visibility
                vis_c = lm[JOINT_C].visibility

                if vis_a > 0.5 and vis_b > 0.5 and vis_c > 0.5:
                    landmarks_visible = True

                    a = (lm[JOINT_A].x * w, lm[JOINT_A].y * h)
                    b = (lm[JOINT_B].x * w, lm[JOINT_B].y * h)
                    c = (lm[JOINT_C].x * w, lm[JOINT_C].y * h)

                    angle = calc_angle(a, b, c)
                    current_angle = angle
                    joint_px = (int(b[0]), int(b[1]))

                # Draw skeleton connections manually
                POSE_CONNECTIONS = [
                    (11,12),(11,13),(13,15),(12,14),(14,16),
                    (11,23),(12,24),(23,24),(23,25),(24,26),
                    (25,27),(26,28)
                ]
                for i, l in enumerate(lm):
                    px = int(l.x * w)
                    py = int(l.y * h)
                    if l.visibility > 0.5:
                        cv2.circle(frame, (px, py), 3, (0, 255, 0), -1)
                for c1, c2 in POSE_CONNECTIONS:
                    if lm[c1].visibility > 0.3 and lm[c2].visibility > 0.3:
                        p1 = (int(lm[c1].x * w), int(lm[c1].y * h))
                        p2 = (int(lm[c2].x * w), int(lm[c2].y * h))
                        cv2.line(frame, p1, p2, (255, 255, 255), 2)

                # Highlight target joint and draw angle
                if landmarks_visible:
                    draw_angle_arc(frame, joint_px, angle)

            # Status bar
            draw_status_bar(frame, fps, frame_count, recording, current_angle)

            # Record to CSV
            if recording and csv_writer:
                csv_writer.writerow([
                    f"{local_ts:.6f}",
                    frame_count,
                    JOINT_NAME,
                    f"{angle:.2f}",
                    1 if landmarks_visible else 0,
                    f"{fps:.1f}"
                ])
                rec_frame_count += 1
                # Flush periodically
                if rec_frame_count % 30 == 0:
                    csv_file.flush()

            # Show frame
            cv2.imshow(WINDOW_NAME, frame)

            # Key handling
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('f'):
                rotation = (rotation + 90) % 360
                print(f"  Rotation: {rotation} deg")
            elif key == ord('r'):
                if not recording:
                    # Start recording
                    set_number += 1
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    set_dir = os.path.join(DATA_DIR, f"set_{set_number:03d}_{timestamp}")
                    os.makedirs(set_dir, exist_ok=True)
                    filepath = os.path.join(set_dir, "vision.csv")
                    csv_file = open(filepath, "w", newline="")
                    csv_writer = csv.writer(csv_file)
                    csv_writer.writerow([
                        "timestamp_local", "frame", "joint",
                        "angle_deg", "visible", "fps"
                    ])
                    rec_frame_count = 0
                    recording = True
                    print(f"  Recording started -> {set_dir}/")
                else:
                    # Stop recording
                    recording = False
                    if csv_file:
                        csv_file.close()
                        csv_file = None
                        csv_writer = None
                    print(f"  Recording stopped. {rec_frame_count} frames saved.")

    except KeyboardInterrupt:
        pass
    finally:
        # Cleanup
        if csv_file:
            csv_file.close()
        landmarker.close()
        cap.release()
        cv2.destroyAllWindows()

        print(f"\nVision pipeline stopped.")
        print(f"  Total frames: {frame_count}")
        print(f"  Sets recorded: {set_number}")

if __name__ == "__main__":
    main()
