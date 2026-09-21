"""
全站导航目录（P0）
================
单一数据源：侧栏 st.navigation 分组 + 页头 group 色板映射。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# (script_path, title, icon, group_key)
# group_key → core.ui_components.GROUP_ACCENTS
NavItem = Tuple[str, str, str, str]

NAV_GROUPS: List[Tuple[str, List[NavItem]]] = [
    (
        "今日看板",
        [
            # 工作台由 app.py 以 callable Page 注入，不在此列表
            ("pages/13_实时市场仪表盘.py", "市场仪表盘", "📡", "market"),
            ("pages/28_主题资金流雷达.py", "主题资金流", "🌊", "market"),
            ("pages/27_盘中估值中心.py", "盘中估值", "📡", "monitor"),
        ],
    ),
    (
        "选基",
        [
            ("pages/01_宏观行业研判.py", "宏观行业研判", "📈", "market"),
            ("pages/10_基金排名精选.py", "排名精选", "🏆", "screen"),
            ("pages/04_主动权益筛选.py", "主动权益筛选", "🎯", "screen"),
            ("pages/03_指数基金筛选.py", "指数基金筛选", "📉", "screen"),
            ("pages/02_债券基金筛选.py", "债券基金筛选", "📊", "screen"),
            ("pages/05_QDII基金筛选.py", "QDII 配置", "🌍", "screen"),
            ("pages/11_基金PK擂台.py", "基金 PK", "⚔️", "tools"),
            ("pages/17_专业评级与风格箱.py", "评级与风格箱", "🎓", "agent"),
        ],
    ),
    (
        "深度分析",
        [
            ("pages/08_FAMAS单基金深度分析.py", "FAMAS 深度分析", "🔬", "agent"),
            ("pages/14_新闻情绪分析.py", "新闻情绪", "📰", "agent"),
            ("pages/25_Brinson业绩归因.py", "Brinson 归因", "🔬", "quant"),
        ],
    ),
    (
        "持仓组合",
        [
            ("pages/19_组合管理.py", "我的组合", "💼", "portfolio"),
            ("pages/07_组合诊断优化.py", "组合诊断", "🩺", "portfolio"),
            ("pages/06_资产配置框架.py", "资产配置", "🔧", "portfolio"),
            ("pages/12_持仓漂移热力图.py", "持仓漂移", "🔥", "tools"),
            ("pages/30_赛道再平衡.py", "赛道再平衡", "⚖️", "portfolio"),
        ],
    ),
    (
        "监控预警",
        [
            ("pages/09_持续监控预警.py", "持续监控", "🚨", "monitor"),
            ("pages/21_预警规则.py", "预警规则", "🔔", "monitor"),
            ("pages/20_信号跟踪.py", "信号跟踪", "🚦", "monitor"),
            ("pages/18_通知配置.py", "通知配置", "📨", "monitor"),
        ],
    ),
    (
        "工具与量化",
        [
            ("pages/15_费率计算器.py", "费率计算器", "💰", "tools"),
            ("pages/16_定投回测模拟器.py", "定投回测", "📆", "tools"),
            ("pages/23_策略引擎.py", "策略引擎", "🧩", "quant"),
            ("pages/26_蒙特卡洛模拟.py", "蒙特卡洛", "🎲", "quant"),
            ("pages/29_AI验证仪表盘.py", "AI 验证", "🎯", "quant"),
            ("pages/24_导出中心.py", "导出中心", "📤", "tools"),
            ("pages/22_分析历史.py", "分析历史", "📚", "quant"),
            ("pages/31_分享阅读.py", "分享阅读", "🔗", "account"),
        ],
    ),
    (
        "账户",
        [
            ("pages/00_登录注册.py", "登录 / 注册", "🔐", "account"),
            ("pages/99_账户设置.py", "账户设置", "👤", "account"),
            ("pages/97_用户管理.py", "用户管理", "👥", "account"),
        ],
    ),
]

# 文件名 → group（页头强制使用）
PAGE_GROUP_MAP: Dict[str, str] = {}
PAGE_TITLE_MAP: Dict[str, str] = {}
_PAGE_SECTION_MAP: Dict[str, str] = {}
for _sec, items in NAV_GROUPS:
    for path, title, _icon, group in items:
        key = path.replace("\\", "/").split("/")[-1]
        PAGE_GROUP_MAP[key] = group
        PAGE_TITLE_MAP[key] = title
        PAGE_GROUP_MAP[path] = group
        _PAGE_SECTION_MAP[key] = _sec
        _PAGE_SECTION_MAP[path] = _sec


# ============================================================
# 套餐权限门槛（托管版 EDITION=cloud 生效）
# ============================================================
#
# 菜单在侧栏始终「显性保留」，未订阅用户也能看见；
# 点击进入后由 core.middleware.require_feature_access 渲染「请进行订阅」引导页。
#
# 档位由低到高：free(免费版) < plus(个人版) < pro(专业版) < enterprise(企业版)
# 调整门槛只需改这张表。

GROUP_REQUIRED_TIER: Dict[str, str] = {
    "深度分析": "pro",        # FAMAS 深度分析 / 新闻情绪 / Brinson 归因
    "持仓组合": "pro",        # 我的组合 / 组合诊断 / 资产配置 / 持仓漂移 / 赛道再平衡
    "监控预警": "enterprise",  # 持续监控 / 预警规则 / 信号跟踪 / 通知配置
}

TIER_RANK: Dict[str, int] = {
    "free": 0,
    "plus": 1,
    "pro": 2,
    "enterprise": 3,
}


def tier_rank(tier: Optional[str]) -> int:
    """档位 → 数字等级（未知档位按 free 处理）。"""
    return TIER_RANK.get((tier or "free").strip().lower(), 0)


def tier_meets(user_tier: Optional[str], required_tier: Optional[str]) -> bool:
    """用户档位是否达到要求。required 为空表示不限制。"""
    if not required_tier:
        return True
    return tier_rank(user_tier) >= tier_rank(required_tier)


def required_tier_for(page_or_group: str) -> Optional[str]:
    """查询某页面/分组所需的订阅档位；无需订阅返回 None。

    参数可以是中文栏目名（"持仓组合"）、文件名（"19_组合管理.py"）
    或完整路径（"pages/19_组合管理.py"）。
    """
    if not page_or_group:
        return None
    key = str(page_or_group).replace("\\", "/")
    # 1) 直接是栏目名
    if key in GROUP_REQUIRED_TIER:
        return GROUP_REQUIRED_TIER[key]
    # 2) 页面路径/文件名 → 中文栏目 → 门槛
    sec = _PAGE_SECTION_MAP.get(key) or _PAGE_SECTION_MAP.get(key.split("/")[-1])
    if sec:
        return GROUP_REQUIRED_TIER.get(sec)
    # 3) 兜底：兼容传入 accent group_key（portfolio / monitor ...）
    return GROUP_REQUIRED_TIER.get(group_for_page(key))


def locked_pages_for(tier: Optional[str]) -> List[str]:
    """当前档位下仍被锁定的页面文件名列表（用于侧栏打标记）。"""
    locked: List[str] = []
    for _sec, items in NAV_GROUPS:
        req = GROUP_REQUIRED_TIER.get(_sec)
        if req and not tier_meets(tier, req):
            locked.extend(path.replace("\\", "/").split("/")[-1] for path, *_ in items)
    return locked



def group_for_page(filename_or_path: str) -> str:
    p = filename_or_path.replace("\\", "/")
    if p in PAGE_GROUP_MAP:
        return PAGE_GROUP_MAP[p]
    base = p.split("/")[-1]
    return PAGE_GROUP_MAP.get(base, "screen")


def section_for_page(filename_or_path: str) -> str:
    """返回页面所属的中文栏目名（如 "持仓组合"）；未知返回空串。"""
    p = str(filename_or_path).replace("\\", "/")
    if p in _PAGE_SECTION_MAP:
        return _PAGE_SECTION_MAP[p]
    return _PAGE_SECTION_MAP.get(p.split("/")[-1], "")


def pages_in_section(section: str) -> List[str]:
    """某栏目下的页面标题列表（用于订阅引导页展示解锁范围）。"""
    for sec, items in NAV_GROUPS:
        if sec == section:
            return [title for _path, title, _icon, _g in items]
    return []


def _nav_user_tier() -> str:
    """导航构建时读取当前用户档位。

    app.py 在页面脚本执行前构建侧栏，此时 st.session_state["user"]
    可能尚未恢复（登录态由 require_auth 从 token 还原），因此这里
    自行尝试从 session / URL token 解析一次，并按会话缓存结果。
    """
    try:
        import streamlit as st
    except Exception:
        return "free"

    cached = st.session_state.get("_nav_user_tier")
    if cached:
        return cached

    tier = "free"
    user = st.session_state.get("user")
    if user:
        tier = (user.get("tier") or "free").lower()
    else:
        try:
            from core.auth import AuthManager
            from core.user_repo import UserRepo

            token = st.session_state.get("auth_token", "") or st.query_params.get("auth", "")
            if token:
                payload = AuthManager.verify_token(token)
                if payload:
                    u = UserRepo().get_by_id(payload["user_id"])
                    if u:
                        tier = (u.get("tier") or "free").lower()
                        # 顺手把用户写回 session，避免下面各页重复查库
                        st.session_state["user"] = {k: v for k, v in u.items() if k != "password_hash"}
                        st.session_state["auth_token"] = token
        except Exception:
            pass

    st.session_state["_nav_user_tier"] = tier
    return tier


def build_streamlit_nav(home_page, *, include_admin: bool = True) -> Dict[str, list]:
    """构造 st.navigation 字典。home_page 为工作台 st.Page。

    托管版下，未订阅足够档位的菜单仍会展示（显性保留），
    仅在标题后追加 🔒 提示需要订阅；点击后由页面守卫渲染订阅引导。
    """
    import streamlit as st

    from core.middleware import is_cloud_edition

    gating_on = is_cloud_edition()
    tier = _nav_user_tier() if gating_on else "enterprise"

    _PAGE_REGISTRY.clear()

    nav: Dict[str, list] = {
        "今日看板": [home_page],
    }
    for section, items in NAV_GROUPS:
        required = GROUP_REQUIRED_TIER.get(section) if gating_on else None
        section_locked = bool(required) and not tier_meets(tier, required)
        pages = []
        for path, title, icon, _group in items:
            if path.endswith("97_用户管理.py") and not include_admin:
                continue
            label = f"{title} 🔒" if section_locked else title
            page = st.Page(path, title=label, icon=icon)
            _register_page(path, page)
            pages.append(page)
        if section == "今日看板":
            nav["今日看板"].extend(pages)
        else:
            nav[section] = pages
    return nav


# ============================================================
# 页面对象注册表
# ------------------------------------------------------------
# Streamlit 的 st.page_link / st.switch_page 只接受 st.Page 返回的
# StreamlitPage 对象；传文件路径字符串时，其内部按 os.path.realpath 比对
# 注册表，路径形态稍有差异就会抛 StreamlitPageNotFoundError，把整页打成
# 红色报错框。此处缓存 build_streamlit_nav 建好的页面对象，供页面内跳转
# 复用，彻底绕开该字符串匹配问题。
# ============================================================

_PAGE_REGISTRY: Dict[str, Any] = {}


def _register_page(path: str, page: Any) -> None:
    """登记页面对象，同时支持「完整路径」与「文件名」两种键。"""
    key = str(path).replace("\\", "/")
    _PAGE_REGISTRY[key] = page
    _PAGE_REGISTRY[key.split("/")[-1]] = page


def get_page(path_or_name: str):
    """按路径或文件名取回已注册的 StreamlitPage；未注册时返回 None。

    返回 None 的典型场景：管理员页面在当前用户下被 include_admin 过滤掉。
    """
    if not path_or_name:
        return None
    key = str(path_or_name).replace("\\", "/")
    return _PAGE_REGISTRY.get(key) or _PAGE_REGISTRY.get(key.split("/")[-1])


def has_page(path_or_name: str) -> bool:
    """该页面当前是否已注册（用于决定是否渲染入口，避免出现死链接）。"""
    return get_page(path_or_name) is not None


def safe_page_link(path_or_name: str, **kwargs) -> bool:
    """渲染指向内部页面的链接；页面未注册时不渲染并返回 False。

    st.page_link 传字符串路径会因注册表比对失败而抛错，故统一走页面对象。
    """
    import streamlit as st

    page = get_page(path_or_name)
    if page is None:
        return False
    try:
        st.page_link(page, **kwargs)
    except Exception as e:  # 兜底：任何情况下都不应让整页报错
        logger.warning(f"page_link 失败 ({path_or_name}): {e}")
        return False
    return True


def safe_switch_page(path_or_name: str) -> bool:
    """跳转到内部页面；页面未注册时返回 False（调用方自行提示）。"""
    import streamlit as st

    page = get_page(path_or_name)
    if page is None:
        return False
    try:
        st.switch_page(page)
    except Exception as e:
        logger.warning(f"switch_page 失败 ({path_or_name}): {e}")
        return False
    return True



def workbench_quick_links() -> List[Tuple[str, str, str]]:
    """工作台精简快捷入口 (icon, label, path)。"""
    return [
        ("📡", "市场仪表盘", "pages/13_实时市场仪表盘.py"),
        ("🌊", "主题资金", "pages/28_主题资金流雷达.py"),
        ("🔬", "FAMAS", "pages/08_FAMAS单基金深度分析.py"),
        ("💼", "我的组合", "pages/19_组合管理.py"),
        ("🚨", "监控预警", "pages/09_持续监控预警.py"),
        ("🏆", "排名精选", "pages/10_基金排名精选.py"),
        ("📡", "盘中估值", "pages/27_盘中估值中心.py"),
        ("📚", "分析历史", "pages/22_分析历史.py"),
        ("⚔️", "基金 PK", "pages/11_基金PK擂台.py"),
        ("⚖️", "赛道再平衡", "pages/30_赛道再平衡.py"),
    ]
