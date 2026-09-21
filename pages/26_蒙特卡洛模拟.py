"""
蒙特卡洛模拟 — 页面 26
======================
对投资组合未来N年做M次随机模拟，输出财富分布、成功概率、VaR/CVaR。
支持压力测试（股灾/高通胀/滞胀/失去的十年）。

使用说明:
  1. 从已有组合导入持仓，或手动输入基金代码和权重
  2. 设置模拟参数（年数、次数、每月定投、目标金额）
  3. 查看财富路径 Fan Chart + 终值分布 + 风险指标
  4. 压力测试各极端场景下的组合表现
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

from core.config import config
from core.data_fetcher import get_fetcher
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    show_info_box,
    show_error,
    init_page_state,
    safe_run,
    section_header,
)
from core.portfolio import get_portfolio_manager
from core.monte_carlo import MonteCarloSimulator, SimulationParams

init_page_state({
    "mc_result": None,
    "mc_stress_result": None,
    "mc_fund_codes": [],
})


def format_money(val: float) -> str:
    """格式化金额"""
    if abs(val) >= 1e8:
        return f"{val/1e8:.2f}亿"
    elif abs(val) >= 1e4:
        return f"{val/1e4:.0f}万"
    else:
        return f"{val:,.0f}"


def render_params_form():
    """模拟参数表单"""
    col1, col2 = st.columns(2)
    with col1:
        years = st.slider("模拟年数", 5, 40, 20)
        simulations = st.select_slider("模拟次数", options=[1000, 2000, 5000, 10000], value=5000,
                                       help="次数越多越精确，但计算时间更长")
    with col2:
        initial = st.number_input("初始投入 (元)", 0, 100000000, 100000, step=10000)
        monthly = st.number_input("每月定投 (元)", 0, 1000000, 2000, step=500)

    col3, col4 = st.columns(2)
    with col3:
        target = st.number_input("目标金额 (元)", 100000, 500000000, 1000000, step=100000)
    with col4:
        inflation = st.slider("年化通胀率 (%)", 0.0, 10.0, 2.5, step=0.5) / 100

    rebalance = st.selectbox("再平衡策略", ["none", "annual"], index=1,
                             format_func=lambda x: "无" if x == "none" else "每年再平衡")

    return SimulationParams(
        years=years, simulations=simulations,
        initial_value=initial, monthly_contribution=monthly,
        target_value=target, inflation_rate=inflation,
        rebalance=rebalance,
    )


def render_fan_chart(result):
    """Fan Chart 财富路径"""
    params = result.params
    percentiles = result.percentiles
    years_range = list(range(params.years + 1))

    fig = go.Figure()

    # 填充区间
    fig.add_trace(go.Scatter(
        x=years_range + years_range[::-1],
        y=percentiles["p10"] + percentiles["p90"][::-1],
        fill="toself", fillcolor="rgba(59,130,246,0.15)",
        line=dict(color="rgba(255,255,255,0)"), name="10%-90%",
    ))
    fig.add_trace(go.Scatter(
        x=years_range + years_range[::-1],
        y=percentiles["p25"] + percentiles["p75"][::-1],
        fill="toself", fillcolor="rgba(59,130,246,0.25)",
        line=dict(color="rgba(255,255,255,0)"), name="25%-75%",
    ))

    # 中位数线
    fig.add_trace(go.Scatter(
        x=years_range, y=percentiles["p50"],
        mode="lines", name="中位数", line=dict(color="#1D4ED8", width=3),
    ))

    # 目标线
    fig.add_hline(y=params.target_value, line_dash="dash", line_color="#EF4444",
                  annotation_text=f"目标: {format_money(params.target_value)}")

    fig.update_layout(
        height=400,
        xaxis_title="年数", yaxis_title="组合价值 (元)",
        margin=dict(l=10, r=10, t=10, b=10),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # 各分位终点值
    st.caption("📊 各分位终值:")
    cols = st.columns(5)
    for i, (p, label) in enumerate([("p10", "P10 悲观"), ("p25", "P25"), ("p50", "P50 中位"),
                                      ("p75", "P75"), ("p90", "P90 乐观")]):
        cols[i].metric(label, format_money(percentiles[p][-1]))


def render_terminal_dashboard(result):
    """终值分布 + 风险指标"""
    params = result.params

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("中位数终值", format_money(result.median_terminal))
    col2.metric("均值终值", format_money(result.mean_terminal))
    col3.metric("达成概率", f"{result.success_probability*100:.0f}%",
                delta="✅ 大概率达成" if result.success_probability > 0.7 else "⚠️ 需要调整")
    col4.metric("VaR (95%)", format_money(abs(result.var_95)),
                help="95%置信度下最差损失")
    col5.metric("破产概率", f"{result.bankruptcy_prob*100:.1f}%",
                delta_color="inverse")

    if result.years_to_target_median:
        st.info(f"🎯 中位数估计: **{result.years_to_target_median} 年** 后达到目标金额 {format_money(params.target_value)}")

    # 终值分布直方图
    section_header("终值分布")
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=result.final_values,
        nbinsx=80,
        marker_color="#3B82F6",
        opacity=0.7,
        name="模拟终值",
    ))
    # 中位数线
    fig.add_vline(x=result.median_terminal, line_dash="dash", line_color="#1D4ED8",
                  annotation_text="中位数")
    # 目标线
    fig.add_vline(x=params.target_value, line_dash="dash", line_color="#EF4444",
                  annotation_text="目标")
    # VaR线
    fig.add_vline(x=result.var_95 + params.initial_value, line_dash="dot", line_color="#F59E0B",
                  annotation_text="VaR95")

    fig.update_layout(
        height=350,
        xaxis_title="终值 (元)", yaxis_title="频次",
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    # 逐年统计表
    section_header("逐年财富分位表")
    percentiles = result.percentiles
    years_range = list(range(0, params.years + 1, max(1, params.years // 10)))
    table_data = []
    for y in years_range:
        table_data.append({
            "年": y,
            "P10": format_money(percentiles["p10"][y]),
            "P25": format_money(percentiles["p25"][y]),
            "P50": format_money(percentiles["p50"][y]),
            "P75": format_money(percentiles["p75"][y]),
            "P90": format_money(percentiles["p90"][y]),
        })
    st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)


def render_stress_test(stress_result):
    """压力测试结果对比"""
    if not stress_result:
        return

    section_header("压力测试 — 各场景对比")

    # 对比卡片
    scenarios = []
    for name, result in stress_result.items():
        scenarios.append({
            "场景": {
                "baseline": "📊 基准", "crash": "💥 股灾(-40%)",
                "inflation": "📈 高通胀(6%)", "stagflation": "🌪️ 滞胀",
                "lost_decade": "🐌 失去的十年",
            }.get(name, name),
            "中位数终值": format_money(result.median_terminal),
            "达成概率": f"{result.success_probability*100:.0f}%",
            "VaR(95%)": format_money(abs(result.var_95)),
            "破产概率": f"{result.bankruptcy_prob*100:.1f}%",
        })

    st.dataframe(pd.DataFrame(scenarios), use_container_width=True, hide_index=True)

    # 财富路径对比图
    section_header("各场景中位数财富路径对比")
    fig = go.Figure()
    colors = {"baseline": "#3B82F6", "crash": "#EF4444", "inflation": "#F59E0B",
              "stagflation": "#8B5CF6", "lost_decade": "#6B7280"}
    labels = {"baseline": "基准", "crash": "股灾", "inflation": "高通胀",
              "stagflation": "滞胀", "lost_decade": "失去的十年"}

    for name, result in stress_result.items():
        years = list(range(result.params.years + 1))
        fig.add_trace(go.Scatter(
            x=years, y=result.percentiles["p50"],
            mode="lines", name=labels.get(name, name),
            line=dict(color=colors.get(name, "#9CA3AF"), width=2),
        ))

    fig.update_layout(
        height=400,
        xaxis_title="年数", yaxis_title="组合价值 (元)",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # 终值分布对比（箱线图）
    section_header("各场景终值分布")
    box_data = []
    for name, result in stress_result.items():
        for val in np.random.choice(result.final_values, size=min(1000, len(result.final_values)), replace=False):
            box_data.append({"场景": labels.get(name, name), "终值": val})

    if box_data:
        df_box = pd.DataFrame(box_data)
        fig_box = px.box(df_box, x="场景", y="终值", color="场景",
                         color_discrete_map=colors)
        fig_box.update_layout(height=400, showlegend=False, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_box, use_container_width=True)


def main():
    render_page_header(
        title="蒙特卡洛模拟",
        icon="🎲",
        description="对投资组合未来N年做M次随机模拟，输出财富分布、成功概率、VaR/CVaR，含压力测试",
        help_text="使用说明：1. 从已有组合导入持仓 2. 设置参数 3. 查看财富路径/终值分布 4. 压力测试极端场景",
        accent_color="#6366F1",
    )

    sidebar_config = render_sidebar_config()
    render_top_toolbar()

    # ---- 选择数据来源 ----
    section_header("选择组合数据")

    col1, col2 = st.columns(2)

    with col1:
        pm = get_portfolio_manager()
        portfolios = pm.list_all()
        sel_portfolio = st.selectbox(
            "从已有组合导入",
            ["手动输入"] + [p.name for p in portfolios],
            key="mc_portfolio_sel",
        )

    fund_codes = []
    fund_weights = {}

    if sel_portfolio != "手动输入":
        p = next((p for p in portfolios if p.name == sel_portfolio), None)
        if p:
            p.load_holdings()
            st.caption(f"✅ 已加载「{p.name}」({p.holding_count} 只基金)")
            for h in p.holdings:
                fund_codes.append(h["fund_code"])
                fund_weights[h["fund_code"]] = h.get("weight", 1.0 / p.holding_count)

    with col2:
        manual_codes = st.text_area(
            "或手动输入基金代码+权重",
            placeholder="000001,0.4\n110011,0.3\n005827,0.3",
            help="每行：基金代码,权重（逗号分隔，权重总和应为1.0）",
        )
        if manual_codes.strip() and sel_portfolio == "手动输入":
            for line in manual_codes.strip().split("\n"):
                parts = [x.strip() for x in line.split(",")]
                if len(parts) >= 2:
                    code = parts[0]
                    wt = float(parts[1])
                    fund_codes.append(code)
                    fund_weights[code] = wt
                elif len(parts) == 1 and parts[0]:
                    fund_codes.append(parts[0])

    if not fund_codes:
        st.info("👆 请选择已有组合或手动输入基金代码")
        return

    # 归一化权重
    tw = sum(fund_weights.values())
    if tw > 0:
        fund_weights = {c: w / tw for c, w in fund_weights.items()}
    else:
        fund_weights = {c: 1.0 / len(fund_codes) for c in fund_codes}

    st.caption(f"📊 将使用 {len(fund_codes)} 只基金进行模拟")

    st.divider()

    # ---- 参数设置 ----
    section_header("模拟参数")
    params = render_params_form()

    # ---- 运行模拟 ----
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 运行模拟", use_container_width=True, type="primary"):
            with st.spinner(f"正在拉取 {len(fund_codes)} 只基金的历史净值 + {params.simulations} 次模拟..."):
                try:
                    fetcher = get_fetcher()
                    return_data = {}
                    name_map = {}
                    for code in fund_codes:
                        nav = fetcher.get_fund_nav_history(code, years=params.years)
                        if nav is not None and not nav.empty:
                            nav = nav.sort_values("日期")
                            nav["ret"] = nav["单位净值"].pct_change()
                            rets = nav.set_index("日期")["ret"].dropna()
                            if len(rets) > 60:
                                return_data[code] = rets
                                info = fetcher.get_fund_manager_info(code)
                                name_map[code] = info.get("基金名称", code) if info else code

                    if len(return_data) < 1:
                        st.error("至少需要1只有净值数据的基金")
                    else:
                        returns_df = pd.DataFrame(return_data).dropna()
                        if len(returns_df) < 30:
                            st.error(f"重叠交易日不足（仅{len(returns_df)}天），需要≥30天")
                        else:
                            # 调整权重只保留有数据的基金
                            valid_codes = list(returns_df.columns)
                            valid_weights = {c: fund_weights.get(c, 1.0 / len(valid_codes)) for c in valid_codes}
                            tw2 = sum(valid_weights.values())
                            valid_weights = {c: w / tw2 for c, w in valid_weights.items()}

                            sim = MonteCarloSimulator(returns_df, valid_weights)
                            result = sim.run(params)
                            st.session_state["mc_result"] = result
                            st.session_state["mc_stress_result"] = None
                            st.session_state["mc_fund_codes"] = valid_codes
                            st.success(f"✅ 模拟完成 ({params.simulations} 次 × {params.years} 年)")
                except Exception as e:
                    st.error(f"模拟失败: {str(e)[:200]}")

    with col2:
        if st.button("🌪️ 含压力测试运行", use_container_width=True):
            with st.spinner(f"正在执行基准+4种极端场景模拟 ({params.simulations}次×5) ..."):
                try:
                    fetcher = get_fetcher()
                    return_data = {}
                    for code in fund_codes:
                        nav = fetcher.get_fund_nav_history(code, years=params.years)
                        if nav is not None and not nav.empty:
                            nav = nav.sort_values("日期")
                            nav["ret"] = nav["单位净值"].pct_change()
                            rets = nav.set_index("日期")["ret"].dropna()
                            if len(rets) > 60:
                                return_data[code] = rets

                    if len(return_data) >= 1:
                        returns_df = pd.DataFrame(return_data).dropna()
                        if len(returns_df) >= 30:
                            valid_codes = list(returns_df.columns)
                            valid_weights = {c: fund_weights.get(c, 1.0 / len(valid_codes)) for c in valid_codes}
                            tw2 = sum(valid_weights.values())
                            valid_weights = {c: w / tw2 for c, w in valid_weights.items()}

                            sim = MonteCarloSimulator(returns_df, valid_weights)
                            stress = sim.run_with_stress(params)
                            st.session_state["mc_stress_result"] = stress
                            st.session_state["mc_result"] = stress.get("baseline")
                            st.session_state["mc_fund_codes"] = valid_codes
                            st.success("✅ 压力测试完成")
                except Exception as e:
                    st.error(f"压力测试失败: {str(e)[:200]}")

    # ---- 结果展示 ----
    result = st.session_state.get("mc_result")
    stress = st.session_state.get("mc_stress_result")

    if result:
        st.divider()

        tab1, tab2, tab3 = st.tabs([
            "📈 财富路径",
            "📊 终值分析",
            "🌪️ 压力测试",
        ])

        with tab1:
            section_header("Fan Chart — 财富模拟路径")
            st.caption(
                f"初始: {format_money(result.params.initial_value)} | "
                f"月投: {format_money(result.params.monthly_contribution)} | "
                f"通胀: {result.params.inflation_rate*100:.1f}% | "
                f"再平衡: {'每年' if result.params.rebalance != 'none' else '无'}"
            )
            render_fan_chart(result)

        with tab2:
            render_terminal_dashboard(result)

        with tab3:
            if stress:
                render_stress_test(stress)
            else:
                st.info("👆 请点击「含压力测试运行」以查看多场景对比")
                st.markdown("""
                #### 压力测试场景说明

                | 场景 | 描述 |
                |------|------|
                | 💥 股灾 | 第3年市场暴跌 -40% |
                | 📈 高通胀 | 年化通胀率升至 6%（侵蚀购买力） |
                | 🌪️ 滞胀 | 股灾 + 高通胀叠加 |
                | 🐌 失去的十年 | 前5年年化收益减半 |
                """)


if __name__ == "__main__":
    main()
