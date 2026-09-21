"""
全站导航目录（P0）
================
单一数据源：侧栏 st.navigation 分组 + 页头 group 色板映射。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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
for _sec, items in NAV_GROUPS:
    for path, title, _icon, group in items:
        key = path.replace("\\", "/").split("/")[-1]
        PAGE_GROUP_MAP[key] = group
        PAGE_TITLE_MAP[key] = title
        PAGE_GROUP_MAP[path] = group


def group_for_page(filename_or_path: str) -> str:
    p = filename_or_path.replace("\\", "/")
    if p in PAGE_GROUP_MAP:
        return PAGE_GROUP_MAP[p]
    base = p.split("/")[-1]
    return PAGE_GROUP_MAP.get(base, "screen")


def build_streamlit_nav(home_page, *, include_admin: bool = True) -> Dict[str, list]:
    """构造 st.navigation 字典。home_page 为工作台 st.Page。"""
    import streamlit as st

    nav: Dict[str, list] = {
        "今日看板": [home_page],
    }
    for section, items in NAV_GROUPS:
        pages = []
        for path, title, icon, _group in items:
            if path.endswith("97_用户管理.py") and not include_admin:
                continue
            pages.append(st.Page(path, title=title, icon=icon))
        if section == "今日看板":
            nav["今日看板"].extend(pages)
        else:
            nav[section] = pages
    return nav


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
