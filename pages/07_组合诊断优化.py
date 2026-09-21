"""
组合诊断优化 — 页面 7（漏斗第三步：做体检）
===========================================
对现有基金持仓进行多维度诊断，发现行业过度集中、风格漂移、
费率过高等问题，并给出优化调仓建议。
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
    show_dataframe, show_empty_state,
    check_api_ready, safe_run, run_analysis_stream,
    section_header,
)

fetcher = get_fetcher()
analyzer = get_analyzer()
pm = get_prompt_manager()

# ---- 页面配置 ----
render_page_header(
    title="组合诊断优化",
    icon="🩺",
    accent_color="#10B981",
    description="""
    **漏斗式三步法 · 第三步：做体检**

    对现有基金持仓进行全面的多维度诊断——行业集中度、风格漂移、
    费率效率、相关性风险——并给出具体的优化调仓方案。
    """,
    help_text="""
    **诊断维度：**
    1. **结构分析**：股债配比偏差、行业集中度、风格暴露
    2. **质量审查**：业绩归因（Alpha/Beta）、风格漂移、经理变更
    3. **成本效率**：综合费率、隐性成本、可替代性
    4. **风险诊断**：回撤来源、相关性矩阵、流动性风险

    **输出：**
    - 各维度 ✅/⚠️/❌ 健康状态
    - TOP 3 优先解决问题
    - 具体调仓方案（减仓/加仓/替换）
    - 优化后的目标组合表
    """,
)

# ---- 侧边栏 ----
sidebar_config = render_sidebar_config()
render_top_toolbar()

with st.expander("📋 快速操作", expanded=True):
    st.markdown("""
    **两种输入方式：**
    1. 手动输入持仓信息
    2. 粘贴基金代码列表自动获取数据
    """)
    auto_fetch = st.checkbox(
        "🔍 自动获取基金数据",
    value=True,
    help="输入基金代码后自动从天天基金获取净值、持仓、费率等数据",
)

# ---- 主区域 ----

section_header("持仓信息输入")

tab1, tab2 = st.tabs(["📝 手动输入", "🔢 代码批量导入"])

with tab1:
    portfolio_text = st.text_area(
        "请输入当前基金持仓明细",
        height=200,
        placeholder=(
            "请描述每只基金的持仓情况，格式示例：\n\n"
            "1. 基金代码: 000001 | 名称: 华夏成长 | 持仓金额: 15万 | 占比: 20% | 买入时间: 2023-01\n"
            "2. 基金代码: 110011 | 名称: 易方达优质精选 | 持仓金额: 20万 | 占比: 27% | 买入时间: 2022-06\n"
            "3. 基金代码: 510300 | 名称: 华泰柏瑞沪深300ETF | 持仓金额: 10万 | 占比: 13% | 买入时间: 2023-03\n"
            "...\n\n"
            "也可以自由描述：\"持有5只基金，总市值75万：华夏成长15万、沪深300ETF 10万...\""
        ),
    )

with tab2:
    fund_codes = st.text_area(
        "输入基金代码（每行一个）",
        height=120,
        placeholder="000001\n110011\n510300\n...",
        help="输入代码后点击下方按钮自动获取基金信息",
    )

    if fund_codes.strip() and auto_fetch:
        if st.button("🔍 自动获取基金信息", use_container_width=True):
            codes = [
                c.strip()
                for c in fund_codes.split("\n")
                if c.strip() and len(c.strip()) == 6
            ]
            if codes:
                with st.spinner(f"正在获取 {len(codes)} 只基金的信息..."):
                    portfolio_parts = []
                    for i, code in enumerate(codes):
                        info = fetcher.get_fund_manager_info(code)
                        nav = fetcher.get_fund_nav_history(code, years=1)
                        estimate = fetcher.get_realtime_estimate(code)

                        name = (
                            info.get("基金名称", "")
                            if info
                            else f"基金{code}"
                        )
                        latest_nav = (
                            nav["单位净值"].iloc[0]
                            if not nav.empty and "单位净值" in nav.columns
                            else "?"
                        )

                        portfolio_parts.append(
                            f"{i+1}. 基金代码: {code} | 名称: {name} | "
                            f"最新净值: {latest_nav} | "
                            f"类型: {info.get('基金类型', '未知') if info else '未知'} | "
                            f"经理: {info.get('基金经理', '未知') if info else '未知'}"
                        )

                    portfolio_text = "\n".join(portfolio_parts)
                    st.session_state["auto_portfolio"] = portfolio_text
                    st.success(f"✅ 已获取 {len(codes)} 只基金的基本信息")

    if st.session_state.get("auto_portfolio"):
        portfolio_text = st.session_state["auto_portfolio"]
        st.text_area(
            "自动获取的持仓信息（可编辑）",
            value=portfolio_text,
            height=200,
        )

st.markdown("---")

# 额外的诊断偏好
section_header("诊断偏好（可选）")
col1, col2, col3 = st.columns(3)

with col1:
    check_concentration = st.checkbox("行业集中度分析", value=True)
    check_fee = st.checkbox("费率效率分析", value=True)
with col2:
    check_style = st.checkbox("风格漂移检测", value=True)
    check_correlation = st.checkbox("相关性分析", value=True)
with col3:
    check_manager = st.checkbox("经理变更风险", value=True)
    check_alternative = st.checkbox("可替代性分析", value=True)

extra_requirements = []
if not check_concentration:
    extra_requirements.append("跳过行业集中度分析")
if not check_style:
    extra_requirements.append("跳过风格漂移检测")

st.markdown("---")

# AI 分析区
section_header("AI 组合诊断分析")

if not check_api_ready():
    st.stop()

# 确定实际使用的持仓文本
final_portfolio = portfolio_text if portfolio_text else ""

analyze_clicked = render_analysis_button(
    "🚀 开始组合诊断",
    disabled=not final_portfolio,
    key="btn_diagnosis_analysis",
)

if analyze_clicked:
    template = pm.get("portfolio_diagnosis")

    if template is None:
        show_error("提示词模板加载失败")
        st.stop()

    # 附加额外要求
    portfolio_with_extras = final_portfolio
    if extra_requirements:
        portfolio_with_extras += (
            "\n\n## 用户额外要求\n" + "\n".join(extra_requirements)
        )

    system_prompt, user_prompt = template.render({
        "portfolio_data": portfolio_with_extras,
    })

    if sidebar_config.get("model"):
        analyzer._model = sidebar_config["model"]

    # 组合诊断通常需要更详细的分析
    depth_map = {"简要": 4096, "标准": 8192, "深度": 12288, "极致": 16384}
    max_tokens = depth_map.get(sidebar_config.get("depth", "标准"), 8192)

    final_result = run_analysis_stream(
        analyzer, system_prompt, user_prompt,
        max_tokens=max_tokens, temperature=0.2,
        placeholder_label="📋 诊断报告"
    )

    if final_result and final_result.get("success"):
        st.success("✅ 组合诊断完成")
        st.markdown("---")
        col1, col2 = st.columns([1, 1])
        with col1:
            show_elapsed_time(final_result.get("elapsed_seconds", 0))
        with col2:
            show_token_usage(final_result.get("usage", {}))

        # 后续建议
        st.markdown("---")
        show_info_box(
            """
            💡 **诊断后的行动建议**

            1. 优先处理报告中标注为 ❌ 的紧急问题
            2. 调仓时注意申赎费用和持有时间（避免短期频繁交易）
            3. 建议每季度/半年进行一次组合再体检
            4. 调仓完成后可再次运行此诊断验证改善效果
            """
        )

if not analyze_clicked and not final_portfolio:
    show_empty_state("请在上方输入您的基金持仓信息，然后点击 **开始组合诊断**")
elif not analyze_clicked:
    show_empty_state("持仓信息已就绪，点击 **开始组合诊断** 获取 AI 深度诊断报告")
