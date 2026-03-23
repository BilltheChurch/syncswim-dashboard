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

    def test_build_gauge_height_200(self):
        from dashboard.components.gauge_chart import build_gauge
        fig = build_gauge(_sample_metric(), _sample_config())
        assert fig.layout.height == 200

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

    def test_build_phase_timeline_height_40(self):
        from dashboard.components.timeline_chart import build_phase_timeline
        fig = build_phase_timeline(_sample_phases())
        assert fig.layout.height == 40
