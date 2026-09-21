"""
个人工作台数据层
================
收藏基金、最近访问、用户偏好（主题等）按 user_id 持久化。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .db import get_connection, get_user_id, now_iso, DB_MODE


def _ph() -> str:
    return "%s" if DB_MODE == "postgresql" else "?"


# ---- favorites ----

def list_favorites(limit: int = 50) -> List[Dict[str, Any]]:
    uid = get_user_id()
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT fund_code, fund_name, created_at FROM user_favorites "
            f"WHERE user_id = {_ph()} ORDER BY created_at DESC LIMIT {_ph()}",
            (uid, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def is_favorite(fund_code: str) -> bool:
    if not fund_code:
        return False
    uid = get_user_id()
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT 1 FROM user_favorites WHERE user_id = {_ph()} AND fund_code = {_ph()} LIMIT 1",
            (uid, fund_code.strip()),
        ).fetchone()
    return bool(row)


def add_favorite(fund_code: str, fund_name: str = "") -> None:
    code = (fund_code or "").strip()
    if not code:
        return
    uid = get_user_id()
    name = (fund_name or "").strip()
    with get_connection() as conn:
        if DB_MODE == "postgresql":
            conn.execute(
                "INSERT INTO user_favorites (user_id, fund_code, fund_name, created_at) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (user_id, fund_code) DO UPDATE SET "
                "fund_name = EXCLUDED.fund_name",
                (uid, code, name, now_iso()),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO user_favorites (user_id, fund_code, fund_name, created_at) "
                "VALUES (?, ?, ?, ?)",
                (uid, code, name, now_iso()),
            )


def remove_favorite(fund_code: str) -> None:
    uid = get_user_id()
    with get_connection() as conn:
        conn.execute(
            f"DELETE FROM user_favorites WHERE user_id = {_ph()} AND fund_code = {_ph()}",
            (uid, (fund_code or "").strip()),
        )


def toggle_favorite(fund_code: str, fund_name: str = "") -> bool:
    """切换收藏，返回切换后是否已收藏。"""
    if is_favorite(fund_code):
        remove_favorite(fund_code)
        return False
    add_favorite(fund_code, fund_name)
    return True


# ---- recent ----

def touch_recent(kind: str, ref_key: str, title: str = "") -> None:
    """记录最近访问（fund / page）。"""
    kind = (kind or "").strip()
    key = (ref_key or "").strip()
    if not kind or not key:
        return
    uid = get_user_id()
    with get_connection() as conn:
        if DB_MODE == "postgresql":
            conn.execute(
                "INSERT INTO user_recent (user_id, kind, ref_key, title, visited_at) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id, kind, ref_key) DO UPDATE SET "
                "title = EXCLUDED.title, visited_at = EXCLUDED.visited_at",
                (uid, kind, key, title or key, now_iso()),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO user_recent (user_id, kind, ref_key, title, visited_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uid, kind, key, title or key, now_iso()),
            )
        # 只保留最近 30 条
        rows = conn.execute(
            f"SELECT id FROM user_recent WHERE user_id = {_ph()} ORDER BY visited_at DESC",
            (uid,),
        ).fetchall()
        if len(rows) > 30:
            drop_ids = [r["id"] for r in rows[30:]]
            for did in drop_ids:
                conn.execute(f"DELETE FROM user_recent WHERE id = {_ph()}", (did,))


def list_recent(kind: str = None, limit: int = 10) -> List[Dict[str, Any]]:
    uid = get_user_id()
    with get_connection() as conn:
        if kind:
            rows = conn.execute(
                f"SELECT kind, ref_key, title, visited_at FROM user_recent "
                f"WHERE user_id = {_ph()} AND kind = {_ph()} "
                f"ORDER BY visited_at DESC LIMIT {_ph()}",
                (uid, kind, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT kind, ref_key, title, visited_at FROM user_recent "
                f"WHERE user_id = {_ph()} ORDER BY visited_at DESC LIMIT {_ph()}",
                (uid, limit),
            ).fetchall()
    return [dict(r) for r in rows]


# ---- prefs ----

def get_prefs() -> Dict[str, Any]:
    uid = get_user_id()
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT color_mode, prefs_json FROM user_prefs WHERE user_id = {_ph()}",
            (uid,),
        ).fetchone()
    if not row:
        return {"color_mode": "light", "prefs": {}}
    try:
        prefs = json.loads(row["prefs_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        prefs = {}
    return {"color_mode": row["color_mode"] or "light", "prefs": prefs}


def save_prefs(color_mode: str = None, prefs_patch: dict = None) -> None:
    uid = get_user_id()
    current = get_prefs()
    mode = color_mode if color_mode in ("light", "dark") else current["color_mode"]
    prefs = dict(current.get("prefs") or {})
    if prefs_patch:
        prefs.update(prefs_patch)
    payload = json.dumps(prefs, ensure_ascii=False)
    with get_connection() as conn:
        if DB_MODE == "postgresql":
            conn.execute(
                "INSERT INTO user_prefs (user_id, color_mode, prefs_json, updated_at) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET "
                "color_mode = EXCLUDED.color_mode, prefs_json = EXCLUDED.prefs_json, "
                "updated_at = EXCLUDED.updated_at",
                (uid, mode, payload, now_iso()),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO user_prefs (user_id, color_mode, prefs_json, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (uid, mode, payload, now_iso()),
            )


def get_color_mode_pref() -> Optional[str]:
    try:
        mode = get_prefs().get("color_mode")
        return mode if mode in ("light", "dark") else None
    except Exception:
        return None


def set_color_mode_pref(mode: str) -> None:
    if mode in ("light", "dark"):
        save_prefs(color_mode=mode)


# ---- workbench snapshot ----

def workbench_snapshot() -> Dict[str, Any]:
    """首页工作台摘要数据。"""
    from .user_repo import UserRepo
    from .portfolio import get_portfolio_manager
    from .alert_engine import get_alert_engine

    uid = get_user_id()
    usage = {"api_calls_today": 0, "api_calls_limit": 0}
    try:
        usage = UserRepo().get_usage(uid)
    except Exception:
        pass

    portfolios = []
    holding_count = 0
    try:
        pm = get_portfolio_manager()
        portfolios = pm.list_all()
        for p in portfolios:
            holding_count += p.holding_count
    except Exception:
        portfolios = []

    watch_count = 0
    try:
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM monitoring_watchlist WHERE user_id = {_ph()}",
                (uid,),
            ).fetchone()
            watch_count = int(row["cnt"] if row else 0)
    except Exception:
        pass

    unack = 0
    today_triggers = 0
    try:
        ae = get_alert_engine()
        stats = ae.get_trigger_stats()
        unack = int(stats.get("unacknowledged", 0))
        today_triggers = ae.count_triggers_today()
    except Exception:
        pass

    history_count = 0
    try:
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM analysis_history WHERE user_id = {_ph()}",
                (uid,),
            ).fetchone()
            history_count = int(row["cnt"] if row else 0)
    except Exception:
        pass

    return {
        "usage": usage,
        "portfolio_count": len(portfolios),
        "holding_count": holding_count,
        "watch_count": watch_count,
        "unack_alerts": unack,
        "today_alerts": today_triggers,
        "history_count": history_count,
        "favorites": list_favorites(8),
        "recent_funds": list_recent("fund", 8),
        "recent_pages": list_recent("page", 6),
    }
