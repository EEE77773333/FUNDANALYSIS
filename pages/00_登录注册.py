"""
登录/注册 — 页面 00
====================
用户认证入口。登录或注册后方可使用系统功能。

在多用户模式下，此页作为入口守卫；
在单用户模式（SQLite）下自动使用本地用户，无需手动登录。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from core.middleware import show_login_page
from core.db import DB_MODE

# 如果已登录，显示用户信息
if "user" in st.session_state and st.session_state["user"]:
    st.success(f"✅ 已登录: {st.session_state['user'].get('email', '')}")
    st.caption("使用左侧导航菜单访问各项功能")
    if st.button("🚪 退出登录"):
        st.session_state.pop("auth_token", None)
        st.session_state.pop("user", None)
        st.session_state.pop("_nav_user_tier", None)  # 清掉侧栏档位缓存
        st.query_params.pop("auth", None)
        st.rerun()
else:
    if DB_MODE == "sqlite":
        st.info(
            "📋 **单用户模式**\n\n"
            "当前使用本地 SQLite 数据库，无需登录即可使用全部功能。\n"
            "切换到 PostgreSQL 模式（设置 `DATABASE_URL` 环境变量）后，"
            "此页面将显示登录/注册表单。"
        )
        # 自动创建本地用户会话
        from core.user_repo import UserRepo
        user = UserRepo().get_by_email("local@fund.local")
        if user:
            st.session_state["user"] = {k: v for k, v in user.items() if k != "password_hash"}
        st.success("✅ 单用户模式已就绪，使用左侧导航菜单开始使用")
    else:
        show_login_page()
