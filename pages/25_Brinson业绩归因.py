"""
Brinson 业绩归因 — 页面 25
==========================
将基金超额收益分解为配置效应 + 选股效应 + 交互效应。
支持 BHB（三因子）和 BF（两因子）模型。

使用说明:
  1. 输入基金代码
  2. 选择对比基准（沪深300/中证500）
  3. 查看行业层面的收益分解
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np

from core.config import config
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    show_info_box,
    show_error,
    init_page_state,
    safe_run,
    section_header,
)
from core.brinson import BrinsonAnalyzer
from core.holding_penetration import SECTOR_BENCHMARK_WEIGHTS

init_page_state({
    "brinson_result": None,
    "brinson_fund_code": "",
})


def main():
    render_page_header(
        title="Brinson 业绩归因",
        icon="🔬",
        description="将基金超额收益分解为配置效应（择时）+ 选股效应（择券）+ 交互效应，行业维度可视化",
        help_text="使用说明：1. 输入基金代码 2. 选择基准 3. 开始归因分析。BHB三因子模型含交叉项，BF两因子版更简洁。",
        accent_color="#7C3AED",
    )

    sidebar_config = render_sidebar_config()
    render_top_toolbar()

    with st.expander("⚙️ 参数设置", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            fund_code = st.text_input("基金代码", "000001", max_chars=6)
        with c2:
            benchmark = st.selectbox("对比基准", ["沪深300", "中证500"])
        fetch_clicked = st.button("🔬 开始归因分析", use_container_width=True, type="primary")

    if fetch_clicked:
        with st.spinner(f"正在获取 {fund_code} 的持仓数据 + 行业收益率..."):
            try:
                ba = BrinsonAnalyzer()
                result = ba.analyze(fund_code=fund_code, benchmark=benchmark)
                if "error" in result:
                    show_error(result["error"])
                else:
                    st.session_state["brinson_result"] = result
                    st.session_state["brinson_fund_code"] = fund_code
            except Exception as e:
                show_error(f"归因分析失败: {str(e)[:200]}")

    result = st.session_state.get("brinson_result")
    if not result:
        st.info("👈 请在侧边栏输入基金代码并点击「开始归因分析」")
        st.markdown("""
        ### 📖 Brinson 归因模型说明

        **Brinson 模型**是公募基金业绩归因的行业标准方法，将基金相对于基准的超额收益拆解为：

        | 效应 | 含义 | 正贡献来源 |
        |------|------|-----------|
        | **配置效应** | 超配/低配行业带来的收益 | 超配上涨行业、低配下跌行业 |
        | **选股效应** | 行业内部选股带来的收益 | 行业内的持仓涨幅 > 行业指数涨幅 |
        | **交互效应** | 配置与选股的交叉影响 | 超配且选股胜出的叠加效果 |

        ---
        #### 数学模型（BHB 三因子）

        - **配置效应** = Σ (Wp,i − Wb,i) × Rb,i
        - **选股效应** = Σ Wb,i × (Rp,i − Rb,i)
        - **交互效应** = Σ (Wp,i − Wb,i) × (Rp,i − Rb,i)

        其中 W=权重, R=收益率, p=组合, b=基准, i=行业
        """)
        return

    # ============================================================
    # 结果展示
    # ============================================================
    fund_code = st.session_state["brinson_fund_code"]

    # 概览卡片
    section_header("归因概览")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("总超额收益", f"{result['total_excess']:+.2f}%")
    col2.metric("组合收益", f"{result['Rp']}%")
    col3.metric("基准收益", f"{result['Rb']}%")
    col4.metric("覆盖行业数", result["sector_count"])
    col5.metric("基准", result["benchmark"])

    # BHB vs BF
    section_header("收益分解")
    col1, col2 = st.columns(2)
    with col1:
        section_header("BHB 三因子")
        bhb = result["bhb"]
        m1, m2, m3 = st.columns(3)
        m1.metric("配置效应", f"{bhb['allocation']:+.2f}%")
        m2.metric("选股效应", f"{bhb['selection']:+.2f}%")
        m3.metric("交互效应", f"{bhb['interaction']:+.2f}%")

    with col2:
        section_header("BF 两因子")
        bf = result["bf"]
        m1, m2 = st.columns(2)
        m1.metric("配置效应", f"{bf['allocation']:+.2f}%")
        m2.metric("选股效应", f"{bf['selection']:+.2f}%")

    # 行业分解瀑布图
    section_header("行业层面分解")
    chart = result["chart_data"]
    by_sector = result["by_sector"]

    if by_sector:
        # 堆叠柱状图：配置+选股+交互
        fig = go.Figure()
        sectors = chart["sectors"]
        fig.add_trace(go.Bar(name="配置效应", x=sectors, y=chart["allocation"],
                             marker_color="#3B82F6"))
        fig.add_trace(go.Bar(name="选股效应", x=sectors, y=chart["selection"],
                             marker_color="#10B981"))
        fig.add_trace(go.Bar(name="交互效应", x=sectors, y=chart["interaction"],
                             marker_color="#F59E0B"))
        fig.update_layout(
            barmode="relative",
            height=max(350, len(sectors) * 30),
            xaxis_title="行业",
            yaxis_title="收益贡献 (%)",
            legend=dict(orientation="h", y=1.12),
        )
        st.plotly_chart(fig, use_container_width=True)

    # 行业归因明细表
    section_header("行业归因明细")
    df_sector = pd.DataFrame(by_sector)

    # 超配/低配着色
    def color_overweight(val):
        if isinstance(val, (int, float)):
            if val > 0: return "color: #DC2626"
            elif val < 0: return "color: #16A34A"
        return ""

    st.dataframe(
        df_sector.style
        .applymap(color_overweight, subset=["超配%", "配置效应%", "选股效应%", "交互效应%", "总效应%"])
        .format({
            "组合权重%": "{:.1f}", "基准权重%": "{:.1f}",
            "超配%": "{:+.1f}", "行业收益%": "{:+.1f}",
            "配置效应%": "{:+.3f}", "选股效应%": "{:+.3f}",
            "交互效应%": "{:+.3f}", "总效应%": "{:+.3f}",
        }),
        use_container_width=True, hide_index=True,
        height=min(600, len(by_sector) * 35 + 38),
    )

    # 解读
    st.divider()
    section_header("AI 解读")
    total_excess = result["total_excess"]
    alloc = bhb["allocation"]
    sel = bhb["selection"]

    if total_excess > 0:
        main_driver = "配置能力" if abs(alloc) > abs(sel) else "选股能力"
        st.success(
            f"✅ 该基金在分析期间跑赢基准 **{total_excess:+.2f}%**。\n\n"
            f"主要超额收益来源于**{main_driver}**"
            f"（配置贡献 {alloc:+.2f}%，选股贡献 {sel:+.2f}%）。"
        )
    else:
        st.warning(
            f"⚠️ 该基金在分析期间跑输基准 **{total_excess:+.2f}%**。\n\n"
            f"配置效应 {alloc:+.2f}%，选股效应 {sel:+.2f}%。"
        )

    # top3 超配/低配行业
    sorted_by_overweight = sorted(by_sector, key=lambda x: x["超配%"], reverse=True)
    top_over = sorted_by_overweight[:3]
    top_under = sorted_by_overweight[-3:]

    st.caption(
        "**超配最多的行业**: " +
        "、".join(f"{s['行业']}({s['超配%']:+.1f}%)" for s in top_over) +
        " | **低配最多的行业**: " +
        "、".join(f"{s['行业']}({s['超配%']:+.1f}%)" for s in reversed(top_under))
    )


if __name__ == "__main__":
    main()
