"""SyncSwim Dashboard — Streamlit multi-page app entry point.

Launch with: streamlit run dashboard/app.py
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path so 'dashboard' package is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st

from dashboard.config import load_config, save_config
from dashboard.core.data_loader import load_or_rebuild_index

# ── Page config (must be first Streamlit call) ──────────────────────────
st.set_page_config(
    page_title="SyncSwim 训练分析面板",
    page_icon=":material/pool:",
    layout="wide",
)

# ── Session state defaults ──────────────────────────────────────────────
defaults = {
    "role": "教练",
    "selected_set": None,
    "selected_set_dir": None,
    "sessions_index": None,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ── Sidebar: Role toggle ───────────────────────────────────────────────
role = st.sidebar.radio("视角切换", ["教练", "运动员"], horizontal=True)
st.session_state["role"] = role

# ── Sidebar: Set selector ──────────────────────────────────────────────
config = load_config()
data_dir = config["dashboard"]["data_dir"]
sessions = load_or_rebuild_index(data_dir)
st.session_state["sessions_index"] = sessions

if sessions:
    session_names = [s["name"] for s in sessions]
    selected = st.sidebar.selectbox(
        "选择训练组",
        options=session_names,
        index=None,
        placeholder="请选择一个训练组...",
    )
    if selected:
        match = next((s for s in sessions if s["name"] == selected), None)
        if match:
            st.session_state["selected_set"] = match
            st.session_state["selected_set_dir"] = match["path"]
    else:
        st.session_state["selected_set"] = None
        st.session_state["selected_set_dir"] = None
else:
    st.sidebar.info("暂无训练数据")

# ── Navigation: 3 page groups ──────────────────────────────────────────
training_pages = [
    st.Page("pages/training.py", title="训练监控", icon=":material/fitness_center:", default=True),
]
analysis_pages = [
    st.Page("pages/analysis.py", title="数据分析", icon=":material/analytics:"),
]
team_visibility = "visible" if role == "教练" else "hidden"
team_pages = [
    st.Page("pages/team.py", title="团队同步", icon=":material/group:", visibility=team_visibility),
]

pg = st.navigation({
    "训练": training_pages,
    "分析": analysis_pages,
    "团队同步": team_pages,
})

# ── Sidebar: Settings expander ─────────────────────────────────────────
with st.sidebar.expander("设置", expanded=False):
    cfg = load_config()

    st.subheader("FINA 扣分阈值")
    fina = cfg.get("fina", {})
    clean_thresh = st.number_input(
        "Clean 阈值 (度)",
        value=fina.get("clean_threshold_deg", 15),
        min_value=0,
        max_value=90,
    )
    minor_thresh = st.number_input(
        "Minor 阈值 (度)",
        value=fina.get("minor_deduction_deg", 30),
        min_value=0,
        max_value=90,
    )
    clean_ded = st.number_input(
        "Clean 扣分",
        value=fina.get("clean_deduction", 0.0),
        min_value=0.0,
        step=0.1,
        format="%.1f",
    )
    minor_ded = st.number_input(
        "Minor 扣分",
        value=fina.get("minor_deduction", 0.2),
        min_value=0.0,
        step=0.1,
        format="%.1f",
    )
    major_ded = st.number_input(
        "Major 扣分",
        value=fina.get("major_deduction", 0.5),
        min_value=0.0,
        step=0.1,
        format="%.1f",
    )

    st.subheader("硬件配置")
    hw = cfg.get("hardware", {})
    camera_url = st.text_input("Camera URL", value=hw.get("camera_url", ""))
    ble_name = st.text_input("BLE 设备名", value=hw.get("ble_device_name", ""))
    ble_uuid = st.text_input("BLE Char UUID", value=hw.get("ble_char_uuid", ""))

    if st.button("保存设置"):
        new_config = {
            "fina": {
                "clean_threshold_deg": clean_thresh,
                "minor_deduction_deg": minor_thresh,
                "clean_deduction": clean_ded,
                "minor_deduction": minor_ded,
                "major_deduction": major_ded,
            },
            "hardware": {
                "camera_url": camera_url,
                "ble_device_name": ble_name,
                "ble_char_uuid": ble_uuid,
            },
            "dashboard": cfg.get("dashboard", {}),
        }
        try:
            save_config(new_config)
            st.success("设置已保存")
        except Exception as e:
            st.error(f"设置保存失败：无法写入 config.toml。请检查文件权限。\n{e}")

# ── Run selected page ──────────────────────────────────────────────────
pg.run()
