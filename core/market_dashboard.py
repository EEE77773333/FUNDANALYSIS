"""
实时市场仪表盘数据层
==================
广度 / 成交额 / 风格 / 北南向 / 跨资产 / 估值 / 概念 / 分时 / 持仓行业联动。
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

# 抑制 akshare 进度条刷屏
os.environ.setdefault("TQDM_DISABLE", "1")

from .quote_provider import get_index_quotes, sina_get
from .utils import safe_float

_CN_TZ = timezone(timedelta(hours=8))
_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com",
}
_NO_PROXY = {"http": None, "https": None}

MAIN_INDEX_MAP = {
    "上证指数": "s_sh000001",
    "深证成指": "s_sz399001",
    "创业板指": "s_sz399006",
    "科创50": "s_sh000688",
    "沪深300": "s_sh000300",
    "中证500": "s_sh000905",
}

STYLE_INDEX_MAP = {
    "大盘·沪深300": "s_sh000300",
    "中盘·中证500": "s_sh000905",
    "小盘·中证1000": "s_sh000852",
    "价值·国证价值": "s_sz399371",
    "成长·国证成长": "s_sz399370",
    "成长·创业板": "s_sz399006",
}

MINUTE_INDEX_OPTIONS = {
    "上证指数": "000001",
    "深证成指": "399001",
    "创业板指": "399006",
    "沪深300": "000300",
    "中证500": "000905",
    "科创50": "000688",
}


def now_cn() -> datetime:
    return datetime.now(_CN_TZ)


def is_cn_trading_session(dt: Optional[datetime] = None) -> bool:
    """开市自动刷新窗口：工作日 09:15–11:30、13:00–15:00。"""
    t = dt or now_cn()
    if t.weekday() >= 5:
        return False
    minutes = t.hour * 60 + t.minute
    return (9 * 60 + 15 <= minutes <= 11 * 60 + 30) or (13 * 60 <= minutes <= 15 * 60)


def market_session_label() -> str:
    t = now_cn()
    if t.weekday() >= 5:
        return "休市（周末）"
    if is_cn_trading_session(t):
        return "交易中"
    minutes = t.hour * 60 + t.minute
    if minutes < 9 * 60 + 15:
        return "未开盘"
    if 11 * 60 + 30 < minutes < 13 * 60:
        return "午间休市"
    return "已收盘"


# ── helpers ──────────────────────────────────────────────

def _sina_index_amount_yi(sina_code: str) -> Optional[float]:
    """新浪综合指数成交额字段单位为万元 → 亿元。"""
    text = sina_get(f"https://hq.sinajs.cn/list={sina_code}")
    if not text:
        return None
    m = re.search(rf'var hq_str_{re.escape(sina_code)}="([^"]*)"', text)
    if not m:
        return None
    parts = m.group(1).split(",")
    if len(parts) < 6:
        return None
    wan = safe_float(parts[5])
    if wan <= 0:
        return None
    return round(wan / 10000.0, 2)


def _tx_index_amount_hist(symbol: str, days: int = 15) -> pd.DataFrame:
    """
    腾讯证券日 K：成交额（万元）。

    云主机上东财 push2his 常被直接断开；腾讯接口稳定，字段与新浪综合指数成交额一致。
    """
    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    params = {
        "_var": "kline_dayqfq",
        "param": f"{symbol},day,,,{int(days)},qfq",
        "r": "0.1",
    }
    r = requests.get(
        url,
        params=params,
        timeout=15,
        proxies=_NO_PROXY,
        headers={
            "User-Agent": _UA["User-Agent"],
            "Referer": "https://gu.qq.com/",
        },
    )
    r.raise_for_status()
    m = re.search(r"=(\{.*\})\s*$", r.text.strip(), re.S)
    if not m:
        raise ValueError(f"腾讯K线响应无法解析: {symbol}")
    payload = json.loads(m.group(1))
    rows = (payload.get("data") or {}).get(symbol) or {}
    day = rows.get("day") or rows.get("qfqday") or []
    out = []
    for row in day:
        if not row or len(row) < 9:
            continue
        wan = safe_float(row[8])
        if wan <= 0:
            continue
        out.append({"日期": str(row[0])[:10], "成交额": wan})
    return pd.DataFrame(out)


def _parse_activity_legu(df: pd.DataFrame) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if df is None or df.empty:
        return out
    mapping = {
        "上涨": "up",
        "下跌": "down",
        "平盘": "flat",
        "涨停": "limit_up",
        "跌停": "limit_down",
        "真实涨停": "limit_up_real",
        "真实跌停": "limit_down_real",
        "活跃度": "activity",
        "统计日期": "asof",
    }
    for _, row in df.iterrows():
        item = str(row.get("item", "")).strip()
        key = mapping.get(item)
        if not key:
            continue
        val = row.get("value")
        if key == "asof" or key == "activity":
            out[key] = str(val)
        else:
            out[key] = int(safe_float(val))
    return out


def _today_str() -> str:
    return now_cn().strftime("%Y%m%d")


def fetch_breadth() -> Dict[str, Any]:
    import akshare as ak

    day = _today_str()
    activity = {}
    df_act = ak.stock_market_activity_legu()
    activity = _parse_activity_legu(df_act)

    zt = ak.stock_zt_pool_em(date=day)
    dt = ak.stock_zt_pool_dtgc_em(date=day)
    zb = ak.stock_zt_pool_zbgc_em(date=day)

    max_board = 0
    board_leaders: List[dict] = []
    if zt is not None and not zt.empty and "连板数" in zt.columns:
        zt2 = zt.copy()
        zt2["连板数"] = pd.to_numeric(zt2["连板数"], errors="coerce").fillna(0).astype(int)
        max_board = int(zt2["连板数"].max())
        top = zt2.sort_values(["连板数", "封板资金"], ascending=False).head(5)
        for _, r in top.iterrows():
            board_leaders.append({
                "code": str(r.get("代码", "")),
                "name": str(r.get("名称", "")),
                "lianban": int(r.get("连板数") or 0),
                "industry": str(r.get("所属行业", "")),
            })

    return {
        "activity": activity,
        "limit_up_n": int(len(zt)) if zt is not None else int(activity.get("limit_up") or 0),
        "limit_down_n": int(len(dt)) if dt is not None else int(activity.get("limit_down") or 0),
        "zhaban_n": int(len(zb)) if zb is not None else 0,
        "max_lianban": max_board,
        "lianban_leaders": board_leaders,
        "asof": activity.get("asof") or now_cn().strftime("%Y-%m-%d %H:%M:%S"),
    }


def fetch_turnover() -> Dict[str, Any]:
    sh_live = _sina_index_amount_yi("s_sh000001")
    sz_live = _sina_index_amount_yi("s_sz399001")
    total_live = None
    if sh_live is not None and sz_live is not None:
        total_live = round(sh_live + sz_live, 2)

    sh = _tx_index_amount_hist("sh000001", days=15)
    sz = _tx_index_amount_hist("sz399001", days=15)
    sh["成交额"] = pd.to_numeric(sh["成交额"], errors="coerce")
    sz["成交额"] = pd.to_numeric(sz["成交额"], errors="coerce")
    merged = pd.merge(
        sh[["日期", "成交额"]].rename(columns={"成交额": "sh"}),
        sz[["日期", "成交额"]].rename(columns={"成交额": "sz"}),
        on="日期",
        how="inner",
    )
    # 腾讯/新浪均为万元 → 亿元
    merged["total_yi"] = (merged["sh"] + merged["sz"]) / 10000.0
    merged = merged.sort_values("日期")
    hist = merged.tail(6).copy()
    today_label = now_cn().strftime("%Y-%m-%d")
    if total_live is not None and not hist.empty:
        last_date = str(hist.iloc[-1]["日期"])[:10]
        if last_date == today_label:
            hist.loc[hist.index[-1], "total_yi"] = total_live
        else:
            hist = pd.concat(
                [hist, pd.DataFrame([{"日期": today_label, "total_yi": total_live}])],
                ignore_index=True,
            )

    series = [
        {"date": str(r["日期"])[:10], "total_yi": round(float(r["total_yi"]), 2)}
        for _, r in hist.iterrows()
    ]
    today_yi = series[-1]["total_yi"] if series else total_live
    prev_yi = series[-2]["total_yi"] if len(series) >= 2 else None
    avg5 = None
    if len(series) >= 6:
        avg5 = round(sum(x["total_yi"] for x in series[-6:-1]) / 5, 2)
    elif len(series) >= 2:
        avg5 = round(sum(x["total_yi"] for x in series[:-1]) / max(len(series) - 1, 1), 2)

    vs_yday = None
    vs_avg5 = None
    if today_yi is not None and prev_yi:
        vs_yday = round((today_yi / prev_yi - 1) * 100, 2)
    if today_yi is not None and avg5:
        vs_avg5 = round((today_yi / avg5 - 1) * 100, 2)

    return {
        "sh_yi": sh_live,
        "sz_yi": sz_live,
        "total_yi": today_yi,
        "prev_yi": prev_yi,
        "avg5_yi": avg5,
        "vs_yesterday_pct": vs_yday,
        "vs_avg5_pct": vs_avg5,
        "series": series,
    }


def fetch_style_box() -> Dict[str, dict]:
    return get_index_quotes(STYLE_INDEX_MAP)


def fetch_cross_asset() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    bond = get_index_quotes({"国债指数": "s_sh000012"}).get("国债指数")
    if bond:
        out["bond"] = {
            "name": "国债指数",
            "price": bond["最新价"],
            "chg_pct": bond["涨跌幅"],
        }

    text = sina_get("https://hq.sinajs.cn/list=hf_GC,fx_susdcny")
    if text:
        m_g = re.search(r'var hq_str_hf_GC="([^"]*)"', text)
        if m_g:
            g = m_g.group(1).split(",")
            # 黄金格式：现价,,buy,sell,high,low,time,prev,...
            price = safe_float(g[0])
            prev = safe_float(g[7]) if len(g) > 7 else 0
            chg = ((price - prev) / prev * 100) if prev else 0.0
            out["gold"] = {"name": "COMEX黄金", "price": price, "chg_pct": round(chg, 2)}
        m_fx = re.search(r'var hq_str_fx_susdcny="([^"]*)"', text)
        if m_fx:
            f = m_fx.group(1).split(",")
            # time, bid, ask, ..., 昨收指数类字段附近有涨跌幅
            price = safe_float(f[1])
            chg = safe_float(f[11]) if len(f) > 11 else 0.0  # 涨跌幅%
            out["usdcny"] = {"name": "美元/人民币", "price": price, "chg_pct": round(chg, 4)}
    return out


def fetch_north_south() -> Dict[str, Any]:
    import akshare as ak

    summary = ak.stock_hsgt_fund_flow_summary_em()
    north_net = 0.0
    south_net = 0.0
    rows = []
    if summary is not None and not summary.empty:
        for _, r in summary.iterrows():
            direction = str(r.get("资金方向", ""))
            # 成交净买额单位：亿元（接口样本中为小幅数字；资金净流入另有字段）
            net = safe_float(r.get("成交净买额"))
            inflow = safe_float(r.get("资金净流入"))
            use = net if abs(net) > 1e-9 else inflow
            rows.append({
                "板块": str(r.get("板块", "")),
                "方向": direction,
                "净买额(亿)": round(use, 2),
                "上涨数": int(safe_float(r.get("上涨数"))),
                "下跌数": int(safe_float(r.get("下跌数"))),
            })
            if direction == "北向":
                north_net += use
            elif direction == "南向":
                south_net += use

    north_min = ak.stock_hsgt_fund_min_em(symbol="北向资金")
    south_min = ak.stock_hsgt_fund_min_em(symbol="南向资金")

    def _clean_min(df: pd.DataFrame, col: str) -> List[dict]:
        if df is None or df.empty or col not in df.columns:
            return []
        d = df[["时间", col]].copy()
        d[col] = pd.to_numeric(d[col], errors="coerce")
        d = d.dropna(subset=[col])
        return [{"time": str(r["时间"]), "value": float(r[col])} for _, r in d.iterrows()]

    north_series = _clean_min(north_min, "北向资金")
    south_series = _clean_min(south_min, "南向资金")
    # 分时末值往往比 summary 盘中更可信
    if north_series:
        north_net = north_series[-1]["value"]
    if south_series:
        south_net = south_series[-1]["value"]

    return {
        "north_net_yi": round(float(north_net), 2),
        "south_net_yi": round(float(south_net), 2),
        "rows": rows,
        "north_series": north_series,
        "south_series": south_series,
    }


def fetch_pe_percentile() -> List[dict]:
    from .data_fetcher import get_fetcher

    fetcher = get_fetcher()
    out = []
    for name in ("沪深300", "中证500", "创业板指"):
        val = fetcher.get_index_valuation(name) or {}
        out.append({
            "name": name,
            "pe": val.get("PE"),
            "pe_pct": val.get("PE百分位"),
            "pb": val.get("PB"),
            "pb_pct": val.get("PB百分位"),
            "date": val.get("数据日期") or "",
        })
    return out


def fetch_board_changes(
    kind: str = "industry",
    top_n: int = 15,
    *,
    full: bool = False,
) -> pd.DataFrame:
    """kind: industry | concept。full=True 返回全量，否则涨跌各 top_n。

    数据源：新浪 `stock_sector_spot`（云上东财板块接口会主动断连）。
    """
    import akshare as ak

    indicator = "概念" if kind == "concept" else "行业"
    df = ak.stock_sector_spot(indicator=indicator)
    if df is None or df.empty or "板块" not in df.columns:
        return pd.DataFrame(columns=["name", "change_pct", "up", "down"])
    chg = pd.to_numeric(df["涨跌幅"], errors="coerce")
    out = pd.DataFrame({
        "name": df["板块"].astype(str),
        "change_pct": chg,
        "up": 0,
        "down": 0,
    }).dropna(subset=["change_pct"])
    if full:
        return out.sort_values("change_pct", ascending=False).reset_index(drop=True)
    top = out.nlargest(top_n, "change_pct")
    bot = out.nsmallest(top_n, "change_pct")
    return pd.concat([top, bot]).drop_duplicates("name")


def _index_to_tx_code(symbol: str) -> str:
    s = str(symbol).strip().lower()
    if s.startswith(("sh", "sz")):
        return s
    s = s.zfill(6)
    if s.startswith("399"):
        return f"sz{s}"
    return f"sh{s}"


def fetch_index_minute(symbol: str) -> pd.DataFrame:
    """指数分时：腾讯 minute/query（避开东财 push2his）。"""
    code = _index_to_tx_code(symbol)
    url = "https://web.ifzq.gtimg.cn/appstock/app/minute/query"
    r = requests.get(
        url,
        params={"code": code},
        timeout=15,
        proxies=_NO_PROXY,
        headers={"User-Agent": _UA["User-Agent"], "Referer": "https://gu.qq.com/"},
    )
    r.raise_for_status()
    payload = r.json()
    rows = (((payload.get("data") or {}).get(code) or {}).get("data") or {}).get("data") or []
    parsed = []
    for row in rows:
        parts = str(row).split()
        if len(parts) < 2:
            continue
        hhmm = parts[0]
        price = safe_float(parts[1])
        if price <= 0 or len(hhmm) < 4:
            continue
        parsed.append({
            "时间": f"{hhmm[:2]}:{hhmm[2:4]}",
            "收盘": price,
        })
    out = pd.DataFrame(parsed)
    if out.empty:
        return out
    base = float(out.iloc[0]["收盘"])
    out["涨跌幅%"] = (out["收盘"] / base - 1.0) * 100 if base else 0.0
    return out


def _stock_industry(code: str) -> str:
    """个股所属行业：巨潮资讯（与新浪行业板块命名一致）。"""
    import akshare as ak

    code = str(code).zfill(6)
    try:
        df = ak.stock_profile_cninfo(symbol=code)
    except Exception:
        return ""
    if df is None or df.empty or "所属行业" not in df.columns:
        return ""
    return str(df.iloc[0].get("所属行业") or "").strip()


def _norm_industry(name: str) -> str:
    return re.sub(r"[ⅠⅡⅢIVX一二三四五级类]$", "", name or "").replace("Ⅱ", "").replace("Ⅰ", "").strip()


def fetch_portfolio_sector_pulse(max_funds: int = 4, top_stocks: int = 5) -> Dict[str, Any]:
    """持仓重仓股所属行业 → 对照新浪行业板块当日涨跌。"""
    from .portfolio import get_portfolio_manager
    from .data_fetcher import get_fetcher

    pm = get_portfolio_manager()
    portfolios = pm.list_all()
    best = None
    best_df = None
    for p in portfolios:
        df = pm.get_holdings_df(p.id)
        if df is None or df.empty:
            continue
        if best is None or len(df) > len(best_df):
            best, best_df = p, df
    if best is None:
        return {"ok": False, "reason": "empty"}

    rows = best_df.to_dict("records")
    w_sum = sum(safe_float(h.get("weight")) for h in rows)
    if w_sum <= 0:
        w_sum = sum(safe_float(h.get("amount")) for h in rows) or len(rows)
        for h in rows:
            h["_w"] = safe_float(h.get("amount")) / w_sum if w_sum else 0
    else:
        for h in rows:
            h["_w"] = safe_float(h.get("weight")) / w_sum
    rows = sorted(rows, key=lambda h: h["_w"], reverse=True)[:max_funds]

    fetcher = get_fetcher()
    exposure: Dict[str, float] = {}
    for h in rows:
        code = str(h.get("fund_code", "")).zfill(6)
        hold = fetcher.get_fund_holdings(code)
        if hold is None or hold.empty:
            continue
        # 标准化列
        code_col = "股票代码" if "股票代码" in hold.columns else hold.columns[0]
        w_col = "占净值比例" if "占净值比例" in hold.columns else None
        sub = hold.head(top_stocks)
        for _, s in sub.iterrows():
            sc = str(s.get(code_col, "")).zfill(6)
            if not sc.isdigit():
                continue
            sw = safe_float(s.get(w_col)) / 100.0 if w_col else (1.0 / len(sub))
            ind = _stock_industry(sc)
            if not ind:
                continue
            key = _norm_industry(ind) or ind
            exposure[key] = exposure.get(key, 0.0) + h["_w"] * sw

    if not exposure:
        return {"ok": False, "reason": "no_industry", "portfolio_name": best.name}

    board = fetch_board_changes("industry", full=True)
    # 建立行业名 → 涨跌映射（规范化匹配）
    chg_map: Dict[str, float] = {}
    for _, r in board.iterrows():
        chg_map[_norm_industry(r["name"])] = float(r["change_pct"])
        chg_map[str(r["name"])] = float(r["change_pct"])

    items = []
    for ind, w in sorted(exposure.items(), key=lambda x: -x[1])[:8]:
        pct = None
        if ind in chg_map:
            pct = chg_map[ind]
        else:
            for k, v in chg_map.items():
                if ind in k or k in ind:
                    pct = v
                    break
        items.append({
            "industry": ind,
            "weight_pct": round(w * 100, 2),
            "change_pct": None if pct is None else round(pct, 2),
        })

    return {
        "ok": True,
        "portfolio_name": best.name,
        "items": items,
    }


def fetch_dashboard_bundle(include_heavy: bool = True) -> Dict[str, Any]:
    """并行拉取仪表盘核心块。"""
    result: Dict[str, Any] = {
        "updated_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
        "session": market_session_label(),
        "trading": is_cn_trading_session(),
    }

    jobs = {
        "indexes": lambda: get_index_quotes(MAIN_INDEX_MAP),
        "breadth": fetch_breadth,
        "turnover": fetch_turnover,
        "style": fetch_style_box,
        "cross": fetch_cross_asset,
        "north_south": fetch_north_south,
        "pe": fetch_pe_percentile,
        "industry": lambda: fetch_board_changes("industry"),
        "concept": lambda: fetch_board_changes("concept"),
    }
    if include_heavy:
        jobs["portfolio_sectors"] = fetch_portfolio_sector_pulse

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(fn): key for key, fn in jobs.items()}
        for fut in as_completed(futs):
            key = futs[fut]
            try:
                result[key] = fut.result()
            except Exception as e:
                result[key] = {"_error": f"{type(e).__name__}: {e}"}

    return result
