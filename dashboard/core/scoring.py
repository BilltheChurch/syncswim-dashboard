"""Scoring engine for biomechanical metrics and FINA deductions.

Implements the metrics studied in:

* Edriss et al. (2024) "Advancing Artistic Swimming Officiating and
  Performance Assessment — A Computer Vision Study Using MediaPipe",
  IJCSS 23(2). Validated leg-angle deviation and shoulder-knee angle
  against AutoCAD (r=0.93, ICC=0.92).
* Yue et al. (2023) "Maximizing choreography and performance in
  artistic swimming team free routines: the role of hybrid figures",
  Scientific Reports 13, 21303. Identified movement frequency, leg
  height index, leg angle deviation, pattern duration and rotation
  frequency as significant predictors of total score.

Metrics whose input data is unavailable are returned with
``zone="no_data"`` so the UI can honestly display "--" rather than a
fabricated perfect score.
"""
from dataclasses import dataclass, field

import math
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from dashboard.core.analysis import calc_imu_tilt, smooth
from dashboard.core.angles import calc_angle
from dashboard.core.vision_angles import (
    calc_leg_deviation_vision,
    calc_knee_extension,
    calc_shoulder_knee_angle,
    calc_leg_symmetry,
    calc_trunk_vertical,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MetricResult:
    """Single metric result with FINA deduction info.

    ``zone="no_data"`` means the metric's required inputs were missing
    or entirely occluded; ``deduction`` is 0 and the metric is excluded
    from overall scoring.
    """

    name: str
    value: float | None
    unit: str
    deduction: float
    zone: str            # "clean" | "minor" | "major" | "no_data"
    max_value: float


@dataclass
class SetReport:
    """Complete analysis report for one recorded set."""

    metrics: list[MetricResult] = field(default_factory=list)
    overall_score: float | None = None
    phases: list[dict] = field(default_factory=list)
    correlation: float | None = None


# ---------------------------------------------------------------------------
# FINA deduction logic
# ---------------------------------------------------------------------------

def compute_deduction(value: float, config: dict, metric: str = "") -> tuple[float, str]:
    """Apply FINA threshold rules to a metric value.

    FINA deduction scale (Edriss 2024, Figures 2 & 3):
        0–15° deviation  → -0.2
        15–30° deviation → -0.5
        >30° deviation    → -1.0
    """
    fina = config["fina"]

    if metric and metric in fina and isinstance(fina[metric], dict):
        m = fina[metric]
        inverted = m["clean"] > m["major"]  # higher-is-better scale
        if inverted:
            if value > m["clean"]:
                return (m.get("clean_ded", 0.0), "clean")
            if value > m["minor"]:
                return (m.get("minor_ded", 0.2), "minor")
            return (m.get("major_ded", 0.5), "major")
        else:
            if value < m["clean"]:
                return (m.get("clean_ded", 0.0), "clean")
            if value < m["minor"]:
                return (m.get("minor_ded", 0.2), "minor")
            return (m.get("major_ded", 0.5), "major")

    if value < fina["clean_threshold_deg"]:
        return (fina["clean_deduction"], "clean")
    if value < fina["minor_deduction_deg"]:
        return (fina["minor_deduction"], "minor")
    return (fina["major_deduction"], "major")


# ---------------------------------------------------------------------------
# Small helpers for no_data aware aggregation
# ---------------------------------------------------------------------------

def _nanmean_or_none(arr, min_samples: int = 1) -> float | None:
    """Return nan-safe mean, or None if nothing usable."""
    if arr is None or len(arr) == 0:
        return None
    arr = np.asarray(arr, dtype=float)
    valid = arr[~np.isnan(arr)]
    if len(valid) < min_samples:
        return None
    return float(np.mean(valid))


def _no_data(name: str, unit: str, max_value: float) -> MetricResult:
    return MetricResult(
        name=name, value=None, unit=unit,
        deduction=0.0, zone="no_data", max_value=max_value,
    )


# ---------------------------------------------------------------------------
# Individual metric computation functions
# ---------------------------------------------------------------------------

def compute_leg_deviation(imu_df: pd.DataFrame) -> float:
    """Mean deviation of IMU tilt angle from 90° vertical."""
    records = imu_df[["ax", "ay", "az"]].to_dict("records")
    tilt = calc_imu_tilt(records)
    tilt_smooth = smooth(tilt, window=15)
    return float(np.mean(np.abs(tilt_smooth - 90.0)))


def compute_smoothness(imu_df: pd.DataFrame) -> float:
    """Jerk of gyroscope magnitude (lower = smoother motion)."""
    gx = imu_df["gx"].values
    gy = imu_df["gy"].values
    gz = imu_df["gz"].values
    gyro_mag = np.sqrt(gx**2 + gy**2 + gz**2)
    smoothed = smooth(gyro_mag, window=5)
    return float(np.mean(np.abs(np.gradient(smoothed))))


def compute_stability(imu_df: pd.DataFrame, phase_bounds: tuple[float, float]) -> float:
    """Standard deviation of tilt angle within a phase (lower = stabler)."""
    t_start, t_end = phase_bounds
    mask = (imu_df["timestamp_local"] >= t_start) & (imu_df["timestamp_local"] <= t_end)
    filtered = imu_df.loc[mask]
    if filtered.empty:
        return 0.0
    records = filtered[["ax", "ay", "az"]].to_dict("records")
    tilt = calc_imu_tilt(records)
    return float(np.std(tilt))


def compute_leg_height_index(landmarks_df: pd.DataFrame) -> float | None:
    """Leg height index ≈ fraction of leg length lifted above hip, per frame,
    averaged. Returns value in percent (0–100) matching Yue 2023 convention.

    This is a proxy — paper measures fraction above *water line* (AB/AC); we
    approximate with hip level because the waterline is rarely detectable in
    poolside footage.
    """
    if landmarks_df is None or landmarks_df.empty:
        return None
    cols = ["right_hip_x", "right_hip_y", "right_knee_x", "right_knee_y",
            "right_ankle_x", "right_ankle_y",
            "right_hip_vis", "right_knee_vis", "right_ankle_vis"]
    if not all(c in landmarks_df.columns for c in cols):
        return None

    lifts: list[float] = []
    for _, row in landmarks_df.iterrows():
        if (float(row["right_hip_vis"]) < 0.5 or
                float(row["right_knee_vis"]) < 0.5 or
                float(row["right_ankle_vis"]) < 0.5):
            continue
        hx, hy = row["right_hip_x"], row["right_hip_y"]
        kx, ky = row["right_knee_x"], row["right_knee_y"]
        ax, ay = row["right_ankle_x"], row["right_ankle_y"]
        leg_len = math.hypot(kx - hx, ky - hy) + math.hypot(ax - kx, ay - ky)
        if leg_len <= 1e-6:
            continue
        lift = hy - ay  # normalized coords, y grows downward → positive = ankle above hip
        lifts.append(max(0.0, lift / leg_len))
    if not lifts:
        return None
    return float(np.mean(lifts)) * 100.0


def compute_movement_frequency(imu_df: pd.DataFrame) -> float | None:
    """Movement frequency in Hz = peaks of |accel| per second.

    From Yue 2023 (standardized β = 0.345, p < 0.001) this is the
    strongest positive predictor of total score for hybrid figures.
    """
    if imu_df is None or imu_df.empty or len(imu_df) < 30:
        return None
    ax = imu_df["ax"].values.astype(float)
    ay = imu_df["ay"].values.astype(float)
    az = imu_df["az"].values.astype(float)
    mag = np.sqrt(ax**2 + ay**2 + az**2)
    peaks, _ = find_peaks(mag, prominence=0.25, distance=15)
    if "timestamp_local" in imu_df.columns:
        ts = imu_df["timestamp_local"].values.astype(float)
        duration = float(ts[-1] - ts[0]) if len(ts) > 1 else 0.0
    else:
        duration = len(imu_df) / 72.5
    if duration <= 0:
        return None
    return len(peaks) / duration


def compute_rotation_frequency(imu_df: pd.DataFrame) -> float | None:
    """Rotation frequency in deg/s (paper metric, Yue 2023).

    Uses magnitude of gyroscope signal as the rotation-rate estimate.
    The dominant axis is typically yaw (vertical spin around body);
    this simple |gyro| averages all three axes which still tracks the
    quantity the paper measured (total angular speed).
    """
    if imu_df is None or imu_df.empty or not all(c in imu_df.columns for c in ("gx", "gy", "gz")):
        return None
    gx = imu_df["gx"].values.astype(float)
    gy = imu_df["gy"].values.astype(float)
    gz = imu_df["gz"].values.astype(float)
    omega = np.sqrt(gx ** 2 + gy ** 2 + gz ** 2)
    return float(np.mean(omega))


def compute_pattern_durations(imu_df: pd.DataFrame) -> tuple[float | None, float | None]:
    """Returns (mean_pattern_duration, last_hf_duration) both in seconds.

    A "pattern change" is detected as a large direction flip of the
    acceleration vector. The mean gap between flips approximates Yue
    2023's `mean_pattern_duration`; the final segment (last flip →
    end) approximates `last_HF_duration`.
    """
    if imu_df is None or imu_df.empty or len(imu_df) < 50:
        return None, None
    if "timestamp_local" not in imu_df.columns:
        return None, None

    ts = imu_df["timestamp_local"].values.astype(float)
    if len(ts) < 2:
        return None, None
    duration = float(ts[-1] - ts[0])
    if duration <= 1.0:
        return None, None

    ax = imu_df["ax"].values.astype(float)
    ay = imu_df["ay"].values.astype(float)
    az = imu_df["az"].values.astype(float)
    mag = np.sqrt(ax ** 2 + ay ** 2 + az ** 2)
    smoothed = smooth(mag, window=11)
    # Peaks spaced ≥0.5 s apart mark pattern boundaries
    peaks, _ = find_peaks(smoothed, prominence=0.3, distance=36)
    if len(peaks) < 2:
        return None, None

    peak_ts = ts[peaks]
    gaps = np.diff(peak_ts)
    mean_pattern = float(np.mean(gaps)) if len(gaps) else None
    last_hf = float(ts[-1] - peak_ts[-1])
    return mean_pattern, last_hf


def compute_explosive_power(imu_df: pd.DataFrame) -> float | None:
    """95th-percentile of |acceleration - 1 g| (unit: g).

    A burst-style metric — captures peak output during jumps / kicks.
    """
    if imu_df is None or imu_df.empty:
        return None
    ax = imu_df["ax"].values.astype(float)
    ay = imu_df["ay"].values.astype(float)
    az = imu_df["az"].values.astype(float)
    mag = np.sqrt(ax ** 2 + ay ** 2 + az ** 2)
    dynamic = np.abs(mag - 1.0)  # remove gravity baseline
    if len(dynamic) == 0:
        return None
    return float(np.percentile(dynamic, 95))


def compute_energy_index(imu_df: pd.DataFrame) -> float | None:
    """Integral of dynamic acceleration magnitude over duration, in g·s/s.

    Proxy for metabolic cost (higher = more energy expended).
    """
    if imu_df is None or imu_df.empty or "timestamp_local" not in imu_df.columns:
        return None
    ts = imu_df["timestamp_local"].values.astype(float)
    if len(ts) < 2:
        return None
    duration = float(ts[-1] - ts[0])
    if duration <= 0:
        return None
    ax = imu_df["ax"].values.astype(float)
    ay = imu_df["ay"].values.astype(float)
    az = imu_df["az"].values.astype(float)
    dynamic = np.abs(np.sqrt(ax**2 + ay**2 + az**2) - 1.0)
    return float(np.trapz(dynamic, ts) / duration)


def compute_motion_complexity(imu_df: pd.DataFrame) -> float | None:
    """Spectral entropy of acceleration magnitude — higher = more varied / complex motion.

    Uses Welch-free estimator: normalized power spectrum then Shannon entropy.
    Range roughly 0 (single sine wave) .. ~6 bits (broadband noise).
    """
    if imu_df is None or imu_df.empty or len(imu_df) < 64:
        return None
    ax = imu_df["ax"].values.astype(float)
    ay = imu_df["ay"].values.astype(float)
    az = imu_df["az"].values.astype(float)
    mag = np.sqrt(ax**2 + ay**2 + az**2) - 1.0   # remove gravity
    # FFT magnitude as power proxy
    spec = np.abs(np.fft.rfft(mag))
    spec_sum = spec.sum()
    if spec_sum <= 0:
        return None
    p = spec / spec_sum
    # Drop the DC bin and any zero bins to avoid log(0)
    p = p[1:]
    p = p[p > 1e-10]
    if len(p) == 0:
        return None
    return float(-np.sum(p * np.log2(p)))


# ---------------------------------------------------------------------------
# Set report orchestrator
# ---------------------------------------------------------------------------

def compute_set_report(
    arm_imu_df: pd.DataFrame,
    leg_imu_df: pd.DataFrame | None,
    vision_df: pd.DataFrame,
    landmarks_df: pd.DataFrame | None,
    config: dict,
) -> SetReport:
    """Compute all metrics and produce a complete set report.

    Metrics whose inputs are unavailable or entirely occluded are emitted
    with ``zone="no_data"`` and ``value=None``; they contribute 0
    deduction and are excluded from ``overall_score``. If fewer than
    two metrics have real data the overall score is ``None``.
    """
    from dashboard.core.phase_detect import detect_phases

    metrics: list[MetricResult] = []
    has_arm_imu = arm_imu_df is not None and not arm_imu_df.empty
    has_leg_imu = leg_imu_df is not None and not leg_imu_df.empty
    has_vision = vision_df is not None and not vision_df.empty
    has_landmarks = landmarks_df is not None and not landmarks_df.empty

    # Phase detection
    if has_arm_imu:
        phases = detect_phases(arm_imu_df)
    else:
        phases = [
            {"name": "准备", "start": 0.0, "end": 0.33, "zone_color": "#09AB3B"},
            {"name": "动作", "start": 0.33, "end": 0.66, "zone_color": "#FACA2B"},
            {"name": "恢复", "start": 0.66, "end": 1.0, "zone_color": "#09AB3B"},
        ]

    # 1. leg_deviation — prefer dedicated leg IMU, fall back to vision, then arm IMU.
    dev_val = None
    if has_leg_imu:
        dev_val = compute_leg_deviation(leg_imu_df)
    elif has_landmarks:
        dev_val = _nanmean_or_none(calc_leg_deviation_vision(landmarks_df), min_samples=3)
    if dev_val is None:
        metrics.append(_no_data("leg_deviation", "deg", 90.0))
    else:
        d, z = compute_deduction(dev_val, config, metric="leg_deviation")
        metrics.append(MetricResult("leg_deviation", dev_val, "deg", d, z, 90.0))

    # 2. leg_height_index (Vision, paper-inspired)
    height_val = compute_leg_height_index(landmarks_df) if has_landmarks else None
    if height_val is None:
        metrics.append(_no_data("leg_height_index", "%", 50.0))
    else:
        # Score band: elite teams 32%+ (clean), 25-32% minor, <25% major
        if height_val >= 32.0:
            height_d, height_z = 0.0, "clean"
        elif height_val >= 25.0:
            height_d, height_z = 0.2, "minor"
        else:
            height_d, height_z = 0.5, "major"
        metrics.append(MetricResult(
            "leg_height_index", height_val, "%", height_d, height_z, 50.0,
        ))

    # 3. knee_extension
    knee_val = _nanmean_or_none(calc_knee_extension(landmarks_df), min_samples=3) if has_landmarks else None
    if knee_val is None:
        metrics.append(_no_data("knee_extension", "deg", 180.0))
    else:
        d, z = compute_deduction(knee_val, config, metric="knee_extension")
        metrics.append(MetricResult("knee_extension", knee_val, "deg", d, z, 180.0))

    # 4. shoulder_knee_alignment — Edriss 2024's strongest single predictor (r=-0.444)
    align_val = _nanmean_or_none(calc_shoulder_knee_angle(landmarks_df), min_samples=3) if has_landmarks else None
    if align_val is None:
        metrics.append(_no_data("shoulder_knee_alignment", "deg", 180.0))
    else:
        d, z = compute_deduction(align_val, config, metric="shoulder_knee_alignment")
        metrics.append(MetricResult("shoulder_knee_alignment", align_val, "deg", d, z, 180.0))

    # 5. trunk_vertical
    trunk_val = _nanmean_or_none(calc_trunk_vertical(landmarks_df), min_samples=3) if has_landmarks else None
    if trunk_val is None:
        metrics.append(_no_data("trunk_vertical", "deg", 90.0))
    else:
        d, z = compute_deduction(trunk_val, config, metric="trunk_vertical")
        metrics.append(MetricResult("trunk_vertical", trunk_val, "deg", d, z, 90.0))

    # 6. leg_symmetry
    sym_val = _nanmean_or_none(calc_leg_symmetry(landmarks_df), min_samples=3) if has_landmarks else None
    if sym_val is None:
        metrics.append(_no_data("leg_symmetry", "deg", 90.0))
    else:
        d, z = compute_deduction(sym_val, config, metric="leg_symmetry")
        metrics.append(MetricResult("leg_symmetry", sym_val, "deg", d, z, 90.0))

    # 7. smoothness (IMU)
    smooth_parts: list[float] = []
    if has_arm_imu:
        smooth_parts.append(compute_smoothness(arm_imu_df))
    if has_leg_imu:
        smooth_parts.append(compute_smoothness(leg_imu_df))
    if not smooth_parts:
        metrics.append(_no_data("smoothness", "deg/s^2", 50.0))
    else:
        smooth_val = float(np.mean(smooth_parts))
        d, z = compute_deduction(smooth_val, config)
        metrics.append(MetricResult("smoothness", smooth_val, "deg/s^2", d, z, 50.0))

    # 8. stability (IMU within active phase)
    if len(phases) >= 2:
        active_phase = phases[1]
        stab_bounds = (active_phase["start"], active_phase["end"])
    elif has_arm_imu:
        ts = arm_imu_df["timestamp_local"]
        stab_bounds = (float(ts.iloc[0]), float(ts.iloc[-1]))
    else:
        stab_bounds = (0.0, 1.0)

    stab_parts: list[float] = []
    if has_arm_imu:
        stab_parts.append(compute_stability(arm_imu_df, stab_bounds))
    if has_leg_imu:
        stab_parts.append(compute_stability(leg_imu_df, stab_bounds))
    if not stab_parts:
        metrics.append(_no_data("stability", "deg", 45.0))
    else:
        stab_val = float(np.mean(stab_parts))
        d, z = compute_deduction(stab_val, config)
        metrics.append(MetricResult("stability", stab_val, "deg", d, z, 45.0))

    # 9. movement_frequency (IMU, Yue 2023) — primarily from the leg/body IMU
    mov_source = leg_imu_df if has_leg_imu else (arm_imu_df if has_arm_imu else None)
    mov_val = compute_movement_frequency(mov_source) if mov_source is not None else None
    if mov_val is None:
        metrics.append(_no_data("movement_frequency", "Hz", 3.0))
    else:
        # Elite band (Yue 2023 Table 2): top-5 teams 1.92 ± 0.15 Hz.
        if 1.6 <= mov_val <= 2.2:
            d, z = 0.0, "clean"
        elif 1.3 <= mov_val <= 2.6:
            d, z = 0.2, "minor"
        else:
            d, z = 0.4, "major"
        metrics.append(MetricResult("movement_frequency", mov_val, "Hz", d, z, 3.0))

    # 10. rotation_frequency (IMU, Yue 2023) — mean angular speed in deg/s.
    rot_val = compute_rotation_frequency(mov_source) if mov_source is not None else None
    if rot_val is None:
        metrics.append(_no_data("rotation_frequency", "deg/s", 120.0))
    else:
        # Yue 2023 Table 2: top-5 teams 44.95 ± 10.07 deg/s.
        if 35.0 <= rot_val <= 55.0:
            d, z = 0.0, "clean"
        elif 25.0 <= rot_val <= 70.0:
            d, z = 0.2, "minor"
        else:
            d, z = 0.3, "major"
        metrics.append(MetricResult("rotation_frequency", rot_val, "deg/s", d, z, 120.0))

    # 11 + 12. pattern durations (IMU, Yue 2023)
    mean_pat, last_hf = compute_pattern_durations(mov_source) if mov_source is not None else (None, None)
    if mean_pat is None:
        metrics.append(_no_data("mean_pattern_duration", "s", 10.0))
    else:
        # Yue 2023: top-5 teams ~5.45 s. Wider tolerance here since we're
        # estimating from single-sensor IMU, not team video.
        if 3.0 <= mean_pat <= 8.0:
            d, z = 0.0, "clean"
        elif 1.5 <= mean_pat <= 12.0:
            d, z = 0.2, "minor"
        else:
            d, z = 0.3, "major"
        metrics.append(MetricResult("mean_pattern_duration", mean_pat, "s", d, z, 12.0))

    if last_hf is None:
        metrics.append(_no_data("last_hf_duration", "s", 20.0))
    else:
        # Yue 2023 top-5: ~17.0 s. But our recordings are typically much
        # shorter than a full routine, so don't over-penalize; use wider band.
        d, z = 0.0, "clean"
        metrics.append(MetricResult("last_hf_duration", last_hf, "s", d, z, 25.0))

    # 13. explosive_power — our unique IMU metric (peak dynamic acceleration)
    exp_val = compute_explosive_power(mov_source) if mov_source is not None else None
    if exp_val is None:
        metrics.append(_no_data("explosive_power", "g", 3.0))
    else:
        # Dynamic acceleration above gravity. Higher is more explosive.
        if exp_val >= 1.2:
            d, z = 0.0, "clean"
        elif exp_val >= 0.6:
            d, z = 0.1, "minor"
        else:
            d, z = 0.3, "major"
        metrics.append(MetricResult("explosive_power", exp_val, "g", d, z, 3.0))

    # 14. energy_index — metabolic-cost proxy (integral of dynamic accel)
    energy_val = compute_energy_index(mov_source) if mov_source is not None else None
    if energy_val is None:
        metrics.append(_no_data("energy_index", "g", 1.0))
    else:
        # Neutral metric: we just report, no deduction (different techniques
        # require different energy). Zone indicates range.
        if energy_val >= 0.3:
            z = "clean"
        elif energy_val >= 0.15:
            z = "minor"
        else:
            z = "major"
        metrics.append(MetricResult("energy_index", energy_val, "g", 0.0, z, 1.0))

    # 15. motion_complexity — spectral entropy
    complex_val = compute_motion_complexity(mov_source) if mov_source is not None else None
    if complex_val is None:
        metrics.append(_no_data("motion_complexity", "bits", 7.0))
    else:
        # Neutral: 3–5 bits ≈ rhythmic motion, >5 ≈ varied / complex.
        if 3.0 <= complex_val <= 6.0:
            z = "clean"
        elif 2.0 <= complex_val <= 7.0:
            z = "minor"
        else:
            z = "major"
        metrics.append(MetricResult("motion_complexity", complex_val, "bits", 0.0, z, 7.0))

    # Overall score — only counts metrics that have real data
    real_metrics = [m for m in metrics if m.zone != "no_data"]
    if len(real_metrics) < 2:
        overall_score = None
    else:
        total_deductions = sum(m.deduction for m in real_metrics)
        overall_score = max(0.0, min(10.0, 10.0 - total_deductions))

    # IMU ↔ vision correlation (only when both present)
    correlation: float | None = None
    if has_arm_imu and has_vision:
        try:
            imu_tilt = calc_imu_tilt(
                arm_imu_df[["ax", "ay", "az"]].to_dict("records")
            )
            vision_angles = vision_df["angle_deg"].values
            common_len = min(len(imu_tilt), len(vision_angles))
            if common_len > 1:
                imu_interp = np.interp(
                    np.linspace(0, 1, common_len),
                    np.linspace(0, 1, len(imu_tilt)),
                    imu_tilt,
                )
                vis_interp = np.interp(
                    np.linspace(0, 1, common_len),
                    np.linspace(0, 1, len(vision_angles)),
                    vision_angles,
                )
                corr_matrix = np.corrcoef(imu_interp, vis_interp)
                correlation = float(corr_matrix[0, 1])
        except (ValueError, IndexError, KeyError):
            correlation = None

    return SetReport(
        metrics=metrics,
        overall_score=overall_score,
        phases=phases,
        correlation=correlation,
    )
