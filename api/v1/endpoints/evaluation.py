"""AI 建议事后验证接口"""

from fastapi import APIRouter, Query
from typing import Optional

from api.deps import get_evaluation_manager

router = APIRouter()


@router.post("/run")
async def run_evaluation():
    """执行多窗口验证回填任务"""
    em = get_evaluation_manager()
    result = em.run_batch()
    return {"status": "ok", **result}


@router.get("/summary")
async def get_summary():
    """验证 KPI 汇总"""
    em = get_evaluation_manager()
    return em.get_summary()


@router.get("/calibration")
async def get_calibration():
    """置信度校准分桶数据"""
    em = get_evaluation_manager()
    return {"buckets": em.get_calibration_data()}


@router.get("/items")
async def list_evaluations(
    source_type: Optional[str] = Query(None, description="signal | analysis"),
    fund_code: Optional[str] = Query(None),
    horizon_days: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """验证明细列表"""
    em = get_evaluation_manager()
    items = em.list_evaluations(
        source_type=source_type,
        fund_code=fund_code,
        horizon_days=horizon_days,
        limit=limit,
    )
    return {"total": len(items), "items": [e.to_dict() for e in items]}


@router.get("/pending")
async def get_pending():
    """待验证队列统计"""
    em = get_evaluation_manager()
    return em.count_pending()
