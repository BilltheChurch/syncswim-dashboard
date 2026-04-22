"""
Recorder module for Coach Workstation FastAPI backend.
Manages recording state and writes CSV/MP4 files.

Ported from sync_recorder.py into a reusable class.
"""

import csv
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime

import cv2

# ---- Landmark names (33 MediaPipe pose landmarks) ----
LANDMARK_NAMES = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]

IMU_NODES = ["NODE_A1", "NODE_A2"]

IMU_HEADER = [
    "timestamp_local", "timestamp_device", "node", "state", "set",
    "ax", "ay", "az", "gx", "gy", "gz",
]

VISION_HEADER = [
    "timestamp_local", "frame", "joint", "angle_deg", "visible", "fps",
]


def _landmark_csv_header():
    """Build the header row for landmarks.csv."""
    header = ["timestamp_local", "frame"]
    for name in LANDMARK_NAMES:
        header.extend([f"{name}_x", f"{name}_y", f"{name}_z", f"{name}_vis"])
    return header


class Recorder:
    """Thread-safe recording manager for IMU CSV, vision CSV, landmarks CSV, and MP4 video."""

    def __init__(self, data_dir="data"):
        self._data_dir = data_dir
        self._lock = threading.Lock()

        # Recording state
        self._recording = False
        self._set_number = 0
        self._set_dir = None
        self._last_set_dir = None
        self._start_time = None

        # Per-node IMU writers: {node_name: (file, csv.writer)}
        self._imu_files = {}
        self._imu_writers = {}
        self._imu_row_counts = {}

        # Vision CSV
        self._vision_file = None
        self._vision_writer = None
        self._vision_frame_count = 0

        # Landmarks CSV
        self._landmarks_file = None
        self._landmarks_writer = None

        # Multi-person landmarks (JSONL: one line per video frame,
        # captures every detected person — needed so the analysis
        # page can replay team routines with a per-person skeleton).
        self._landmarks_multi_file = None

        # Video
        self._video_writer = None
        self._video_writer_pending = False

        os.makedirs(self._data_dir, exist_ok=True)

    # ---- Properties ----

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def set_number(self) -> int:
        return self._set_number

    @property
    def set_dir(self):
        return self._set_dir

    @property
    def last_set_dir(self):
        return self._last_set_dir

    @property
    def elapsed(self) -> float:
        if self._recording and self._start_time is not None:
            return time.time() - self._start_time
        return 0.0

    # ---- Recording lifecycle ----

    def start_recording(self, set_number: int):
        """Start a new recording set with the given set number."""
        with self._lock:
            if self._recording:
                return
            self._set_number = set_number
            self._recording = True
            self._start_time = time.time()
            self._vision_frame_count = 0

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            set_dir = os.path.join(self._data_dir, f"set_{set_number:03d}_{ts}")
            os.makedirs(set_dir, exist_ok=True)
            self._set_dir = set_dir
            print(f"[recorder] start set_{set_number:03d} → {set_dir}")

            # Per-node IMU CSVs
            for node_name in IMU_NODES:
                f = open(os.path.join(set_dir, f"imu_{node_name}.csv"), "w", newline="")
                w = csv.writer(f)
                w.writerow(IMU_HEADER)
                self._imu_files[node_name] = f
                self._imu_writers[node_name] = w
                self._imu_row_counts[node_name] = 0

            # Vision CSV
            f2 = open(os.path.join(set_dir, "vision.csv"), "w", newline="")
            w2 = csv.writer(f2)
            w2.writerow(VISION_HEADER)
            self._vision_file = f2
            self._vision_writer = w2

            # Landmarks CSV
            f3 = open(os.path.join(set_dir, "landmarks.csv"), "w", newline="")
            w3 = csv.writer(f3)
            w3.writerow(_landmark_csv_header())
            self._landmarks_file = f3
            self._landmarks_writer = w3

            # Multi-person landmarks — JSONL, one line per written
            # video frame. Kept strictly 1:1 with video frames so the
            # analysis page can map video.currentTime → exact frame
            # index without drift (see DEVLOG #13).
            self._landmarks_multi_file = open(
                os.path.join(set_dir, "landmarks_multi.jsonl"), "w"
            )

            # Video writer will be initialized on first frame
            self._video_writer_pending = True

    def start_manual(self):
        """Start recording from the dashboard button, auto-incrementing set number."""
        next_set = self._scan_next_set_number()
        self.start_recording(next_set)

    def stop_recording(self):
        """Flush and close all CSV files and the video writer."""
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            self._last_set_dir = self._set_dir
            set_dir_to_transcode = self._set_dir   # snapshot for the async worker

            # Close per-node IMU files
            for node_name in list(self._imu_files.keys()):
                f = self._imu_files.pop(node_name, None)
                if f:
                    f.flush()
                    f.close()
            self._imu_writers.clear()
            self._imu_row_counts.clear()

            # Close vision CSV
            if self._vision_file:
                self._vision_file.flush()
                self._vision_file.close()
            self._vision_file = None
            self._vision_writer = None

            # Close landmarks CSV
            if self._landmarks_file:
                self._landmarks_file.flush()
                self._landmarks_file.close()
            self._landmarks_file = None
            self._landmarks_writer = None

            # Close multi-person landmarks JSONL
            if self._landmarks_multi_file:
                self._landmarks_multi_file.flush()
                self._landmarks_multi_file.close()
            self._landmarks_multi_file = None

            # Release video writer
            if self._video_writer:
                self._video_writer.release()
                self._video_writer = None
            self._video_writer_pending = False

            self._start_time = None

        # Kick off background H.264 transcode OUTSIDE the lock so the
        # HTTP /recording/stop response returns immediately. HTML5
        # <video> in Chrome/Safari struggles with OpenCV's mp4v codec
        # even though cv2.VideoCapture reads it fine. Re-encoding to
        # H.264 with faststart makes every browser able to play and
        # seek the recording.
        if set_dir_to_transcode:
            self._transcode_to_h264_async(set_dir_to_transcode)

    def _transcode_to_h264_async(self, set_dir: str) -> None:
        """Fire-and-forget: spawn a daemon thread that re-encodes
        ``video.mp4`` from mp4v → H.264 (libx264). On success,
        atomically replaces the original file; on failure keeps the
        mp4v file so the recording is never lost.
        """
        src = os.path.join(set_dir, "video.mp4")
        if not os.path.exists(src):
            return
        tmp = os.path.join(set_dir, "video.h264.tmp.mp4")

        def _worker():
            try:
                result = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", src,
                        "-c:v", "libx264",
                        "-preset", "veryfast",
                        "-crf", "23",
                        "-pix_fmt", "yuv420p",       # max browser compat
                        "-movflags", "+faststart",   # moov atom at head
                        "-loglevel", "error",
                        tmp,
                    ],
                    capture_output=True, timeout=600,
                )
                ok = (
                    result.returncode == 0
                    and os.path.exists(tmp)
                    and os.path.getsize(tmp) > 1024
                )
                if ok:
                    os.replace(tmp, src)
                    print(f"[recorder] transcoded to H.264: {src} "
                          f"({os.path.getsize(src) / 1024 / 1024:.1f} MB)")
                else:
                    err = result.stderr.decode(errors="ignore")[:200]
                    print(f"[recorder] transcode failed (rc={result.returncode}): {err}")
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            except FileNotFoundError:
                print("[recorder] ffmpeg not found — skipping H.264 transcode; "
                      "browser may have trouble playing mp4v files")
            except Exception as e:
                print(f"[recorder] transcode error: {e}")
                try:
                    os.remove(tmp)
                except OSError:
                    pass

        threading.Thread(target=_worker, daemon=True, name="transcode").start()

    # ---- Write methods ----

    def write_imu(self, node_name: str, readings_list: list):
        """Write IMU rows for a specific node.

        Each reading is a dict with keys:
            local_ts, ts, node, state, set, ax, ay, az, gx, gy, gz
        """
        with self._lock:
            if not self._recording:
                return
            writer = self._imu_writers.get(node_name)
            imu_file = self._imu_files.get(node_name)
            if writer is None or imu_file is None:
                return
            for r in readings_list:
                writer.writerow([
                    f"{r['local_ts']:.6f}",
                    r["ts"],
                    r["node"],
                    r["state"],
                    r["set"],
                    f"{r['ax']:.3f}",
                    f"{r['ay']:.3f}",
                    f"{r['az']:.3f}",
                    f"{r['gx']:.1f}",
                    f"{r['gy']:.1f}",
                    f"{r['gz']:.1f}",
                ])
                self._imu_row_counts[node_name] = self._imu_row_counts.get(node_name, 0) + 1
                if self._imu_row_counts[node_name] % 100 == 0:
                    imu_file.flush()

    def write_vision(self, local_ts: float, frame_count: int, joint_name: str,
                     angle: float, visible: bool, fps: float):
        """Write one row to vision.csv."""
        with self._lock:
            if not self._recording or self._vision_writer is None:
                return
            self._vision_writer.writerow([
                f"{local_ts:.6f}",
                frame_count,
                joint_name,
                f"{angle:.2f}",
                1 if visible else 0,
                f"{fps:.1f}",
            ])
            self._vision_frame_count += 1
            if self._vision_frame_count % 30 == 0:
                self._vision_file.flush()

    def write_landmarks(self, local_ts: float, frame_count: int, landmarks_list: list):
        """Write one row to landmarks.csv.

        landmarks_list: 33 items, each with x, y, z, visibility.
        """
        with self._lock:
            if not self._recording or self._landmarks_writer is None:
                return
            row = [f"{local_ts:.6f}", frame_count]
            if landmarks_list and len(landmarks_list) == 33:
                for lm in landmarks_list:
                    row.extend([
                        f"{lm['x']:.6f}",
                        f"{lm['y']:.6f}",
                        f"{lm['z']:.6f}",
                        f"{lm['visibility']:.4f}",
                    ])
            else:
                # No pose detected -- fill with zeros
                row.extend([0.0] * (33 * 4))
            self._landmarks_writer.writerow(row)
            # Flush at same cadence as vision
            if self._vision_frame_count % 30 == 0:
                self._landmarks_file.flush()

    def write_landmarks_multi(self, local_ts: float, frame_count: int,
                              all_landmarks: list):
        """Write one JSONL row per video frame with every detected person.

        ``all_landmarks`` is a list of up to N persons; each person is a
        list of 33 ``[x, y, visibility]`` triples (normalized coords).
        Empty list is fine — we always write a row so the file stays
        1:1 with ``video.mp4`` frames (see DEVLOG #13 sync fix).
        """
        with self._lock:
            if not self._recording or self._landmarks_multi_file is None:
                return
            persons = []
            for lm in (all_landmarks or []):
                if not lm or len(lm) != 33:
                    continue
                persons.append([
                    [round(float(p[0]), 4), round(float(p[1]), 4),
                     round(float(p[2]), 3)]
                    for p in lm
                ])
            row = {"ts": round(float(local_ts), 3),
                   "frame": int(frame_count),
                   "persons": persons}
            self._landmarks_multi_file.write(json.dumps(row, separators=(",", ":")) + "\n")
            if self._vision_frame_count % 30 == 0:
                self._landmarks_multi_file.flush()

    def write_video_frame(self, frame):
        """Write a BGR numpy frame to video.mp4.

        Initializes VideoWriter on first frame using frame dimensions.
        Codec: **mp4v** (pure-software MPEG-4 encoder). We explicitly
        avoid ``avc1`` / H.264 because on Apple Silicon the H.264
        hardware path goes through Metal, and when YOLO is already
        using MPS (Metal Performance Shaders) the two contend for the
        same GPU context — recording a frame can block for seconds,
        which stalls the vision writer and freezes the whole pipeline.
        ``mp4v`` runs on CPU and is rock-solid.
        """
        with self._lock:
            if not self._recording:
                return
            # Initialize on first frame
            if self._video_writer_pending and self._set_dir:
                video_path = os.path.join(self._set_dir, "video.mp4")
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                h, w = frame.shape[:2]
                self._video_writer = cv2.VideoWriter(video_path, fourcc, 25.0, (w, h))
                opened = self._video_writer.isOpened() if self._video_writer else False
                print(f"[recorder] video writer init: {video_path} {w}x{h} "
                      f"fourcc=mp4v opened={opened}")
                self._video_writer_pending = False

            if self._video_writer:
                self._video_writer.write(frame)

    # ---- Internal helpers ----

    def _scan_next_set_number(self) -> int:
        """Scan existing set directories to determine the next set number."""
        pattern = re.compile(r"^set_(\d{3})_")
        max_n = 0
        if os.path.isdir(self._data_dir):
            for name in os.listdir(self._data_dir):
                m = pattern.match(name)
                if m:
                    n = int(m.group(1))
                    if n > max_n:
                        max_n = n
        return max_n + 1
