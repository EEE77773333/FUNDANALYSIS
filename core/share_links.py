"""
分析历史只读分享链接
====================
生成限时 token，他人无需登录即可查看脱敏后的分析结果。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .db import DB_MODE, get_connection, get_user_id, now_iso


def _ph() -> str:
    return "%s" if DB_MODE == "postgresql" else "?"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_share(history_id: int, hours: int = 72, title: str = "") -> Optional[Dict[str, Any]]:
    """为当前用户的一条分析历史创建分享链接。"""
    from .history import get_history_manager

    rec = get_history_manager().get(history_id)
    if not rec:
        return None

    uid = get_user_id()
    token = secrets.token_urlsafe(24)
    expires = (_utc_now() + timedelta(hours=max(1, min(int(hours), 24 * 30)))).strftime("%Y-%m-%d %H:%M:%S")
    title = title or f"{rec.page_name} · {rec.fund_code or '分析'}".strip(" ·")
    with get_connection() as conn:
        conn.execute(
            f"INSERT INTO share_links (token, user_id, history_id, title, expires_at, created_at, view_count, revoked) "
            f"VALUES ({_ph()}, {_ph()}, {_ph()}, {_ph()}, {_ph()}, {_ph()}, 0, 0)",
            (token, uid, history_id, title, expires, now_iso()),
        )
    return {
        "token": token,
        "history_id": history_id,
        "title": title,
        "expires_at": expires,
    }


def list_my_shares(limit: int = 50) -> List[Dict[str, Any]]:
    uid = get_user_id()
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM share_links WHERE user_id = {_ph()} ORDER BY created_at DESC LIMIT {_ph()}",
            (uid, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def revoke_share(token: str) -> bool:
    uid = get_user_id()
    with get_connection() as conn:
        conn.execute(
            f"UPDATE share_links SET revoked = 1 WHERE token = {_ph()} AND user_id = {_ph()}",
            (token, uid),
        )
    return True


def get_share_payload(token: str) -> Optional[Dict[str, Any]]:
    """公开读取：校验未过期未撤销，返回只读内容（不含用户邮箱）。"""
    if not token:
        return None
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT * FROM share_links WHERE token = {_ph()} LIMIT 1",
            (token,),
        ).fetchone()
        if not row:
            return None
        link = dict(row)
        if int(link.get("revoked") or 0) == 1:
            return {"error": "链接已撤销"}
        exp = link.get("expires_at") or ""
        try:
            exp_dt = datetime.strptime(exp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if _utc_now() > exp_dt:
                return {"error": "链接已过期"}
        except ValueError:
            return {"error": "链接无效"}

        hist = conn.execute(
            f"SELECT id, page_name, fund_code, fund_name, result_content, model, created_at, "
            f"structured_result_json, elapsed_seconds FROM analysis_history WHERE id = {_ph()}",
            (link["history_id"],),
        ).fetchone()
        if not hist:
            return {"error": "内容不存在"}

        conn.execute(
            f"UPDATE share_links SET view_count = view_count + 1 WHERE token = {_ph()}",
            (token,),
        )

    h = dict(hist)
    content = h.get("result_content") or ""
    # 简单脱敏：去掉可能的邮箱、长数字串密钥样
    content = _redact(content)
    return {
        "title": link.get("title") or h.get("page_name"),
        "page_name": h.get("page_name"),
        "fund_code": h.get("fund_code"),
        "fund_name": h.get("fund_name"),
        "model": h.get("model"),
        "created_at": h.get("created_at"),
        "elapsed_seconds": h.get("elapsed_seconds"),
        "result_content": content,
        "structured_result_json": h.get("structured_result_json") or "",
        "expires_at": link.get("expires_at"),
        "view_count": int(link.get("view_count") or 0) + 1,
    }


def _redact(text: str) -> str:
    import re
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)
    text = re.sub(r"(sk-|Bearer\s+)[A-Za-z0-9_\-]{10,}", r"\1***", text)
    return text


def share_url_path(token: str) -> str:
    """Streamlit 多页路径 + query。"""
    return f"/分享阅读?share={token}"
