"""Training monitoring page - displays set metadata, scoring card, and analysis tabs."""
import os

import numpy as np
import streamlit as st

from dashboard.config import load_config
from dashboard.core.data_loader import load_imu, load_vision
from dashboard.core.metrics import compute_all_metrics
from dashboard.core.scoring import SetReport
from dashboard.components.gauge_chart import build_scoring_card
from dashboard.components.timeline_chart import build_phase_timeline

# ── Metric name mapping (English key -> Chinese display) ──────────────
METRIC_LABELS = {
    "leg_deviation": "腿部垂直偏差",
    "leg_height_index": "腿部高度指数",
    "shoulder_knee_alignment": "肩膝对齐角度",
    "smoothness": "动作流畅度",
    "stability": "展示稳定性",
}

# ── Zone color mapping ────────────────────────────────────────────────
ZONE_COLORS = {
    "clean": "#09AB3B",
    "minor": "#FACA2B",
    "major": "#FF4B4B",
}

st.header("训练监控")

# Initialize session state for frame navigation (namespaced per RESEARCH.md)
if "p2_current_frame" not in st.session_state:
    st.session_state.p2_current_frame = 0

selected = st.session_state.get("selected_set")

if selected is None:
    sessions = st.session_state.get("sessions_index", [])
    if not sessions:
        st.info("暂无训练数据\n\n在 data/ 目录中未找到训练记录。请先使用 sync_recorder.py 录制一组训练数据。")
    else:
        st.info("请从左侧边栏选择一个训练组以查看分析报告。")
else:
    # Metadata card -- 4 columns (inherited from Phase 1)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("训练组 #", f"{selected['set_number']:03d}")
    with col2:
        st.metric("日期", selected["date"])
    with col3:
        duration = selected["duration_sec"]
        if duration >= 60:
            st.metric("时长", f"{duration/60:.1f} 分钟")
        else:
            st.metric("时长", f"{duration:.1f} 秒")
    with col4:
        has_imu = selected["has_imu"]
        has_vision = selected["has_vision"]
        if has_imu and has_vision:
            st.success("IMU + 视觉数据完整")
        elif has_imu or has_vision:
            available = "IMU" if has_imu else "视觉"
            missing = "视觉" if has_imu else "IMU"
            st.warning(f"部分数据缺失：该组训练仅包含 {available} 数据（缺少 {missing}）")
        else:
            st.error("数据文件损坏")

    st.caption(f"时间: {selected['time']}  |  IMU 采样数: {selected['imu_rows']}  |  视觉采样数: {selected['vision_rows']}")

    # ── Report generation ─────────────────────────────────────────────
    try:
        # Cache report in session state to avoid recompute on tab switch
        cache_key = f"_p2_report_{selected['name']}"
        if cache_key not in st.session_state:
            with st.spinner("正在生成分析报告..."):
                report = compute_all_metrics(selected["path"])
            st.session_state[cache_key] = report
        else:
            report = st.session_state[cache_key]

        if report is None:
            st.error("分析报告生成失败：数据文件不完整。")
        else:
            # ── Scoring card (persistent header above tabs) ───────────
            st.divider()

            # Overall score with FINA zone color
            if report.overall_score >= 8.0:
                score_color = "#09AB3B"
            elif report.overall_score >= 6.0:
                score_color = "#FACA2B"
            else:
                score_color = "#FF4B4B"

            st.caption('<p style="text-align:center;">预估执行分</p>', unsafe_allow_html=True)
            st.markdown(
                f'<h1 style="text-align:center;color:{score_color};margin-top:-10px;">'
                f'{report.overall_score:.1f} / 10</h1>',
                unsafe_allow_html=True,
            )

            # Gauge row
            config = load_config()
            gauge_figs = build_scoring_card(report.metrics, config)
            gauge_cols = st.columns(len(gauge_figs)) if gauge_figs else []
            for i, (fig, col) in enumerate(zip(gauge_figs, gauge_cols)):
                with col:
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                    metric = report.metrics[i]
                    zone_color = ZONE_COLORS.get(metric.zone, "#9BA1A6")
                    label = METRIC_LABELS.get(metric.name, metric.name)
                    st.markdown(
                        f'<p style="text-align:center;font-size:12px;color:{zone_color};">'
                        f'扣分: -{metric.deduction:.1f}</p>',
                        unsafe_allow_html=True,
                    )

            # ── Tab container ─────────────────────────────────────────
            tab_overview, tab_visual, tab_sensor = st.tabs(["概览", "视觉分析", "传感器"])

            # ── Tab 1: Overview ───────────────────────────────────────
            with tab_overview:
                st.subheader("动作阶段时间线")
                timeline_fig = build_phase_timeline(report.phases)
                st.plotly_chart(timeline_fig, use_container_width=True, config={"displayModeBar": False})

                # Phase boundary slider
                imu_df = load_imu(selected["path"])
                if not imu_df.empty and "timestamp_local" in imu_df.columns:
                    t_min = float(imu_df["timestamp_local"].iloc[0])
                    t_max = float(imu_df["timestamp_local"].iloc[-1])

                    # Default boundaries from detected phases
                    if len(report.phases) >= 3:
                        default_b1 = report.phases[0]["end"]
                        default_b2 = report.phases[1]["end"]
                    else:
                        third = (t_max - t_min) / 3
                        default_b1 = t_min + third
                        default_b2 = t_min + 2 * third

                    # Clamp defaults within range
                    default_b1 = max(t_min, min(default_b1, t_max))
                    default_b2 = max(t_min, min(default_b2, t_max))

                    st.slider(
                        "调整阶段边界",
                        min_value=t_min,
                        max_value=t_max,
                        value=(default_b1, default_b2),
                        key="p2_phase_boundaries",
                        help="拖动滑块微调自动检测的阶段分界点",
                    )

                # Phase quality cards
                st.subheader("阶段质量")
                phase_cols = st.columns(len(report.phases))
                for phase, pcol in zip(report.phases, phase_cols):
                    with pcol:
                        phase_duration = phase["end"] - phase["start"]
                        st.metric(
                            phase["name"],
                            f"{phase_duration:.1f}s",
                        )

            # ── Tab 2: Visual (placeholder -- Task 2 fills) ──────────
            with tab_visual:
                st.info("正在加载...")

            # ── Tab 3: Sensor (placeholder -- Task 2 fills) ──────────
            with tab_sensor:
                st.info("正在加载...")

    except Exception as e:
        st.error(f"分析报告生成失败：{str(e)}")
