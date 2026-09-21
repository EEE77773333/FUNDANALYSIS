"""
资产配置框架 — 页面 6（漏斗第一步：定框架）
===========================================
根据投资者财务状况、投资期限和风险承受能力，
AI 生成个性化的"核心-卫星"股债配比战略方案。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from core.config import config
from core.ai_analyzer import get_analyzer
from core.prompt_templates import get_prompt_manager
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    render_analysis_button,
    show_token_usage,
    show_elapsed_time,
    show_error,
    show_info_box,
    show_empty_state,
    check_api_ready, run_analysis_stream,
    section_header,
)

# ---- 页面配置 ----
render_page_header(
    title="资产配置框架",
    icon="🔧",
    accent_color="#10B981",
    description="""
    **漏斗式三步法 · 第一步：定框架**

    输入个人财务状况、投资期限和最大可承受回撤，AI 为您设计个性化的
    "核心-卫星"资产配置方案。这是后续选基的纲领性框架。
    """,
    help_text="""
    **核心-卫星策略：**
    - **核心仓位（~70%）**：配置宽基指数、长期绩优基金等稳定资产
    - **卫星仓位（~30%）**：配置行业/主题/海外等弹性资产

    **配置输出：**
    - 各类资产的目标配置比例
    - 风险预算分配
    - 再平衡规则
    - 实施路径建议
    """,
)

# ---- 侧边栏 ----
sidebar_config = render_sidebar_config()
render_top_toolbar()

with st.expander("📋 快速模板（一键填充投资者画像）", expanded=True):
    preset = st.selectbox(
        "选择预设模板",
        options=[
            "自定义",
            "进取型（年轻人/高收入/高风险承受）",
            "稳健型（中年/中等收入/中等风险承受）",
            "保守型（临近退休/低风险承受）",
        ],
        index=0,
    )

# 根据预设填充默认值
presets = {
    "进取型（年轻人/高收入/高风险承受）": {
        "financial": "可投资资产100万，年收入50万稳定增长，无负债，已有房产",
        "horizon": "10年以上",
        "drawdown": "-25%",
        "goal": "最大化长期资产增值，为提前退休做准备",
        "stage": "30岁，事业上升期，收入增长预期强",
    },
    "稳健型（中年/中等收入/中等风险承受）": {
        "financial": "可投资资产200万，年收入40万，房贷月供1万",
        "horizon": "5-8年",
        "drawdown": "-15%",
        "goal": "资产稳健增值，兼顾子女教育金储备",
        "stage": "42岁，事业稳定期，家庭责任较重",
    },
    "保守型（临近退休/低风险承受）": {
        "financial": "可投资资产500万，退休金+理财收入，无负债",
        "horizon": "3-5年",
        "drawdown": "-8%",
        "goal": "保值为主，追求稳定现金流，补充退休生活",
        "stage": "58岁，即将退休，风险承受能力下降",
    },
}

if preset != "自定义":
    p = presets.get(preset, {})
    st.session_state["preset_financial"] = p.get("financial", "")
    st.session_state["preset_horizon"] = p.get("horizon", "")
    st.session_state["preset_drawdown"] = p.get("drawdown", "")
    st.session_state["preset_goal"] = p.get("goal", "")
    st.session_state["preset_stage"] = p.get("stage", "")

# ---- 主区域 ----
section_header("投资者画像")

col1, col2 = st.columns(2)

with col1:
    financial_situation = st.text_area(
        "财务状况 *",
        value=st.session_state.get("preset_financial", ""),
        height=100,
        placeholder="描述您的：可投资资产规模、年收入及稳定性、负债情况、房产等...",
        help="越详细，AI 给出的配置建议越精准",
    )
    investment_horizon = st.selectbox(
        "投资期限 *",
        options=["1-3年", "3-5年", "5-8年", "10年以上"],
        index=1,
    )

with col2:
    max_drawdown = st.selectbox(
        "最大可承受回撤 *",
        options=["-5%", "-8%", "-10%", "-15%", "-20%", "-25%", "-30%+"],
        index=3,
        help="指您能接受的投资组合最大亏损幅度",
    )
    investment_goal = st.text_area(
        "投资目标",
        value=st.session_state.get("preset_goal", "长期资产增值"),
        height=68,
        placeholder="如：退休储备、子女教育、买房首付、资产增值...",
    )

life_stage = st.text_input(
    "人生阶段",
    value=st.session_state.get("preset_stage", "35-45岁，事业上升期"),
    placeholder="年龄范围 + 人生阶段描述",
)

current_holdings = st.text_area(
    "现有持仓概要（可选）",
    height=80,
    placeholder="如有现有持仓，请简要描述：如\"持有50万沪深300ETF + 30万某主动基金\"。留空表示从零开始。",
)

st.markdown("---")

# AI 分析区
section_header("AI 资产配置方案")

if not check_api_ready():
    st.stop()

filled = bool(financial_situation and max_drawdown)

analyze_clicked = render_analysis_button(
    "🚀 生成资产配置方案",
    disabled=not filled,
    key="btn_allocation_analysis",
)

if analyze_clicked:
    pm = get_prompt_manager()
    template = pm.get("asset_allocation")

    if template is None:
        show_error("提示词模板加载失败")
        st.stop()

    system_prompt, user_prompt = template.render({
        "financial_situation": financial_situation,
        "investment_horizon": investment_horizon,
        "max_drawdown_tolerance": max_drawdown,
        "investment_goal": investment_goal or "长期资产增值",
        "life_stage": life_stage or "未指定",
        "current_holdings": current_holdings or "无现有持仓，从零开始构建组合",
    })

    analyzer = get_analyzer()
    if sidebar_config.get("model"):
        analyzer._model = sidebar_config["model"]

    depth_map = {"简要": 2048, "标准": 4096, "深度": 8192, "极致": 16384}
    max_tokens = depth_map.get(sidebar_config.get("depth", "标准"), 4096)

    section_header("个性化配置方案")

    final_result = run_analysis_stream(
        analyzer, system_prompt, user_prompt,
        max_tokens=max_tokens, temperature=0.3,
        placeholder_label="📋 资产配置方案",
        page_name="资产配置框架",
    )

    if final_result and final_result.get("success"):
        st.success("✅ 资产配置方案已生成")
        show_elapsed_time(final_result.get("elapsed_seconds", 0))
        show_token_usage(final_result.get("usage", {}))

        # 提示下一步
        st.markdown("---")
        show_info_box(
            """
            💡 **下一步建议**

            资产配置框架已确定！现在可以进入**第二步：填标的**：
            1. 如果是权益仓位 → 前往 [主动权益筛选](/04_主动权益筛选) 或 [指数基金筛选](/03_指数基金筛选)
            2. 如果是固收仓位 → 前往 [债券基金筛选](/02_债券基金筛选)
            3. 如果是海外仓位 → 前往 [QDII基金筛选](/05_QDII基金筛选)
            4. 建仓完成后 → 前往 [组合诊断优化](/07_组合诊断优化) 做最终体检
            """
        )

if not analyze_clicked and not filled:
    show_empty_state("请先填写投资者画像（财务状况 + 投资期限 + 最大回撤），再点击生成配置方案")
elif not analyze_clicked:
    show_empty_state("画像已填写，点击 **生成资产配置方案** 获取 AI 个性化方案")
