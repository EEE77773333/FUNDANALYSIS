"""
分析历史 - 页面 22
================
浏览、搜索历史AI分析结果，支持同基金时间序列对比和跨基金横向对比。

使用说明:
  1. 历史浏览：按页面/基金代码/关键词筛选历史分析
  2. 时间对比：查看同一只基金不同时间的分析演变
  3. 跨基金对比：横向比较不同基金的最新分析结论
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
    render_metrics_row,
    init_page_state,
    safe_run,
    show_sortable_df,
    section_header,
)
from core.decision_renderer import render_decision_dashboard
from core.history import get_history_manager
from core.signal_evaluation import get_evaluation_manager


# ============================================================
# Page Config
# ============================================================
init_page_state({
    "history_selected_id": None,
})


# ============================================================
# Helpers
# ============================================================

def render_history_browser():
    """历史浏览 Tab"""
    hm = get_history_manager()

    # 筛选条件
    col1, col2, col3 = st.columns(3)
    with col1:
        page_names = ["全部"] + hm.get_page_names()
        sel_page = st.selectbox("按页面", page_names, key="hist_page_filter")
    with col2:
        sel_fund = st.text_input(
            "按基金代码", placeholder="留空=全部, 如 000001",
            key="hist_fund_filter", max_chars=6,
        )
    with col3:
        search = st.text_input("🔍 关键词搜索", placeholder="搜索结果内容...", key="hist_search")

    records = hm.list_all(
        page_name=sel_page if sel_page != "全部" else None,
        fund_code=sel_fund.strip() if sel_fund and sel_fund.strip() else None,
        search=search if search else None,
        limit=100,
    )

    total = hm.count(
        page_name=sel_page if sel_page != "全部" else None,
        fund_code=sel_fund.strip() if sel_fund and sel_fund.strip() else None,
    )

    st.caption(f"共 {total} 条记录（当前账号）")
    if total == 0:
        st.info(
            "📭 暂无分析历史。\n\n"
            "- 新版会在 AI 分析完成后**自动保存**到这里\n"
            "- 若此前分析发生在自动保存上线前，当时结果仅在当次会话显示，不会出现在此列表\n"
            "- 请重新跑一次分析验证；成功时页面会提示「已自动保存到分析历史 #ID」"
        )
        return

    if not records:
        st.info("📭 当前筛选条件下无记录，请清空筛选后再试。")
        return

    for rec in records:
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            with col1:
                fund_label = f"{rec.fund_name} ({rec.fund_code})" if rec.fund_code else "全局分析"
                st.markdown(f"**{rec.page_name}** — {fund_label}")
                st.caption(rec.preview)
                st.caption(f"🕐 {rec.created_at} · 模型: {rec.model} · 耗时: {rec.elapsed_seconds:.1f}s")

            with col2:
                usage = rec.usage
                if usage:
                    st.caption(f"Tokens: {usage.get('total_tokens', '?')}")

            with col3:
                if st.button("📖 查看", key=f"view_{rec.id}"):
                    st.session_state["history_selected_id"] = rec.id
                    st.rerun()

            with col4:
                if st.button("🔗 分享", key=f"share_{rec.id}"):
                    st.session_state["history_share_id"] = rec.id
                    st.rerun()

            st.divider()

    # 创建分享链接
    if st.session_state.get("history_share_id"):
        sid = st.session_state["history_share_id"]
        with st.expander(f"🔗 创建分享链接 — 记录 #{sid}", expanded=True):
            hours = st.slider("有效期（小时）", 1, 168, 72, key="share_hours")
            if st.button("生成只读链接", key="gen_share"):
                from core.share_links import create_share
                link = create_share(sid, hours=hours)
                if link:
                    st.session_state["history_last_share_token"] = link["token"]
                    st.success(f"已生成，过期时间 {link['expires_at']}")
                else:
                    st.error("生成失败（记录不存在或无权限）")
            tok = st.session_state.get("history_last_share_token")
            if tok:
                st.code(f"/分享阅读?share={tok}", language=None)
                st.caption("把站点域名拼在前面发给同事；对方无需登录。可随时在下方撤销。")
            if st.button("关闭", key="close_share_box"):
                st.session_state.pop("history_share_id", None)
                st.rerun()

    # 我的分享管理
    with st.expander("📎 我的分享链接"):
        from core.share_links import list_my_shares, revoke_share
        shares = list_my_shares(30)
        if not shares:
            st.caption("暂无分享")
        else:
            for s in shares:
                revoked = int(s.get("revoked") or 0)
                status = "已撤销" if revoked else "有效"
                st.markdown(
                    f"**{s.get('title')}** · {status} · 浏览 {s.get('view_count', 0)} · "
                    f"过期 {s.get('expires_at')}"
                )
                st.code(f"/分享阅读?share={s.get('token')}", language=None)
                if not revoked and st.button("撤销", key=f"rev_{s.get('token')}"):
                    revoke_share(s.get("token"))
                    st.rerun()

    # 查看详情弹窗
    if st.session_state.get("history_selected_id"):
        rec = hm.get(st.session_state["history_selected_id"])
        if rec:
            with st.expander(f"📖 分析详情 — {rec.created_at}", expanded=True):
                dashboard = rec.structured_result
                if dashboard:
                    render_decision_dashboard(dashboard, expanded=True)
                    evs = get_evaluation_manager().get_for_source("analysis", rec.id)
                    if evs:
                        section_header("事后验证（T+N）")
                        import pandas as pd
                        show_sortable_df(pd.DataFrame([{
                            "窗口": f"T+{e.horizon_days}",
                            "动作": e.predicted_action,
                            "置信度": f"{e.confidence:.0%}",
                            "实际收益": f"{e.actual_return * 100:+.2f}%",
                            "结果": e.outcome,
                        } for e in evs]))
                    st.markdown("---")
                # 对超长内容做截断展示，避免前端卡顿
                content = rec.result_content or ""
                max_display = 8000
                if len(content) > max_display:
                    st.caption(f"⚠️ 内容较长（{len(content)}字符），仅展示前{max_display}字符。请使用「导出中心」下载完整报告。")
                    st.markdown(content[:max_display] + "\n\n---\n*[内容已截断，完整报告请导出]*")
                else:
                    st.markdown(content)
                if st.button("❌ 关闭", key="close_detail"):
                    st.session_state["history_selected_id"] = None
                    st.rerun()

    # 清理旧记录
    st.divider()
    with st.expander("🧹 清理旧记录"):
        days = st.number_input("删除多少天前的记录", min_value=1, value=90, step=30)
        confirm = st.checkbox(f"⚠️ 我确认删除 {days} 天前的所有历史记录", key="cleanup_confirm")
        if st.button("🗑️ 确认清理", key="cleanup_old", disabled=not confirm):
            count = hm.delete_older_than(days)
            st.success(f"已删除 {count} 条 {days} 天前的记录")
            st.session_state["cleanup_confirm"] = False
            st.rerun()


def render_time_comparison():
    """时间对比 Tab"""
    hm = get_history_manager()
    fund_codes = hm.get_all_fund_codes()

    if not fund_codes:
        st.info("📭 暂无历史数据。请先在分析页面执行分析。")
        return

    sel_fund = st.selectbox("选择基金", fund_codes, key="time_comp_fund")
    records = hm.get_for_fund(sel_fund, limit=10)

    if not records:
        st.info(f"📭 {sel_fund} 暂无历史分析记录")
        return

    st.markdown(f"### 📈 {sel_fund} 分析时间线")
    st.caption(f"最近 {len(records)} 次分析")

    # 按时间正序显示
    for i, rec in enumerate(reversed(records)):
        with st.expander(
            f"{i + 1}. {rec.page_name} — {rec.created_at} ({rec.model}, {rec.elapsed_seconds:.1f}s)",
            expanded=(i == len(records) - 1),  # 展开最新一条
        ):
            st.markdown(rec.result_content)

            usage = rec.usage
            if usage:
                cols = st.columns(3)
                cols[0].metric("输入 Token", usage.get("input_tokens", 0))
                cols[1].metric("输出 Token", usage.get("output_tokens", 0))
                cols[2].metric("总 Token", usage.get("total_tokens", 0))


def render_cross_fund_comparison():
    """跨基金对比 Tab"""
    hm = get_history_manager()
    fund_codes = hm.get_all_fund_codes()

    if len(fund_codes) < 2:
        st.info("📭 需要至少两只基金的历史分析才能对比。请先执行分析。")
        return

    sel_funds = st.multiselect(
        "选择要对比的基金（2-5只）",
        fund_codes,
        max_selections=5,
        key="cross_comp_funds",
    )

    if sel_funds:
        page_names = ["全部"] + hm.get_page_names()
        sel_page = st.selectbox("按分析页面（可选）", page_names, key="cross_comp_page")

        if st.button("🔍 开始对比", use_container_width=True):
            records = hm.compare_funds(
                sel_funds,
                page_name=sel_page if sel_page != "全部" else None,
            )

            if not records:
                st.warning("未找到匹配的分析记录")
                return

            # 并排显示
            cols = st.columns(len(records))
            for i, (code, rec) in enumerate(records.items()):
                with cols[i]:
                    st.markdown(f"### {rec.fund_name or code}")
                    st.caption(f"{code} · {rec.created_at}")
                    st.caption(f"模型: {rec.model} · {rec.elapsed_seconds:.1f}s")
                    with st.container(height=400):
                        st.markdown(rec.result_content[:2000])
        else:
            st.caption("👆 选择基金和页面后，点击「开始对比」")

    # 统计概览
    st.divider()
    section_header("历史统计概览")
    total = hm.count()
    st.metric("总分析次数", total)

    page_names = hm.get_page_names()
    if page_names:
        st.caption("各页面分析次数:")
        cols = st.columns(min(len(page_names), 4))
        for i, pn in enumerate(page_names):
            cnt = hm.count(page_name=pn)
            cols[i % len(cols)].metric(pn[:12], cnt)


# ============================================================
# Main
# ============================================================

def main():
    render_page_header(
        title="分析历史",
        icon="📚",
        description="浏览、搜索历史AI分析结果，支持时间序列对比和跨基金横向对比",
        help_text="使用说明：1. 历史浏览：筛选和搜索历史分析 2. 时间对比：同一基金的历史分析变化 3. 跨基金对比：不同基金的分析结论比较",
        accent_color="#6366F1",
    )

    sidebar_config = render_sidebar_config()
    render_top_toolbar()

    tab1, tab2, tab3 = st.tabs([
        "📋 历史浏览",
        "📈 时间对比",
        "🔬 跨基金对比",
    ])

    with tab1:
        render_history_browser()

    with tab2:
        render_time_comparison()

    with tab3:
        render_cross_fund_comparison()


if __name__ == "__main__":
    main()
