"""
新闻情绪分析 — 页面 14
======================
对基金重仓股进行近期新闻扫描 + AI 情绪判断。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import streamlit as st
import pandas as pd

from core.data_fetcher import get_fetcher
from core.ai_analyzer import get_analyzer
from core.utils import safe_float
from core.ui_components import (
    render_page_header, render_sidebar_config, render_top_toolbar, render_analysis_button,
    show_token_usage, show_elapsed_time, show_error, check_api_ready, run_analysis_stream,
    section_header,
)

render_page_header("新闻情绪分析", "📰",
    "扫描基金前十大重仓股的最新新闻，AI 判断每条新闻对股价的情绪影响（正面/负面/中性）。",
    "**用法：** 输入基金代码 → 获取重仓股 → 拉取近期新闻 → AI情绪分析",
    accent_color="#7C3AED")

sidebar_config = render_sidebar_config()
render_top_toolbar()
fetcher = get_fetcher()

st.sidebar.markdown("---")
fund_code = st.text_input("基金代码", "000001", max_chars=6)
news_count = st.slider("每只股票抓取新闻数", 3, 20, 5)

if st.button("📡 获取重仓股+新闻", use_container_width=True, type="primary"):
    import akshare as ak

    with st.spinner(f"获取 {fund_code} 持仓..."):
        holdings = fetcher.get_fund_holdings(fund_code)
        if holdings is None or holdings.empty:
            show_error("未获取到持仓数据")
            st.stop()

    # 获取每只重仓股的新闻
    stock_news = {}
    for _, row in holdings.iterrows():
        stock_name = str(row["股票名称"])
        stock_code = str(row["股票代码"])
        try:
            news_df = ak.stock_news_em(symbol=stock_code)
            if news_df is not None and not news_df.empty:
                stock_news[stock_name] = news_df.head(news_count)[["新闻标题","发布时间"]].to_markdown(index=False)
        except Exception:
            pass

    st.session_state["sentiment_stocks"] = stock_news
    st.session_state["sentiment_fund"] = fund_code
    st.success(f"✅ 抓取了 {len(stock_news)}/{len(holdings)} 只股票的新闻")

if "sentiment_stocks" not in st.session_state:
    st.info("👆 输入基金代码并获取数据")
    st.stop()

stocks = st.session_state["sentiment_stocks"]

# 展示新闻
st.markdown(f"### 📋 重仓股新闻 ({len(stocks)}只)")
for name, news_md in stocks.items():
    with st.expander(f"📰 {name}", expanded=False):
        st.markdown(news_md)

# AI 情绪分析
st.markdown("---")
section_header("AI 情绪分析")
if not check_api_ready(): st.stop()

if render_analysis_button("🧠 AI 情绪分析", key="sentiment_ai"):
    news_summary = "\n\n".join(f"## {name}\n{news}" for name, news in stocks.items())
    analyzer = get_analyzer()
    if sidebar_config.get("model"): analyzer._model = sidebar_config["model"]
    fund = st.session_state.get("sentiment_fund") or fund_code

    result = run_analysis_stream(
        analyzer,
        system_prompt="""你是金融新闻情绪分析师。分析每条新闻对股价的可能影响，分为：
🟢 正面（利好）/ 🔴 负面（利空）/ ⚪ 中性。汇总该基金重仓股的整体情绪倾向。
最后给出"该基金当前持仓的新闻情绪综合评分（-10到+10）"。不构成投资建议。""",
        user_prompt=f"基金{fund}的重仓股近期新闻：\n\n{news_summary}\n\n请逐只分析情绪倾向，并给出综合评分。",
        max_tokens=4096,
        temperature=0.3,
        placeholder_label="新闻情绪分析报告",
        page_name="新闻情绪分析",
        fund_code=str(fund),
        fund_name="",
        enable_decision_dashboard=False,
    )
    if result:
        show_elapsed_time(result.get("elapsed_seconds", 0))
        show_token_usage(result.get("usage", {}))
        if result.get("history_id"):
            st.info(f"已写入分析历史 #{result['history_id']}，可到「分析历史」查看")
        elif result.get("content"):
            st.warning("分析已完成，但未写入历史。请看上方是否有红色/橙色报错，或到账户偏好确认已开启自动保存。")
