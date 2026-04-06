"""Metrics orchestrator -- single entry point for training page analysis.

Combines data loading, scoring engine, and phase detection into one call.
"""
import pandas as pd

from dashboard.config import load_config
from dashboard.core.data_loader import load_imu, load_vision
from dashboard.core.landmarks import load_landmarks_csv
from dashboard.core.scoring import SetReport, compute_set_report


def compute_all_metrics(set_dir: str) -> SetReport | None:
    """Load data and compute all metrics for a recorded set.

    This is the single entry point for the training page. Loads all four
    data sources (arm IMU, leg IMU, vision, landmarks), loads config, and
    delegates to compute_set_report.

    Args:
        set_dir: Path to the set directory (e.g. 'data/set_002_20260319_165319').

    Returns:
        SetReport with all metrics, or None if all DataFrames are empty.
    """
    arm_imu_df = load_imu(set_dir, node="NODE_A1")
    # Try NODE_A2 first (actual device name), fall back to NODE_L1
    leg_imu_df = load_imu(set_dir, node="NODE_A2")
    if leg_imu_df.empty:
        leg_imu_df = load_imu(set_dir, node="NODE_L1")
    vision_df = load_vision(set_dir)
    landmarks_df = load_landmarks_csv(set_dir)

    has_any = (
        not arm_imu_df.empty
        or not leg_imu_df.empty
        or not vision_df.empty
        or not landmarks_df.empty
    )
    if not has_any:
        return None

    config = load_config()
    return compute_set_report(
        arm_imu_df,
        leg_imu_df if not leg_imu_df.empty else None,
        vision_df,
        landmarks_df if not landmarks_df.empty else None,
        config,
    )
