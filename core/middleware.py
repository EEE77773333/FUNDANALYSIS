"""
Streamlit 认证中间件
====================
页面入口守卫 + 配额检查 + 用户上下文管理。

两种运行形态（由环境变量 EDITION 控制）：
    EDITION=community（默认，开源自部署）
        不限制任何功能与次数。用户在「账户设置」里配自己的模型密钥，
        成本自担，配额体系只用于展示用量。
    EDITION=cloud（你运营的托管版）
        按套餐扣减每日配额，超额给出升级引导。

使用方式（在每个页面顶部）:
    from core.middleware import require_auth, require_ai_quota

    user = require_auth()
    if not require_ai_quota("深度分析"):
        st.stop()
"""

import os
from typing import Optional, Dict, Any

import streamlit as st

from core.auth import AuthManager
from core.db import DB_MODE


# ============================================================
# 运行形态
# ============================================================

EDITION = (os.getenv("EDITION", "community") or "community").strip().lower()


def is_cloud_edition() -> bool:
    """是否为托管运营版（需执行套餐配额）。"""
    return EDITION in ("cloud", "saas", "hosted")


# ============================================================
# 配额定义
# ============================================================
#
# 说明：额度数值集中在此处，运营方可按自己的定价策略调整。
# 方案文档建议的锚点参考：
#     免费版  ¥0          → 每天 3 次 AI 分析
#     个人版  ¥19.9/月    → 每月 300 次深度分析
#     专业版  ¥49/月      → 无限 AI 分析 + 监控推送
#     团队版  ¥2,999+/年  → 多成员、数据隔离、API
# 这里为兼容既有用户数据，保留 free/pro/enterprise 三个键，
# 并新增 plus（个人版）。调整数值只会影响新计费周期，不会破坏现有账户。

QUOTA_MAP = {
    "free": {
        "ai_analysis": 10,
        "monitoring": 5,
        "portfolio": 1,
        "export": 3,
    },
    "plus": {
        "ai_analysis": 40,
        "monitoring": 20,
        "portfolio": 5,
        "export": 50,
    },
    "pro": {
        "ai_analysis": 100,
        "monitoring": 50,
        "portfolio": 10,
        "export": 999,
    },
    "enterprise": {
        "ai_analysis": 99999,
        "monitoring": 200,
        "portfolio": 999,
        "export": 99999,
    },
}

TIER_LABELS = {
    "free": "🆓 免费版",
    "plus": "🌱 个人版",
    "pro": "⭐ 专业版",
    "enterprise": "💎 企业版",
}

# 各档位的参考定价（仅用于升级页展示，不参与计算）
TIER_PRICING = {
    "free": "¥0",
    "plus": "¥19.9 / 月　或　¥128 / 年",
    "pro": "¥49 / 月",
    "enterprise": "¥2,999+ / 年",
}

# 各档位卖点（升级页展示）
TIER_BENEFITS = {
    "free": ["每日 10 次 AI 分析", "全部筛选与回测工具", "7 天分析历史"],
    "plus": ["每日 40 次 AI 分析", "20 只基金持续监控", "5 个组合托管", "稳定行情数据源"],
    "pro": ["每日 100 次 AI 分析", "50 只基金监控 + 预警推送", "10 个组合托管", "全部功能解锁", "优先支持"],
    "enterprise": ["AI 分析不限量", "200 只基金监控", "多成员与数据隔离", "API 接口", "SLA 保障"],
}


# ============================================================
# 登录/注册 UI
# ============================================================

def show_login_page():
    """渲染登录/注册页面（未认证时由 require_auth 调用）"""
    st.markdown("""
    <div style="text-align:center;padding:2rem 0 1rem;">
        <h1 style="font-size:2rem;">🏦 基金智能分析系统</h1>
        <p style="color:#64748B;">登录或注册以继续使用</p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["📧 登录", "✨ 注册"])

    # ---- Tab 1: 登录 ----
    with tab1:
        with st.form("login_form"):
            email = st.text_input("邮箱", placeholder="your@email.com")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("🚀 登录", use_container_width=True, type="primary")

            if submitted:
                if not email or not password:
                    st.error("请输入邮箱和密码")
                else:
                    result = AuthManager.login(email, password)
                    if result:
                        token, user = result
                        st.session_state["auth_token"] = token
                        st.session_state["user"] = user
                        # 持久化到 URL，刷新后可恢复登录态
                        st.query_params["auth"] = token
                        st.success(f"✅ 欢迎回来，{user.get('display_name') or user['email']}")
                        st.rerun()
                    else:
                        st.error("邮箱或密码错误，或账户未激活")
                        st.caption("💡 没有账号？切换到「✨ 注册」标签页创建新账户。")

    # ---- Tab 2: 注册 ----
    with tab2:
        with st.form("register_form"):
            email = st.text_input("邮箱", placeholder="your@email.com", key="reg_email")
            display_name = st.text_input("昵称（可选）", placeholder="怎么称呼你", key="reg_name")
            password = st.text_input("密码", type="password", key="reg_password",
                                     help="至少6位字符")
            password2 = st.text_input("确认密码", type="password", key="reg_password2")
            agree = st.checkbox(
                "我已阅读并同意《用户协议》与《隐私政策》，并理解本系统仅为数据分析工具、不构成投资建议",
                key="reg_agree",
            )
            submitted = st.form_submit_button("✨ 注册", use_container_width=True, type="primary")

            if submitted:
                if not email or not password:
                    st.error("请填写邮箱和密码")
                elif not agree:
                    st.error("请先阅读并勾选同意《用户协议》与《隐私政策》后再注册")
                elif len(password) < 6:
                    st.error("密码至少6位")
                elif password != password2:
                    st.error("两次密码输入不一致")
                else:
                    try:
                        uid = AuthManager.register(email, password, display_name)
                        if uid:
                            st.success("✅ 注册成功！请切换到「登录」标签页登录")
                        else:
                            st.error("该邮箱已被注册")
                    except ValueError as e:
                        st.error(str(e))

        with st.expander("📄 查看《用户协议》与《隐私政策》"):
            st.markdown(_read_legal_doc("用户协议.md"), unsafe_allow_html=False)
            st.divider()
            st.markdown(_read_legal_doc("隐私政策.md"), unsafe_allow_html=False)


def _read_legal_doc(filename: str) -> str:
    """读取 docs/ 下的合规文档；缺失时给出降级提示而不是抛异常。"""
    try:
        from pathlib import Path as _Path
        p = _Path(__file__).resolve().parent.parent / "docs" / filename
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass
    return f"_未找到 `docs/{filename}`，请在仓库的 `docs/` 目录中查看完整条款。_"


# ============================================================
# 认证守卫
# ============================================================

def require_auth() -> Dict[str, Any]:
    """
    页面入口守卫。
    在每个页面顶部调用一次。

    - SQLite 单用户模式：自动登录本地用户（免登录体验）
    - PostgreSQL 多用户模式：要求登录，未认证则显示登录页并 st.stop()

    Returns:
        user 字典: {id, email, display_name, tier, ...}
    """
    # 如果已有有效用户，直接返回
    if "user" in st.session_state and st.session_state["user"]:
        return st.session_state["user"]

    # 单用户模式：自动加载本地用户
    if DB_MODE == "sqlite":
        try:
            from core.user_repo import UserRepo
            u = UserRepo().get_by_email("local@fund.local")
            if u:
                user_safe = {k: v for k, v in u.items() if k != "password_hash"}
                st.session_state["user"] = user_safe
                return user_safe
        except Exception:
            pass

    # 检查认证 token：会话优先，其次 URL query param（解决浏览器刷新后丢失登录态）
    token = st.session_state.get("auth_token", "") or st.query_params.get("auth", "")
    if token:
        payload = AuthManager.verify_token(token)
        if payload:
            from core.user_repo import UserRepo
            user = UserRepo().get_by_id(payload["user_id"])
            if user:
                user_safe = {k: v for k, v in user.items() if k != "password_hash"}
                st.session_state["user"] = user_safe
                st.session_state["auth_token"] = token
                # 持久化到 URL，确保后续刷新仍可恢复
                if st.query_params.get("auth") != token:
                    st.query_params["auth"] = token
                return user_safe

        # Token 无效或过期 → 清理
        st.session_state.pop("auth_token", None)
        st.session_state.pop("user", None)
        st.query_params.pop("auth", None)

    # 未认证 → 显示登录页
    show_login_page()
    st.stop()


def check_quota(user: dict, resource: str) -> bool:
    """
    检查用户配额。

    社区版（EDITION=community）永远返回 True —— 开源自部署不限制次数，
    用户用自己的模型密钥，成本自担。

    Args:
        user: require_auth() 返回的用户字典
        resource: "ai_analysis" | "monitoring" | "portfolio" | "export"

    Returns:
        True = 有配额，False = 已用完
    """
    if not is_cloud_edition():
        return True

    tier = user.get("tier", "free")
    limit = QUOTA_MAP.get(tier, QUOTA_MAP["free"]).get(resource, 0)
    if limit >= 99999:
        return True

    used = _quota_used(user, resource)
    return used < limit


def _quota_used(user: dict, resource: str) -> int:
    """读取某资源的已用量。"""
    if resource == "ai_analysis" and user.get("id"):
        try:
            from core.user_repo import UserRepo
            return UserRepo().get_usage(int(user["id"])).get("api_calls_today", 0)
        except Exception:
            return user.get("api_calls_today", 0)
    return user.get("api_calls_today", 0)


def get_remaining_quota(user: dict, resource: str) -> int:
    """获取指定资源的剩余配额（社区版返回一个很大的数表示不限）。"""
    if not is_cloud_edition():
        return 99999
    tier = user.get("tier", "free")
    limit = QUOTA_MAP.get(tier, QUOTA_MAP["free"]).get(resource, 0)
    if limit >= 99999:
        return 99999
    return max(0, limit - _quota_used(user, resource))


def render_quota_exhausted_notice(feature_label: str = "AI 分析") -> None:
    """超额时的统一提示 + 升级引导。"""
    st.error(f"今日 **{feature_label}** 次数已用完")

    user = st.session_state.get("user") or {}
    tier = user.get("tier", "free")
    quota = QUOTA_MAP.get(tier, QUOTA_MAP["free"]).get("ai_analysis", 0)
    next_tier = {"free": "plus", "plus": "pro", "pro": "enterprise"}.get(tier)

    cols = st.columns([2, 1])
    with cols[0]:
        st.caption(f"当前套餐：{TIER_LABELS.get(tier, tier)} · 每日上限 {quota} 次")
        if next_tier:
            price = TIER_PRICING.get(next_tier, "")
            new_quota = QUOTA_MAP.get(next_tier, {}).get("ai_analysis", 0)
            st.markdown(
                f"**升级到 {TIER_LABELS.get(next_tier, next_tier)}**（{price}）"
                f"，每日可分析 **{new_quota if new_quota < 99999 else '不限'}** 次"
            )
            for benefit in TIER_BENEFITS.get(next_tier, [])[:3]:
                st.caption(f"· {benefit}")
    with cols[1]:
        st.caption("明日 0 点（北京时间）自动重置")


def require_ai_quota(feature_label: str = "AI 分析") -> bool:
    """
    AI 类功能守卫：在发起耗额度的操作前调用。

    社区版恒返回 True；托管版超额时渲染升级引导并返回 False。

    使用示例:
        if not require_ai_quota("FAMAS 深度分析"):
            st.stop()
    """
    if not is_cloud_edition():
        return True

    user = st.session_state.get("user") or {}
    if not user:
        return False

    # 用户自带密钥的调用不占托管额度，直接放行
    try:
        from core.metering import _llm_source_is_byok
        if _llm_source_is_byok():
            return True
    except Exception:
        pass

    if check_quota(user, "ai_analysis"):
        return True

    render_quota_exhausted_notice(feature_label)
    return False


# ============================================================
# 套餐订阅守卫（菜单权限控制）
# ============================================================
#
# 设计要点：
#   1. 菜单在侧栏「显性保留」，未订阅用户同样看得见（标题带 🔒）；
#   2. 打开受限菜单时渲染「请进行订阅」引导页，不进入功能正文；
#   3. 仅在托管版（EDITION=cloud）生效；开源自部署（community）全解锁；
#   4. 门槛配置集中在 core/nav_catalog.GROUP_REQUIRED_TIER，改一处即可。

# 订阅档位环境变量：订阅联系方式（微信号 / 邮箱 / 链接），运营方可在 .env 里配置
SUBSCRIBE_CONTACT = (os.getenv("SUBSCRIBE_CONTACT", "") or "").strip()

# 栏目 → 该栏目需要的档位描述（引导页文案）
_TIER_CN = {"free": "免费版", "plus": "个人版", "pro": "专业版", "enterprise": "企业版"}


def current_user_tier() -> str:
    """当前登录用户的套餐档位（未知按 free）。"""
    user = st.session_state.get("user") or {}
    return (user.get("tier") or "free").strip().lower()


def _detect_page_path() -> Optional[str]:
    """从调用栈里找出当前页面脚本路径（兜底用，避免漏判）。"""
    try:
        import inspect

        for frame in inspect.stack():
            fn = (frame.filename or "").replace("\\", "/")
            if "/pages/" in fn and fn.endswith(".py"):
                return fn
    except Exception:
        pass
    return None


def require_feature_access(page_or_group: Optional[str] = None) -> bool:
    """订阅守卫：打开受限菜单时校验套餐档位。

    托管版下若档位不足，渲染「请进行订阅」引导页并返回 False（调用方应 st.stop()）。
    社区版恒返回 True。

    Args:
        page_or_group: 页面路径/文件名（如 __file__）或栏目名（如 "持仓组合"）

    使用示例:
        from core.middleware import require_feature_access
        if not require_feature_access(__file__):
            st.stop()
    """
    if not is_cloud_edition():
        return True

    try:
        from core.nav_catalog import required_tier_for, tier_meets
    except Exception:
        return True

    target = page_or_group or _detect_page_path()
    required = required_tier_for(target) if target else None
    if not required:
        return True

    user = st.session_state.get("user") or {}
    tier = current_user_tier()
    if user and tier_meets(tier, required):
        return True

    render_subscription_required(required, target)
    return False


def render_subscription_required(required_tier: str, page_or_group: Optional[str] = None) -> None:
    """渲染「请进行订阅」引导页。"""
    try:
        from core.nav_catalog import (
            GROUP_REQUIRED_TIER,
            pages_in_section,
            section_for_page,
            tier_meets,
        )
    except Exception:  # pragma: no cover - 理论上不会发生
        st.error("请进行订阅")
        return

    section = ""
    if page_or_group:
        key = str(page_or_group).replace("\\", "/")
        if key in GROUP_REQUIRED_TIER:
            section = key
        else:
            section = section_for_page(key)
    if not section:
        # 兜底：反查该档位对应的栏目
        for sec, req in GROUP_REQUIRED_TIER.items():
            if req == required_tier:
                section = sec
                break

    tier = current_user_tier()
    req_label = TIER_LABELS.get(required_tier, _TIER_CN.get(required_tier, required_tier))
    cur_label = TIER_LABELS.get(tier, tier)
    price = TIER_PRICING.get(required_tier, "")

    # 主提示（不依赖主题的配色，深浅色模式都可读）
    st.markdown(
        f"""
        <div style="border:1px solid rgba(220,38,38,.35);background:rgba(220,38,38,.08);
                    border-left:4px solid #DC2626;border-radius:12px;
                    padding:1.5rem 1.75rem;margin:0.5rem 0 1.25rem;">
            <div style="font-size:1.35rem;font-weight:800;letter-spacing:.02em;margin-bottom:.5rem;">
                🔒 请进行订阅
            </div>
            <div style="font-size:.92rem;line-height:1.75;">
                「{section or '该功能'}」需要 <b>{req_label}</b> 及以上套餐，
                当前你的套餐为 <b>{cur_label}</b>，暂无权使用。
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 解锁后可见的菜单
    features = pages_in_section(section) if section else []
    if features:
        cols = st.columns([3, 2])
        with cols[0]:
            st.markdown(f"**订阅 {req_label} 后可解锁「{section}」全部 {len(features)} 个功能：**")
            for name in features:
                st.markdown(f"- {name}")
        with cols[1]:
            st.markdown("**套餐权益**")
            for b in TIER_BENEFITS.get(required_tier, [])[:5]:
                st.markdown(f"- {b}")
            if price:
                st.caption(f"参考价：{price}")

    st.divider()

    # 档位对照
    with st.expander("📊 查看全部套餐对照", expanded=False):
        rows = []
        for t in ("free", "plus", "pro", "enterprise"):
            rows.append(
                {
                    "套餐": TIER_LABELS.get(t, t),
                    "价格": TIER_PRICING.get(t, ""),
                    "每日 AI 次数": QUOTA_MAP.get(t, {}).get("ai_analysis", 0),
                    "深度分析 / 持仓组合": "✅" if tier_meets(t, "pro") else "—",
                    "监控预警": "✅" if tier_meets(t, "enterprise") else "—",
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    # 行动指引
    if SUBSCRIBE_CONTACT:
        st.success(f"**开通 / 升级方式**：{SUBSCRIBE_CONTACT}")
    else:
        st.info(
            "**开通 / 升级方式**：请通过页面右下角的联系方式与管理员取得联系，"
            "说明需要开通的套餐档位（专业版 / 企业版）。\n\n"
            "_（运营方可设置环境变量 `SUBSCRIBE_CONTACT` 自定义此处文案，"
            "例如微信号或开通链接。）_"
        )

    st.caption(
        "提示：菜单会一直保留在左侧，订阅开通后无需重新登录即可直接进入。"
        "如果你已订阅，请点击左下角「退出登录」后重新登录以刷新套餐状态。"
    )


def record_api_call() -> bool:
    """
    【已废弃】手动记录一次 AI 调用。

    计量已下沉到 LLM 层（core/metering.py），由 AIAnalyzer 在调用成功后自动触发。
    页面里再调用本函数会导致重复计数，因此保留仅为兼容旧代码，实际不做任何写入。
    """
    import logging
    logging.getLogger(__name__).warning(
        "record_api_call() 已废弃：AI 用量由 core/metering.py 在 LLM 层自动记账，请移除调用处。"
    )
    return False


def is_admin() -> bool:
    """检查当前用户是否为管理员（enterprise 套餐）"""
    user = st.session_state.get("user", {})
    if not user:
        return False
    return user.get("tier") == "enterprise"

