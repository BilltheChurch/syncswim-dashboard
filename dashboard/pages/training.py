"""Training monitoring page - displays set metadata and data status."""
import streamlit as st
from dashboard.core.data_loader import load_imu, load_vision

st.header("训练监控")

selected = st.session_state.get("selected_set")

if selected is None:
    sessions = st.session_state.get("sessions_index", [])
    if not sessions:
        st.info("暂无训练数据\n\n在 data/ 目录中未找到训练记录。请先使用 sync_recorder.py 录制一组训练数据。")
    else:
        st.info("请从左侧边栏选择一个训练组。")
else:
    # Metadata card — 4 columns
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

    # Show additional metadata
    st.caption(f"时间: {selected['time']}  |  IMU 采样数: {selected['imu_rows']}  |  视觉采样数: {selected['vision_rows']}")

    # Placeholder sections for future phases
    st.divider()
    with st.container():
        st.caption("实时监控 — Phase 5 开发中")
    st.divider()
    with st.container():
        st.caption("训练报告 — Phase 2 开发中")
