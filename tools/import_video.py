"""Import an existing recorded video as a synthetic Set.

Use case:
  - Coach has historical training footage on disk
  - Wants to feed it through the dashboard pipeline (analysis,
    cross-Set comparison, athlete naming, PDF export, ...) WITHOUT
    re-shooting with the live recorder
  - End result: a ``data/set_NNN_imported_<stem>_<ts>/`` directory
    that looks identical to a live recording — minus the IMU CSVs
    (which stay header-only so analysis falls back to vision-only)

Pipeline (mirrors live recording exactly so downstream code paths
are byte-identical):
  1. Read source video frame by frame
  2. Run yolo_pose detector + ByteTracker (same code as live)
  3. Write video.mp4, then transcode to H.264 + faststart
  4. Write vision.csv  — primary person's elbow angle, one row per frame
  5. Write landmarks.csv  — 33 keypoints per frame (zeros if no detection),
                            kept 1:1 with video frames (DEVLOG #13)
  6. Write landmarks_multi.jsonl  — every detected person + ByteTracker IDs
  7. Touch header-only IMU CSVs so the duration fallback chain works

After import the Set is indistinguishable from a live recording
on the analysis page, history view, athlete-naming modal, cross-Set
comparison tab, etc.

Example:
    python tools/import_video.py path/to/training.mp4
    python tools/import_video.py path/to/portrait.mov --rotate 90
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import cv2

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

# Reuse exactly the same code as the live recorder so the imported
# data passes through identical column orderings, angle formulas,
# and visibility thresholds. Downstream analysis is then guaranteed
# byte-identical for live vs imported sets.
from fastapi_app.camera_manager import _compute_angles  # noqa: E402
from fastapi_app.recorder import (  # noqa: E402
    IMU_HEADER, LANDMARK_NAMES, VISION_HEADER,
)

DEFAULT_DATA_DIR = _ROOT / "data"
DEFAULT_MODEL = str(_ROOT / "yolov8s-pose.pt")


def _next_set_number(data_dir: Path) -> int:
    """Same scan logic as ``Recorder._scan_next_set_number`` so
    imported sets share a single counter with live ones — coach
    sees a continuous numbering in the history page."""
    pattern = re.compile(r"^set_(\d{3})_")
    max_n = 0
    if data_dir.is_dir():
        for entry in data_dir.iterdir():
            m = pattern.match(entry.name)
            if m:
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
    return max_n + 1


def _safe_stem(stem: str) -> str:
    """Sanitize a filename stem for use in a directory name."""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem.strip())
    return s[:24] or "video"


def _landmark_csv_header() -> list[str]:
    h = ["timestamp_local", "frame"]
    for name in LANDMARK_NAMES:
        h.extend([f"{name}_x", f"{name}_y", f"{name}_z", f"{name}_vis"])
    return h


def _transcode_to_h264(src: Path) -> bool:
    """Re-encode src .mp4 to H.264 + faststart in place.

    Mirrors ``Recorder._transcode_to_h264_async`` semantics: failure
    keeps the original mp4v file (browser playback may struggle but
    the recording isn't lost). ffmpeg missing → warning, no crash.
    """
    tmp = src.with_suffix(".h264.tmp.mp4")
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(src),
                "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", "-loglevel", "error",
                str(tmp),
            ],
            capture_output=True, timeout=600,
        )
    except FileNotFoundError:
        print("[warn] ffmpeg not installed — keeping mp4v video "
              "(browser playback may struggle)")
        return False
    except subprocess.TimeoutExpired:
        print("[warn] ffmpeg transcode timed out (>10min); "
              "keeping source codec")
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 1024:
        os.replace(tmp, src)
        return True
    err = result.stderr.decode(errors="ignore")[:200]
    print(f"[warn] ffmpeg transcode failed (rc={result.returncode}): {err}")
    try:
        tmp.unlink()
    except OSError:
        pass
    return False


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("video", type=Path,
                        help="Source video file (mp4/mov/avi/mkv)")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help="Where to create the set directory (default: data/)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="YOLOv8-pose weights for inference")
    parser.add_argument("--conf", type=float, default=0.35,
                        help="Detection confidence threshold")
    parser.add_argument("--device", default="mps",
                        help="Inference device: mps / cuda / cpu")
    parser.add_argument("--max-persons", type=int, default=8)
    parser.add_argument(
        "--rotate", type=int, choices=[0, 90, 180, 270], default=0,
        help="Rotate frames clockwise (use 90 for portrait phone footage)",
    )
    args = parser.parse_args()

    src = args.video
    if not src.exists():
        print(f"[error] video not found: {src}")
        sys.exit(1)

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        print(f"[error] cannot open: {src}")
        sys.exit(1)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    src_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Allocate a set directory in the shared numbering space
    set_n = _next_set_number(args.data_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = _safe_stem(src.stem)
    set_dir = args.data_dir / f"set_{set_n:03d}_imported_{stem}_{ts}"
    set_dir.mkdir(parents=True)
    print(f"[+] set dir: {set_dir}")
    print(f"    source: {src.name} ({src_frame_count} frames @ {src_fps:.1f} fps)")

    # Lazy-import the detector so `--help` works without ultralytics
    from fastapi_app.yolo_pose import YoloPoseDetector
    det = YoloPoseDetector(
        model_path=args.model, conf=args.conf,
        max_persons=args.max_persons, device=args.device,
    )
    # Reset BYTETracker state — same reason live recording does it
    # at every start_recording (see DEVLOG #25). Without this, IDs
    # leak across runs of this importer.
    det.reset_tracking()

    video_out_path = set_dir / "video.mp4"
    video_writer = None

    vision_f = open(set_dir / "vision.csv", "w", newline="")
    vision_w = csv.writer(vision_f)
    vision_w.writerow(VISION_HEADER)

    lm_f = open(set_dir / "landmarks.csv", "w", newline="")
    lm_w = csv.writer(lm_f)
    lm_w.writerow(_landmark_csv_header())

    multi_f = open(set_dir / "landmarks_multi.jsonl", "w")

    # Empty IMU CSVs (header only) — duration fallback (DEVLOG #13)
    # walks IMU → vision → landmarks → video, so an imported video
    # without IMU still gets a sensible duration value.
    for node in ("NODE_A1", "NODE_A2"):
        with open(set_dir / f"imu_{node}.csv", "w", newline="") as f:
            csv.writer(f).writerow(IMU_HEADER)

    rot_map = {
        90: cv2.ROTATE_90_CLOCKWISE,
        180: cv2.ROTATE_180,
        270: cv2.ROTATE_90_COUNTERCLOCKWISE,
    }

    frame_idx = 0
    persons_total = 0
    base_ts = 0.0   # synthetic; analysis duration falls back to vision.csv
    ts_step = 1.0 / max(1.0, src_fps)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if args.rotate:
                frame = cv2.rotate(frame, rot_map[args.rotate])
            h, w = frame.shape[:2]

            # Init video writer on first frame (need W/H from the frame
            # itself rather than CAP_PROP — the latter lies for some
            # rotated containers).
            if video_writer is None:
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                video_writer = cv2.VideoWriter(
                    str(video_out_path), fourcc, src_fps, (w, h)
                )
            video_writer.write(frame)

            persons, track_ids = det.detect(frame, w, h)
            local_ts = base_ts + frame_idx * ts_step
            frame_no = frame_idx + 1   # 1-based for parity with live recorder

            # Primary person → vision.csv (elbow angle) + landmarks.csv
            primary_lm = persons[0] if persons else []
            if primary_lm:
                angles = _compute_angles(primary_lm, w, h)
                elbow = float(angles.get("elbow", 0.0))
                visible = "elbow" in angles
            else:
                elbow, visible = 0.0, False

            vision_w.writerow([
                f"{local_ts:.6f}", frame_no, "R_Elbow",
                f"{elbow:.2f}", 1 if visible else 0, f"{src_fps:.1f}",
            ])

            # landmarks.csv — 1:1 with video frames; zeros when no
            # detection (DEVLOG #13: analysis page maps video time →
            # landmark idx by ratio, so the two files MUST stay aligned
            # row-for-row even on no-pose frames).
            lm_row: list = [f"{local_ts:.6f}", frame_no]
            if primary_lm:
                for lm in primary_lm:
                    lm_row.extend([
                        f"{lm.x:.6f}", f"{lm.y:.6f}",
                        "0.0", f"{lm.visibility:.4f}",
                    ])
            else:
                lm_row.extend([0.0] * (33 * 4))
            lm_w.writerow(lm_row)

            # landmarks_multi.jsonl — all persons + track_ids
            persons_payload = []
            kept_idx: list[int] = []
            for orig_idx, lm_list in enumerate(persons):
                if not lm_list or len(lm_list) != 33:
                    continue
                persons_payload.append([
                    [round(lm.x, 4), round(lm.y, 4),
                     round(lm.visibility, 3)]
                    for lm in lm_list
                ])
                kept_idx.append(orig_idx)
            ids = [
                (int(track_ids[i])
                 if (i < len(track_ids) and track_ids[i] is not None)
                 else None)
                for i in kept_idx
            ]
            multi_f.write(json.dumps({
                "ts": round(local_ts, 3),
                "frame": frame_no,
                "persons": persons_payload,
                "ids": ids,
            }, separators=(",", ":")) + "\n")
            persons_total += len(persons_payload)

            frame_idx += 1
            if frame_idx % 50 == 0:
                pct = frame_idx * 100.0 / max(1, src_frame_count)
                print(f"  {frame_idx}/{src_frame_count} frames ({pct:.0f}%)")
    finally:
        cap.release()
        if video_writer:
            video_writer.release()
        vision_f.close()
        lm_f.close()
        multi_f.close()

    print(f"\n[+] transcoding {video_out_path.name} to H.264...")
    _transcode_to_h264(video_out_path)

    print(f"\n[done] imported {frame_idx} frames into {set_dir.name}")
    print(f"       persons across all frames: {persons_total}")
    print(f"       open dashboard → 历史 / 分析 / 对比 to inspect")


if __name__ == "__main__":
    main()
