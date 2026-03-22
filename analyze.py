"""
Phase 4: Basic Analysis & Verification
Reads a set's IMU + Vision CSVs, aligns by local timestamp,
plots IMU tilt angle vs MediaPipe joint angle on the same graph.

Usage:
    python3 analyze.py                        # auto-picks latest set
    python3 analyze.py data/set_002_20260319_165319  # specific set
"""

import csv
import math
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

# ─── Config ───────────────────────────────────────────────
DATA_DIR = "data"
TARGET_NAME = "NODE_A1"

# ─── Load CSVs ────────────────────────────────────────────
def load_imu(filepath):
    rows = []
    with open(filepath) as f:
        for r in csv.DictReader(f):
            rows.append({
                "t": float(r["timestamp_local"]),
                "ax": float(r["ax"]),
                "ay": float(r["ay"]),
                "az": float(r["az"]),
                "gx": float(r["gx"]),
                "gy": float(r["gy"]),
                "gz": float(r["gz"]),
            })
    return rows

def load_vision(filepath):
    rows = []
    with open(filepath) as f:
        for r in csv.DictReader(f):
            rows.append({
                "t": float(r["timestamp_local"]),
                "angle": float(r["angle_deg"]),
                "visible": int(r["visible"]),
            })
    return rows

# ─── IMU Tilt Angle ──────────────────────────────────────
def calc_imu_tilt(imu_data):
    """
    Compute forearm tilt angle from accelerometer.
    Uses pitch = atan2(ax, sqrt(ay^2 + az^2)) converted to degrees.
    Then maps to 0-180 range to visually compare with elbow angle.
    """
    angles = []
    for r in imu_data:
        ax, ay, az = r["ax"], r["ay"], r["az"]
        # Pitch angle (rotation around Y axis)
        pitch = math.degrees(math.atan2(ax, math.sqrt(ay**2 + az**2)))
        angles.append(pitch)
    return np.array(angles)

# ─── Smoothing ────────────────────────────────────────────
def smooth(data, window=5):
    """Simple moving average."""
    if len(data) < window:
        return data
    kernel = np.ones(window) / window
    return np.convolve(data, kernel, mode='same')

# ─── Find Set Directory ──────────────────────────────────
def find_set_dir(arg=None):
    if arg:
        return arg

    # Find latest set that has BOTH files
    sets = sorted([
        os.path.join(DATA_DIR, d) for d in os.listdir(DATA_DIR)
        if d.startswith("set_") and os.path.isdir(os.path.join(DATA_DIR, d))
    ])
    for s in reversed(sets):
        imu_path = os.path.join(s, f"imu_{TARGET_NAME}.csv")
        vis_path = os.path.join(s, "vision.csv")
        if os.path.exists(imu_path) and os.path.exists(vis_path):
            return s
    return None

# ─── Main ─────────────────────────────────────────────────
def main():
    set_dir = find_set_dir(sys.argv[1] if len(sys.argv) > 1 else None)
    if not set_dir:
        print("ERROR: No set found with both IMU and vision CSVs.")
        print("Usage: python3 analyze.py [set_dir]")
        return

    imu_path = os.path.join(set_dir, f"imu_{TARGET_NAME}.csv")
    vis_path = os.path.join(set_dir, "vision.csv")

    print(f"Analyzing: {set_dir}")
    print(f"  IMU:    {imu_path}")
    print(f"  Vision: {vis_path}")

    # Load data
    imu_data = load_imu(imu_path)
    vis_data = load_vision(vis_path)
    print(f"  IMU rows:    {len(imu_data)}")
    print(f"  Vision rows: {len(vis_data)}")

    # Use common time origin (earliest timestamp)
    t0 = min(imu_data[0]["t"], vis_data[0]["t"])
    imu_t = np.array([r["t"] - t0 for r in imu_data])
    vis_t = np.array([r["t"] - t0 for r in vis_data])

    # IMU tilt angle
    imu_tilt = calc_imu_tilt(imu_data)
    imu_tilt_smooth = smooth(imu_tilt, window=15)

    # Vision angle (filter visible-only for clean data)
    vis_angle = np.array([r["angle"] for r in vis_data])
    vis_visible = np.array([r["visible"] for r in vis_data])
    # Replace invisible frames with NaN
    vis_angle_clean = np.where(vis_visible == 1, vis_angle, np.nan)

    # ─── Time alignment check ────────────────────────────
    print(f"\n  Time alignment:")
    print(f"    IMU range:    {imu_t[0]:.3f}s - {imu_t[-1]:.3f}s ({imu_t[-1]-imu_t[0]:.1f}s)")
    print(f"    Vision range: {vis_t[0]:.3f}s - {vis_t[-1]:.3f}s ({vis_t[-1]-vis_t[0]:.1f}s)")
    print(f"    Start offset: {(vis_t[0]-imu_t[0])*1000:.1f} ms")

    # ─── Correlation analysis ─────────────────────────────
    # Resample IMU to vision timestamps for correlation
    imu_resampled = np.interp(vis_t, imu_t, imu_tilt_smooth)
    # Only compare where vision is visible
    mask = vis_visible == 1
    if mask.sum() > 10:
        corr = np.corrcoef(imu_resampled[mask], vis_angle_clean[mask[: len(vis_angle_clean)]])[0, 1]
        print(f"\n  Correlation (IMU tilt vs MediaPipe angle): {corr:.3f}")
        if abs(corr) > 0.5:
            print(f"    -> Strong correlation! Pipeline is working.")
        elif abs(corr) > 0.3:
            print(f"    -> Moderate correlation. Sensor placement may differ from camera view.")
        else:
            print(f"    -> Weak correlation. Check sensor orientation and camera angle.")

    # ─── Plot ─────────────────────────────────────────────
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    fig.suptitle(f"IMU vs Vision Analysis — {os.path.basename(set_dir)}", fontsize=14, fontweight='bold')

    # Plot 1: MediaPipe angle
    ax1.plot(vis_t, vis_angle_clean, 'b-', linewidth=1, alpha=0.7, label='MediaPipe angle')
    ax1.set_ylabel('Elbow Angle (deg)')
    ax1.set_ylim(0, 200)
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.set_title('Vision: MediaPipe Elbow Angle')

    # Plot 2: IMU tilt angle
    ax2.plot(imu_t, imu_tilt, color='orange', linewidth=0.5, alpha=0.3, label='Raw')
    ax2.plot(imu_t, imu_tilt_smooth, color='red', linewidth=1.5, label='Smoothed (15-pt)')
    ax2.set_ylabel('Tilt Angle (deg)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    ax2.set_title('IMU: Accelerometer Tilt Angle')

    # Plot 3: Overlay (normalized for visual comparison)
    # Normalize both to 0-1 range for shape comparison
    vis_norm = (vis_angle_clean - np.nanmin(vis_angle_clean)) / (np.nanmax(vis_angle_clean) - np.nanmin(vis_angle_clean) + 1e-6)
    imu_norm = (imu_tilt_smooth - np.min(imu_tilt_smooth)) / (np.max(imu_tilt_smooth) - np.min(imu_tilt_smooth) + 1e-6)

    ax3.plot(vis_t, vis_norm, 'b-', linewidth=1.5, alpha=0.8, label='MediaPipe (normalized)')
    ax3.plot(imu_t, imu_norm, 'r-', linewidth=1.5, alpha=0.8, label='IMU tilt (normalized)')
    ax3.set_ylabel('Normalized (0-1)')
    ax3.set_xlabel('Time (seconds)')
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)
    ax3.set_title(f'Overlay Comparison (correlation: {corr:.3f})' if mask.sum() > 10 else 'Overlay Comparison')

    plt.tight_layout()

    # Save
    out_path = os.path.join(set_dir, "analysis.png")
    plt.savefig(out_path, dpi=150)
    print(f"\n  Plot saved: {out_path}")
    print(f"  Opening plot...")
    plt.show()

if __name__ == "__main__":
    main()
