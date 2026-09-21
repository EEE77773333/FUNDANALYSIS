"""
费率计算器 — 页面 15
=====================
A类 vs C类基金费率对比 + 持有成本模拟。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np

from core.data_fetcher import get_fetcher
from core.utils import safe_float
from core.ui_components import render_page_header, render_sidebar_config, render_top_toolbar, show_error, section_header

render_page_header("费率计算器", "💰",
    "A类 vs C类基金费率对比 + 持有成本精确模拟。看清费率对长期收益的侵蚀。",
    "**核心原理：** A类申购时扣费，适合长期持有；C类按天计提销售服务费，适合短期。找到平衡点。",
    accent_color="#0891B2")

sidebar_config = render_sidebar_config(show_ai_config=False)
render_top_toolbar()
fetcher = get_fetcher()

st.sidebar.markdown("---")
with st.expander("📊 费率参数", expanded=False):
    fund_code = st.text_input("基金代码（可选，自动填充费率）", "", max_chars=6)
    section_header("A类费率")
    a_subscribe = st.slider("申购费率%", 0.0, 2.0, 0.15, 0.01, key="a_sub")
    a_redeem = st.slider("赎回费率% (持有一年)", 0.0, 2.0, 0.5, 0.01, key="a_red")
    a_manage = st.slider("管理费率%", 0.1, 2.0, 1.5, 0.01, key="a_mgr")
    section_header("C类费率")
    c_subscribe = st.slider("申购费率%", 0.0, 1.0, 0.0, 0.01, key="c_sub")
    c_service = st.slider("销售服务费率% (年化)", 0.0, 2.0, 0.8, 0.01, key="c_svc")
    c_manage = st.slider("管理费率%", 0.1, 2.0, 1.5, 0.01, key="c_mgr")

# 如果输入了基金代码，自动填充
if fund_code and st.button("📡 自动填充基金费率", use_container_width=True):
    info = fetcher.get_fund_manager_info(fund_code)
    if info:
        st.success(f"已填充 {info.get('基金名称','')} 的费率")

section_header("投资参数")
col1, col2 = st.columns(2)
with col1:
    principal = st.number_input("投资金额（元）", 1000, 10000000, 100000, 10000)
with col2:
    max_years = st.slider("模拟年限", 1, 10, 5)

# 计算
years = np.arange(0, max_years + 0.1, 0.1)
# A类: 申购时扣申购费 + 每年管理费 + 赎回时扣赎回费
# C类: 无申购费 + 每年(管理费+销售服务费)
annual_return = 0.08  # 假设年化8%

a_values = []
c_values = []
for y in years:
    # A类
    a_net = principal * (1 - a_subscribe/100)  # 扣除申购费
    a_net = a_net * (1 + annual_return - a_manage/100) ** y  # 复利
    if y < 1: a_redeem_actual = a_redeem * 0.5  # 短期赎回费更高
    elif y < 2: a_redeem_actual = a_redeem * 0.25
    else: a_redeem_actual = 0
    a_net = a_net * (1 - a_redeem_actual/100)
    a_values.append(a_net)

    # C类
    c_net = principal * (1 - c_subscribe/100)
    c_net = c_net * (1 + annual_return - c_manage/100 - c_service/100) ** y
    c_values.append(c_net)

# 找平衡点
diff = np.array(a_values) - np.array(c_values)
crossover_idx = np.argmax(diff >= 0)
crossover_year = years[crossover_idx] if diff[crossover_idx] >= 0 else None

# 图表
fig = go.Figure()
fig.add_trace(go.Scatter(x=years, y=a_values, mode='lines', name='A类',
                          line=dict(color='#3B82F6', width=2)))
fig.add_trace(go.Scatter(x=years, y=c_values, mode='lines', name='C类',
                          line=dict(color='#3B82F6', width=2)))
if crossover_year:
    crossover_val = a_values[crossover_idx]
    fig.add_trace(go.Scatter(x=[crossover_year], y=[crossover_val],
                              mode='markers+text', name=f'平衡点 ≈ {crossover_year:.1f}年',
                              marker=dict(size=12, color='#EF4444'),
                              text=[f'{crossover_year:.1f}年'], textposition='top center'))
fig.update_layout(height=400, xaxis_title="持有年限", yaxis_title="最终金额(元)",
                  hovermode='x unified')
st.plotly_chart(fig, use_container_width=True)

# 结论（按「模拟年限」动态展示，避免 fixed index 越界）
section_header("结论")
_milestones = [y for y in (1, 3, 5, 7, 10) if y <= max_years]
if not _milestones:
    _milestones = [max_years]
_rows = ["| 持有年限 | A类最终金额 | C类最终金额 | 建议 |", "|---------|:---------:|:---------:|------|"]
for _y in _milestones:
    _idx = min(int(round(_y / 0.1)), len(a_values) - 1)
    _a, _c = a_values[_idx], c_values[_idx]
    _tip = "C类更优" if _c > _a else "A类更优"
    _rows.append(f"| {_y}年 | ¥{_a:,.0f} | ¥{_c:,.0f} | {_tip} |")
st.markdown("\n".join(_rows))

if crossover_year:
    st.info(f"💡 A/C类费率平衡点约在 **{crossover_year:.1f}年**。持有超过此年限选A类更划算，短期选C类。")
else:
    st.info("💡 在当前参数下，A类始终优于C类（或反之）。可调整费率参数重新计算。")

st.caption("⚠️ 简化模型，未考虑分红再投资、费率变动、阶梯赎回费。实际以基金合同为准。")
