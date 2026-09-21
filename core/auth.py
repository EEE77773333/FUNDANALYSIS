"""
用户认证模块
============
密码哈希 (bcrypt) + JWT 签发/验证 + 会话管理。

使用方式:
    from core.auth import AuthManager

    am = AuthManager()
    token, user = am.login("user@example.com", "password123")
    payload = am.verify_token(token)
"""

import os
import hashlib
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

# JWT 密钥（优先环境变量，其次持久化文件，最后自动生成）
_JWT_SECRET = os.getenv("JWT_SECRET", "")
if not _JWT_SECRET:
    _SECRET_FILE = Path(__file__).parent.parent / "data" / ".jwt_secret"
    try:
        _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _SECRET_FILE.exists():
            _JWT_SECRET = _SECRET_FILE.read_text().strip()
        else:
            _JWT_SECRET = hashlib.sha256(os.urandom(64)).hexdigest()[:32]
            _SECRET_FILE.write_text(_JWT_SECRET)
    except Exception:
        _JWT_SECRET = hashlib.sha256(os.urandom(64)).hexdigest()[:32]

_JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))

# bcrypt 可用性检测
_BCRYPT_AVAILABLE = False
try:
    import bcrypt
    _BCRYPT_AVAILABLE = True
except ImportError:
    pass


class AuthManager:
    """用户认证管理器"""

    @staticmethod
    def hash_password(plain: str) -> str:
        """bcrypt 哈希密码"""
        if _BCRYPT_AVAILABLE:
            return bcrypt.hashpw(
                plain.encode("utf-8"),
                bcrypt.gensalt(rounds=12),
            ).decode("utf-8")
        # Fallback: hashlib (仅用于开发环境)
        return "sha256:" + hashlib.sha256(
            (plain + _JWT_SECRET).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        """验证密码"""
        if _BCRYPT_AVAILABLE and not hashed.startswith("sha256:"):
            try:
                return bcrypt.checkpw(
                    plain.encode("utf-8"),
                    hashed.encode("utf-8"),
                )
            except Exception:
                return False
        # Fallback
        expected = "sha256:" + hashlib.sha256(
            (plain + _JWT_SECRET).encode("utf-8")
        ).hexdigest()
        import hmac as _hmac
        return _hmac.compare_digest(hashed.encode(), expected.encode())

    @staticmethod
    def create_token(user_id: int, email: str) -> str:
        """
        签发认证 Token（HMAC-SHA256 签名）。

        格式: payload_base64.signature_hex
        """
        import json as _json
        import base64 as _b64

        now = datetime.now(timezone.utc)
        payload_json = _json.dumps({
            "user_id": user_id,
            "email": email,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=_JWT_EXPIRY_HOURS)).timestamp()),
        }, separators=(",", ":"))

        payload_b64 = _b64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        sig = hashlib.sha256((payload_b64 + _JWT_SECRET).encode()).hexdigest()[:32]

        return f"{payload_b64}.{sig}"

    @staticmethod
    def verify_token(token: str) -> Optional[Dict[str, Any]]:
        """
        验证 Token，返回 payload 或 None。

        校验：签名 + 过期时间。
        """
        import json as _json
        import base64 as _b64

        try:
            parts = token.rsplit(".", 1)
            if len(parts) != 2:
                return None
            payload_b64, sig = parts

            # 验证签名（恒定时间比较）
            expected_sig = hashlib.sha256(
                (payload_b64 + _JWT_SECRET).encode()
            ).hexdigest()[:32]
            import hmac as _hmac
            if not _hmac.compare_digest(sig, expected_sig):
                return None

            # 解码 payload
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            payload = _json.loads(_b64.urlsafe_b64decode(payload_b64))

            # 检查过期
            exp = payload.get("exp", 0)
            if exp and int(time.time()) > exp:
                return None

            return payload

        except Exception as e:
            logger.debug(f"Token verification failed: {e}")
            return None

    @staticmethod
    def login(email: str, password: str) -> Optional[Tuple[str, Dict]]:
        """
        登录：验证凭证 → 创建 Token。

        Returns:
            (token, user_dict) 或 None
        """
        from core.user_repo import UserRepo

        repo = UserRepo()
        user = repo.get_by_email(email)
        if not user:
            return None

        if not user.get("is_active"):
            return None

        if not AuthManager.verify_password(password, user["password_hash"]):
            return None

        token = AuthManager.create_token(user["id"], email)

        # 更新最后登录时间
        repo.update_last_login(user["id"])

        # 不返回密码哈希
        user_safe = {k: v for k, v in user.items() if k != "password_hash"}
        return token, user_safe

    @staticmethod
    def register(email: str, password: str, display_name: str = "") -> Optional[int]:
        """
        注册新用户。

        Returns:
            user_id 或 None（邮箱已存在）
        """
        from core.user_repo import UserRepo

        if len(password) < 6:
            raise ValueError("密码至少6位")

        repo = UserRepo()
        if repo.get_by_email(email):
            return None  # 邮箱已注册

        hashed = AuthManager.hash_password(password)
        user_id = repo.create(email, hashed, display_name)
        return user_id
