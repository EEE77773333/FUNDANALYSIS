"""决策信号接口"""

from fastapi import APIRouter, Query
from typing import Optional
from api.deps import get_signal_manager

router = APIRouter()


@router.get("/")
async def list_signals(
    status: Optional[str] = Query(None, description="active/confirmed/rejected/expired"),
    fund_code: Optional[str] = Query(None),
    action: Optional[str] = Query(None, description="buy/add/hold/reduce/sell/watch/avoid"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """查询决策信号"""
    sm = get_signal_manager()
    signals = sm.list_all(status=status, fund_code=fund_code, action=action, limit=limit, offset=offset)
    return {"total": len(signals), "items": [s.to_dict() for s in signals]}


@router.get("/stats")
async def get_statistics():
    """信号统计"""
    sm = get_signal_manager()
    return sm.get_statistics()
