"""
指数型基金筛选 — 页面 3
=======================
布局宽基或特定赛道，硬性过滤：PE百分位、跟踪误差、规模流动性、费率。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import streamlit as st
import pandas as pd
from core.config import config

from core.data_fetcher import get_fetcher, INDEX_CODE_MAP
from core.ai_analyzer import get_analyzer
from core.prompt_templates import get_prompt_manager
from core.utils import (
    fmt_pct, fmt_money, safe_float,
    calc_annualized_return, calc_max_drawdown, calc_sharpe_ratio, calc_annual_volatility,
    calc_sortino_ratio, calc_calmar_ratio,
)
from core.ui_components import (
    render_page_header, render_sidebar_config, render_top_toolbar, render_analysis_button,
    show_token_usage, show_elapsed_time, show_error, show_warning_box, show_info_box,
    show_dataframe, show_sortable_df,
    check_api_ready, safe_run, run_analysis_stream,
    section_header,
)

fetcher = get_fetcher()
analyzer = get_analyzer()
pm = get_prompt_manager()

render_page_header(
    title="指数基金筛选", icon="📉",
    description="布局宽基或赛道。硬性过滤：PE分位、跟踪误差、规模、费率、折溢价。",
    help_text="**核心指标：** PE/PB百分位(低估买入) | 跟踪误差(<2%/年) | 折溢价(|<2%|) | 规模(2-100亿) | 费率(越低越好)",
)

sidebar_config = render_sidebar_config()
render_top_toolbar()
with st.expander("📊 指数选择 & 硬性过滤", expanded=False):
    index_name = st.selectbox("目标指数", list(INDEX_CODE_MAP.keys()), index=0)
    prefer_type = st.radio("基金类型", ["不限", "场内ETF优先", "场外联接优先", "两者对比"], index=0)
    min_scale = st.selectbox("最低规模（亿）", [2, 5, 10, 20, 50], index=0)
    max_tracking_error = st.slider("年化跟踪误差上限（%）", 0.5, 5.0, 2.0, 0.5, help="指数基金核心指标，越小越好")
    max_premium = st.slider("折溢价容忍度（%）", 1.0, 5.0, 2.0, 0.5, help="ETF市价vs净值的偏离，超过此值预警")
    pe_pct_warn = st.slider("PE分位警告线（%）", 20, 80, 50, 10, help="PE分位超过此值发出高估警告")

section_header("指数估值与基金数据")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("📡 获取指数估值", use_container_width=True):
        with st.spinner(f"获取 {index_name} 估值..."):
            val = fetcher.get_index_valuation(index_name)
            if val:
                st.session_state["index_valuation"] = val
                st.success("✅ 估值获取成功")
    if st.session_state.get("index_valuation"):
        val = st.session_state["index_valuation"]
        m1, m2, m3 = st.columns(3)
        m1.metric("当前 PE", val.get("PE", "N/A"))
        pct = val.get("PE百分位", "N/A")
        m2.metric("PE 百分位", f"{pct}%" if pct != "N/A" else "N/A")
        m3.metric("当前 PB", val.get("PB", "N/A"))
        if isinstance(pct, (int, float)):
            if pct < pe_pct_warn * 0.6: show_info_box(f"🟢 {index_name} PE处{pct}%分位 — **低估区域**，安全边际高")
            elif pct < pe_pct_warn: show_info_box(f"🟡 {index_name} PE处{pct}%分位 — **合理区域**")
            else: show_warning_box(f"🔴 {index_name} PE处{pct}%分位 — **高估区域**，建议等待或极小仓位定投")

with col2:
    if st.button("📡 获取指数基金列表", use_container_width=True):
        with st.spinner(f"搜索跟踪 {index_name} 的基金..."):
            all_funds = fetcher.get_all_funds_basic()
            if not all_funds.empty:
                keywords = [index_name] + index_name.split(" ")
                mask = pd.Series(False, index=all_funds.index)
                for kw in keywords: mask |= all_funds["基金简称"].str.contains(kw, na=False)
                candidates = all_funds[mask].head(30) if mask.any() else fetcher.get_fund_list("指数型").head(30)
                results = []
                for _, row in candidates.iterrows():
                    code = str(row["基金代码"])
                    nav = fetcher.get_fund_nav_history(code, years=2)
                    estimate = fetcher.get_realtime_estimate(code)
                    if nav.empty: continue
                    nav_s = nav.sort_values("日期", ascending=True)["单位净值"].dropna()
                    if len(nav_s) < 30: continue
                    results.append({
                        "基金代码": code, "基金简称": row.get("基金简称", ""),
                        "基金类型": row.get("基金类型", ""),
                        "近2年年化": f"{calc_annualized_return(nav_s, 244)*100:.2f}%",
                        "最新净值": nav_s.iloc[-1],
                        "估算涨幅": f"{safe_float(estimate.get('估算涨幅%', 0)):.2f}%" if estimate else "N/A",
                    })
                if results:
                    st.session_state["index_fund_data"] = pd.DataFrame(results)
                    st.success(f"✅ {len(results)} 只")
                else: show_error("未找到相关基金")
    if st.session_state.get("index_fund_data") is not None:
        show_sortable_df(st.session_state["index_fund_data"])

st.markdown("---")
section_header("AI 指数基金对比分析")
if not check_api_ready(): st.stop()

has_data = st.session_state.get("index_valuation") and st.session_state.get("index_fund_data") is not None
analyze_clicked = render_analysis_button("🚀 开始 AI 对比分析", disabled=not has_data, key="btn_index")
if analyze_clicked:
    pm = get_prompt_manager(); template = pm.get("index_fund_screening")
    system_prompt, user_prompt = template.render({
        "index_name": index_name,
        "valuation_data": str(st.session_state.get("index_valuation", {})),
        "fund_data": st.session_state["index_fund_data"].to_markdown(index=False),
    })
    if sidebar_config.get("model"): analyzer._model = sidebar_config["model"]
    depth_map = {"简要": 2048, "标准": 4096, "深度": 8192, "极致": 16384}
    max_tokens = depth_map.get(sidebar_config.get("depth", "标准"), 4096)

    final_result = run_analysis_stream(
        analyzer, system_prompt, user_prompt,
        max_tokens=max_tokens, temperature=0.3,
        placeholder_label="📝 指数筛选报告",
        page_name="指数基金筛选",
    )

    if final_result and final_result.get("success"): show_elapsed_time(final_result.get("elapsed_seconds", 0)); show_token_usage(final_result.get("usage", {}))
if not analyze_clicked and not has_data: st.info("👆 请先获取估值和基金数据")
