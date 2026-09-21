"""
通知配置 - 页面 18
===============
配置多通道消息通知（企业微信、飞书、邮件），
用于预警信号、市场异动等关键事件的自动推送。

使用说明:
  1. 选择通道类型（企业微信/飞书/邮件）
  2. 填写对应配置参数
  3. 点击"测试发送"验证配置
  4. 启用通道后，预警触发时将自动推送
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
    show_info_box,
    show_error,
    safe_run,
    init_page_state,
    check_api_ready,
    section_header,
)
from core.notifications import get_notification_manager


# ============================================================
# Page Config
# ============================================================
init_page_state({
    "notif_selected_channel": None,
    "notif_test_result": None,
})


# ============================================================
# Render
# ============================================================

def main():
    render_page_header(
        title="通知配置",
        icon="📨",
        description="配置多通道消息通知，预警触发时自动推送到企业微信/飞书/邮件",
        help_text="使用说明：1. 选择通道类型 2. 填写配置参数 3. 测试发送 4. 启用后生效",
        accent_color="#F59E0B",
    )

    sidebar_config = render_sidebar_config(show_ai_config=False)
    render_top_toolbar()

    nm = get_notification_manager()
    channels = nm.get_channels()

    # ---- Tab 结构 ----
    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 已配置通道",
        "💬 企业微信",
        "🐦 飞书",
        "📧 邮件",
    ])

    # ============================================================
    # Tab 1: 已配置通道
    # ============================================================
    with tab1:
        if not channels:
            st.info("📭 暂无配置的通知通道。请切换到「企业微信」「飞书」或「邮件」标签页添加。")
        else:
            for name, ch in channels.items():
                ch_type = ch.get("type", "unknown")
                enabled = ch.get("enabled", True)
                cfg = ch.get("config", {})

                type_labels = {
                    "wechat_work": "💬 企业微信",
                    "feishu": "🐦 飞书",
                    "email": "📧 邮件",
                }
                type_label = type_labels.get(ch_type, f"❓ {ch_type}")

                with st.container():
                    col1, col2, col3 = st.columns([3, 1, 1])
                    with col1:
                        status = "🟢 已启用" if enabled else "🔴 已禁用"
                        st.markdown(f"**{name}**  {type_label}  {status}")
                        # 显示关键配置
                        if ch_type == "wechat_work":
                            wh = cfg.get("webhook_url", "")
                            st.caption(f"Webhook: {wh[:50]}..." if len(wh) > 50 else f"Webhook: {wh}")
                        elif ch_type == "feishu":
                            wh = cfg.get("webhook_url", "")
                            st.caption(f"Webhook: {wh[:50]}..." if len(wh) > 50 else f"Webhook: {wh}")
                        elif ch_type == "email":
                            st.caption(f"发件: {cfg.get('username', '')} → 收件: {cfg.get('to_addresses', '')}")

                    with col2:
                        new_state = not enabled
                        btn_label = "启用" if not enabled else "禁用"
                        if st.button(btn_label, key=f"toggle_{name}"):
                            nm.toggle_channel(name, not enabled)
                            st.rerun()

                    with col3:
                        if st.button("🗑️ 删除", key=f"del_{name}"):
                            nm.remove_channel(name)
                            st.rerun()

        # 测试发送
        st.divider()
        section_header("广播测试")
        test_title = st.text_input("测试标题", "基金预警测试", key="broadcast_title")
        test_content = st.text_area("测试内容", "这是一条来自基金分析系统的测试消息，用于验证通知通道是否配置正确。", key="broadcast_content")

        if st.button("📣 向所有已启用通道广播", use_container_width=True):
            results = nm.broadcast(test_title, test_content)
            for ch_name, success in results.items():
                if success:
                    st.success(f"✅ {ch_name}: 发送成功")
                else:
                    st.error(f"❌ {ch_name}: 发送失败")
            if not results:
                st.warning("⚠️ 没有已启用的通知通道")

    # ============================================================
    # Tab 2: 企业微信
    # ============================================================
    with tab2:
        st.markdown("""
        ### 💬 企业微信机器人配置

        1. 在企业微信中打开目标群聊
        2. 点击群设置 → 群机器人 → 添加机器人
        3. 复制 Webhook 地址
        """)

        with st.form("wechat_form"):
            name = st.text_input("通道名称", "企业微信", help="用于区分多个通道")
            webhook_url = st.text_input("Webhook 地址", placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...")
            submitted = st.form_submit_button("💾 保存并启用", use_container_width=True)

            if submitted:
                if not webhook_url:
                    st.error("请输入 Webhook 地址")
                else:
                    nm.add_channel(name, "wechat_work", {"webhook_url": webhook_url})
                    st.success(f"✅ 通道「{name}」已添加")

        # 快速测试
        if channels:
            wechat_channels = [n for n, c in channels.items() if c.get("type") == "wechat_work"]
            if wechat_channels:
                st.divider()
                st.caption("快速测试已有通道:")
                sel = st.selectbox("选择通道", wechat_channels, key="wechat_test_sel")
                if st.button("📤 测试发送", key="wechat_test_btn"):
                    ok = nm.send_to_channel(sel, "测试消息", "来自基金分析系统的测试通知 ✅")
                    if ok:
                        st.success(f"✅ {sel}: 发送成功")
                    else:
                        st.error(f"❌ {sel}: 发送失败，请检查 Webhook 地址")

    # ============================================================
    # Tab 3: 飞书
    # ============================================================
    with tab3:
        st.markdown("""
        ### 🐦 飞书机器人配置

        1. 在飞书中打开目标群聊
        2. 点击群设置 → 群机器人 → 添加机器人 → 自定义机器人
        3. 复制 Webhook 地址
        4. （可选）设置签名校验密钥
        """)

        with st.form("feishu_form"):
            name = st.text_input("通道名称", "飞书", help="用于区分多个通道")
            webhook_url = st.text_input("Webhook 地址", placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/...")
            secret = st.text_input("签名校验密钥（可选）", placeholder="留空则不启用签名")
            submitted = st.form_submit_button("💾 保存并启用", use_container_width=True)

            if submitted:
                if not webhook_url:
                    st.error("请输入 Webhook 地址")
                else:
                    cfg = {"webhook_url": webhook_url}
                    if secret:
                        cfg["secret"] = secret
                    nm.add_channel(name, "feishu", cfg)
                    st.success(f"✅ 通道「{name}」已添加")

        # 快速测试
        if channels:
            feishu_channels = [n for n, c in channels.items() if c.get("type") == "feishu"]
            if feishu_channels:
                st.divider()
                st.caption("快速测试已有通道:")
                sel = st.selectbox("选择通道", feishu_channels, key="feishu_test_sel")
                if st.button("📤 测试发送", key="feishu_test_btn"):
                    ok = nm.send_to_channel(sel, "测试消息", "来自基金分析系统的测试通知 ✅")
                    if ok:
                        st.success(f"✅ {sel}: 发送成功")
                    else:
                        st.error(f"❌ {sel}: 发送失败，请检查 Webhook 地址和密钥")

    # ============================================================
    # Tab 4: 邮件
    # ============================================================
    with tab4:
        st.markdown("""
        ### 📧 邮件配置

        常见 SMTP 服务器:
        - **QQ邮箱**: smtp.qq.com, 端口 587, 需开启SMTP服务并使用授权码
        - **163邮箱**: smtp.163.com, 端口 587
        - **Gmail**: smtp.gmail.com, 端口 587, 需开启App Password
        """)

        with st.form("email_form"):
            name = st.text_input("通道名称", "邮件通知", help="用于区分多个通道")

            col1, col2 = st.columns(2)
            with col1:
                smtp_host = st.text_input("SMTP 服务器", "smtp.qq.com")
            with col2:
                smtp_port = st.number_input("端口", 25, 995, 587)

            username = st.text_input("发件人邮箱", placeholder="your@qq.com")
            password = st.text_input("SMTP 密码/授权码", type="password", help="不是邮箱密码，而是SMTP授权码")
            to_addresses = st.text_input("收件人（逗号分隔多个）", placeholder="receiver1@qq.com, receiver2@163.com")
            use_tls = st.checkbox("启用 TLS", value=True)

            submitted = st.form_submit_button("💾 保存并启用", use_container_width=True)

            if submitted:
                if not smtp_host or not username or not to_addresses:
                    st.error("请填写必填字段")
                else:
                    nm.add_channel(name, "email", {
                        "smtp_host": smtp_host,
                        "smtp_port": smtp_port,
                        "username": username,
                        "password": password,
                        "to_addresses": to_addresses,
                        "use_tls": use_tls,
                    })
                    st.success(f"✅ 通道「{name}」已添加")

        # 快速测试
        if channels:
            email_channels = [n for n, c in channels.items() if c.get("type") == "email"]
            if email_channels:
                st.divider()
                st.caption("快速测试已有通道:")
                sel = st.selectbox("选择通道", email_channels, key="email_test_sel")
                if st.button("📤 测试发送", key="email_test_btn"):
                    ok = nm.send_to_channel(sel, "测试邮件", "来自基金分析系统的测试通知 ✅\n\n如果您收到此邮件，说明邮件通知配置正确。")
                    if ok:
                        st.success(f"✅ {sel}: 发送成功")
                    else:
                        st.error(f"❌ {sel}: 发送失败，请检查SMTP配置")


if __name__ == "__main__":
    main()
