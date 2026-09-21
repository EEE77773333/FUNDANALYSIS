"""
API 依赖注入
===========
FastAPI Depends 函数，延迟加载 core 单例。
"""

from functools import lru_cache
from typing import Optional

import os

from fastapi import Header, HTTPException


def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    """
    API 访问鉴权依赖。

    - 需在环境变量 API_ACCESS_KEY 中配置访问密钥；
    - 客户端通过请求头 X-API-Key 传入；
    - 未配置密钥时拒绝所有请求（secure-by-default，不静默开放）。
    """
    expected = os.getenv("API_ACCESS_KEY", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="API 未配置访问密钥（请设置环境变量 API_ACCESS_KEY）",
        )
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=401, detail="无效或缺失的 API Key")
    return True


def get_fetcher():
    """获取 DataFetcher 单例"""
    from core.data_fetcher import get_fetcher as _get
    return _get()


def get_analyzer():
    """获取 AIAnalyzer 实例（API 请求级：每次新建，避免并发请求间 switch_model 串台）"""
    from core.ai_analyzer import AIAnalyzer
    return AIAnalyzer()


def get_prompt_manager():
    """获取 PromptManager 单例"""
    from core.prompt_templates import get_prompt_manager as _get
    return _get()


def get_portfolio_manager():
    """获取 PortfolioManager 单例"""
    from core.portfolio import get_portfolio_manager as _get
    return _get()


def get_history_manager():
    """获取 HistoryManager 单例"""
    from core.history import get_history_manager as _get
    return _get()


def get_alert_engine():
    """获取 AlertEngine 单例"""
    from core.alert_engine import get_alert_engine as _get
    return _get()


def get_signal_manager():
    """获取 SignalManager 单例"""
    from core.signals import get_signal_manager as _get
    return _get()


def get_evaluation_manager():
    """获取 EvaluationManager 单例"""
    from core.signal_evaluation import get_evaluation_manager as _get
    return _get()


def get_notification_manager():
    """获取 NotificationManager 单例"""
    from core.notifications import get_notification_manager as _get
    return _get()


def get_model_router():
    """获取 ModelRouter 单例"""
    from core.model_router import get_model_router as _get
    return _get()
