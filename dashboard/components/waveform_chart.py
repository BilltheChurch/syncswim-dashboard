"""IMU waveform and fusion dual-axis chart builders.

Pure functions that take numpy arrays and return Plotly figures.
No Streamlit dependency -- importable by the training page and testable in isolation.
"""

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.components import CHART_THEME


def build_imu_waveform(
    time: np.ndarray,
    accel_mag: np.ndarray,
    gyro_mag: np.ndarray,
    tilt_angle: np.ndarray,
) -> go.Figure:
    """Build an IMU waveform chart with 3 traces.

    Args:
        time: Time array in seconds.
        accel_mag: Accelerometer magnitude array.
        gyro_mag: Gyroscope magnitude array.
        tilt_angle: Fused tilt angle array.

    Returns:
        Plotly Figure with 3 scatter traces.
    """
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=time,
            y=accel_mag,
            name="加速度",
            line={"color": "#0068C9", "width": 1.5},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=time,
            y=gyro_mag,
            name="角速度",
            line={"color": "#FF8C00", "width": 1.5},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=time,
            y=tilt_angle,
            name="倾斜角",
            line={"color": "#7D44CF", "width": 2},
        )
    )

    fig.update_layout(
        height=300,
        xaxis_title="时间 (秒)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        template=CHART_THEME["template"],
        font_family=CHART_THEME["font_family"],
        font_color=CHART_THEME["font_color"],
        paper_bgcolor=CHART_THEME["paper_bgcolor"],
        plot_bgcolor=CHART_THEME["plot_bgcolor"],
        margin=CHART_THEME["margin"],
    )

    return fig


def build_fusion_chart(
    time: np.ndarray,
    vision_angle: np.ndarray,
    imu_tilt: np.ndarray,
) -> tuple[go.Figure, float | None]:
    """Build a dual-axis fusion chart overlaying vision angle and IMU tilt.

    Args:
        time: Time array in seconds.
        vision_angle: Vision joint angle array (degrees).
        imu_tilt: IMU tilt angle array (degrees).

    Returns:
        Tuple of (Plotly Figure, correlation coefficient or None).
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=time,
            y=vision_angle,
            name="视觉关节角度",
            line={"color": "#09AB3B", "width": 2},
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=time,
            y=imu_tilt,
            name="IMU 倾斜角",
            line={"color": "#0068C9", "width": 2},
        ),
        secondary_y=True,
    )

    fig.update_layout(
        height=350,
        xaxis_title="时间 (秒)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        template=CHART_THEME["template"],
        font_family=CHART_THEME["font_family"],
        font_color=CHART_THEME["font_color"],
        paper_bgcolor=CHART_THEME["paper_bgcolor"],
        plot_bgcolor=CHART_THEME["plot_bgcolor"],
        margin=CHART_THEME["margin"],
    )

    fig.update_yaxes(
        title_text="视觉关节角度 (deg)",
        title_font_size=14,
        title_font_color="#09AB3B",
        secondary_y=False,
    )
    fig.update_yaxes(
        title_text="IMU 倾斜角 (deg)",
        title_font_size=14,
        title_font_color="#0068C9",
        secondary_y=True,
    )

    # Compute correlation, masking NaN values
    mask = ~np.isnan(vision_angle) & ~np.isnan(imu_tilt)
    correlation: float | None = None
    if mask.sum() > 10:
        corr_matrix = np.corrcoef(vision_angle[mask], imu_tilt[mask])
        correlation = float(corr_matrix[0, 1])

    return fig, correlation
