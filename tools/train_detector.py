"""Train a YOLOv8s DETECTOR (bbox only) on the SyncSwim dataset.

This is Phase A of fine-tuning — fix the recall problem first.
DEVLOG #33 quantified that COCO YOLO has ~7% recall on water-pose
targets, which is the root cause of the 19.8× ID inflation we saw
in dogfood. A custom-trained detector can hit 70%+ recall with
~150 annotated frames (1-2h CVAT work).

Phase B (separate PR, separate training) will fine-tune the keypoint
head on top of this detector.

Output: runs/detect/swimmer_det_v1/weights/best.pt

Differences from tools/train_pose.py:
  - Base model: yolov8s.pt (DETECTOR, NOT yolov8s-pose.pt)
  - imgsz default 1280 (water small targets — see DEVLOG #33)
  - batch default 8 (1280 imgsz uses ~4× memory vs 640)
  - Same pool-tuned augmentation (low rotation, low mosaic)

After training, swap into the live pipeline by setting
``swimmer_detector`` in config.toml — fastapi_app/yolo_pose.py
will load it for bboxes and keep using yolov8s-pose.pt for keypoints
(see HybridSwimmerDetector docstring).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

DEFAULT_YAML = _ROOT / "data" / "training" / "phase_a" / "swimmer_det.yaml"
DEFAULT_BASE = "yolov8s.pt"  # detector, not -pose


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data", type=Path, default=DEFAULT_YAML,
        help="Dataset config (default: data/training/phase_a/swimmer_det.yaml)",
    )
    parser.add_argument(
        "--base", default=DEFAULT_BASE,
        help="Base detector to fine-tune from (default: yolov8s.pt)",
    )
    parser.add_argument(
        "--epochs", type=int, default=80,
        help="Training epochs (default: 80 — 150 frames overfits past this)",
    )
    parser.add_argument(
        "--imgsz", type=int, default=1280,
        help="Training image size (default: 1280 — proven critical for "
             "small water targets, see DEVLOG #33)",
    )
    parser.add_argument(
        "--batch", type=int, default=8,
        help="Batch size (default: 8 — M2 16GB tops out here at imgsz 1280)",
    )
    parser.add_argument(
        "--device", default="mps",
        help="Device: mps / cuda / cpu",
    )
    parser.add_argument(
        "--name", default="swimmer_det_v1",
        help="Output run name → runs/detect/<name>/",
    )
    args = parser.parse_args()

    if not args.data.exists():
        print(f"[error] dataset yaml not found: {args.data}")
        print("        run `python tools/extract_frames.py` then annotate")
        print("        bboxes in CVAT (see docs/phase-a-annotation.md).")
        sys.exit(1)

    # Sanity check: train.txt + val.txt must exist or we'll auto-split.
    yaml_dir = args.data.parent
    if not (yaml_dir / "train.txt").exists():
        print(f"[warn] {yaml_dir}/train.txt missing — ultralytics will")
        print("       auto-split, which is BAD (mixes adjacent frames")
        print("       across train/val). See docs/phase-a-annotation.md.")

    from ultralytics import YOLO

    model = YOLO(args.base)
    model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        name=args.name,
        # Pool-tuned augmentation (matches tools/train_pose.py)
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.5,
        degrees=5.0,
        mosaic=0.5,
        mixup=0.1,
        copy_paste=0.0,
        # Detection-specific: keep flip on (left/right symmetry of swim
        # poses doesn't matter for bbox)
        fliplr=0.5,
        flipud=0.0,
    )

    out = Path("runs/detect") / args.name / "weights" / "best.pt"
    print(f"\n[done] best detector: {out}")
    print(f"       NEXT STEP: validate with")
    print(f"           python tools/eval_detector.py")
    print(f"       then enable in config.toml:")
    print(f"           [hardware]")
    print(f"           swimmer_detector = \"{out}\"")


if __name__ == "__main__":
    main()
