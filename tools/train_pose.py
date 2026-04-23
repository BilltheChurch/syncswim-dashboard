"""Train a YOLOv8-pose model on the corrected SyncSwim dataset.

Run after `tools/preannotate.py` + manual correction in CVAT /
Label Studio. Reads `data/training/syncswim.yaml` for dataset paths
and class info.

Augmentation defaults are tuned for swimming pool footage:
  - HSV jitter is wider (light reflections vary wildly)
  - rotation is reduced (vertical-routine athletes have a strong
    "up is up" prior; flipping them around confuses the model)
  - mosaic is half of the COCO default (multi-person frames already
    contain natural mosaicing; doubling it on top tends to produce
    nonsensical training samples)

See docs/fine-tuning.md for the full pipeline + interpretation
of the mAP / OKS numbers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

DEFAULT_YAML = _ROOT / "data" / "training" / "syncswim.yaml"
DEFAULT_BASE = "yolov8s-pose.pt"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_YAML,
                        help="Dataset config (default: data/training/syncswim.yaml)")
    parser.add_argument("--base", default=DEFAULT_BASE,
                        help="Pre-trained checkpoint to fine-tune from")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16,
                        help="Batch size — M2 16GB tops out at 16, "
                             "M3 Pro can do 32, NVIDIA depends on VRAM")
    parser.add_argument("--device", default="mps",
                        help="Device: mps (Apple Metal) / cuda / cpu")
    parser.add_argument("--name", default="syncswim_v1",
                        help="Output run name → runs/pose/<name>/")
    args = parser.parse_args()

    if not args.data.exists():
        print(f"[error] dataset yaml not found: {args.data}")
        print("        run `python tools/preannotate.py` first,")
        print("        then correct labels in CVAT/Label-Studio.")
        sys.exit(1)

    from ultralytics import YOLO

    model = YOLO(args.base)
    model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        name=args.name,
        # Pool-tuned augmentation (see module docstring)
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.5,
        degrees=5.0,
        mosaic=0.5,
        mixup=0.1,
        copy_paste=0.0,
    )
    out = Path("runs/pose") / args.name / "weights" / "best.pt"
    print(f"\n[done] best weights: {out}")
    print(f"       NEXT STEP: edit config.toml →")
    print(f"           [hardware]")
    print(f"           yolo_model = \"{out}\"")
    print(f"       restart the dashboard, then run")
    print(f"           python tools/eval_pose.py")
    print(f"       on a held-out venue to confirm real improvement.")


if __name__ == "__main__":
    main()
