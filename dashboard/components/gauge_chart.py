"""Gauge chart builders for FINA scoring visualization.

Pure functions that take MetricResult dataclasses and return Plotly figures.
No Streamlit dependency -- importable by the training page and testable in isolation.
"""

import plotly.graph_objects as go

from dashboard.components import CHART_THEME
from dashboard.core.scoring import MetricResult


def build_gauge(
    metric: MetricResult,
    config: dict,
    target: float | None = None,
) -> go.Figure:
    """Build a single gauge chart for a metric with FINA zone coloring.

    Args:
        metric: MetricResult with value, name, max_value, zone info.
        config: Full config dict with config["fina"] threshold keys.
        target: Optional target value for threshold reference line.

    Returns:
        Plotly Figure with go.Indicator gauge.
    """
    fina = config["fina"]
    clean_thresh = fina["clean_threshold_deg"]
    minor_thresh = fina["minor_deduction_deg"]

    threshold_kwargs = {}
    if target is not None:
        threshold_kwargs["threshold"] = {
            "line": {"color": "#262730", "width": 2},
            "thickness": 0.75,
            "value": target,
        }

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=metric.value,
            number={"font": {"size": 28, "family": "Source Sans Pro"}},
            title={"text": metric.name, "font": {"size": 14}},
            gauge={
                "axis": {
                    "range": [0, metric.max_value],
                    "tickfont": {"size": 11},
                },
                "bar": {"color": "#0068C9"},
                "steps": [
                    {"range": [0, clean_thresh], "color": "#09AB3B"},
                    {"range": [clean_thresh, minor_thresh], "color": "#FACA2B"},
                    {"range": [minor_thresh, metric.max_value], "color": "#FF4B4B"},
                ],
                **threshold_kwargs,
            },
        )
    )

    fig.update_layout(
        height=220,
        margin={"l": 0, "r": 0, "t": 48, "b": 0},
        paper_bgcolor=CHART_THEME["paper_bgcolor"],
        font_family=CHART_THEME["font_family"],
        font_color=CHART_THEME["font_color"],
    )

    return fig


def build_scoring_card(
    metrics: list[MetricResult],
    config: dict,
) -> list[go.Figure]:
    """Build a list of gauge figures for the scoring card.

    Args:
        metrics: List of MetricResult instances.
        config: Full config dict with FINA thresholds.

    Returns:
        List of Plotly Figures, one per metric.
    """
    return [build_gauge(m, config) for m in metrics]
