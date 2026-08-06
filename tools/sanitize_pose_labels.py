"""Sanitize CVAT ultralytics-YOLO-pose exports for training.

Why this exists (DEVLOG #38): CVAT lets the annotator place skeleton
points OUTSIDE the image (a limb that extends past the crop edge), and
its "Ultralytics YOLO pose 1.0" export writes those coordinates as-is
(< 0 or > 1). ultralytics' dataset validator then rejects the ENTIRE
image as corrupt — the Phase B job_4 export lost 13/53 crops this way.

Correct semantics for an out-of-crop keypoint: it is NOT visible in
this training image → coords zeroed, visibility 0 (the pose loss
ignores v=0 points, same convention we already use for underwater
joints). Boxes get clamped to the image bounds instead — a bbox
partially past the edge is still a valid (visible) box.

Usage:
    python tools/sanitize_pose_labels.py data/training/phase_b/labels
    python tools/sanitize_pose_labels.py <dir> --dry-run
"""

from __future__ import annotations

import argparse
from pathlib import Path


def sanitize_line(line: str) -> tuple[str, int, bool]:
    """Return (fixed_line, n_kpts_dropped, bbox_clamped)."""
    parts = line.split()
    if len(parts) < 5 or (len(parts) - 5) % 3 != 0:
        return line, 0, False   # not a pose row — leave untouched

    cls = parts[0]
    cx, cy, w, h = (float(v) for v in parts[1:5])

    # Clamp bbox via corner representation so a box that pokes past
    # the edge shrinks to the visible part instead of shifting.
    x1 = max(0.0, cx - w / 2)
    y1 = max(0.0, cy - h / 2)
    x2 = min(1.0, cx + w / 2)
    y2 = min(1.0, cy + h / 2)
    ncx, ncy = (x1 + x2) / 2, (y1 + y2) / 2
    nw, nh = max(0.0, x2 - x1), max(0.0, y2 - y1)
    bbox_clamped = any(
        abs(a - b) > 1e-9 for a, b in ((ncx, cx), (ncy, cy), (nw, w), (nh, h))
    )

    dropped = 0
    kpts: list[str] = []
    for i in range(5, len(parts), 3):
        x, y, v = float(parts[i]), float(parts[i + 1]), float(parts[i + 2])
        if x < 0.0 or x > 1.0 or y < 0.0 or y > 1.0:
            x, y, v = 0.0, 0.0, 0.0
            dropped += 1
        kpts.extend([f"{x:.6f}", f"{y:.6f}", f"{v:g}"])

    fixed = " ".join(
        [cls, f"{ncx:.6f}", f"{ncy:.6f}", f"{nw:.6f}", f"{nh:.6f}"] + kpts
    )
    return fixed, dropped, bbox_clamped


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("labels_dir", type=Path,
                        help="Directory of YOLO-pose .txt label files")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    args = parser.parse_args()

    files = sorted(args.labels_dir.glob("*.txt"))
    if not files:
        print(f"[error] no .txt labels in {args.labels_dir}")
        raise SystemExit(1)

    touched = 0
    total_dropped = 0
    for f in files:
        lines = f.read_text().strip().splitlines()
        out_lines = []
        file_dropped = 0
        file_clamped = False
        for line in lines:
            if not line.strip():
                continue
            fixed, dropped, clamped = sanitize_line(line)
            out_lines.append(fixed)
            file_dropped += dropped
            file_clamped = file_clamped or clamped
        if file_dropped or file_clamped:
            touched += 1
            total_dropped += file_dropped
            what = []
            if file_dropped:
                what.append(f"{file_dropped} kpt→invisible")
            if file_clamped:
                what.append("bbox clamped")
            print(f"  {f.name}: {', '.join(what)}")
            if not args.dry_run:
                f.write_text("\n".join(out_lines) + "\n")

    mode = "DRY RUN — " if args.dry_run else ""
    print(f"\n[{mode}done] {touched}/{len(files)} files fixed, "
          f"{total_dropped} out-of-bounds keypoints marked invisible")


if __name__ == "__main__":
    main()
