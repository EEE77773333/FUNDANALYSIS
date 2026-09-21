"""
实时市场仪表盘 — 页面 13
=========================
广度 / 成交 / 风格 / 北南向 / 跨资产 / 估值 / 行业·概念 / 分时 / 持仓行业联动。
开市默认每 3 分钟自动刷新。
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    section_header,
    quote_strip,
    kpi_strip,
    compact_fig,
    fin_pill,
    fin_callout,
)
from core.market_dashboard import (
    MINUTE_INDEX_OPTIONS,
    fetch_dashboard_bundle,
    fetch_index_minute,
    is_cn_trading_session,
    market_session_label,
    now_cn,
)

render_page_header(
    "实时市场仪表盘",
    "📡",
    "指数 / 广度 / 成交 / 风格 / 北南向 / 跨资产 / 估值分位 / 行业·概念 / 分时 / 持仓行业联动。",
    "数据源：Sina / 腾讯 / 巨潮 · 开市默认每 3 分钟自动刷新",
    accent_color="#0EA5E9",
    group="market",
)

render_sidebar_config(show_ai_config=False)
render_top_toolbar()
st.sidebar.markdown("---")
st.sidebar.caption(f"🕐 {now_cn().strftime('%H:%M:%S')} · {market_session_label()}")

REFRESH_MINUTES = 3


def _bar_hot(df: pd.DataFrame, title: str) -> None:
    if df is None or df.empty:
        st.caption(f"{title}暂无数据")
        return
    fig = px.bar(
        df,
        x="change_pct",
        y="name",
        orientation="h",
        color="change_pct",
        color_continuous_scale=[[0, "#16A34A"], [0.5, "#F1F5F9"], [1, "#DC2626"]],
        color_continuous_midpoint=0,
        labels={"change_pct": "涨跌幅%", "name": ""},
    )
    compact_fig(fig, height=380, title=title)


def _render_bundle(data: dict) -> None:
    sess = data.get("session") or ""
    trading = bool(data.get("trading"))
    pill = fin_pill("交易中", "live") if trading else fin_pill(sess or "收盘", "closed")
    auto_txt = "自动刷新开" if trading else "手动刷新"
    st.markdown(
        f'<div class="fin-toolbar"><div class="fin-toolbar-meta">{pill} '
        f'更新 {data.get("updated_at")} · {auto_txt}</div></div>',
        unsafe_allow_html=True,
    )

    section_header("主要指数")
    idxs = data.get("indexes") or {}
    if idxs.get("_error"):
        st.caption(idxs["_error"])
    else:
        quote_strip(idxs)

    section_header("市场广度", "涨跌家数 · 涨停生态")
    breadth = data.get("breadth") or {}
    if breadth.get("_error"):
        st.warning(breadth["_error"])
    else:
        act = breadth.get("activity") or {}
        kpi_strip([
            {"label": "上涨", "value": str(act.get("up", "—")), "tone": "up"},
            {"label": "下跌", "value": str(act.get("down", "—")), "tone": "down"},
            {"label": "涨停", "value": str(breadth.get("limit_up_n", act.get("limit_up", "—")))},
            {"label": "跌停", "value": str(breadth.get("limit_down_n", act.get("limit_down", "—")))},
            {"label": "炸板", "value": str(breadth.get("zhaban_n", "—"))},
            {"label": "连板高度", "value": f"{breadth.get('max_lianban', 0)}板"},
        ])
        leaders = breadth.get("lianban_leaders") or []
        if leaders:
            st.markdown(
                '<div class="fin-meta">高度龙头：'
                + " · ".join(f"{x['name']}({x['lianban']}板/{x['industry']})" for x in leaders[:5])
                + "</div>",
                unsafe_allow_html=True,
            )
        if act.get("activity"):
            st.markdown(
                f'<div class="fin-meta">活跃度 {act.get("activity")} · {act.get("asof") or breadth.get("asof")}</div>',
                unsafe_allow_html=True,
            )

    section_header("两市成交额")
    turn = data.get("turnover") or {}
    if turn.get("_error"):
        st.warning(turn["_error"])
    else:
        yoy = turn.get("vs_yesterday_pct")
        a5 = turn.get("vs_avg5_pct")
        kpi_strip([
            {"label": "两市合计", "value": f"{turn.get('total_yi') or '—'}亿"},
            {
                "label": "较昨日",
                "value": f"{yoy:+.2f}%" if yoy is not None else "—",
                "delta": f"昨 {turn.get('prev_yi')}亿" if turn.get("prev_yi") else None,
                "tone": "up" if (yoy or 0) >= 0 else "down",
            },
            {
                "label": "较5日均",
                "value": f"{a5:+.2f}%" if a5 is not None else "—",
                "delta": f"均 {turn.get('avg5_yi')}亿" if turn.get("avg5_yi") else None,
                "tone": "up" if (a5 or 0) >= 0 else "down",
            },
            {"label": "沪 / 深", "value": f"{turn.get('sh_yi') or '—'} / {turn.get('sz_yi') or '—'}"},
        ])
        series = turn.get("series") or []
        if series:
            sdf = pd.DataFrame(series)
            fig = go.Figure(go.Bar(x=sdf["date"], y=sdf["total_yi"], marker_color="#2563EB"))
            compact_fig(fig, height=240, title="近几日两市成交额（亿）")

    mid1, mid2 = st.columns(2)
    with mid1:
        section_header("风格箱")
        style = data.get("style") or {}
        if style.get("_error"):
            st.warning(style["_error"])
        else:
            quote_strip(style)
    with mid2:
        section_header("跨资产")
        cross = data.get("cross") or {}
        if cross.get("_error"):
            st.warning(cross["_error"])
        else:
            cards = []
            for key in ("bond", "gold", "usdcny"):
                d = cross.get(key)
                if not d:
                    continue
                price = d["price"]
                fmt = f"{price:.4f}" if key == "usdcny" else f"{price:.2f}"
                chg = d["chg_pct"]
                cards.append({
                    "label": d["name"],
                    "value": fmt,
                    "delta": f"{chg:+.2f}%",
                    "tone": "up" if chg >= 0 else "down",
                })
            kpi_strip(cards)

    section_header("估值分位", "乐股 / 中证")
    pe_list = data.get("pe") or []
    if isinstance(pe_list, dict) and pe_list.get("_error"):
        st.warning(pe_list["_error"])
    elif pe_list:
        pe_kpis = []
        for item in pe_list:
            pe_pct = item.get("pe_pct")
            if pe_pct is None:
                lamp, tone = "—", "muted"
            elif pe_pct < 30:
                lamp, tone = "低估区", "down"
            elif pe_pct < 70:
                lamp, tone = "中位", "muted"
            else:
                lamp, tone = "偏高", "up"
            pe_kpis.append({
                "label": item["name"],
                "value": f"{pe_pct}%" if pe_pct is not None else "—",
                "delta": f"PE {item.get('pe')} · {lamp}",
                "tone": tone,
            })
        kpi_strip(pe_kpis)

    section_header("北向 / 南向")
    ns = data.get("north_south") or {}
    if ns.get("_error"):
        st.warning(ns["_error"])
    else:
        nn = float(ns.get("north_net_yi") or 0)
        sn = float(ns.get("south_net_yi") or 0)
        kpi_strip([
            {"label": "北向净流入", "value": f"{nn:+.2f}亿", "tone": "up" if nn >= 0 else "down"},
            {"label": "南向净流入", "value": f"{sn:+.2f}亿", "tone": "up" if sn >= 0 else "down"},
        ])
        if abs(nn) < 1e-9 and abs(sn) < 1e-9:
            fin_callout("北向/南向分时当前为 0，数据源可能暂停披露实时净流入。", "warn")
        c_a, c_b = st.columns(2)
        north_s = ns.get("north_series") or []
        south_s = ns.get("south_series") or []
        with c_a:
            if north_s:
                ndf = pd.DataFrame(north_s)
                fig = go.Figure(go.Scatter(
                    x=ndf["time"], y=ndf["value"], mode="lines",
                    line=dict(color="#DC2626", width=1.5),
                ))
                compact_fig(fig, height=250, title="北向分时（亿）")
        with c_b:
            if south_s:
                sdf = pd.DataFrame(south_s)
                fig = go.Figure(go.Scatter(
                    x=sdf["time"], y=sdf["value"], mode="lines",
                    line=dict(color="#2563EB", width=1.5),
                ))
                compact_fig(fig, height=250, title="南向分时（亿）")
        rows = ns.get("rows") or []
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=160)

    section_header("板块涨幅")
    t1, t2 = st.tabs(["行业", "概念"])
    with t1:
        ind = data.get("industry")
        if isinstance(ind, dict) and ind.get("_error"):
            st.warning(ind["_error"])
        else:
            _bar_hot(ind if isinstance(ind, pd.DataFrame) else pd.DataFrame(), "行业 Top / 跌幅 Top")
    with t2:
        concept = data.get("concept")
        if isinstance(concept, dict) and concept.get("_error"):
            st.warning(concept["_error"])
        else:
            _bar_hot(concept if isinstance(concept, pd.DataFrame) else pd.DataFrame(), "概念 Top / 跌幅 Top")

    section_header("盘中时间轴")
    labels = list(MINUTE_INDEX_OPTIONS.keys())
    choice = st.selectbox("指数", labels, index=0, key="mkt_min_idx", label_visibility="collapsed")
    symbol = MINUTE_INDEX_OPTIONS[choice]
    try:
        mdf = fetch_index_minute(symbol)
    except Exception as e:
        mdf = pd.DataFrame()
        st.warning(f"分时: {e}")
    if mdf is not None and not mdf.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=mdf["时间"], y=mdf["收盘"], name="点位",
            line=dict(color="#2563EB", width=1.6), yaxis="y1",
        ))
        fig.add_trace(go.Scatter(
            x=mdf["时间"], y=mdf["涨跌幅%"], name="相对开盘%",
            line=dict(color="#D97706", width=1.2, dash="dot"), yaxis="y2",
        ))
        fig.update_layout(
            yaxis=dict(title="点位"),
            yaxis2=dict(title="%", overlaying="y", side="right"),
        )
        compact_fig(fig, height=300, title=f"{choice} 分钟走势")
        last = mdf.iloc[-1]
        st.markdown(
            f'<div class="fin-meta">最新 {last["时间"]} · {float(last["收盘"]):.2f} · '
            f'较开盘 {float(last["涨跌幅%"]):+.2f}%</div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("分时暂无")

    section_header("持仓行业联动")
    ps = data.get("portfolio_sectors") or {}
    if ps.get("_error"):
        st.warning(ps["_error"])
    elif not ps.get("ok"):
        st.caption("暂无持仓行业暴露")
    else:
        st.markdown(
            f'<div class="fin-meta">组合「{ps.get("portfolio_name")}」重仓股行业 vs 今日板块</div>',
            unsafe_allow_html=True,
        )
        items = ps.get("items") or []
        if items:
            show = pd.DataFrame(items).rename(columns={
                "industry": "行业",
                "weight_pct": "持仓暴露%",
                "change_pct": "板块涨跌%",
            })
            st.dataframe(show, use_container_width=True, hide_index=True, height=220)
            labeled = [x for x in items if x.get("change_pct") is not None]
            if labeled:
                fig = px.bar(
                    pd.DataFrame(labeled),
                    x="change_pct",
                    y="industry",
                    orientation="h",
                    color="change_pct",
                    color_continuous_scale=[[0, "#16A34A"], [0.5, "#F1F5F9"], [1, "#DC2626"]],
                    color_continuous_midpoint=0,
                    labels={"change_pct": "涨跌幅%", "industry": ""},
                )
                compact_fig(fig, height=270, title="高暴露行业今日表现")


# ---- 控制条 + 自动刷新片段 ----
ctrl1, ctrl2, ctrl3 = st.columns([2, 1, 1])
with ctrl1:
    auto = st.toggle(
        f"开市自动刷新（每 {REFRESH_MINUTES} 分钟）",
        value=True,
        key="mkt_auto_refresh",
    )
with ctrl2:
    st.toggle("含持仓行业", value=True, key="mkt_include_portfolio")
with ctrl3:
    if st.button("立即刷新", type="primary", use_container_width=True):
        st.rerun()

run_every = timedelta(minutes=REFRESH_MINUTES) if (auto and is_cn_trading_session()) else None
if not is_cn_trading_session():
    fin_callout(
        f"当前为 <b>{market_session_label()}</b>，显示收盘/最近一帧；开市后每 {REFRESH_MINUTES} 分钟自动刷新。",
        "warn",
    )


@st.fragment(run_every=run_every)
def _dashboard_fragment():
    with st.spinner("拉取市场数据…"):
        data = fetch_dashboard_bundle(
            include_heavy=bool(st.session_state.get("mkt_include_portfolio", True))
        )
    _render_bundle(data)


_dashboard_fragment()
