"""分析历史接口"""

from fastapi import APIRouter, Query
from typing import Optional
from api.deps import get_history_manager

router = APIRouter()


@router.get("/")
async def list_history(
    page_name: Optional[str] = Query(None, description="页面名称"),
    fund_code: Optional[str] = Query(None, description="基金代码"),
    search: Optional[str] = Query(None, description="关键词搜索"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """分页查询分析历史"""
    hm = get_history_manager()
    records = hm.list_all(
        page_name=page_name,
        fund_code=fund_code,
        search=search,
        limit=limit,
        offset=offset,
    )
    total = hm.count(page_name=page_name, fund_code=fund_code)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [r.to_dict() for r in records],
    }


@router.get("/{record_id}")
async def get_record(record_id: int):
    """获取单条历史记录详情"""
    hm = get_history_manager()
    rec = hm.get(record_id)
    if not rec:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="记录不存在")
    return {
        "id": rec.id,
        "page_name": rec.page_name,
        "fund_code": rec.fund_code,
        "fund_name": rec.fund_name,
        "result_content": rec.result_content,
        "usage": rec.usage,
        "elapsed_seconds": rec.elapsed_seconds,
        "model": rec.model,
        "created_at": rec.created_at,
        "structured_result": rec.structured_result,
    }


@router.get("/{record_id}/dashboard")
async def get_record_dashboard(record_id: int):
    """获取单条历史记录的结构化决策仪表盘 JSON"""
    from fastapi import HTTPException
    from core.decision_schema import validate_dashboard

    hm = get_history_manager()
    rec = hm.get(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="记录不存在")
    data = rec.structured_result
    if not data:
        raise HTTPException(status_code=404, detail="该记录无结构化决策仪表盘")
    return validate_dashboard(data)


@router.delete("/{record_id}")
async def delete_record(record_id: int):
    """删除历史记录"""
    hm = get_history_manager()
    hm.delete(record_id)
    return {"status": "deleted"}


@router.get("/compare/funds")
async def compare_funds(
    fund_codes: str = Query(..., description="逗号分隔的基金代码"),
    page_name: Optional[str] = Query(None, description="页面筛选"),
):
    """多基金横向对比"""
    codes = [c.strip() for c in fund_codes.split(",") if c.strip()]
    hm = get_history_manager()
    records = hm.compare_funds(codes, page_name=page_name)
    return {
        "items": {code: rec.to_dict() for code, rec in records.items()},
    }


@router.get("/fund/{fund_code}")
async def get_fund_history(
    fund_code: str,
    limit: int = Query(20, ge=1, le=100),
):
    """单基金时间序列"""
    hm = get_history_manager()
    records = hm.get_for_fund(fund_code, limit=limit)
    return {
        "fund_code": fund_code,
        "total": len(records),
        "items": [r.to_dict() for r in records],
    }
