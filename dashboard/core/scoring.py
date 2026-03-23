"""Scoring engine for biomechanical metrics and FINA deductions.

Computes 5 metrics from IMU and vision DataFrames, applies FINA deduction
rules, and produces a structured SetReport dataclass.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from dashboard.core.analysis import calc_imu_tilt, smooth
from dashboard.core.angles import calc_angle


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

def compute_deduction(value: float, config: dict) -> tuple[float, str]:
    """Apply FINA threshold rules to a metric value.

    Args:
        value: The metric value (e.g., angle deviation in degrees).
        config: Full config dict with config["fina"] keys:
            clean_threshold_deg, minor_deduction_deg,
            clean_deduction, minor_deduction, major_deduction.

    Returns:
        Tuple of (deduction_amount, zone_name).
    """
    fina = config["fina"]
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
    imu_df: pd.DataFrame,
    vision_df: pd.DataFrame,
    config: dict,
) -> SetReport:
    """Compute all metrics and produce a complete set report.

    Handles partial data: skips IMU metrics if imu_df empty,
    skips vision metrics if vision_df empty.

    Args:
        imu_df: IMU DataFrame (may be empty).
        vision_df: Vision DataFrame (may be empty).
        config: Full config dict with fina thresholds.

    Returns:
        SetReport with metrics, overall_score, phases, and correlation.
    """
    from dashboard.core.phase_detect import detect_phases

    metrics: list[MetricResult] = []
    has_imu = not imu_df.empty
    has_vision = not vision_df.empty

    # Detect phases from IMU data (or fallback)
    if has_imu:
        phases = detect_phases(imu_df)
    else:
        phases = [
            {"name": "准备", "start": 0.0, "end": 0.33, "zone_color": "#09AB3B"},
            {"name": "动作", "start": 0.33, "end": 0.66, "zone_color": "#FACA2B"},
            {"name": "恢复", "start": 0.66, "end": 1.0, "zone_color": "#09AB3B"},
        ]

    # --- IMU metrics ---
    if has_imu:
        # Leg deviation
        dev_val = compute_leg_deviation(imu_df)
        dev_ded, dev_zone = compute_deduction(dev_val, config)
        metrics.append(MetricResult(
            name="leg_deviation", value=dev_val, unit="deg",
            deduction=dev_ded, zone=dev_zone, max_value=90.0,
        ))

        # Smoothness
        smooth_val = compute_smoothness(imu_df)
        smooth_ded, smooth_zone = compute_deduction(smooth_val, config)
        metrics.append(MetricResult(
            name="smoothness", value=smooth_val, unit="deg/s^2",
            deduction=smooth_ded, zone=smooth_zone, max_value=50.0,
        ))

        # Stability (use active phase bounds if available)
        if len(phases) >= 2:
            active_phase = phases[1]  # "动作" phase
            stab_bounds = (active_phase["start"], active_phase["end"])
        else:
            t_start = float(imu_df["timestamp_local"].iloc[0])
            t_end = float(imu_df["timestamp_local"].iloc[-1])
            stab_bounds = (t_start, t_end)

        stab_val = compute_stability(imu_df, stab_bounds)
        stab_ded, stab_zone = compute_deduction(stab_val, config)
        metrics.append(MetricResult(
            name="stability", value=stab_val, unit="deg",
            deduction=stab_ded, zone=stab_zone, max_value=45.0,
        ))

    # --- Vision metrics ---
    if has_vision:
        # Leg height index
        height_val = compute_leg_height_index(vision_df)
        height_ded, height_zone = compute_deduction(height_val, config)
        metrics.append(MetricResult(
            name="leg_height_index", value=height_val, unit="deg",
            deduction=height_ded, zone=height_zone, max_value=180.0,
        ))

        # Shoulder-knee alignment
        align_val = compute_shoulder_knee_alignment(vision_df)
        align_ded, align_zone = compute_deduction(align_val, config)
        metrics.append(MetricResult(
            name="shoulder_knee_alignment", value=align_val, unit="deg",
            deduction=align_ded, zone=align_zone, max_value=90.0,
        ))

    # Overall score
    total_deductions = sum(m.deduction for m in metrics)
    overall_score = max(0.0, 10.0 - total_deductions)

    # Correlation between IMU tilt and vision angle (if both present)
    correlation: float | None = None
    if has_imu and has_vision:
        try:
            imu_tilt = calc_imu_tilt(
                imu_df[["ax", "ay", "az"]].to_dict("records")
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
