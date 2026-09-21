"""
账户设置 — 页面 99
==================
个人资料、修改密码、用量统计、套餐管理。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from core.config import config
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    render_kv_cards,
    init_page_state,
    safe_run,
    section_header,
)
from core.db import DB_MODE
from core.auth import AuthManager
from core.user_repo import UserRepo
from core.middleware import QUOTA_MAP, TIER_LABELS, is_admin

init_page_state({"account_pw_msg": None})


def main():
    render_page_header(
        title="账户设置",
        icon="👤",
        description="管理个人资料、修改密码、查看用量统计",
        accent_color="#6366F1",
    )

    sidebar_config = render_sidebar_config(show_ai_config=False)
    render_top_toolbar(show_ai_config=False)

    user = st.session_state.get("user", {})
    if not user:
        st.warning("请先登录")
        st.page_link("pages/00_登录注册.py", label="→ 前往登录", icon="📧")
        st.stop()

    admin_mode = is_admin()
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["👤 个人资料", "🔑 修改密码", "🔌 AI 与数据源", "📊 用量统计", "⚙️ 偏好设置"]
    )

    # ---- Tab 1: 个人资料 ----
    with tab1:
        section_header("账户信息")
        render_kv_cards([
            ("邮箱", user.get("email", "-")),
            ("昵称", user.get("display_name") or "未设置"),
            ("套餐", TIER_LABELS.get(user.get("tier", "free"), user.get("tier", "free"))),
            ("注册时间", str(user.get("created_at", "-"))[:10]),
        ], columns=4)

        st.divider()
        section_header("修改昵称")
        new_name = st.text_input("新昵称", value=user.get("display_name", ""))
        if st.button("💾 保存", key="save_name"):
            if new_name.strip():
                UserRepo().update_display_name(user["id"], new_name.strip())
                user["display_name"] = new_name.strip()
                st.session_state["user"] = user
                st.success("✅ 昵称已更新")

    # ---- Tab 2: 修改密码 ----
    with tab2:
        section_header("修改登录密码")
        with st.form("change_pw"):
            old_pw = st.text_input("当前密码", type="password")
            new_pw = st.text_input("新密码（至少6位）", type="password")
            new_pw2 = st.text_input("确认新密码", type="password")
            submitted = st.form_submit_button("🔐 修改密码", use_container_width=True)

            if submitted:
                if not old_pw or not new_pw:
                    st.error("请填写所有字段")
                elif len(new_pw) < 6:
                    st.error("新密码至少6位")
                elif new_pw != new_pw2:
                    st.error("两次新密码输入不一致")
                else:
                    repo = UserRepo()
                    full_user = repo.get_by_id(user["id"])
                    if not AuthManager.verify_password(old_pw, full_user["password_hash"]):
                        st.error("当前密码错误")
                    else:
                        repo.update_password(user["id"], AuthManager.hash_password(new_pw))
                        st.success("✅ 密码已修改，请妥善保管")

    # ---- Tab 3: AI 与数据源（自带密钥 / 自带数据源）----
    with tab3:
        from core.integration_ui import render_integration_settings
        st.caption(
            "本系统不绑定任何模型厂商与行情源。你可以用**自己的** API Key 和行情账号，"
            "成本与数据都掌握在自己手里。未配置 AI 密钥时，筛选、回测、费率计算等"
            "本地功能依然完全可用。"
        )
        render_integration_settings(show_data_source=True)

    # ---- Tab 4: 用量统计 ----
    with tab4:
        section_header("AI 分析用量（今日）")
        repo = UserRepo()
        usage = repo.get_usage(user["id"])

        tier = usage.get("tier", "free")
        # 展示配额以套餐定义为准，避免 DB 字段与 QUOTA_MAP 不一致造成「不对」感
        limit = QUOTA_MAP.get(tier, QUOTA_MAP["free"]).get("ai_analysis", usage.get("api_calls_limit", 100))
        used = usage.get("api_calls_today", 0)
        remaining = max(0, limit - used)
        pct = used / limit * 100 if limit > 0 else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("今日已用", str(used))
        c2.metric("今日剩余", str(remaining))
        c3.metric("每日配额", "不限" if limit >= 99999 else str(limit))

        # 进度条
        st.progress(min(pct / 100, 1.0), text=f"AI 分析用量: {used}/{limit if limit < 99999 else '∞'} ({pct:.0f}%)")
        st.caption("仅统计成功生成正文的 AI 分析次数（含筛选页流式分析、FAMAS Agent）。每天 0 点（北京时间）清零。")

        st.divider()
        section_header("套餐详情")
        tier_info = QUOTA_MAP.get(tier, QUOTA_MAP["free"])
        for resource, quota in tier_info.items():
            labels = {
                "ai_analysis": "🤖 AI 分析（次/天）",
                "monitoring": "🚨 监控基金（只）",
                "portfolio": "💼 组合数量（个）",
                "export": "📤 导出次数（次/天）",
            }
            qtxt = "不限" if isinstance(quota, int) and quota >= 99999 else str(quota)
            st.caption(f"{labels.get(resource, resource)}: {qtxt}")

        st.divider()
        st.caption(f"当前套餐: {TIER_LABELS.get(tier, tier)}")
        if tier == "free":
            st.info("💡 升级到专业版获得更多配额：每日100次AI分析、50只监控、10个组合")

    # ---- Tab 5: 偏好（跨设备同步）----
    with tab5:
        from core.user_workspace import get_prefs, save_prefs, set_color_mode_pref
        from core.ui_theme import THEME_KEY
        prefs_wrap = get_prefs()
        prefs = prefs_wrap.get("prefs") or {}
        section_header("跨设备偏好")
        st.caption("以下设置保存在云端数据库，换设备登录后自动恢复。")

        mode = st.selectbox(
            "主题",
            ["light", "dark"],
            index=0 if prefs_wrap.get("color_mode", "light") == "light" else 1,
            format_func=lambda x: "浅色" if x == "light" else "深色",
            key="pref_color_mode",
        )
        auto_save = st.toggle(
            "AI 分析自动保存到历史",
            value=bool(prefs.get("auto_save_history", True)),
            key="pref_auto_save",
        )
        digest_auto = st.toggle(
            "盘后自动推送日报（需配置通知通道，15:05 后）",
            value=bool(prefs.get("digest_auto", True)),
            key="pref_digest_auto",
        )
        default_depth = st.select_slider(
            "默认分析深度",
            options=["简要", "标准", "深度", "极致"],
            value=prefs.get("default_depth") if prefs.get("default_depth") in ("简要", "标准", "深度", "极致") else "标准",
            key="pref_default_depth",
        )
        if st.button("💾 保存偏好", key="save_prefs_btn"):
            set_color_mode_pref(mode)
            st.session_state[THEME_KEY] = mode
            save_prefs(prefs_patch={
                "auto_save_history": auto_save,
                "digest_auto": digest_auto,
                "default_depth": default_depth,
            })
            st.success("偏好已保存")

    # 管理员快捷入口
    if admin_mode:
        st.divider()
        st.page_link("pages/97_用户管理.py", label="👥 进入用户管理", icon="👥")

    # 退出登录
    st.divider()
    if st.button("🚪 退出登录"):
        st.session_state.pop("auth_token", None)
        st.session_state.pop("user", None)
        st.session_state.pop("_nav_user_tier", None)  # 清掉侧栏档位缓存
        st.query_params.pop("auth", None)
        st.success("已退出登录")
        st.rerun()


if __name__ == "__main__":
    main()
