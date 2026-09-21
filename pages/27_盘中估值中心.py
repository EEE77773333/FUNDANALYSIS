"""
盘中估值中心 — 页面 27
========================
重仓股穿透估值 + ETF 联接追踪 + 官方估算对照。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.graph_objects as go

from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    render_intraday_nav,
    show_sortable_df,
    section_header,
)

render_page_header(
    title="盘中估值中心",
    icon="📡",
    description="交易时段基金盘中估值：前十大重仓穿透加权、ETF联接底层追踪，并对照天天基金官方估算。",
    help_text="""
    **估值模式：**
    - **ETF联接**：自动识别联接基金并跟踪场内 ETF 涨跌幅
    - **重仓穿透**：用前十大持仓股票实时涨跌加权估算
    - **官方估算**：持仓不足时回退天天基金估算

    **说明：** 穿透估值基于最近季报持仓，存在滞后；仅供参考，不构成投资建议。
    """,
    accent_color="#F59E0B",
)

render_sidebar_config(show_ai_config=False)
render_top_toolbar(show_ai_config=False)

section_header("单基金盘中估值")

col1, col2 = st.columns([1, 2])
with col1:
    fund_code = st.text_input("基金代码", "", max_chars=6, placeholder="如 000001")
    auto_refresh = st.checkbox("60 秒自动刷新", value=False)
    if st.button("📡 计算盘中估值", type="primary", use_container_width=True):
        st.session_state["intraday_code"] = fund_code.strip()

code = st.session_state.get("intraday_code", fund_code.strip())


@st.fragment(run_every=60 if auto_refresh and code else None)
def _intraday_panel(active_code: str):
    if not active_code:
        st.info("👆 输入基金代码并点击「计算盘中估值」")
        return
    result = render_intraday_nav(active_code, expanded=True, show_table=True)
    if not result:
        return
    st.session_state["last_intraday"] = result.to_dict()
    # 落盘分时快照
    from core.intraday_nav import save_intraday_snapshot, load_intraday_snapshots
    save_intraday_snapshot(result)
    d = result.to_dict()
    official = d.get("official_estimate") or {}
    if official and d["mode"] != "official_fallback":
        labels = ["穿透估算", "官方估算"]
        values = [d["estimated_pct"], float(official.get("估算涨幅%", 0) or 0)]
        fig = go.Figure(go.Bar(
            x=labels, y=values,
            marker_color=["#3B82F6", "#94A3B8"],
            text=[f"{v:+.2f}%" for v in values],
            textposition="outside",
        ))
        fig.update_layout(
            title="穿透估算 vs 官方估算（涨跌幅%）",
            height=280,
            yaxis_title="涨跌幅 %",
        )
        st.plotly_chart(fig, use_container_width=True)

    # 分时曲线（当日快照）
    snap = load_intraday_snapshots(active_code)
    if len(snap) >= 2:
        fig_ts = go.Figure(go.Scatter(
            x=snap["time"],
            y=snap["estimated_pct"],
            mode="lines+markers",
            line=dict(color="#F59E0B", width=2),
            fill="tozeroy",
            fillcolor="rgba(245,158,11,0.12)",
            name="估算涨跌%",
        ))
        fig_ts.add_hline(y=0, line_dash="dash", line_color="#94A3B8")
        fig_ts.update_layout(
            title=f"当日盘中估值分时（{len(snap)} 个采样点）",
            height=300,
            yaxis_title="估算涨跌 %",
            xaxis_title="时间",
        )
        st.plotly_chart(fig_ts, use_container_width=True)
    elif auto_refresh:
        st.caption("⏳ 分时曲线将随刷新逐步积累采样点")

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.page_link("pages/08_FAMAS单基金深度分析.py", label="深度分析", icon="🔬")
    with c2:
        st.page_link("pages/09_持续监控预警.py", label="加入监控", icon="🚨")
    with c3:
        st.page_link("pages/19_组合管理.py", label="我的组合", icon="💼")


with col2:
    _intraday_panel(code)

st.markdown("---")
section_header("批量观察（可选）")
batch = st.text_area(
    "每行一个基金代码（最多 10 只）",
    height=100,
    placeholder="000001\n110011\n518880",
)
if batch.strip() and st.button("📡 批量估算", use_container_width=True):
    codes = [c.strip().zfill(6) for c in batch.splitlines() if c.strip() and len(c.strip()) <= 6][:10]
    rows = []
    from core.intraday_nav import get_intraday_engine
    engine = get_intraday_engine()
    for c in codes:
        r = engine.estimate(c)
        rows.append({
            "基金代码": c,
            "基金简称": r.fund_name,
            "模式": r.mode,
            "估算涨跌%": r.estimated_pct,
            "估算净值": r.estimated_nav,
            "置信度": r.confidence,
        })
    if rows:
        import pandas as pd
        show_sortable_df(pd.DataFrame(rows))
