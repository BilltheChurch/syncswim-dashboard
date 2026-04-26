"""Semi-supervised pre-annotation for YOLOv8-pose fine-tuning.

Workflow:
    1. Coach drops raw .mp4 / .mov / .avi files in data/raw_videos/
    2. Run: python tools/preannotate.py --interval 5
       (extract every 5th frame; cuts annotation work proportionally)
    3. Outputs:
         data/training/images/<source>_f<frame>.jpg
         data/training/labels/<source>_f<frame>.txt   (YOLO pose format)
    4. Coach loads into CVAT / Label-Studio and CORRECTS the
       pre-annotations. Pre-annotation cuts manual work 5-10x compared
       to drawing 17 keypoints from scratch.
    5. Run: python tools/train_pose.py
    6. Run: python tools/eval_pose.py

YOLO pose label format (one line per person):
    class x_center y_center width height \\
        kx1 ky1 v1 kx2 ky2 v2 ... kx17 ky17 v17

All coords are normalized to [0, 1]. v is visibility:
    0 = not labelled / outside frame
    1 = occluded
    2 = visible
For the COCO-pose convention used by yolov8s-pose.pt, class is always 0.

See docs/fine-tuning.md for the full pipeline + CVAT walkthrough.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

DEFAULT_MODEL = str(_ROOT / "yolov8s-pose.pt")
DEFAULT_RAW_DIR = _ROOT / "data" / "raw_videos"
DEFAULT_OUT_DIR = _ROOT / "data" / "training"


def _frames_iter(video_path: Path, interval: int):
    """Yield ``(frame_idx, bgr_frame)`` every ``interval`` frames.

    Reads a single pass through the file with OpenCV. Returns
    immediately if the file can't be opened (skip silently so a
    corrupt video doesn't kill the whole batch).
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[skip] cannot open: {video_path.name}")
        return
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % interval == 0:
            yield idx, frame
        idx += 1
    cap.release()


def _to_yolo_pose_labels(result, w: int, h: int) -> list[str]:
    """Convert one ultralytics result frame into YOLO-pose label lines.

    Each returned line is whitespace-separated:
        class cx cy bw bh kx1 ky1 v1 ... kx17 ky17 v17
    All values are normalized to [0, 1]. ``class`` is always 0 (person)
    to match the COCO-pose convention.
    """
    if result.boxes is None or result.keypoints is None:
        return []
    boxes = result.boxes.xyxy.cpu().numpy()
    kp_xy = result.keypoints.xy.cpu().numpy()
    kp_conf = (
        result.keypoints.conf.cpu().numpy()
        if result.keypoints.conf is not None
        else None
    )
    lines: list[str] = []
    for i in range(len(boxes)):
        x1, y1, x2, y2 = boxes[i]
        cx = ((x1 + x2) / 2) / w
        cy = ((y1 + y2) / 2) / h
        bw = (x2 - x1) / w
        bh = (y2 - y1) / h
        parts = [
            "0",
            f"{cx:.6f}", f"{cy:.6f}", f"{bw:.6f}", f"{bh:.6f}",
        ]
        for kp_idx in range(17):
            kx = kp_xy[i, kp_idx, 0] / w
            ky = kp_xy[i, kp_idx, 1] / h
            if kp_conf is not None:
                c = float(kp_conf[i, kp_idx])
                v = 2 if c > 0.5 else (1 if c > 0.0 else 0)
            else:
                v = 2
            parts.extend([f"{kx:.6f}", f"{ky:.6f}", str(v)])
        lines.append(" ".join(parts))
    return lines


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--raw", type=Path, default=DEFAULT_RAW_DIR,
        help="Directory of raw .mp4/.mov files (default: data/raw_videos)",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_DIR,
        help="Output directory for images/ and labels/ (default: data/training)",
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help="Pre-trained YOLOv8-pose weights to use for pre-annotation",
    )
    parser.add_argument(
        "--interval", type=int, default=5,
        help="Sample every Nth frame (default 5: 25fps → 5 frames/sec)",
    )
    parser.add_argument(
        "--conf", type=float, default=0.3,
        help="Detection confidence threshold (lower = more borderline "
             "detections to correct, faster than starting blank)",
    )
    parser.add_argument(
        "--device", default="mps",
        help="Inference device: mps (Apple) / cuda / cpu",
    )
    parser.add_argument(
        "--max-persons", type=int, default=10,
        help="Cap detections per frame (avoid noise on busy lanes)",
    )
    args = parser.parse_args()

    if not args.raw.exists():
        print(f"[error] raw video dir does not exist: {args.raw}")
        print(f"        please drop .mp4/.mov files there first")
        sys.exit(1)

    # Case-insensitive suffix match — same fix as extract_frames.py
    # (Codex P2): iPhone .MOV / mixed-case GoPro firmware would
    # otherwise be silently skipped on case-sensitive filesystems.
    extensions = {".mp4", ".mov", ".avi", ".mkv"}
    videos: list[Path] = sorted(
        p for p in args.raw.iterdir()
        if p.is_file() and p.suffix.lower() in extensions
    )
    if not videos:
        print(f"[error] no videos found in {args.raw}")
        sys.exit(1)

    img_dir = args.out / "images"
    lbl_dir = args.out / "labels"
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    # Lazy import so `--help` works without ultralytics installed.
    from ultralytics import YOLO

    model = YOLO(args.model)

    total_frames = 0
    total_persons = 0
    for video in sorted(videos):
        stem = video.stem
        print(f"\n[+] processing {video.name}")
        for frame_idx, frame in _frames_iter(video, args.interval):
            h, w = frame.shape[:2]
            results = model.predict(
                frame,
                verbose=False,
                conf=args.conf,
                device=args.device,
                max_det=args.max_persons,
            )
            if not results:
                continue
            lines = _to_yolo_pose_labels(results[0], w, h)
            if not lines:
                # No persons detected — skip writing label, also skip
                # the image (saving an empty-label image only wastes
                # disk and confuses the validator later).
                continue
            base = f"{stem}_f{frame_idx:06d}"
            cv2.imwrite(str(img_dir / f"{base}.jpg"), frame)
            (lbl_dir / f"{base}.txt").write_text("\n".join(lines) + "\n")
            total_frames += 1
            total_persons += len(lines)
            if total_frames % 20 == 0:
                print(f"  {total_frames} frames / {total_persons} persons")

    print(f"\n[done] {total_frames} frames written to {img_dir}")
    print(f"       {total_persons} persons across {len(videos)} videos")
    print(f"       NEXT STEP: load {args.out} into CVAT/Label-Studio,")
    print(f"                  correct the pre-annotations, then run")
    print(f"                  `python tools/train_pose.py`.")


if __name__ == "__main__":
    main()
