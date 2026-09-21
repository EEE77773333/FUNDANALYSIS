"""
基金PK擂台 — 页面 11
=====================
多基金横向对比：雷达图 + 指标矩阵 + AI 裁判。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from core.data_fetcher import get_fetcher
from core.ai_analyzer import get_analyzer
from core.utils import (
    safe_float, calc_annualized_return, calc_max_drawdown,
    calc_sharpe_ratio, calc_annual_volatility, calc_sortino_ratio, calc_calmar_ratio,
)
from core.ui_components import (
    render_page_header, render_sidebar_config, render_top_toolbar, render_analysis_button,
    show_token_usage, show_elapsed_time, show_error, show_sortable_df,
    check_api_ready, run_analysis_stream,
    section_header,
)

render_page_header("基金PK擂台", "⚔️",
    "输入2-5只基金代码，雷达图多维度对比 + AI裁判判定。",
    "**对比维度：** 年化收益/最大回撤/夏普比率/波动率/索提诺/卡尔玛 | 规模/费率/经理年限",
    accent_color="#0891B2")

sidebar_config = render_sidebar_config()
render_top_toolbar()
fetcher = get_fetcher()

with st.expander("⚔️ 基金代码", expanded=True):
    codes_input = st.text_area("每行一个基金代码（2-5只）", "000001\n110011\n005827", height=120)

codes = [c.strip() for c in codes_input.split("\n") if c.strip() and len(c.strip()) == 6]

if len(codes) < 2:
    st.info("👆 请在侧边栏输入至少 2 只基金代码（每行一个）")
    st.stop()

# 获取各基金数据
if st.button("📡 获取对比数据", use_container_width=True, type="primary"):
    funds_data = []
    for code in codes:
        with st.spinner(f"获取 {code}..."):
            nav = fetcher.get_fund_nav_history(code, years=3)
            info = fetcher.get_fund_manager_info(code)
            if nav.empty:
                st.warning(f"{code} 无净值数据，跳过")
                continue
            nav_s = nav.sort_values("日期", ascending=True)["单位净值"].dropna()
            rets = nav_s.pct_change().dropna()
            if len(nav_s) < 60:
                st.warning(f"{code} 数据不足，跳过")
                continue
            funds_data.append({
                "代码": code,
                "名称": info.get("基金名称", code) if info else code,
                "年化收益": calc_annualized_return(nav_s),
                "最大回撤": calc_max_drawdown(nav_s),
                "夏普比率": calc_sharpe_ratio(rets),
                "年化波动": calc_annual_volatility(rets),
                "索提诺": calc_sortino_ratio(rets),
                "卡尔玛": calc_calmar_ratio(nav_s, rets),
                "规模": safe_float(info.get("最新规模","0").replace("亿元","")) if info else 0,
                "管理费率": safe_float(info.get("管理费率%",0)) if info else 0,
                "经理": info.get("基金经理","") if info else "",
                "_nav_s": nav_s,
            })
    st.session_state["pk_funds"] = funds_data
    st.success(f"✅ 加载 {len(funds_data)} 只基金")

if "pk_funds" not in st.session_state or len(st.session_state["pk_funds"]) < 2:
    st.stop()

funds = st.session_state["pk_funds"]

# 指标矩阵
section_header("指标矩阵")
matrix_data = []
for f in funds:
    matrix_data.append({
        "基金": f"{f['名称']}({f['代码']})",
        "年化收益": f"{f['年化收益']*100:.2f}%",
        "最大回撤": f"{f['最大回撤']*100:.2f}%",
        "夏普比率": f"{f['夏普比率']:.2f}",
        "年化波动": f"{f['年化波动']*100:.2f}%",
        "索提诺": f"{f['索提诺']:.2f}",
        "卡尔玛": f"{f['卡尔玛']:.2f}",
        "管理费率": f"{f['管理费率']:.2f}%",
    })
show_sortable_df(pd.DataFrame(matrix_data))

# 雷达图
section_header("雷达图对比")
radar_categories = ["年化收益", "抗回撤(反向)", "夏普比率", "稳定性(反向波动)", "索提诺", "卡尔玛"]
fig = go.Figure()
colors = ["#DC2626","#3B82F6","#16A34A","#F59E0B","#8B5CF6"]
for i, f in enumerate(funds):
    values = [
        min(f["年化收益"]/0.5, 1.0),
        min(abs(1+f["最大回撤"]), 1.0),
        min(f["夏普比率"]/3, 1.0),
        min(abs(1-f["年化波动"]/0.5), 1.0),
        min(f["索提诺"]/3, 1.0),
        min(f["卡尔玛"]/3, 1.0),
    ]
    fig.add_trace(go.Scatterpolar(r=values, theta=radar_categories, fill='toself',
                                  name=f"{f['名称']}({f['代码']})", line_color=colors[i%5]))
fig.update_layout(polar=dict(radialaxis=dict(range=[0,1])), height=450)
st.plotly_chart(fig, use_container_width=True)

# AI 裁判
st.markdown("---")
section_header("AI 裁判")
if not check_api_ready(): st.stop()

if render_analysis_button("🧠 AI裁判判定", key="pk_judge"):
    compare_text = "\n".join(
        f"- {f['名称']}({f['代码']}): 年化{f['年化收益']*100:.1f}%, 回撤{f['最大回撤']*100:.1f}%, "
        f"夏普{f['夏普比率']:.2f}, 波动{f['年化波动']*100:.1f}%, 索提诺{f['索提诺']:.2f}"
        for f in funds
    )
    analyzer = get_analyzer()
    if sidebar_config.get("model"): analyzer._model = sidebar_config["model"]

    result = run_analysis_stream(analyzer,
        system_prompt="""你是基金对比裁判。从多维度判定每只基金的优劣势，给出"XX类型投资者应选A，YY类型投资者应选B"的结论。
严格不输出买入/卖出/推荐交易信号。输出框架为适配度分析。""",
        user_prompt=f"对比以下{len(funds)}只基金，给出各维度的排名和综合评价：\n\n{compare_text}\n\n请输出：1.各维度排名表 2.AI综评 3.不同类型投资者的选择建议",
        max_tokens=4096, temperature=0.3, placeholder_label="📝 裁判结果")
    if result and result.get("success"):
        show_elapsed_time(result.get("elapsed_seconds",0))
        show_token_usage(result.get("usage",{}))
