"""
用户管理 — 页面 97（管理员专用）
===============================
创建、查看、管理所有用户账号。仅管理员可访问。
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
    init_page_state,
    section_header,
)
from core.auth import AuthManager
from core.user_repo import UserRepo
from core.middleware import QUOTA_MAP, TIER_LABELS

init_page_state({"admin_tab": "list"})


def main():
    render_page_header(
        title="用户管理",
        icon="👥",
        description="创建和管理系统用户账号，设置套餐和配额",
        help_text="管理员专用页面。可创建新用户、修改套餐、启用/禁用账号、重置密码。",
        accent_color="#7C3AED",
    )

    sidebar_config = render_sidebar_config(show_ai_config=False)
    render_top_toolbar(show_ai_config=False)

    # 权限检查
    user = st.session_state.get("user", {})
    from core.middleware import is_admin
    if not is_admin():
        st.error("⛔ 此页面仅限企业版管理员访问")
        st.caption("请使用企业版账户登录")
        st.stop()

    repo = UserRepo()

    tabs = st.tabs(["📋 用户列表", "➕ 创建用户", "📊 统计概览"])

    # ============================================================
    # Tab 1: 用户列表
    # ============================================================
    with tabs[0]:
        all_users = repo.list_all()

        # 统计条
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("总用户", len(all_users))
        c2.metric("活跃", sum(1 for u in all_users if u.get("is_active")))
        c3.metric("禁用", sum(1 for u in all_users if not u.get("is_active")))
        c4.metric("企业版", sum(1 for u in all_users if u.get("tier") == "enterprise"))
        st.divider()

        if not all_users:
            st.info("暂无用户")
        else:
            # 搜索
            search = st.text_input("🔍 搜索（邮箱/昵称）", placeholder="输入关键词筛选...")
            if search:
                q = search.lower()
                all_users = [u for u in all_users
                           if q in u.get("email", "").lower()
                           or q in u.get("display_name", "").lower()]

            st.caption(f"显示 {len(all_users)} 个用户")

            for u in all_users:
                with st.container():
                    c1, c2, c3, c4, c5 = st.columns([3, 1.5, 1, 1, 1])

                    with c1:
                        icon = "🟢" if u.get("is_active") else "🔴"
                        name = u.get("display_name") or "未设置"
                        st.markdown(f"{icon} **{name}**")
                        st.caption(
                            f"📧 {u['email']} · "
                            f"注册: {str(u.get('created_at', ''))[:10]}"
                            + (f" · 最后登录: {str(u.get('last_login_at', ''))[:10]}"
                               if u.get('last_login_at') else "")
                        )

                    with c2:
                        # 套餐快速切换
                        current_tier = u.get("tier", "free")
                        limits = {"free": 10, "pro": 100, "enterprise": 99999}
                        new_tier = st.selectbox(
                            "套餐",
                            ["free", "pro", "enterprise"],
                            index=["free", "pro", "enterprise"].index(current_tier),
                            key=f"tier_{u['id']}",
                            label_visibility="collapsed",
                        )
                        if new_tier != current_tier:
                            repo.set_tier(u["id"], new_tier, limits[new_tier])
                            st.rerun()

                    with c3:
                        st.caption(
                            f"API: {u.get('api_calls_today', 0)}/"
                            f"{u.get('api_calls_limit', 100)}"
                        )

                    with c4:
                        if u.get("is_active"):
                            if st.button("🔒 禁用", key=f"deact_{u['id']}"):
                                repo.toggle_active(u["id"], False)
                                st.rerun()
                        else:
                            if st.button("🔓 启用", key=f"act_{u['id']}"):
                                repo.toggle_active(u["id"], True)
                                st.rerun()

                    with c5:
                        # 操作菜单
                        with st.popover("⚙️", use_container_width=True):
                            st.caption(f"操作: **{u['email']}**")

                            # 重置密码
                            new_pw = st.text_input(
                                "新密码", type="password",
                                key=f"rpw_{u['id']}",
                                placeholder="留空不修改",
                            )
                            reset_pw_clicked = st.button("🔑 重置密码", key=f"resetpw_{u['id']}")
                            if reset_pw_clicked:
                                if not new_pw:
                                    st.warning("请先输入新密码")
                                elif len(new_pw) < 6:
                                    st.error("密码至少6位")
                                else:
                                    repo.update_password(u["id"], AuthManager.hash_password(new_pw))
                                    st.success("密码已重置")

                            # 修改昵称
                            new_name = st.text_input(
                                "昵称", value=u.get("display_name", ""),
                                key=f"name_{u['id']}",
                            )
                            save_name_clicked = st.button("💾 保存", key=f"savename_{u['id']}")
                            if save_name_clicked:
                                if new_name != u.get("display_name", ""):
                                    repo.update_display_name(u["id"], new_name)
                                    st.success("昵称已保存")
                                    st.rerun()

                            # 重置用量
                            if st.button("🔄 重置今日用量", key=f"resetapi_{u['id']}"):
                                from core.db import get_connection
                                with get_connection() as conn:
                                    conn.execute(
                                        "UPDATE users SET api_calls_today = 0 WHERE id = ?",
                                        (u["id"],),
                                    )
                                st.success("今日用量已清零")
                                st.rerun()

                st.divider()

    # ============================================================
    # Tab 2: 创建用户
    # ============================================================
    with tabs[1]:
        section_header("创建新用户")

        with st.form("admin_create_user_form"):
            c1, c2 = st.columns(2)
            with c1:
                email = st.text_input("邮箱 *", placeholder="user@example.com")
                display_name = st.text_input("昵称", placeholder="用户昵称")
            with c2:
                password = st.text_input("初始密码 *", type="password",
                                         help="用户首次登录后应尽快修改")
                tier = st.selectbox("套餐", ["free", "pro", "enterprise"], index=1,
                                    format_func=lambda t: TIER_LABELS.get(t, t))

            api_limit = st.slider(
                "每日 API 配额",
                5, 99999,
                {"free": 10, "pro": 100, "enterprise": 99999}.get(tier, 100),
                step=5,
                help="AI 分析每日最大调用次数"
            )

            submitted = st.form_submit_button("✅ 创建用户", use_container_width=True, type="primary")

            if submitted:
                if not email or not password:
                    st.error("邮箱和密码为必填项")
                elif "@" not in email:
                    st.error("请输入有效的邮箱地址")
                elif len(password) < 6:
                    st.error("密码至少6位")
                else:
                    try:
                        uid = repo.admin_create_user(email, password, display_name, tier, api_limit)
                        st.success(f"✅ 用户创建成功")
                        st.info(f"""
                        **账号信息:**
                        - 邮箱: {email}
                        - 密码: {password}
                        - 套餐: {TIER_LABELS.get(tier, tier)}
                        - 每日配额: {api_limit} 次

                        请将以上信息发送给用户。
                        """)
                    except ValueError as e:
                        st.error(str(e))

    # ============================================================
    # Tab 3: 统计概览
    # ============================================================
    with tabs[2]:
        all_users = repo.list_all()
        section_header("用户统计")

        # 饼图：套餐分布
        tier_counts = {"free": 0, "pro": 0, "enterprise": 0}
        for u in all_users:
            t = u.get("tier", "free")
            tier_counts[t] = tier_counts.get(t, 0) + 1

        c1, c2 = st.columns(2)
        with c1:
            import plotly.graph_objects as go
            fig = go.Figure(data=[go.Pie(
                labels=["Free", "Pro", "Enterprise"],
                values=[tier_counts["free"], tier_counts["pro"], tier_counts["enterprise"]],
                hole=0.4,
                marker=dict(colors=["#9CA3AF", "#3B82F6", "#7C3AED"]),
            )])
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            # 注册时间线
            section_header("今日用量排行（谁在烧额度）")
            burn = []
            for u in all_users:
                usage = repo.get_usage(u["id"])
                burn.append({
                    "邮箱": u.get("email"),
                    "昵称": u.get("display_name") or "",
                    "套餐": u.get("tier"),
                    "今日": usage.get("api_calls_today", 0),
                    "限额": usage.get("api_calls_limit", 0),
                })
            burn = sorted(burn, key=lambda x: x["今日"], reverse=True)
            if burn:
                st.dataframe(pd.DataFrame(burn), use_container_width=True, hide_index=True)
            else:
                st.caption("暂无数据")
            if all_users:
                reg_dates = pd.to_datetime([u.get("created_at", "") for u in all_users if u.get("created_at")])
                if len(reg_dates) > 0:
                    reg_df = pd.DataFrame({"date": reg_dates})
                    reg_df["count"] = 1
                    reg_df = reg_df.set_index("date").resample("W").count()
                    fig2 = go.Figure(data=[go.Bar(
                        x=reg_df.index, y=reg_df["count"],
                        marker_color="#3B82F6",
                    )])
                    fig2.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                                      xaxis_title="", yaxis_title="新增用户")
                    st.plotly_chart(fig2, use_container_width=True)
                else:
                    st.info("暂无注册数据")
            else:
                st.info("暂无用户数据")

        # 详情表
        st.divider()
        section_header("用户活跃度")
        table_data = []
        for u in sorted(all_users, key=lambda x: x.get("api_calls_today", 0), reverse=True):
            table_data.append({
                "邮箱": u["email"],
                "昵称": u.get("display_name", ""),
                "套餐": u.get("tier", "free"),
                "活跃": "🟢" if u.get("is_active") else "🔴",
                "今日API": f"{u.get('api_calls_today', 0)}/{u.get('api_calls_limit', 100)}",
                "注册日期": str(u.get("created_at", ""))[:10],
                "最后登录": str(u.get("last_login_at", ""))[:16] if u.get("last_login_at") else "-",
            })
        if table_data:
            st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
