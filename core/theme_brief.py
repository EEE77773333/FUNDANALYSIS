"""
主题资金流观察简报（Markdown）+ Top5 五行短评 / AI 润色
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from .theme_flow import ThemeFlowRow


def generate_theme_brief(themes: List[ThemeFlowRow], *, title: str = "主题资金流观察简报") -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# {title}",
        f"",
        f"> 生成时间：{now}",
        f"> 说明：数据来源于东财板块主力资金流，主题经本地归并配置映射，仅供参考。",
        f"",
        f"## 资金净流入 Top5",
        f"",
    ]
    for i, t in enumerate(themes[:5], 1):
        lines.append(
            f"{i}. **{t.theme}** — 净流入 {t.net_inflow_yi:+.2f} 亿，"
            f"板块均涨 {t.change_pct:+.2f}%（代表：{t.top_sector or '—'}）"
        )
    lines.extend(["", "## 资金净流出 Top5", ""])
    tail = sorted(themes, key=lambda x: x.net_inflow_yi)[:5]
    for i, t in enumerate(tail, 1):
        lines.append(
            f"{i}. **{t.theme}** — 净流入 {t.net_inflow_yi:+.2f} 亿，"
            f"板块均涨 {t.change_pct:+.2f}%"
        )
    lines.extend([
        "",
        "---",
        "*本简报不构成投资建议。*",
    ])
    return "\n".join(lines)


def generate_top5_five_lines(
    themes: List[ThemeFlowRow],
    rank_moves: Optional[List[dict]] = None,
    streaks: Optional[dict] = None,
) -> str:
    """Top5 主题压缩为 5 行短评（规则模板，不调用模型）。"""
    move_map = {m["theme"]: m for m in (rank_moves or [])}
    lines = []
    for i, t in enumerate(themes[:5], 1):
        m = move_map.get(t.theme) or {}
        delta = m.get("delta")
        if delta is None:
            rank_txt = f"排名#{m.get('curr_rank') or i}"
        elif delta > 0:
            rank_txt = f"排名#{m.get('curr_rank')}↑{delta}"
        elif delta < 0:
            rank_txt = f"排名#{m.get('curr_rank')}↓{abs(delta)}"
        else:
            rank_txt = f"排名#{m.get('curr_rank')}平"

        st = (streaks or {}).get(t.theme) or {}
        if st.get("direction") == "in":
            streak_txt = f"连流入{st.get('in_days', 0)}日"
        elif st.get("direction") == "out":
            streak_txt = f"连流出{st.get('out_days', 0)}日"
        else:
            streak_txt = "风向中性"

        tone = "强势吸金" if t.net_inflow_yi > 0 and t.change_pct > 0 else (
            "吸金滞涨" if t.net_inflow_yi > 0 else (
                "抛压杀跌" if t.change_pct < 0 else "流出抗跌"
            )
        )
        lines.append(
            f"{i}. {t.theme}｜净流入{t.net_inflow_yi:+.1f}亿｜涨跌{t.change_pct:+.2f}%｜"
            f"{rank_txt}｜{streak_txt}｜{tone}｜代表板块{t.top_sector or '—'}"
        )
    return "\n".join(lines)


def generate_top5_ai_brief(
    themes: List[ThemeFlowRow],
    rank_moves: Optional[List[dict]] = None,
    streaks: Optional[dict] = None,
) -> str:
    """
    调用已配置 AI，对 Top5 生成约 5 行盘面短评。
    需侧栏已配置可用模型。
    """
    from .ai_analyzer import get_analyzer

    base = generate_top5_five_lines(themes, rank_moves=rank_moves, streaks=streaks)
    facts = generate_theme_brief(themes[:5] + sorted(themes, key=lambda x: x.net_inflow_yi)[:3])
    system = (
        "你是A股主题资金流观察助手。根据给定数据写恰好5行中文短评，"
        "每行一个主题，不超过40字，客观中性，不荐股，不编造数字。"
    )
    user = f"规则摘要：\n{base}\n\n详细数据：\n{facts}\n\n请输出5行短评："
    analyzer = get_analyzer()
    result = analyzer.analyze(system, user, max_tokens=512, temperature=0.3)
    if isinstance(result, dict):
        text = (result.get("content") or "").strip()
        if not result.get("success", True) and not text:
            text = base
    else:
        text = (getattr(result, "content", None) or str(result) or "").strip()
    return text or base
