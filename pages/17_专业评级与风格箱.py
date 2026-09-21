"""
专业评级与风格箱 — 页面 17
===========================
晨星九宫格风格箱 + 四机构评级 + 好买性价比评分。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from core.data_fetcher import get_fetcher
from core.fund_analyzer import (
    get_multi_agency_ratings, get_fund_ratings_by_code,
    classify_style_box, style_box_card, calc_howbuy_score,
    STYLE_BOX,
)
from core.utils import safe_float
from core.ui_components import (
    render_page_header, render_sidebar_config, render_top_toolbar, render_analysis_button,
    show_token_usage, show_elapsed_time, show_error, show_info_box,
    check_api_ready, rating_badge,
    section_header,
)

render_page_header("专业评级与风格箱", "🎓",
    "晨星九宫格风格箱 · 四机构评级（晨星/上海/招商/济安）· 好买性价比评分。",
    "**三大维度：** 风格箱定位大盘/中盘/小盘×价值/均衡/成长 | 四机构1-5星评级 | 0-100性价比综合评分",
    accent_color="#7C3AED")

sidebar_config = render_sidebar_config()
render_top_toolbar()
fetcher = get_fetcher()

tab1, tab2, tab3 = st.tabs(["📦 风格箱", "⭐ 机构评级", "💰 性价比评分"])

# ═══════════ Tab 1: 风格箱 ═══════════
with tab1:
    section_header("晨星九宫格风格箱")
    fund_code = st.text_input("基金代码", "000001", max_chars=6, key="style_code")

    if st.button("🔍 分析风格箱", use_container_width=True, type="primary"):
        with st.spinner("计算持仓风格..."):
            info = fetcher.get_fund_manager_info(fund_code)
            style = classify_style_box(fund_code)

            if style.get("confidence") != "无":
                fund_name = info.get("基金名称", fund_code) if info else fund_code

                # 九宫格可视化
                mcap = style.get("market_cap", "?")
                val = style.get("valuation", "?")
                grid_pos = {"大盘": 0, "中盘": 1, "小盘": 2}.get(mcap, 1)
                grid_val = {"价值": 0, "均衡": 1, "成长": 2}.get(val, 1)

                # 构建颜色矩阵
                z = [[0.1]*3 for _ in range(3)]
                z[grid_pos][grid_val] = 1.0
                labels_x = ["价值", "均衡", "成长"]
                labels_y = ["大盘", "中盘", "小盘"]

                fig = go.Figure(data=go.Heatmap(
                    z=z, x=labels_x, y=labels_y,
                    colorscale=[[0, '#F8FAFC'], [1, '#7C3AED']],
                    showscale=False,
                    text=[["","",""],["","",""],["","",""]],
                    texttemplate="", hoverinfo='skip',
                ))
                # 高亮当前格
                fig.add_annotation(x=grid_val, y=grid_pos,
                    text="★", font=dict(size=30, color="#7C3AED"), showarrow=False)

                fig.update_layout(
                    title=f"{fund_name} — {style.get('style', '')}",
                    height=350, xaxis=dict(side="top"),
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)

                # 指标详情
                cols = st.columns(4)
                cols[0].metric("风格定位", style.get("style", "N/A"))
                cols[1].metric("加权平均市值", f"{style.get('avg_mcap_亿', 'N/A')}亿")
                cols[2].metric("加权平均PE", f"{style.get('avg_pe', 'N/A')}")
                cols[3].metric("置信度", f"{style.get('confidence', 'N/A')} ({style.get('样本数', 0)}样本)")

                st.caption("💡 基于前十大重仓股的加权平均市值和PE估值进行九宫格定位")
            else:
                show_error("该基金持仓数据不足，无法判断风格")

# ═══════════ Tab 2: 机构评级 ═══════════
with tab2:
    section_header("四机构评级总览")
    if st.button("📡 获取最新评级数据", use_container_width=True, type="primary"):
        with st.spinner("获取全市场评级..."):
            df = get_multi_agency_ratings()
            if not df.empty:
                st.session_state["ratings_df"] = df
                st.success(f"✅ 加载 {len(df)} 只基金的评级数据")

    if "ratings_df" in st.session_state:
        df = st.session_state["ratings_df"]

        # 五星基金统计
        five_star_cols = ["晨星", "上海证券", "招商证券", "济安金信"]
        existing_cols = [c for c in five_star_cols if c in df.columns]
        if existing_cols:
            five_star_counts = {c: int((df[c]==5).sum()) for c in existing_cols}
            fig = px.bar(x=list(five_star_counts.keys()), y=list(five_star_counts.values()),
                         labels={"x":"","y":"五星基金数量"}, color_discrete_sequence=["#7C3AED"])
            fig.update_layout(height=250)
            st.plotly_chart(fig, use_container_width=True)

        # 搜索单只基金
        search_code = st.text_input("搜索基金代码查看评级", "", max_chars=6, placeholder="如 000001")
        if search_code:
            ratings = get_fund_ratings_by_code(search_code)
            if ratings:
                cols = st.columns(5)
                cols[0].metric("晨星", f"{ratings.get('晨星','?')}★" if ratings.get('晨星') else "N/A")
                cols[1].metric("上海证券", f"{ratings.get('上海证券','?')}★" if ratings.get('上海证券') else "N/A")
                cols[2].metric("招商证券", f"{ratings.get('招商证券','?')}★" if ratings.get('招商证券') else "N/A")
                cols[3].metric("济安金信", f"{ratings.get('济安金信','?')}★" if ratings.get('济安金信') else "N/A")
                cols[4].metric("综合评分", f"{ratings.get('综合评分', '?')}/5")
            else:
                st.info("未找到该基金的评级数据")

        # 高评级基金列表
        section_header("四机构一致5星基金")
        rated_cols = [c for c in five_star_cols if c in df.columns]
        if rated_cols:
            all_five = df[df[rated_cols].ge(4).all(axis=1)]
            st.dataframe(
                all_five[["基金代码","基金简称","晨星","上海证券","招商证券","济安金信","五星家数","基金类型"]].head(20),
                use_container_width=True, hide_index=True
            )
            st.caption(f"共 {len(all_five)} 只基金获四机构一致4星以上")

# ═══════════ Tab 3: 性价比评分 ═══════════
with tab3:
    section_header("好买风格性价比评分")
    code_score = st.text_input("基金代码", "000001", max_chars=6, key="score_code")

    if st.button("📊 计算性价比评分", use_container_width=True, type="primary"):
        with st.spinner("计算中..."):
            score = calc_howbuy_score(code_score)
            if score.get("total", 0) > 0:
                info = fetcher.get_fund_manager_info(code_score)
                fund_name = info.get("基金名称", code_score) if info else code_score

                # 总分环形图
                fig = go.Figure(go.Indicator(
                    mode="gauge+number", value=score["total"],
                    title={"text": f"{fund_name} 性价比评分"},
                    gauge={
                        "axis": {"range": [0, 100]},
                        "bar": {"color": "#7C3AED"},
                        "steps": [
                            {"range": [0, 35], "color": "#FEF2F2"},
                            {"range": [35, 50], "color": "#FFFBEB"},
                            {"range": [50, 65], "color": "#F0FDF4"},
                            {"range": [65, 80], "color": "#EFF6FF"},
                            {"range": [80, 100], "color": "#F5F3FF"},
                        ],
                        "threshold": {"line": {"color": "#7C3AED", "width": 3}, "value": score["total"]},
                    },
                    number={"suffix": f"  {score.get('等级','')}"},
                ))
                fig.update_layout(height=300)
                st.plotly_chart(fig, use_container_width=True)

                # 五维雷达图
                dims = ["收益能力","风控能力","费率效率","经理稳定","规模适配"]
                values = [score.get(d, 0) for d in dims]
                max_vals = [35, 30, 15, 10, 10]  # 各维度满分

                fig2 = go.Figure()
                fig2.add_trace(go.Scatterpolar(
                    r=[v/m*100 for v,m in zip(values, max_vals)],
                    theta=dims, fill='toself', line_color='#7C3AED',
                    name=fund_name))
                fig2.update_layout(polar=dict(radialaxis=dict(range=[0,100])), height=350)
                st.plotly_chart(fig2, use_container_width=True)

                # 分项明细
                section_header("分项评分")
                c1,c2,c3,c4,c5 = st.columns(5)
                c1.metric("收益能力", f"{score['收益能力']}/35")
                c2.metric("风控能力", f"{score['风控能力']}/30")
                c3.metric("费率效率", f"{score['费率效率']}/15")
                c4.metric("经理稳定", f"{score['经理稳定']}/10")
                c5.metric("规模适配", f"{score['规模适配']}/10")
            else:
                show_error(f"计算失败: {score.get('error', '未知错误')}")

st.markdown("---")
show_info_box(
    "🔬 **数据来源**：晨星评级 / 上海证券评级 / 招商证券评级 / 济安金信评级（AKShare）\n\n"
    "📦 **风格箱**：基于前十大持仓加权平均市值+PE估值的九宫格定位（近似晨星方法论）\n\n"
    "💰 **性价比评分**：参考好买基金评分框架，综合收益+风控+费率+经理+规模五维度"
)
