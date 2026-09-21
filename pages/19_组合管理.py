"""
组合管理 - 页面 19
================
创建和管理投资组合，支持手动添加持仓、CSV/Excel批量导入、
组合风险分析（集中度、回撤、相关性、净值走势）。

使用说明:
  1. 创建新组合：在「我的组合」标签页点击"新建组合"
  2. 添加持仓：在「持仓明细」标签页手动添加或导入CSV/Excel
  3. 风险分析：在「风险分析」标签页查看组合概览
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from core.config import config
from core.data_fetcher import get_fetcher
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    show_info_box,
    show_error,
    render_metrics_row,
    init_page_state,
    safe_run,
    section_header,
)
from core.portfolio import get_portfolio_manager
from core.portfolio_optimizer import PortfolioOptimizer
from core.ui_components import render_intraday_nav, show_sortable_df
from core.track_rebalance import get_track_rebalance_engine, BALANCE_PRESETS


# ============================================================
# Page Config
# ============================================================
init_page_state({
    "portfolio_selected_id": None,
    "portfolio_import_preview": None,
})


# ============================================================
# Helpers
# ============================================================

def render_create_form():
    """新建组合表单"""
    with st.form("create_portfolio"):
        name = st.text_input("组合名称", placeholder="例如：我的养老定投组合")
        description = st.text_area("描述（可选）", placeholder="组合策略说明...")
        submitted = st.form_submit_button("✅ 创建组合", use_container_width=True)
        if submitted and name.strip():
            pm = get_portfolio_manager()
            pid = pm.create(name.strip(), description.strip())
            st.session_state["portfolio_selected_id"] = pid
            st.success(f"✅ 组合「{name}」已创建")
            st.rerun()
        elif submitted and not name.strip():
            st.error("请输入组合名称")


def render_holding_add_form(portfolio_id: int):
    """添加持仓表单"""
    with st.form(f"add_holding_{portfolio_id}"):
        col1, col2 = st.columns(2)
        with col1:
            fund_code = st.text_input("基金代码", placeholder="6位代码，如 000001")
        with col2:
            weight = st.number_input("权重 (%)", 0.0, 100.0, 10.0, step=1.0)

        col3, col4 = st.columns(2)
        with col3:
            amount = st.number_input("投入金额", 0.0, 1e9, 10000.0, step=1000.0)
        with col4:
            purchase_date = st.date_input("购买日期", key=f"pdate_{portfolio_id}")

        notes = st.text_input("备注（可选）", placeholder="定投/一次性买入...")

        submitted = st.form_submit_button("➕ 添加持仓", use_container_width=True)
        if submitted and fund_code.strip():
            pm = get_portfolio_manager()
            pm.add_holding(
                portfolio_id,
                fund_code.strip(),
                amount=amount,
                weight=weight / 100,
                purchase_date=str(purchase_date) if purchase_date else "",
                notes=notes,
            )
            st.success(f"✅ 已添加 {fund_code}")
            st.rerun()


def render_import_section(portfolio_id: int):
    """导入持仓区域"""
    section_header("批量导入持仓")
    st.caption("支持 CSV、Excel (.xlsx) 文件，自动识别列名")

    uploaded = st.file_uploader(
        "上传文件",
        type=["csv", "xlsx"],
        key=f"import_{portfolio_id}",
        help="列名可以是：基金代码/代码/code、基金名称/名称/name、权重/占比/weight、金额/市值/amount",
    )

    if uploaded:
        file_bytes = uploaded.read()
        pm = get_portfolio_manager()

        # 预览解析结果
        try:
            if uploaded.name.endswith(".csv"):
                for enc in ["utf-8", "gbk", "gb2312", "utf-8-sig"]:
                    try:
                        import io
                        df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc)
                        break
                    except (UnicodeDecodeError, TypeError):
                        continue
                else:
                    df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8", errors="replace")
            else:
                df = pd.read_excel(io.BytesIO(file_bytes))

            st.dataframe(df.head(10), use_container_width=True)
            st.caption(f"共识别 {len(df)} 行数据")

            if st.button("✅ 确认导入", key=f"confirm_import_{portfolio_id}"):
                try:
                    count = pm.import_from_dataframe(portfolio_id, df)
                    st.success(f"✅ 成功导入 {count} 条持仓")
                    st.rerun()
                except Exception as e:
                    st.error(f"导入失败: {e}")

        except Exception as e:
            st.error(f"文件解析失败: {e}")


def render_risk_dashboard(portfolio_id: int):
    """风险分析面板"""
    pm = get_portfolio_manager()
    p = pm.get(portfolio_id)
    if not p or not p.holdings:
        st.info("📭 暂无持仓数据，请先添加基金")
        return

    with st.spinner("计算风险指标中..."):
        # ---- 集中度 ----
        conc = pm.analyze_concentration(portfolio_id)

        # ---- 综合指标 ----
        metrics = pm.compute_portfolio_metrics(portfolio_id)

        # ---- 相关性 ----
        corr = pm.analyze_correlation(portfolio_id)

        # ---- 净值序列 ----
        nav_series = pm.get_nav_series(portfolio_id)

    # 指标卡片
    if metrics:
        cols = st.columns(5)
        cols[0].metric("年化收益", f"{metrics.get('annualized_return', 0) * 100:.2f}%")
        cols[1].metric("年化波动", f"{metrics.get('annual_volatility', 0) * 100:.2f}%")
        cols[2].metric("夏普比率", f"{metrics.get('sharpe_ratio', 0):.2f}")
        cols[3].metric("最大回撤", f"{metrics.get('max_drawdown', 0) * 100:.2f}%")
        cols[4].metric("胜率", f"{metrics.get('win_rate', 0) * 100:.0f}%")

    st.divider()

    # 图表区域
    col1, col2 = st.columns(2)

    with col1:
        # 集中度饼图
        section_header("持仓权重分布")
        holdings_df = pm.get_holdings_df(portfolio_id)
        if not holdings_df.empty:
            labels = holdings_df["fund_name"].fillna(holdings_df["fund_code"]).tolist()
            values = holdings_df["weight"].tolist()
            # 缩短标签
            short_labels = [l[:12] + "..." if len(str(l)) > 12 else l for l in labels]
            fig = go.Figure(data=[go.Pie(labels=short_labels, values=values, hole=0.4)])
            fig.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        # 净值走势
        section_header("组合净值走势")
        if not nav_series.empty:
            fig = go.Figure(data=[go.Scatter(
                x=nav_series.index, y=nav_series.values,
                mode="lines", line=dict(color="#3B82F6", width=2),
                name="组合净值",
            )])
            fig.update_layout(
                height=350, margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title="", yaxis_title="净值",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("数据不足，无法生成净值走势")

    # 相关性热力图
    if not corr.empty:
        section_header("持仓相关性矩阵")
        fig = px.imshow(
            corr, text_auto=".2f",
            color_continuous_scale="RdBu_r",
            zmin=-1, zmax=1,
            aspect="auto",
        )
        fig.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # 集中度分析
    section_header("集中度分析")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("前3大持仓占比", f"{conc.get('top3_weight', 0) * 100:.1f}%")
    c2.metric("前5大持仓占比", f"{conc.get('top5_weight', 0) * 100:.1f}%")
    c3.metric("最大单一持仓", f"{conc.get('max_single_weight', 0) * 100:.1f}%")
    hhi = conc.get("hhi_index", 0)
    hhi_label = "高集中" if hhi > 2500 else ("中等集中" if hhi > 1500 else "分散")
    c4.metric("HHI 指数", f"{hhi:.0f}", delta=hhi_label)

    # 基金类型分布
    ftypes = conc.get("fund_type_breakdown", {})
    if ftypes:
        st.caption("📋 基金类型分布:")
        cols = st.columns(len(ftypes))
        for i, (ftype, wt) in enumerate(ftypes.items()):
            cols[i].metric(ftype, f"{wt * 100:.1f}%")


def render_intraday_track_panel(portfolio_id: int):
    """组合盘中估值 + 赛道暴露快览。"""
    pm = get_portfolio_manager()
    p = pm.get(portfolio_id)
    if not p or not p.holdings:
        st.info("暂无持仓")
        return

    section_header("持仓盘中估值快览")
    for h in p.holdings[:6]:
        render_intraday_nav(h["fund_code"], expanded=False, show_table=False)

    section_header("赛道暴露 vs 目标")
    engine = get_track_rebalance_engine()
    result = engine.analyze(p.holdings, balance_strength=BALANCE_PRESETS["中"], include_flow=True)
    rows = [{
        "赛道": r.track,
        "当前%": round(r.current_weight * 100, 1),
        "目标%": round(r.target_weight * 100, 1),
        "偏离%": round(r.deviation * 100, 1),
    } for r in result["track_rows"]]
    if rows:
        show_sortable_df(pd.DataFrame(rows))
    st.page_link("pages/30_赛道再平衡.py", label="完整赛道再平衡", icon="⚖️")


# ============================================================
# Main
# ============================================================

def main():
    render_page_header(
        title="组合管理",
        icon="💼",
        description="创建和管理投资组合，支持持仓导入、风险分析和净值跟踪",
        help_text="使用说明：1. 创建组合 2. 添加持仓（手动或导入CSV/Excel） 3. 查看风险分析",
        accent_color="#10B981",
    )

    sidebar_config = render_sidebar_config()
    render_top_toolbar()

    pm = get_portfolio_manager()
    portfolios = pm.list_all()

    # ---- Tab 结构 ----
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 我的组合",
        "📊 持仓明细",
        "🔬 风险分析",
        "📡 盘中与赛道",
        "📈 有效前沿",
    ])

    # ============================================================
    # Tab 1: 我的组合
    # ============================================================
    with tab1:
        # 新建组合
        with st.expander("➕ 新建组合", expanded=not portfolios):
            render_create_form()

        if not portfolios:
            st.info("📭 暂无组合。点击上方「新建组合」开始。")
        else:
            st.divider()
            section_header("已有组合")

            for p in portfolios:
                with st.container():
                    col1, col2, col3 = st.columns([3, 1, 1])
                    with col1:
                        is_selected = st.session_state.get("portfolio_selected_id") == p.id
                        selected_marker = "⭐ " if is_selected else ""
                        st.markdown(f"**{selected_marker}{p.name}**")
                        if p.description:
                            st.caption(p.description)
                        st.caption(f"🕐 更新于 {p.updated_at} · {p.holding_count} 只基金")

                    with col2:
                        if st.button("📊 分析", key=f"analyze_{p.id}"):
                            st.session_state["portfolio_selected_id"] = p.id
                            st.rerun()

                    with col3:
                        if st.button("🗑️ 删除", key=f"delete_{p.id}"):
                            pm.delete(p.id)
                            if st.session_state.get("portfolio_selected_id") == p.id:
                                st.session_state["portfolio_selected_id"] = None
                            st.success(f"已删除「{p.name}」")
                            st.rerun()

    # ============================================================
    # Tab 2: 持仓明细
    # ============================================================
    with tab2:
        if not portfolios:
            st.info("📭 请先在「我的组合」标签页创建组合")
        else:
            # 选择组合
            sel_id = st.selectbox(
                "选择组合",
                [p.id for p in portfolios],
                format_func=lambda pid: next((p.name for p in portfolios if p.id == pid), str(pid)),
                key="holdings_portfolio_sel",
            )

            if sel_id:
                p = pm.get(sel_id)
                st.markdown(f"### {p.name}")
                st.caption(f"{p.holding_count} 只基金 · 总权重 {p.total_weight * 100:.1f}%")

                # 持仓表格
                holdings_df = pm.get_holdings_df(sel_id)
                if holdings_df.empty:
                    st.info("📭 暂无持仓")
                else:
                    # 可编辑表格
                    display_df = holdings_df[["fund_code", "fund_name", "amount", "weight", "purchase_date", "notes"]].copy()
                    display_df["weight"] = (display_df["weight"] * 100).round(1)  # 显示为百分比
                    display_df.columns = ["基金代码", "基金名称", "金额", "权重%", "购买日期", "备注"]

                    edited = st.data_editor(
                        display_df,
                        num_rows="dynamic",
                        use_container_width=True,
                        key=f"editor_{sel_id}",
                        column_config={
                            "基金代码": st.column_config.TextColumn("基金代码", width="small"),
                            "权重%": st.column_config.NumberColumn("权重%", min_value=0, max_value=100, step=1.0),
                        },
                    )

                    if st.button("💾 保存修改", key=f"save_{sel_id}"):
                        # 同步修改
                        for idx, row in edited.iterrows():
                            code = str(row["基金代码"]).strip()
                            if code:
                                pm.update_holding(
                                    sel_id, code,
                                    amount=float(row.get("金额", 0)),
                                    weight=float(row.get("权重%", 0)) / 100,
                                    notes=str(row.get("备注", "")),
                                )
                        st.success("✅ 已保存")
                        st.rerun()

                    # 删除按钮
                    st.divider()
                    to_delete = st.selectbox(
                        "选择要删除的基金",
                        holdings_df["fund_code"].tolist(),
                        format_func=lambda c: f"{c} - {holdings_df[holdings_df['fund_code']==c]['fund_name'].iloc[0]}" if c else c,
                        key=f"del_sel_{sel_id}",
                    )
                    if st.button("🗑️ 删除选中持仓", key=f"del_btn_{sel_id}"):
                        pm.remove_holding(sel_id, to_delete)
                        st.success(f"已删除 {to_delete}")
                        st.rerun()

                # 添加持仓
                st.divider()
                section_header("手动添加")
                render_holding_add_form(sel_id)

                # 导入
                st.divider()
                render_import_section(sel_id)

    # ============================================================
    # Tab 3: 风险分析
    # ============================================================
    with tab3:
        if not portfolios:
            st.info("📭 请先在「我的组合」标签页创建组合并添加持仓")
        else:
            # 复用 Tab 1 的选择（如果有的话）
            ids = [p.id for p in portfolios]
            default_idx = 0
            preselected = st.session_state.get("portfolio_selected_id")
            if preselected and preselected in ids:
                default_idx = ids.index(preselected)
            sel_id = st.selectbox(
                "选择组合",
                ids,
                index=default_idx,
                format_func=lambda pid: next((p.name for p in portfolios if p.id == pid), str(pid)),
                key="risk_portfolio_sel",
            )

            if sel_id:
                render_risk_dashboard(sel_id)

    # ============================================================
    # Tab 4: 盘中与赛道
    # ============================================================
    with tab4:
        if not portfolios:
            st.info("📭 请先在「我的组合」标签页创建组合并添加持仓")
        else:
            ids = [p.id for p in portfolios]
            default_idx = 0
            preselected = st.session_state.get("portfolio_selected_id")
            if preselected and preselected in ids:
                default_idx = ids.index(preselected)
            sel_id = st.selectbox(
                "选择组合",
                ids,
                index=default_idx,
                format_func=lambda pid: next((p.name for p in portfolios if p.id == pid), str(pid)),
                key="intraday_portfolio_sel",
            )
            if sel_id:
                render_intraday_track_panel(sel_id)

    # ============================================================
    # Tab 5: 有效前沿
    # ============================================================
    with tab5:
        if not portfolios:
            st.info("📭 请先在「我的组合」标签页创建组合并添加持仓")
        else:
            ids = [p.id for p in portfolios]
            default_idx = 0
            preselected = st.session_state.get("portfolio_selected_id")
            if preselected and preselected in ids:
                default_idx = ids.index(preselected)
            sel_id = st.selectbox(
                "选择组合",
                ids,
                index=default_idx,
                format_func=lambda pid: next((p.name for p in portfolios if p.id == pid), str(pid)),
                key="frontier_portfolio_sel",
            )

            if sel_id:
                p = pm.get(sel_id)
                if not p or len(p.holdings) < 2:
                    st.info("📭 需要至少 2 只持仓基金才能进行优化分析")
                else:
                    st.markdown(f"### 📈 {p.name} — 马科维茨优化")

                    if st.button("🚀 计算有效前沿", key="calc_frontier", use_container_width=True, type="primary"):
                        with st.spinner("正在获取基金历史收益率 + 优化求解..."):
                            try:
                                # 获取各持仓基金的日收益率
                                codes = [h["fund_code"] for h in p.holdings]
                                weights_cur = {h["fund_code"]: h.get("weight", 0) for h in p.holdings}
                                # 归一化当前权重
                                tw = sum(weights_cur.values())
                                if tw > 0:
                                    weights_cur = {c: w / tw for c, w in weights_cur.items()}

                                fetcher = get_fetcher()
                                return_data = {}
                                for code in codes:
                                    nav = fetcher.get_fund_nav_history(code, years=3)
                                    if nav is not None and not nav.empty:
                                        nav = nav.sort_values("日期")
                                        nav["ret"] = nav["单位净值"].pct_change()
                                        rets = nav.set_index("日期")["ret"].dropna()
                                        if len(rets) > 60:
                                            return_data[code] = rets

                                if len(return_data) < 2:
                                    st.error("至少需要2只基金有足够的净值数据（>60个交易日）")
                                else:
                                    returns_df = pd.DataFrame(return_data).dropna()
                                    if len(returns_df) < 30:
                                        st.error("重叠交易日不足30天，无法计算协方差矩阵")
                                    else:
                                        optimizer = PortfolioOptimizer()
                                        comp = optimizer.compare_allocations(returns_df, weights_cur)

                                        st.session_state["frontier_data"] = {
                                            "comparison": comp,
                                            "codes_used": list(return_data.keys()),
                                            "weights_current": weights_cur,
                                        }

                                        # 有效前沿
                                        frontier = optimizer.efficient_frontier(returns_df, points=40)
                                        st.session_state["frontier_curve"] = frontier
                                        st.success("✅ 优化完成")
                            except Exception as e:
                                st.error(f"优化失败: {str(e)[:200]}")

                    # 结果展示
                    frontier_data = st.session_state.get("frontier_data")
                    frontier_curve = st.session_state.get("frontier_curve")

                    if frontier_data:
                        comp = frontier_data["comparison"]

                        # ---- 权重对比表 ----
                        section_header("权重对比")
                        codes_used = frontier_data["codes_used"]
                        weights_table = []
                        for code in codes_used:
                            name = ""
                            for h in p.holdings:
                                if h["fund_code"] == code:
                                    name = h.get("fund_name", code)
                                    break
                            cur = comp["current"]["weights"].get(code, 0)
                            ms = comp["max_sharpe"].get("weights", {}).get(code, 0) if comp["max_sharpe"].get("success") else 0
                            mv = comp["min_volatility"].get("weights", {}).get(code, 0) if comp["min_volatility"].get("success") else 0
                            weights_table.append({
                                "基金": f"{name}({code})",
                                "当前": f"{cur*100:.0f}%",
                                "最大Sharpe": f"{ms*100:.0f}%",
                                "最小波动": f"{mv*100:.0f}%",
                            })

                        st.dataframe(pd.DataFrame(weights_table), use_container_width=True, hide_index=True)

                        # ---- 指标对比 ----
                        section_header("优化方案对比")
                        metrics_compare = []
                        for label, data in [
                            ("当前配置", comp["current"]),
                            ("最大Sharpe", comp["max_sharpe"]),
                            ("最小波动", comp["min_volatility"]),
                            ("风险平价", comp["risk_parity"]),
                        ]:
                            if isinstance(data, dict) and data.get("success", True):
                                metrics_compare.append({
                                    "方案": label,
                                    "年化收益": f"{data['annualized_return']*100:.2f}%",
                                    "年化波动": f"{data['annualized_volatility']*100:.2f}%",
                                    "Sharpe": f"{data['sharpe_ratio']:.2f}",
                                })

                        if metrics_compare:
                            st.dataframe(pd.DataFrame(metrics_compare), use_container_width=True, hide_index=True)

                        # ---- 有效前沿图 ----
                        if frontier_curve and frontier_curve.get("frontier"):
                            section_header("有效前沿曲线")
                            frontier_pts = frontier_curve["frontier"]
                            max_s = frontier_curve.get("max_sharpe", {})
                            min_v = frontier_curve.get("min_volatility", {})

                            fig_ef = go.Figure()
                            # 有效前沿
                            fig_ef.add_trace(go.Scatter(
                                x=[p["volatility"] * 100 for p in frontier_pts],
                                y=[p["return"] * 100 for p in frontier_pts],
                                mode="lines+markers",
                                name="有效前沿",
                                line=dict(color="#3B82F6", width=2),
                                marker=dict(size=3),
                            ))
                            # 最大 Sharpe 点
                            if max_s:
                                fig_ef.add_trace(go.Scatter(
                                    x=[max_s["volatility"] * 100],
                                    y=[max_s["return"] * 100],
                                    mode="markers",
                                    name="最大Sharpe",
                                    marker=dict(color="#EF4444", size=14, symbol="diamond"),
                                ))
                            # 最小波动点
                            if min_v:
                                fig_ef.add_trace(go.Scatter(
                                    x=[min_v["volatility"] * 100],
                                    y=[min_v["return"] * 100],
                                    mode="markers",
                                    name="最小波动",
                                    marker=dict(color="#10B981", size=14, symbol="circle"),
                                ))
                            # 当前配置点
                            cur_ret = comp["current"]["annualized_return"] * 100
                            cur_vol = comp["current"]["annualized_volatility"] * 100
                            fig_ef.add_trace(go.Scatter(
                                x=[cur_vol], y=[cur_ret],
                                mode="markers",
                                name="当前配置",
                                marker=dict(color="#F59E0B", size=14, symbol="star"),
                            ))

                            fig_ef.update_layout(
                                height=450,
                                xaxis_title="年化波动率 (%)",
                                yaxis_title="年化收益率 (%)",
                                margin=dict(l=10, r=10, t=10, b=10),
                            )
                            st.plotly_chart(fig_ef, use_container_width=True)

                            st.caption(
                                "💡 **最大Sharpe** = 风险调整后最优 · "
                                "**最小波动** = 最保守配置 · "
                                "**当前配置** = 你现在的持仓权重"
                            )
                    else:
                        st.info("👆 点击「计算有效前沿」开始优化分析")


if __name__ == "__main__":
    main()
