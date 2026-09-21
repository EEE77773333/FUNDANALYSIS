"""
债券型基金筛选 — 页面 2
=======================
寻找底仓防守资产，重点考察信用风险、回撤控制与久期管理。
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
    title="债券基金筛选", icon="📊",
    description="筛选适合当前行情的稳健型债券基金。重点考察信用风险、回撤控制、久期管理与费率成本。",
    help_text="**硬性标准：** 年化波动率<3% | 最大回撤<3% | 信用AA+为主 | 管理费<0.8% | 经理≥3年固收经验",
)

sidebar_config = render_sidebar_config()
render_top_toolbar()
with st.expander("📊 硬性筛选标准", expanded=True):

    fund_count = st.slider("分析数量（每种类型）", 20, 100, 50, 10)
    bond_subtype = st.selectbox("债券子类型", ["全部债基", "纯债基金", "一级债基", "二级债基", "可转债基金", "中短债基金"], index=0)

with st.expander("🎚️ 质量过滤", expanded=False):
    min_years = st.number_input("最少成立年数", 1, 10, 3)
    max_vol = st.slider("年化波动率上限（%）", 1.0, 10.0, 3.0, 0.5)
    max_drawdown = st.slider("最大回撤上限（%）", -10.0, -0.5, -3.0, 0.5)
    max_fee = st.slider("管理费上限（%）", 0.1, 1.5, 0.8, 0.1)
    min_manager_years = st.slider("基金经理最低固收年限", 1, 10, 3)

section_header("数据获取")

col1, col2 = st.columns([1, 2])
with col1:
    if st.button("📡 获取债券基金数据", use_container_width=True):
        with st.spinner(f"筛选债券基金（波动率<{max_vol}% | 回撤<{max_drawdown}% | 费率<{max_fee}%）..."):
            bond_type = "债券型" if bond_subtype == "全部债基" else bond_subtype
            fund_list = fetcher.get_fund_list(bond_type)
            if fund_list.empty:
                show_error("未获取到数据")
            else:
                from core.utils import calc_annualized_return, calc_max_drawdown, calc_annual_volatility
                results, skipped = [], {"no_nav": 0, "short": 0, "high_vol": 0, "high_dd": 0, "high_fee": 0}
                batch = fund_list.sample(n=min(fund_count, len(fund_list)), random_state=42) if len(fund_list) > fund_count else fund_list
                progress = st.progress(0)
                for i, (_, row) in enumerate(batch.iterrows()):
                    code = str(row["基金代码"])
                    nav = fetcher.get_fund_nav_history(code, years=3)
                    if nav.empty: skipped["no_nav"] += 1; continue
                    nav_s = nav.sort_values("日期", ascending=True)["单位净值"].dropna()
                    rets = nav_s.pct_change().dropna()
                    if len(nav_s) < 60: skipped["short"] += 1; continue
                    vol = calc_annual_volatility(rets) * 100
                    dd = calc_max_drawdown(nav_s) * 100
                    info = fetcher.get_fund_manager_info(code)
                    fee = safe_float(info.get("管理费率%", 0) if info else 0)
                    if vol > max_vol: skipped["high_vol"] += 1; continue
                    if dd < max_drawdown: skipped["high_dd"] += 1; continue
                    if fee > max_fee: skipped["high_fee"] += 1; continue
                    results.append({
                        "基金代码": code, "基金简称": row.get("基金简称", ""), "基金类型": row.get("基金类型", ""),
                        "年化收益率": f"{calc_annualized_return(nav_s)*100:.2f}%",
                        "年化波动率": f"{vol:.2f}%", "最大回撤": f"{dd:.2f}%",
                        "管理费率": f"{fee:.2f}%",
                        "基金经理": info.get("基金经理", "") if info else "",
                        "基金公司": info.get("基金公司", "") if info else "",
                    })
                    progress.progress(min((i+1)/len(batch), 1.0), text=f"已通过 {len(results)} 只")
                progress.empty()
                if results:
                    df = pd.DataFrame(results)
                    st.session_state["bond_fund_data"] = df
                    st.session_state["bond_data_fetched"] = True
                    st.success(f"✅ {len(df)}只通过 | 波动率>{max_vol}%: {skipped['high_vol']} | 回撤>{abs(max_drawdown)}%: {skipped['high_dd']} | 费率高: {skipped['high_fee']}")
                else:
                    show_error(f"扫描{len(batch)}只，无通过。建议放宽：波动率>{max_vol}%({skipped['high_vol']}只) 回撤超标({skipped['high_dd']}只)")

with col2:
    if st.session_state.get("bond_data_fetched"):
        show_sortable_df(st.session_state["bond_fund_data"], f"已加载 {len(st.session_state['bond_fund_data'])} 只")

st.markdown("---")
section_header("AI 债券基金筛选分析")
if not check_api_ready(): st.stop()

analyze_clicked = render_analysis_button("🚀 开始 AI 筛选分析", disabled=not st.session_state.get("bond_data_fetched"), key="btn_bond")
if analyze_clicked:
    df = st.session_state["bond_fund_data"]
    template = pm.get("bond_fund_screening")
    system_prompt, user_prompt = template.render({
        "fund_data": df.to_markdown(index=False),
        "market_context": f"子类型: {bond_subtype} | 筛选: 成立≥{min_years}年, 波动率<{max_vol}%, 回撤<{max_drawdown}%, 费率<{max_fee}%, 经理≥{min_manager_years}年 | 共{len(df)}只候选",
    })
    if sidebar_config.get("model"): analyzer._model = sidebar_config["model"]
    depth_map = {"简要": 2048, "标准": 4096, "深度": 8192, "极致": 16384}
    max_tokens = depth_map.get(sidebar_config.get("depth", "标准"), 4096)

    final_result = run_analysis_stream(
        analyzer, system_prompt, user_prompt,
        max_tokens=max_tokens, temperature=0.3,
        placeholder_label="📝 债券筛选报告",
        page_name="债券基金筛选",
    )

    if final_result and final_result.get("success"):
        st.success("✅ 完成"); show_elapsed_time(final_result.get("elapsed_seconds", 0)); show_token_usage(final_result.get("usage", {}))

if not analyze_clicked and not st.session_state.get("bond_data_fetched"):
    st.info("👆 请先获取数据，再启动 AI 分析")
