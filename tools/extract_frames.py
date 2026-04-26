"""Extract evenly-sampled frames from raw videos for CVAT bbox annotation.

Phase A (detector fine-tune) workflow:
    1. Coach drops .mp4 / .mov files in data/raw_videos/
    2. Run: python tools/extract_frames.py --per-video 50
       → produces data/training/phase_a/frames/<stem>_f<idx>.jpg
    3. Coach uploads frames to CVAT, draws ONE bbox per swimmer
       (no keypoints — that's Phase B). See docs/phase-a-annotation.md.
    4. Coach exports YOLO 1.1 → labels/ → runs tools/train_detector.py.

Why a separate, simpler tool than tools/preannotate.py:
  - Phase A only needs bboxes, no pose pre-annotation
  - We proved YOLO COCO recall on swim is ~7%, so pre-annotation would
    miss 93% of swimmers — coach draws most boxes from scratch anyway
  - Sampling N frames per video (uniform across the clip) gives
    better diversity than every-Nth-frame. A 30-second clip at fps=25
    is 750 frames; we want ~50 well-spaced ones, not the first 50.
  - No model load → 10× faster than preannotate (~5s vs ~50s for 3 clips)

Output naming matches preannotate.py so future Phase B can re-use the
same frames + add keypoint labels alongside the bbox labels.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

DEFAULT_RAW_DIR = _ROOT / "data" / "raw_videos"
DEFAULT_OUT_DIR = _ROOT / "data" / "training" / "phase_a" / "frames"


def _sample_indices(total: int, target: int, edge_skip_pct: float) -> list[int]:
    """Pick ``target`` evenly-spaced frame indices from a clip of
    length ``total``, skipping the first/last ``edge_skip_pct`` of
    the clip (fade-ins, mic checks, swimmers entering the pool, etc.).

    If the clip is too short to give ``target`` frames after edge skip,
    return whatever's available.
    """
    if total <= 0 or target <= 0:
        return []
    skip = int(total * edge_skip_pct)
    start = skip
    end = total - skip
    usable = max(1, end - start)
    if target >= usable:
        return list(range(start, end))
    step = usable / target
    return [int(start + i * step) for i in range(target)]


def _extract_one(video: Path, out_dir: Path, target: int,
                 edge_skip_pct: float) -> int:
    """Extract ``target`` evenly-spaced frames from ``video`` into
    ``out_dir``. Returns count actually written.

    OpenCV cannot reliably random-seek on every codec (especially
    variable-frame-rate H.264 from phones), so we walk the clip
    sequentially and yield frames whose index is in our pre-computed
    sample list. Slower than seek but correct everywhere.
    """
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"  [skip] cannot open: {video.name}")
        return 0

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    sample = set(_sample_indices(total, target, edge_skip_pct))
    if not sample:
        cap.release()
        print(f"  [skip] {video.name}: no frames to sample")
        return 0

    print(f"  {video.name}: {total} frames @ {fps:.1f}fps "
          f"→ sampling {len(sample)}")

    written = 0
    idx = 0
    stem = video.stem
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx in sample:
            out_path = out_dir / f"{stem}_f{idx:06d}.jpg"
            cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            written += 1
        idx += 1
    cap.release()
    return written


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--raw", type=Path, default=DEFAULT_RAW_DIR,
        help="Directory of raw videos (default: data/raw_videos)",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_DIR,
        help="Output frames dir (default: data/training/phase_a/frames)",
    )
    parser.add_argument(
        "--per-video", type=int, default=50,
        help="Frames to sample from EACH video (default: 50). "
             "3 videos × 50 = 150 frames ≈ 1-2h CVAT work.",
    )
    parser.add_argument(
        "--edge-skip-pct", type=float, default=0.03,
        help="Skip this fraction of the clip at start AND end "
             "(default: 0.03 = 3%% — drops fade-in/out + setup time)",
    )
    args = parser.parse_args()

    if not args.raw.exists():
        print(f"[error] raw video dir does not exist: {args.raw}")
        print(f"        drop .mp4/.mov files there first")
        sys.exit(1)

    videos: list[Path] = []
    for ext in (".mp4", ".mov", ".avi", ".mkv"):
        videos.extend(args.raw.glob(f"*{ext}"))
    if not videos:
        print(f"[error] no videos found in {args.raw}")
        sys.exit(1)

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"[+] extracting up to {args.per_video} frames per clip "
          f"into {args.out}")

    total_written = 0
    for video in sorted(videos):
        total_written += _extract_one(
            video, args.out, args.per_video, args.edge_skip_pct,
        )

    print(f"\n[done] {total_written} frames across {len(videos)} videos")
    print(f"       → next: zip and upload {args.out} to CVAT")
    print(f"         (see docs/phase-a-annotation.md)")


if __name__ == "__main__":
    main()
