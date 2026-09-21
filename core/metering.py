"""
AI 用量计量
============
集中记录每一次成功的 LLM 调用，用于配额扣减与用量展示。

**为什么放在 LLM 层内部而不是各页面里**
    页面里的手动记账必然漏（本项目改造前 30 个页面只有 1 处记账，
    配额体系等于没生效）。把计量下沉到 `AIAnalyzer.analyze / analyze_stream`，
    任何现有或未来的 AI 功能都自动被计入，不可能漏。

两种运行形态
-----------
- **EDITION=community**（开源自部署，默认）
    不做任何限额，仅累计用量供用户自己查看。用户自担模型成本。

- **EDITION=cloud**（你运营的托管版）
    按用户套餐扣减每日配额。但有一个重要例外：
    **用户自带密钥（BYOK）的调用不扣配额** —— 那部分成本由用户自己承担，
    占你的额度没有道理。

计量原则
-------
- 只统计成功的调用（失败不扣用户额度）
- 每次调用记一次（流式与非流式一致）
- 跨天自动重置，按北京时间
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 运行形态
EDITION = (os.getenv("EDITION", "community") or "community").strip().lower()

_lock = threading.Lock()


def is_cloud_edition() -> bool:
    """是否为托管运营版（需要执行套餐配额）。"""
    return EDITION in ("cloud", "saas", "hosted")


def _llm_source_is_byok() -> bool:
    """当前生效的 LLM 配置是否来自用户自带密钥。"""
    try:
        from .config import config
        return config.effective_llm.source == "user"
    except Exception:
        return False


def note_ai_call(usage: Optional[Dict[str, Any]] = None, model: str = "", source: str = "") -> bool:
    """
    记录一次成功的 AI 调用。

    Args:
        usage: {"input_tokens": n, "output_tokens": n}
        model: 实际使用的模型名
        source: 调用来源标签（如 "famas" / "screen" / "digest"），便于用量分析

    Returns:
        是否真正写入了配额计数
    """
    usage = usage or {}

    # 自带密钥的调用不计入托管配额（成本由用户自担）
    byok = _llm_source_is_byok()

    try:
        import streamlit as st
        user = st.session_state.get("user") or {}
    except Exception:
        user = {}

    uid = user.get("id")

    if not is_cloud_edition():
        # 社区版：只记流水，不做限额
        _log_usage(uid, usage, model, source, byok, counted=False)
        return False

    if byok:
        # 托管版 + 用户自带密钥：不扣配额
        _log_usage(uid, usage, model, source, byok, counted=False)
        return False

    if not uid:
        return False

    try:
        with _lock:
            from .user_repo import UserRepo
            repo = UserRepo()
            repo.increment_api_call(int(uid))
            usage_row = repo.get_usage(int(uid))
            user["api_calls_today"] = usage_row.get("api_calls_today", 0)
            user["api_calls_limit"] = usage_row.get("api_calls_limit", user.get("api_calls_limit"))
            try:
                import streamlit as st
                st.session_state["user"] = user
            except Exception:
                pass
        _log_usage(uid, usage, model, source, byok, counted=True)
        return True
    except Exception:
        logger.exception("AI 用量记账失败 user_id=%s", uid)
        return False


def _log_usage(uid, usage, model, source, byok, counted: bool) -> None:
    """写一行日志，便于运营侧对账。"""
    in_tok = usage.get("input_tokens", 0) or 0
    out_tok = usage.get("output_tokens", 0) or 0
    logger.info(
        "[AI用量] user=%s model=%s source=%s tokens=%s+%s byok=%s counted=%s",
        uid, model or "-", source or "-", in_tok, out_tok, byok, counted,
    )


def usage_summary() -> Dict[str, Any]:
    """当前用户的用量概况（供账户设置页展示）。"""
    try:
        import streamlit as st
        user = st.session_state.get("user") or {}
    except Exception:
        user = {}
    uid = user.get("id")
    if not uid:
        return {}

    try:
        from .user_repo import UserRepo
        from .middleware import QUOTA_MAP
        repo = UserRepo()
        row = repo.get_usage(int(uid))
        tier = row.get("tier", "free")
        limit = QUOTA_MAP.get(tier, QUOTA_MAP["free"]).get(
            "ai_analysis", row.get("api_calls_limit", 100)
        )
        used = row.get("api_calls_today", 0)
        return {
            "tier": tier,
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "unlimited": limit >= 99999,
            "edition": EDITION,
            "enforced": is_cloud_edition(),
        }
    except Exception:
        return {}
