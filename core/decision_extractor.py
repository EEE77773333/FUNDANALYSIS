"""
从 AI 输出中提取结构化决策仪表盘 JSON
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

from .decision_schema import empty_dashboard, validate_dashboard

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
_JSON_BLOCK = re.compile(r"(\{[\s\S]*\"schema_version\"[\s\S]*?\})\s*(?:```|$)", re.IGNORECASE)


def extract_dashboard(text: str) -> Optional[Dict[str, Any]]:
  """
  从 Markdown/混合文本中提取 decision dashboard JSON。
  优先 ```json 代码块，其次含 schema_version 的 JSON 对象。
  """
  if not text or not text.strip():
    return None

  candidates: list[str] = []

  for m in _JSON_FENCE.finditer(text):
    candidates.append(m.group(1))

  if not candidates:
    m = _JSON_BLOCK.search(text)
    if m:
      candidates.append(m.group(1))

  # 兜底：找最后一个看起来像完整 JSON 的大括号块
  if not candidates:
    start = text.find("{")
    while start != -1:
      chunk = _try_balanced_json(text[start:])
      if chunk and "schema_version" in chunk:
        candidates.append(chunk)
      start = text.find("{", start + 1)

  for raw in candidates:
    parsed = _parse_json(raw)
    if parsed:
      return validate_dashboard(parsed)
  return None


def split_markdown_and_dashboard(text: str) -> Tuple[str, Optional[Dict[str, Any]]]:
  """分离正文 Markdown 与 dashboard JSON。"""
  dashboard = extract_dashboard(text)
  if not dashboard:
    return text, None

  body = text
  for pattern in (_JSON_FENCE, _JSON_BLOCK):
    body = pattern.sub("", body)
  body = re.sub(r"\n{3,}", "\n\n", body).strip()
  dashboard["markdown_fallback"] = body or text
  return body, dashboard


def merge_with_meta(
    dashboard: Optional[Dict[str, Any]],
    *,
    page_name: str = "",
    fund_code: str = "",
    fund_name: str = "",
    model: str = "",
    markdown_fallback: str = "",
) -> Dict[str, Any]:
  """补全 meta 字段。"""
  base = validate_dashboard(dashboard or empty_dashboard())
  base["meta"]["page_name"] = page_name or base["meta"].get("page_name", "")
  base["meta"]["fund_code"] = fund_code or base["meta"].get("fund_code", "")
  base["meta"]["fund_name"] = fund_name or base["meta"].get("fund_name", "")
  base["meta"]["model"] = model or base["meta"].get("model", "")
  if markdown_fallback:
    base["markdown_fallback"] = markdown_fallback
  return base


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
  try:
    data = json.loads(raw)
    return data if isinstance(data, dict) else None
  except json.JSONDecodeError:
    # 简单修复：去掉尾部逗号
    fixed = re.sub(r",\s*}", "}", raw)
    fixed = re.sub(r",\s*]", "]", fixed)
    try:
      data = json.loads(fixed)
      return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
      return None


def _try_balanced_json(text: str) -> Optional[str]:
  depth = 0
  for i, ch in enumerate(text):
    if ch == "{":
      depth += 1
    elif ch == "}":
      depth -= 1
      if depth == 0:
        return text[: i + 1]
  return None


# 追加到 system/user prompt 的标准输出指令
DECISION_JSON_INSTRUCTION = """
---
请在分析正文之后，**额外**输出一个 JSON 代码块（```json ... ```），严格遵循以下 schema：

{
  "schema_version": "1.0",
  "meta": {"page_name": "", "fund_code": "", "fund_name": "", "data_quality_score": 0.0-1.0},
  "core_conclusion": {
    "rating_stars": 1-5 或 null,
    "one_liner": "一句话核心结论",
    "suitability": ["适配投资者类型"],
    "not_suitable": ["不适配类型"]
  },
  "data_perspective": {
    "metrics": [{"label": "指标名", "value": "值", "badge": "可选标签"}],
    "valuation_context": "估值/市场环境简述"
  },
  "risk_watchlist": [{"level": "info|warning|danger", "item": "风险项", "detail": "说明"}],
  "observation_plan": {
    "horizon": "观察期限",
    "conditions": ["触发再评估的条件"],
    "review_triggers": ["复核节点"]
  },
  "signal_for_validation": {
    "action": "buy|add|hold|reduce|sell|watch|avoid",
    "confidence": 0.0-1.0,
    "horizon_days": 20
  },
  "attribution": {"performance": 0.0, "valuation": 0.0, "manager": 0.0, "macro": 0.0},
  "compliance": {"disclaimer": "不构成投资建议"}
}

要求：JSON 必须合法；不要输出买入/卖出交易指令，signal_for_validation 仅表示适配度观察方向。
"""
