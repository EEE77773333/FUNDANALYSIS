"""
主题资金流雷达 — 页面 28
==========================
连续流入天数 / 排名跃升 / 背离 / 代表基金 / 组合暴露 /
热力日历 / 板块穿透 / 时段对比 / AI 短评 / 观察池 / 导出分享。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    show_sortable_df,
    section_header,
    compact_fig,
    fin_callout,
    kpi_strip,
)
from core.theme_flow import (
    get_theme_flow_engine,
    themes_to_dataframe,
    sectors_to_dataframe,
    load_theme_trend,
)
from core.theme_taxonomy import (
    theme_sector_map,
    load_taxonomy,
    get_theme_representatives,
    reload_taxonomy,
)
from core.theme_brief import (
    generate_theme_brief,
    generate_top5_five_lines,
    generate_top5_ai_brief,
)
from core.theme_radar_insights import (
    compute_streaks,
    find_divergences,
    build_heat_matrix,
    session_compare_today,
    theme_sector_breakdown,
    portfolio_theme_exposure,
    watchlist_in_topn,
)
from core.portfolio import get_portfolio_manager
from core.user_workspace import get_prefs, save_prefs, touch_recent

WATCH_TOP_N = 5

render_page_header(
    title="主题资金流雷达",
    icon="🌊",
    description="主题归并资金流 + 连续流入/排名跃升/背离/组合暴露/热力/时段/观察池与导出分享。",
    help_text="""
    **数据来源：** AKShare 行业/概念主力资金流（东财）
    **主题归并：** `data/theme_taxonomy.yaml`
    **说明：** 资金数据为盘中快照，仅供参考，不构成投资建议。
    """,
    accent_color="#0EA5E9",
    group="market",
)

render_sidebar_config(show_ai_config=True)
render_top_toolbar(show_ai_config=True)
reload_taxonomy()


def _goto_famas(code: str, name: str = "") -> None:
    code = (code or "").strip()
    if not code:
        return
    touch_recent("fund", code, name or code)
    st.session_state["famas_fund_code_prefills"] = code
    st.query_params["fund"] = code
    # 必须传页面对象：传路径字符串会抛 StreamlitPageNotFoundError 导致跳转无声失败
    from core.nav_catalog import safe_switch_page
    safe_switch_page("pages/08_FAMAS单基金深度分析.py")


if "theme_flow_data" not in st.session_state:
    st.session_state["theme_flow_data"] = None

c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    save_snap = st.checkbox("保存快照", value=True)
with c2:
    if st.button("刷新资金流", type="primary", use_container_width=True):
        with st.spinner("拉取主题资金流..."):
            st.session_state["theme_flow_data"] = get_theme_flow_engine().fetch(save=save_snap)

if st.session_state.get("theme_flow_data") is None:
    with st.spinner("首次加载…"):
        st.session_state["theme_flow_data"] = get_theme_flow_engine().fetch(save=save_snap)

with c3:
    data = st.session_state.get("theme_flow_data")
    if data:
        src = data.get("source", "")
        src_label = "AKShare/东财" if src == "akshare" else src
        st.markdown(
            f'<div class="fin-toolbar"><div class="fin-toolbar-meta">'
            f'🕐 {data["updated_at"]}'
            + (f" · {src_label}" if src_label else "")
            + (" · 快照已存" if data.get("snapshot_path") else "")
            + "</div></div>",
            unsafe_allow_html=True,
        )

if not data:
    st.info("👆 数据加载中或拉取失败，请点击「刷新主题资金流」重试")
    st.stop()

themes = data["themes"]
sectors = data["sectors"]
rank_moves = data.get("rank_moves") or []
theme_df = themes_to_dataframe(themes)
sector_df = sectors_to_dataframe(sectors)
streaks = compute_streaks(themes)
divs = find_divergences(themes)

if not data.get("fetch_ok"):
    st.warning("未能拉取板块资金流。请确认已安装 AKShare 且网络可访问东财数据源，然后重试。")
    st.stop()

# 增强主题表：连续天数 + 排名变动
move_map = {m["theme"]: m for m in rank_moves}
enrich_rows = []
for _, r in theme_df.iterrows():
    th = r["主题"]
    st_info = streaks.get(th) or {}
    mv = move_map.get(th) or {}
    delta = mv.get("delta")
    if st_info.get("direction") == "in":
        streak_label = f"连流入{st_info.get('in_days', 0)}日"
    elif st_info.get("direction") == "out":
        streak_label = f"连流出{st_info.get('out_days', 0)}日"
    else:
        streak_label = "—"
    enrich_rows.append({
        **r.to_dict(),
        "连续天数": streak_label,
        "当前排名": mv.get("curr_rank"),
        "上次排名": mv.get("prev_rank"),
        "排名变动": delta,
    })
enrich_df = pd.DataFrame(enrich_rows)

# 观察池 TopN 提醒
prefs = get_prefs().get("prefs") or {}
watch_themes = list(prefs.get("theme_watchlist") or [])
watch_hits = watchlist_in_topn(themes, watch_themes, top_n=WATCH_TOP_N)
if watch_hits:
    names = "、".join(f"{h['theme']}(#{h['rank']})" for h in watch_hits)
    fin_callout(f"观察池主题进入净流入 Top{WATCH_TOP_N}：<b>{names}</b>", "warn")

# 顶部摘要 KPI
if themes:
    top_t = themes[0]
    bot_t = min(themes, key=lambda x: x.net_inflow_yi)
    jumps = [m for m in rank_moves if m.get("delta") is not None and abs(m["delta"]) >= 3]
    kpi_strip([
        {"label": "主题数", "value": str(len(themes))},
        {"label": "最大流入", "value": f"{top_t.net_inflow_yi:+.1f}亿", "delta": top_t.theme, "tone": "up"},
        {"label": "最大流出", "value": f"{bot_t.net_inflow_yi:+.1f}亿", "delta": bot_t.theme, "tone": "down"},
        {"label": "大幅跃升≥3", "value": str(len(jumps))},
    ])

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🎯 主题雷达",
    "⚡ 背离·时段",
    "📅 热力日历",
    "💼 组合暴露",
    "👀 观察池·代表",
    "🔥 盘中热点",
    "📤 简报·导出",
])

with tab1:
    section_header("资金雷达", "红涨绿跌 · 含连续天数/排名")
    if enrich_df.empty:
        st.info("暂无主题数据")
    else:
        fig = px.bar(
            enrich_df.head(15),
            x="主力净流入(亿)",
            y="主题",
            orientation="h",
            color="平均涨跌幅%",
            color_continuous_scale=[[0, "#16A34A"], [0.5, "#F1F5F9"], [1, "#DC2626"]],
            color_continuous_midpoint=0,
            hover_data=["连续天数", "排名变动"],
        )
        compact_fig(fig, height=440, title="主题主力净流入（亿）")

    style_df = enrich_df.copy()
    if watch_themes:
        style_df.insert(0, "观察", style_df["主题"].apply(lambda x: "★" if x in watch_themes else ""))
    show_sortable_df(style_df)

    section_header("行业 ↔ 概念穿透")
    drill = st.selectbox("选择主题", enrich_df["主题"].tolist(), key="theme_drill", label_visibility="collapsed")
    br = theme_sector_breakdown(drill, sectors)
    if br.empty:
        st.caption("该主题暂无命中板块")
    else:
        c_a, c_b = st.columns([1.2, 1])
        with c_a:
            fig = px.bar(
                br.head(12),
                x="主力净流入(亿)",
                y="板块名称",
                orientation="h",
                color="类型",
            )
            compact_fig(fig, height=340, title=f"{drill} · 流入构成")
        with c_b:
            show_sortable_df(br)

    reps = get_theme_representatives(drill)
    if reps:
        section_header("代表基金")
        cols = st.columns(len(reps))
        for i, rep in enumerate(reps):
            with cols[i]:
                kind = "指数" if rep["kind"] == "index" else "主动"
                if st.button(
                    f"{rep['code']} {rep['name']}（{kind}）",
                    key=f"rep_{drill}_{rep['code']}",
                    use_container_width=True,
                ):
                    _goto_famas(rep["code"], rep["name"])

with tab2:
    section_header("资金 vs 涨跌背离")
    col_a, col_b = st.columns(2)
    with col_a:
        st.caption("大流入 · 弱涨")
        iw = pd.DataFrame(divs.get("inflow_weak") or [])
        if iw.empty:
            st.caption("暂无")
        else:
            show_sortable_df(iw.rename(columns={
                "theme": "主题", "net_inflow_yi": "净流入(亿)",
                "change_pct": "涨跌%", "top_sector": "代表板块",
            }))
    with col_b:
        st.caption("大流出 · 抗跌")
        ow = pd.DataFrame(divs.get("outflow_resilient") or [])
        if ow.empty:
            st.caption("暂无")
        else:
            show_sortable_df(ow.rename(columns={
                "theme": "主题", "net_inflow_yi": "净流入(亿)",
                "change_pct": "涨跌%", "top_sector": "代表板块",
            }))

    section_header("排名跃升", "对齐预警 theme_flow_rank_jump")
    jump_df = pd.DataFrame(rank_moves)
    if jump_df.empty:
        st.caption("暂无排名对照（首次刷新建立基线）")
    else:
        jump_df = jump_df.rename(columns={
            "theme": "主题", "curr_rank": "当前", "prev_rank": "上次",
            "delta": "跃升幅度", "net_inflow_yi": "净流入(亿)", "change_pct": "涨跌%",
        })
        jump_show = jump_df.dropna(subset=["跃升幅度"]).sort_values("跃升幅度", ascending=False)
        show_sortable_df(jump_show)
        big = jump_show[jump_show["跃升幅度"].abs() >= 3]
        if not big.empty:
            st.markdown(
                '<div class="fin-meta">幅度≥3：'
                + "、".join(f"{r['主题']}({r['跃升幅度']:+.0f})" for _, r in big.head(8).iterrows())
                + "</div>",
                unsafe_allow_html=True,
            )

    section_header("早盘 / 午盘资金差")
    sess = session_compare_today()
    if not sess.get("ok"):
        reason = sess.get("reason")
        if reason == "need_both_sessions":
            fin_callout(
                f"需同日早盘与午盘快照。早盘 {sess.get('am_time') or '无'} · 午盘 {sess.get('pm_time') or '无'}。",
                "warn",
            )
        else:
            fin_callout("暂无时段数据。勾选保存快照并在早盘/午盘各刷新一次。", "warn")
    else:
        st.markdown(
            f'<div class="fin-meta">早盘 {sess["am_time"]} · 午盘 {sess["pm_time"]}</div>',
            unsafe_allow_html=True,
        )
        sdf = pd.DataFrame(sess["rows"])
        show_sortable_df(sdf)
        fig = px.bar(
            sdf.head(12),
            x="午-早差(亿)",
            y="主题",
            orientation="h",
            color="午-早差(亿)",
            color_continuous_scale=[[0, "#16A34A"], [0.5, "#F1F5F9"], [1, "#DC2626"]],
            color_continuous_midpoint=0,
        )
        compact_fig(fig, height=320, title="午盘相对早盘净流入变化")

with tab3:
    section_header("热力日历")
    horizon = st.radio("热力窗口", ["近一周", "近一月"], horizontal=True, key="heat_horizon")
    days = 7 if horizon == "近一周" else 22
    heat = build_heat_matrix(days=days)
    if heat.empty:
        fin_callout("快照不足，开启保存并多日刷新后可见热力。", "warn")
    else:
        plot_df = heat.copy()
        fig = px.imshow(
            plot_df,
            aspect="auto",
            color_continuous_scale=[[0, "#16A34A"], [0.5, "#F8FAFC"], [1, "#DC2626"]],
            color_continuous_midpoint=0,
            labels=dict(x="日期", y="主题", color="净流入(亿)"),
        )
        compact_fig(fig, height=400, title=f"主题资金热力（{horizon}·日终）")
        show_sortable_df(plot_df.reset_index().rename(columns={"theme": "主题"}))

    section_header("单主题折线")
    sel_theme = st.selectbox("选择主题", theme_df["主题"].tolist(), key="trend_theme", label_visibility="collapsed")
    trend = load_theme_trend(sel_theme, days=10)
    if trend.empty:
        st.caption("暂无该主题历史折线")
    else:
        xcol = "datetime" if "datetime" in trend.columns else "date"
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=trend[xcol], y=trend["net_inflow_yi"],
            mode="lines+markers", name="主力净流入(亿)",
            line=dict(color="#2563EB", width=1.6),
        ))
        compact_fig(fig, height=280, title=f"{sel_theme} · 资金流趋势")

with tab4:
    section_header("持仓主题暴露", "权重 vs 今日净流入")
    pm = get_portfolio_manager()
    portfolios = pm.list_all()
    fund_rows = []
    if portfolios:
        pid = st.selectbox(
            "选择组合",
            [p.id for p in portfolios],
            format_func=lambda i: next(p.name for p in portfolios if p.id == i),
        )
        holdings = pm.get_holdings_df(pid)
        if not holdings.empty:
            for _, row in holdings.iterrows():
                fund_rows.append({
                    "code": row["fund_code"],
                    "name": row.get("fund_name", row["fund_code"]),
                    "weight": row.get("weight", 0),
                    "amount": row.get("amount", 0),
                })
    extra = st.text_area("额外基金代码（每行一个）", height=80, placeholder="000001\n110011")
    if extra.strip():
        from core.data_fetcher import get_fetcher
        fetcher = get_fetcher()
        for c in extra.strip().splitlines():
            code = c.strip().zfill(6)
            if len(code) == 6 and code.isdigit():
                info = fetcher.get_fund_manager_info(code)
                fund_rows.append({
                    "code": code,
                    "name": info.get("基金名称", code) if info else code,
                    "weight": 0,
                    "amount": 0,
                })

    if not fund_rows:
        st.info("请选择组合或输入基金代码")
    else:
        expo = portfolio_theme_exposure(fund_rows, themes)
        show_sortable_df(expo)
        plot = expo[expo["主题"] != "未匹配"].head(12)
        if not plot.empty:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                name="持仓权重%", x=plot["主题"], y=plot["持仓权重%"],
                marker_color="#64748B",
            ))
            fig.add_trace(go.Bar(
                name="净流入(亿)", x=plot["主题"], y=plot["今日净流入(亿)"],
                marker_color="#2563EB", yaxis="y2",
            ))
            fig.update_layout(
                yaxis=dict(title="持仓%"),
                yaxis2=dict(title="亿", overlaying="y", side="right"),
                barmode="group",
            )
            compact_fig(fig, height=320, title="暴露 vs 资金流")

with tab5:
    section_header("观察池", f"进入 Top{WATCH_TOP_N} 高亮")
    all_theme_names = list(load_taxonomy().keys())
    selected = st.multiselect(
        f"关注主题（进入净流入 Top{WATCH_TOP_N} 将高亮提醒）",
        all_theme_names,
        default=[t for t in watch_themes if t in all_theme_names],
        key="theme_watch_multi",
    )
    if st.button("保存观察池", key="save_theme_watch"):
        save_prefs(prefs_patch={"theme_watchlist": selected})
        st.toast("观察池已保存", icon="👀")
        st.rerun()

    if watch_hits:
        st.success("当前命中 Top{}：".format(WATCH_TOP_N))
        show_sortable_df(pd.DataFrame(watch_hits).rename(columns={
            "theme": "主题", "rank": "排名",
            "net_inflow_yi": "净流入(亿)", "change_pct": "涨跌%",
        }))

    section_header("占优主题代表基金")
    top_themes = [t.theme for t in themes[:5]]
    for th in top_themes:
        reps = get_theme_representatives(th)
        st.markdown(f"**{th}**")
        if not reps:
            st.caption("未配置代表基金")
            continue
        cols = st.columns(len(reps))
        for i, rep in enumerate(reps):
            with cols[i]:
                kind = "指数" if rep["kind"] == "index" else "主动"
                label = f"{rep['code']} {rep['name']}（{kind}）"
                if st.button(label, key=f"top_rep_{th}_{rep['code']}", use_container_width=True):
                    _goto_famas(rep["code"], rep["name"])

with tab6:
    section_header("盘中板块热点")
    col_a, col_b = st.columns(2)
    with col_a:
        st.caption("净流入 Top10")
        if sector_df.empty:
            st.info("暂无板块数据")
        else:
            top = sector_df.nlargest(10, "主力净流入(亿)")
            fig = px.bar(
                top, x="主力净流入(亿)", y="板块名称", orientation="h",
                color="涨跌幅%", color_continuous_scale=["#16A34A", "#DC2626"],
            )
            compact_fig(fig, height=320, title="流入 Top10")
    with col_b:
        st.caption("净流出 Top10")
        if sector_df.empty:
            st.info("暂无板块数据")
        else:
            bot = sector_df.nsmallest(10, "主力净流入(亿)")
            fig = px.bar(
                bot, x="主力净流入(亿)", y="板块名称", orientation="h",
                color="涨跌幅%", color_continuous_scale=["#16A34A", "#DC2626"],
            )
            compact_fig(fig, height=320, title="流出 Top10")

    section_header("归并审计")
    audit_rows = []
    for theme, sectors_list in theme_sector_map().items():
        audit_rows.append({
            "主题": theme,
            "配置板块数": len(sectors_list),
            "板块示例": "、".join(sectors_list[:5]),
        })
    show_sortable_df(pd.DataFrame(audit_rows))
    unmapped = sector_df[sector_df["映射主题"] == "其他"].head(20)
    st.caption("未归并板块抽样")
    show_sortable_df(unmapped[["板块名称", "主力净流入(亿)", "涨跌幅%"]])

with tab7:
    section_header("Top5 短评 / 导出分享")
    five = generate_top5_five_lines(themes, rank_moves=rank_moves, streaks=streaks)
    st.code(five, language=None)

    if st.button("✨ AI 生成 5 行短评", type="primary", key="theme_ai_brief"):
        with st.spinner("AI 撰写中…"):
            ai_text = generate_top5_ai_brief(themes, rank_moves=rank_moves, streaks=streaks)
            st.session_state["theme_ai_brief_text"] = ai_text
    if st.session_state.get("theme_ai_brief_text"):
        st.markdown(st.session_state["theme_ai_brief_text"])

    brief = generate_theme_brief(themes)
    st.download_button(
        "📥 导出 Markdown 简报",
        brief,
        file_name="theme_flow_brief.md",
        mime="text/markdown",
        use_container_width=True,
    )
    st.download_button(
        "📥 导出主题 CSV",
        enrich_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="theme_flow_today.csv",
        mime="text/csv",
        use_container_width=True,
    )

    section_header("只读分享")
    hours = st.slider("链接有效小时", 1, 168, 72, key="theme_share_hours")
    if st.button("🔗 生成只读分享链接", key="theme_share_btn"):
        from core.history import get_history_manager
        from core.share_links import create_share, share_url_path

        body = brief + "\n\n## Top5 短评\n\n" + five
        if st.session_state.get("theme_ai_brief_text"):
            body += "\n\n## AI 短评\n\n" + st.session_state["theme_ai_brief_text"]
        hid = get_history_manager().save(
            page_name="主题资金流雷达",
            fund_code="",
            fund_name="主题资金流",
            system_prompt="theme_flow_share",
            user_prompt=data.get("updated_at", ""),
            result_content=body,
            usage={},
            elapsed_seconds=0,
            model="theme-flow",
        )
        share = create_share(int(hid), hours=hours, title=f"主题资金流 · {data.get('updated_at', '')}")
        if share:
            path = share_url_path(share["token"])
            st.session_state["theme_share_path"] = path
            st.session_state["theme_share_exp"] = share["expires_at"]
            st.success(f"已生成：`{path}` · 失效 {share['expires_at']} UTC")
        else:
            st.error("分享创建失败")
    if st.session_state.get("theme_share_path"):
        st.code(st.session_state["theme_share_path"])
