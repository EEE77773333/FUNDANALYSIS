"""
统一实时行情提供（Sina Finance）
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import requests

from .data_fetcher import _http_get
from .utils import safe_float

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
}

_NO_PROXY = {"http": None, "https": None}
_TIMEOUT = 10


def sina_get(url: str) -> Optional[str]:
    """Sina API 直连（绕过系统代理，gb2312 编码）。13/27/28 共用。"""
    try:
        r = requests.get(url, headers=UA_HEADERS, timeout=_TIMEOUT, proxies=_NO_PROXY)
        r.encoding = "gb2312"
        return r.text
    except Exception:
        return None


def get_index_quotes(index_map: Dict[str, str]) -> Dict[str, dict]:
    """
    批量获取指数行情。

    Args:
        index_map: {显示名: sina代码}，如 {"上证指数": "s_sh000001"}
    Returns:
        {显示名: {最新价, 涨跌幅, 涨跌额}}
    """
    out: Dict[str, dict] = {}
    codes = ",".join(index_map.values())
    if not codes:
        return out
    text = sina_get(f"https://hq.sinajs.cn/list={codes}")
    if not text:
        return out
    for name, code in index_map.items():
        m = re.search(rf'var hq_str_{re.escape(code)}="([^"]*)"', text)
        if not m:
            continue
        parts = m.group(1).split(",")
        if len(parts) < 4:
            continue
        try:
            out[name] = {
                "最新价": float(parts[1]),
                "涨跌额": float(parts[2]),
                "涨跌幅": float(parts[3]),
            }
        except (ValueError, IndexError):
            continue
    return out


def normalize_stock_code(code: str) -> Optional[str]:
    """将股票/ETF代码转为 Sina list 参数，如 sh600519 / sz000001。"""
    if not code:
        return None
    c = str(code).strip().upper()
    c = c.replace(".SH", "").replace(".SZ", "").replace(".OF", "")
    if len(c) == 6 and c.isdigit():
        if c.startswith(("5", "6", "9")):
            return f"sh{c}"
        if c.startswith(("0", "1", "2", "3")):
            return f"sz{c}"
    return None


def get_sector_board(board_type: str = "industry", page_size: int = 50) -> List[dict]:
    """
    获取行业板块行情（涨跌幅）。

    数据源：AKShare `stock_sector_spot`（Sina 行业板块）。
    东财 push2 clist 接口对本机常被反爬主动断连，故统一走 Sina。

    Returns:
        [{"name": 板块名, "change_pct": 涨跌幅%}, ...]；失败返回空列表
    """
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        df = ak.stock_sector_spot(indicator="行业")
    except Exception:
        return []
    if df is None or getattr(df, "empty", True) or "板块" not in df.columns:
        return []

    chg_col = "涨跌幅" if "涨跌幅" in df.columns else None
    rows: List[dict] = []
    for _, row in df.iterrows():
        name = str(row.get("板块", "")).strip()
        if not name:
            continue
        try:
            chg = float(row.get(chg_col)) if chg_col else 0.0
        except (TypeError, ValueError):
            chg = 0.0
        rows.append({"name": name, "change_pct": chg})
    return rows


def get_realtime_quotes(codes: List[str]) -> Dict[str, dict]:
    """
    批量获取 A 股/ETF 实时行情。

    Returns:
        {原始代码: {name, price, prev_close, change_pct, sina_code}}
    """
    out: Dict[str, dict] = {}
    mapping: List[Tuple[str, str]] = []
    for raw in codes:
        sina = normalize_stock_code(raw)
        if sina:
            mapping.append((raw, sina))

    if not mapping:
        return out

    # Sina 支持逗号分隔，每批最多 50
    batch_size = 40
    for i in range(0, len(mapping), batch_size):
        batch = mapping[i : i + batch_size]
        query = ",".join(s for _, s in batch)
        text = _http_get(
            f"https://hq.sinajs.cn/list={query}",
            headers=UA_HEADERS,
        )
        if not text:
            continue
        for raw, sina in batch:
            parsed = _parse_sina_line(text, sina)
            if parsed:
                out[raw] = parsed
    return out


def _parse_sina_line(text: str, sina_code: str) -> Optional[dict]:
    pattern = rf'var hq_str_{re.escape(sina_code)}="([^"]*)"'
    m = re.search(pattern, text)
    if not m:
        return None
    parts = m.group(1).split(",")
    if len(parts) < 4:
        return None
    name = parts[0]
    try:
        prev_close = float(parts[2])
        price = float(parts[3])
    except (ValueError, IndexError):
        return None
    if prev_close <= 0:
        return None
    chg_pct = (price - prev_close) / prev_close * 100
    return {
        "name": name,
        "price": price,
        "prev_close": prev_close,
        "change_pct": chg_pct,
        "sina_code": sina_code,
    }
