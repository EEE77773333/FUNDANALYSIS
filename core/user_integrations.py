"""
用户自有集成配置（BYOK / BYO-DataSource）
========================================
让每个用户使用**自己的** LLM 密钥与行情数据源账号，而不是共用服务器上的额度。
这是自部署体验与云端成本解耦的关键：服务器只出算力和代码，模型成本由用户自担。

配置优先级（高 → 低）：
    1. 会话内临时覆盖（st.session_state，UI 未保存的即时生效项）
    2. 当前登录用户的库内配置（user_integrations 表）
    3. .env / config.yaml（自部署用户的一次性全局配置）

安全说明：
    密钥以明文存入 user_integrations.llm_json，与数据库同等安全级别。
    界面上一律只回显掩码（sk-abcd****wxyz），不回传明文。
    多租户生产环境建议改用 KMS / 独立的密钥托管服务，并开启数据库加密。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional

from .db import get_connection, get_user_id, now_iso
from .llm_presets import get_preset, infer_preset, DEFAULT_PRESET

logger = logging.getLogger(__name__)

# 会话内覆盖项的 session_state 键
SESSION_LLM_KEY = "_llm_override"
SESSION_DATA_KEY = "_data_override"

LLM_FIELDS = ("preset", "base_url", "api_key", "model", "protocol")
DATA_FIELDS = ("provider", "tushare_token", "cache_ttl")


# ============================================================
# 掩码工具
# ============================================================

def mask_key(key: Optional[str]) -> str:
    """把密钥变成可安全回显的掩码形式。"""
    if not key:
        return ""
    s = str(key)
    if len(s) <= 8:
        return "*" * len(s)
    return f"{s[:4]}{'*' * min(len(s) - 8, 12)}{s[-4:]}"


def is_masked(value: Optional[str]) -> bool:
    """判断传入值是否本身就是掩码（避免把掩码当成新密钥存回去）。"""
    return bool(value) and "*" in str(value)


# ============================================================
# 有效配置解析结果
# ============================================================

@dataclass
class EffectiveLLMConfig:
    """解析后的生效 LLM 配置。"""

    preset: str = DEFAULT_PRESET
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    protocol: str = "openai"
    source: str = "env"  # "session" | "user" | "env" | "none"

    @property
    def is_configured(self) -> bool:
        """是否具备可用配置（本地服务不要求 key）。"""
        preset_obj = get_preset(self.preset)
        needs_key = preset_obj.requires_key if preset_obj else True
        if needs_key and not (self.api_key and len(self.api_key) > 8):
            return False
        return bool(self.base_url or self.protocol == "anthropic") and bool(self.model)

    @property
    def is_local(self) -> bool:
        p = get_preset(self.preset)
        return bool(p and p.is_local)

    @property
    def api_key_masked(self) -> str:
        return mask_key(self.api_key) or "未配置"

    @property
    def source_label(self) -> str:
        return {
            "session": "本次会话临时设置",
            "user": "我的账户配置",
            "env": "服务端 .env 配置",
            "none": "未配置",
        }.get(self.source, self.source)


# ============================================================
# 库内配置读写
# ============================================================

def _load_row(user_id: Optional[int]) -> Dict[str, Any]:
    uid = user_id or get_user_id()
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT llm_json, data_json FROM user_integrations WHERE user_id = ?"
                if _is_sqlite() else
                "SELECT llm_json, data_json FROM user_integrations WHERE user_id = %s",
                (uid,),
            ).fetchone()
            if not row:
                return {}
            out: Dict[str, Any] = {}
            for col in ("llm_json", "data_json"):
                raw = row[col] if not hasattr(row, "get") else row.get(col)
                out[col] = _as_dict(raw)
            return out
    except Exception as e:
        logger.debug("读取 user_integrations 失败: %s", e)
        return {}


def _is_sqlite() -> bool:
    from .db import DB_MODE
    return DB_MODE != "postgresql"


def _as_dict(raw: Any) -> Dict[str, Any]:
    """兼容 TEXT(JSON 字符串) 与 JSONB(已是 dict) 两种存储形态。"""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "ignore")
    try:
        val = json.loads(raw)
        return dict(val) if isinstance(val, dict) else {}
    except Exception:
        return {}


def _upsert(user_id: Optional[int], column: str, payload: Dict[str, Any]) -> bool:
    """写入 llm_json 或 data_json。"""
    if column not in ("llm_json", "data_json"):
        raise ValueError(f"非法列名: {column}")
    uid = user_id or get_user_id()
    ph = "?" if _is_sqlite() else "%s"
    body = json.dumps(payload, ensure_ascii=False)
    try:
        with get_connection() as conn:
            exists = conn.execute(
                f"SELECT 1 FROM user_integrations WHERE user_id = {ph}", (uid,)
            ).fetchone()
            if exists:
                conn.execute(
                    f"UPDATE user_integrations SET {column} = {ph}, updated_at = {ph} "
                    f"WHERE user_id = {ph}",
                    (body, now_iso(), uid),
                )
            else:
                other = "data_json" if column == "llm_json" else "llm_json"
                conn.execute(
                    f"INSERT INTO user_integrations (user_id, {column}, {other}, updated_at) "
                    f"VALUES ({ph}, {ph}, {ph}, {ph})",
                    (uid, body, "{}", now_iso()),
                )
        return True
    except Exception as e:
        logger.warning("写入 user_integrations.%s 失败: %s", column, e)
        return False


# ============================================================
# 对外 API
# ============================================================

def get_user_llm(user_id: Optional[int] = None) -> Dict[str, Any]:
    """读取用户库内 LLM 配置（明文，仅供内部分辨率解析使用）。"""
    return _load_row(user_id).get("llm_json", {})


def get_user_data_source(user_id: Optional[int] = None) -> Dict[str, Any]:
    """读取用户库内数据源配置（明文）。"""
    return _load_row(user_id).get("data_json", {})


def save_user_llm(cfg: Dict[str, Any], user_id: Optional[int] = None) -> bool:
    """
    保存用户 LLM 配置。

    只接受 LLM_FIELDS 中的键；api_key 若为掩码或被省略则保留原值，
    避免「界面回显掩码→用户没改→保存把真 key 覆盖成掩码」这类事故。
    """
    uid = user_id or get_user_id()
    current = get_user_llm(uid)
    patch = {k: cfg[k] for k in LLM_FIELDS if k in cfg and cfg[k] is not None}

    if "api_key" in patch and is_masked(patch["api_key"]):
        patch.pop("api_key")
    if not patch.get("api_key") and current.get("api_key") and "api_key" not in patch:
        patch["api_key"] = current["api_key"]

    merged = {**current, **patch}

    # 按预设补全缺省 base_url / protocol，减少用户手填
    preset = get_preset(merged.get("preset"))
    if preset:
        if not merged.get("base_url"):
            merged["base_url"] = preset.base_url
        if not merged.get("protocol"):
            merged["protocol"] = preset.protocol

    merged = {k: merged[k] for k in LLM_FIELDS if k in merged}
    return _upsert(uid, "llm_json", merged)


def save_user_data_source(cfg: Dict[str, Any], user_id: Optional[int] = None) -> bool:
    """保存用户数据源配置。tushare_token 同样支持掩码占位。"""
    uid = user_id or get_user_id()
    current = get_user_data_source(uid)
    patch = {k: cfg[k] for k in DATA_FIELDS if k in cfg and cfg[k] is not None}
    if "tushare_token" in patch and is_masked(patch["tushare_token"]):
        patch.pop("tushare_token")
    merged = {**current, **patch}
    merged = {k: merged[k] for k in DATA_FIELDS if k in merged}
    return _upsert(uid, "data_json", merged)


def clear_user_llm(user_id: Optional[int] = None) -> bool:
    """清除用户 LLM 配置，回退到服务端 .env。"""
    return _upsert(user_id or get_user_id(), "llm_json", {})


def set_session_override(cfg: Optional[Dict[str, Any]]) -> None:
    """
    设置会话内临时 LLM 覆盖（不落库）。

    典型用法：用户在侧边栏临时试一个模型，不想改动账户配置。
    """
    try:
        import streamlit as st
        if cfg:
            st.session_state[SESSION_LLM_KEY] = cfg
        else:
            st.session_state.pop(SESSION_LLM_KEY, None)
        st.session_state.pop("_ai_analyzer", None)  # 让下次调用重建后端
    except Exception:
        pass


def set_session_model(model: str) -> None:
    """
    会话内临时指定模型，保留其他 BYOK 字段。

    用于侧边栏「模型」下拉：用户当次选择应立即作用于分析引擎，
    而不是只写进偏好等下次生效。
    """
    if not model:
        return
    try:
        import streamlit as st
        cur = dict(st.session_state.get(SESSION_LLM_KEY) or {})
        if cur.get("model") == model:
            return
        cur["model"] = model
        st.session_state[SESSION_LLM_KEY] = cur
        st.session_state.pop("_ai_analyzer", None)
    except Exception:
        pass


def clear_session_override() -> None:
    """清除会话内的临时 LLM 覆盖（保存账户配置后调用，避免旧值压住新配置）。"""
    set_session_override(None)


def get_session_override() -> Optional[Dict[str, Any]]:
    try:
        import streamlit as st
        return st.session_state.get(SESSION_LLM_KEY)
    except Exception:
        return None


# ============================================================
# 生效配置解析
# ============================================================

def resolve_llm_config(user_id: Optional[int] = None) -> EffectiveLLMConfig:
    """
    按「会话 → 用户库 → 环境变量」顺序解析出真正要用的 LLM 配置。
    """
    from .config import config as _env_config

    env_cfg = EffectiveLLMConfig(
        preset=getattr(_env_config, "llm_preset", DEFAULT_PRESET),
        base_url=getattr(_env_config, "llm_base_url", ""),
        api_key=getattr(_env_config, "llm_api_key", ""),
        model=getattr(_env_config, "llm_model", ""),
        protocol=getattr(_env_config, "llm_protocol", "openai"),
        source="env",
    )

    def _merge(base: EffectiveLLMConfig, patch: Dict[str, Any], source: str) -> EffectiveLLMConfig:
        if not patch:
            return base
        preset_key = patch.get("preset") or base.preset
        preset_obj = get_preset(preset_key)
        merged = replace(
            base,
            preset=preset_key,
            base_url=patch.get("base_url") or (preset_obj.base_url if preset_obj else "") or base.base_url,
            api_key=patch.get("api_key") or base.api_key,
            model=patch.get("model") or base.model,
            protocol=patch.get("protocol") or (preset_obj.protocol if preset_obj else "") or base.protocol,
            source=source,
        )
        return merged

    result = env_cfg
    user_cfg = get_user_llm(user_id)
    if user_cfg:
        result = _merge(result, user_cfg, "user")
    session_cfg = get_session_override()
    if session_cfg:
        result = _merge(result, session_cfg, "session")

    # 兼容老配置：只填了 DEEPSEEK_* 没填 LLM_PRESET 时，反推预设名
    if result.preset == DEFAULT_PRESET and result.base_url:
        result.preset = infer_preset(result.base_url, result.protocol)

    return result


def resolve_data_source_config(user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    解析生效的数据源配置。

    Returns:
        {"provider": "akshare"|"tushare"|"eastmoney"|"baostock", "tushare_token": str, "cache_ttl": int}
    """
    import os

    env_cfg = {
        "provider": os.getenv("DATA_PROVIDER", "akshare").strip().lower() or "akshare",
        "tushare_token": os.getenv("TUSHARE_TOKEN", "").strip(),
        "cache_ttl": int(os.getenv("QUOTE_CACHE_TTL", "300") or 300),
    }
    merged = dict(env_cfg)
    merged.update({k: v for k, v in get_user_data_source(user_id).items() if v not in (None, "")})

    try:
        import streamlit as st
        sess = st.session_state.get(SESSION_DATA_KEY) or {}
        if sess:
            merged.update({k: v for k, v in sess.items() if v not in (None, "")})
    except Exception:
        pass

    return merged
