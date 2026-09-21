"""基金数据查询"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from api.deps import get_fetcher

router = APIRouter()


@router.get("/search")
async def search_funds(q: str = Query(..., description="搜索关键词（代码/名称/拼音）")):
    """搜索基金"""
    fetcher = get_fetcher()
    df = fetcher.search_fund(q)
    if df is None or df.empty:
        return {"total": 0, "items": []}
    items = df.head(20).to_dict(orient="records")
    return {"total": len(items), "items": items}


@router.get("/{fund_code}/nav")
async def get_nav_history(
    fund_code: str,
    years: int = Query(3, ge=1, le=10, description="回溯年数"),
):
    """获取基金净值历史"""
    fetcher = get_fetcher()
    df = fetcher.get_fund_nav_history(fund_code, years=years)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail="未找到净值数据")
    return {"fund_code": fund_code, "years": years, "count": len(df), "data": df.tail(500).to_dict(orient="records")}


@router.get("/{fund_code}/info")
async def get_fund_info(fund_code: str):
    """获取基金基本信息"""
    fetcher = get_fetcher()
    info = fetcher.get_fund_manager_info(fund_code)
    if not info:
        raise HTTPException(status_code=404, detail="未找到基金信息")
    return {"fund_code": fund_code, **info}


@router.get("/{fund_code}/estimate")
async def get_realtime_estimate(fund_code: str):
    """获取实时估值"""
    fetcher = get_fetcher()
    est = fetcher.get_realtime_estimate(fund_code)
    if not est:
        raise HTTPException(status_code=404, detail="实时估值不可用")
    return est


@router.get("/{fund_code}/holdings")
async def get_holdings(fund_code: str):
    """获取前十大持仓"""
    fetcher = get_fetcher()
    df = fetcher.get_fund_holdings(fund_code)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail="持仓数据不可用")
    return {"fund_code": fund_code, "holdings": df.to_dict(orient="records")}


@router.get("/{fund_code}/comprehensive")
async def get_comprehensive(fund_code: str):
    """一站式综合查询"""
    fetcher = get_fetcher()
    data = fetcher.get_fund_comprehensive(fund_code)
    return data


@router.get("/screen/list")
async def screen_funds(
    fund_type: Optional[str] = Query(None, description="基金类型"),
    min_years: Optional[int] = Query(None, description="最少成立年数"),
    max_drawdown: Optional[float] = Query(None, description="最大回撤阈值"),
    top_n: int = Query(20, ge=5, le=100),
):
    """多维度基金筛选"""
    fetcher = get_fetcher()
    df = fetcher.screen_funds(
        fund_type=fund_type,
        min_years=min_years,
        max_drawdown=max_drawdown,
        top_n=top_n,
    )
    if df is None or df.empty:
        return {"total": 0, "items": []}
    return {"total": len(df), "items": df.to_dict(orient="records")}


@router.get("/macro")
async def get_macro_indicators():
    """获取宏观指标"""
    fetcher = get_fetcher()
    data = fetcher.get_macro_indicators()
    return data
