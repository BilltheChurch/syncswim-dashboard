"""Evaluate a fine-tuned YOLOv8 detector vs the COCO baseline.

Phase A success criterion (from task.md §9.1): mAP@50 > 0.70 on the
held-out clip. Anything above the baseline (~0.07 recall on swim per
DEVLOG #33) is technically a win, but 0.70 is the threshold where
ID-stability problems start to disappear.

Output:
    [trained]
    mAP@50      : 0.XXXX
    mAP@50-95   : 0.XXXX
    recall      : 0.XXXX

    [baseline yolov8s.pt at imgsz 1280]
    mAP@50      : 0.XXXX
    recall      : 0.XXXX

    [delta]   +X.XX recall, +Y.YY mAP@50

Run AFTER tools/train_detector.py. Compares the trained best.pt vs
the COCO yolov8s.pt on the SAME val.txt (held-out clip).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

DEFAULT_YAML = _ROOT / "data" / "training" / "phase_a" / "swimmer_det.yaml"
DEFAULT_WEIGHTS = (
    _ROOT / "runs" / "detect" / "swimmer_det_v1" / "weights" / "best.pt"
)
DEFAULT_BASELINE = _ROOT / "yolov8s.pt"


def _val_one(weights: Path, data: Path, imgsz: int, device: str, label: str):
    from ultralytics import YOLO

    if not weights.exists():
        print(f"[error] weights not found: {weights}")
        if label == "baseline":
            print("        download with:")
            print("        curl -L -o yolov8s.pt \\")
            print("          https://github.com/ultralytics/assets/"
                  "releases/download/v8.3.0/yolov8s.pt")
        return None

    print(f"\n[+] evaluating {label}: {weights.name}")
    model = YOLO(str(weights))
    metrics = model.val(
        data=str(data),
        imgsz=imgsz,
        device=device,
        verbose=False,
    )
    # ultralytics' detection metrics: .box.map, .box.map50, .box.mr (recall)
    return {
        "mAP@50": float(metrics.box.map50),
        "mAP@50-95": float(metrics.box.map),
        "recall": float(metrics.box.mr),
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_YAML)
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS,
                        help="Trained detector to evaluate")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE,
                        help="COCO baseline detector (default: yolov8s.pt)")
    parser.add_argument("--imgsz", type=int, default=1280,
                        help="Eval image size (default: 1280, matches train)")
    parser.add_argument("--device", default="mps")
    parser.add_argument("--skip-baseline", action="store_true",
                        help="Skip baseline run (faster if you already have it)")
    args = parser.parse_args()

    trained = _val_one(args.weights, args.data, args.imgsz, args.device,
                       "trained")
    if trained is None:
        sys.exit(1)

    baseline = None
    if not args.skip_baseline:
        baseline = _val_one(args.baseline, args.data, args.imgsz, args.device,
                            "baseline")

    print("\n" + "=" * 50)
    print("[trained]")
    for k, v in trained.items():
        print(f"  {k:12s}: {v:.4f}")
    if baseline is not None:
        print("\n[baseline yolov8s.pt at imgsz {}]".format(args.imgsz))
        for k, v in baseline.items():
            print(f"  {k:12s}: {v:.4f}")
        print("\n[delta]")
        for k in trained:
            d = trained[k] - baseline[k]
            sign = "+" if d >= 0 else ""
            print(f"  {k:12s}: {sign}{d:.4f}")

    print("\n[verdict]")
    if trained["mAP@50"] >= 0.70:
        print(f"  ✅ mAP@50 = {trained['mAP@50']:.4f} ≥ 0.70 — Phase A target hit.")
        print(f"     Enable in config.toml:")
        print(f"       [hardware]")
        print(f"       swimmer_detector = \"{args.weights}\"")
    elif trained["mAP@50"] >= 0.50:
        print(f"  ⚠ mAP@50 = {trained['mAP@50']:.4f} (target 0.70). Still beats")
        print(f"     baseline, deployable but ID stability won't be perfect.")
        print(f"     Add 50-100 more annotated frames before declaring done.")
    else:
        print(f"  ❌ mAP@50 = {trained['mAP@50']:.4f} — train data too small")
        print(f"     or held-out clip too dissimilar. Check:")
        print(f"     1. Did you annotate ≥150 frames?")
        print(f"     2. Is the val clip from the SAME pool as train?")
        print(f"        (cross-pool generalization needs Phase 9.3 data expansion)")


if __name__ == "__main__":
    main()
