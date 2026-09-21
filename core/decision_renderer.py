"""
决策仪表盘 Streamlit 渲染
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from .decision_schema import validate_dashboard

_LEVEL_STYLE = {
    "info": ("#2563EB", "#EFF6FF", "ℹ️"),
    "warning": ("#D97706", "#FFFBEB", "⚠️"),
    "danger": ("#DC2626", "#FEF2F2", "❌"),
}


def render_decision_dashboard(data: Dict[str, Any], *, expanded: bool = True):
  """渲染结构化决策仪表盘卡片组。"""
  d = validate_dashboard(data)
  meta = d.get("meta", {})
  cc = d.get("core_conclusion", {})
  dp = d.get("data_perspective", {})
  sfv = d.get("signal_for_validation", {})

  with st.expander("📋 决策仪表盘", expanded=expanded):
    # 标题行
    title_parts = []
    if meta.get("fund_name"):
      title_parts.append(meta["fund_name"])
    if meta.get("fund_code"):
      title_parts.append(f"({meta['fund_code']})")
    if title_parts:
      st.markdown(f"**{' '.join(title_parts)}**")

    stars = cc.get("rating_stars")
    if stars:
      st.markdown(f"### {'⭐' * int(stars)} ({stars}/5)")

    if cc.get("one_liner"):
      st.info(cc["one_liner"])

    col1, col2, col3 = st.columns(3)
    with col1:
      suit = cc.get("suitability") or []
      if suit:
        st.caption("✅ 适配")
        for s in suit[:4]:
          st.markdown(f"- {s}")
    with col2:
      ns = cc.get("not_suitable") or []
      if ns:
        st.caption("⛔ 不适配")
        for s in ns[:4]:
          st.markdown(f"- {s}")
    with col3:
      action = sfv.get("action", "watch")
      conf = sfv.get("confidence", 0)
      st.caption("🔍 观察信号")
      st.markdown(f"**{action}** · 置信 {conf:.0%} · {sfv.get('horizon_days', 20)}日")

    metrics: List[dict] = dp.get("metrics") or []
    if metrics:
      st.markdown("##### 数据视角")
      cols = st.columns(min(len(metrics), 4))
      for i, m in enumerate(metrics[:4]):
        with cols[i % len(cols)]:
          label = m.get("label", "—")
          value = m.get("value", "—")
          badge = m.get("badge", "")
          st.metric(label, value, help=badge or None)

    if dp.get("valuation_context"):
      st.caption(f"📊 {dp['valuation_context']}")

    risks = d.get("risk_watchlist") or []
    if risks:
      st.markdown("##### 风险关注")
      for r in risks[:6]:
        level = r.get("level", "info")
        color, bg, icon = _LEVEL_STYLE.get(level, _LEVEL_STYLE["info"])
        st.markdown(
          f'<div style="background:{bg};border-left:3px solid {color};'
          f'padding:0.5rem 0.75rem;margin-bottom:0.35rem;border-radius:6px;">'
          f'<b>{icon} {r.get("item","")}</b><br><span style="color:#64748B;font-size:0.85rem;">'
          f'{r.get("detail","")}</span></div>',
          unsafe_allow_html=True,
        )

    op = d.get("observation_plan") or {}
    if op.get("horizon") or op.get("conditions"):
      st.markdown("##### 观察计划")
      if op.get("horizon"):
        st.caption(f"期限: {op['horizon']}")
      for c in (op.get("conditions") or [])[:5]:
        st.markdown(f"- {c}")

    attr = d.get("attribution") or {}
    if attr:
      parts = [f"{k} {v:.0%}" for k, v in attr.items() if isinstance(v, (int, float))]
      if parts:
        st.caption("归因权重: " + " · ".join(parts))

    st.caption(d.get("compliance", {}).get("disclaimer", ""))
