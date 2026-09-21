"""
工作台实时摘要：市场一览 / 持仓估算 / 监控异动。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .db import get_connection, get_user_id, DB_MODE
from .data_fetcher import get_fetcher
from .portfolio import get_portfolio_manager
from .quote_provider import get_index_quotes
from .theme_flow import load_latest_theme_snapshot
from .utils import safe_float


def _ph() -> str:
    return "%s" if DB_MODE == "postgresql" else "?"


INDEX_MAP = {
    "上证指数": "s_sh000001",
    "沪深300": "s_sh000300",
    "创业板指": "s_sz399006",
}


def fetch_market_strip() -> Dict[str, Any]:
    """主要指数 + 最新主题资金快照 Top。"""
    indexes = get_index_quotes(INDEX_MAP)
    themes = load_latest_theme_snapshot()
    top_in = themes[:2] if themes else []
    top_out = sorted(themes, key=lambda t: t["net_inflow_yi"])[:1] if themes else []
    asof = ""
    if top_in:
        asof = top_in[0].get("asof") or ""
    elif top_out:
        asof = top_out[0].get("asof") or ""
    return {
        "indexes": indexes,
        "theme_in": top_in,
        "theme_out": top_out,
        "theme_asof": asof,
    }


def _fund_estimate(code: str) -> Optional[Dict[str, Any]]:
    est = get_fetcher().get_realtime_estimate(code)
    if not est:
        return None
    pct = safe_float(est.get("估算涨幅%"))
    return {
        "code": str(est.get("基金代码") or code).zfill(6),
        "name": est.get("基金名称") or "",
        "pct": pct,
        "est_nav": safe_float(est.get("估算净值")),
        "est_time": est.get("估算时间") or "",
    }


def _normalize_weights(rows: List[dict]) -> List[Tuple[dict, float]]:
    """返回 (holding, weight_fraction) ，权重和为 1。"""
    w_sum = sum(safe_float(h.get("weight")) for h in rows)
    if w_sum > 1e-9:
        return [(h, safe_float(h.get("weight")) / w_sum) for h in rows]
    a_sum = sum(safe_float(h.get("amount")) for h in rows)
    if a_sum > 1e-9:
        return [(h, safe_float(h.get("amount")) / a_sum) for h in rows]
    n = len(rows)
    eq = 1.0 / n if n else 0.0
    return [(h, eq) for h in rows]


def fetch_portfolio_summary(max_funds: int = 10) -> Dict[str, Any]:
    """
    默认选持仓最多的组合，用官方实时估算加权组合涨跌，
    并给出贡献/拖累前几名。
    """
    pm = get_portfolio_manager()
    portfolios = pm.list_all()
    if not portfolios:
        return {"ok": False, "reason": "empty"}

    best = None
    best_df = None
    for p in portfolios:
        df = pm.get_holdings_df(p.id)
        if df is None or df.empty:
            continue
        if best is None or len(df) > len(best_df):
            best, best_df = p, df

    if best is None:
        return {"ok": False, "reason": "no_holdings"}

    rows = best_df.to_dict("records")
    # 优先权重大的先估，控制首页请求量
    rows_sorted = sorted(
        rows,
        key=lambda h: (safe_float(h.get("weight")), safe_float(h.get("amount"))),
        reverse=True,
    )[:max_funds]
    weighted = _normalize_weights(rows_sorted)

    items: List[dict] = []
    port_pct = 0.0
    for h, w in weighted:
        code = str(h.get("fund_code", "")).zfill(6)
        est = _fund_estimate(code)
        pct = est["pct"] if est else 0.0
        name = (est or {}).get("name") or h.get("fund_name") or ""
        contrib = w * pct
        port_pct += contrib
        items.append({
            "code": code,
            "name": name,
            "weight": round(w * 100, 2),
            "pct": round(pct, 2),
            "contrib": round(contrib, 3),
            "est_time": (est or {}).get("est_time") or "",
        })

    gainers = sorted(items, key=lambda x: x["contrib"], reverse=True)[:3]
    losers = sorted(items, key=lambda x: x["contrib"])[:3]
    return {
        "ok": True,
        "portfolio_id": best.id,
        "portfolio_name": best.name,
        "holding_n": len(rows),
        "estimated_n": len(items),
        "port_pct": round(port_pct, 2),
        "gainers": gainers,
        "losers": losers,
        "items": items,
    }


def fetch_watch_movers(limit: int = 5, max_scan: int = 20) -> Dict[str, Any]:
    """监控列表按估算涨跌幅绝对值排序，取异动 Top。"""
    uid = get_user_id()
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT fund_code, fund_name FROM monitoring_watchlist "
            f"WHERE user_id = {_ph()} ORDER BY added_at DESC",
            (uid,),
        ).fetchall()
    watch = [dict(r) for r in rows][:max_scan]
    if not watch:
        return {"ok": False, "reason": "empty", "movers": []}

    movers: List[dict] = []
    for w in watch:
        code = str(w.get("fund_code", "")).zfill(6)
        est = _fund_estimate(code)
        if not est:
            continue
        movers.append({
            "code": code,
            "name": est.get("name") or w.get("fund_name") or "",
            "pct": round(est["pct"], 2),
            "est_time": est.get("est_time") or "",
        })

    movers.sort(key=lambda x: abs(x["pct"]), reverse=True)
    return {
        "ok": True,
        "total": len(watch),
        "movers": movers[:limit],
    }
