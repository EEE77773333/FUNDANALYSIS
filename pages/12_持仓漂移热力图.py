"""
持仓漂移热力图 — 页面 12
=========================
近8季度前十大持仓变化：热力图 + 行业暴露 + 风格漂移检测。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import numpy as np

from core.data_fetcher import get_fetcher
from core.ui_components import render_page_header, render_sidebar_config, render_top_toolbar, show_error, section_header
from core.holding_penetration import (
    map_stocks_to_sectors,
    calculate_sector_exposure,
    calculate_sector_deviation,
    detect_style_drift,
    SECTOR_BENCHMARK_WEIGHTS,
)

render_page_header("持仓漂移热力图", "🔥",
    "近8季度前十大持仓变化 + 行业暴露穿透 + 风格漂移检测",
    "**用法：** 输入基金代码 → 自动拉取连续8个季度的季报持仓 → 热力图/行业暴露/漂移预警",
    accent_color="#0891B2")

sidebar_config = render_sidebar_config()
render_top_toolbar()
fetcher = get_fetcher()

st.sidebar.markdown("---")
with st.expander("⚙️ 参数设置", expanded=True):
    c1, c2 = st.columns([1, 2])
    with c1:
        fund_code = st.text_input("基金代码", "000001", max_chars=6)
    with c2:
        st.write("")
        fetch_clicked = st.button("📡 获取持仓数据", use_container_width=True)

if fetch_clicked:
    import akshare as ak
    all_quarters = []
    try:
        df = ak.fund_portfolio_hold_em(symbol=fund_code, date=str(pd.Timestamp.now().year))
        if df is not None and not df.empty:
            quarters = df["季度"].dropna().unique()
            for q in sorted(quarters)[-8:]:
                q_df = df[df["季度"] == q][["股票名称","占净值比例","季度","股票代码"] if "股票代码" in df.columns else ["股票名称","占净值比例","季度"]].copy()
                q_df["占净值比例"] = q_df["占净值比例"].apply(float)
                all_quarters.append(q_df)

        if all_quarters:
            st.session_state["drift_data"] = all_quarters
            st.session_state["drift_code"] = fund_code
            st.session_state["sector_exposure"] = None   # 清除缓存
            st.session_state["style_drift"] = None
            st.success(f"✅ 加载了 {len(all_quarters)} 个季度的持仓数据")
        else:
            show_error("未获取到该基金的持仓数据（可能为纯债/货基）")
    except Exception as e:
        show_error(f"数据获取失败: {str(e)[:200]}")

if "drift_data" not in st.session_state:
    st.info("👆 请在侧边栏输入基金代码并获取数据")
    st.stop()

quarters_data = st.session_state["drift_data"]
quarter_labels = [str(q["季度"].iloc[0])[-8:] for q in quarters_data]

# ============================================================
# Tab 结构
# ============================================================
tab1, tab2, tab3 = st.tabs([
    "🔥 持仓变化",
    "🏭 行业暴露",
    "⚠️ 风格漂移",
])

# ============================================================
# Tab 1: 持仓变化（原有内容）
# ============================================================
with tab1:
    section_header("持仓权重变化热力图")
    all_stocks = sorted(set(s for q in quarters_data for s in q["股票名称"].values))

    heatmap_data = []
    for stock in all_stocks:
        row = []
        for q_df in quarters_data:
            match = q_df[q_df["股票名称"] == stock]
            row.append(float(match["占净值比例"].iloc[0]) if not match.empty else 0)
        heatmap_data.append(row)

    fig = go.Figure(data=go.Heatmap(
        z=heatmap_data,
        x=quarter_labels,
        y=all_stocks,
        colorscale="RdYlGn",
        text=[[f"{v:.2f}%" for v in row] for row in heatmap_data],
        texttemplate="%{text}",
        textfont={"size":10},
    ))
    fig.update_layout(height=max(300, len(all_stocks)*28), xaxis_title="季度", yaxis_title="")
    st.plotly_chart(fig, use_container_width=True)

    # 持仓集中度趋势
    section_header("持仓集中度趋势")
    conc_data = []
    for q_df in quarters_data:
        top3 = q_df.head(3)["占净值比例"].sum()
        top5 = q_df.head(5)["占净值比例"].sum()
        top10 = q_df["占净值比例"].sum()
        conc_data.append({"季度": quarter_labels[len(conc_data)], "Top3": top3, "Top5": top5, "Top10": top10})

    df_conc = pd.DataFrame(conc_data)
    fig2 = px.line(df_conc, x="季度", y=["Top3","Top5","Top10"], markers=True,
                   labels={"value":"集中度%","variable":"范围"},
                   color_discrete_map={"Top3":"#EF4444","Top5":"#F59E0B","Top10":"#3B82F6"})
    fig2.update_layout(height=350)
    st.plotly_chart(fig2, use_container_width=True)

    # 持仓变化概览
    section_header("最新两期对比")
    if len(quarters_data) >= 2:
        latest = quarters_data[-1].rename(columns={"占净值比例":"本期权重"})
        previous = quarters_data[-2].rename(columns={"占净值比例":"上期权重"})
        merged = pd.merge(latest, previous, on="股票名称", how="outer").fillna(0)
        merged["变化"] = merged["本期权重"] - merged["上期权重"]
        merged = merged.sort_values("变化", ascending=False)
        st.dataframe(merged[["股票名称","上期权重","本期权重","变化"]].style
                     .background_gradient(subset=["变化"], cmap="RdYlGn"),
                     use_container_width=True, hide_index=True)

# ============================================================
# Tab 2: 行业暴露
# ============================================================
with tab2:
    section_header("行业暴露穿透")
    st.caption("将前十大持仓穿透到申万一级行业，汇总各行业占净值比例")

    if st.button("🔍 计算行业暴露", key="calc_exposure"):
        with st.spinner("正在映射股票→行业 + 计算行业权重..."):
            # 获取行业映射
            all_names = list(set(s for q in quarters_data for s in q["股票名称"].values))
            sector_map = map_stocks_to_sectors(all_names)

            # 计算行业暴露
            exposure_df = calculate_sector_exposure(quarters_data, sector_map)
            st.session_state["sector_exposure"] = exposure_df
            st.session_state["sector_map"] = sector_map

            # 计算偏离基准
            deviation_df = calculate_sector_deviation(exposure_df)
            st.session_state["sector_deviation"] = deviation_df

    exposure_df = st.session_state.get("sector_exposure")
    deviation_df = st.session_state.get("sector_deviation")

    if exposure_df is not None and not exposure_df.empty:
        # 行业暴露热力图
        section_header("行业权重变化热力图")
        fig3 = go.Figure(data=go.Heatmap(
            z=exposure_df.values,
            x=exposure_df.columns.tolist(),
            y=exposure_df.index.tolist(),
            colorscale="Blues",
            text=[[f"{v:.1f}%" for v in row] for row in exposure_df.values],
            texttemplate="%{text}",
            textfont={"size":10},
        ))
        fig3.update_layout(
            height=max(300, len(exposure_df)*50),
            xaxis_title="行业", yaxis_title="季度",
        )
        st.plotly_chart(fig3, use_container_width=True)

        # 最新季度的行业分布饼图
        section_header("最新季度行业分布")
        latest_row = exposure_df.iloc[-1]
        latest_row = latest_row[latest_row > 0].sort_values(ascending=False)

        col1, col2 = st.columns([1, 1])
        with col1:
            fig_pie = go.Figure(data=[go.Pie(
                labels=latest_row.index.tolist(),
                values=latest_row.values.tolist(),
                hole=0.4,
                textinfo="label+percent",
            )])
            fig_pie.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_pie, use_container_width=True)

        with col2:
            # 行业暴露 vs 基准对比（最新季度）
            if deviation_df is not None and not deviation_df.empty:
                section_header("最新季度 超配/低配 vs 沪深300")
                latest_dev = deviation_df.iloc[-1].sort_values()

                colors = ["#EF4444" if v > 0 else "#16A34A" for v in latest_dev.values]
                fig_bar = go.Figure(data=[go.Bar(
                    x=latest_dev.values,
                    y=latest_dev.index.tolist(),
                    orientation="h",
                    marker_color=colors,
                )])
                fig_bar.update_layout(
                    height=max(300, len(latest_dev)*22),
                    xaxis_title="超配/低配 (百分点)",
                    margin=dict(l=10, r=10, t=10, b=10),
                )
                st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("👆 点击「计算行业暴露」按钮进行分析")

# ============================================================
# Tab 3: 风格漂移
# ============================================================
with tab3:
    section_header("风格漂移检测")
    st.caption("检测行业集中度变化、持仓换手率、行业权重偏离等风格漂移信号")

    if st.button("🔍 检测风格漂移", key="detect_drift"):
        with st.spinner("正在分析风格一致性..."):
            # 确保有行业暴露数据
            if st.session_state.get("sector_exposure") is None:
                all_names = list(set(s for q in quarters_data for s in q["股票名称"].values))
                sector_map = map_stocks_to_sectors(all_names)
                exposure_df = calculate_sector_exposure(quarters_data, sector_map)
                st.session_state["sector_exposure"] = exposure_df
                st.session_state["sector_map"] = sector_map

            drift_result = detect_style_drift(quarters_data)
            st.session_state["style_drift"] = drift_result

    drift_result = st.session_state.get("style_drift")

    if drift_result:
        # 漂移评分仪表盘
        score = drift_result.get("drift_score", 0)
        is_drifting = drift_result.get("is_drifting", False)

        col1, col2, col3 = st.columns(3)
        with col1:
            color = "#EF4444" if score >= 0.6 else ("#F59E0B" if score >= 0.4 else "#10B981")
            label = "⚠️ 显著漂移" if score >= 0.6 else ("⚡ 轻微漂移" if score >= 0.4 else "✅ 风格稳定")
            st.metric("漂移评分", f"{score:.0%}", delta=label)

        with col2:
            hhi_trend = drift_result.get("hhi_trend", [])
            if len(hhi_trend) >= 2:
                hhi_change = hhi_trend[-1]["HHI"] - hhi_trend[0]["HHI"]
                st.metric("HHI 变化", f"{hhi_trend[-1]['HHI']:.0f}", delta=f"{hhi_change:+.0f}")

        with col3:
            alerts = drift_result.get("drift_alerts", [])
            st.metric("漂移信号", f"{len(alerts)} 条")

        # 漂移告警
        if alerts:
            st.warning("🚨 检测到以下行业权重漂移信号:")
            for alert in alerts:
                st.markdown(f"- {alert}")

        # HHI 趋势图
        hhi_trend = drift_result.get("hhi_trend", [])
        if hhi_trend:
            section_header("行业集中度 (HHI) 趋势")
            df_hhi = pd.DataFrame(hhi_trend)
            fig_hhi = px.line(df_hhi, x="季度", y="HHI", markers=True)
            fig_hhi.add_hline(y=1000, line_dash="dash", line_color="orange", annotation_text="适度集中")
            fig_hhi.add_hline(y=1800, line_dash="dash", line_color="red", annotation_text="高集中")
            fig_hhi.update_layout(height=300)
            st.plotly_chart(fig_hhi, use_container_width=True)

        # 换手率代理
        turnover = drift_result.get("turnover_proxy", [])
        if turnover:
            section_header("行业换手率代理")
            df_to = pd.DataFrame(turnover)
            fig_to = px.bar(df_to, x="季度", y="换手率%", text_auto=".1f")
            fig_to.update_layout(height=250, yaxis_title="换手率%")
            st.plotly_chart(fig_to, use_container_width=True)

        # 风格一致性判断
        st.divider()
        if is_drifting:
            st.warning(
                "⚠️ **风格稳定性较差**\n\n"
                "该基金在过去几个季度中行业配置出现了显著变化。"
                "这可能意味着:\n"
                "- 基金经理在主动调整行业配置（行业轮动策略）\n"
                "- 或投资策略不稳定，存在风格漂移风险\n\n"
                "建议结合基金经理策略说明和季报观点综合判断。"
            )
        else:
            st.success(
                "✅ **风格较为稳定**\n\n"
                "该基金的行业配置在过去几个季度中保持相对一致，"
                "投资风格稳定，未检测到显著漂移信号。"
            )
    else:
        st.info("👆 点击「检测风格漂移」按钮进行诊断")
