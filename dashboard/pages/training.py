"""Training monitoring page - displays set metadata, scoring card, and analysis tabs."""
import os

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import CHART_THEME
from dashboard.config import load_config
from dashboard.core.data_loader import load_imu, load_vision
from dashboard.core.metrics import compute_all_metrics
from dashboard.core.scoring import SetReport
from dashboard.components.gauge_chart import build_scoring_card
from dashboard.components.timeline_chart import build_phase_timeline
from dashboard.components.waveform_chart import build_imu_waveform, build_fusion_chart
from dashboard.core.landmarks import extract_frame, detect_landmarks, get_total_frames, load_landmarks_csv
from dashboard.components.skeleton_renderer import render_skeleton_frame
from dashboard.core.analysis import calc_imu_tilt, smooth
from dashboard.core.vision_angles import (
    calc_leg_deviation_vision,
    calc_knee_extension,
    calc_shoulder_knee_angle,
    calc_leg_symmetry,
    calc_trunk_vertical,
)
import cv2

# ── Metric name mapping (English key -> Chinese display) ──────────────
METRIC_LABELS = {
    "leg_deviation": "腿部垂直偏差",
    "leg_height_index": "腿部高度指数",
    "knee_extension": "膝关节伸展",
    "leg_symmetry": "腿部对称性",
    "shoulder_knee_alignment": "肩膝对齐角度",
    "trunk_vertical": "躯干垂直度",
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
            set_dir = selected["path"]

            # ── Load all 4 data sources ──────────────────────────────
            arm_imu_df = load_imu(set_dir, node="NODE_A1")
            leg_imu_df = load_imu(set_dir, node="NODE_L1")
            vision_df = load_vision(set_dir)
            landmarks_df = load_landmarks_csv(set_dir)

            has_arm_imu = not arm_imu_df.empty
            has_leg_imu = not leg_imu_df.empty
            has_vision_data = not vision_df.empty
            has_landmarks = not landmarks_df.empty

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

            # Gauge layout: 2 rows of 4 for 8 metrics
            config = load_config()
            gauge_figs = build_scoring_card(report.metrics, config)

            # Row 1: leg_deviation, leg_height_index, knee_extension, leg_symmetry
            row1_figs = gauge_figs[:4]
            row1_metrics = report.metrics[:4]
            if row1_figs:
                gauge_cols_r1 = st.columns(4)
                for i, (fig, col) in enumerate(zip(row1_figs, gauge_cols_r1)):
                    with col:
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                        metric = row1_metrics[i]
                        zone_color = ZONE_COLORS.get(metric.zone, "#9BA1A6")
                        label = METRIC_LABELS.get(metric.name, metric.name)
                        st.markdown(
                            f'<p style="text-align:center;font-size:12px;color:{zone_color};">'
                            f'扣分: -{metric.deduction:.1f}</p>',
                            unsafe_allow_html=True,
                        )

            # Row 2: shoulder_knee_alignment, trunk_vertical, smoothness, stability
            row2_figs = gauge_figs[4:8]
            row2_metrics = report.metrics[4:8]
            if row2_figs:
                gauge_cols_r2 = st.columns(4)
                for i, (fig, col) in enumerate(zip(row2_figs, gauge_cols_r2)):
                    with col:
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                        metric = row2_metrics[i]
                        zone_color = ZONE_COLORS.get(metric.zone, "#9BA1A6")
                        label = METRIC_LABELS.get(metric.name, metric.name)
                        st.markdown(
                            f'<p style="text-align:center;font-size:12px;color:{zone_color};">'
                            f'扣分: -{metric.deduction:.1f}</p>',
                            unsafe_allow_html=True,
                        )

            # ── Tab container (4 tabs) ────────────────────────────────
            tab_overview, tab_legs, tab_arms, tab_fusion = st.tabs([
                "概览", "腿部分析", "手臂分析", "传感器融合"
            ])

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

            # ── Tab 2: 腿部分析 ──────────────────────────────────────
            with tab_legs:
                if not has_landmarks and not has_leg_imu:
                    st.warning("该训练组无腿部分析所需数据（关键点或小腿 IMU）。")
                else:
                    # -- Leg deviation angle time series --
                    if has_landmarks:
                        st.subheader("腿部偏差角度")
                        leg_dev = calc_leg_deviation_vision(landmarks_df)
                        t_frames = np.arange(len(leg_dev))
                        fig_leg_dev = go.Figure()
                        fig_leg_dev.add_trace(go.Scatter(
                            x=t_frames, y=leg_dev,
                            name="腿部偏差", line={"color": "#0068C9", "width": 2},
                        ))
                        fig_leg_dev.update_layout(
                            height=300, xaxis_title="帧", yaxis_title="偏差角 (°)",
                            margin=CHART_THEME["margin"],
                            template=CHART_THEME["template"],
                            font_family=CHART_THEME["font_family"],
                            paper_bgcolor=CHART_THEME["paper_bgcolor"],
                            plot_bgcolor=CHART_THEME["plot_bgcolor"],
                        )
                        st.plotly_chart(fig_leg_dev, use_container_width=True, config={"displayModeBar": False})

                    # -- Knee extension angle time series --
                    if has_landmarks:
                        st.subheader("膝关节伸展角度")
                        knee_ext = calc_knee_extension(landmarks_df)
                        t_frames_k = np.arange(len(knee_ext))
                        fig_knee = go.Figure()
                        fig_knee.add_trace(go.Scatter(
                            x=t_frames_k, y=knee_ext,
                            name="膝关节伸展", line={"color": "#09AB3B", "width": 2},
                        ))
                        fig_knee.update_layout(
                            height=300, xaxis_title="帧", yaxis_title="角度 (°)",
                            margin=CHART_THEME["margin"],
                            template=CHART_THEME["template"],
                            font_family=CHART_THEME["font_family"],
                            paper_bgcolor=CHART_THEME["paper_bgcolor"],
                            plot_bgcolor=CHART_THEME["plot_bgcolor"],
                        )
                        st.plotly_chart(fig_knee, use_container_width=True, config={"displayModeBar": False})

                    # -- Leg symmetry time series --
                    if has_landmarks:
                        st.subheader("腿部对称性")
                        leg_sym = calc_leg_symmetry(landmarks_df)
                        t_frames_s = np.arange(len(leg_sym))
                        fig_sym = go.Figure()
                        fig_sym.add_trace(go.Scatter(
                            x=t_frames_s, y=leg_sym,
                            name="左右偏差差异", line={"color": "#FACA2B", "width": 2},
                        ))
                        fig_sym.update_layout(
                            height=300, xaxis_title="帧", yaxis_title="对称差异 (°)",
                            margin=CHART_THEME["margin"],
                            template=CHART_THEME["template"],
                            font_family=CHART_THEME["font_family"],
                            paper_bgcolor=CHART_THEME["paper_bgcolor"],
                            plot_bgcolor=CHART_THEME["plot_bgcolor"],
                        )
                        st.plotly_chart(fig_sym, use_container_width=True, config={"displayModeBar": False})

                    # -- Shin IMU tilt angle time series --
                    if has_leg_imu:
                        st.subheader("小腿 IMU 倾斜角")
                        leg_tilt_raw = calc_imu_tilt(leg_imu_df[["ax", "ay", "az"]].to_dict("records"))
                        leg_tilt_smooth = smooth(leg_tilt_raw, 15)
                        leg_imu_time = (
                            leg_imu_df["timestamp_local"] - leg_imu_df["timestamp_local"].iloc[0]
                        ).values
                        fig_leg_tilt = go.Figure()
                        fig_leg_tilt.add_trace(go.Scatter(
                            x=leg_imu_time, y=leg_tilt_smooth,
                            name="小腿倾斜角", line={"color": "#7D44CF", "width": 2},
                        ))
                        fig_leg_tilt.update_layout(
                            height=300, xaxis_title="时间 (秒)", yaxis_title="倾斜角 (°)",
                            margin=CHART_THEME["margin"],
                            template=CHART_THEME["template"],
                            font_family=CHART_THEME["font_family"],
                            paper_bgcolor=CHART_THEME["paper_bgcolor"],
                            plot_bgcolor=CHART_THEME["plot_bgcolor"],
                        )
                        st.plotly_chart(fig_leg_tilt, use_container_width=True, config={"displayModeBar": False})

                    # -- Fusion comparison: shin tilt vs vision leg deviation --
                    if has_leg_imu and has_landmarks:
                        st.divider()
                        st.subheader("小腿 IMU 与视觉融合对比")
                        # Resample vision leg deviation to IMU time base
                        leg_dev_vis = calc_leg_deviation_vision(landmarks_df)
                        vis_time_norm = np.linspace(0, leg_imu_time[-1], len(leg_dev_vis))
                        leg_dev_resampled = np.interp(leg_imu_time, vis_time_norm, leg_dev_vis)

                        fusion_fig_leg, corr_leg = build_fusion_chart(
                            leg_imu_time, leg_dev_resampled, leg_tilt_smooth,
                        )
                        st.plotly_chart(fusion_fig_leg, use_container_width=True, config={"displayModeBar": False})

                        if corr_leg is not None:
                            st.metric("腿部融合相关系数", f"r = {corr_leg:.3f}")

            # ── Tab 3: 手臂分析 ──────────────────────────────────────
            with tab_arms:
                if not has_landmarks and not has_arm_imu and not has_vision_data:
                    st.warning("该训练组无手臂分析所需数据。")
                else:
                    # -- Shoulder-knee alignment time series --
                    if has_landmarks:
                        st.subheader("肩膝对齐角度")
                        sk_angle = calc_shoulder_knee_angle(landmarks_df)
                        t_frames_sk = np.arange(len(sk_angle))
                        fig_sk = go.Figure()
                        fig_sk.add_trace(go.Scatter(
                            x=t_frames_sk, y=sk_angle,
                            name="肩膝对齐", line={"color": "#0068C9", "width": 2},
                        ))
                        fig_sk.update_layout(
                            height=300, xaxis_title="帧", yaxis_title="角度 (°)",
                            margin=CHART_THEME["margin"],
                            template=CHART_THEME["template"],
                            font_family=CHART_THEME["font_family"],
                            paper_bgcolor=CHART_THEME["paper_bgcolor"],
                            plot_bgcolor=CHART_THEME["plot_bgcolor"],
                        )
                        st.plotly_chart(fig_sk, use_container_width=True, config={"displayModeBar": False})

                    # -- Trunk verticality time series --
                    if has_landmarks:
                        st.subheader("躯干垂直度")
                        trunk_v = calc_trunk_vertical(landmarks_df)
                        t_frames_tv = np.arange(len(trunk_v))
                        fig_tv = go.Figure()
                        fig_tv.add_trace(go.Scatter(
                            x=t_frames_tv, y=trunk_v,
                            name="躯干偏差", line={"color": "#FF8C00", "width": 2},
                        ))
                        fig_tv.update_layout(
                            height=300, xaxis_title="帧", yaxis_title="偏差角 (°)",
                            margin=CHART_THEME["margin"],
                            template=CHART_THEME["template"],
                            font_family=CHART_THEME["font_family"],
                            paper_bgcolor=CHART_THEME["paper_bgcolor"],
                            plot_bgcolor=CHART_THEME["plot_bgcolor"],
                        )
                        st.plotly_chart(fig_tv, use_container_width=True, config={"displayModeBar": False})

                    # -- Forearm IMU tilt angle time series --
                    if has_arm_imu:
                        st.subheader("前臂 IMU 倾斜角")
                        arm_tilt_raw = calc_imu_tilt(arm_imu_df[["ax", "ay", "az"]].to_dict("records"))
                        arm_tilt_smooth = smooth(arm_tilt_raw, 15)
                        arm_imu_time = (
                            arm_imu_df["timestamp_local"] - arm_imu_df["timestamp_local"].iloc[0]
                        ).values
                        fig_arm_tilt = go.Figure()
                        fig_arm_tilt.add_trace(go.Scatter(
                            x=arm_imu_time, y=arm_tilt_smooth,
                            name="前臂倾斜角", line={"color": "#7D44CF", "width": 2},
                        ))
                        fig_arm_tilt.update_layout(
                            height=300, xaxis_title="时间 (秒)", yaxis_title="倾斜角 (°)",
                            margin=CHART_THEME["margin"],
                            template=CHART_THEME["template"],
                            font_family=CHART_THEME["font_family"],
                            paper_bgcolor=CHART_THEME["paper_bgcolor"],
                            plot_bgcolor=CHART_THEME["plot_bgcolor"],
                        )
                        st.plotly_chart(fig_arm_tilt, use_container_width=True, config={"displayModeBar": False})

                    # -- Skeleton overlay / keyframe comparison (from old 视觉分析 tab) --
                    video_path = os.path.join(selected["path"], "video.mp4")
                    has_video_file = os.path.exists(video_path)
                    vision_df_visual = load_vision(selected["path"])
                    has_vision_csv = not vision_df_visual.empty

                    if not has_video_file and not has_vision_csv:
                        pass  # silently skip if no visual data
                    elif not has_video_file and has_vision_csv:
                        st.divider()
                        st.subheader("视觉关节角度")
                        vis_t_rel = (vision_df_visual["timestamp_local"] - vision_df_visual["timestamp_local"].iloc[0]).values
                        vis_angles_plot = vision_df_visual["angle_deg"].values
                        angle_fig = go.Figure()
                        angle_fig.add_trace(go.Scatter(
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
                        st.divider()
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

                    # -- Fusion chart: arm IMU vs vision (keep existing logic) --
                    if has_arm_imu and has_vision_data:
                        st.divider()
                        st.subheader("手臂传感器融合")

                        arm_tilt_raw_f = calc_imu_tilt(arm_imu_df[["ax", "ay", "az"]].to_dict("records"))
                        arm_tilt_smooth_f = smooth(arm_tilt_raw_f, 15)
                        arm_imu_time_f = (
                            arm_imu_df["timestamp_local"] - arm_imu_df["timestamp_local"].iloc[0]
                        ).values

                        vis_t = (
                            vision_df["timestamp_local"] - vision_df["timestamp_local"].iloc[0]
                        ).values
                        vis_angles = vision_df["angle_deg"].values

                        if len(vis_t) > 0 and len(arm_imu_time_f) > 0:
                            # Resample IMU tilt to vision time base via linear interpolation
                            imu_tilt_resampled = np.interp(vis_t, arm_imu_time_f, arm_tilt_smooth_f)

                            fusion_fig, corr = build_fusion_chart(vis_t, vis_angles, imu_tilt_resampled)
                            st.plotly_chart(fusion_fig, use_container_width=True, config={"displayModeBar": False})

                            # Correlation badge
                            if corr is not None:
                                st.metric("相关系数", f"r = {corr:.3f}")

            # ── Tab 4: 传感器融合 ────────────────────────────────────
            with tab_fusion:
                # -- Dual-node or single-node waveform --
                if has_arm_imu and has_leg_imu:
                    st.subheader("双节点 IMU 波形叠加")

                    # Arm IMU signals
                    arm_accel_mag = np.sqrt(
                        arm_imu_df["ax"]**2 + arm_imu_df["ay"]**2 + arm_imu_df["az"]**2
                    ).values
                    arm_gyro_mag = np.sqrt(
                        arm_imu_df["gx"]**2 + arm_imu_df["gy"]**2 + arm_imu_df["gz"]**2
                    ).values
                    arm_tilt_raw_w = calc_imu_tilt(arm_imu_df[["ax", "ay", "az"]].to_dict("records"))
                    arm_tilt_w = smooth(arm_tilt_raw_w, 15)
                    arm_time_w = (
                        arm_imu_df["timestamp_local"] - arm_imu_df["timestamp_local"].iloc[0]
                    ).values

                    # Leg IMU signals
                    leg_accel_mag = np.sqrt(
                        leg_imu_df["ax"]**2 + leg_imu_df["ay"]**2 + leg_imu_df["az"]**2
                    ).values
                    leg_tilt_raw_w = calc_imu_tilt(leg_imu_df[["ax", "ay", "az"]].to_dict("records"))
                    leg_tilt_w = smooth(leg_tilt_raw_w, 15)
                    leg_time_w = (
                        leg_imu_df["timestamp_local"] - leg_imu_df["timestamp_local"].iloc[0]
                    ).values

                    waveform_fig = build_imu_waveform(
                        arm_time_w, arm_accel_mag, arm_gyro_mag, arm_tilt_w,
                        node_label="前臂",
                        time2=leg_time_w,
                        accel_mag2=leg_accel_mag,
                        tilt_angle2=leg_tilt_w,
                        node_label2="小腿",
                    )
                    st.plotly_chart(waveform_fig, use_container_width=True, config={"displayModeBar": False})

                elif has_arm_imu:
                    st.subheader("IMU 波形")
                    arm_accel_mag = np.sqrt(
                        arm_imu_df["ax"]**2 + arm_imu_df["ay"]**2 + arm_imu_df["az"]**2
                    ).values
                    arm_gyro_mag = np.sqrt(
                        arm_imu_df["gx"]**2 + arm_imu_df["gy"]**2 + arm_imu_df["gz"]**2
                    ).values
                    arm_tilt_raw_w = calc_imu_tilt(arm_imu_df[["ax", "ay", "az"]].to_dict("records"))
                    arm_tilt_w = smooth(arm_tilt_raw_w, 15)
                    arm_time_w = (
                        arm_imu_df["timestamp_local"] - arm_imu_df["timestamp_local"].iloc[0]
                    ).values

                    waveform_fig = build_imu_waveform(arm_time_w, arm_accel_mag, arm_gyro_mag, arm_tilt_w)
                    st.plotly_chart(waveform_fig, use_container_width=True, config={"displayModeBar": False})

                elif has_leg_imu:
                    st.subheader("IMU 波形")
                    leg_accel_mag = np.sqrt(
                        leg_imu_df["ax"]**2 + leg_imu_df["ay"]**2 + leg_imu_df["az"]**2
                    ).values
                    leg_gyro_mag = np.sqrt(
                        leg_imu_df["gx"]**2 + leg_imu_df["gy"]**2 + leg_imu_df["gz"]**2
                    ).values
                    leg_tilt_raw_w = calc_imu_tilt(leg_imu_df[["ax", "ay", "az"]].to_dict("records"))
                    leg_tilt_w = smooth(leg_tilt_raw_w, 15)
                    leg_time_w = (
                        leg_imu_df["timestamp_local"] - leg_imu_df["timestamp_local"].iloc[0]
                    ).values

                    waveform_fig = build_imu_waveform(leg_time_w, leg_accel_mag, leg_gyro_mag, leg_tilt_w)
                    st.plotly_chart(waveform_fig, use_container_width=True, config={"displayModeBar": False})

                else:
                    st.warning("该训练组无 IMU 数据。")

                # -- Data quality summary --
                st.divider()
                st.subheader("数据质量摘要")
                q_cols = st.columns(4)
                with q_cols[0]:
                    arm_rows = len(arm_imu_df) if has_arm_imu else 0
                    st.metric("前臂 IMU 采样数", f"{arm_rows:,}")
                    if has_arm_imu and "timestamp_local" in arm_imu_df.columns and len(arm_imu_df) > 1:
                        arm_dur = arm_imu_df["timestamp_local"].iloc[-1] - arm_imu_df["timestamp_local"].iloc[0]
                        arm_rate = arm_rows / arm_dur if arm_dur > 0 else 0
                        st.caption(f"采样率: {arm_rate:.0f} Hz")
                with q_cols[1]:
                    leg_rows = len(leg_imu_df) if has_leg_imu else 0
                    st.metric("小腿 IMU 采样数", f"{leg_rows:,}")
                    if has_leg_imu and "timestamp_local" in leg_imu_df.columns and len(leg_imu_df) > 1:
                        leg_dur = leg_imu_df["timestamp_local"].iloc[-1] - leg_imu_df["timestamp_local"].iloc[0]
                        leg_rate = leg_rows / leg_dur if leg_dur > 0 else 0
                        st.caption(f"采样率: {leg_rate:.0f} Hz")
                with q_cols[2]:
                    vis_rows = len(vision_df) if has_vision_data else 0
                    st.metric("视觉采样数", f"{vis_rows:,}")
                    if has_vision_data and "timestamp_local" in vision_df.columns and len(vision_df) > 1:
                        vis_dur = vision_df["timestamp_local"].iloc[-1] - vision_df["timestamp_local"].iloc[0]
                        vis_rate = vis_rows / vis_dur if vis_dur > 0 else 0
                        st.caption(f"采样率: {vis_rate:.0f} Hz")
                with q_cols[3]:
                    lm_rows = len(landmarks_df) if has_landmarks else 0
                    st.metric("关键点帧数", f"{lm_rows:,}")

                # -- Placeholder for advanced fusion --
                st.divider()
                st.info("高级融合 — 即将推出")

    except Exception as e:
        st.error(f"分析报告生成失败：{str(e)}")
