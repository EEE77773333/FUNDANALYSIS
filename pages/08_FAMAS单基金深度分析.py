"""
FAMAS 单基金深度分析 — 页面 8
=============================
基于 FAMAS (Fund Analysis Multi-Agent System) 的多Agent协作框架，
对单只基金进行全方位深度分析：文档解析 → 业绩归因+费率+经理 → 宏观适配 → 综合评级。

Agent 清单:
1. prospectus_analyzer — 基金文档解析
2. performance_analyst — 业绩归因分析
3. cost_analyzer — 费率侦探
4. manager_profiler — 基金经理画像
5. holding_contribution — 个股贡献穿透
6. macro_strategist — 宏观策略顾问
7. wealth_advisor — 财富顾问（综合评级）
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime

from core.config import config
from core.data_fetcher import get_fetcher
from core.ai_analyzer import get_analyzer
from core.utils import (
    fmt_pct, fmt_money, safe_float,
    calc_annualized_return, calc_max_drawdown,
    calc_sharpe_ratio, calc_annual_volatility,
    calc_calmar_ratio, calc_sortino_ratio,
)
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    render_analysis_button,
    render_metrics_row,
    render_kv_cards,
    show_token_usage,
    show_elapsed_time,
    show_error,
    show_info_box,
    check_api_ready, run_analysis_stream,
    render_intraday_nav,
    _maybe_create_signal_from_dashboard,
    section_header,
)
from core.decision_extractor import DECISION_JSON_INSTRUCTION, extract_dashboard, merge_with_meta
from core.decision_renderer import render_decision_dashboard


# ---- Agent Prompts ----

def load_agent_prompt(agent_name: str) -> str:
    """加载 FAMAS Agent 的 System Prompt。"""
    prompt_path = Path(__file__).parent.parent / "prompts" / f"{agent_name}.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return ""


AGENTS = {
    "prospectus_analyzer": "基金文档解析专员",
    "performance_analyst": "业绩归因分析师",
    "cost_analyzer": "费率侦探",
    "manager_profiler": "基金经理画像师",
    "holding_contribution": "个股贡献穿透分析师",
    "macro_strategist": "宏观策略顾问",
    "wealth_advisor": "财富顾问",
}

# ---- 页面配置 ----
render_page_header(
    title="单基金深度分析",
    icon="🔬",
    accent_color="#7C3AED",
    description="""
    对单只基金进行七维度全方位深度分析。
    流程：文档解析 → 业绩归因+费率穿透+经理画像+个股穿透（并行）→ 宏观适配 → 综合评级。
    """,
    help_text="""
    **七个 Agent 分工：**
    1. 📄 **文档解析专员** — 投资范围、业绩基准、特殊条款、持有人结构
    2. 📈 **业绩归因分析师** — Alpha/Beta、风格漂移、行业轮动、回撤修复
    3. 💰 **费率侦探** — 显性费率+隐性成本+规模惩罚评估
    4. 👤 **基金经理画像师** — 能力圈图谱、稳定性、逆风表现
    5. 🔎 **个股贡献穿透分析师** — 重仓股贡献分解、行业暴露、个股质量、调仓动向
    6. 🌍 **宏观策略顾问** — 利率/汇率/政策适配度
    7. 🏷️ **财富顾问** — 综合星级评定(1-5星) + 时机矩阵 + 适配投资者类型

    **使用流程：**
    1. 输入基金代码
    2. 点击"获取基金数据"
    3. 逐个或批量启动 Agent 分析
    4. 查看综合评级报告
    """,
)

# ---- 侧边栏 ----
sidebar_config = render_sidebar_config()
render_top_toolbar()

with st.expander("💡 使用说明", expanded=False):
    st.markdown("""
    1. 输入基金代码
    2. 点击「获取基金数据」
    3. 逐个点击 Agent 的 **▶️ 启动分析** 按钮
    4. 或点击 **批量启动全部** 一键运行七Agent
    5. 最后查看 wealth_advisor 的综合评级
    """
)

st.sidebar.markdown("---")
st.sidebar.caption("💡 建议至少完成前5个Agent后再查看综合评级")

# ---- 主区域 ----
fetcher = get_fetcher()

# 侧栏/工作台跳转带入代码
_prefill = (
    st.session_state.pop("famas_fund_code_prefills", None)
    or st.query_params.get("fund", "")
    or ""
)
if _prefill:
    st.session_state["famas_fund_code_input"] = str(_prefill).strip()[:6]

section_header("基金数据获取")

col1, col2 = st.columns([1, 3])

with col1:
    fund_code = st.text_input(
        "基金代码 *",
        max_chars=6,
        placeholder="如 000001",
        help="输入6位基金代码",
        key="famas_fund_code_input",
    )

    fetch_clicked = st.button("📡 获取基金数据", use_container_width=True)
    if fund_code and fund_code.strip():
        from core.user_workspace import is_favorite, toggle_favorite
        fav = is_favorite(fund_code.strip())
        if st.button("⭐ 取消收藏" if fav else "⭐ 收藏", use_container_width=True, key="famas_fav_btn"):
            name = ""
            if st.session_state.get("famas_fund_data"):
                name = (st.session_state["famas_fund_data"].get("基本信息") or {}).get("基金名称", "")
            on = toggle_favorite(fund_code.strip(), name)
            st.toast("已收藏" if on else "已取消收藏", icon="⭐")
            st.rerun()

with col2:
    if fetch_clicked and fund_code.strip():
        with st.spinner(f"正在获取 {fund_code} 全面数据（含宏观+多季度+持有人+经理历史）..."):
            comprehensive = fetcher.get_fund_comprehensive(fund_code)

            # P0/P1/P2 增强数据获取
            try:
                comprehensive["宏观指标"] = fetcher.get_macro_indicators()
            except: pass

            try:
                comprehensive["持有人结构"] = fetcher._get_holder_structure(fund_code)
            except: pass

            try:
                comprehensive["多季度持仓"] = fetcher._get_multi_quarter_holdings(fund_code)
            except: pass

            try:
                comprehensive["经理变更历史"] = fetcher._get_manager_history(fund_code)
            except: pass

            st.session_state["famas_fund_code"] = fund_code
            st.session_state["famas_fund_data"] = comprehensive
            st.session_state["famas_data_fetched"] = True
            try:
                from core.user_workspace import touch_recent
                fname = (comprehensive.get("基本信息") or {}).get("基金名称", "")
                touch_recent("fund", fund_code.strip(), fname or fund_code.strip())
            except Exception:
                pass

    if st.session_state.get("famas_data_fetched"):
        data = st.session_state.get("famas_fund_data", {})
        info = data.get("基金概况", {})
        estimate = data.get("实时估值", {})
        nav = data.get("历史净值", pd.DataFrame())
        holdings = data.get("持仓明细", pd.DataFrame())

        # 基本信息卡片（文本用信息卡，真数值用 metric）
        section_header("基金概览")
        render_kv_cards([
            ("基金名称", info.get("基金名称", "N/A")),
            ("基金经理", info.get("基金经理", "N/A")),
            ("基金公司", info.get("基金公司", "N/A")),
            ("最新规模", info.get("最新规模", "N/A")),
        ], columns=4)
        render_intraday_nav(fund_code, expanded=True, show_table=True)

        # 历史净值
        if nav is not None and not nav.empty:
            with st.expander("📈 历史净值走势（近3年）", expanded=False):
                if "日期" in nav.columns and "单位净值" in nav.columns:
                    chart_df = nav.sort_values("日期", ascending=True).copy()
                    chart_df["日期"] = pd.to_datetime(chart_df["日期"])
                    st.line_chart(
                        chart_df.set_index("日期")["单位净值"],
                        use_container_width=True,
                    )

st.markdown("---")

# ---- AI 分析区 ----
if not check_api_ready():
    st.stop()

if not st.session_state.get("famas_data_fetched"):
    st.info("👆 请先输入基金代码并获取数据")
    st.stop()

fund_code = st.session_state["famas_fund_code"]
fund_data = st.session_state["famas_fund_data"]

analyzer = get_analyzer()
if sidebar_config.get("model"):
    analyzer.model = sidebar_config["model"]

depth_map = {"简要": 2048, "标准": 4096, "深度": 8192, "极致": 16384}
max_tokens = depth_map.get(sidebar_config.get("depth", "标准"), 4096)

# ---- 六个 Agent 定义 ----
AGENT_DEFS = [
    {
        "key": "prospectus_analyzer",
        "icon": "📄",
        "name": "文档解析专员",
        "desc": "投资范围、业绩基准、特殊条款、持有人结构",
        "layer": "第1层 · 基础解析",
        "deps": [],
    },
    {
        "key": "performance_analyst",
        "icon": "📈",
        "name": "业绩归因分析师",
        "desc": "Alpha/Beta、风格漂移、行业轮动、回撤修复天数",
        "layer": "第2层 · 量化归因",
        "deps": ["prospectus_analyzer"],
    },
    {
        "key": "cost_analyzer",
        "icon": "💰",
        "name": "费率侦探",
        "desc": "显性费率、隐性交易成本、规模惩罚评估",
        "layer": "第2层 · 量化归因",
        "deps": ["prospectus_analyzer"],
    },
    {
        "key": "manager_profiler",
        "icon": "👤",
        "name": "基金经理画像师",
        "desc": "能力圈图谱、稳定性评分、逆风年份表现",
        "layer": "第2层 · 量化归因",
        "deps": ["prospectus_analyzer"],
    },
    {
        "key": "holding_contribution",
        "icon": "🔎",
        "name": "个股贡献穿透分析师",
        "desc": "重仓股贡献分解、行业暴露、个股质量评估、调仓动向",
        "layer": "第2层 · 量化归因",
        "deps": ["prospectus_analyzer"],
    },
    {
        "key": "macro_strategist",
        "icon": "🌍",
        "name": "宏观策略顾问",
        "desc": "利率/汇率/行业政策适配度、风格顺风/逆风判断",
        "layer": "第3层 · 宏观适配",
        "deps": ["performance_analyst", "cost_analyzer", "manager_profiler", "holding_contribution"],
    },
    {
        "key": "wealth_advisor",
        "icon": "🏷️",
        "name": "财富顾问（综合评级）",
        "desc": "1-5星综合评定、时机矩阵、适配投资者画像、风险提示",
        "layer": "第4层 · 综合输出",
        "deps": ["prospectus_analyzer", "performance_analyst", "cost_analyzer",
                 "manager_profiler", "holding_contribution", "macro_strategist"],
    },
]


def _build_context(data: dict) -> str:
    """构建基金数据上下文（P0/P1/P2 全面增强）。"""
    info = data.get("基金概况", {})
    estimate = data.get("实时估值", {})
    nav = data.get("历史净值", pd.DataFrame())
    holdings = data.get("持仓明细", pd.DataFrame())
    macro = data.get("宏观指标", {})
    holder = data.get("持有人结构", {})
    multi_q = data.get("多季度持仓", [])
    manager_hist = data.get("经理变更历史", {})

    ctx_parts = [f"## 基金代码: {fund_code}"]

    # 基金概况
    if info:
        ctx_parts.append(f"## 基金概况\n```json\n{info}\n```")

    # 实时估值
    if estimate:
        ctx_parts.append(f"## 实时估值\n```json\n{estimate}\n```")

    # 持有人结构 (P2)
    if holder:
        ctx_parts.append(f"## 持有人结构\n```json\n{holder}\n```")

    # 经理变更历史 (P2)
    if manager_hist:
        ctx_parts.append(f"## 经理变更历史\n```json\n{manager_hist}\n```")

    # 收益风险指标
    if nav is not None and not nav.empty:
        nav_sorted = nav.sort_values("日期", ascending=True)
        nav_series = nav_sorted["单位净值"].dropna()
        returns = nav_series.pct_change().dropna()
        metrics = {
            "最新净值": round(nav_series.iloc[-1], 4),
            "年化收益率": f"{calc_annualized_return(nav_series)*100:.2f}%",
            "年化波动率": f"{calc_annual_volatility(returns)*100:.2f}%",
            "最大回撤": f"{calc_max_drawdown(nav_series)*100:.2f}%",
            "夏普比率": f"{calc_sharpe_ratio(returns):.2f}",
            "索提诺比率": f"{calc_sortino_ratio(returns):.2f}",
            "卡尔玛比率": f"{calc_calmar_ratio(nav_series, returns):.2f}",
            "数据起始": nav_sorted["日期"].iloc[0].strftime("%Y-%m-%d"),
            "数据截止": nav_sorted["日期"].iloc[-1].strftime("%Y-%m-%d"),
        }
        ctx_parts.append(f"## 收益风险指标\n```json\n{metrics}\n```")

    # 最新持仓（含涨跌幅+贡献度）
    if holdings is not None and not holdings.empty:
        enriched = fetcher.enrich_holdings_with_returns(holdings.head(10))
        ctx_parts.append(
            f"## 最新季度前十大重仓股（含涨跌幅及近似贡献度）\n{enriched.to_markdown(index=False)}"
        )

    # 多季度持仓对比 (P1)
    if multi_q:
        ctx_parts.append(f"## 近{len(multi_q)}季度持仓变化（用于风格漂移和调仓分析）\n```json\n{multi_q}\n```")

    # 宏观数据 (P0)
    if macro:
        ctx_parts.append(f"## 当前宏观经济指标\n```json\n{macro}\n```")
    else:
        ctx_parts.append("## 宏观经济指标\n（请基于你的训练知识分析当前宏观环境，并明确标注信息来源和时效性）")

    return "\n\n".join(ctx_parts)


# ---- 批量操作栏 ----
section_header("操作面板")
op_col1, op_col2, op_col3 = st.columns([2, 2, 1])
with op_col1:
    batch_all = st.button(
        "🚀 批量启动全部（按层级顺序）",
        type="primary",
        use_container_width=True,
        key="btn_batch_all",
    )
with op_col2:
    batch_layer2 = st.button(
        "⚡ 启动第1+2层（文档+业绩+费率+经理+个股穿透）",
        use_container_width=True,
        key="btn_batch_layer2",
    )
with op_col3:
    st.caption(f"模型: {analyzer.model}")

# ---- Agent 卡片网格 ----
st.markdown("---")
section_header("Agent 分析面板")

# 初始化 session state 存储各 Agent 结果
if "famas_results" not in st.session_state:
    st.session_state["famas_results"] = {}
if "famas_running" not in st.session_state:
    st.session_state["famas_running"] = {}

results = st.session_state["famas_results"]
running = st.session_state["famas_running"]


def _get_status(key: str) -> str:
    """获取 Agent 运行状态。"""
    if key in results:
        return "✅ 已完成"
    if running.get(key):
        return "⏳ 分析中..."
    return "⏸️ 待启动"


def _run_single_agent(agent_def: dict, context_data: str):
    """执行单个 Agent 并存储结果。"""
    key = agent_def["key"]
    running[key] = True

    system_prompt = load_agent_prompt(key)
    if not system_prompt:
        system_prompt = f"你是{agent_def['name']}，{agent_def['desc']}。请专业、客观地进行分析。"

    # 收集依赖 Agent 的结果作为上下文
    dep_context = ""
    for dep_key in agent_def["deps"]:
        if dep_key in results:
            dep_context += f"\n\n## {dep_key} 分析结果\n{results[dep_key]}"

    user_prompt = f"""请基于以下基金数据进行分析：

{context_data}
{ dep_context if dep_context else '' }

请按照你的专业领域（{agent_def['name']}：{agent_def['desc']}）输出详细的结构化分析结果。"""

    # 套餐配额守卫（托管版生效；社区版直通）
    try:
        from core.middleware import require_ai_quota
        if not require_ai_quota(f"FAMAS · {agent_def.get('name', 'Agent')} 分析"):
            results[key] = "⛔ 今日 AI 分析额度已用完，请升级套餐或明日再试。"
            running[key] = False
            return
    except ImportError:
        pass

    result = analyzer.analyze(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=0.3,
    )

    if result["success"]:
        results[key] = result["content"]
    else:
        results[key] = f"❌ 分析失败: {result['error']}"

    running[key] = False
    # 说明：AI 用量已由 core/metering.py 在 LLM 层统一记账，此处无需再手动计数


def _finalize_wealth_dashboard(full_text: str):
    """wealth_advisor 完成后解析决策 JSON 并持久化。"""
    if not full_text:
        return
    raw = extract_dashboard(full_text)
    if not raw:
        return
    info = fund_data.get("基金概况", {}) if fund_data else {}
    dashboard = merge_with_meta(
        raw,
        page_name="FAMAS单基金深度分析",
        fund_code=fund_code,
        fund_name=info.get("基金名称", ""),
        model=analyzer.model,
        markdown_fallback=full_text,
    )
    st.session_state["famas_dashboard"] = dashboard
    render_decision_dashboard(dashboard, expanded=True)
    _maybe_create_signal_from_dashboard(dashboard, fund_code, info.get("基金名称", ""))
    try:
        from core.history import get_history_manager
        hid = get_history_manager().save(
            page_name="FAMAS单基金深度分析",
            fund_code=fund_code,
            fund_name=info.get("基金名称", ""),
            system_prompt="wealth_advisor",
            user_prompt="",
            result_content=full_text,
            usage={},
            elapsed_seconds=0,
            model=analyzer.model,
            structured_result=dashboard,
        )
        st.caption(f"📚 综合评级已自动保存至分析历史 (#{hid})")
    except Exception as e:
        st.warning(f"⚠️ 综合评级保存失败：{str(e)[:120]}")


def _run_agent_stream(agent_def: dict, context_data: str, placeholder):
    """流式执行单个 Agent。"""
    key = agent_def["key"]
    running[key] = True

    # 套餐配额守卫（托管版生效；社区版直通；用户自带密钥不占用额度）
    try:
        from core.middleware import require_ai_quota
        if not require_ai_quota(f"FAMAS · {agent_def.get('name', 'Agent')} 分析"):
            results[key] = "⛔ 今日 AI 分析额度已用完，请升级套餐或明日再试。"
            running[key] = False
            return
    except ImportError:
        pass

    system_prompt = load_agent_prompt(key)
    if not system_prompt:
        system_prompt = f"你是{agent_def['name']}，{agent_def['desc']}。请专业、客观地进行分析。"

    if key == "wealth_advisor":
        system_prompt = system_prompt.rstrip() + "\n" + DECISION_JSON_INSTRUCTION

    dep_context = ""
    for dep_key in agent_def["deps"]:
        if dep_key in results:
            dep_context += f"\n\n## {dep_key} 分析结果\n{results[dep_key]}"

    full_text = ""
    try:
        stream_gen = analyzer.analyze_stream(
            system_prompt=system_prompt,
            user_prompt=f"请基于以下基金数据进行分析：\n\n{context_data}{dep_context}\n\n请按照你的专业领域（{agent_def['name']}：{agent_def['desc']}）输出详细的结构化分析。",
            max_tokens=max_tokens,
            temperature=0.3,
        )
        for chunk in stream_gen:
            if isinstance(chunk, str):
                full_text += chunk
                placeholder.markdown(full_text + "▌")
        results[key] = full_text
        if full_text.strip():
            # AI 用量已由 core/metering.py 在 LLM 层统一记账，此处无需重复计数
            # 每个 Agent 结果也写入分析历史（云端可回溯）
            try:
                from core.history import get_history_manager
                from core.user_workspace import touch_recent
                info = fund_data.get("基金概况", {}) if fund_data else {}
                fname = info.get("基金名称", "") if isinstance(info, dict) else ""
                hid = get_history_manager().save(
                    page_name=f"FAMAS/{agent_def.get('name') or key}",
                    fund_code=fund_code,
                    fund_name=fname or "",
                    system_prompt=system_prompt[:2000],
                    user_prompt=f"agent={key}",
                    result_content=full_text,
                    usage={},
                    elapsed_seconds=0,
                    model=getattr(analyzer, "model", "") or "",
                    structured_result=None,
                )
                st.caption(f"📚 已保存 {agent_def.get('name') or key} → 历史 #{hid}")
                touch_recent("fund", fund_code, fname or fund_code)
            except Exception as e:
                st.caption(f"⚠️ 保存历史失败：{str(e)[:80]}")
        if key == "wealth_advisor":
            _finalize_wealth_dashboard(full_text)
    except Exception as e:
        results[key] = f"❌ 分析失败: {str(e)}"

    running[key] = False


# 预构建数据上下文
context_data = _build_context(fund_data)

# 渲染 Agent — Tab 模式
agent_tabs = st.tabs([f"{a['icon']} {a['name']}" for a in AGENT_DEFS])

for i, agent in enumerate(AGENT_DEFS):
    key = agent["key"]
    status = _get_status(key)

    with agent_tabs[i]:
        # Agent 信息 + 操作栏
        c1, c2, c3 = st.columns([3, 1, 1.5])
        with c1:
            st.caption(f"{agent['desc']} · _{agent['layer']}_")
        with c2:
            st.caption(status)
        with c3:
            btn_disabled = running.get(key, False)
            btn_label = "🔄 重跑" if key in results else "▶️ 启动"
            if btn_disabled:
                btn_label = "⏳ 中..."
            if st.button(btn_label, key=f"tab_btn_{key}", disabled=btn_disabled, use_container_width=True):
                result_placeholder = st.empty()
                with st.spinner(f"{agent['icon']} {agent['name']} 分析中..."):
                    _run_agent_stream(agent, context_data, result_placeholder)
                st.rerun()

        # 结果
        if key in results:
            st.markdown(results[key])
            if key == "wealth_advisor" and st.session_state.get("famas_dashboard"):
                st.markdown("---")
                render_decision_dashboard(st.session_state["famas_dashboard"], expanded=True)
        else:
            st.info(f"👆 点击「▶️ 启动」运行 {agent['name']} 分析")

# ---- 批量处理 ----
if batch_all or batch_layer2:
    # 决定要运行的 Agent
    if batch_all:
        agents_to_run = AGENT_DEFS
    else:
        # 第1层 + 第2层
        agents_to_run = [a for a in AGENT_DEFS if "第1层" in a["layer"] or "第2层" in a["layer"]]

    # 按依赖顺序逐层运行
    for agent in agents_to_run:
        key = agent["key"]
        if key in results:
            continue  # 已有结果则跳过

        st.markdown(f"#### {agent['icon']} {agent['name']} 分析中...")
        placeholder = st.empty()

        _run_agent_stream(agent, context_data, placeholder)

    st.rerun()

# ---- 综合评级快速入口 ----
st.markdown("---")
if st.button("🏷️ 仅生成综合评级（需要前面6个Agent已完成）", use_container_width=True, key="btn_wealth_only"):
    wa = AGENT_DEFS[-1]  # wealth_advisor
    if wa["key"] not in results:
        placeholder = st.empty()
        st.markdown(f"#### {wa['icon']} {wa['name']} 分析中...")
        _run_agent_stream(wa, context_data, placeholder)
        st.rerun()
    else:
        st.info("综合评级已存在，点击上方 wealth_advisor 的「重新分析」按钮可重新生成")

# ---- 合规提示 ----
show_info_box(
    """
    ⚖️ **合规声明**
    - 本报告仅作信息整理与适配度分析，**不构成任何投资建议**
    - 评级基于历史数据与公开信息，基金过往业绩不预示未来表现
    - 报告中不包含"买入/卖出/加仓/减仓"等交易信号
    - 投资决策请结合自身风险承受能力与独立判断
    """
)
