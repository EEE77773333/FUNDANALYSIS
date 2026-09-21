"""
预警规则配置 - 页面 21
====================
创建和管理基金净值/回撤预警规则，自动巡检触发并推送通知。

使用说明:
  1. 规则管理：创建净值下跌、回撤、连续下跌等预警规则
  2. 触发历史：查看历史预警记录，确认/忽略
  3. 立即巡检：手动执行全部规则评估
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd

from core.config import config
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    show_info_box,
    show_error,
    safe_run,
    init_page_state,
    section_header,
)
from core.alert_engine import (
    get_alert_engine,
    ALERT_TYPE_PARAMS,
    ALERT_TYPE_LABELS,
    SEVERITY_LABELS,
)


# ============================================================
# Page Config
# ============================================================
init_page_state({
    "alert_edit_rule_id": None,
})


# ============================================================
# Helpers
# ============================================================

def render_rule_manager():
    """规则管理 Tab"""
    ae = get_alert_engine()
    rules = ae.list_rules()

    # 新建规则表单
    with st.expander("➕ 新建预警规则", expanded=not rules):
        with st.form("new_alert_rule"):
            name = st.text_input("规则名称", placeholder="例如：核心基金回撤预警")
            alert_type = st.selectbox(
                "预警类型",
                list(ALERT_TYPE_LABELS.keys()),
                format_func=lambda t: ALERT_TYPE_LABELS.get(t, t),
            )

            severity = st.selectbox(
                "严重程度",
                ["high", "medium", "low"],
                format_func=lambda s: SEVERITY_LABELS.get(s, s),
            )

            fund_codes_str = st.text_area(
                "基金代码（每行一个，或逗号分隔）",
                placeholder="000001\n110011\n005827",
                help="输入需要监控的基金代码；「主题资金排名跃变」可填主题名如「半导体/芯片链」，留空则监控全部主题",
            )

            # 根据预警类型显示对应参数（静态 key，避免 form 内动态列数问题）
            params_config = ALERT_TYPE_PARAMS.get(alert_type, {})
            params = {}
            if params_config:
                st.caption("预警参数:")
                for pname, pinfo in params_config.items():
                    if pinfo["type"] == "number":
                        default_val = pinfo["default"]
                        step_val = 1 if isinstance(default_val, int) else 1.0
                        params[pname] = st.number_input(
                            pinfo["label"],
                            value=default_val,
                            step=step_val,
                            key=f"param_{alert_type}_{pname}",
                        )

            submitted = st.form_submit_button("✅ 创建规则", use_container_width=True)
            if submitted:
                if not name.strip():
                    st.error("请输入规则名称")
                elif alert_type != "theme_flow_rank_jump" and not fund_codes_str.strip():
                    st.error("请输入至少一个基金代码")
                else:
                    codes = [c.strip() for c in fund_codes_str.replace("\n", ",").split(",") if c.strip()]
                    rid = ae.create_rule(name.strip(), alert_type, codes, params, severity)
                    st.success(f"✅ 规则「{name}」已创建")
                    st.rerun()

    # 已有规则列表
    if not rules:
        st.info("📭 暂无预警规则。点击上方「新建预警规则」创建。")
        return

    st.divider()
    section_header("已有规则")

    for rule in rules:
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            with col1:
                enabled_icon = "🟢" if rule.enabled else "🔴"
                st.markdown(f"**{enabled_icon} {rule.name}**")
                st.caption(f"{rule.type_label} · {rule.severity_label}")
                code_str = ", ".join(rule.fund_codes[:5])
                if len(rule.fund_codes) > 5:
                    code_str += f" ... +{len(rule.fund_codes) - 5}"
                st.caption(f"监控: {code_str}")

            with col2:
                if st.button("禁用" if rule.enabled else "启用", key=f"toggle_rule_{rule.id}"):
                    ae.toggle_rule(rule.id, not rule.enabled)
                    st.rerun()

            with col3:
                if st.button("📋 历史", key=f"hist_rule_{rule.id}"):
                    st.session_state["alert_filter_rule_id"] = rule.id
                    st.rerun()

            with col4:
                if st.button("🗑️ 删除", key=f"del_rule_{rule.id}"):
                    ae.delete_rule(rule.id)
                    st.success(f"已删除「{rule.name}」")
                    st.rerun()

            # 参数详情
            if rule.parameters:
                param_str = " · ".join(f"{k}: {v}" for k, v in rule.parameters.items())
                st.caption(f"参数: {param_str}")


def render_trigger_history():
    """触发历史 Tab"""
    ae = get_alert_engine()

    col1, col2, col3 = st.columns(3)
    with col1:
        show_ack = st.selectbox(
            "确认状态",
            ["未确认", "全部", "已确认/忽略"],
            key="trigger_ack_filter",
        )
    with col2:
        today_only = st.checkbox("仅今日", value=True, key="trigger_today_only")
    with col3:
        if st.button("✅ 全部确认/忽略", key="ack_all"):
            ae.acknowledge_all()
            st.success("已全部确认")
            st.rerun()

    acknowledged = None
    if show_ack == "未确认":
        acknowledged = False
    elif show_ack == "已确认/忽略":
        acknowledged = True

    # 统计
    stats = ae.get_trigger_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总触发", stats["total"])
    c2.metric("未确认", stats["unacknowledged"], delta_color="inverse")
    c3.metric("今日", stats.get("today", 0))
    c4.metric("近7天", stats["recent_7d"])

    st.divider()

    groups = ae.get_triggers_grouped(
        acknowledged=acknowledged,
        today_only=today_only,
        limit=80,
    )

    if not groups:
        st.info("📭 暂无触发记录" + ("（今日）" if today_only else ""))
        return

    st.caption("同类告警已按「基金+摘要」合并；忽略会确认组内全部条目。")

    for i, g in enumerate(groups):
        ack_icon = "✅" if g["acknowledged"] else "🔔"
        sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(g["severity"], "⚪")
        cnt = g["count"]
        cnt_label = f" ×{cnt}" if cnt > 1 else ""

        with st.container():
            st.markdown(
                f"{sev_icon} {ack_icon} **{g['fund_code']}**{cnt_label} — {g['latest_at']}"
            )
            st.caption(g["message"])

            if not g["acknowledged"]:
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("确认 / 忽略", key=f"ack_grp_{i}_{g['ids'][0]}"):
                        ae.dismiss_trigger_ids(g["ids"])
                        st.rerun()
                with b2:
                    if cnt > 1 and st.button("仅确认最新", key=f"ack_one_{i}_{g['ids'][0]}"):
                        ae.acknowledge_trigger(g.get("latest_id") or g["ids"][0])
                        st.rerun()

            st.divider()


def render_run_inspection():
    """立即巡检 Tab"""
    ae = get_alert_engine()
    rules = ae.list_rules(enabled_only=True)

    section_header("立即巡检")
    st.caption(f"当前共有 {len(rules)} 条启用规则，将对其中所有基金执行预警检查。")

    if st.button("🚀 开始巡检", use_container_width=True, type="primary"):
        with st.spinner("正在评估预警规则..."):
            triggers = ae.evaluate_all()

        if triggers:
            high_count = sum(1 for t in triggers if t.severity == "high")
            med_count = sum(1 for t in triggers if t.severity == "medium")
            low_count = sum(1 for t in triggers if t.severity == "low")

            st.warning(f"🚨 共触发 {len(triggers)} 条预警 (高: {high_count}, 中: {med_count}, 低: {low_count})")

            if high_count > 0:
                st.error("⚠️ 高严重度预警已自动推送通知（如已配置通知通道）")

            for t in triggers:
                sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(t.severity, "⚪")
                with st.expander(f"{sev_icon} [{t.fund_code}] {t.message[:80]}", expanded=t.severity == "high"):
                    st.write(t.message)
                    st.caption(f"触发时间: {t.triggered_at}")
        else:
            st.success("✅ 所有规则检查通过，未触发预警")


# ============================================================
# Main
# ============================================================

def main():
    render_page_header(
        title="预警规则",
        icon="🔔",
        description="创建和管理基金净值/回撤预警规则，自动巡检并推送通知",
        help_text="使用说明：1. 规则管理：创建预警规则 2. 触发历史：查看历史预警 3. 立即巡检：手动执行评估",
        accent_color="#F59E0B",
    )

    sidebar_config = render_sidebar_config()
    render_top_toolbar()

    # 收件箱摘要
    ae = get_alert_engine()
    stats = ae.get_trigger_stats()
    unack = int(stats.get("unacknowledged", 0))
    today_n = int(stats.get("today", 0))
    if unack:
        st.warning(f"📥 待处理预警收件箱：{unack} 条未确认（今日新增 {today_n}）。同类已在「触发历史」合并展示。")
        inbox = ae.get_triggers_grouped(acknowledged=False, today_only=False, limit=5)
        if inbox:
            with st.expander("快捷处理最近未确认", expanded=True):
                for i, g in enumerate(inbox):
                    st.caption(f"[{g['fund_code']}] ×{g['count']} · {g['message'][:100]}")
                    if st.button("忽略本组", key=f"inbox_ack_{i}_{g['ids'][0]}"):
                        ae.dismiss_trigger_ids(g["ids"])
                        st.rerun()
    else:
        st.success("📥 收件箱清空：暂无未确认预警")

    tab1, tab2, tab3 = st.tabs([
        "📋 规则管理",
        "📜 触发历史",
        "🔍 立即巡检",
    ])

    with tab1:
        render_rule_manager()

    with tab2:
        render_trigger_history()

    with tab3:
        render_run_inspection()


if __name__ == "__main__":
    main()
