"""
用户数据访问层
==============
用户 CRUD + 配额管理 + 用量统计。

使用方式:
    from core.user_repo import UserRepo

    repo = UserRepo()
    user = repo.get_by_email("user@example.com")
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
from .db import get_connection, now_iso

# 「今日」按北京时间（UTC+8）计算，与系统其余「今日」逻辑（选股/盯盘/跑批）保持一致
_CN_TZ = timezone(timedelta(hours=8))


def _today_cn() -> str:
    return datetime.now(_CN_TZ).strftime("%Y-%m-%d")


def _row_get(row, key: str, default=None):
    """
    安全地从查询结果行中取值。

    SQLite 返回 sqlite3.Row（只有下标访问，没有 .get），PostgreSQL 走
    RealDictCursor 返回 dict。直接用 row.get(...) 会在 SQLite 下抛
    AttributeError —— 本项目历史上 AI 用量计数就是这样静默失效的。
    """
    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


class UserRepo:
    """用户数据访问"""

    @staticmethod
    def _ph() -> str:
        from .db import DB_MODE
        return "%s" if DB_MODE == "postgresql" else "?"

    def create(self, email: str, password_hash: str, display_name: str = "") -> int:
        """创建用户，返回 user_id（默认 free 套餐，配额与 QUOTA_MAP 保持一致）"""
        from .middleware import QUOTA_MAP
        free_limit = QUOTA_MAP["free"]["ai_analysis"]
        ph = self._ph()
        with get_connection() as conn:
            result = conn.execute(
                f"INSERT INTO users (email, password_hash, display_name, api_calls_limit, created_at, updated_at) "
                f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})",
                (email, password_hash, display_name, free_limit, now_iso(), now_iso()),
            )
            # PG: RETURNING id 需要额外查询
            from .db import DB_MODE
            if DB_MODE == "postgresql":
                row = conn.execute(
                    "SELECT id FROM users WHERE email = %s", (email,)
                ).fetchone()
                return row["id"]
            else:
                return result.lastrowid

    def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """根据邮箱查找用户"""
        ph = self._ph()
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT * FROM users WHERE email = {ph}", (email,)
            ).fetchone()
            return dict(row) if row else None

    def get_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 查找用户"""
        ph = self._ph()
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT * FROM users WHERE id = {ph}", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_last_login(self, user_id: int):
        """更新最后登录时间"""
        ph = self._ph()
        with get_connection() as conn:
            conn.execute(
                f"UPDATE users SET last_login_at = {ph}, updated_at = {ph} WHERE id = {ph}",
                (now_iso(), now_iso(), user_id),
            )

    def update_password(self, user_id: int, new_hash: str):
        """修改密码"""
        ph = self._ph()
        with get_connection() as conn:
            conn.execute(
                f"UPDATE users SET password_hash = {ph}, updated_at = {ph} WHERE id = {ph}",
                (new_hash, now_iso(), user_id),
            )

    def update_display_name(self, user_id: int, name: str):
        """修改昵称"""
        ph = self._ph()
        with get_connection() as conn:
            conn.execute(
                f"UPDATE users SET display_name = {ph}, updated_at = {ph} WHERE id = {ph}",
                (name, now_iso(), user_id),
            )

    def increment_api_call(self, user_id: int):
        """增加 API 调用计数（自动跨天重置，按北京时间）"""
        ph = self._ph()
        today = _today_cn()
        with get_connection() as conn:
            # 检查是否需要跨天重置
            # 注意：SQLite 返回 sqlite3.Row（无 .get 方法），PG 返回 dict，
            # 因此必须用统一的安全取值函数，不能直接 row.get(...)
            user = conn.execute(
                f"SELECT api_calls_today_date FROM users WHERE id = {ph}", (user_id,)
            ).fetchone()
            if user is not None and _row_get(user, "api_calls_today_date") == today:
                conn.execute(
                    f"UPDATE users SET api_calls_today = api_calls_today + 1 WHERE id = {ph}",
                    (user_id,),
                )
            else:
                conn.execute(
                    f"UPDATE users SET api_calls_today = 1, api_calls_today_date = {ph} WHERE id = {ph}",
                    (today, user_id),
                )

    def get_usage(self, user_id: int) -> dict:
        """获取用户用量统计（自动处理跨天，按北京时间）"""
        user = self.get_by_id(user_id)
        if not user:
            return {}
        today = _today_cn()
        # 跨天时显示为 0（下次 API 调用时才会重置 DB）
        is_today = _row_get(user, "api_calls_today_date") == today
        used = (_row_get(user, "api_calls_today", 0) or 0) if is_today else 0
        limit = _row_get(user, "api_calls_limit", 100) or 100
        return {
            "api_calls_today": used,
            "api_calls_limit": limit,
            "tier": _row_get(user, "tier", "free"),
            "tier_expires_at": _row_get(user, "tier_expires_at"),
            "remaining_today": max(0, limit - used),
        }

    # ---- 管理员方法 ----

    def list_all(self) -> list:
        """列出所有用户（管理员功能）"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT id, email, display_name, tier, is_active, api_calls_today, "
                "api_calls_limit, last_login_at, created_at FROM users ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def set_tier(self, user_id: int, tier: str, calls_limit: int = None):
        """修改用户套餐。

        calls_limit 未显式传入时，从 QUOTA_MAP 按档位推导，保证
        api_calls_limit 列始终与档位一致（该列会被 get_usage / 日报等
        展示路径读取，遗留旧值会导致显示的配额与实际不符）。
        QUOTA_MAP 仍是唯一权威来源，此处只是同步镜像。
        """
        if calls_limit is None:
            try:
                from .middleware import QUOTA_MAP
                calls_limit = QUOTA_MAP.get(tier, {}).get("ai_analysis")
            except Exception:
                calls_limit = None
        ph = self._ph()
        with get_connection() as conn:
            if calls_limit is not None:
                conn.execute(
                    f"UPDATE users SET tier = {ph}, api_calls_limit = {ph}, updated_at = {ph} WHERE id = {ph}",
                    (tier, calls_limit, now_iso(), user_id),
                )
            else:
                conn.execute(
                    f"UPDATE users SET tier = {ph}, updated_at = {ph} WHERE id = {ph}",
                    (tier, now_iso(), user_id),
                )

    def toggle_active(self, user_id: int, active: bool):
        """启用/禁用用户"""
        ph = self._ph()
        with get_connection() as conn:
            conn.execute(
                f"UPDATE users SET is_active = {ph}, updated_at = {ph} WHERE id = {ph}",
                (1 if active else 0, now_iso(), user_id),
            )

    def admin_create_user(self, email: str, password: str, display_name: str,
                          tier: str = "pro", calls_limit: int = 100) -> int:
        """管理员创建用户（跳过邮箱唯一性之外的验证）"""
        from core.auth import AuthManager
        existing = self.get_by_email(email)
        if existing:
            raise ValueError(f"邮箱 {email} 已被注册")
        hashed = AuthManager.hash_password(password)
        user_id = self.create(email, hashed, display_name)
        # 应用指定的套餐和配额
        self.set_tier(user_id, tier, calls_limit)
        return user_id
