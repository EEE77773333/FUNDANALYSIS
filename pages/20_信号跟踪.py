"""
信号跟踪 - 页面 20
================
追踪 AI 分析产生的投资决策信号，记录信号准确率，优化后续投资决策。

使用说明:
  1. 活跃信号：查看当前有效的买入/卖出/观望建议
  2. 信号仪表盘：统计总览（准确率、按动作分布、置信度趋势）
  3. 提取信号：从分析报告文本中自动提取结构化信号
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from core.config import config
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    show_info_box,
    show_error,
    render_metrics_row,
    init_page_state,
    check_api_ready,
    safe_run,
    section_header,
)
from core.signals import (
    get_signal_manager,
    VALID_ACTIONS,
    VALID_OUTCOMES,
    ACTION_LABELS,
)


# ============================================================
# Page Config
# ============================================================
init_page_state({
    "signal_analysis_text": "",
})


# ============================================================
# Helpers
# ============================================================

def render_active_signals():
    """活跃信号列表"""
    sm = get_signal_manager()

    col1, col2, col3 = st.columns(3)
    with col1:
        filter_action = st.selectbox("按动作", ["全部"] + VALID_ACTIONS, key="sig_filter_action")
    with col2:
        filter_status = st.selectbox("按状态", ["全部", "active", "confirmed", "rejected", "expired"], key="sig_filter_status")
    with col3:
        filter_outcome = st.selectbox("按结果", ["全部"] + VALID_OUTCOMES, key="sig_filter_outcome")

    signals = sm.list_all(
        status=filter_status if filter_status != "全部" else None,
        action=filter_action if filter_action != "全部" else None,
        outcome=filter_outcome if filter_outcome != "全部" else None,
        limit=100,
    )

    if not signals:
        st.info("📭 暂无信号记录。可以从「提取信号」标签页分析报告，或等待 AI 分析自动生成信号。")
        return

    st.caption(f"共 {len(signals)} 条信号")

    for sig in signals:
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            with col1:
                st.markdown(f"**{sig.action_label}** — {sig.fund_name or sig.fund_code}")
                if sig.reason:
                    st.caption(sig.reason[:120])
                st.caption(f"创建于 {sig.created_at}")

            with col2:
                st.metric("置信度", f"{sig.confidence:.0%}")
            with col3:
                status_colors = {"active": "🟡", "confirmed": "🟢", "rejected": "🔴", "expired": "⚫"}
                sc = status_colors.get(sig.status, "⚪")
                st.caption(f"{sc} {sig.status}")

            with col4:
                if sig.outcome:
                    outcome_colors = {"correct": "✅", "wrong": "❌", "partial": "⚠️"}
                    oc = outcome_colors.get(sig.outcome, "❓")
                    st.caption(f"{oc} {sig.outcome}")

            # 操作按钮
            if sig.status == "active":
                c1, c2 = st.columns([1, 1])
                with c1:
                    if st.button("✅ 采纳", key=f"confirm_{sig.id}"):
                        sm.update_status(sig.id, "confirmed")
                        st.rerun()
                with c2:
                    if st.button("❌ 拒绝", key=f"reject_{sig.id}"):
                        sm.update_status(sig.id, "rejected")
                        st.rerun()

            # 记录结果（已采纳的信号可以标记结果）
            if sig.status == "confirmed" and not sig.outcome:
                c1, c2 = st.columns([1, 3])
                with c1:
                    st.caption("标记结果:")
                with c2:
                    oc = st.selectbox(
                        "结果", ["选择...", "correct", "wrong", "partial"],
                        key=f"oc_{sig.id}", label_visibility="collapsed",
                    )
                    if oc != "选择...":
                        sm.record_outcome(sig.id, oc)
                        st.rerun()

            st.divider()


def render_signal_dashboard():
    """信号统计仪表盘"""
    sm = get_signal_manager()
    stats = sm.get_statistics()

    st.info(
        "📊 本页提供信号池的快速统计。**标准化多窗口验证（T+1/3/5/10/20）、"
        "Brier 分数与概率校准曲线**请前往「AI 验证仪表盘」。"
    )
    st.page_link("pages/29_AI验证仪表盘.py", label="前往 AI 验证仪表盘（校准与准确率）", icon="🎯")
    st.divider()

    if stats["total"] == 0:
        st.info("📭 暂无信号数据")
        return

    # 指标卡片
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("总信号数", stats["total"])
    col2.metric("已结算", stats["resolved_total"])
    col3.metric("准确率", f"{stats['accuracy'] * 100:.0f}%")
    col4.metric("平均置信度", f"{stats['avg_confidence'] * 100:.0f}%")
    col5.metric("活跃中", stats["by_status"].get("active", 0))

    st.divider()

    # 按动作分布
    col1, col2 = st.columns(2)

    with col1:
        section_header("按动作类型分布")
        by_action = stats["by_action"]
        if by_action:
            labels = [ACTION_LABELS.get(a, a) for a in by_action.keys()]
            values = list(by_action.values())
            colors = {
                "buy": "#DC2626", "add": "#EF4444", "hold": "#9CA3AF",
                "reduce": "#F59E0B", "sell": "#16A34A", "watch": "#60A5FA", "avoid": "#16A34A",
            }
            fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.4,
                                          marker=dict(colors=[colors.get(a, "#9CA3AF") for a in by_action.keys()]))])
            fig.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        section_header("信号结果分布")
        c = stats["correct"]
        w = stats["wrong"]
        p = stats["partial"]
        if c + w + p > 0:
            fig = go.Figure(data=[go.Bar(
                x=["正确", "错误", "部分正确"],
                y=[c, w, p],
                marker_color=["#10B981", "#EF4444", "#FBBF24"],
            )])
            fig.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无结果数据")

    # 按状态分布
    by_status = stats.get("by_status", {})
    if by_status:
        section_header("按状态分布")
        status_labels = {"active": "活跃", "confirmed": "已确认", "rejected": "已拒绝", "expired": "已过期"}
        cols = st.columns(len(by_status))
        for i, (status, cnt) in enumerate(by_status.items()):
            cols[i].metric(status_labels.get(status, status), cnt)


def render_extract_signal():
    """从分析文本提取信号"""
    section_header("从分析报告提取决策信号")
    st.caption("粘贴 AI 分析报告文本，自动识别其中的投资操作建议")

    analysis_text = st.text_area(
        "分析报告文本",
        placeholder="请粘贴 AI 生成的分析报告内容...",
        height=250,
        key="extract_analysis_text",
    )

    fund_code = st.text_input("基金代码", placeholder="如 000001", key="extract_fund_code")

    if st.button("🔍 提取信号", use_container_width=True, key="extract_btn"):
        if not analysis_text:
            st.error("请粘贴分析报告文本")
        elif not fund_code:
            st.error("请输入基金代码")
        elif not check_api_ready():
            pass
        else:
            sm = get_signal_manager()
            with st.spinner("AI 正在分析报告..."):
                ids = sm.extract_from_analysis(analysis_text, fund_code)
            if ids:
                st.success(f"✅ 成功提取 {len(ids)} 条信号")
                for sid in ids:
                    sig = sm.get(sid)
                    if sig:
                        st.info(f"{sig.action_label} (置信度: {sig.confidence:.0%}): {sig.reason}")
            else:
                st.warning("⚠️ 未能从文本中识别到明确的投资信号")


# ============================================================
# Main
# ============================================================

def main():
    render_page_header(
        title="信号跟踪",
        icon="🎯",
        description="操作层：确认/驳回/记录信号结果，管理 AI 投资决策信号池",
        help_text="使用说明：1. 活跃信号：确认/驳回/标记结果 2. 仪表盘：快速统计（深度校准见 29 页）3. 提取信号：从分析报告提取结构化信号",
        accent_color="#F59E0B",
    )

    sidebar_config = render_sidebar_config()
    render_top_toolbar()

    tab1, tab2, tab3 = st.tabs([
        "📡 活跃信号",
        "📊 信号仪表盘",
        "🔍 提取信号",
    ])

    with tab1:
        render_active_signals()

    with tab2:
        render_signal_dashboard()

    with tab3:
        render_extract_signal()


if __name__ == "__main__":
    main()
