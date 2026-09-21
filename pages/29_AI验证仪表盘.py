"""
AI 验证仪表盘 — 页面 29
========================
多窗口 T+1/3/5/10/20 事后验证：方向准确率、Brier、校准曲线。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    show_sortable_df,
    section_header,
)
from core.signal_evaluation import get_evaluation_manager, HORIZONS
from core.signals import ACTION_LABELS
from core.agent_memory import SignalEvaluator
from core.evaluation_scheduler import run_daily_evaluation_if_due, last_run_date

render_page_header(
    title="AI 验证仪表盘",
    icon="🎯",
    description="对 AI 分析信号与结构化决策建议进行 T+1/3/5/10/20 多窗口事后验证，统计方向准确率与置信度校准。",
    help_text="""
    **验证来源：**
    - `20 信号跟踪` 中的决策信号
    - `22 分析历史` 中含 `signal_for_validation` 的结构化 JSON（功能四）

    **指标说明：**
    - **方向准确率**：明确看涨/看跌建议与实际净值方向一致的比例
    - **Brier 分数**：置信度校准误差（越低越好）
    - **ECE**：分桶期望校准误差
    """,
    accent_color="#8B5CF6",
)

render_sidebar_config(show_ai_config=False)
render_top_toolbar(show_ai_config=False)

em = get_evaluation_manager()

# 每日自动跑批（应用启动时由 app.py 触发；此处展示状态）
_auto = st.session_state.get("daily_eval_result")
if _auto:
    st.caption(
        f"🤖 今日自动验证：新增 {_auto.get('created', 0)} 条 · "
        f"信号评判 {_auto.get('legacy', 0)} 条"
    )
elif last_run_date():
    st.caption(f"🤖 最近自动验证日期：{last_run_date()}")

col1, col2 = st.columns([1, 3])
with col1:
    if st.button("▶️ 立即运行验证任务", type="primary", use_container_width=True):
        with st.spinner("正在回填 T+N 窗口验证..."):
            legacy = SignalEvaluator().evaluate_pending_signals()
            batch = em.run_batch()
            st.session_state["last_eval_run"] = {
                "legacy": len(legacy),
                **batch,
            }
            st.rerun()

run_info = st.session_state.get("last_eval_run")
if run_info:
    st.success(
        f"验证完成：新增 {run_info.get('created', 0)} 条 · "
        f"跳过 {run_info.get('skipped', 0)} · "
        f"信号池自动评判 {run_info.get('legacy', 0)} 条"
    )
with col2:
    st.caption("本页为只读统计与校准分析；信号的确认/驳回/结果标记请在「信号跟踪」操作。")
    st.page_link("pages/20_信号跟踪.py", label="前往信号跟踪（确认 / 驳回 / 备注）", icon="🎯")

summary = em.get_summary()
pending = em.count_pending()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("验证样本", summary["total"])
k2.metric("方向准确率", f"{summary['direction_accuracy'] * 100:.1f}%")
k3.metric("平均 Brier", f"{summary['avg_brier']:.3f}")
k4.metric("ECE", f"{summary['ece']:.3f}")
k5.metric("待验证", pending["pending_signals"] + pending["pending_analysis"])

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 总览", "📐 校准图", "🪟 窗口明细", "⏳ 待验证队列", "📈 单基金时间线",
])

with tab1:
    section_header("按验证窗口（交易日）")
    by_h = summary.get("by_horizon") or {}
    if by_h:
        rows = [{
            "窗口": f"T+{h}",
            "样本数": v["total"],
            "可判定": v["decisive"],
            "命中率": f"{v['accuracy'] * 100:.1f}%",
        } for h, v in sorted(by_h.items())]
        show_sortable_df(pd.DataFrame(rows))
    else:
        st.info("暂无验证数据，请先运行验证任务")

    section_header("按动作类型分布")
    by_a = summary.get("by_action") or {}
    if by_a:
        labels = [ACTION_LABELS.get(a, a) for a in by_a.keys()]
        fig = go.Figure(go.Pie(labels=labels, values=list(by_a.values()), hole=0.4))
        fig.update_layout(height=320)
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    buckets = em.get_calibration_data()
    if not buckets or all(b["count"] == 0 for b in buckets):
        st.info("需要更多带置信度的验证样本才能绘制校准曲线")
    else:
        labels = [b["bin"] for b in buckets]
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=labels,
            y=[b["hit_rate"] for b in buckets],
            name="实际命中率",
            marker_color="#3B82F6",
        ))
        fig.add_trace(go.Scatter(
            x=labels,
            y=[b["avg_confidence"] for b in buckets],
            mode="lines+markers",
            name="平均置信度",
            line=dict(color="#F59E0B"),
        ))
        fig.update_layout(
            title="置信度校准（柱=命中率，线=预测置信度）",
            height=380,
            yaxis_title="比率",
        )
        st.plotly_chart(fig, use_container_width=True)

with tab3:
    horizon_filter = st.selectbox("筛选窗口", ["全部"] + [f"T+{h}" for h in HORIZONS])
    h_days = None if horizon_filter == "全部" else int(horizon_filter.replace("T+", ""))
    evs = em.list_evaluations(horizon_days=h_days, limit=300)
    if not evs:
        st.info("暂无窗口明细")
    else:
        rows = [{
            "来源": e.source_type,
            "来源ID": e.source_id,
            "基金": f"{e.fund_name} ({e.fund_code})" if e.fund_code else "—",
            "窗口": f"T+{e.horizon_days}",
            "动作": ACTION_LABELS.get(e.predicted_action, e.predicted_action),
            "置信度": f"{e.confidence:.0%}",
            "实际收益": f"{e.actual_return * 100:+.2f}%",
            "命中": "✅" if e.direction_hit else ("❌" if e.direction_hit is False else "⚠️"),
            "Brier": round(e.brier_score, 4),
            "验证时间": e.evaluated_at,
        } for e in evs]
        show_sortable_df(pd.DataFrame(rows))

with tab4:
    st.markdown(f"**待补全信号：** {pending['pending_signals']} 条")
    st.markdown(f"**待补全结构化分析：** {pending['pending_analysis']} 条")
    st.caption(f"目标窗口：{', '.join(f'T+{h}' for h in pending['horizons'])}")
    st.info(
        "信号来自 `20 信号跟踪`；结构化分析需先在 AI 分析页保存含决策仪表盘 JSON 的历史记录。"
    )
    st.page_link("pages/20_信号跟踪.py", label="前往信号跟踪", icon="📡")
    st.page_link("pages/22_分析历史.py", label="前往分析历史", icon="📚")

with tab5:
    fund_code = st.text_input("基金代码", max_chars=6, placeholder="000001")
    if fund_code.strip():
        evs = em.list_evaluations(fund_code=fund_code.strip().zfill(6), limit=100)
        if not evs:
            st.info("该基金暂无验证记录")
        else:
            df = pd.DataFrame([{
                "窗口": f"T+{e.horizon_days}",
                "动作": e.predicted_action,
                "收益%": e.actual_return * 100,
                "命中": 1 if e.direction_hit else (0 if e.direction_hit is False else 0.5),
            } for e in evs])
            fig = go.Figure(go.Scatter(
                x=df["窗口"], y=df["收益%"],
                mode="markers+text",
                text=df["动作"],
                textposition="top center",
                marker=dict(
                    size=12,
                    color=df["命中"],
                    colorscale=[[0, "#EF4444"], [0.5, "#FBBF24"], [1, "#10B981"]],
                    showscale=False,
                ),
            ))
            fig.update_layout(title=f"基金 {fund_code} 验证时间线", height=360)
            st.plotly_chart(fig, use_container_width=True)
            show_sortable_df(pd.DataFrame([e.to_dict() for e in evs]))
