"""
ETF 联接基金 → 场内 ETF 映射
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

_MAP_PATH = Path(__file__).parent.parent / "data" / "etf_linkage_map.json"
_CACHE: Optional[Dict[str, dict]] = None


def load_etf_map() -> Dict[str, dict]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if _MAP_PATH.exists():
        try:
            _CACHE = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
            return _CACHE
        except Exception:
            pass
    _CACHE = {}
    return _CACHE


def is_link_fund(fund_name: str) -> bool:
    if not fund_name:
        return False
    return "联接" in fund_name or "链接" in fund_name


def resolve_underlying_etf(fund_code: str, fund_name: str = "") -> Optional[Tuple[str, str, str]]:
    """
    解析联接基金对应的场内 ETF。

    Returns:
        (etf_code, etf_name, match_reason) 或 None
    """
    name = fund_name or ""
    etf_map = load_etf_map()

    # 1) 名称中直接带 6 位 ETF 代码
    m = re.search(r"(?:ETF|etf)[^\d]{0,8}(\d{6})", name)
    if m and m.group(1) in etf_map:
        code = m.group(1)
        return code, etf_map[code].get("name", code), "名称含ETF代码"

    # 2) 关键词匹配
    for code, info in etf_map.items():
        for kw in info.get("keywords", []):
            if kw and kw in name:
                return code, info.get("name", code), f"关键词:{kw}"

    # 3) 从基金简称提取标的名（如「博时黄金ETF联接C」→ 黄金）
    if is_link_fund(name):
        cleaned = re.sub(r"(联接|链接)[A-C]?$", "", name)
        cleaned = re.sub(r"^[A-Za-z\u4e00-\u9fff]+", "", cleaned)  # 去公司前缀粗略
        for code, info in etf_map.items():
            etf_n = info.get("name", "")
            for token in (etf_n, *info.get("keywords", [])):
                if len(token) >= 2 and token in name:
                    return code, etf_n, f"标的名:{token}"

    return None
