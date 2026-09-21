"""组合管理接口"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from api.deps import get_portfolio_manager

router = APIRouter()


class CreatePortfolioRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""


class AddHoldingRequest(BaseModel):
    fund_code: str
    amount: float = 0
    weight: float = 0
    purchase_date: str = ""
    notes: str = ""


@router.post("/")
async def create_portfolio(req: CreatePortfolioRequest):
    """创建组合"""
    pm = get_portfolio_manager()
    pid = pm.create(req.name, req.description)
    return {"id": pid, "name": req.name}


@router.get("/")
async def list_portfolios():
    """列出所有组合"""
    pm = get_portfolio_manager()
    portfolios = pm.list_all()
    return {"total": len(portfolios), "items": [p.to_dict() for p in portfolios]}


@router.get("/{portfolio_id}")
async def get_portfolio(portfolio_id: int):
    """获取单个组合详情"""
    pm = get_portfolio_manager()
    p = pm.get(portfolio_id)
    if not p:
        raise HTTPException(status_code=404, detail="组合不存在")
    return p.to_dict()


@router.delete("/{portfolio_id}")
async def delete_portfolio(portfolio_id: int):
    """删除组合"""
    pm = get_portfolio_manager()
    pm.delete(portfolio_id)
    return {"status": "deleted"}


@router.post("/{portfolio_id}/holdings")
async def add_holding(portfolio_id: int, req: AddHoldingRequest):
    """添加持仓"""
    pm = get_portfolio_manager()
    pm.add_holding(portfolio_id, req.fund_code, req.amount, req.weight, req.purchase_date, req.notes)
    return {"status": "added"}


@router.delete("/{portfolio_id}/holdings/{fund_code}")
async def remove_holding(portfolio_id: int, fund_code: str):
    """删除持仓"""
    pm = get_portfolio_manager()
    pm.remove_holding(portfolio_id, fund_code)
    return {"status": "removed"}


@router.get("/{portfolio_id}/risk")
async def analyze_risk(portfolio_id: int):
    """组合风险分析"""
    pm = get_portfolio_manager()
    conc = pm.analyze_concentration(portfolio_id)
    metrics = pm.compute_portfolio_metrics(portfolio_id)
    corr = pm.analyze_correlation(portfolio_id)
    return {
        "concentration": conc,
        "metrics": metrics,
        "correlation": corr.to_dict() if not corr.empty else {},
    }


@router.get("/{portfolio_id}/nav")
async def get_nav_series(portfolio_id: int):
    """组合净值序列"""
    pm = get_portfolio_manager()
    nav = pm.get_nav_series(portfolio_id)
    if nav.empty:
        return {"data": []}
    df = nav.reset_index()
    df.columns = ["date", "nav"]
    return {"data": df.to_dict(orient="records")}
