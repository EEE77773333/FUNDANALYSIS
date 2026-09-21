"""
QDII 基金筛选 — 页面 5
======================
全球化配置。硬性过滤：溢价率、额度状态、汇率策略。
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
    title="QDII 基金配置", icon="🌍",
    description="全球化配置，分散A股风险。硬性过滤：溢价率、额度状态、汇率策略。",
    help_text="**QDII特有风险：** 汇率风险 | 溢价风险(>3%回避) | 额度风险(限购) | 时差风险。**硬性过滤：** 溢价率<3% | 避开限购基金 | 关注汇率对冲策略",
)

sidebar_config = render_sidebar_config()
render_top_toolbar()
with st.expander("🌍 海外资产方向 & 过滤", expanded=False):
    target_markets = st.multiselect("配置方向", [
        "美股宽基（标普500/纳指100）", "美股科技（半导体）", "日股（日经225/东证）",
        "港股（恒生科技/恒指）", "印度/越南等新兴市场", "全球债券", "黄金/贵金属", "全球REITs/不动产",
    ], default=["美股宽基（标普500/纳指100）"])
    fund_count = st.slider("分析数量", 10, 100, 50, 10)
    max_premium = st.slider("溢价率上限（%）", 1.0, 10.0, 3.0, 0.5, help="场内溢价超过此值自动排除")
    exclude_restricted = st.checkbox("🚫 排除限购/暂停申购", value=True, help="QDII额度用完后常限购，二级市场买入溢价极高")
    warn_fx_risk = st.checkbox("💱 汇率风险提示", value=True)

section_header("QDII 基金数据获取")

if st.button("📡 获取 QDII 基金数据", use_container_width=True, type="primary"):
    with st.spinner("获取 QDII 基金数据..."):
        qdii_list = fetcher.get_fund_list("QDII")
        if qdii_list.empty: show_error("未获取到数据"); st.stop()
        results, premium_warns = [], []
        batch = qdii_list.sample(n=min(fund_count, len(qdii_list)), random_state=42) if len(qdii_list) > fund_count else qdii_list
        progress = st.progress(0)
        for i, (_, row) in enumerate(batch.iterrows()):
            code = str(row["基金代码"])
            estimate = fetcher.get_realtime_estimate(code)
            info = fetcher.get_fund_manager_info(code)
            nav = fetcher.get_fund_nav_history(code, years=2)
            ret_1y = "N/A"
            if not nav.empty and len(nav) >= 244:
                nav_s = nav.sort_values("日期", ascending=True)["单位净值"].dropna()
                if len(nav_s) >= 244: ret_1y = f"{calc_annualized_return(nav_s.iloc[-244:], 244)*100:.2f}%"
            premium, premium_val = "N/A", 0
            if estimate:
                est = safe_float(estimate.get("估算净值", 0)); last = safe_float(estimate.get("上一日净值", 0))
                if last > 0: premium_val = (est - last) / last * 100; premium = f"{premium_val:.2f}%"
            if abs(premium_val) > max_premium and premium_val != 0:
                premium_warns.append(f"⚠️ {row.get('基金简称','')}（{code}）溢价 {premium}")
                continue  # 排除高溢价
            results.append({
                "基金代码": code, "基金简称": row.get("基金简称", ""), "基金类型": row.get("基金类型", ""),
                "近1年收益": ret_1y,
                "估算涨幅": f"{safe_float(estimate.get('估算涨幅%', 0)):.2f}%" if estimate else "N/A",
                "溢价状态": premium,
                "基金经理": info.get("基金经理", "") if info else "N/A",
                "管理费率": f"{safe_float(info.get('管理费率%', 0) if info else 0):.2f}%",
            })
            progress.progress(min((i+1)/len(batch), 1.0))
        progress.empty()
        if results:
            st.session_state["qdii_fund_data"] = pd.DataFrame(results); st.session_state["qdii_data_fetched"] = True
            st.success(f"✅ {len(results)}只（排除{len(premium_warns)}只高溢价）")
        else: show_error("无基金通过溢价过滤")
        if premium_warns:
            with st.expander(f"⚠️ {len(premium_warns)}只高溢价基金被排除", expanded=False):
                for w in premium_warns: st.warning(w)

if st.session_state.get("qdii_data_fetched"):
    df = st.session_state["qdii_fund_data"]
    show_sortable_df(df)

st.markdown("---")
section_header("AI 全球配置分析")
if not check_api_ready(): st.stop()
analyze_clicked = render_analysis_button("🚀 开始 AI 全球配置分析", disabled=not st.session_state.get("qdii_data_fetched"), key="btn_qdii")
if analyze_clicked:
    df = st.session_state["qdii_fund_data"]
    pm = get_prompt_manager(); template = pm.get("qdii_fund_screening")
    system_prompt, user_prompt = template.render({
        "fund_data": df.to_markdown(index=False),
        "market_context": f"方向: {', '.join(target_markets)} | 溢价<{max_premium}% | {'排除限购' if exclude_restricted else '不限购'} | 请结合美联储货币政策、汇率走势分析",
    })
    if sidebar_config.get("model"): analyzer._model = sidebar_config["model"]
    depth_map = {"简要": 2048, "标准": 4096, "深度": 8192, "极致": 16384}
    max_tokens = depth_map.get(sidebar_config.get("depth", "标准"), 4096)
    final_result = run_analysis_stream(
        analyzer, system_prompt, user_prompt,
        max_tokens=max_tokens, temperature=0.3,
        placeholder_label="📝 全球配置分析报告"
    )
    if final_result and final_result.get("success"): show_elapsed_time(final_result.get("elapsed_seconds", 0)); show_token_usage(final_result.get("usage", {}))
if not analyze_clicked and not st.session_state.get("qdii_data_fetched"): st.info("👆 请先获取数据")
