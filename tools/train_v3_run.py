"""One-shot launcher for Phase B v3 training (DEVLOG #39 dataset).

Written as a file (not a heredoc) so nohup survives session teardown.
Recipe = DEVLOG #38 winner: seeded 19-kpt base, no mosaic/mixup.
"""
from ultralytics import YOLO

m = YOLO("runs/pose/seed/yolov8s-pose19-seeded.pt")
m.train(
    data="data/training/phase_b_v3/swimmer_pose19_v3.yaml",
    epochs=400, imgsz=640, batch=8, device="cpu", freeze=10,
    name="swimmer_pose19_v3", exist_ok=True,
    mosaic=0.0, mixup=0.0, degrees=5.0,
    hsv_h=0.015, hsv_s=0.7, hsv_v=0.5,
    patience=100, plots=False, verbose=False,
)
print("[done] v3 training complete")
