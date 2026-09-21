"""
侧栏工作台组件：全局搜索、收藏、用量、最近访问。
"""

from __future__ import annotations

import re

import streamlit as st

from .user_workspace import (
    list_favorites,
    list_recent,
    remove_favorite,
    touch_recent,
    toggle_favorite,
)


PAGE_CATALOG = [
    ("pages/08_FAMAS单基金深度分析.py", "🔬 FAMAS 深度分析"),
    ("pages/09_持续监控预警.py", "🚨 持续监控"),
    ("pages/19_组合管理.py", "💼 我的组合"),
    ("pages/21_预警规则.py", "🔔 预警规则"),
    ("pages/10_基金排名精选.py", "🏆 排名精选"),
    ("pages/11_基金PK擂台.py", "⚔️ 基金 PK"),
    ("pages/22_分析历史.py", "📚 分析历史"),
    ("pages/27_盘中估值中心.py", "📡 盘中估值"),
    ("pages/28_主题资金流雷达.py", "🌊 主题资金"),
    ("pages/18_通知配置.py", "📨 通知配置"),
    ("pages/99_账户设置.py", "👤 账户设置"),
]


def _goto_famas(code: str, name: str = "") -> None:
    code = (code or "").strip()
    if not code:
        return
    touch_recent("fund", code, name or code)
    st.session_state["famas_fund_code_prefills"] = code
    st.query_params["fund"] = code
    # 必须传页面对象：传路径字符串会抛 StreamlitPageNotFoundError，跳转静默失效
    from core.nav_catalog import safe_switch_page
    safe_switch_page("pages/08_FAMAS单基金深度分析.py")


def render_quota_badge() -> None:
    try:
        user = st.session_state.get("user") or {}
        if not user:
            return
        from .user_repo import UserRepo
        from .middleware import QUOTA_MAP
        usage = UserRepo().get_usage(int(user["id"]))
        tier = usage.get("tier") or user.get("tier") or "free"
        used = int(usage.get("api_calls_today", 0) or 0)
        limit = int(
            QUOTA_MAP.get(tier, {}).get("ai_analysis")
            or usage.get("api_calls_limit", 0)
            or 0
        )
        if limit <= 0:
            st.caption(f"⚡ AI 今日 {used} 次")
            return
        pct = min(used / limit, 1.0) if limit else 0
        st.caption(f"⚡ AI 今日 {used}/{limit}")
        st.progress(pct)
        if pct >= 0.8:
            st.caption("⚠️ 接近今日限额")
    except Exception:
        pass


def render_global_search() -> None:
    with st.expander("🔎 快速搜索", expanded=False):
        q = st.text_input(
            "基金代码/名称",
            key="ws_global_search",
            placeholder="如 000001 或 新能源",
            label_visibility="collapsed",
        )
        action = st.selectbox(
            "打开方式",
            ["FAMAS 分析", "加入收藏", "持续监控页"],
            key="ws_search_action",
            label_visibility="collapsed",
        )
        if not q or not q.strip():
            st.caption("输入代码或名称后回车搜索")
            return
        kw = q.strip()
        # 纯 6 位代码直达
        if re.fullmatch(r"\d{6}", kw):
            if st.button(f"打开 {kw}", key="ws_open_code", use_container_width=True):
                if action == "加入收藏":
                    toggle_favorite(kw, "")
                    st.toast(f"已收藏 {kw}", icon="⭐")
                elif action == "持续监控页":
                    st.session_state["watch_prefill_code"] = kw
                    touch_recent("fund", kw, kw)
                    from core.nav_catalog import safe_switch_page
                    safe_switch_page("pages/09_持续监控预警.py")
                else:
                    _goto_famas(kw)
            return
        try:
            from .data_fetcher import get_fetcher
            df = get_fetcher().search_fund(kw)
            if df is None or df.empty:
                st.caption("无匹配基金")
                return
            show = df.head(8)
            for _, row in show.iterrows():
                code = str(row.get("基金代码", ""))
                name = str(row.get("基金简称", "") or "")
                label = f"{code} {name}".strip()
                if st.button(label, key=f"ws_hit_{code}", use_container_width=True):
                    if action == "加入收藏":
                        toggle_favorite(code, name)
                        st.toast(f"已收藏 {code}", icon="⭐")
                    elif action == "持续监控页":
                        st.session_state["watch_prefill_code"] = code
                        touch_recent("fund", code, name)
                        from core.nav_catalog import safe_switch_page
                        safe_switch_page("pages/09_持续监控预警.py")
                    else:
                        _goto_famas(code, name)
        except Exception as e:
            st.caption(f"搜索暂不可用：{str(e)[:60]}")


def render_favorites_panel() -> None:
    favs = list_favorites(12)
    with st.expander(f"⭐ 收藏 ({len(favs)})", expanded=False):
        if not favs:
            st.caption("搜索基金后可加入收藏")
            return
        for f in favs:
            code = f.get("fund_code", "")
            name = f.get("fund_name", "")
            c1, c2 = st.columns([4, 1])
            with c1:
                if st.button(f"{code}", key=f"fav_open_{code}", use_container_width=True):
                    _goto_famas(code, name)
            with c2:
                if st.button("×", key=f"fav_del_{code}"):
                    remove_favorite(code)
                    st.rerun()
            if name:
                st.caption(name)


def render_recent_panel() -> None:
    items = list_recent(limit=8)
    if not items:
        return
    with st.expander("🕘 最近", expanded=False):
        for it in items:
            kind = it.get("kind")
            key = it.get("ref_key", "")
            title = it.get("title") or key
            if kind == "fund":
                if st.button(f"📈 {key}", key=f"recent_f_{key}", use_container_width=True):
                    _goto_famas(key, title)
            elif kind == "page":
                label = next((lb for p, lb in PAGE_CATALOG if p == key), title)
                st.page_link(key, label=label, use_container_width=True)


def render_sidebar_workspace() -> None:
    """侧栏工作台入口（需已登录）。"""
    if not st.session_state.get("user"):
        return
    render_quota_badge()
    render_global_search()
    render_favorites_panel()
    render_recent_panel()


def _chg_color(pct: float) -> str:
    return "#DC2626" if pct >= 0 else "#16A34A"


def _load_live_bundle(force: bool = False) -> dict:
    """会话内缓存市场/持仓/监控摘要，点刷新或首次进入时重拉。"""
    from .workbench_live import (
        fetch_market_strip,
        fetch_portfolio_summary,
        fetch_watch_movers,
    )

    key = "wb_live_bundle"
    if force or key not in st.session_state:
        with st.spinner("刷新市场与持仓摘要…"):
            st.session_state[key] = {
                "market": fetch_market_strip(),
                "portfolio": fetch_portfolio_summary(),
                "watch": fetch_watch_movers(),
            }
    return st.session_state[key]


def _render_market_strip(data: dict) -> None:
    from .ui_components import section_header, quote_strip

    section_header("市场一览", "指数 · 主题资金快照")
    indexes = data.get("indexes") or {}
    if indexes:
        quote_strip(indexes)
    else:
        st.caption("指数行情暂不可用")

    theme_in = data.get("theme_in") or []
    theme_out = data.get("theme_out") or []
    bits = []
    for t in theme_in:
        bits.append(f"流入 <b>{t['theme']}</b> {t['net_inflow_yi']:+.1f}亿")
    for t in theme_out:
        if theme_in and t["theme"] == theme_in[0]["theme"]:
            continue
        bits.append(f"流出 <b>{t['theme']}</b> {t['net_inflow_yi']:+.1f}亿")
    asof = data.get("theme_asof") or ""
    if bits:
        meta = " · ".join(bits) + (f" · 快照 {asof}" if asof else "")
        st.markdown(f'<div class="fin-meta">{meta}</div>', unsafe_allow_html=True)
    else:
        st.caption("主题资金：打开雷达页刷新后显示")

    l1, l2 = st.columns(2)
    with l1:
        st.page_link("pages/13_实时市场仪表盘.py", label="市场仪表盘", icon="📡")
    with l2:
        st.page_link("pages/28_主题资金流雷达.py", label="主题资金", icon="🌊")


def _render_portfolio_summary(data: dict) -> None:
    from .ui_components import kpi_strip

    st.markdown('<div class="fin-panel-title">持仓摘要</div>', unsafe_allow_html=True)
    if not data.get("ok"):
        st.caption("暂无持仓")
        st.page_link("pages/19_组合管理.py", label="去组合管理", icon="💼")
        return

    port_pct = float(data.get("port_pct") or 0)
    tone = "up" if port_pct >= 0 else "down"
    kpi_strip([{
        "label": data["portfolio_name"],
        "value": f"{port_pct:+.2f}%",
        "delta": f"{data['estimated_n']}/{data['holding_n']} 只覆盖",
        "tone": tone,
    }])
    st.markdown(
        '<div class="fin-meta">权重加权 · 天天基金实时估算</div>',
        unsafe_allow_html=True,
    )

    gcol, lcol = st.columns(2)
    with gcol:
        st.caption("贡献")
        for g in data.get("gainers") or []:
            label = f"{g['code']} {g['name'][:6]} {g['pct']:+.2f}%"
            if st.button(label, key=f"wb_port_g_{g['code']}", use_container_width=True):
                _goto_famas(g["code"], g.get("name") or "")
    with lcol:
        st.caption("拖累")
        for lo in data.get("losers") or []:
            label = f"{lo['code']} {lo['name'][:6]} {lo['pct']:+.2f}%"
            if st.button(label, key=f"wb_port_l_{lo['code']}", use_container_width=True):
                _goto_famas(lo["code"], lo.get("name") or "")
    st.page_link("pages/19_组合管理.py", label="组合详情", icon="💼")


def _render_watch_movers(data: dict) -> None:
    st.markdown('<div class="fin-panel-title">监控异动</div>', unsafe_allow_html=True)
    if not data.get("ok"):
        st.caption("监控列表为空")
        st.page_link("pages/09_持续监控预警.py", label="去添加监控", icon="🚨")
        return

    movers = data.get("movers") or []
    if not movers:
        st.caption("暂无估值数据")
        return

    st.markdown(
        f'<div class="fin-meta">按涨跌幅绝对值 · 扫描 {data.get("total", 0)} 只</div>',
        unsafe_allow_html=True,
    )
    for m in movers:
        pct = float(m["pct"])
        tone = "fin-up" if pct >= 0 else "fin-down"
        label = f"{m['code']} {(m.get('name') or '')[:8]}".strip()
        c1, c2 = st.columns([4, 1])
        with c1:
            if st.button(label, key=f"wb_watch_{m['code']}", use_container_width=True):
                _goto_famas(m["code"], m.get("name") or "")
        with c2:
            st.markdown(
                f'<div style="text-align:right;padding-top:0.4rem;font-weight:700;" class="{tone}">{pct:+.2f}%</div>',
                unsafe_allow_html=True,
            )
    st.page_link("pages/09_持续监控预警.py", label="持续监控", icon="🚨")


def _render_workbench_live_panels() -> None:
    """市场一览 / 持仓摘要 / 监控异动。"""
    from .ui_components import section_header

    force = bool(st.session_state.pop("wb_live_force_refresh", False))
    top = st.columns([5, 1])
    with top[0]:
        section_header("实时看板", "会话缓存 · 点刷新重拉")
    with top[1]:
        if st.button("刷新", key="wb_live_refresh", use_container_width=True):
            st.session_state["wb_live_force_refresh"] = True
            st.rerun()

    bundle = _load_live_bundle(force=force)
    _render_market_strip(bundle["market"])
    left, right = st.columns(2)
    with left:
        _render_portfolio_summary(bundle["portfolio"])
    with right:
        _render_watch_movers(bundle["watch"])


def render_workbench_home() -> bool:
    """
    登录用户的个人工作台首页。
    Returns: True 表示已渲染工作台（调用方可跳过营销首页大部分内容）。
    """
    user = st.session_state.get("user")
    if not user:
        return False

    from .user_workspace import workbench_snapshot, get_prefs, save_prefs
    from .daily_digest import build_digest_text, send_digest, maybe_auto_digest
    from .ui_components import kpi_strip, fin_callout, section_header, fin_pill

    name = user.get("display_name") or user.get("email") or "用户"
    snap = workbench_snapshot()
    usage = snap.get("usage") or {}

    st.markdown(
        f'<div class="fin-wb-title">工作台 <span>{name}</span></div>',
        unsafe_allow_html=True,
    )

    limit = usage.get("api_calls_limit", 0) or 0
    used = usage.get("api_calls_today", 0) or 0
    unack = int(snap.get("unack_alerts", 0) or 0)
    kpi_strip([
        {"label": "组合", "value": str(snap.get("portfolio_count", 0)),
         "delta": f"持仓 {snap.get('holding_count', 0)}"},
        {"label": "监控", "value": str(snap.get("watch_count", 0))},
        {"label": "今日预警", "value": str(snap.get("today_alerts", 0)),
         "delta": f"未确认 {unack}", "tone": "up" if unack else "muted"},
        {"label": "分析历史", "value": str(snap.get("history_count", 0))},
        {"label": "AI 今日", "value": f"{used}/{limit}" if limit else str(used)},
    ])

    if unack:
        fin_callout(
            f"有 <b>{unack}</b> 条未确认预警，建议及时处理。",
            tone="warn",
        )
        st.page_link("pages/21_预警规则.py", label="打开预警历史", icon="🔔")

    _render_workbench_live_panels()

    section_header("快捷入口")
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        st.page_link("pages/19_组合管理.py", label="我的组合", icon="💼", use_container_width=True)
    with a2:
        st.page_link("pages/09_持续监控预警.py", label="监控预警", icon="🚨", use_container_width=True)
    with a3:
        st.page_link("pages/08_FAMAS单基金深度分析.py", label="FAMAS 分析", icon="🔬", use_container_width=True)
    with a4:
        st.page_link("pages/22_分析历史.py", label="分析历史", icon="📚", use_container_width=True)

    left, right = st.columns(2)
    with left:
        section_header("收藏")
        favs = snap.get("favorites") or []
        if not favs:
            st.caption("侧栏搜索基金后可加入收藏")
        else:
            for f in favs:
                code = f.get("fund_code", "")
                label = f"{code} {f.get('fund_name') or ''}".strip()
                if st.button(label, key=f"wb_fav_{code}", use_container_width=True):
                    _goto_famas(code, f.get("fund_name") or "")
    with right:
        section_header("最近基金")
        recent = snap.get("recent_funds") or []
        if not recent:
            st.caption("分析或搜索后会出现在这里")
        else:
            for r in recent:
                code = r.get("ref_key", "")
                label = f"{code} {r.get('title') or ''}".strip()
                if st.button(label, key=f"wb_recent_{code}", use_container_width=True):
                    _goto_famas(code, r.get("title") or "")

    section_header("每日简报")
    prefs = get_prefs().get("prefs") or {}
    auto_on = prefs.get("digest_auto", True)
    col_d1, col_d2, col_d3 = st.columns([2, 1, 1])
    with col_d1:
        last = prefs.get("digest_last_sent") or "尚未发送"
        st.markdown(
            f'<div class="fin-meta">上次发送：{last} · 自动推送需通知通道且北京时间 15:05 后 '
            f'{fin_pill("自动" if auto_on else "手动", "live" if auto_on else "")}</div>',
            unsafe_allow_html=True,
        )
    with col_d2:
        new_auto = st.toggle("自动推送", value=auto_on, key="wb_digest_auto")
        if new_auto != auto_on:
            save_prefs(prefs_patch={"digest_auto": new_auto})
    with col_d3:
        if st.button("立即发送", key="wb_digest_send", use_container_width=True):
            res = send_digest(display_name=name, force=True)
            if res.get("ok"):
                st.toast(f"已推送到 {res.get('channels')} 个通道", icon="📬")
            else:
                st.toast(res.get("reason") or "发送失败", icon="⚠️")

    with st.expander("预览今日简报", expanded=False):
        title, body = build_digest_text(name)
        st.markdown(f"**{title}**")
        st.markdown(body)

    if "digest_bootstrapped" not in st.session_state:
        st.session_state["digest_bootstrapped"] = True
        try:
            maybe_auto_digest(display_name=name)
        except Exception:
            pass

    return True


def track_current_page(page_path: str, title: str = "") -> None:
    try:
        if st.session_state.get("user"):
            touch_recent("page", page_path, title or page_path)
    except Exception:
        pass
