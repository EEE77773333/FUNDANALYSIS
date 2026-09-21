"""健康检查"""

from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def health_check():
    return {"status": "healthy", "service": "fund-analysis-api"}


@router.get("/ready")
async def readiness():
    """检查核心服务是否就绪"""
    try:
        from core.config import config
        from core.data_fetcher import get_fetcher
        api_ready = config.is_configured
        fetcher_ok = get_fetcher() is not None
        return {
            "status": "ready" if api_ready and fetcher_ok else "degraded",
            "api_configured": api_ready,
            "data_fetcher": fetcher_ok,
            "provider": config.ai_provider,
            "model": config.active_model,
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}
