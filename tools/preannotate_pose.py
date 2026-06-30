#!/usr/bin/env python3
"""preannotate_pose.py — Phase B 关键点预标注(v2 detector + MediaPipe → 19 点)。

用 v2 detector(98% 召回)框人 + MediaPipe(33 点含脚尖)在框内出关键点,提取 19 点
(COCO-17 + 左右脚尖),写成 YOLO pose label。人工在 CVAT 只需修正,比从零画 19 点
快 5-10x,也解决旧 tools/preannotate.py "COCO 7% 召回漏 93%" 的问题。

用法:
  python tools/preannotate_pose.py --raw data/raw_videos --interval 5 \
      --detector runs/detect/swimmer_det_v2/weights/best.pt
输出: data/training/phase_b/images/*.jpg + labels/*.txt(YOLO pose 19 点)
后续: 上传 CVAT 修正(尤其脚尖+倒立)→ 导出 → tools/train_pose.py
      --data data/training/phase_b/swimmer_pose.yaml
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cv2

# 让 `python tools/preannotate_pose.py` 能 import dashboard/fastapi_app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# MediaPipe 33 点 → 19 点(COCO-17 顺序 + 左右脚尖 foot_index)
# nose,L_eye,R_eye,L_ear,R_ear,L_sho,R_sho,L_elb,R_elb,L_wri,R_wri,
# L_hip,R_hip,L_knee,R_knee,L_ank,R_ank,L_foot,R_foot
MP_FOR_19 = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28, 31, 32]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default="data/raw_videos")
    ap.add_argument("--out", default="data/training/phase_b")
    ap.add_argument("--detector", default="runs/detect/swimmer_det_v2/weights/best.pt")
    ap.add_argument("--interval", type=int, default=5, help="每 N 帧抽一帧")
    ap.add_argument("--conf", type=float, default=0.5)
    ap.add_argument("--device", default="cpu", help="cpu 最稳(MPS 训练/推理偶有崩)")
    args = ap.parse_args()

    from ultralytics import YOLO
    from dashboard.core.landmarks import detect_landmarks

    if not os.path.exists(args.detector):
        print(f"[error] detector 不存在: {args.detector}（先训 v2 或传 --detector）")
        return
    det = YOLO(args.detector)
    img_dir = os.path.join(args.out, "images")
    lbl_dir = os.path.join(args.out, "labels")
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(lbl_dir, exist_ok=True)

    exts = {".mp4", ".mov", ".avi", ".mkv"}
    vids = sorted(p for p in Path(args.raw).iterdir() if p.suffix.lower() in exts)
    if not vids:
        print(f"[error] {args.raw} 里没有视频")
        return

    total = foot_frames = 0
    for vp in vids:
        cap = cv2.VideoCapture(str(vp))
        idx = 0
        stem = vp.stem
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % args.interval == 0:
                H, W = frame.shape[:2]
                r = det.predict(frame, classes=[0], conf=args.conf,
                                device=args.device, verbose=False)[0]
                lines = []
                has_foot = False
                if r.boxes is not None and len(r.boxes) > 0:
                    for b in r.boxes.xyxy.cpu().numpy():
                        x1, y1, x2, y2 = (max(0, int(b[0])), max(0, int(b[1])),
                                          min(W, int(b[2])), min(H, int(b[3])))
                        if x2 <= x1 or y2 <= y1:
                            continue
                        crop = frame[y1:y2, x1:x2]
                        cw, ch = x2 - x1, y2 - y1
                        lms = detect_landmarks(crop)
                        if lms is None or len(lms) < 33:
                            continue
                        cx, cy = ((x1 + x2) / 2) / W, ((y1 + y2) / 2) / H
                        bw, bh = cw / W, ch / H
                        kp = []
                        for j in MP_FOR_19:
                            gx = (x1 + lms[j].x * cw) / W
                            gy = (y1 + lms[j].y * ch) / H
                            v = float(getattr(lms[j], "visibility", 1.0))
                            vv = 2 if v > 0.5 else (1 if v > 0.1 else 0)
                            if j in (31, 32) and vv > 0:
                                has_foot = True
                            kp += [f"{gx:.6f}", f"{gy:.6f}", str(vv)]
                        lines.append(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f} " + " ".join(kp))
                name = f"{stem}_f{idx:06d}"
                cv2.imwrite(os.path.join(img_dir, name + ".jpg"), frame,
                            [cv2.IMWRITE_JPEG_QUALITY, 92])
                with open(os.path.join(lbl_dir, name + ".txt"), "w") as f:
                    f.write("\n".join(lines) + ("\n" if lines else ""))
                total += 1
                foot_frames += int(has_foot)
            idx += 1
        cap.release()
        print(f"  {vp.name}: 抽帧完成")

    print(f"\n✓ 预标注 {total} 帧({foot_frames} 帧含脚尖初始点) → {img_dir} / {lbl_dir}")
    print("  下一步: 上传 CVAT 修正 19 点(尤其脚尖+倒立场景),导出 YOLO pose,再")
    print("  python tools/train_pose.py --data data/training/phase_b/swimmer_pose.yaml")


if __name__ == "__main__":
    main()
