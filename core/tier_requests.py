"""
档位升级申请
============
托管版（EDITION=cloud）下，低档位用户在工作台 / 受限页 / 配额用尽提示里
一键提交升级申请：

    1. 申请落库（tier_upgrade_requests 表，幂等：同一用户只保留一条待处理）；
    2. 提交同时向所有「企业管理员」配置的通知通道（企业微信 / 飞书 / 邮件）
       异步推送，管理员即可在 IM / 邮箱里收到提醒；
    3. 管理员在「用户管理 → 升级申请」页一键开通（走 set_tier，配额同步）。

未配置通知通道时仅落库，不阻塞用户提交。

使用方式:
    from core.tier_requests import create_request, notify_admins_async
    res = create_request(user, "pro", note="想开通监控预警")
    if res.get("ok"):
        notify_admins_async("档位升级申请", "user@example.com 申请升级到 专业版")
"""

from typing import Any, Dict, List, Optional

from .db import get_connection, now_iso

VALID_TIERS = ("free", "plus", "pro", "enterprise")


def _ph() -> str:
    from .db import DB_MODE
    return "%s" if DB_MODE == "postgresql" else "?"


def _valid_tier(tier: str) -> str:
    t = (tier or "").strip().lower()
    return t if t in VALID_TIERS else "pro"


# ============================================================
# 数据访问
# ============================================================

def create_request(user: dict, requested_tier: str, note: str = "") -> Dict[str, Any]:
    """
    创建（或更新）升级申请。

    同一用户已存在待处理申请时不重复插入，而是更新目标档位与留言，
    保证管理员列表始终干净（一个用户最多一条 pending）。

    Returns:
        {"ok": True, "id": int, "created": bool}  /  失败 {"ok": False, "reason": str}
    """
    uid = int(user.get("id") or 0)
    if not uid:
        return {"ok": False, "reason": "未登录"}
    if (user.get("tier") or "free") == "enterprise":
        return {"ok": False, "reason": "已是最高档位"}

    tier = _valid_tier(requested_tier)
    email = user.get("email") or ""
    name = user.get("display_name") or ""
    cur_tier = (user.get("tier") or "free").strip().lower()
    note = (note or "").strip()[:200]
    ph = _ph()

    try:
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT id FROM tier_upgrade_requests "
                f"WHERE user_id = {ph} AND status = 'pending' LIMIT 1",
                (uid,),
            ).fetchone()
            if row:
                rid = row["id"] if not isinstance(row, dict) else row.get("id")
                conn.execute(
                    f"UPDATE tier_upgrade_requests SET requested_tier = {ph}, note = {ph}, "
                    f"created_at = {ph} WHERE id = {ph}",
                    (tier, note, now_iso(), rid),
                )
                return {"ok": True, "id": rid, "created": False}

            conn.execute(
                f"INSERT INTO tier_upgrade_requests "
                f"(user_id, email, display_name, current_tier, requested_tier, note, status, created_at) "
                f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, 'pending', {ph})",
                (uid, email, name, cur_tier, tier, note, now_iso()),
            )
            row2 = conn.execute(
                f"SELECT id FROM tier_upgrade_requests "
                f"WHERE user_id = {ph} AND status = 'pending' ORDER BY id DESC LIMIT 1",
                (uid,),
            ).fetchone()
            rid = (row2.get("id") if isinstance(row2, dict) else row2["id"]) if row2 else None
            return {"ok": True, "id": rid, "created": True}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:120]}


def has_pending(user_id: int) -> bool:
    """该用户是否已有待处理的申请。"""
    ph = _ph()
    try:
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT id FROM tier_upgrade_requests "
                f"WHERE user_id = {ph} AND status = 'pending' LIMIT 1",
                (int(user_id),),
            ).fetchone()
            return row is not None
    except Exception:
        return False


def get(request_id: int) -> Optional[Dict[str, Any]]:
    """按 ID 读取一条申请。"""
    ph = _ph()
    try:
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT * FROM tier_upgrade_requests WHERE id = {ph}", (int(request_id),)
            ).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def list_requests(status: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    """列出申请；status=None 返回全部，按提交时间倒序。"""
    ph = _ph()
    try:
        with get_connection() as conn:
            if status:
                rows = conn.execute(
                    f"SELECT * FROM tier_upgrade_requests WHERE status = {ph} "
                    f"ORDER BY created_at DESC LIMIT {int(limit)}",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM tier_upgrade_requests "
                    f"ORDER BY created_at DESC LIMIT {int(limit)}"
                ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def pending_count() -> int:
    """待处理申请数（管理员角标）。"""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM tier_upgrade_requests WHERE status = 'pending'"
            ).fetchone()
            v = row.get("c") if isinstance(row, dict) else row["c"]
            return int(v or 0)
    except Exception:
        return 0


def resolve_request(request_id: int, status: str, handled_by: str = "") -> bool:
    """处理申请：status 取 'approved' / 'rejected'。开通动作由调用方先做 set_tier。"""
    if status not in ("approved", "rejected"):
        return False
    ph = _ph()
    try:
        with get_connection() as conn:
            conn.execute(
                f"UPDATE tier_upgrade_requests SET status = {ph}, handled_at = {ph}, "
                f"handled_by = {ph} WHERE id = {ph} AND status = 'pending'",
                (status, now_iso(), (handled_by or "")[:100], int(request_id)),
            )
        return True
    except Exception:
        return False


# ============================================================
# 管理员通知
# ============================================================

def _admin_notification_targets() -> List[str]:
    """
    找出所有企业管理员的「通知配置文件名」。

    通知配置按用户隔离（core/persistence._user_config_name）：
    uid=1 → notification_config.json，其余 → notification_config_user{uid}.json。
    """
    names, seen = [], set()
    try:
        from .user_repo import UserRepo
        for u in UserRepo().list_all():
            if u.get("tier") != "enterprise" or not u.get("is_active"):
                continue
            uid = int(u.get("id") or 0)
            if not uid:
                continue
            base = "notification_config" if uid == 1 else f"notification_config_user{uid}"
            if base not in seen:
                seen.add(base)
                names.append(base)
    except Exception:
        pass
    return names


def notify_admins(title: str, content: str) -> int:
    """
    向所有企业管理员配置的通知通道推送消息。

    Returns:
        成功发送的通道数（未配置通道或全部失败返回 0 —— 申请仍已落库）。
    """
    sent = 0
    try:
        from .notifications import NotificationSender
        from .persistence import load_json_config

        for base in _admin_notification_targets():
            cfg = load_json_config(base) or {}
            for _name, ch in (cfg.get("channels") or {}).items():
                if not isinstance(ch, dict) or not ch.get("enabled", True):
                    continue
                try:
                    sender = NotificationSender.create(ch.get("type", ""), ch.get("config", {}))
                    if sender and sender.send(title, content):
                        sent += 1
                except Exception:
                    continue
    except Exception:
        pass
    return sent


def notify_admins_async(title: str, content: str) -> None:
    """
    异步通知管理员（后台线程，不阻塞页面渲染/不拖慢用户点击）。
    通知失败不影响申请本身（已落库，管理员进用户管理页仍能看到）。
    """
    import threading

    threading.Thread(
        target=notify_admins, args=(title, content), daemon=True, name="tier-req-notify"
    ).start()
