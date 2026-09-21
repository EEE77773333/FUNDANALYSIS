"""
分享阅读 — 页面 31
================
通过 ?share=TOKEN 只读查看分析历史，无需登录。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import streamlit as st
from core.ui_components import section_header

from core.share_links import get_share_payload

section_header("分享阅读（只读）")
token = st.query_params.get("share", "") or ""

if not token:
    token = st.text_input("粘贴分享 token", key="share_token_input", placeholder="从分享链接的 share= 参数复制")
    st.caption("完整链接示例：`https://你的域名/分享阅读?share=xxxx`")
    if not token:
        st.stop()

payload = get_share_payload(token.strip())
if not payload:
    st.error("链接无效")
    st.stop()

if payload.get("error"):
    st.error(payload["error"])
    st.stop()

st.info(
    f"只读分享 · 过期 {payload.get('expires_at')} · 已阅 {payload.get('view_count', 0)} 次。"
    " 内容已脱敏，不构成投资建议。"
)

st.markdown(f"## {payload.get('title') or '分析报告'}")
st.caption(
    f"{payload.get('page_name', '')} · "
    f"{payload.get('fund_code', '')} {payload.get('fund_name', '')} · "
    f"{payload.get('created_at', '')} · {payload.get('model', '')}"
)

dash_raw = payload.get("structured_result_json") or ""
if dash_raw:
    try:
        from core.decision_renderer import render_decision_dashboard
        dash = json.loads(dash_raw)
        if isinstance(dash, dict) and dash:
            render_decision_dashboard(dash, expanded=True)
            st.markdown("---")
    except Exception:
        pass

content = payload.get("result_content") or ""
max_display = 12000
if len(content) > max_display:
    st.caption(f"内容较长，仅展示前 {max_display} 字")
    st.markdown(content[:max_display])
else:
    st.markdown(content)

st.markdown("---")
st.caption("由基金智能分析系统生成 · 仅供学习研究")
