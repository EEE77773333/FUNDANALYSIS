"""
定投回测模拟器 — 页面 16
========================
定投 vs 一次性投入回测对比。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from datetime import datetime

from core.data_fetcher import get_fetcher
from core.utils import safe_float, calc_annualized_return, calc_max_drawdown
from core.ui_components import render_page_header, render_sidebar_config, render_top_toolbar, show_error, section_header

render_page_header("定投回测模拟器", "📆",
    "模拟定期定额投资 vs 一次性投入的历史收益对比。",
    "**支持：** 日/周/月定投 | 任意起止日期 | 定投vs一次性对比 | 最佳止盈点分析",
    accent_color="#0891B2")

sidebar_config = render_sidebar_config(show_ai_config=False)
render_top_toolbar()
fetcher = get_fetcher()

section_header("回测参数")
p1, p2, p3 = st.columns(3)
with p1:
    fund_code = st.text_input("基金代码", "000001", max_chars=6)
with p2:
    invest_period = st.selectbox("定投频率", ["每周", "每两周", "每月"], index=0)
with p3:
    amount_per = st.number_input("每次投入金额（元）", 100, 100000, 1000, 100)

# 定投 vs 一次性计算
if fund_code and st.button("📡 获取净值并回测", use_container_width=True, type="primary"):
    nav = fetcher.get_fund_nav_history(fund_code, years=5)
    if nav.empty:
        show_error("未获取到净值数据")
        st.stop()

    nav_sorted = nav.sort_values("日期", ascending=True)
    nav_sorted["日期"] = pd.to_datetime(nav_sorted["日期"])
    nav_series = nav_sorted.set_index("日期")["单位净值"].dropna()

    if len(nav_series) < 100:
        show_error(f"数据不足（仅{len(nav_series)}个交易日）")
        st.stop()

    # 定投模拟
    freq_map = {"每周": "W", "每两周": "2W", "每月": "ME"}
    invest_dates = pd.date_range(nav_series.index[0], nav_series.index[-1], freq=freq_map[invest_period])
    invest_dates = [d for d in invest_dates if d in nav_series.index or d >= nav_series.index[0]]
    # 取最近交易日
    aligned_dates = []
    for d in invest_dates:
        nearby = nav_series.index[nav_series.index <= d]
        if len(nearby) > 0:
            aligned_dates.append(nearby[-1])
    aligned_dates = sorted(set(aligned_dates))

    dca_units = 0
    dca_invested = 0
    dca_values = []
    lump_units = 0
    lump_invested = amount_per * len(aligned_dates)
    all_dates = nav_series.index.tolist()

    # 一次性投入：在第一天全部买入
    lump_units = lump_invested / nav_series.iloc[0]

    for i, date in enumerate(all_dates):
        nav_val = nav_series.loc[date]
        # 定投
        if date in aligned_dates:
            units_bought = amount_per / nav_val
            dca_units += units_bought
            dca_invested += amount_per
        dca_values.append({"日期": date, "定投市值": dca_units * nav_val,
                           "一次性市值": lump_units * nav_val,
                           "定投投入": dca_invested, "一次性投入": lump_invested})

    df_backtest = pd.DataFrame(dca_values)

    # 图表
    section_header("定投 vs 一次性投入")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_backtest["日期"], y=df_backtest["定投市值"],
                              mode='lines', name='定投市值', line=dict(color='#3B82F6', width=2)))
    fig.add_trace(go.Scatter(x=df_backtest["日期"], y=df_backtest["一次性市值"],
                              mode='lines', name='一次性投入市值', line=dict(color='#3B82F6', width=2)))
    fig.add_trace(go.Scatter(x=df_backtest["日期"], y=df_backtest["定投投入"],
                              mode='lines', name='累计投入(定投)', line=dict(color='#94A3B8', width=1, dash='dash')))
    fig.update_layout(height=400, hovermode='x unified')
    st.plotly_chart(fig, use_container_width=True)

    # 统计指标
    dca_final = df_backtest["定投市值"].iloc[-1]
    lump_final = df_backtest["一次性市值"].iloc[-1]
    dca_return = (dca_final - dca_invested) / dca_invested * 100
    lump_return = (lump_final - lump_invested) / lump_invested * 100

    # 定投年化
    dca_nav = pd.Series([dca_final / dca_invested], dtype=float)
    # 简化：用终值/投入计算
    years = len(aligned_dates) / (12 if invest_period == "每月" else 52 if invest_period == "每周" else 26)
    dca_annual = ((dca_final / dca_invested) ** (1 / max(years, 0.5)) - 1) * 100

    section_header("回测统计")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("定投终值", f"¥{dca_final:,.0f}", f"{dca_return:+.1f}%")
    c2.metric("一次性终值", f"¥{lump_final:,.0f}", f"{lump_return:+.1f}%")
    c3.metric("定投总投入", f"¥{dca_invested:,.0f}")
    c4.metric("定投期数", f"{len(aligned_dates)}期")

    st.caption(f"回测区间: {nav_series.index[0].strftime('%Y-%m-%d')} → {nav_series.index[-1].strftime('%Y-%m-%d')}")

    # 最大回撤对比
    dca_series = df_backtest.set_index("日期")["定投市值"]
    lump_series = df_backtest.set_index("日期")["一次性市值"]
    dca_dd = calc_max_drawdown(dca_series)
    lump_dd = calc_max_drawdown(lump_series)

    st.markdown(f"""
    | 指标 | 定投 | 一次性投入 |
    |------|:--:|:--:|
    | 终值 | ¥{dca_final:,.0f} | ¥{lump_final:,.0f} |
    | 总收益 | {dca_return:+.1f}% | {lump_return:+.1f}% |
    | 最大回撤 | {dca_dd*100:.1f}% | {lump_dd*100:.1f}% |
    """)
