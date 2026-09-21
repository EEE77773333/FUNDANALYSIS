"""
主题资金流雷达增强分析
====================
连续流入天数、排名变动、背离、时段对比、热力日历、组合主题暴露。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .theme_flow import SNAPSHOT_DIR, ThemeFlowRow, SectorFlowRow, load_theme_rank_snapshot
from .theme_taxonomy import load_taxonomy, map_sector_to_theme
from .utils import safe_float


def compute_rank_moves(
    themes: List[ThemeFlowRow],
    prev_ranks: Optional[Dict[str, int]] = None,
) -> List[dict]:
    """相对上次排名缓存的跃升幅度（正=名次上升）。不写缓存。"""
    prev = prev_ranks if prev_ranks is not None else (load_theme_rank_snapshot().get("ranks") or {})
    out = []
    for i, t in enumerate(themes):
        curr = i + 1
        prev_r = prev.get(t.theme)
        delta = (int(prev_r) - curr) if prev_r is not None else None
        out.append({
            "theme": t.theme,
            "curr_rank": curr,
            "prev_rank": prev_r,
            "delta": delta,
            "net_inflow_yi": t.net_inflow_yi,
            "change_pct": t.change_pct,
        })
    return out


def _eod_theme_frame(days: int = 30) -> pd.DataFrame:
    """
    近 N 个快照文件中，每个交易日取「最后一次」刷新，得到主题日终净流入表。
    列: date, theme, net_inflow_yi, change_pct
    """
    if not SNAPSHOT_DIR.exists():
        return pd.DataFrame()
    files = sorted(SNAPSHOT_DIR.glob("*.csv"), reverse=True)[:days]
    parts = []
    for f in files:
        try:
            df = pd.read_csv(f)
        except Exception:
            continue
        if df.empty or "theme" not in df.columns:
            continue
        df["net_inflow_yi"] = pd.to_numeric(df.get("net_inflow_yi"), errors="coerce").fillna(0)
        df["change_pct"] = pd.to_numeric(df.get("change_pct"), errors="coerce").fillna(0)
        if "time" in df.columns:
            df = df.sort_values("time")
            df = df.drop_duplicates(subset=["theme"], keep="last")
        else:
            df = df.drop_duplicates(subset=["theme"], keep="last")
        date = str(df["date"].iloc[0]) if "date" in df.columns else f.stem
        df = df[["theme", "net_inflow_yi", "change_pct"]].copy()
        df["date"] = str(date)[:10]
        parts.append(df)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def compute_streaks(themes: List[ThemeFlowRow], days: int = 20) -> Dict[str, dict]:
    """
    连续流入/流出天数：按日终净流入符号自最近一日往回计。
    """
    eod = _eod_theme_frame(days=days)
    out: Dict[str, dict] = {}
    theme_names = [t.theme for t in themes]
    if eod.empty:
        for name in theme_names:
            # 仅凭当日：流入则 1 天，流出则 -1 记为流出天数
            t = next(x for x in themes if x.theme == name)
            if t.net_inflow_yi > 0:
                out[name] = {"in_days": 1, "out_days": 0, "direction": "in"}
            elif t.net_inflow_yi < 0:
                out[name] = {"in_days": 0, "out_days": 1, "direction": "out"}
            else:
                out[name] = {"in_days": 0, "out_days": 0, "direction": "flat"}
        return out

    # 用今日实时覆盖最近日
    today = datetime.now().strftime("%Y-%m-%d")
    live = pd.DataFrame([{
        "date": today,
        "theme": t.theme,
        "net_inflow_yi": t.net_inflow_yi,
        "change_pct": t.change_pct,
    } for t in themes])
    eod = eod[eod["date"] != today]
    eod = pd.concat([eod, live], ignore_index=True)

    for name in theme_names:
        sub = eod[eod["theme"] == name].sort_values("date", ascending=False)
        if sub.empty:
            out[name] = {"in_days": 0, "out_days": 0, "direction": "flat"}
            continue
        signs = [1 if v > 0 else (-1 if v < 0 else 0) for v in sub["net_inflow_yi"].tolist()]
        first = signs[0]
        streak = 0
        for s in signs:
            if s == 0:
                break
            if s != first:
                break
            streak += 1
        if first > 0:
            out[name] = {"in_days": streak, "out_days": 0, "direction": "in"}
        elif first < 0:
            out[name] = {"in_days": 0, "out_days": streak, "direction": "out"}
        else:
            out[name] = {"in_days": 0, "out_days": 0, "direction": "flat"}
    return out


def find_divergences(themes: List[ThemeFlowRow], top_n: int = 5) -> Dict[str, List[dict]]:
    """
    大流入弱涨 / 大流出抗跌。
    """
    if not themes:
        return {"inflow_weak": [], "outflow_resilient": []}
    # 流入侧：净流入 Top 半区里涨幅排名靠后
    by_in = sorted(themes, key=lambda t: t.net_inflow_yi, reverse=True)
    inflow_pool = [t for t in by_in if t.net_inflow_yi > 0][: max(top_n * 2, 6)]
    inflow_weak = sorted(inflow_pool, key=lambda t: t.change_pct)[:top_n]

    outflow_pool = [t for t in sorted(themes, key=lambda t: t.net_inflow_yi) if t.net_inflow_yi < 0][: max(top_n * 2, 6)]
    outflow_resilient = sorted(outflow_pool, key=lambda t: t.change_pct, reverse=True)[:top_n]

    def _row(t: ThemeFlowRow) -> dict:
        return {
            "theme": t.theme,
            "net_inflow_yi": t.net_inflow_yi,
            "change_pct": t.change_pct,
            "top_sector": t.top_sector,
        }

    return {
        "inflow_weak": [_row(t) for t in inflow_weak],
        "outflow_resilient": [_row(t) for t in outflow_resilient],
    }


def build_heat_matrix(days: int = 22) -> pd.DataFrame:
    """主题 × 日期 净流入热力矩阵（日终）。"""
    eod = _eod_theme_frame(days=days)
    if eod.empty:
        return pd.DataFrame()
    pivot = eod.pivot_table(
        index="theme",
        columns="date",
        values="net_inflow_yi",
        aggfunc="last",
    )
    cols = sorted(pivot.columns)
    return pivot[cols]


def session_compare_today() -> Dict[str, Any]:
    """
    当日早盘(≤11:30)最后一帧 vs 午盘(≥13:00)最后一帧资金差。
    依赖当日多次快照。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    path = SNAPSHOT_DIR / f"{today}.csv"
    if not path.exists():
        return {"ok": False, "reason": "no_today_snapshot", "rows": []}

    df = pd.read_csv(path)
    if df.empty or "time" not in df.columns:
        return {"ok": False, "reason": "no_time", "rows": []}

    df["net_inflow_yi"] = pd.to_numeric(df["net_inflow_yi"], errors="coerce").fillna(0)
    df["time"] = df["time"].astype(str)

    am = df[df["time"] <= "11:30:59"]
    pm = df[df["time"] >= "13:00:00"]
    if am.empty or pm.empty:
        return {
            "ok": False,
            "reason": "need_both_sessions",
            "am_time": str(am["time"].iloc[-1]) if not am.empty else "",
            "pm_time": str(pm["time"].iloc[-1]) if not pm.empty else "",
            "rows": [],
        }

    am_t = str(am["time"].iloc[-1])
    pm_t = str(pm["time"].iloc[-1])
    am_last = am[am["time"] == am_t].drop_duplicates("theme", keep="last")
    pm_last = pm[pm["time"] == pm_t].drop_duplicates("theme", keep="last")
    am_map = {r["theme"]: float(r["net_inflow_yi"]) for _, r in am_last.iterrows()}
    pm_map = {r["theme"]: float(r["net_inflow_yi"]) for _, r in pm_last.iterrows()}
    themes = sorted(set(am_map) | set(pm_map))
    rows = []
    for th in themes:
        a = am_map.get(th, 0.0)
        p = pm_map.get(th, 0.0)
        rows.append({
            "主题": th,
            "早盘净流入(亿)": round(a, 2),
            "午盘净流入(亿)": round(p, 2),
            "午-早差(亿)": round(p - a, 2),
        })
    rows.sort(key=lambda x: abs(x["午-早差(亿)"]), reverse=True)
    return {"ok": True, "am_time": am_t, "pm_time": pm_t, "rows": rows}


def theme_sector_breakdown(
    theme: str,
    sectors: List[SectorFlowRow],
) -> pd.DataFrame:
    """主题下贡献板块构成（行业/概念）。"""
    rows = []
    for s in sectors:
        mapped = map_sector_to_theme(s.name) or "其他"
        if mapped != theme:
            continue
        rows.append({
            "板块名称": s.name,
            "类型": "行业" if s.board_type == "industry" else "概念",
            "主力净流入(亿)": round(s.net_inflow_yi, 2),
            "涨跌幅%": s.change_pct,
        })
    if not rows:
        return pd.DataFrame(columns=["板块名称", "类型", "主力净流入(亿)", "涨跌幅%"])
    return pd.DataFrame(rows).sort_values("主力净流入(亿)", ascending=False)


def portfolio_theme_exposure(
    holdings: List[dict],
    themes: List[ThemeFlowRow],
) -> pd.DataFrame:
    """
    持仓按基金名称关键词映射主题，汇总权重 vs 今日净流入。
    holdings: [{code, name, weight}]
    """
    tax = load_taxonomy()
    theme_flow = {t.theme: t for t in themes}
    expo: Dict[str, float] = {}
    w_sum = sum(safe_float(h.get("weight")) for h in holdings)
    use_amount = w_sum <= 1e-9
    if use_amount:
        w_sum = sum(safe_float(h.get("amount")) for h in holdings) or len(holdings) or 1

    for h in holdings:
        name = str(h.get("name") or h.get("fund_name") or "")
        w = safe_float(h.get("amount" if use_amount else "weight")) / w_sum
        matched = []
        for theme, cfg in tax.items():
            for kw in (cfg.get("keywords") or []) + (cfg.get("sectors") or []):
                if kw and kw in name:
                    matched.append(theme)
                    break
        if not matched:
            matched = ["未匹配"]
        share = w / len(matched)
        for th in matched:
            expo[th] = expo.get(th, 0.0) + share

    rows = []
    for th, w in sorted(expo.items(), key=lambda x: -x[1]):
        tf = theme_flow.get(th)
        inflow = tf.net_inflow_yi if tf else None
        chg = tf.change_pct if tf else None
        if th == "未匹配":
            bias = "—"
        elif inflow is None:
            bias = "—"
        elif w >= 0.08 and inflow > 0:
            bias = "偏多对齐"
        elif w >= 0.08 and inflow < 0:
            bias = "持仓遇流出"
        elif w < 0.05 and inflow > 0:
            bias = "流入未配"
        elif w < 0.05 and inflow < 0:
            bias = "低配流出"
        else:
            bias = "中性"
        rows.append({
            "主题": th,
            "持仓权重%": round(w * 100, 2),
            "今日净流入(亿)": None if inflow is None else round(inflow, 2),
            "主题涨跌%": None if chg is None else round(chg, 2),
            "对照": bias,
        })
    return pd.DataFrame(rows)


def watchlist_in_topn(
    themes: List[ThemeFlowRow],
    watch: List[str],
    top_n: int = 5,
) -> List[dict]:
    """观察池主题进入净流入 TopN 时返回高亮项。"""
    top = {t.theme: i + 1 for i, t in enumerate(themes[:top_n])}
    hits = []
    for w in watch or []:
        if w in top:
            t = next(x for x in themes if x.theme == w)
            hits.append({
                "theme": w,
                "rank": top[w],
                "net_inflow_yi": t.net_inflow_yi,
                "change_pct": t.change_pct,
            })
    return hits
