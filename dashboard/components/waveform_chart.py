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
    *,
    node_label: str = "IMU",
    time2: np.ndarray | None = None,
    accel_mag2: np.ndarray | None = None,
    tilt_angle2: np.ndarray | None = None,
    node_label2: str = "IMU 2",
) -> go.Figure:
    """Build an IMU waveform chart with 3 traces on dual Y axes.

    Accelerometer and tilt share the left Y axis (small values in G/degrees).
    Gyroscope uses the right Y axis (large values in deg/s).

    Optionally overlays a second IMU node's accel and tilt as dashed traces.

    Args:
        time: Time array in seconds.
        accel_mag: Accelerometer magnitude array.
        gyro_mag: Gyroscope magnitude array.
        tilt_angle: Fused tilt angle array.
        node_label: Display label for the primary node traces.
        time2: Second node time array (enables dual-node overlay).
        accel_mag2: Second node accelerometer magnitude array.
        tilt_angle2: Second node tilt angle array.
        node_label2: Display label for the second node traces.

    Returns:
        Plotly Figure with dual-axis scatter traces.
    """
    dual = time2 is not None

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # --- primary node traces ---
    accel_name = f"{node_label} 加速度 (G)" if dual else "加速度 (G)"
    tilt_name = f"{node_label} 倾斜角 (°)" if dual else "倾斜角 (°)"
    gyro_name = f"{node_label} 角速度 (°/s)" if dual else "角速度 (°/s)"

    fig.add_trace(
        go.Scatter(
            x=time,
            y=accel_mag,
            name=accel_name,
            line={"color": "#0068C9", "width": 1.5},
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=time,
            y=tilt_angle,
            name=tilt_name,
            line={"color": "#7D44CF", "width": 2},
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=time,
            y=gyro_mag,
            name=gyro_name,
            line={"color": "#FF8C00", "width": 1.5},
        ),
        secondary_y=True,
    )

    # --- second node traces (dashed) ---
    if dual:
        colorway = CHART_THEME["colorway"]
        second_accel_color = colorway[1]  # #09AB3B
        second_tilt_color = colorway[3]   # #FF4B4B

        if accel_mag2 is not None:
            fig.add_trace(
                go.Scatter(
                    x=time2,
                    y=accel_mag2,
                    name=f"{node_label2} 加速度 (G)",
                    line={"color": second_accel_color, "width": 1.5, "dash": "dash"},
                ),
                secondary_y=False,
            )
        if tilt_angle2 is not None:
            fig.add_trace(
                go.Scatter(
                    x=time2,
                    y=tilt_angle2,
                    name=f"{node_label2} 倾斜角 (°)",
                    line={"color": second_tilt_color, "width": 2, "dash": "dash"},
                ),
                secondary_y=False,
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

    fig.update_yaxes(
        title_text="加速度 (G) / 倾斜角 (°)",
        title_font_size=12,
        title_font_color="#0068C9",
        secondary_y=False,
    )
    fig.update_yaxes(
        title_text="角速度 (°/s)",
        title_font_size=12,
        title_font_color="#FF8C00",
        secondary_y=True,
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
