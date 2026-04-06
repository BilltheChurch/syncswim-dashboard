"""Scoring engine for biomechanical metrics and FINA deductions.

Computes 8 metrics from IMU and vision DataFrames, applies FINA deduction
rules, and produces a structured SetReport dataclass.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

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
    """Single metric result with FINA deduction info."""

    name: str
    value: float
    unit: str
    deduction: float
    zone: str
    max_value: float


@dataclass
class SetReport:
    """Complete analysis report for one recorded set."""

    metrics: list[MetricResult] = field(default_factory=list)
    overall_score: float = 10.0
    phases: list[dict] = field(default_factory=list)
    correlation: float | None = None


# ---------------------------------------------------------------------------
# FINA deduction logic
# ---------------------------------------------------------------------------

def compute_deduction(value: float, config: dict, metric: str = "") -> tuple[float, str]:
    """Apply FINA threshold rules to a metric value.

    When *metric* is provided and a per-metric sub-dict exists under
    ``config["fina"][metric]``, those thresholds are used instead of the
    global ones.  For "inverted" metrics where higher values are better
    (indicated by ``clean > major``), the comparison direction is reversed.

    Args:
        value: The metric value (e.g., angle deviation in degrees).
        config: Full config dict with config["fina"] keys.
        metric: Optional metric name for per-metric thresholds.

    Returns:
        Tuple of (deduction_amount, zone_name).
    """
    fina = config["fina"]

    # --- per-metric path ---
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

    # --- global fallback ---
    if value < fina["clean_threshold_deg"]:
        return (fina["clean_deduction"], "clean")
    if value < fina["minor_deduction_deg"]:
        return (fina["minor_deduction"], "minor")
    return (fina["major_deduction"], "major")


# ---------------------------------------------------------------------------
# Individual metric computation functions
# ---------------------------------------------------------------------------

def compute_leg_deviation(imu_df: pd.DataFrame) -> float:
    """Compute mean deviation of IMU tilt angle from 90 degrees vertical.

    Args:
        imu_df: DataFrame with columns ax, ay, az.

    Returns:
        Mean absolute deviation from 90 degrees.
    """
    records = imu_df[["ax", "ay", "az"]].to_dict("records")
    tilt = calc_imu_tilt(records)
    tilt_smooth = smooth(tilt, window=15)
    return float(np.mean(np.abs(tilt_smooth - 90.0)))


def compute_leg_height_index(vision_df: pd.DataFrame) -> float:
    """Compute leg height index from vision data.

    Phase 2 MVP: Without landmarks.csv, uses mean angle_deg as proxy metric.

    Args:
        vision_df: DataFrame with column angle_deg.

    Returns:
        Proxy metric value (mean angle_deg).
    """
    if "angle_deg" not in vision_df.columns or vision_df.empty:
        return 0.0
    return float(vision_df["angle_deg"].mean())


def compute_shoulder_knee_alignment(vision_df: pd.DataFrame) -> float:
    """Compute shoulder-knee alignment from vision data.

    Phase 2 MVP: Without landmarks.csv, uses 180 - mean(angle_deg) as proxy.

    Args:
        vision_df: DataFrame with column angle_deg.

    Returns:
        Proxy alignment metric value.
    """
    if "angle_deg" not in vision_df.columns or vision_df.empty:
        return 0.0
    return float(180.0 - vision_df["angle_deg"].mean())


def compute_smoothness(imu_df: pd.DataFrame) -> float:
    """Compute smoothness (jerk) from gyroscope magnitude.

    Jerk = mean absolute value of gradient of smoothed gyro magnitude.

    Args:
        imu_df: DataFrame with columns gx, gy, gz.

    Returns:
        Positive float jerk value.
    """
    gx = imu_df["gx"].values
    gy = imu_df["gy"].values
    gz = imu_df["gz"].values
    gyro_mag = np.sqrt(gx**2 + gy**2 + gz**2)
    smoothed = smooth(gyro_mag, window=5)
    return float(np.mean(np.abs(np.gradient(smoothed))))


def compute_stability(imu_df: pd.DataFrame, phase_bounds: tuple[float, float]) -> float:
    """Compute tilt stability within a phase boundary.

    Stability = standard deviation of tilt angle within the given time window.

    Args:
        imu_df: DataFrame with columns timestamp_local, ax, ay, az.
        phase_bounds: Tuple of (start_time, end_time) for the phase.

    Returns:
        Standard deviation of tilt angle (lower = more stable).
    """
    t_start, t_end = phase_bounds
    mask = (imu_df["timestamp_local"] >= t_start) & (imu_df["timestamp_local"] <= t_end)
    filtered = imu_df.loc[mask]

    if filtered.empty:
        return 0.0

    records = filtered[["ax", "ay", "az"]].to_dict("records")
    tilt = calc_imu_tilt(records)
    return float(np.std(tilt))


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
    """Compute all 8 metrics and produce a complete set report.

    Handles partial data gracefully: uses proxy values or defaults when
    a data source is missing, so the report always contains 8 metrics.

    Args:
        arm_imu_df: Arm/forearm IMU DataFrame (may be empty).
        leg_imu_df: Leg/shin IMU DataFrame, or None if unavailable.
        vision_df: Vision DataFrame (may be empty).
        landmarks_df: MediaPipe landmarks DataFrame, or None if unavailable.
        config: Full config dict with fina thresholds.

    Returns:
        SetReport with 8 metrics, overall_score, phases, and correlation.
    """
    from dashboard.core.phase_detect import detect_phases

    metrics: list[MetricResult] = []
    has_arm_imu = not arm_imu_df.empty
    has_leg_imu = leg_imu_df is not None and not leg_imu_df.empty
    has_vision = not vision_df.empty
    has_landmarks = landmarks_df is not None and not landmarks_df.empty

    # Detect phases from IMU data (or fallback)
    if has_arm_imu:
        phases = detect_phases(arm_imu_df)
    else:
        phases = [
            {"name": "准备", "start": 0.0, "end": 0.33, "zone_color": "#09AB3B"},
            {"name": "动作", "start": 0.33, "end": 0.66, "zone_color": "#FACA2B"},
            {"name": "恢复", "start": 0.66, "end": 1.0, "zone_color": "#09AB3B"},
        ]

    # ---------------------------------------------------------------
    # 1. leg_deviation (IMU + Vision fusion)
    # ---------------------------------------------------------------
    dev_val = 0.0
    if has_leg_imu:
        dev_val = compute_leg_deviation(leg_imu_df)
    elif has_landmarks:
        dev_val = float(np.mean(calc_leg_deviation_vision(landmarks_df)))
    elif has_arm_imu:
        dev_val = compute_leg_deviation(arm_imu_df)

    dev_ded, dev_zone = compute_deduction(dev_val, config, metric="leg_deviation")
    metrics.append(MetricResult(
        name="leg_deviation", value=dev_val, unit="deg",
        deduction=dev_ded, zone=dev_zone, max_value=90.0,
    ))

    # ---------------------------------------------------------------
    # 2. leg_height_index (Vision)
    # ---------------------------------------------------------------
    if has_landmarks:
        height_val = float(np.mean(calc_knee_extension(landmarks_df)))
    elif has_vision and "angle_deg" in vision_df.columns:
        height_val = float(vision_df["angle_deg"].mean())
    else:
        height_val = 0.0

    height_ded, height_zone = compute_deduction(height_val, config)
    metrics.append(MetricResult(
        name="leg_height_index", value=height_val, unit="deg",
        deduction=height_ded, zone=height_zone, max_value=180.0,
    ))

    # ---------------------------------------------------------------
    # 3. knee_extension (Vision - NEW, inverted)
    # ---------------------------------------------------------------
    if has_landmarks:
        knee_val = float(np.mean(calc_knee_extension(landmarks_df)))
    else:
        knee_val = 180.0  # assume straight, no penalty

    knee_ded, knee_zone = compute_deduction(knee_val, config, metric="knee_extension")
    metrics.append(MetricResult(
        name="knee_extension", value=knee_val, unit="deg",
        deduction=knee_ded, zone=knee_zone, max_value=180.0,
    ))

    # ---------------------------------------------------------------
    # 4. shoulder_knee_alignment (Vision, inverted)
    # ---------------------------------------------------------------
    if has_landmarks:
        align_val = float(np.mean(calc_shoulder_knee_angle(landmarks_df)))
    elif has_vision and "angle_deg" in vision_df.columns:
        align_val = float(180.0 - vision_df["angle_deg"].mean())
    else:
        align_val = 180.0

    align_ded, align_zone = compute_deduction(
        align_val, config, metric="shoulder_knee_alignment",
    )
    metrics.append(MetricResult(
        name="shoulder_knee_alignment", value=align_val, unit="deg",
        deduction=align_ded, zone=align_zone, max_value=180.0,
    ))

    # ---------------------------------------------------------------
    # 5. trunk_vertical (Vision - NEW)
    # ---------------------------------------------------------------
    if has_landmarks:
        trunk_val = float(np.mean(calc_trunk_vertical(landmarks_df)))
    else:
        trunk_val = 0.0  # assume vertical, no penalty

    trunk_ded, trunk_zone = compute_deduction(
        trunk_val, config, metric="trunk_vertical",
    )
    metrics.append(MetricResult(
        name="trunk_vertical", value=trunk_val, unit="deg",
        deduction=trunk_ded, zone=trunk_zone, max_value=90.0,
    ))

    # ---------------------------------------------------------------
    # 6. leg_symmetry (Vision - NEW)
    # ---------------------------------------------------------------
    if has_landmarks:
        sym_val = float(np.mean(calc_leg_symmetry(landmarks_df)))
    else:
        sym_val = 0.0

    sym_ded, sym_zone = compute_deduction(
        sym_val, config, metric="leg_symmetry",
    )
    metrics.append(MetricResult(
        name="leg_symmetry", value=sym_val, unit="deg",
        deduction=sym_ded, zone=sym_zone, max_value=90.0,
    ))

    # ---------------------------------------------------------------
    # 7. smoothness (IMU)
    # ---------------------------------------------------------------
    smooth_vals: list[float] = []
    if has_arm_imu:
        smooth_vals.append(compute_smoothness(arm_imu_df))
    if has_leg_imu:
        smooth_vals.append(compute_smoothness(leg_imu_df))

    smooth_val = float(np.mean(smooth_vals)) if smooth_vals else 0.0
    smooth_ded, smooth_zone = compute_deduction(smooth_val, config)
    metrics.append(MetricResult(
        name="smoothness", value=smooth_val, unit="deg/s^2",
        deduction=smooth_ded, zone=smooth_zone, max_value=50.0,
    ))

    # ---------------------------------------------------------------
    # 8. stability (IMU)
    # ---------------------------------------------------------------
    if len(phases) >= 2:
        active_phase = phases[1]  # "动作" phase
        stab_bounds = (active_phase["start"], active_phase["end"])
    elif has_arm_imu:
        t_start = float(arm_imu_df["timestamp_local"].iloc[0])
        t_end = float(arm_imu_df["timestamp_local"].iloc[-1])
        stab_bounds = (t_start, t_end)
    else:
        stab_bounds = (0.0, 1.0)

    stab_vals: list[float] = []
    if has_arm_imu:
        stab_vals.append(compute_stability(arm_imu_df, stab_bounds))
    if has_leg_imu:
        stab_vals.append(compute_stability(leg_imu_df, stab_bounds))

    stab_val = float(np.mean(stab_vals)) if stab_vals else 0.0
    stab_ded, stab_zone = compute_deduction(stab_val, config)
    metrics.append(MetricResult(
        name="stability", value=stab_val, unit="deg",
        deduction=stab_ded, zone=stab_zone, max_value=45.0,
    ))

    # Overall score
    total_deductions = sum(m.deduction for m in metrics)
    overall_score = max(0.0, 10.0 - total_deductions)

    # Correlation between IMU tilt and vision angle (if both present)
    correlation: float | None = None
    if has_arm_imu and has_vision:
        try:
            imu_tilt = calc_imu_tilt(
                arm_imu_df[["ax", "ay", "az"]].to_dict("records")
            )
            vision_angles = vision_df["angle_deg"].values
            # Interpolate to common length
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
