"""
结构化决策仪表盘 JSON Schema
==============================
基金分析 AI 输出的标准 JSON 结构定义与校验。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.0"

VALID_ACTIONS = {"buy", "add", "hold", "reduce", "sell", "watch", "avoid"}
VALID_RISK_LEVELS = {"info", "warning", "danger"}


def empty_dashboard(
    page_name: str = "",
    fund_code: str = "",
    fund_name: str = "",
    model: str = "",
) -> Dict[str, Any]:
    """返回空模板。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "page_name": page_name,
            "fund_code": fund_code,
            "fund_name": fund_name,
            "model": model,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_quality_score": None,
        },
        "core_conclusion": {
            "rating_stars": None,
            "one_liner": "",
            "suitability": [],
            "not_suitable": [],
        },
        "data_perspective": {"metrics": [], "valuation_context": ""},
        "risk_watchlist": [],
        "observation_plan": {
            "horizon": "",
            "conditions": [],
            "review_triggers": [],
        },
        "signal_for_validation": {
            "action": "watch",
            "confidence": 0.5,
            "horizon_days": 20,
        },
        "attribution": {},
        "compliance": {"disclaimer": "本内容仅供学习研究，不构成投资建议。"},
        "markdown_fallback": "",
    }


def validate_dashboard(data: Dict[str, Any]) -> Dict[str, Any]:
    """轻量校验并规范化 dashboard 字典。"""
    if not isinstance(data, dict):
        return empty_dashboard()

    out = empty_dashboard()
    out["schema_version"] = str(data.get("schema_version", SCHEMA_VERSION))

    meta = data.get("meta") or {}
    if isinstance(meta, dict):
        out["meta"].update({k: meta.get(k, out["meta"].get(k)) for k in out["meta"]})

    cc = data.get("core_conclusion") or {}
    if isinstance(cc, dict):
        stars = cc.get("rating_stars")
        if stars is not None:
            try:
                out["core_conclusion"]["rating_stars"] = max(1, min(5, int(stars)))
            except (TypeError, ValueError):
                pass
        out["core_conclusion"]["one_liner"] = str(cc.get("one_liner", "") or "")
        for key in ("suitability", "not_suitable"):
            val = cc.get(key, [])
            out["core_conclusion"][key] = val if isinstance(val, list) else []

    dp = data.get("data_perspective") or {}
    if isinstance(dp, dict):
        metrics = dp.get("metrics", [])
        out["data_perspective"]["metrics"] = metrics if isinstance(metrics, list) else []
        out["data_perspective"]["valuation_context"] = str(dp.get("valuation_context", "") or "")

    rw = data.get("risk_watchlist", [])
    if isinstance(rw, list):
        cleaned = []
        for item in rw:
            if not isinstance(item, dict):
                continue
            level = str(item.get("level", "info"))
            if level not in VALID_RISK_LEVELS:
                level = "info"
            cleaned.append({
                "level": level,
                "item": str(item.get("item", "")),
                "detail": str(item.get("detail", "")),
            })
        out["risk_watchlist"] = cleaned

    op = data.get("observation_plan") or {}
    if isinstance(op, dict):
        out["observation_plan"]["horizon"] = str(op.get("horizon", "") or "")
        for key in ("conditions", "review_triggers"):
            val = op.get(key, [])
            out["observation_plan"][key] = val if isinstance(val, list) else []

    sfv = data.get("signal_for_validation") or {}
    if isinstance(sfv, dict):
        action = str(sfv.get("action", "watch")).lower()
        if action in VALID_ACTIONS:
            out["signal_for_validation"]["action"] = action
        try:
            conf = float(sfv.get("confidence", 0.5))
            out["signal_for_validation"]["confidence"] = max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            pass
        try:
            out["signal_for_validation"]["horizon_days"] = int(sfv.get("horizon_days", 20))
        except (TypeError, ValueError):
            pass

    attr = data.get("attribution")
    if isinstance(attr, dict):
        out["attribution"] = attr

    comp = data.get("compliance") or {}
    if isinstance(comp, dict) and comp.get("disclaimer"):
        out["compliance"]["disclaimer"] = str(comp["disclaimer"])

    if data.get("markdown_fallback"):
        out["markdown_fallback"] = str(data["markdown_fallback"])

    return out


def dashboard_to_json(data: Dict[str, Any]) -> str:
    return json.dumps(validate_dashboard(data), ensure_ascii=False, indent=2)
