"""Transplant yolov8s-pose (17-kpt) head weights into a 19-kpt model.

Why (DEVLOG #38): ultralytics' keypoint loss is OKS-shaped —
``1 - exp(-d²/(2σ)²/area)``. A freshly-initialized kpt head predicts
far from any body, the exponential saturates, gradients vanish, and
the head NEVER learns (pose mAP stays 0.0 forever — this silently
killed the 2026-07-27 Phase B attempt and reproduced in 3 probes).
A 17-kpt fine-tune works precisely because the pretrained cv4 head
starts near the body.

Fix: build the 19-kpt architecture, copy the pretrained cv4 weights
for keypoints 0-16 channel-by-channel, and SEED the two new
foot_index keypoints (17/18) from the corresponding ankle channels
(15/16) — feet start where ankles are, a few centimeters of offset to
learn instead of half an image. All other modules transfer 1:1.

Channel layout note: cv4's channels are laid out kpt-major, 3 values
(x, y, v) per keypoint → 17 kpt = 51 ch, 19 kpt = 57 ch. The
intermediate cv4 convs are also nk-wide (c4 = max(ch/4, nk) = nk
here), so every conv in cv4 needs the same row/col treatment.

Usage:
    python tools/seed_pose19_head.py \
        --base yolov8s-pose.pt \
        --out runs/pose/seed/yolov8s-pose19-seeded.pt
"""

from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path

import torch
import yaml

ANKLE_L, ANKLE_R = 15, 16     # source keypoints for the seed
FOOT_L, FOOT_R = 17, 18       # target keypoints


def _expand_rows(w17: torch.Tensor, w19: torch.Tensor) -> torch.Tensor:
    """Copy 51 rows (17 kpt × 3) and seed rows 51:57 from ankles."""
    out = w19.clone()
    out[:51] = w17[:51]
    out[FOOT_L * 3:FOOT_L * 3 + 3] = w17[ANKLE_L * 3:ANKLE_L * 3 + 3]
    out[FOOT_R * 3:FOOT_R * 3 + 3] = w17[ANKLE_R * 3:ANKLE_R * 3 + 3]
    return out


def _expand_conv(w17: torch.Tensor, w19: torch.Tensor,
                 rows: bool, cols: bool) -> torch.Tensor:
    """Transplant a conv weight, expanding out-channels (rows) and/or
    in-channels (cols) from 51 to 57 with ankle-seeded extras."""
    out = w19.clone()
    src = w17
    if cols:
        # expand input dim first: build a (…, 57, …) version of src
        expanded = out.new_zeros((src.shape[0], 57) + tuple(src.shape[2:]))
        expanded[:, :51] = src
        expanded[:, FOOT_L * 3:FOOT_L * 3 + 3] = src[:, ANKLE_L * 3:ANKLE_L * 3 + 3]
        expanded[:, FOOT_R * 3:FOOT_R * 3 + 3] = src[:, ANKLE_R * 3:ANKLE_R * 3 + 3]
        src = expanded
    if rows:
        out[:51] = src[:51]
        out[FOOT_L * 3:FOOT_L * 3 + 3] = src[ANKLE_L * 3:ANKLE_L * 3 + 3]
        out[FOOT_R * 3:FOOT_R * 3 + 3] = src[ANKLE_R * 3:ANKLE_R * 3 + 3]
    else:
        out[:] = src
    return out


def build_seeded(base_pt: str) -> "object":
    import ultralytics
    from ultralytics import YOLO

    # 19-kpt arch yaml (packaged yolov8-pose.yaml + kpt_shape override)
    models_dir = os.path.join(os.path.dirname(ultralytics.__file__),
                              "cfg", "models")
    src_yaml = glob.glob(os.path.join(models_dir, "**", "yolov8-pose.yaml"),
                         recursive=True)[0]
    cfg = yaml.safe_load(open(src_yaml))
    cfg["kpt_shape"] = [19, 3]
    tmp_yaml = Path(base_pt).parent / "yolov8s-pose19.yaml"
    yaml.safe_dump(cfg, open(tmp_yaml, "w"))

    m19 = YOLO(str(tmp_yaml))
    m19.load(base_pt)                       # everything except cv4
    m17 = YOLO(base_pt)

    cv4_19 = m19.model.model[-1].cv4        # ModuleList: 3 scales
    cv4_17 = m17.model.model[-1].cv4
    with torch.no_grad():
        for s19, s17 in zip(cv4_19, cv4_17):
            # scale branch = Sequential(Conv(c,c4), Conv(c4,c4), Conv2d(c4,nk))
            m_pairs = list(zip(s19.modules(), s17.modules()))
            first_conv_done = False
            for mod19, mod17 in m_pairs:
                if not isinstance(mod19, torch.nn.Conv2d):
                    continue
                rows = mod19.weight.shape[0] != mod17.weight.shape[0]
                cols = mod19.weight.shape[1] != mod17.weight.shape[1]
                if not rows and not cols:
                    mod19.weight.copy_(mod17.weight)
                else:
                    mod19.weight.copy_(_expand_conv(
                        mod17.weight, mod19.weight, rows=rows, cols=cols))
                if mod19.bias is not None and mod17.bias is not None:
                    if mod19.bias.shape[0] != mod17.bias.shape[0]:
                        mod19.bias.copy_(_expand_rows(mod17.bias, mod19.bias))
                    else:
                        mod19.bias.copy_(mod17.bias)
                first_conv_done = True
            # BatchNorm layers inside Conv blocks
            for mod19, mod17 in m_pairs:
                if not isinstance(mod19, torch.nn.BatchNorm2d):
                    continue
                if mod19.weight.shape[0] != mod17.weight.shape[0]:
                    for attr in ("weight", "bias", "running_mean",
                                 "running_var"):
                        t19 = getattr(mod19, attr)
                        t17 = getattr(mod17, attr)
                        t19.copy_(_expand_rows(t17, t19))
                else:
                    mod19.load_state_dict(mod17.state_dict())
            assert first_conv_done, "cv4 branch had no Conv2d?"
    return m19


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="yolov8s-pose.pt")
    parser.add_argument("--out", default="runs/pose/seed/yolov8s-pose19-seeded.pt")
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    m19 = build_seeded(args.base)
    m19.save(str(out))
    print(f"[done] seeded 19-kpt checkpoint: {out}")
    print("       train with: python tools/train_pose.py "
          f"--base {out} --data data/training/phase_b/swimmer_pose19.yaml")


if __name__ == "__main__":
    main()
