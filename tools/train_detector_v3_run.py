"""One-shot launcher for detector v3 (DEVLOG #40).

Fine-tunes swimmer_det_v2 on old-pool + new-pool frames so the detector
stops firing on the new pool's red lane floats. Written as a file (not a
heredoc) so nohup survives session teardown.
"""
from ultralytics import YOLO

m = YOLO("runs/detect/swimmer_det_v2/weights/best.pt")
m.train(
    data="data/training/phase_a_v3/swimmer_det_v3.yaml",
    epochs=120, imgsz=1280, batch=4, device="cpu",
    name="swimmer_det_v3", exist_ok=True,
    # Same pool-tuned augmentation discipline as Phase A/B: no mosaic
    # (small dataset), mild rotation (vertical-routine prior).
    mosaic=0.0, mixup=0.0, degrees=5.0,
    hsv_h=0.015, hsv_s=0.7, hsv_v=0.5,
    patience=40, plots=False, verbose=False,
)
print("[done] detector v3 training complete")
