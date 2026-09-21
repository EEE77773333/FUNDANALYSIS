"""
赛道再平衡对账 — 页面 30
========================
持仓基金 → 主题赛道聚类 → 目标权重 → 再平衡对账清单。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import pandas as pd

from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    show_sortable_df,
    section_header,
)
from core.portfolio import get_portfolio_manager
from core.track_rebalance import (
    get_track_rebalance_engine,
    BALANCE_PRESETS,
)

render_page_header(
    title="赛道再平衡对账",
    icon="⚖️",
    description="将组合持仓聚类到可观察主题赛道，对比目标权重并生成再平衡对账建议（ifund 思路）。",
    help_text="""
    **流程：**
    1. 选择组合 → 自动解析每只基金的主题归属（基金名称 + 持仓穿透）
    2. 设置均衡强度（松/中/紧）→ 计算目标赛道权重
    3. 查看偏离与再平衡建议 → 可选一键回写权重

    **说明：** 目标权重为战术观察参考，不构成投资建议。
    """,
    accent_color="#10B981",
)

render_sidebar_config(show_ai_config=False)
render_top_toolbar(show_ai_config=False)

pm = get_portfolio_manager()
engine = get_track_rebalance_engine()
portfolios = pm.list_all()

if not portfolios:
    st.info("👆 请先在「我的组合」创建组合并添加持仓")
    st.page_link("pages/19_组合管理.py", label="前往组合管理", icon="💼")
    st.stop()

pid = st.selectbox(
    "选择组合",
    [p.id for p in portfolios],
    format_func=lambda i: next(f"{p.name}（{p.holding_count}只）" for p in portfolios if p.id == i),
)

portfolio = pm.get(pid)
if not portfolio or not portfolio.holdings:
    st.warning("该组合暂无持仓")
    st.stop()

holdings = portfolio.holdings

c1, c2, c3 = st.columns(3)
with c1:
    balance_label = st.selectbox("均衡强度", list(BALANCE_PRESETS.keys()), index=1)
    balance_strength = BALANCE_PRESETS[balance_label]
with c2:
    threshold = st.slider("偏离阈值（%）", 1, 10, 3)
with c3:
    include_flow = st.checkbox("叠加主题资金热度", value=True)

flow_tilt = st.checkbox(
    "资金热度参与目标权重（净流入 Top 赛道 ±2% 微调）",
    value=False,
    disabled=not include_flow,
    help="开启后，目标权重在均衡基础上向净流入较高的赛道有界倾斜（单赛道上限 ±2%），再重新归一。",
)

cache_sig = f"{pid}|{balance_strength}|{threshold}|{include_flow}|{flow_tilt}"
if st.button("🔄 刷新赛道分析", type="primary", use_container_width=True):
    st.session_state.pop("track_result", None)
    st.session_state.pop("track_sig", None)

if st.session_state.get("track_sig") != cache_sig:
    with st.spinner("正在穿透持仓并聚类赛道..."):
        st.session_state["track_result"] = engine.analyze(
            holdings,
            balance_strength=balance_strength,
            deviation_threshold=threshold / 100.0,
            include_flow=include_flow,
            flow_tilt=flow_tilt,
        )
        st.session_state["track_sig"] = cache_sig

result = st.session_state["track_result"]
track_rows = result["track_rows"]
fund_infos = result["fund_infos"]
actions = result["actions"]

k1, k2, k3, k4 = st.columns(4)
k1.metric("持仓基金", len(fund_infos))
k2.metric("赛道数", len(track_rows))
k3.metric("组合权重合计", f"{result['total_weight'] * 100:.1f}%")
k4.metric("待调赛道", sum(1 for a in actions if a.action != "hold" and abs(a.suggested_delta_pct) > 0))

if result.get("flow_tilt"):
    st.caption("🌊 目标权重已按主题资金净流入做有界微调（±2% 上限）")

section_header("赛道聚类分布")
track_df = pd.DataFrame([{
    "赛道": r.track,
    "当前权重%": round(r.current_weight * 100, 2),
    "目标权重%": round(r.target_weight * 100, 2),
    "偏离%": round(r.deviation * 100, 2),
    "基金数": r.fund_count,
    "代表基金": r.representative_name,
    "主题净流入(亿)": r.theme_flow_yi,
} for r in track_rows])

if not track_df.empty:
    col_a, col_b = st.columns(2)
    with col_a:
        fig = px.pie(
            track_df,
            names="赛道",
            values="当前权重%",
            title="当前赛道权重",
            hole=0.35,
        )
        fig.update_layout(height=360)
        st.plotly_chart(fig, use_container_width=True)
    with col_b:
        fig2 = px.bar(
            track_df.assign(偏离绝对值=track_df["偏离%"].abs()).sort_values("偏离绝对值", ascending=True),
            x="偏离%",
            y="赛道",
            orientation="h",
            color="偏离%",
            color_continuous_scale=["#16A34A", "#F1F5F9", "#DC2626"],
            color_continuous_midpoint=0,
            title="赛道偏离（当前 - 目标）",
        )
        fig2.update_layout(height=360)
        st.plotly_chart(fig2, use_container_width=True)

section_header("赛道明细")
show_sortable_df(track_df)

section_header("基金 → 赛道映射")
fund_df = pd.DataFrame([{
    "基金代码": f.fund_code,
    "基金名称": f.fund_name,
    "组合权重%": round(f.portfolio_weight * 100, 2),
    "主赛道": f.primary_track,
    "映射来源": f.mapping_source,
    "赛道拆分": "、".join(f"{k}({v:.0%})" for k, v in f.track_shares.items()),
} for f in fund_infos])
show_sortable_df(fund_df)

section_header("再平衡对账清单")
action_df = pd.DataFrame([{
    "操作": {"add": "➕ 加仓", "reduce": "➖ 减仓", "hold": "⏸️ 持有"}.get(a.action, a.action),
    "赛道": a.track,
    "基金": f"{a.fund_name} ({a.fund_code})",
    "当前权重%": round(a.current_weight_pct, 2),
    "建议调整%": a.suggested_delta_pct,
    "理由": a.reason,
} for a in actions if a.action != "hold"])
if action_df.empty:
    st.success("✅ 各赛道偏离均在阈值内，暂无需调仓")
else:
    show_sortable_df(action_df)

st.markdown("---")
c1, c2, c3, c4 = st.columns(4)
with c1:
    if st.button("💾 一键回写目标权重", type="primary", use_container_width=True):
        n = engine.apply(pid, result)
        st.success(f"✅ 已更新 {n} 条持仓权重")
        st.session_state.pop("track_result", None)
        st.session_state.pop("track_sig", None)
        st.rerun()
with c2:
    st.page_link("pages/19_组合管理.py", label="组合管理", icon="💼")
with c3:
    st.page_link("pages/07_组合诊断优化.py", label="组合诊断", icon="🩺")
with c4:
    st.page_link("pages/28_主题资金流雷达.py", label="主题资金", icon="🌊")
