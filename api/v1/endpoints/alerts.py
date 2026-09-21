"""预警管理接口"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from api.deps import get_alert_engine

router = APIRouter()


class CreateAlertRuleRequest(BaseModel):
    name: str
    alert_type: str = Field(..., description="nav_drop_pct | drawdown_pct | consecutive_down_days")
    fund_codes: List[str]
    parameters: dict = Field(default_factory=dict)
    severity: str = "medium"


@router.get("/rules")
async def list_rules(enabled_only: bool = False):
    """列出预警规则"""
    ae = get_alert_engine()
    rules = ae.list_rules(enabled_only=enabled_only)
    return {"total": len(rules), "items": [r.to_dict() for r in rules]}


@router.post("/rules")
async def create_rule(req: CreateAlertRuleRequest):
    """创建预警规则"""
    ae = get_alert_engine()
    rid = ae.create_rule(req.name, req.alert_type, req.fund_codes, req.parameters, req.severity)
    return {"id": rid, "name": req.name}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int):
    """删除预警规则"""
    ae = get_alert_engine()
    ae.delete_rule(rule_id)
    return {"status": "deleted"}


@router.put("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: int, enabled: bool = True):
    """启用/禁用规则"""
    ae = get_alert_engine()
    ae.toggle_rule(rule_id, enabled)
    return {"status": "enabled" if enabled else "disabled"}


@router.get("/triggers")
async def list_triggers(
    fund_code: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    limit: int = 100,
):
    """查询触发历史"""
    ae = get_alert_engine()
    triggers = ae.get_triggers(fund_code=fund_code, acknowledged=acknowledged, limit=limit)
    return {
        "total": len(triggers),
        "items": [
            {
                "id": t.id, "rule_id": t.rule_id, "fund_code": t.fund_code,
                "message": t.message, "severity": t.severity,
                "triggered_at": t.triggered_at, "acknowledged": t.acknowledged,
            }
            for t in triggers
        ],
    }


@router.post("/triggers/{trigger_id}/acknowledge")
async def acknowledge_trigger(trigger_id: int):
    """确认预警"""
    ae = get_alert_engine()
    ae.acknowledge_trigger(trigger_id)
    return {"status": "acknowledged"}


@router.post("/evaluate")
async def evaluate_all():
    """立即执行全部规则巡检"""
    ae = get_alert_engine()
    triggers = ae.evaluate_all()
    return {
        "total_triggers": len(triggers),
        "high": sum(1 for t in triggers if t.severity == "high"),
        "medium": sum(1 for t in triggers if t.severity == "medium"),
        "low": sum(1 for t in triggers if t.severity == "low"),
        "items": [
            {"fund_code": t.fund_code, "message": t.message, "severity": t.severity}
            for t in triggers
        ],
    }
