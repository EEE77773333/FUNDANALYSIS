"""
策略引擎 - 页面 23
================
基于YAML策略模板的规则化基金筛选引擎。
加载预置或自定义策略，结合市场阶段判断，驱动AI执行策略化筛选。

使用说明:
  1. 选择策略：从下拉菜单选择预置策略或自定义策略
  2. 市场阶段（可选）：检测当前市场阶段，自动匹配策略
  3. 执行筛选：选择基金类型，驱动AI按策略规则筛选
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import json

from core.config import config
from core.data_fetcher import get_fetcher
from core.ai_analyzer import get_analyzer
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    show_info_box,
    show_error,
    show_token_usage,
    show_elapsed_time,
    render_analysis_button,
    run_analysis_stream,
    init_page_state,
    check_api_ready,
    safe_run,
    section_header,
)
from core.strategy_engine import (
    get_strategy_loader,
    StrategyExecutor,
)
from core.market_phase import get_phase_detector


# ============================================================
# Page Config
# ============================================================
init_page_state({
    "strategy_result": None,
    "strategy_market_phase": None,
})


# ============================================================
# Helpers
# ============================================================

def render_strategy_selector():
    """策略选择器"""
    loader = get_strategy_loader()
    strategies = loader.list_all()

    if not strategies:
        st.info("📭 暂无可用策略")
        return None

    # 按类别分组
    categories = {}
    for s in strategies:
        cat = s.category_label
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(s)

    section_header("选择策略")

    sel_cat = st.selectbox(
        "策略类别",
        list(categories.keys()),
        key="strategy_cat",
    )

    cat_strategies = categories.get(sel_cat, [])
    sel = st.selectbox(
        "策略",
        cat_strategies,
        format_func=lambda s: f"{s.display_name} — {s.description[:40]}",
        key="strategy_sel",
    )

    if sel:
        # 策略详情
        with st.expander(f"📖 {sel.display_name} — 策略详情", expanded=True):
            st.markdown(f"**类别**: {sel.category_label}")
            st.markdown(f"**描述**: {sel.description}")
            st.markdown(f"**适用市场阶段**: {', '.join(sel.market_regimes) if sel.market_regimes else '通用'}")
            st.markdown(f"**来源**: {'系统预置' if sel.source == 'system' else '用户自定义'}")
            st.markdown("---")
            st.markdown(sel.instructions)

    return sel


def render_market_phase_section():
    """市场阶段检测区域"""
    section_header("市场阶段检测（可选）")

    if st.button("🔍 检测当前市场阶段", key="detect_phase"):
        with st.spinner("正在分析沪深300指数..."):
            pd_obj = get_phase_detector()
            phase = pd_obj.detect("沪深300")
            st.session_state["strategy_market_phase"] = phase

    phase = st.session_state.get("strategy_market_phase")
    if phase:
        formatted = get_phase_detector().format_for_llm(phase)
        st.markdown(formatted)

        # 推荐策略
        rec_strategies = get_phase_detector().get_recommended_strategies(phase)
        if rec_strategies:
            st.caption(f"💡 当前阶段推荐策略: {', '.join(rec_strategies)}")


def render_strategy_editor():
    """自定义策略编辑器"""
    section_header("自定义策略编辑器")
    st.caption("创建你的专属筛选策略，保存后将出现在策略列表中")

    with st.form("custom_strategy_form"):
        name = st.text_input("策略标识（英文）", placeholder="my_custom_strategy")
        display_name = st.text_input("策略名称（中文）", placeholder="我的自定义策略")
        description = st.text_input("策略描述", placeholder="一句话描述...")
        category = st.selectbox(
            "类别",
            ["active_equity", "fixed_income", "asset_allocation", "index", "general"],
            format_func=lambda c: {
                "active_equity": "🔴 主动权益",
                "fixed_income": "🔵 固收",
                "asset_allocation": "🟡 资产配置",
                "index": "🟢 指数",
                "general": "⚪ 通用",
            }.get(c, c),
        )
        market_regimes_str = st.text_input("适用市场阶段（逗号分隔）", "bull,sideways")
        instructions = st.text_area(
            "策略规则（Markdown格式）",
            placeholder="## 策略规则\n\n### 1. 基金筛选\n- ...\n\n### 2. 评分权重\n- ...",
            height=300,
        )

        submitted = st.form_submit_button("💾 保存策略", use_container_width=True)

        if submitted:
            if not name or not display_name or not instructions:
                st.error("请填写必填字段")
            else:
                data = {
                    "name": name.strip(),
                    "display_name": display_name.strip(),
                    "description": description.strip(),
                    "category": category,
                    "instructions": instructions.strip(),
                    "market_regimes": [r.strip() for r in market_regimes_str.split(",") if r.strip()],
                }
                loader = get_strategy_loader()
                loader.save_custom_strategy(data)
                st.success(f"✅ 策略「{display_name}」已保存")

    # 管理自定义策略
    loader = get_strategy_loader()
    user_strategies = [s for s in loader.list_all() if s.source == "user"]
    if user_strategies:
        st.divider()
        st.caption("管理自定义策略:")
        for s in user_strategies:
            if st.button(f"🗑️ 删除「{s.display_name}」", key=f"del_strat_{s.name}"):
                loader.delete_custom_strategy(s.name)
                st.success(f"已删除「{s.display_name}」")
                st.rerun()


def render_execution_panel():
    """策略执行面板"""
    loader = get_strategy_loader()
    strategy = st.session_state.get("strategy_sel")

    if not strategy:
        st.info("👈 请先在左侧选择策略")
        return

    section_header("执行策略筛选")

    fund_type = st.selectbox(
        "基金类型",
        ["全部", "混合型", "股票型", "债券型", "指数型", "QDII", "货币型"],
        key="exec_fund_type",
    )

    top_n = st.slider("筛选数量", 5, 50, 20, key="exec_top_n")

    # 市场阶段上下文
    phase = st.session_state.get("strategy_market_phase")
    phase_context = ""
    if phase:
        phase_context = get_phase_detector().format_for_llm(phase)

    if not check_api_ready():
        return

    if st.button("🎯 开始策略筛选", use_container_width=True, type="primary"):
        with st.spinner(f"正在获取基金数据 + 执行策略「{strategy.display_name}」..."):
            # 获取基金列表
            fetcher = get_fetcher()
            fund_type_arg = None if fund_type == "全部" else fund_type
            fund_df = fetcher.screen_funds(
                fund_type=fund_type_arg,
                top_n=top_n,
            )

            if fund_df is None or fund_df.empty:
                st.warning("⚠️ 未找到符合条件的基金")
                return

            # 构建基金列表上下文
            context_lines = ["## 候选基金列表\n"]
            for _, row in fund_df.iterrows():
                code = row.get("基金代码", "")
                name = row.get("基金名称", "")
                ftype = row.get("基金类型", "")
                context_lines.append(
                    f"- {code} {name} ({ftype})"
                )

            fund_list_context = "\n".join(context_lines)

            # 执行策略
            executor = StrategyExecutor(strategy)
            system_prompt, user_prompt = executor.build_screening_prompt(
                fund_list_context,
                market_phase=phase_context,
            )

            result = run_analysis_stream(
                get_analyzer(),
                system_prompt,
                user_prompt,
                max_tokens=4096,
                temperature=0.3,
                placeholder_label=f"🎯 {strategy.display_name} 筛选结果",
            )

            if result and result.get("success"):
                st.session_state["strategy_result"] = result
                show_elapsed_time(result.get("elapsed_seconds", 0))
                show_token_usage(result.get("usage", {}))
            else:
                st.error("策略执行失败，请重试")


# ============================================================
# Main
# ============================================================

def main():
    render_page_header(
        title="策略引擎",
        icon="🧩",
        description="基于YAML策略模板的规则化基金筛选引擎，支持预置策略和自定义策略",
        help_text="使用说明：1. 选择策略模板 2. （可选）检测市场阶段 3. 选择基金类型并执行筛选",
        accent_color="#6366F1",
    )

    sidebar_config = render_sidebar_config()
    render_top_toolbar()

    tab1, tab2, tab3 = st.tabs([
        "🎯 策略筛选",
        "✏️ 自定义策略",
        "📖 策略详情",
    ])

    with tab1:
        col1, col2 = st.columns([1, 2])
        with col1:
            strategy = render_strategy_selector()
            render_market_phase_section()
        with col2:
            render_execution_panel()

    with tab2:
        render_strategy_editor()

    with tab3:
        section_header("预置策略总览")
        loader = get_strategy_loader()

        for cat in loader.get_categories():
            cat_strategies = loader.list_all(category=cat)
            if not cat_strategies:
                continue
            st.markdown(f"#### {cat_strategies[0].category_label}")
            for s in cat_strategies:
                with st.expander(f"{s.display_name} — {s.description}"):
                    st.caption(f"适用: {', '.join(s.market_regimes) if s.market_regimes else '通用'}")
                    st.caption(f"来源: {'系统预置' if s.source == 'system' else '用户自定义'}")
                    st.markdown(s.instructions)


if __name__ == "__main__":
    main()
