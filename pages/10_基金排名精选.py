"""
基金排名精选 · Top 10 — 页面 10
================================
天天基金实时排名 + 11 项专业量化过滤 + AI 精选 Top 10。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from core.config import config
from core.data_fetcher import get_fetcher
from core.ai_analyzer import get_analyzer
from core.utils import (
    safe_float, calc_max_drawdown, calc_annualized_return,
    calc_sharpe_ratio, calc_annual_volatility, calc_sortino_ratio,
)
from core.ui_components import (
    render_page_header, render_sidebar_config, render_top_toolbar, render_analysis_button,
    show_token_usage, show_elapsed_time, show_error, show_info_box, show_warning_box,
    show_next_steps,
    check_api_ready, run_analysis_stream,
    section_header,
)

render_page_header(
    title="基金排名精选 · Top 10", icon="🏆",
    description="天天基金实时排名 + **11 项专业量化指标过滤** + AI 精选。层层筛选，优中选优。",
    help_text="**11 项过滤：** 性价比 | 主动能力 | 极端风险 | 净值波动 | 下行风险 | 业绩胜率 | 长期业绩 | 规模健康度 | 持仓集中度 | 经理经验 | 费率成本",
)

sidebar_config = render_sidebar_config()
render_top_toolbar()
fetcher = get_fetcher()
import akshare as ak

# ============================================================
# 侧边栏 — 筛选配置
# ============================================================
with st.expander("🎚️ 基础配置", expanded=True):
    rank_symbol = st.selectbox("基金类型", ["全部", "股票型", "混合型", "指数型", "QDII"], index=1)
    top_n_pool = st.slider("候选池（从天天基金排名取前N）", 30, 200, 100, 10)

with st.expander("📏 量化过滤 & 评分权重", expanded=False):
    c1, c2, c3 = st.columns(3)

    with c1:
        st.caption("📊 性价比"); filter_efficiency = st.checkbox("启用", value=True, key="f1"); min_efficiency = st.slider("超额/波动≥", 0.0, 2.0, 1.0, 0.1, key="f1v")
        st.caption("🎯 主动能力"); filter_active = st.checkbox("启用", value=True, key="f2"); min_active = st.slider("超额/跟踪误差≥", 0.0, 1.5, 0.5, 0.1, key="f2v")
        st.caption("📉 极端风险"); filter_drawdown = st.checkbox("启用", value=True, key="f3"); max_drawdown_pct = st.slider("最大回撤≤%", 5, 40, 25, 1, key="f3v")
        st.caption("〰️ 净值波动"); filter_vol = st.checkbox("启用", value=False, key="f4"); max_vol_pct = st.slider("波动率<%", 0, 60, 0, 5, key="f4v")

    with c2:
        st.caption("🛡️ 下行风险"); filter_sortino = st.checkbox("启用", value=True, key="f5"); min_sortino = st.slider("Sortino≥", 0.0, 3.0, 1.2, 0.1, key="f5v")
        st.caption("🎲 业绩胜率"); filter_winrate = st.checkbox("启用", value=True, key="f6"); min_winrate = st.slider("月度胜率≥", 0.40, 0.80, 0.60, 0.05, key="f6v")
        st.caption("📈 长期业绩"); filter_return = st.checkbox("启用", value=True, key="f7"); min_excess_pct = st.slider("3年超额≥%", 0, 20, 5, 1, key="f7v")
        st.caption("🏋️ 规模健康度"); filter_scale = st.checkbox("启用", value=True, key="f8"); scale_min = st.number_input("下限(亿)", 1, 50, 20, key="f8min"); scale_max = st.number_input("上限(亿)", 30, 300, 100, key="f8max")

    with c3:
        st.caption("🧩 持仓集中度"); filter_conc = st.checkbox("启用", value=True, key="f9"); max_conc = st.slider("集中度≤", 30, 80, 50, 5, key="f9v")
        st.caption("👤 经理经验"); filter_manager = st.checkbox("启用", value=True, key="f10"); min_manager_yr = st.slider("年限≥", 1.0, 10.0, 3.0, 0.5, key="f10v")
        st.caption("💰 费率成本"); filter_fee = st.checkbox("启用", value=True, key="f11"); max_fee_pct = st.slider("费率<%", 0.5, 3.0, 1.5, 0.1, key="f11v")
        st.caption("⚖️ 评分权重")
        w_short = st.slider("短期%", 0, 40, 20, 5, key="ws") / 100
        w_mid = st.slider("中期%", 0, 50, 35, 5, key="wm") / 100
        w_long = st.slider("长期%", 0, 50, 35, 5, key="wl") / 100
        w_risk = st.slider("风险%", 0, 30, 10, 5, key="wr") / 100

total_w = w_short + w_mid + w_long + w_risk
w_short, w_mid, w_long, w_risk = w_short/total_w, w_mid/total_w, w_long/total_w, w_risk/total_w
st.caption(f"归一化: 短期{w_short:.0%} 中期{w_mid:.0%} 长期{w_long:.0%} 风险{w_risk:.0%}")

# ============================================================
# Step 1: 获取天天基金排名
# ============================================================
section_header("Step 1 — 获取天天基金排名")
if st.button("📡 获取排名数据", use_container_width=True, type="primary"):
    with st.spinner(f"获取「{rank_symbol}」排名前{top_n_pool}..."):
        try:
            df = ak.fund_open_fund_rank_em(symbol=rank_symbol)
            df = df.head(top_n_pool).copy()
            df["基金代码"] = df["基金代码"].astype(str).str.zfill(6)
            for col in ["日增长率","近1周","近1月","近3月","近6月","近1年","近2年","近3年","今年来","成立来"]:
                if col in df.columns: df[col] = df[col].apply(safe_float)
            if "手续费" in df.columns: df["手续费_pct"] = df["手续费"].str.rstrip("%").apply(safe_float)
            st.session_state["rank_raw"] = df
            st.session_state["step1_done"] = True
            st.success(f"✅ {len(df)} 只（{rank_symbol}）")
        except Exception as e:
            show_error(str(e)[:200]); st.stop()

if st.session_state.get("step1_done"):
    with st.expander("📊 排名原始数据", expanded=False):
        cols = ["序号","基金代码","基金简称","近1月","近3月","近6月","近1年","近3年","手续费"]
        st.dataframe(st.session_state["rank_raw"][[c for c in cols if c in st.session_state["rank_raw"].columns]],
                     use_container_width=True, hide_index=True, height=300)

st.markdown("---")

# ============================================================
# Step 2: 获取详细数据 + 计算量化指标 + 硬性过滤
# ============================================================
if st.session_state.get("step1_done"):
    section_header("Step 2 — 量化指标计算 & 11 项过滤")

    if st.button("📐 计算指标并过滤", use_container_width=True, type="primary"):
        rank_df = st.session_state["rank_raw"]
        results, stats = [], {f"f{i}": 0 for i in range(1, 12)}
        stats["no_nav"] = 0
        stats["total"] = len(rank_df)

        # 评估用的基准年化（近似沪深300近3年）
        BENCHMARK_ANNUAL = 0.02  # 2%

        progress = st.progress(0)
        status = st.empty()

        for idx, (_, row) in enumerate(rank_df.iterrows()):
            code = str(row["基金代码"])
            status.text(f"分析 {code} {row.get('基金简称','')}...")

            # 获取净值
            nav = fetcher.get_fund_nav_history(code, years=3)
            if nav.empty or len(nav) < 120:
                stats["no_nav"] += 1
                progress.progress((idx+1)/len(rank_df))
                continue

            nav_s = nav.sort_values("日期", ascending=True)["单位净值"].dropna()
            rets = nav_s.pct_change().dropna()
            if len(nav_s) < 244 or len(rets) < 200:
                stats["no_nav"] += 1
                progress.progress((idx+1)/len(rank_df))
                continue

            # 计算核心指标
            ann_ret = calc_annualized_return(nav_s)
            ann_vol = calc_annual_volatility(rets)
            max_dd = calc_max_drawdown(nav_s)
            sharpe = calc_sharpe_ratio(rets)
            sortino = calc_sortino_ratio(rets)
            # 超额收益
            excess = ann_ret - BENCHMARK_ANNUAL
            # 跟踪误差≈波动率（简化, 实际需与基准回归）
            tracking_err = ann_vol * 0.7  # 近似

            # 月度胜率（用20交易日≈1个月近似）
            monthly_rets = nav_s.pct_change(20).dropna()
            if len(monthly_rets) >= 24:
                win_rate = (monthly_rets > 0).sum() / len(monthly_rets)
            else:
                win_rate = 0.5

            # 获取基金详情
            info = fetcher.get_fund_manager_info(code)
            holdings = fetcher.get_fund_holdings(code)

            # 规模
            size_str = info.get("最新规模", "") if info else ""
            scale_val = 0
            if size_str:
                import re
                m = re.search(r'([\d.]+)', str(size_str))
                if m: scale_val = safe_float(m.group(1))

            # 持仓集中度
            conc = 0
            if holdings is not None and not holdings.empty and "占净值比例%" in holdings.columns:
                conc = holdings["占净值比例%"].sum() / 100

            # 经理年限
            mgr_tenure = 0
            if info and info.get("从业年限"):
                mgr_tenure = safe_float(str(info["从业年限"]).replace("年",""))

            # 费率
            fee = 0
            if info:
                fee = safe_float(info.get("管理费率%", 0)) + safe_float(info.get("托管费率%", 0))

            # === 应用 11 项过滤 ===
            skipped = False

            # 1. 性价比: 超额/波动率 >= min
            efficiency = excess / ann_vol if ann_vol > 0 else 0
            if filter_efficiency and efficiency < min_efficiency:
                stats["f1"] += 1; skipped = True

            # 2. 主动能力: 超额/跟踪误差 >= min
            active_ratio = excess / tracking_err if tracking_err > 0 else 0
            if filter_active and active_ratio < min_active:
                stats["f2"] += 1; skipped = True

            # 3. 极端风险: 回撤 <= max
            if filter_drawdown and abs(max_dd) > max_drawdown_pct / 100:
                stats["f3"] += 1; skipped = True

            # 4. 净值波动
            vol_threshold = max_vol_pct / 100 if max_vol_pct > 0 else 0.35
            if filter_vol and ann_vol > vol_threshold:
                stats["f4"] += 1; skipped = True

            # 5. 下行风险
            if filter_sortino and sortino < min_sortino:
                stats["f5"] += 1; skipped = True

            # 6. 胜率
            if filter_winrate and win_rate < min_winrate:
                stats["f6"] += 1; skipped = True

            # 7. 长期业绩
            if filter_return and excess < min_excess_pct / 100:
                stats["f7"] += 1; skipped = True

            # 8. 规模
            if filter_scale and scale_val > 0:
                if scale_val < scale_min or scale_val > scale_max:
                    stats["f8"] += 1; skipped = True

            # 9. 集中度
            if filter_conc and conc > max_conc / 100:
                stats["f9"] += 1; skipped = True

            # 10. 经理
            if filter_manager and mgr_tenure > 0 and mgr_tenure < min_manager_yr:
                stats["f10"] += 1; skipped = True

            # 11. 费率
            if filter_fee and fee > 0 and fee > max_fee_pct:
                stats["f11"] += 1; skipped = True

            if not skipped:
                results.append({
                    "基金代码": code,
                    "基金简称": row.get("基金简称", ""),
                    "基金类型": row.get("基金类型", ""),
                    # 数值列保持为数字，展示格式交由 column_config，确保表头排序正确
                    "近1月": safe_float(row.get('近1月', 0)),
                    "近3月": safe_float(row.get('近3月', 0)),
                    "近1年": safe_float(row.get('近1年', 0)),
                    "近3年": safe_float(row.get('近3年', 0)),
                    "年化收益": ann_ret * 100,
                    "年化波动": ann_vol * 100,
                    "最大回撤": max_dd * 100,
                    "夏普比率": sharpe,
                    "索提诺": sortino,
                    "性价比": efficiency,
                    "胜率": win_rate * 100,
                    "规模(亿)": scale_val if scale_val else np.nan,
                    "集中度": conc * 100 if conc else np.nan,
                    "经理年限": mgr_tenure if mgr_tenure else np.nan,
                    "综合费率": fee if fee else np.nan,
                    "手续费": row.get("手续费", "N/A"),
                    "_ann_ret": ann_ret,
                    "_sharpe": sharpe,
                    "_sortino": sortino,
                    "_efficiency": efficiency,
                })

            progress.progress((idx+1)/len(rank_df))

        status.empty(); progress.empty()

        if results:
            df_out = pd.DataFrame(results)
            df_out["_score"] = df_out["_efficiency"] * 0.3 + df_out["_sharpe"] * 0.3 + df_out["_sortino"] * 0.2 + df_out["_ann_ret"] * 0.2
            df_out = df_out.sort_values("_score", ascending=False)

            # ---- 同类排名分位 ----
            n = len(df_out)
            if n >= 3:
                # 排名: 值越大越好 → 排名越小=越靠前（和 _score 排序一致）
                for col, label in [("_ann_ret", "年化排名"), ("_sharpe", "Sharpe排名"), ("_sortino", "Sortino排名")]:
                    # 按指标降序排名 (1=最优)
                    df_out[label] = df_out[col].rank(ascending=False, method="min").astype(int)
                # 综合排名分位: 权重加权排名
                df_out["综合排名分位"] = (
                    df_out["_ann_ret"].rank(ascending=False, pct=True) * 0.25 +
                    df_out["_sharpe"].rank(ascending=False, pct=True) * 0.35 +
                    df_out["_sortino"].rank(ascending=False, pct=True) * 0.25 +
                    df_out["_efficiency"].rank(ascending=False, pct=True) * 0.15
                )
                # 转为人类可读的排名标签
                def _rank_label(pct_val):
                    pct_int = int(round(pct_val * 100))
                    if pct_int <= 10:
                        return f"🏅 前{pct_int}%"
                    elif pct_int <= 25:
                        return f"前{pct_int}%"
                    else:
                        return f"前{pct_int}%"
                df_out["综合排名"] = df_out["综合排名分位"].apply(_rank_label)
                df_out.drop(columns=["综合排名分位"], inplace=True)

            df_out = df_out.drop(columns=["_ann_ret","_sharpe","_sortino","_efficiency","_score"])

            st.session_state["filtered_df"] = df_out
            st.session_state["filter_stats"] = stats
            st.session_state["step2_done"] = True

            # 过滤诊断
            active_filters = {
                "1.性价比": (filter_efficiency, stats["f1"]),
                "2.主动能力": (filter_active, stats["f2"]),
                "3.极端风险": (filter_drawdown, stats["f3"]),
                "4.净值波动": (filter_vol, stats["f4"]),
                "5.下行风险": (filter_sortino, stats["f5"]),
                "6.业绩胜率": (filter_winrate, stats["f6"]),
                "7.长期业绩": (filter_return, stats["f7"]),
                "8.规模健康度": (filter_scale, stats["f8"]),
                "9.持仓集中度": (filter_conc, stats["f9"]),
                "10.经理经验": (filter_manager, stats["f10"]),
                "11.费率成本": (filter_fee, stats["f11"]),
            }
            diag = " | ".join(f"{k}: {v}只" for k, (enabled, v) in active_filters.items() if enabled and v > 0)
            st.success(f"✅ {len(df_out)} 只通过 | 扫描{stats['total']}只 | 无净值{stats['no_nav']}只")
            if diag:
                st.caption(f"🔍 各过滤淘汰: {diag}")

            _num = st.column_config.NumberColumn
            rank_col_cfg = {
                "近1月": _num(format="%+.2f%%"),
                "近3月": _num(format="%+.2f%%"),
                "近1年": _num(format="%+.2f%%"),
                "近3年": _num(format="%+.2f%%"),
                "年化收益": _num(format="%.2f%%"),
                "年化波动": _num(format="%.2f%%"),
                "最大回撤": _num(format="%.2f%%"),
                "夏普比率": _num(format="%.2f"),
                "索提诺": _num(format="%.2f"),
                "性价比": _num(format="%.2f"),
                "胜率": _num(format="%.0f%%"),
                "规模(亿)": _num(format="%.1f"),
                "集中度": _num(format="%.0f%%"),
                "经理年限": _num(format="%.1f 年"),
                "综合费率": _num(format="%.2f%%"),
            }
            st.dataframe(df_out, use_container_width=True, hide_index=True, height=400,
                         column_config=rank_col_cfg)

            # 迷你趋势图：Top 5 近3月净值走势
            if len(df_out) >= 3:
                with st.expander("📈 Top 基金近3月净值趋势（迷你图）", expanded=False):
                    import plotly.graph_objects as go
                    top5_codes = df_out.head(5)["基金代码"].tolist()
                    fig = go.Figure()
                    colors = ["#DC2626","#3B82F6","#16A34A","#F59E0B","#8B5CF6"]
                    for i, code in enumerate(top5_codes):
                        nav = fetcher.get_fund_nav_history(str(code), years=1)
                        if not nav.empty and "日期" in nav.columns and "单位净值" in nav.columns:
                            nav_s = nav.sort_values("日期", ascending=True)
                            # 归一化：以起始日为100
                            base = nav_s["单位净值"].iloc[0]
                            if base > 0:
                                y = nav_s["单位净值"].apply(lambda x: x/base*100)
                                matched = df_out[df_out["基金代码"] == str(code)]["基金简称"]
                                name = matched.iloc[0] if len(matched) > 0 else str(code)
                                fig.add_trace(go.Scatter(x=pd.to_datetime(nav_s["日期"]), y=y,
                                    mode='lines', name=f"{name}", line=dict(color=colors[i%5], width=2)))
                    fig.update_layout(height=280, margin=dict(l=0,r=0,t=10,b=0),
                        xaxis_title="", yaxis_title="净值 (起始=100)",
                        hovermode='x unified', legend=dict(orientation='h', y=1.15))
                    st.plotly_chart(fig, use_container_width=True)
        else:
            show_error(f"扫描{stats['total']}只，全部被过滤。淘汰分布: { {k:v for k,v in stats.items() if isinstance(k,str) and v>0} }")

st.markdown("---")

# ============================================================
# Step 3: AI 精选 Top 10
# ============================================================
if st.session_state.get("step2_done"):
    section_header("Step 3 — AI 精选 Top 10")
    if not check_api_ready(): st.stop()

    analyze_clicked = render_analysis_button("🚀 AI 精选 Top 10", key="btn_ai")
    if analyze_clicked:
        df = st.session_state["filtered_df"]
        info_cols = [c for c in df.columns if not c.startswith("_")]
        candidates_text = df[info_cols].head(30).to_markdown(index=False, floatfmt=".2f")

        analyzer = get_analyzer()
        if sidebar_config.get("model"): analyzer._model = sidebar_config["model"]
        depth_map = {"简要": 4096, "标准": 8192, "深度": 12288, "极致": 16384}
        max_tokens = depth_map.get(sidebar_config.get("depth", "标准"), 8192)

        system_prompt = """你是资深基金投研分析师。从已通过11项量化过滤的候选池中精选**10只**最优基金。

原则：
① 各周期表现均衡，避免单周期暴增的"流星型"
② 量化指标优异（性价比>1.0优先，索提诺>1.2优先）
③ 分散不同投资风格和行业赛道
④ 关注费率合理性

输出格式（每只200-300字）：
## 🏆 精选 Top 10

### N. [基金简称] ([基金代码])
- **推荐理由**：...
- **量化亮点**：性价比X.XX | 夏普X.XX | 索提诺X.XX | 胜率XX%
- **适合投资者**：...
- **关注风险**：...

## 📋 组合配置建议
...

⚠️ 基于历史数据的适配度分析，不构成投资建议。"""

        user_prompt = f"从以下已通过{len(df)}只候选池中精选10只：\n\n{candidates_text}\n\n权重: 短期{w_short:.0%} 中期{w_mid:.0%} 长期{w_long:.0%} | 类型: {rank_symbol}"

        final_result = run_analysis_stream(
            analyzer, system_prompt, user_prompt,
            max_tokens=max_tokens, temperature=0.3,
            placeholder_label="🏆 精选报告",
            page_name="排名精选Top10",
        )
        if final_result and final_result.get("success"):
            show_elapsed_time(final_result.get("elapsed_seconds", 0))
            show_token_usage(final_result.get("usage", {}))
            st.markdown("---")
            show_next_steps([
                ("pages/08_FAMAS单基金深度分析.py", "深度分析", "🔬"),
                ("pages/11_基金PK擂台.py", "基金PK", "⚔️"),
                ("pages/19_组合管理.py", "加入组合", "💼"),
                ("pages/07_组合诊断优化.py", "组合诊断", "🩺"),
            ])

        show_info_box("⚖️ 以上基于天天基金公开排名 + 11项量化指标过滤 + AI分析，**不构成投资建议**。基金过往业绩不预示未来表现。")
