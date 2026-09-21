"""
全局浅色 / 深色主题
====================
通过侧边栏按钮切换，session_state 保持当前会话内偏好。
"""

from __future__ import annotations

from typing import Dict

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

THEME_KEY = "color_mode"

LIGHT_TOKENS: Dict[str, str] = {
    "--bg-primary": "#F8FAFC",
    "--bg-card": "#FFFFFF",
    "--text-primary": "#1E293B",
    "--text-secondary": "#64748B",
    "--text-muted": "#94A3B8",
    "--text-heading": "#0F172A",
    "--text-h2": "#1E293B",
    "--text-h3": "#334155",
    "--border-light": "#E2E8F0",
    "--border-medium": "#CBD5E1",
    "--sidebar-bg": "#F1F5F9",
    "--sidebar-text": "#334155",
    "--sidebar-heading": "#1E293B",
    "--toolbar-bg": "linear-gradient(135deg, #F8FAFC 0%, #EFF6FF 100%)",
    "--toolbar-border": "#E2E8F0",
    "--metric-value": "#0F172A",
    "--scrollbar-thumb": "#CBD5E1",
    "--scrollbar-hover": "#94A3B8",
    "--index-bar-bg": "#F8FAFC",
    "--index-bar-border": "#E2E8F0",
    "--risk-bg": "linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%)",
    "--risk-border": "#FCD34D",
    "--risk-title": "#92400E",
    "--risk-body": "#A16207",
    "--step-n1-bg": "#EFF6FF",
    "--step-n2-bg": "#FFFBEB",
    "--step-n3-bg": "#ECFDF5",
    "--header-shadow": "0 1px 3px rgba(0,0,0,0.04)",
    "--widget-bg": "#FFFFFF",
    "--widget-text": "#1E293B",
    "--plot-grid": "#EEF2F7",
    "--plot-axis": "#E2E8F0",
    "--plot-font": "#1E293B",
    "--plot-hover-bg": "#FFFFFF",
    "--code-bg": "#F1F5F9",
    "--link-color": "#2563EB",
}

DARK_TOKENS: Dict[str, str] = {
    "--bg-primary": "#0B1220",
    "--bg-card": "#111827",
    "--text-primary": "#F1F5F9",
    "--text-secondary": "#CBD5E1",
    "--text-muted": "#94A3B8",
    "--text-heading": "#FFFFFF",
    "--text-h2": "#F1F5F9",
    "--text-h3": "#E2E8F0",
    "--border-light": "#334155",
    "--border-medium": "#475569",
    "--sidebar-bg": "#0F172A",
    "--sidebar-text": "#E2E8F0",
    "--sidebar-heading": "#F8FAFC",
    "--toolbar-bg": "linear-gradient(135deg, #111827 0%, #0F172A 100%)",
    "--toolbar-border": "#334155",
    "--metric-value": "#FFFFFF",
    "--scrollbar-thumb": "#475569",
    "--scrollbar-hover": "#64748B",
    "--index-bar-bg": "#111827",
    "--index-bar-border": "#334155",
    "--risk-bg": "linear-gradient(135deg, #422006 0%, #451a03 100%)",
    "--risk-border": "#92400E",
    "--risk-title": "#FCD34D",
    "--risk-body": "#FDE68A",
    "--step-n1-bg": "#1E3A5F",
    "--step-n2-bg": "#422006",
    "--step-n3-bg": "#064E3B",
    "--header-shadow": "0 1px 3px rgba(0,0,0,0.35)",
    "--widget-bg": "#1F2937",
    "--widget-text": "#F1F5F9",
    "--link-color": "#60A5FA",
    "--plot-grid": "#334155",
    "--plot-axis": "#475569",
    "--plot-font": "#F1F5F9",
    "--plot-hover-bg": "#1F2937",
    "--code-bg": "#1E293B",
}

_FUND_PLOTLY_LIGHT = go.layout.Template(
    layout=dict(
        font=dict(
            family="-apple-system, 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', sans-serif",
            size=13,
            color="#1E293B",
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=["#2563EB", "#3B82F6", "#60A5FA", "#94A3B8", "#CBD5E1"],
        xaxis=dict(gridcolor="#EEF2F7", zerolinecolor="#E2E8F0", linecolor="#E2E8F0", automargin=True),
        yaxis=dict(gridcolor="#EEF2F7", zerolinecolor="#E2E8F0", linecolor="#E2E8F0", automargin=True),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#E2E8F0", font=dict(color="#1E293B", size=12)),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=40, b=10),
    )
)

_FUND_PLOTLY_DARK = go.layout.Template(
    layout=dict(
        font=dict(
            family="-apple-system, 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', sans-serif",
            size=13,
            color="#F1F5F9",
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=["#60A5FA", "#3B82F6", "#2563EB", "#94A3B8", "#64748B"],
        xaxis=dict(gridcolor="#1F2937", zerolinecolor="#374151", linecolor="#374151", automargin=True),
        yaxis=dict(gridcolor="#1F2937", zerolinecolor="#374151", linecolor="#374151", automargin=True),
        hoverlabel=dict(bgcolor="#1F2937", bordercolor="#374151", font=dict(color="#E2E8F0", size=12)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#E2E8F0")),
        margin=dict(l=10, r=10, t=40, b=10),
    )
)

pio.templates["fund_theme"] = _FUND_PLOTLY_LIGHT
pio.templates["fund_theme_dark"] = _FUND_PLOTLY_DARK


def get_color_mode() -> str:
    if THEME_KEY not in st.session_state:
        # 优先从云端偏好恢复
        try:
            if st.session_state.get("user"):
                from core.user_workspace import get_color_mode_pref
                pref = get_color_mode_pref()
                if pref in ("light", "dark"):
                    st.session_state[THEME_KEY] = pref
                    return pref
        except Exception:
            pass
        st.session_state[THEME_KEY] = "light"
    return st.session_state[THEME_KEY]


def is_dark_mode() -> bool:
    return get_color_mode() == "dark"


def _tokens() -> Dict[str, str]:
    return DARK_TOKENS if is_dark_mode() else LIGHT_TOKENS


def page_header_colors() -> Dict[str, str]:
    t = _tokens()
    return {
        "card_bg": t["--bg-card"],
        "border": t["--border-light"],
        "title": t["--text-heading"],
        "desc": t["--text-secondary"],
        "shadow": t["--header-shadow"],
    }


def surface_colors() -> Dict[str, str]:
    """内联 HTML / 小组件用色。"""
    t = _tokens()
    return {
        "card_bg": t["--bg-card"],
        "border": t["--border-light"],
        "label": t["--text-muted"],
        "value": t["--text-primary"],
        "heading": t["--text-heading"],
        "muted": t["--text-muted"],
        "reasoning": t["--text-secondary"],
        "code_bg": t["--code-bg"],
    }


def status_badge_palette() -> Dict[str, tuple]:
    """状态徽章 (前景色, 背景色, 标签)。"""
    if is_dark_mode():
        return {
            "success": ("#6EE7B7", "#064E3B", "✅ 正常"),
            "warning": ("#FCD34D", "#422006", "⚠️ 关注"),
            "danger": ("#FCA5A5", "#450A0A", "❌ 风险"),
            "info": ("#93C5FD", "#1E3A5F", "ℹ️ 信息"),
            "neutral": ("#CBD5E1", "#1F2937", "—"),
        }
    return {
        "success": ("#059669", "#ECFDF5", "✅ 正常"),
        "warning": ("#D97706", "#FFFBEB", "⚠️ 关注"),
        "danger": ("#DC2626", "#FEF2F2", "❌ 风险"),
        "info": ("#2563EB", "#EFF6FF", "ℹ️ 信息"),
        "neutral": ("#64748B", "#F8FAFC", "—"),
    }


def apply_plotly_theme() -> None:
    if is_dark_mode():
        pio.templates.default = "fund_theme_dark"
    else:
        pio.templates.default = "plotly_white+fund_theme"


def render_theme_toggle() -> None:
    """侧边栏主题切换按钮。"""
    mode = get_color_mode()
    label = "🌙 切换深色模式" if mode == "light" else "☀️ 切换浅色模式"
    if st.button(label, key="ui_theme_toggle", use_container_width=True):
        new_mode = "dark" if mode == "light" else "light"
        st.session_state[THEME_KEY] = new_mode
        try:
            if st.session_state.get("user"):
                from core.user_workspace import set_color_mode_pref
                set_color_mode_pref(new_mode)
        except Exception:
            pass
        apply_plotly_theme()
        st.rerun()


def _css_vars_block(tokens: Dict[str, str]) -> str:
    return "\n".join(f"    {k}: {v};" for k, v in tokens.items())


def _build_global_css(tokens: Dict[str, str], *, dark: bool) -> str:
    vars_block = _css_vars_block(tokens)
    dark_overrides = _DARK_STREAMLIT_OVERRIDES if dark else ""
    return f"""
<style>
:root {{
{vars_block}
    --accent-gold: #C8963E;
    --accent-blue: #2563EB;
    --accent-green: #10B981;
    --accent-red: #EF4444;
    --accent-amber: #F59E0B;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
    --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.07), 0 2px 4px -2px rgba(0,0,0,0.05);
    --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.08), 0 4px 6px -4px rgba(0,0,0,0.04);
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 16px;
}}

.stApp {{ background: var(--bg-primary); color: var(--text-primary); }}
.stMarkdown {{ color: var(--text-primary); line-height: 1.6; }}
.stCaption {{ color: var(--text-muted) !important; }}

[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] ol,
[data-testid="stMarkdownContainer"] ul,
[data-testid="stMarkdownContainer"] span {{
    color: var(--text-primary);
}}
[data-testid="stMarkdownContainer"] strong {{
    color: var(--text-heading);
}}
[data-testid="stMarkdownContainer"] a {{
    color: var(--link-color);
}}

[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label,
label[data-testid="stWidgetLabel"] {{
    color: var(--text-primary) !important;
}}

.stMain .block-container {{ padding-top: 0.5rem !important; color: var(--text-primary); }}

.global-toolbar {{
    background: var(--toolbar-bg);
    border: 1px solid var(--toolbar-border);
    border-radius: 10px;
    padding: 0.5rem 1rem;
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    font-size: 0.85rem;
    flex-wrap: wrap;
}}
.global-toolbar .tb-sep {{ color: var(--border-medium); }}

.index-ticker-bar {{
    background: var(--index-bar-bg);
    border: 1px solid var(--index-bar-border);
    border-radius: 10px;
    padding: 0.75rem 1.25rem;
    margin-bottom: 1.5rem;
    overflow-x: auto;
    font-size: 0.9rem;
    color: var(--text-primary);
}}

[data-testid="stSidebar"] {{ background: var(--sidebar-bg) !important; }}
[data-testid="stSidebar"] .stMarkdown {{ color: var(--sidebar-text) !important; }}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
    color: var(--sidebar-heading) !important;
}}
[data-testid="stSidebar"] [data-testid="stMetricValue"] {{ color: var(--sidebar-heading) !important; }}
[data-testid="stSidebar"] [data-testid="stMetricDelta"] {{ color: var(--accent-gold) !important; }}
[data-testid="stSidebar"] hr {{ border-color: var(--border-medium); }}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {{
    color: var(--sidebar-text) !important;
}}
[data-testid="stSidebarNav"] a,
[data-testid="stSidebarNav"] span,
[data-testid="stSidebarNav"] p {{
    color: var(--sidebar-heading) !important;
}}
[data-testid="stSidebar"] a {{
    color: var(--sidebar-heading) !important;
    text-decoration: none !important;
    font-weight: 500 !important;
}}
[data-testid="stSidebar"] a:hover {{
    color: var(--sidebar-heading) !important;
    background: rgba(128,128,128,0.12);
    border-radius: 6px;
}}
[data-testid="stSidebar"] .stButton > button:not([kind="primary"]) {{
    background-color: var(--widget-bg) !important;
    color: var(--widget-text) !important;
    border-color: var(--border-light) !important;
}}

h1 {{ font-weight: 700 !important; font-size: 1.75rem !important; color: var(--text-heading) !important; letter-spacing: -0.02em; }}
h2 {{ font-weight: 600 !important; font-size: 1.35rem !important; color: var(--text-h2) !important; letter-spacing: -0.01em; }}
h3 {{ font-weight: 600 !important; font-size: 1.1rem !important; color: var(--text-h3) !important; }}

.hero-section {{
    background: linear-gradient(135deg, #0F1A2E 0%, #1E3A5F 50%, #2D5A8E 100%);
    border-radius: var(--radius-lg);
    padding: 2.5rem 2rem;
    margin-bottom: 2rem;
    position: relative;
    overflow: hidden;
}}
.hero-title {{ font-size: 2rem !important; font-weight: 800 !important; color: #F8FAFC !important; margin-bottom: 0.5rem; letter-spacing: -0.03em; }}
.hero-subtitle {{ font-size: 1rem; color: #94A3B8; line-height: 1.7; }}
.hero-subtitle strong {{ color: var(--accent-gold); font-weight: 600; }}

.card {{
    background: var(--bg-card);
    border-radius: var(--radius-md);
    padding: 1.5rem;
    border: 1px solid var(--border-light);
    box-shadow: var(--shadow-sm);
    transition: box-shadow 0.2s, transform 0.2s;
    height: 100%;
}}
.card:hover {{ box-shadow: var(--shadow-md); transform: translateY(-1px); }}
.card-title {{ font-weight: 600; color: var(--text-primary); margin-bottom: 0.5rem; }}
.card-body {{ color: var(--text-secondary); font-size: 0.9rem; line-height: 1.6; }}
.card-footer {{
    color: var(--text-muted);
    font-size: 0.8rem;
    margin-top: 0.75rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--border-light);
}}
.card-accent {{ border-left: 3px solid var(--accent-gold); }}

.stat-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 1rem; margin: 1.5rem 0; }}
.stat-item {{
    background: var(--bg-card);
    border-radius: var(--radius-md);
    padding: 1.25rem 1rem;
    text-align: center;
    border: 1px solid var(--border-light);
    box-shadow: var(--shadow-sm);
}}
.stat-value {{ font-size: 2rem; font-weight: 700; color: var(--metric-value); line-height: 1.2; }}
.stat-label {{ font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.25rem; }}
.stat-delta {{ font-size: 0.75rem; color: var(--accent-blue); margin-top: 0.15rem; }}

.step-card {{
    background: var(--bg-card);
    border-radius: var(--radius-md);
    padding: 1.5rem;
    border: 1px solid var(--border-light);
    box-shadow: var(--shadow-sm);
    height: 100%;
    position: relative;
    overflow: hidden;
}}
.step-card::after {{
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 3px;
}}
.step-card.card-step1::after {{ background: var(--accent-blue); }}
.step-card.card-step2::after {{ background: var(--accent-gold); }}
.step-card.card-step3::after {{ background: var(--accent-green); }}
.step-number {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px; height: 28px;
    border-radius: 50%;
    font-weight: 700;
    font-size: 0.85rem;
    margin-bottom: 0.75rem;
}}
.step-number.n1 {{ background: var(--step-n1-bg); color: var(--accent-blue); }}
.step-number.n2 {{ background: var(--step-n2-bg); color: var(--accent-gold); }}
.step-number.n3 {{ background: var(--step-n3-bg); color: var(--accent-green); }}

.section-divider {{ border: none; height: 1px; background: var(--border-light); margin: 2rem 0; }}

.risk-disclaimer {{
    background: var(--risk-bg);
    border: 1px solid var(--risk-border);
    border-radius: var(--radius-md);
    padding: 1.25rem 1.5rem;
    margin: 2rem 0;
}}
.risk-disclaimer .title {{ color: var(--risk-title); font-weight: 700; margin-bottom: 0.5rem; }}
.risk-disclaimer .body {{ color: var(--risk-body); font-size: 0.85rem; line-height: 1.7; }}

.app-footer {{
    text-align: center;
    padding: 1.5rem 0;
    margin-top: 2rem;
    border-top: 1px solid var(--border-light);
    color: var(--text-muted);
    font-size: 0.8rem;
}}

.stButton > button {{ border-radius: var(--radius-sm) !important; font-weight: 500 !important; }}
.stButton > button[kind="primary"] {{
    background: var(--accent-blue) !important;
    border: none !important;
    color: #FFFFFF !important;
}}
.stButton > button:not([kind="primary"]) {{
    background-color: var(--widget-bg) !important;
    color: var(--widget-text) !important;
    border: 1px solid var(--border-light) !important;
}}
.stDownloadButton > button {{
    background-color: var(--widget-bg) !important;
    color: var(--widget-text) !important;
    border: 1px solid var(--border-light) !important;
}}

[data-testid="stMetric"] {{
    background: var(--bg-card);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-sm);
    padding: 0.75rem 1rem !important;
    box-shadow: var(--shadow-sm);
}}
[data-testid="stMetricValue"] {{ font-weight: 700 !important; color: var(--metric-value) !important; }}
[data-testid="stMetricLabel"] {{ color: var(--text-secondary) !important; }}

[data-testid="stExpander"] {{
    border: 1px solid var(--border-light) !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm);
    background: var(--bg-card);
}}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p {{
    color: var(--text-primary) !important;
}}

[data-testid="stDataFrame"],
[data-testid="stTable"] {{
    background: var(--bg-card) !important;
    border: 1px solid var(--border-light);
    border-radius: var(--radius-sm);
}}
[data-testid="stDataFrame"] [data-testid="glideDataEditor"],
[data-testid="stDataFrame"] canvas {{
    background: var(--bg-card) !important;
}}

.stCode, pre, code {{
    background-color: var(--code-bg) !important;
    color: var(--text-primary) !important;
}}

button[data-baseweb="tab"] {{
    color: var(--text-secondary) !important;
    background: transparent !important;
}}
button[data-baseweb="tab"][aria-selected="true"] {{
    color: var(--text-heading) !important;
    border-bottom-color: var(--accent-blue) !important;
}}

[data-testid="stRadio"] label span,
[data-testid="stCheckbox"] label span,
[data-testid="stRadio"] label p,
[data-testid="stCheckbox"] label p {{
    color: var(--text-primary) !important;
}}

[data-testid="stStatusWidget"] {{
    background: var(--bg-card) !important;
    border: 1px solid var(--border-light) !important;
}}
[data-testid="stStatusWidget"] label,
[data-testid="stStatusWidget"] [data-testid="stMarkdownContainer"] p {{
    color: var(--text-primary) !important;
}}

[data-testid="stFileUploader"] label,
[data-testid="stFileUploader"] small,
[data-testid="stFileUploader"] span {{
    color: var(--text-secondary) !important;
}}

[data-baseweb="tag"] {{
    background: var(--border-medium) !important;
    color: var(--text-primary) !important;
}}

[data-testid="stToolbar"] {{ display: none !important; }}
[data-testid="stDeployButton"] {{ display: none !important; }}

.stTextInput input, .stTextArea textarea, .stNumberInput input {{
    background-color: var(--widget-bg) !important;
    color: var(--widget-text) !important;
    border-color: var(--border-light) !important;
}}
[data-baseweb="select"] > div {{
    background-color: var(--widget-bg) !important;
    border-color: var(--border-light) !important;
}}
[data-baseweb="select"] span {{ color: var(--widget-text) !important; }}

@media (min-width: 769px) {{
    button[data-testid="baseButton-headerNoPadding"] {{ display: none !important; }}
    [data-testid="collapsedControl"] {{ display: none !important; }}
    section[data-testid="stSidebar"] {{
        display: flex !important;
        width: 21rem !important;
        min-width: 21rem !important;
    }}
}}

::-webkit-scrollbar {{ width: 6px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--scrollbar-thumb); border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--scrollbar-hover); }}

hr {{ border-color: var(--border-light) !important; margin: 1.5rem 0 !important; }}

#back-to-top {{
    position: fixed; bottom: 2rem; right: 2rem;
    width: 44px; height: 44px;
    background: var(--accent-blue); color: #fff;
    border: none; border-radius: 50%;
    font-size: 1.2rem; cursor: pointer;
    opacity: 0; visibility: hidden;
    transition: opacity 0.3s, visibility 0.3s;
    z-index: 9999;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    display: flex; align-items: center; justify-content: center;
}}
#back-to-top.show {{ opacity: 1; visibility: visible; }}
#back-to-top:hover {{ background: #1D4ED8; }}

@media (max-width: 768px) {{
    .stMain .block-container {{ padding: 1rem !important; }}
    .stat-grid {{ grid-template-columns: repeat(2, 1fr); gap: 0.5rem; }}
    .hero-section {{ padding: 1.5rem 1.25rem; }}
    .hero-title {{ font-size: 1.5rem !important; }}
    .fin-kpi-row, .fin-quote-row {{ grid-template-columns: repeat(2, 1fr); }}
}}

/* ---- 金融专业风：紧凑分区 / KPI / 报价条 ---- */
.fin-sec {{
    display: flex; align-items: baseline; justify-content: space-between; gap: 0.75rem;
    margin: 1rem 0 0.5rem; padding-bottom: 0.35rem;
    border-bottom: 1px solid var(--border-light);
}}
.fin-sec-title {{
    font-size: 0.92rem; font-weight: 700; color: var(--text-heading);
    letter-spacing: 0.02em; margin: 0;
}}
.fin-sec-sub {{ font-size: 0.74rem; color: var(--text-muted); white-space: nowrap; }}
.fin-toolbar {{
    display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
    gap: 0.65rem; background: var(--bg-card); border: 1px solid var(--border-light);
    border-radius: 10px; padding: 0.5rem 0.85rem; margin-bottom: 0.75rem;
}}
.fin-toolbar-meta {{ font-size: 0.78rem; color: var(--text-secondary); }}
.fin-pill {{
    display: inline-flex; align-items: center; gap: 0.2rem;
    font-size: 0.7rem; font-weight: 650; padding: 0.12rem 0.5rem; border-radius: 999px;
    border: 1px solid var(--border-light); color: var(--text-secondary); background: var(--bg-primary);
}}
.fin-pill.live {{ color: #059669; border-color: #A7F3D0; background: #ECFDF5; }}
.fin-pill.closed {{ color: #64748B; background: var(--bg-primary); }}
.fin-pill.warn {{ color: #B45309; border-color: #FCD34D; background: #FFFBEB; }}
.fin-kpi-row {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
    gap: 0.45rem; margin: 0 0 0.7rem;
}}
.fin-kpi {{
    background: var(--bg-card); border: 1px solid var(--border-light);
    border-radius: 8px; padding: 0.5rem 0.6rem;
}}
.fin-kpi .l {{
    font-size: 0.66rem; color: var(--text-muted); letter-spacing: 0.04em;
    text-transform: uppercase; margin-bottom: 0.15rem;
}}
.fin-kpi .v {{
    font-size: 1.02rem; font-weight: 700; color: var(--metric-value);
    font-variant-numeric: tabular-nums; line-height: 1.2;
}}
.fin-kpi .d {{
    font-size: 0.7rem; font-weight: 600; margin-top: 0.12rem;
    font-variant-numeric: tabular-nums;
}}
.fin-kpi .d.up, .fin-up {{ color: #DC2626 !important; }}
.fin-kpi .d.down, .fin-down {{ color: #16A34A !important; }}
.fin-kpi .d.muted {{ color: var(--text-muted); }}
.fin-quote-row {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
    gap: 0.4rem; margin: 0 0 0.7rem;
}}
.fin-quote {{
    text-align: center; background: var(--bg-card); border: 1px solid var(--border-light);
    border-radius: 8px; padding: 0.45rem 0.25rem; border-top: 2px solid var(--border-medium);
}}
.fin-quote.up {{ border-top-color: #DC2626; }}
.fin-quote.down {{ border-top-color: #16A34A; }}
.fin-quote .n {{ font-size: 0.66rem; color: var(--text-muted); margin-bottom: 0.1rem; }}
.fin-quote .p {{
    font-size: 0.95rem; font-weight: 700; color: var(--text-heading);
    font-variant-numeric: tabular-nums;
}}
.fin-quote .c {{
    font-size: 0.76rem; font-weight: 650; font-variant-numeric: tabular-nums;
}}
.fin-callout {{
    background: var(--bg-card); border: 1px solid var(--border-light);
    border-left: 3px solid var(--accent-blue); border-radius: 0 8px 8px 0;
    padding: 0.5rem 0.8rem; margin: 0.4rem 0 0.75rem; font-size: 0.84rem;
    color: var(--text-primary);
}}
.fin-callout.warn {{ border-left-color: #D97706; }}
.fin-callout.danger {{ border-left-color: #DC2626; }}
.fin-panel {{
    background: var(--bg-card); border: 1px solid var(--border-light);
    border-radius: 10px; padding: 0.7rem 0.85rem; margin-bottom: 0.65rem;
}}
.fin-panel-h {{
    display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;
    margin-bottom: 0.45rem;
}}
.fin-panel-title {{
    font-size: 0.78rem; font-weight: 700; color: var(--text-heading);
    letter-spacing: 0.03em; margin: 0;
}}
.fin-meta {{ font-size: 0.72rem; color: var(--text-muted); margin: 0 0 0.4rem; }}
.fin-wb-title {{
    font-size: 1.15rem; font-weight: 750; color: var(--text-heading);
    margin: 0.15rem 0 0.65rem; letter-spacing: 0.01em;
}}
.fin-wb-title span {{ color: var(--text-muted); font-weight: 500; font-size: 0.85rem; }}
{dark_overrides}
</style>
"""


_DARK_STREAMLIT_OVERRIDES = """
/* 深色：强制覆盖 Streamlit 内置浅色文字 */
.stApp, .stApp [data-testid="stAppViewContainer"], .main {{
    color: #F1F5F9 !important;
}}
.stMain p, .stMain span, .stMain label, .stMain div {{
    color: inherit;
}}
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span,
[data-testid="stMarkdownContainer"] div {{
    color: #F1F5F9 !important;
}}
[data-testid="stMetricDelta"] {{
    color: #FCA5A5 !important;
}}
[data-testid="stMetricDelta"][data-testid="stMetricDelta"] svg {{
    fill: currentColor;
}}
div[data-testid="stAlert"] p,
div[data-testid="stNotification"] p {{
    color: inherit !important;
}}
.stSlider [data-testid="stThumbValue"],
.stSlider label {{
    color: #F1F5F9 !important;
}}
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stMultiSelect"] [data-baseweb="select"] > div {{
    background-color: #1F2937 !important;
    color: #F1F5F9 !important;
}}
[data-testid="stSelectbox"] svg,
[data-testid="stMultiSelect"] svg {{
    fill: #CBD5E1 !important;
}}
[data-testid="stNumberInput"] input {{
    background-color: #1F2937 !important;
    color: #F1F5F9 !important;
}}
"""


def inject_global_theme_css() -> None:
    """注入全局主题 CSS（须在 set_page_config 之后调用）。"""
    apply_plotly_theme()
    dark = is_dark_mode()
    st.markdown(_build_global_css(DARK_TOKENS if dark else LIGHT_TOKENS, dark=dark), unsafe_allow_html=True)
