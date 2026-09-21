"""
宏观行业研判 — 页面 1
=====================
利用 AI 分析当前宏观经济、政策导向及行业景气度，
为后续选基定下大方向。
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
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    render_analysis_button,
    show_token_usage,
    show_elapsed_time,
    show_run_meta,
    show_next_steps,
    show_empty_state,
    show_error,
    check_api_ready, run_analysis_stream,
    section_header,
)

# ---- 页面配置 ----
render_page_header(
    title="宏观行业研判",
    icon="📈",
    accent_color="#0EA5E9",
    description="""
    利用 AI 分析当前宏观经济、政策导向及行业景气度，预判未来3-6个月的板块轮动方向。
    在配置基金之前，建议先完成此步骤以确定大方向。
    """,
    help_text="""
    **使用流程：**
    1. 点击"获取宏观数据"拉取最新指标（CPI/PPI/PMI等）
    2. 可选填写自定义分析要点
    3. 点击"开始 AI 分析"获取深度研判报告

    **输出内容：**
    - 政策面研判
    - 经济周期定位
    - 行业轮动预判（科技/消费/红利/周期）
    - 三种风险偏好的配置方向建议
    """,
)

# ---- 侧边栏 ----
sidebar_config = render_sidebar_config()
render_top_toolbar()

with st.expander("📊 数据范围", expanded=True):
    c1, c2 = st.columns(2)
    with c1:
        include_macro = st.checkbox("获取宏观数据", value=True)
    with c2:
        include_valuation = st.checkbox("获取指数估值", value=True)

# ---- 主区域 ----
fetcher = get_fetcher()

# 数据获取区
section_header("数据获取")

col_data, col_custom = st.columns([1, 1])

with col_data:
    if st.button("📡 获取最新宏观数据", use_container_width=True):
        with st.spinner("正在获取宏观数据..."):
            if include_macro:
                macro = fetcher.get_macro_indicators()
                st.session_state["macro_data"] = macro
            if include_valuation:
                valuations = {}
                for idx in ["沪深300", "中证500", "创业板指"]:
                    val = fetcher.get_index_valuation(idx)
                    if val:
                        valuations[idx] = val
                st.session_state["index_valuations"] = valuations
            st.session_state["data_fetched"] = True

    # 展示已获取的数据
    if st.session_state.get("data_fetched"):
        macro_data = st.session_state.get("macro_data", {})
        if macro_data:
            with st.expander("📊 宏观数据概览", expanded=False):
                st.json(macro_data)

        valuations = st.session_state.get("index_valuations", {})
        if valuations:
            with st.expander("📈 指数估值概览", expanded=False):
                for name, val in valuations.items():
                    st.metric(
                        name,
                        f"PE: {val.get('PE', 'N/A')}",
                        f"分位: {val.get('PE百分位', 'N/A')}%",
                    )

with col_custom:
    custom_focus = st.text_area(
        "🎯 自定义分析要点（可选）",
        placeholder="例如：重点关注新能源产业链的产能出清进度；\n美联储降息节奏对A股成长股的影响；\n...",
        height=120,
        key="custom_focus",
    )

st.markdown("---")

# AI 分析区
section_header("AI 宏观研判")

if not check_api_ready():
    st.stop()

analyze_clicked = render_analysis_button(
    "🚀 开始宏观研判分析",
    disabled=False,
    key="btn_macro_analysis",
)

if analyze_clicked:
    pm = get_prompt_manager()
    template = pm.get("macro_research")

    if template is None:
        show_error("提示词模板加载失败，请检查 prompts/macro_research.yaml")
        st.stop()

    # 准备数据上下文
    macro_context = ""
    if st.session_state.get("data_fetched"):
        macro_data = st.session_state.get("macro_data", {})
        valuations = st.session_state.get("index_valuations", {})
        if macro_data:
            macro_context += f"## 宏观指标数据\n```json\n{macro_data}\n```\n\n"
        if valuations:
            macro_context += f"## 主要指数估值\n```json\n{valuations}\n```\n\n"

    if custom_focus:
        macro_context += f"## 用户特别关注\n{custom_focus}\n\n"

    if not macro_context:
        macro_context = "请联网查询最新宏观数据"

    # 渲染提示词
    system_prompt, user_prompt = template.render(
        {"macro_data": macro_context}
    )

    # 调用 AI 分析
    analyzer = get_analyzer()

    # 根据配置调整模型
    if sidebar_config.get("model"):
        analyzer._model = sidebar_config["model"]

    depth_map = {"简要": 2048, "标准": 4096, "深度": 8192, "极致": 16384}
    max_tokens = depth_map.get(sidebar_config.get("depth", "标准"), 4096)

    final_result = run_analysis_stream(
        analyzer, system_prompt, user_prompt,
        max_tokens=max_tokens, temperature=0.3,
        placeholder_label="📝 宏观研判报告",
        page_name="宏观行业研判",
    )

    # 展示统计信息
    if final_result and final_result.get("success"):
        st.success("✅ 分析完成")
        show_run_meta(final_result.get("elapsed_seconds", 0), final_result.get("usage", {}))
        st.markdown("---")
        show_next_steps([
            ("pages/10_基金排名精选.py", "排名精选", "🏆"),
            ("pages/28_主题资金流雷达.py", "主题资金", "🌊"),
            ("pages/04_主动权益筛选.py", "主动权益", "🎯"),
            ("pages/03_指数基金筛选.py", "指数筛选", "📉"),
            ("pages/06_资产配置框架.py", "资产配置", "🔧"),
        ])
    elif final_result:
        show_error(final_result.get("error", "未知错误"))

# 初始状态提示
if not analyze_clicked and not st.session_state.get("data_fetched"):
    show_empty_state("先点击 **获取最新宏观数据**，再点击 **开始宏观研判分析**")
elif not analyze_clicked and st.session_state.get("data_fetched"):
    show_empty_state("数据已就绪，点击 **开始宏观研判分析** 获取 AI 深度报告")
