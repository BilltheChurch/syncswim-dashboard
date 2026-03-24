"""Training monitoring page - displays set metadata, scoring card, and analysis tabs."""
import os

import numpy as np
import streamlit as st

from dashboard.components import CHART_THEME
from dashboard.config import load_config
from dashboard.core.data_loader import load_imu, load_vision
from dashboard.core.metrics import compute_all_metrics
from dashboard.core.scoring import SetReport
from dashboard.components.gauge_chart import build_scoring_card
from dashboard.components.timeline_chart import build_phase_timeline
from dashboard.components.waveform_chart import build_imu_waveform, build_fusion_chart
from dashboard.core.landmarks import extract_frame, detect_landmarks, get_total_frames
from dashboard.components.skeleton_renderer import render_skeleton_frame
from dashboard.core.analysis import calc_imu_tilt, smooth
import cv2

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

                # Phase boundary slider (relative seconds, not epoch)
                imu_df = load_imu(selected["path"])
                if not imu_df.empty and "timestamp_local" in imu_df.columns:
                    t_origin = float(imu_df["timestamp_local"].iloc[0])
                    t_min_rel = 0.0
                    t_max_rel = float(imu_df["timestamp_local"].iloc[-1]) - t_origin

                    # Default boundaries from detected phases (convert to relative)
                    if len(report.phases) >= 3:
                        default_b1 = report.phases[0]["end"] - t_origin
                        default_b2 = report.phases[1]["end"] - t_origin
                    else:
                        third = t_max_rel / 3
                        default_b1 = third
                        default_b2 = 2 * third

                    # Clamp defaults within range
                    default_b1 = max(t_min_rel, min(default_b1, t_max_rel))
                    default_b2 = max(t_min_rel, min(default_b2, t_max_rel))

                    st.slider(
                        "调整阶段边界 (秒)",
                        min_value=t_min_rel,
                        max_value=t_max_rel,
                        value=(round(default_b1, 1), round(default_b2, 1)),
                        step=0.1,
                        format="%.1f",
                        key="p2_phase_boundaries",
                        help="拖动滑块微调自动检测的阶段分界点",
                    )

                # Phase quality cards — show duration + avg score per phase
                st.subheader("阶段质量")
                phase_cols = st.columns(len(report.phases))
                for phase, pcol in zip(report.phases, phase_cols):
                    with pcol:
                        phase_duration = phase["end"] - phase["start"]
                        zone = phase.get("zone_color", "#09AB3B")
                        if zone == "#09AB3B":
                            quality_label = "良好"
                        elif zone == "#FACA2B":
                            quality_label = "一般"
                        else:
                            quality_label = "需改进"
                        st.metric(
                            phase["name"],
                            quality_label,
                            delta=f"{phase_duration:.1f}s",
                        )

            # ── Tab 2: Visual (keyframe comparison + skeleton overlay) ──
            with tab_visual:
                video_path = os.path.join(selected["path"], "video.mp4")
                has_video_file = os.path.exists(video_path)
                vision_df_visual = load_vision(selected["path"])
                has_vision_csv = not vision_df_visual.empty

                if not has_video_file and not has_vision_csv:
                    st.warning("该训练组无视觉数据。骨架叠加和关键帧对比不可用。")
                elif not has_video_file and has_vision_csv:
                    st.info("该训练组无视频文件（旧版录制不保存 MP4）。骨架叠加不可用，但可查看视觉角度数据。")
                    # Show vision angle timeline from CSV
                    st.subheader("视觉关节角度")
                    vis_t_rel = (vision_df_visual["timestamp_local"] - vision_df_visual["timestamp_local"].iloc[0]).values
                    vis_angles_plot = vision_df_visual["angle_deg"].values
                    import plotly.graph_objects as go_vis
                    angle_fig = go_vis.Figure()
                    angle_fig.add_trace(go_vis.Scatter(
                        x=vis_t_rel, y=vis_angles_plot,
                        name="关节角度", line={"color": "#09AB3B", "width": 2},
                    ))
                    angle_fig.update_layout(
                        height=300, xaxis_title="时间 (秒)", yaxis_title="角度 (°)",
                        margin={"l": 48, "r": 16, "t": 24, "b": 48},
                        template=CHART_THEME["template"],
                        font_family=CHART_THEME["font_family"],
                        paper_bgcolor=CHART_THEME["paper_bgcolor"],
                        plot_bgcolor=CHART_THEME["plot_bgcolor"],
                    )
                    st.plotly_chart(angle_fig, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.subheader("关键帧对比")
                    total_frames = get_total_frames(video_path)

                    if total_frames > 0:
                        # Frame navigation: [prev] [counter] [next]
                        nav_left, nav_center, nav_right = st.columns([1, 3, 1])
                        with nav_left:
                            if st.button("上一帧", disabled=(st.session_state.p2_current_frame <= 0)):
                                st.session_state.p2_current_frame = max(0, st.session_state.p2_current_frame - 1)
                                st.rerun()
                        with nav_center:
                            st.caption(f"帧 {st.session_state.p2_current_frame + 1} / {total_frames}")
                        with nav_right:
                            if st.button("下一帧", disabled=(st.session_state.p2_current_frame >= total_frames - 1)):
                                st.session_state.p2_current_frame = min(total_frames - 1, st.session_state.p2_current_frame + 1)
                                st.rerun()

                        # Extract and render frame with skeleton
                        frame = extract_frame(video_path, st.session_state.p2_current_frame)
                        if frame is not None:
                            landmarks = detect_landmarks(frame)
                            if landmarks is not None:
                                # Render actual pose skeleton in red
                                annotated = render_skeleton_frame(frame, landmarks, color=(0, 0, 255), line_width=2)
                                st.image(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB), use_container_width=True)
                            else:
                                # No pose detected in this frame
                                st.image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), use_container_width=True)
                                st.caption("未检测到骨架姿态")
                        else:
                            st.warning("无法提取视频帧。")
                    else:
                        st.warning("视频文件无有效帧。")

            # ── Tab 3: Sensor (IMU waveform + fusion chart) ─────────
            with tab_sensor:
                imu_df_sensor = load_imu(selected["path"])
                vision_df_sensor = load_vision(selected["path"])

                has_imu_data = not imu_df_sensor.empty
                has_vision_data = not vision_df_sensor.empty

                # Precompute IMU derived signals (used by both waveform and fusion)
                imu_time_sec = None
                accel_mag = None
                gyro_mag = None
                tilt_smooth = None

                if has_imu_data:
                    accel_mag = np.sqrt(
                        imu_df_sensor["ax"]**2 + imu_df_sensor["ay"]**2 + imu_df_sensor["az"]**2
                    ).values
                    gyro_mag = np.sqrt(
                        imu_df_sensor["gx"]**2 + imu_df_sensor["gy"]**2 + imu_df_sensor["gz"]**2
                    ).values
                    tilt_raw = calc_imu_tilt(imu_df_sensor[["ax", "ay", "az"]].to_dict("records"))
                    tilt_smooth = smooth(tilt_raw, 15)
                    imu_time_sec = (
                        imu_df_sensor["timestamp_local"] - imu_df_sensor["timestamp_local"].iloc[0]
                    ).values

                # ── IMU waveform section ──────────────────────────────
                if has_imu_data:
                    st.subheader("IMU 波形")
                    waveform_fig = build_imu_waveform(imu_time_sec, accel_mag, gyro_mag, tilt_smooth)
                    st.plotly_chart(waveform_fig, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.warning("该训练组无 IMU 数据。")

                # ── Fusion chart section ──────────────────────────────
                if has_imu_data and has_vision_data:
                    st.divider()
                    st.subheader("传感器融合")

                    # Timestamp alignment: resample IMU tilt onto vision timestamps
                    vis_t = (
                        vision_df_sensor["timestamp_local"] - vision_df_sensor["timestamp_local"].iloc[0]
                    ).values
                    vis_angles = vision_df_sensor["angle_deg"].values

                    if len(vis_t) > 0 and len(imu_time_sec) > 0:
                        # Resample IMU tilt to vision time base via linear interpolation
                        imu_tilt_resampled = np.interp(vis_t, imu_time_sec, tilt_smooth)

                        fusion_fig, corr = build_fusion_chart(vis_t, vis_angles, imu_tilt_resampled)
                        st.plotly_chart(fusion_fig, use_container_width=True, config={"displayModeBar": False})

                        # Correlation badge
                        if corr is not None:
                            abs_corr = abs(corr)
                            if abs_corr >= 0.7:
                                corr_color = "#09AB3B"
                            elif abs_corr >= 0.4:
                                corr_color = "#FACA2B"
                            else:
                                corr_color = "#FF4B4B"
                            st.metric("相关系数", f"r = {corr:.3f}")
                    else:
                        st.info("融合图表需要同时有 IMU 和视觉数据。")

                elif has_vision_data and not has_imu_data:
                    st.divider()
                    st.info("融合图表需要同时有 IMU 和视觉数据。仅显示视觉数据。")
                elif not has_imu_data and not has_vision_data:
                    st.error("传感器数据不可用。")

    except Exception as e:
        st.error(f"分析报告生成失败：{str(e)}")
