"""Evaluate a fine-tuned YOLOv8-pose checkpoint.

CRITICAL: the validation split must come from a venue / lighting /
athlete combination that was NOT in the training set. Otherwise a
high mAP just means "memorized this dataset" rather than "improved
generalization to real swimmers". See docs/fine-tuning.md §"评估
集必须来自留出场地".

Output:
    mAP@50      — easier metric, higher first
    mAP@50–95   — harder, what publications usually report
    Per-class breakdown (only "person" for our single-class setup)

Reference baseline (yolov8s-pose.pt without fine-tuning, on our
held-out swim data): mAP@50 ≈ 0.55. Anything above 0.55 means the
fine-tuning genuinely improved over the COCO-pretrained baseline
on swim content.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

DEFAULT_YAML = _ROOT / "data" / "training" / "syncswim.yaml"
DEFAULT_WEIGHTS = _ROOT / "runs" / "pose" / "syncswim_v1" / "weights" / "best.pt"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_YAML)
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()

    if not args.weights.exists():
        print(f"[error] weights not found: {args.weights}")
        print("        train first: python tools/train_pose.py")
        sys.exit(1)

    from ultralytics import YOLO

    model = YOLO(str(args.weights))
    metrics = model.val(
        data=str(args.data),
        imgsz=args.imgsz,
        device=args.device,
    )

    # ultralytics' metrics object exposes .pose.{map, map50, maps}
    print(f"\n[eval]")
    print(f"  mAP@50      : {metrics.pose.map50:.4f}  "
          f"(baseline yolov8s-pose ≈ 0.55 on swim)")
    print(f"  mAP@50–95   : {metrics.pose.map:.4f}")
    if hasattr(metrics, "names") and hasattr(metrics.pose, "maps"):
        per_class = dict(zip(
            metrics.names.values(),
            [float(x) for x in metrics.pose.maps],
        ))
        print(f"  per-class   : {per_class}")
    print(f"\n  Detailed plots: runs/pose/<name>/PR_curve.png, results.png")


if __name__ == "__main__":
    main()
