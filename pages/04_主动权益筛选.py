"""
主动权益类基金筛选 — 页面 4
===========================
硬性过滤：夏普、最大回撤、持仓集中度、经理年限、规模。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import streamlit as st
import pandas as pd
from core.config import config

from core.data_fetcher import get_fetcher
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
    title="主动权益筛选", icon="🎯",
    description="硬性过滤：夏普比率、最大回撤、持仓集中度、经理年限。筛选穿越牛熊的优质主动管理基金。",
    help_text="**黄金标准：** 夏普>1.0 | 回撤<30% | 集中度<50% | 经理≥5年(穿越牛熊) | 规模20-150亿(策略舒适区)",
)

sidebar_config = render_sidebar_config()
render_top_toolbar()
with st.expander("🎚️ 硬性过滤标准", expanded=False):

    fund_type = st.multiselect("基金类型", ["股票型", "混合型-偏股", "混合型-灵活", "混合型-平衡"], default=["股票型", "混合型-偏股"])
    fund_count = st.slider("分析数量（每种类型）", 20, 100, 50, 10)

st.sidebar.markdown("---")
with st.expander("📏 质量门槛", expanded=False):
    min_sharpe = st.slider("夏普比率 ≥", 0.0, 2.0, 0.8, 0.1)
    max_drawdown_limit = st.slider("最大回撤 ≤（%）", -50.0, -5.0, -30.0, 1.0)
    max_concentration = st.slider("前十大集中度 ≤（%）", 30, 80, 50, 5)
    min_manager_years = st.slider("基金经理最低年限", 2, 15, 5)
    min_scale_opt = st.selectbox("管理规模区间（亿）", ["不限", "10-100", "20-150", "30-200", "50-300"], index=1)
    auto_relax = st.checkbox("🔄 无结果时自动放宽条件", value=True)

section_header("数据获取与分析")

if st.button("📡 获取主动权益基金数据", use_container_width=True, type="primary"):
    with st.spinner("正在筛选..."):
        results, stats = [], {"total": 0, "no_nav": 0, "short": 0, "low_sharpe": 0, "high_dd": 0, "high_conc": 0}
        for ft in fund_type:
            fund_list = fetcher.get_fund_list(ft)
            if fund_list.empty: continue
            batch = fund_list.sample(n=min(fund_count, len(fund_list)), random_state=42) if len(fund_list) > fund_count else fund_list
            progress = st.progress(0, text=f"分析 {ft} 中...")
            for i, (_, row) in enumerate(batch.iterrows()):
                code = str(row["基金代码"]); stats["total"] += 1
                nav = fetcher.get_fund_nav_history(code, years=5)
                if nav.empty: stats["no_nav"] += 1; continue
                if len(nav) < 120: stats["short"] += 1; continue
                nav_s = nav.sort_values("日期", ascending=True)["单位净值"].dropna()
                rets = nav_s.pct_change().dropna()
                if len(nav_s) < 60: stats["short"] += 1; continue
                ann_ret = calc_annualized_return(nav_s); max_dd = calc_max_drawdown(nav_s)
                sharpe = calc_sharpe_ratio(rets); vol = calc_annual_volatility(rets)
                info = fetcher.get_fund_manager_info(code); holdings = fetcher.get_fund_holdings(code)
                conc = holdings["占净值比例%"].sum() if holdings is not None and not holdings.empty and "占净值比例%" in holdings.columns else 0
                if sharpe < min_sharpe: stats["low_sharpe"] += 1; continue
                if max_dd * 100 < max_drawdown_limit: stats["high_dd"] += 1; continue
                if conc > max_concentration: stats["high_conc"] += 1; continue
                results.append({
                    "基金代码": code, "基金简称": row.get("基金简称", ""), "基金类型": row.get("基金类型", ""),
                    "年化收益率": f"{ann_ret*100:.2f}%", "最大回撤": f"{max_dd*100:.2f}%",
                    "夏普比率": f"{sharpe:.2f}", "年化波动率": f"{vol*100:.2f}%",
                    "持仓集中度": f"{conc:.1f}%" if conc else "N/A",
                    "基金经理": info.get("基金经理", "") if info else "N/A",
                    "基金公司": info.get("基金公司", "") if info else "N/A",
                    "管理费率": f"{safe_float(info.get('管理费率%', 0) if info else 0):.2f}%",
                })
                progress.progress(min((i+1)/len(batch), 1.0), text=f"通过 {len(results)} 只")
            progress.empty()
        if results:
            df = pd.DataFrame(results)
            df["_sort"] = df["夏普比率"].astype(float)
            df = df.sort_values("_sort", ascending=False).drop(columns=["_sort"])
            st.session_state["active_fund_data"] = df; st.session_state["active_data_fetched"] = True
            st.success(f"✅ {len(df)}只通过 | 扫描{stats['total']} | 无数据{stats['no_nav']} | 夏普低{stats['low_sharpe']} | 回撤大{stats['high_dd']} | 集中度高{stats['high_conc']}")
        elif auto_relax:
            relaxed = max(0.3, min_sharpe - 0.3)
            st.warning(f"夏普≥{min_sharpe}无结果，放宽至≥{relaxed}...（回撤/集中度暂时放宽）")
            r2 = []
            for ft in fund_type:
                fl = fetcher.get_fund_list(ft)
                if fl.empty: continue
                bt = fl.sample(n=min(fund_count*2, len(fl)), random_state=42)
                for _, row in bt.iterrows():
                    code = str(row["基金代码"])
                    nav = fetcher.get_fund_nav_history(code, years=5)
                    if nav.empty or len(nav) < 120: continue
                    nav_s = nav.sort_values("日期", ascending=True)["单位净值"].dropna()
                    rets = nav_s.pct_change().dropna()
                    if len(nav_s) < 60: continue
                    sh = calc_sharpe_ratio(rets)
                    if sh >= relaxed:
                        r2.append({
                            "基金代码": code, "基金简称": row.get("基金简称", ""), "基金类型": row.get("基金类型", ""),
                            "年化收益率": f"{calc_annualized_return(nav_s)*100:.2f}%",
                            "最大回撤": f"{calc_max_drawdown(nav_s)*100:.2f}%",
                            "夏普比率": f"{sh:.2f}", "年化波动率": f"{calc_annual_volatility(rets)*100:.2f}%",
                            "持仓集中度": "N/A", "基金经理": "N/A", "基金公司": "N/A", "管理费率": "N/A",
                        })
            if r2:
                df2 = pd.DataFrame(r2); df2["_s"] = df2["夏普比率"].astype(float)
                st.session_state["active_fund_data"] = df2.sort_values("_s", ascending=False).drop(columns=["_s"])
                st.session_state["active_data_fetched"] = True
                st.success(f"✅ 放宽后 {len(r2)} 只")
            else: show_error("放宽后仍无结果")
        else: show_error(f"扫描{stats['total']}只 | 夏普<{min_sharpe}:{stats['low_sharpe']} | 回撤超标:{stats['high_dd']} | 集中度过高:{stats['high_conc']}\n💡 建议放宽参数")

if st.session_state.get("active_data_fetched"):
    df = st.session_state["active_fund_data"]
    st.markdown(f"**已筛选 {len(df)} 只**")
    if len(df) > 0:
        returns = df["年化收益率"].str.rstrip("%").astype(float)
        sharpes = df["夏普比率"].astype(float)
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("平均年化", f"{returns.mean():.2f}%"); m2.metric("最高年化", f"{returns.max():.2f}%")
        m3.metric("平均夏普", f"{sharpes.mean():.2f}"); m4.metric("基金数量", len(df))
    show_sortable_df(df)

st.markdown("---")
section_header("AI 主动权益深度分析")
if not check_api_ready(): st.stop()
analyze_clicked = render_analysis_button("🚀 开始 AI 深度分析", disabled=not st.session_state.get("active_data_fetched"), key="btn_active")
if analyze_clicked:
    df = st.session_state["active_fund_data"]
    pm = get_prompt_manager(); template = pm.get("active_fund_screening")
    system_prompt, user_prompt = template.render({"fund_data": df.to_markdown(index=False), "benchmark_data": "沪深300"})
    if sidebar_config.get("model"): analyzer._model = sidebar_config["model"]
    depth_map = {"简要": 2048, "标准": 4096, "深度": 8192, "极致": 16384}
    max_tokens = depth_map.get(sidebar_config.get("depth", "标准"), 4096)
    final_result = run_analysis_stream(
        analyzer, system_prompt, user_prompt,
        max_tokens=max_tokens, temperature=0.3,
        placeholder_label="📝 深度分析报告"
    )
    if final_result and final_result.get("success"): show_elapsed_time(final_result.get("elapsed_seconds", 0)); show_token_usage(final_result.get("usage", {}))
if not analyze_clicked and not st.session_state.get("active_data_fetched"): st.info("👆 请先获取数据")
