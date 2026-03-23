"""Phase timeline chart builder.

Pure function that takes phase dicts and returns a Plotly horizontal stacked bar.
No Streamlit dependency -- importable by the training page and testable in isolation.
"""

import plotly.graph_objects as go

from dashboard.components import CHART_THEME


def build_phase_timeline(phases: list[dict]) -> go.Figure:
    """Build a horizontal stacked bar chart showing action phases.

    Args:
        phases: List of phase dicts with keys: name, start, end, zone_color.

    Returns:
        Plotly Figure with horizontal stacked bar traces.
    """
    fig = go.Figure()

    for phase in phases:
        duration = phase["end"] - phase["start"]
        fig.add_trace(
            go.Bar(
                y=["阶段"],
                x=[duration],
                name=phase["name"],
                orientation="h",
                marker_color=phase["zone_color"],
                text=phase["name"],
                textposition="inside",
                textfont={"size": 12, "color": "#FFFFFF"},
            )
        )

    fig.update_layout(
        barmode="stack",
        height=40,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        showlegend=False,
        xaxis={"title": "时间 (秒)", "title_font_size": 14},
        yaxis={"visible": False},
        template=CHART_THEME["template"],
        font_family=CHART_THEME["font_family"],
        font_color=CHART_THEME["font_color"],
        paper_bgcolor=CHART_THEME["paper_bgcolor"],
        plot_bgcolor=CHART_THEME["plot_bgcolor"],
    )

    return fig
