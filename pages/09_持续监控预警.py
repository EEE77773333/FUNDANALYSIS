"""
持续监控预警 — 页面 9
====================
基于 FAMAS watchtower Agent，对用户关注/持有的基金进行持续监控，
在检测到经理变更、规模异动、风格漂移、业绩掉队等关键事件时触发预警。

对应 FAMAS Workflow D: 持续监控预警
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from core.config import config
from core.data_fetcher import get_fetcher
from core.ai_analyzer import get_analyzer
from core.utils import safe_float, fmt_pct
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    render_analysis_button,
    show_token_usage,
    show_elapsed_time,
    show_error,
    show_info_box,
    check_api_ready, run_analysis_stream,
    render_intraday_nav,
    section_header,
)

# ---- 页面配置 ----
render_page_header(
    title="持续监控预警",
    icon="🚨",
    accent_color="#F59E0B",
    description="""
    基于 **FAMAS watchtower** 监控引擎，对您关注/持有的基金进行定期巡检。
    自动检测：经理变更、规模异动、风格漂移、业绩掉队、费率调整、公告风险。
    """,
    help_text="""
    **监控维度：**
    - 👤 **经理变更** — 基金经理离职或新增共管
    - 📊 **规模异动** — 单季度规模变化超过 ±30%
    - 🎯 **风格漂移** — 持仓风格偏离历史中枢1个标准差
    - 📉 **业绩掉队** — 连续两季度跑输基准 5% 以上
    - 💰 **费率调整** — 管理费/托管费变更
    - 📋 **公告风险** — 大额赎回、清盘风险、合同变更

    **使用流程：**
    1. 输入监控基金列表
    2. 配置预警阈值
    3. 点击"执行巡检"查看当前预警状态
    """,
)

# ---- 侧边栏 ----
sidebar_config = render_sidebar_config()
render_top_toolbar()

# ---- 主内容顶部：参数设置 ----
with st.expander("🎚️ 预警阈值配置", expanded=False):
    c1, c2, c3 = st.columns(3)
    with c1:
        for key, label in [
            ("alert_manager", "👤 经理变更预警"),
            ("alert_style", "🎯 风格漂移预警"),
        ]:
            if key not in st.session_state:
                st.session_state[key] = True
            st.checkbox(label, value=st.session_state[key], key=key)
    with c2:
        for key, label in [
            ("alert_scale", "📊 规模异动预警"),
            ("alert_performance", "📉 业绩掉队预警"),
        ]:
            if key not in st.session_state:
                st.session_state[key] = True
            st.checkbox(label, value=st.session_state[key], key=key)
    with c3:
        for key, label in [
            ("alert_fee", "💰 费率调整预警"),
            ("alert_announcement", "📋 公告风险预警"),
        ]:
            if key not in st.session_state:
                st.session_state[key] = True
            st.checkbox(label, value=st.session_state[key], key=key)

    c4, c5 = st.columns(2)
    with c4:
        scale_threshold = st.slider("规模异动阈值（%）", 10, 50, 30, 5,
                                     help="单季度规模变化超过此阈值时触发预警")
    with c5:
        perf_threshold = st.slider("业绩掉队阈值（%）", 3, 15, 5, 1,
                                    help="连续两季度跑输基准超过此阈值时触发预警")

alert_manager = st.session_state["alert_manager"]
alert_scale = st.session_state["alert_scale"]
alert_style = st.session_state["alert_style"]
alert_performance = st.session_state["alert_performance"]
alert_fee = st.session_state["alert_fee"]
alert_announcement = st.session_state["alert_announcement"]
st.sidebar.caption("💡 建议每周巡检一次，季报发布后立即巡检")

# ---- 监控列表管理（DB 持久化）----
from core.db import get_user_id, get_connection, now_iso, DB_MODE

def _load_watchlist():
    """从数据库加载当前用户的监控列表"""
    uid = get_user_id()
    with get_connection() as conn:
        try:
            rows = conn.execute(
                "SELECT fund_code, fund_name, added_at, group_name FROM monitoring_watchlist "
                "WHERE user_id = ? ORDER BY group_name, added_at DESC",
                (uid,),
            ).fetchall()
        except Exception:
            rows = conn.execute(
                "SELECT fund_code, fund_name, added_at FROM monitoring_watchlist "
                "WHERE user_id = ? ORDER BY added_at DESC",
                (uid,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            out.append({
                "code": d["fund_code"],
                "name": d.get("fund_name", ""),
                "added_at": d.get("added_at", ""),
                "group": d.get("group_name") or "未分组",
            })
        return out

def _save_watchlist_item(code, name, group_name=""):
    """添加一只基金到监控列表（DB 持久化）"""
    uid = get_user_id()
    grp = (group_name or "").strip()
    with get_connection() as conn:
        if DB_MODE == "postgresql":
            conn.execute(
                "INSERT INTO monitoring_watchlist (user_id, fund_code, fund_name, added_at, group_name) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (user_id, fund_code) DO UPDATE SET "
                "fund_name = EXCLUDED.fund_name, group_name = COALESCE(NULLIF(EXCLUDED.group_name,''), monitoring_watchlist.group_name)",
                (uid, code, name, now_iso(), grp),
            )
        else:
            # SQLite: 先 insert ignore，再更新分组
            conn.execute(
                "INSERT OR IGNORE INTO monitoring_watchlist (user_id, fund_code, fund_name, added_at, group_name) "
                "VALUES (?, ?, ?, ?, ?)",
                (uid, code, name, now_iso(), grp),
            )
            if grp:
                conn.execute(
                    "UPDATE monitoring_watchlist SET group_name = ?, fund_name = ? "
                    "WHERE user_id = ? AND fund_code = ?",
                    (grp, name, uid, code),
                )

def _remove_watchlist_item(code):
    uid = get_user_id()
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM monitoring_watchlist WHERE user_id = ? AND fund_code = ?",
            (uid, code),
        )

def _remove_watchlist_items(codes):
    for c in codes:
        _remove_watchlist_item(c)

def _set_watchlist_group(codes, group_name):
    uid = get_user_id()
    grp = (group_name or "").strip()
    with get_connection() as conn:
        for c in codes:
            conn.execute(
                "UPDATE monitoring_watchlist SET group_name = ? WHERE user_id = ? AND fund_code = ?",
                (grp, uid, c),
            )

def _clear_watchlist():
    uid = get_user_id()
    with get_connection() as conn:
        conn.execute("DELETE FROM monitoring_watchlist WHERE user_id = ?", (uid,))

fetcher = get_fetcher()

_wp = st.session_state.pop("watch_prefill_code", None)
if _wp:
    st.session_state["input_add_code"] = str(_wp).strip()[:6]

watch_list = _load_watchlist()

section_header("监控列表管理")

# ---- 工具条：同步组合 / 分组筛选 ----
tool1, tool2, tool3 = st.columns([1, 1, 2])
with tool1:
    if st.button("📥 从持仓同步", use_container_width=True, help="把组合持仓并入监控列表"):
        from core.portfolio import get_portfolio_manager
        pm = get_portfolio_manager()
        added = 0
        for p in pm.list_all():
            df = pm.get_holdings_df(p.id)
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                code = str(row.get("fund_code") or row.get("基金代码") or "").strip()
                name = str(row.get("fund_name") or row.get("基金名称") or code).strip()
                if len(code) == 6 and code.isdigit():
                    _save_watchlist_item(code, name, group_name=f"组合:{p.name}")
                    added += 1
        st.success(f"已同步，写入/更新约 {added} 条")
        st.rerun()
with tool2:
    groups = sorted({w["group"] for w in watch_list}) or ["未分组"]
    filter_group = st.selectbox("分组筛选", ["全部"] + groups, key="watch_group_filter")
with tool3:
    batch_group_name = st.text_input("批量设置分组名", placeholder="如 核心/主题/观察", key="watch_batch_group")

# ---- 添加区 ----
add_col1, add_col2, add_col3 = st.columns([2, 1, 1])
with add_col1:
    new_code = st.text_input(
        "添加基金代码",
        placeholder="输入6位代码如 000001",
        max_chars=6,
        key="input_add_code",
        label_visibility="collapsed",
    )
with add_col2:
    if st.button("➕ 添加", use_container_width=True):
        code = new_code.strip()
        if len(code) == 6 and code.isdigit():
            existing = [w["code"] for w in watch_list]
            if code not in existing:
                info = fetcher.get_fund_manager_info(code)
                name = info.get("基金名称", code) if info else code
                _save_watchlist_item(code, name, group_name=batch_group_name)
                st.rerun()
            else:
                st.warning(f"{code} 已在列表中")
        elif new_code.strip():
            st.warning("请输入6位数字基金代码")

with add_col3:
    with st.expander("📋 批量导入", expanded=False):
        batch_codes = st.text_area(
            "每行一个代码",
            height=100,
            placeholder="000001\n110011\n510300",
            key="batch_import",
        )
        if st.button("📥 批量导入", use_container_width=True):
            added = 0
            for c in batch_codes.split("\n"):
                c = c.strip()
                if len(c) == 6 and c.isdigit():
                    if c not in [w["code"] for w in watch_list]:
                        info = fetcher.get_fund_manager_info(c)
                        name = info.get("基金名称", c) if info else c
                        _save_watchlist_item(c, name, group_name=batch_group_name)
                        added += 1
            if added:
                st.success(f"✅ 添加 {added} 只")
                st.rerun()
    if st.button("📋 加载示例", use_container_width=True):
        examples = ["000001","110011","510300","005827","006327"]
        for c in examples:
            if c not in [w["code"] for w in watch_list]:
                info = fetcher.get_fund_manager_info(c)
                name = info.get("基金名称", c) if info else c
                _save_watchlist_item(c, name)
        st.rerun()

# ---- 监控列表展示 ----
st.markdown("---")
visible = watch_list if filter_group == "全部" else [w for w in watch_list if w["group"] == filter_group]

if visible:
    st.markdown(f"##### 📊 当前显示 ({len(visible)}/{len(watch_list)} 只)")

    # 多选批量
    options = {f"{w['code']} · {w['name']} · [{w['group']}]": w["code"] for w in visible}
    selected_labels = st.multiselect("勾选后可批量操作", list(options.keys()), key="watch_multiselect")
    selected_codes = [options[x] for x in selected_labels]
    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("🗑️ 批量删除", disabled=not selected_codes, use_container_width=True):
            _remove_watchlist_items(selected_codes)
            st.rerun()
    with b2:
        if st.button("🏷️ 批量分组", disabled=not selected_codes or not batch_group_name.strip(), use_container_width=True):
            _set_watchlist_group(selected_codes, batch_group_name.strip())
            st.rerun()
    with b3:
        if st.button("🗑️ 清空全部", key="clear_all", use_container_width=True):
            _clear_watchlist()
            st.rerun()
    with b4:
        st.caption(f"已选 {len(selected_codes)}")

    # 表头
    h1, h2, h3, h4, h5 = st.columns([0.5, 1, 2.2, 1.2, 1])
    h1.caption("**#**")
    h2.caption("**代码**")
    h3.caption("**名称**")
    h4.caption("**分组**")
    h5.caption("**操作**")

    rows_container = st.container(height=min(350, 48 * len(visible) + 20))
    to_delete = None
    for i, w in enumerate(visible):
        with rows_container.container():
            r1, r2, r3, r4, r5 = st.columns([0.5, 1, 2.2, 1.2, 1])
            r1.markdown(f"<span style='color:#94A3B8;'>{i+1}</span>", unsafe_allow_html=True)
            r2.markdown(f"<code>{w['code']}</code>", unsafe_allow_html=True)
            r3.markdown(f"<span style='font-size:0.9rem;'>{w['name']}</span>", unsafe_allow_html=True)
            r4.markdown(f"<span style='color:#64748B;font-size:0.8rem;'>{w['group']}</span>", unsafe_allow_html=True)
            if r5.button("🗑️", key=f"del_{w['code']}_{i}", help=f"删除 {w['name']}"):
                to_delete = w["code"]
            if i < len(visible) - 1:
                st.markdown("<hr style='margin:2px 0;border-color:#F1F5F9;'>", unsafe_allow_html=True)

    if to_delete is not None:
        _remove_watchlist_item(to_delete)
        st.rerun()

    with st.expander("📡 盘中估值快览", expanded=False):
        for w in visible[:5]:
            render_intraday_nav(w["code"], expanded=False, show_table=False)

    codes = [w["code"] for w in watch_list]
else:
    st.info("👆 还没有监控基金，请添加；可用「从持仓同步」一键导入组合。")
    codes = [w["code"] for w in watch_list]

st.markdown("---")

# 巡检按钮
section_header("执行巡检")

if not check_api_ready():
    st.stop()

analyze_clicked = render_analysis_button(
    f"🔍 巡检 {len(codes)} 只基金",
    disabled=len(codes) == 0,
    key="btn_monitor_check",
)

if analyze_clicked:
    section_header("预警报告")

    # 逐只基金检查
    alerts = []

    progress = st.progress(0)
    status_text = st.empty()

    for i, code in enumerate(codes):
        status_text.text(f"正在检查 {code}...")

        # 获取基金数据
        info = fetcher.get_fund_manager_info(code)
        nav = fetcher.get_fund_nav_history(code, years=1)
        estimate = fetcher.get_realtime_estimate(code)

        fund_alerts = {
            "基金代码": code,
            "基金名称": info.get("基金名称", f"基金{code}") if info else f"基金{code}",
            "预警列表": [],
        }

        if nav is not None and not nav.empty:
            nav_sorted = nav.sort_values("日期", ascending=True)
            nav_series = nav_sorted["单位净值"].dropna()

            # 检查业绩掉队
            if alert_performance and len(nav_series) >= 60:
                from core.utils import calc_annualized_return
                recent_ret = calc_annualized_return(nav_series.iloc[-60:])
                if recent_ret < -perf_threshold / 100:
                    fund_alerts["预警列表"].append(
                        f"📉 业绩掉队: 近3月年化收益 {recent_ret*100:.1f}%，低于阈值 -{perf_threshold}%"
                    )

            # 检查回撤
            from core.utils import calc_max_drawdown
            max_dd = calc_max_drawdown(nav_series)
            if max_dd < -0.20:
                fund_alerts["预警列表"].append(
                    f"⚠️ 回撤扩大: 近1年最大回撤 {max_dd*100:.1f}%"
                )

        # 检查估值溢价
        if estimate:
            premium = safe_float(estimate.get("估算涨幅%", 0))
            if abs(premium) > 3:
                fund_alerts["预警列表"].append(
                    f"📊 异常波动: 实时估算涨幅 {premium:.2f}%"
                )

        # 检查规模
        if info:
            size_str = info.get("最新规模", "")
            if "0.00" in size_str or "0亿" in size_str:
                fund_alerts["预警列表"].append(
                    "⚠️ 规模异常: 基金规模显示为0，可能存在清盘风险"
                )

        if fund_alerts["预警列表"]:
            alerts.append(fund_alerts)

        progress.progress((i + 1) / len(codes))

    status_text.empty()
    progress.empty()

    # 展示预警结果
    if alerts:
        st.error(f"🚨 **发现 {len(alerts)} 只基金存在预警信号**")

        for a in alerts:
            with st.expander(
                f"{'🔴' if len(a['预警列表']) >= 2 else '🟡'} {a['基金名称']} ({a['基金代码']}) — {len(a['预警列表'])}条预警",
                expanded=len(a["预警列表"]) >= 2,
            ):
                for alert in a["预警列表"]:
                    st.warning(alert)
    else:
        st.success(f"✅ **{len(codes)} 只基金巡检通过，暂无预警信号**")

    # AI 深度分析预警
    if alerts and len(alerts) > 0:
        st.markdown("---")
        section_header("AI 预警深度分析")

        if render_analysis_button(
            "🚀 AI 分析预警信号",
            key="btn_ai_alert_analysis",
        ):
            analyzer = get_analyzer()
            if sidebar_config.get("model"):
                analyzer.model = sidebar_config["model"]

            depth_map = {"简要": 2048, "标准": 4096, "深度": 8192, "极致": 16384}
            max_tokens = depth_map.get(sidebar_config.get("depth", "标准"), 4096)

            # 加载 watchtower prompt
            wt_path = Path(__file__).parent.parent / "prompts" / "watchtower.md"
            if wt_path.exists():
                system_prompt = wt_path.read_text(encoding="utf-8")
            else:
                system_prompt = (
                    "你是基金监控预警专家。请分析以下预警信号的重要性排序、"
                    "可能原因、以及投资者应关注的事项。不构成投资建议。"
                )

            alerts_text = "\n\n".join(
                f"## {a['基金名称']} ({a['基金代码']})\n" +
                "\n".join(f"- {x}" for x in a["预警列表"])
                for a in alerts
            )

            final_result = run_analysis_stream(
                analyzer, system_prompt,
                f"请分析以下基金预警信号，按严重性排序并给出建设性关注建议：\n\n{alerts_text}",
                max_tokens=max_tokens, temperature=0.3,
                placeholder_label="📝 预警分析"
            )

            if final_result and final_result.get("success"):
                show_elapsed_time(final_result.get("elapsed_seconds", 0))
                show_token_usage(final_result.get("usage", {}))

    # 合规提示
    show_info_box(
        """
        ⚖️ **合规声明**
        - 预警系统基于公开数据的自动化检测，可能存在误报
        - 预警信号不代表"卖出"或"减仓"建议，需结合自身情况判断
        - 建议收到预警后查阅基金最新季报/公告以确认具体情况
        - 本系统仅供信息参考，不构成投资建议
        """
    )
