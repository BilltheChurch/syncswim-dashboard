"""Generate a PDF training report for one Set.

Layout (A4 portrait, 1-3 pages — pages 2 and 3 only render when
there's content for them):

  Page 1 — cover
    title bar + recording timestamp + big overall score + radar
    overlay + 4-cell metadata strip (duration / frames / IMU / FPS)

  Page 2 — details (only when there are metrics to show)
    indicator table (name / value / zone / deduction) +
    3-frame keyframe strip (10% / 50% / 90% of recording)

  Page 3 — notes & sensors (only when at least one is non-empty)
    coach note (free-form) + IMU node summary table

Use case:
  Coach finishes training → wants to send a report to the athlete /
  parent / federation. Until 8.4 the only way was screenshotting
  the dashboard.

Why matplotlib PdfPages and not WeasyPrint:
  - matplotlib is already a project dependency (used by analyze.py)
  - WeasyPrint needs native libs (pango/cairo/gdk-pixbuf) that
    require `brew install` on macOS — extra friction for users
  - PdfPages renders vector text + raster images at print quality
  - CJK works once we point matplotlib at a system Heiti TC font

Run standalone:
    python tools/export_pdf.py set_001_imported_xxx
    python tools/export_pdf.py set_NNN -o /tmp/report.pdf

Or hit the FastAPI endpoint that wraps this:
    GET /api/sets/{name}/report.pdf  → application/pdf
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")   # headless — no display required
# Silence the "Font family 'Microsoft YaHei' not found" noise that
# the cross-platform fallback list generates on every PDF render.
# These names are intentional fallbacks for Linux / Windows; on
# macOS the Heiti TC entry wins and the others are tried in vain
# but harmlessly.
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
# Force a CJK-capable font. matplotlib silently falls back to
# DejaVu Sans (which renders Chinese as squares) without explicit
# override. We probe a few common macOS / Linux options; the first
# one that exists wins. Append sans-serif as a final fallback so
# Latin glyphs still render even on a system with none of the
# above installed.
matplotlib.rcParams["font.family"] = [
    "Heiti TC",            # macOS bundled
    "Hiragino Sans GB",    # macOS bundled
    "Songti SC",           # macOS bundled
    "Noto Sans CJK SC",    # Linux (apt install fonts-noto-cjk)
    "Microsoft YaHei",     # Windows
    "sans-serif",
]
matplotlib.rcParams["axes.unicode_minus"] = False

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

import cv2

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from dashboard.core.data_loader import load_all_imus  # noqa: E402
from dashboard.core.metrics import compute_all_metrics  # noqa: E402

A4_PORTRAIT = (8.27, 11.69)

# Translation table — falls back to the raw metric name if missing.
METRIC_LABELS = {
    "leg_deviation": "腿部偏差",
    "knee_extension": "膝盖伸直",
    "shoulder_knee_alignment": "肩膝对齐",
    "trunk_vertical": "躯干垂直",
    "leg_symmetry": "腿部对称",
    "leg_height_index": "腿部高度",
    "movement_frequency": "动作频率",
    "rotation_frequency": "旋转频率",
    "mean_pattern_duration": "动作持续",
    "last_hf_duration": "末段维持",
    "explosive_power": "爆发力",
    "energy_index": "能量消耗",
    "motion_complexity": "动作复杂度",
    "smoothness": "平稳度",
    "stability": "稳定度",
}

ZONE_BADGE = {
    "clean": "✓",
    "minor": "·",
    "major": "!",
    "critical": "!!",
    "no_data": "—",
}


def _normalize_for_radar(name: str, val: float | None) -> float:
    """Mirror the JS dashboard's normalizeForRadar so the PDF radar
    matches what the coach sees on screen. Returns 0–100."""
    if val is None:
        return 0.0
    if name == "leg_deviation":
        return max(0.0, min(100.0, (30 - val) / 30 * 100))
    if name in ("knee_extension", "shoulder_knee_alignment"):
        return max(0.0, min(100.0, (val - 140) / 40 * 100))
    if name == "trunk_vertical":
        return max(0.0, min(100.0, (35 - val) / 35 * 100))
    if name == "leg_symmetry":
        return max(0.0, min(100.0, (30 - val) / 30 * 100))
    if name == "smoothness":
        return max(0.0, min(100.0, (50 - val) / 50 * 100))
    if name == "stability":
        return max(0.0, min(100.0, (45 - val) / 45 * 100))
    if name == "leg_height_index":
        return max(0.0, min(100.0, val / 180 * 100))
    return 50.0


def _video_meta(set_dir: Path) -> tuple[float, int, float]:
    """Return ``(duration_sec, frame_count, fps)`` from video.mp4 if
    present. Falls back to (0, 0, 25.0) so callers don't need to
    null-check."""
    video_path = set_dir / "video.mp4"
    if not video_path.exists():
        return 0.0, 0, 25.0
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return 0.0, 0, 25.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        return n / fps if fps > 0 else 0.0, n, fps
    finally:
        cap.release()


def _extract_keyframes(set_dir: Path, fractions=(0.1, 0.5, 0.9)):
    """Pull frames at the given recording-time fractions. Returns
    a list of BGR numpy arrays (possibly fewer than requested if the
    video can't be read)."""
    video_path = set_dir / "video.mp4"
    if not video_path.exists():
        return []
    frames = []
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return []
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        for frac in fractions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * frac))
            ok, frame = cap.read()
            if ok:
                frames.append(frame)
    finally:
        cap.release()
    return frames


def _read_note(set_dir: Path) -> str:
    p = set_dir / "note.md"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _imu_summary(set_dir: Path) -> list[tuple[str, int, float, float]]:
    """One row per IMU node: (node_name, samples, duration_sec, hz)."""
    out = []
    for node, df in (load_all_imus(str(set_dir)) or {}).items():
        n = len(df)
        if n > 1 and "timestamp_local" in df.columns:
            ts = df["timestamp_local"].values.astype(float)
            duration = float(ts[-1] - ts[0])
        else:
            duration = 0.0
        rate = (n / duration) if duration > 0 else 0.0
        out.append((node, n, duration, rate))
    return out


def _page_cover(pdf, set_name, overall, metrics, duration_s, frame_count,
                imu_count):
    fig = plt.figure(figsize=A4_PORTRAIT)

    # Title bar
    ax = fig.add_axes([0.07, 0.86, 0.86, 0.10])
    ax.axis("off")
    ax.text(0, 0.7, "训练报告", fontsize=28, weight="bold", color="#3B82F6")
    ax.text(0, 0.18, set_name, fontsize=10, color="#888", family="monospace")
    ax.text(1, 0.55, datetime.now().strftime("%Y-%m-%d %H:%M"),
            fontsize=10, color="#888", ha="right")

    # Big score
    ax = fig.add_axes([0.07, 0.65, 0.42, 0.18])
    ax.axis("off")
    score_str = f"{overall:.1f}" if overall is not None else "--"
    ax.text(0.0, 0.55, score_str, fontsize=68, weight="bold",
            color="#10B981", va="center")
    ax.text(0.95, 0.35, "/10", fontsize=18, color="#888",
            va="center", ha="right")
    ax.text(0.0, 0.05, "综合评分", fontsize=11, color="#888")

    # Metadata strip
    ax = fig.add_axes([0.55, 0.65, 0.40, 0.18])
    ax.axis("off")
    cells = [
        ("时长", f"{duration_s:.0f}s"),
        ("帧数", f"{frame_count}"),
        ("IMU 节点", f"{imu_count}"),
    ]
    for i, (label, val) in enumerate(cells):
        x = i * 0.34
        ax.text(x, 0.7, val, fontsize=18, weight="bold", color="#3B82F6")
        ax.text(x, 0.35, label, fontsize=9, color="#888")

    # Radar
    real_metrics = [
        m for m in metrics if m.value is not None and m.zone != "no_data"
    ]
    if len(real_metrics) >= 3:
        ax = fig.add_axes([0.18, 0.18, 0.64, 0.42], projection="polar")
        names = [METRIC_LABELS.get(m.name, m.name) for m in real_metrics]
        values = [_normalize_for_radar(m.name, m.value) for m in real_metrics]
        angles = np.linspace(0, 2 * np.pi, len(names), endpoint=False).tolist()
        values_closed = values + [values[0]]
        angles_closed = angles + [angles[0]]
        ax.fill(angles_closed, values_closed, color="#3B82F6", alpha=0.20)
        ax.plot(angles_closed, values_closed, color="#3B82F6", linewidth=2)
        ax.scatter(angles, values, color="#3B82F6", s=20, zorder=10)
        ax.set_xticks(angles)
        ax.set_xticklabels(names, fontsize=8)
        ax.set_yticks([25, 50, 75, 100])
        ax.set_yticklabels(["", "50", "", "100"], fontsize=7, color="#bbb")
        ax.set_ylim(0, 100)
        ax.grid(True, alpha=0.2)
        ax.spines["polar"].set_color("#ddd")
        ax.set_title("指标雷达图", fontsize=11, color="#666", pad=14)
    else:
        ax = fig.add_axes([0.07, 0.30, 0.86, 0.22])
        ax.axis("off")
        ax.text(0.5, 0.5,
                "可用指标 < 3，无法绘制雷达图\n(等姿态稳定检测后再生成报告效果更好)",
                ha="center", fontsize=10, color="#aaa")

    # Footer
    ax = fig.add_axes([0.07, 0.04, 0.86, 0.04])
    ax.axis("off")
    ax.text(0, 0.5, f'生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")}',
            fontsize=8, color="#aaa")
    ax.text(1, 0.5, "Coach Workstation · Page 1",
            fontsize=8, color="#aaa", ha="right")

    pdf.savefig(fig)
    plt.close(fig)


def _page_details(pdf, set_dir: Path, metrics):
    fig = plt.figure(figsize=A4_PORTRAIT)

    # Header
    ax = fig.add_axes([0.07, 0.92, 0.86, 0.05])
    ax.axis("off")
    ax.text(0, 0.5, "详细指标", fontsize=16, weight="bold", color="#333")

    # Indicator table
    ax = fig.add_axes([0.07, 0.50, 0.86, 0.40])
    ax.axis("off")
    rows = []
    for m in metrics:
        name = METRIC_LABELS.get(m.name, m.name)
        if m.value is None:
            val = "—"
        else:
            unit = m.unit or ""
            val = f"{m.value:.2f} {unit}".strip()
        zone = ZONE_BADGE.get(m.zone, "")
        ded = "—" if m.deduction in (None, 0, 0.0) else f"-{m.deduction:.1f}"
        rows.append([name, val, zone, ded])
    if not rows:
        ax.text(0.5, 0.5, "无指标数据", ha="center", fontsize=11, color="#bbb")
    else:
        table = ax.table(
            cellText=rows,
            colLabels=["指标", "当前值", "区域", "扣分"],
            colWidths=[0.42, 0.28, 0.12, 0.18],
            loc="upper center",
            cellLoc="left",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8.5)
        table.scale(1, 1.45)
        # Header row styling
        for j in range(4):
            cell = table[(0, j)]
            cell.set_facecolor("#f0f4ff")
            cell.set_text_props(weight="bold", color="#333")

    # Keyframes
    keyframes = _extract_keyframes(set_dir)
    if keyframes:
        ax_h = fig.add_axes([0.07, 0.42, 0.86, 0.04])
        ax_h.axis("off")
        ax_h.text(0, 0.5, "关键帧", fontsize=14, weight="bold", color="#333")
        labels = ["开始 10%", "中段 50%", "末段 90%"]
        for i, kf in enumerate(keyframes[:3]):
            ax_kf = fig.add_axes([0.07 + i * 0.30, 0.10, 0.27, 0.30])
            ax_kf.imshow(cv2.cvtColor(kf, cv2.COLOR_BGR2RGB))
            ax_kf.axis("off")
            ax_kf.set_title(labels[i] if i < len(labels) else "",
                            fontsize=9, color="#666")

    # Footer
    ax = fig.add_axes([0.07, 0.04, 0.86, 0.04])
    ax.axis("off")
    ax.text(1, 0.5, "Coach Workstation · Page 2",
            fontsize=8, color="#aaa", ha="right")

    pdf.savefig(fig)
    plt.close(fig)


def _page_notes(pdf, note_text: str, imu_rows):
    fig = plt.figure(figsize=A4_PORTRAIT)

    ax = fig.add_axes([0.07, 0.92, 0.86, 0.05])
    ax.axis("off")
    ax.text(0, 0.5, "教练备注 & 传感器", fontsize=16, weight="bold", color="#333")

    # Note (top half)
    ax = fig.add_axes([0.07, 0.55, 0.86, 0.33])
    ax.axis("off")
    ax.text(0, 1, "教练备注", fontsize=12, weight="bold",
            color="#A855F7", va="top")
    if note_text and note_text.strip():
        # Truncate aggressively — PDF text wrapping in matplotlib is
        # fragile, and a half-page of free-form text is a code smell
        # for using markdown editor instead. 800 chars ≈ 200 zh chars.
        clipped = note_text.strip()
        if len(clipped) > 800:
            clipped = clipped[:800] + "\n\n…(已截断)"
        ax.text(0, 0.93, clipped, fontsize=10, va="top",
                wrap=True, color="#444", linespacing=1.6)
    else:
        ax.text(0, 0.85, "（本场无备注）", fontsize=10, color="#bbb",
                style="italic", va="top")

    # IMU (bottom half)
    ax = fig.add_axes([0.07, 0.20, 0.86, 0.30])
    ax.axis("off")
    ax.text(0, 1, "IMU 数据", fontsize=12, weight="bold",
            color="#A855F7", va="top")
    if imu_rows:
        rows = [
            [name, str(n), f"{dur:.1f}s", f"{rate:.1f} Hz"]
            for (name, n, dur, rate) in imu_rows
        ]
        table = ax.table(
            cellText=rows,
            colLabels=["节点", "样本数", "时长", "频率"],
            loc="upper left",
            colWidths=[0.30, 0.20, 0.20, 0.20],
            cellLoc="left",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1, 1.5)
        for j in range(4):
            cell = table[(0, j)]
            cell.set_facecolor("#f7f0ff")
            cell.set_text_props(weight="bold", color="#444")
    else:
        ax.text(0, 0.85, "（本场无 IMU 数据）", fontsize=10, color="#bbb",
                style="italic", va="top")

    # Footer
    ax = fig.add_axes([0.07, 0.04, 0.86, 0.04])
    ax.axis("off")
    ax.text(1, 0.5, "Coach Workstation · Page 3",
            fontsize=8, color="#aaa", ha="right")

    pdf.savefig(fig)
    plt.close(fig)


def render_pdf(set_dir: Path, output: Path) -> None:
    """Render the full report. Raises ``ValueError`` when the Set has
    no compute-able metrics (so callers can return a clean 404)."""
    report = compute_all_metrics(str(set_dir))
    if report is None:
        raise ValueError(f"no data in {set_dir.name}")

    set_name = set_dir.name
    metrics = report.metrics
    overall = report.overall_score

    duration_s, frame_count, _fps = _video_meta(set_dir)
    note_text = _read_note(set_dir)
    imu_rows = _imu_summary(set_dir)

    output.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(output) as pdf:
        _page_cover(pdf, set_name, overall, metrics,
                    duration_s, frame_count, len(imu_rows))
        if metrics:
            _page_details(pdf, set_dir, metrics)
        if note_text or imu_rows:
            _page_notes(pdf, note_text, imu_rows)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("set_name",
                        help="Set directory name (e.g., set_001_imported_xxx)")
    parser.add_argument("--data-dir", type=Path,
                        default=_ROOT / "data",
                        help="Where set_* directories live")
    parser.add_argument("-o", "--output", type=Path,
                        help="PDF output path (default: <set_dir>/report.pdf)")
    args = parser.parse_args()

    set_dir = args.data_dir / args.set_name
    if not set_dir.is_dir():
        print(f"[error] set not found: {set_dir}")
        sys.exit(1)

    output = args.output or (set_dir / "report.pdf")
    try:
        render_pdf(set_dir, output)
    except ValueError as e:
        print(f"[error] {e}")
        sys.exit(1)
    print(f"[done] {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
