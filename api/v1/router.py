"""
API v1 路由聚合
"""

from fastapi import APIRouter

from api.v1.endpoints import health, funds, analysis, portfolio, history, alerts, signals, export, evaluation

router = APIRouter()

router.include_router(health.router, prefix="/health", tags=["健康检查"])
router.include_router(funds.router, prefix="/funds", tags=["基金数据"])
router.include_router(analysis.router, prefix="/analysis", tags=["AI分析"])
router.include_router(portfolio.router, prefix="/portfolio", tags=["组合管理"])
router.include_router(history.router, prefix="/history", tags=["分析历史"])
router.include_router(alerts.router, prefix="/alerts", tags=["预警管理"])
router.include_router(signals.router, prefix="/signals", tags=["决策信号"])
router.include_router(evaluation.router, prefix="/evaluation", tags=["AI验证"])
router.include_router(export.router, prefix="/export", tags=["结果导出"])
