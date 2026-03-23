"""Metrics orchestrator -- single entry point for training page analysis.

Combines data loading, scoring engine, and phase detection into one call.
"""
import pandas as pd

from dashboard.config import load_config
from dashboard.core.data_loader import load_imu, load_vision
from dashboard.core.scoring import SetReport, compute_set_report


def compute_all_metrics(set_dir: str) -> SetReport | None:
    """Load data and compute all metrics for a recorded set.

    This is the single entry point for the training page. Loads IMU and
    vision DataFrames, loads config, and delegates to compute_set_report.

    Args:
        set_dir: Path to the set directory (e.g. 'data/set_002_20260319_165319').

    Returns:
        SetReport with all metrics, or None if both DataFrames are empty.
    """
    imu_df = load_imu(set_dir)
    vision_df = load_vision(set_dir)

    if imu_df.empty and vision_df.empty:
        return None

    config = load_config()
    return compute_set_report(imu_df, vision_df, config)
