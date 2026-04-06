"""Unit tests for chart builder functions (gauge, timeline, waveform, fusion)."""

import numpy as np
import plotly.graph_objects as go
import pytest

from dashboard.core.scoring import MetricResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sample_metric() -> MetricResult:
    """Create a sample MetricResult for testing."""
    return MetricResult(
        name="腿部垂直偏差",
        value=12.5,
        unit="deg",
        deduction=0.0,
        zone="clean",
        max_value=90.0,
    )


def _sample_config() -> dict:
    """Create a sample config dict with FINA thresholds."""
    return {
        "fina": {
            "clean_threshold_deg": 15,
            "minor_deduction_deg": 30,
            "clean_deduction": 0.0,
            "minor_deduction": 0.2,
            "major_deduction": 0.5,
        },
    }


def _sample_metrics_list() -> list[MetricResult]:
    """Create a list of 5 MetricResult instances for scoring card."""
    return [
        MetricResult(name="腿部垂直偏差", value=12.5, unit="deg", deduction=0.0, zone="clean", max_value=90.0),
        MetricResult(name="腿部高度指数", value=45.0, unit="deg", deduction=0.2, zone="minor", max_value=180.0),
        MetricResult(name="肩膝对齐角度", value=8.0, unit="deg", deduction=0.0, zone="clean", max_value=90.0),
        MetricResult(name="动作流畅度", value=5.2, unit="deg/s^2", deduction=0.0, zone="clean", max_value=50.0),
        MetricResult(name="展示稳定性", value=35.0, unit="deg", deduction=0.5, zone="major", max_value=45.0),
    ]


def _sample_phases() -> list[dict]:
    """Create sample phase dicts for timeline testing."""
    return [
        {"name": "准备", "start": 0.0, "end": 2.5, "zone_color": "#09AB3B"},
        {"name": "动作", "start": 2.5, "end": 7.0, "zone_color": "#FACA2B"},
        {"name": "恢复", "start": 7.0, "end": 10.0, "zone_color": "#09AB3B"},
    ]


# ---------------------------------------------------------------------------
# Gauge chart tests
# ---------------------------------------------------------------------------

class TestBuildGauge:
    """Tests for build_gauge function."""

    def test_build_gauge_returns_figure(self):
        from dashboard.components.gauge_chart import build_gauge
        fig = build_gauge(_sample_metric(), _sample_config())
        assert isinstance(fig, go.Figure)

    def test_build_gauge_has_indicator(self):
        from dashboard.components.gauge_chart import build_gauge
        fig = build_gauge(_sample_metric(), _sample_config())
        assert fig.data[0].type == "indicator"

    def test_build_gauge_height(self):
        from dashboard.components.gauge_chart import build_gauge
        fig = build_gauge(_sample_metric(), _sample_config())
        assert fig.layout.height == 220

    def test_build_gauge_three_steps(self):
        from dashboard.components.gauge_chart import build_gauge
        fig = build_gauge(_sample_metric(), _sample_config())
        steps = fig.data[0].gauge.steps
        assert len(steps) == 3


class TestBuildScoringCard:
    """Tests for build_scoring_card function."""

    def test_build_scoring_card_returns_list(self):
        from dashboard.components.gauge_chart import build_scoring_card
        result = build_scoring_card(_sample_metrics_list(), _sample_config())
        assert isinstance(result, list)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Phase timeline tests
# ---------------------------------------------------------------------------

class TestBuildPhaseTimeline:
    """Tests for build_phase_timeline function."""

    def test_build_phase_timeline_returns_figure(self):
        from dashboard.components.timeline_chart import build_phase_timeline
        fig = build_phase_timeline(_sample_phases())
        assert isinstance(fig, go.Figure)

    def test_build_phase_timeline_three_traces(self):
        from dashboard.components.timeline_chart import build_phase_timeline
        fig = build_phase_timeline(_sample_phases())
        assert len(fig.data) == 3

    def test_build_phase_timeline_horizontal(self):
        from dashboard.components.timeline_chart import build_phase_timeline
        fig = build_phase_timeline(_sample_phases())
        for trace in fig.data:
            assert trace.orientation == "h"

    def test_build_phase_timeline_height(self):
        from dashboard.components.timeline_chart import build_phase_timeline
        fig = build_phase_timeline(_sample_phases())
        assert fig.layout.height == 80


# ---------------------------------------------------------------------------
# Synthetic data for waveform / fusion tests
# ---------------------------------------------------------------------------

def _sample_time() -> np.ndarray:
    return np.linspace(0, 10, 100)


def _sample_accel() -> np.ndarray:
    return np.sin(np.linspace(0, 4 * np.pi, 100))


def _sample_gyro() -> np.ndarray:
    return np.cos(np.linspace(0, 4 * np.pi, 100))


def _sample_tilt() -> np.ndarray:
    return 45.0 + 10.0 * np.sin(np.linspace(0, 2 * np.pi, 100))


def _sample_vision_angle() -> np.ndarray:
    return 90.0 + 15.0 * np.sin(np.linspace(0, 2 * np.pi, 100))


def _sample_imu_tilt() -> np.ndarray:
    return 45.0 + 12.0 * np.sin(np.linspace(0, 2 * np.pi, 100) + 0.3)


# ---------------------------------------------------------------------------
# IMU waveform tests
# ---------------------------------------------------------------------------

class TestBuildImuWaveform:
    """Tests for build_imu_waveform function."""

    def test_build_imu_waveform_returns_figure(self):
        from dashboard.components.waveform_chart import build_imu_waveform
        fig = build_imu_waveform(_sample_time(), _sample_accel(), _sample_gyro(), _sample_tilt())
        assert isinstance(fig, go.Figure)

    def test_build_imu_waveform_three_traces(self):
        from dashboard.components.waveform_chart import build_imu_waveform
        fig = build_imu_waveform(_sample_time(), _sample_accel(), _sample_gyro(), _sample_tilt())
        assert len(fig.data) == 3
        for trace in fig.data:
            assert trace.type == "scatter"

    def test_build_imu_waveform_height_300(self):
        from dashboard.components.waveform_chart import build_imu_waveform
        fig = build_imu_waveform(_sample_time(), _sample_accel(), _sample_gyro(), _sample_tilt())
        assert fig.layout.height == 300


# ---------------------------------------------------------------------------
# IMU waveform dual-node tests
# ---------------------------------------------------------------------------

class TestBuildImuWaveformDualNode:
    """Tests for dual-node overlay in build_imu_waveform."""

    def test_dual_node_returns_figure(self):
        """Dual node waveform returns a valid figure."""
        from dashboard.components.waveform_chart import build_imu_waveform
        t = np.linspace(0, 2, 50)
        fig = build_imu_waveform(
            time=t, accel_mag=np.ones(50), gyro_mag=np.ones(50) * 2,
            tilt_angle=np.ones(50) * 45, node_label="forearm",
            time2=t, accel_mag2=np.ones(50) * 0.8,
            tilt_angle2=np.ones(50) * 60, node_label2="shin",
        )
        assert fig is not None

    def test_dual_node_more_traces_than_single(self):
        """Dual node should have more traces than single node."""
        from dashboard.components.waveform_chart import build_imu_waveform
        t = np.linspace(0, 2, 50)
        fig_single = build_imu_waveform(
            time=t, accel_mag=np.ones(50), gyro_mag=np.ones(50) * 2,
            tilt_angle=np.ones(50) * 45,
        )
        fig_dual = build_imu_waveform(
            time=t, accel_mag=np.ones(50), gyro_mag=np.ones(50) * 2,
            tilt_angle=np.ones(50) * 45, node_label="forearm",
            time2=t, accel_mag2=np.ones(50) * 0.8,
            tilt_angle2=np.ones(50) * 60, node_label2="shin",
        )
        assert len(fig_dual.data) > len(fig_single.data)

    def test_single_node_backward_compat(self):
        """Without dual node params, behaves same as before."""
        from dashboard.components.waveform_chart import build_imu_waveform
        t = np.linspace(0, 2, 50)
        fig = build_imu_waveform(
            time=t, accel_mag=np.ones(50), gyro_mag=np.ones(50) * 2,
            tilt_angle=np.ones(50) * 45,
        )
        assert len(fig.data) == 3  # accel, tilt, gyro


# ---------------------------------------------------------------------------
# Fusion dual-axis chart tests
# ---------------------------------------------------------------------------

class TestBuildFusionChart:
    """Tests for build_fusion_chart function."""

    def test_build_fusion_chart_returns_tuple(self):
        from dashboard.components.waveform_chart import build_fusion_chart
        result = build_fusion_chart(_sample_time(), _sample_vision_angle(), _sample_imu_tilt())
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], go.Figure)

    def test_build_fusion_chart_two_traces(self):
        from dashboard.components.waveform_chart import build_fusion_chart
        fig, _ = build_fusion_chart(_sample_time(), _sample_vision_angle(), _sample_imu_tilt())
        assert len(fig.data) == 2
        for trace in fig.data:
            assert trace.type == "scatter"

    def test_build_fusion_chart_height_350(self):
        from dashboard.components.waveform_chart import build_fusion_chart
        fig, _ = build_fusion_chart(_sample_time(), _sample_vision_angle(), _sample_imu_tilt())
        assert fig.layout.height == 350

    def test_build_fusion_chart_correlation(self):
        from dashboard.components.waveform_chart import build_fusion_chart
        _, corr = build_fusion_chart(_sample_time(), _sample_vision_angle(), _sample_imu_tilt())
        assert isinstance(corr, float)
        assert -1.0 <= corr <= 1.0
