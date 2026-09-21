"""
主题资金流引擎 — 板块主力净流入 + 主题归并聚合
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .data_fetcher import AKSHARE_AVAILABLE, _http_get
from .theme_taxonomy import map_sector_to_theme
from .utils import safe_float

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com",
}
SNAPSHOT_DIR = Path(__file__).parent.parent / "data" / "theme_flow_snapshots"


@dataclass
class SectorFlowRow:
    code: str
    name: str
    change_pct: float
    net_inflow_yi: float  # 主力净流入（亿元）
    board_type: str  # industry | concept


@dataclass
class ThemeFlowRow:
    theme: str
    net_inflow_yi: float
    change_pct: float
    sector_count: int
    top_sector: str = ""
    sectors: List[str] = field(default_factory=list)


@contextlib.contextmanager
def _no_proxy_env():
    """AKShare/东财在系统代理下常失败，请求前临时禁用代理环境变量。"""
    saved = {k: os.environ.pop(k) for k in list(os.environ) if "proxy" in k.lower()}
    os.environ["NO_PROXY"] = "*"
    try:
        yield
    finally:
        os.environ.pop("NO_PROXY", None)
        os.environ.update(saved)


def _normalize_clist_diff(data: dict) -> list:
    raw = (data or {}).get("data", {}).get("diff")
    if raw is None:
        return []
    if isinstance(raw, dict):
        return list(raw.values())
    return list(raw)


def _rows_from_akshare_df(df: pd.DataFrame, board_type: str) -> List[SectorFlowRow]:
    rows: List[SectorFlowRow] = []
    if df is None or df.empty:
        return rows
    name_col = "行业" if "行业" in df.columns else df.columns[1]
    chg_col = "行业-涨跌幅" if "行业-涨跌幅" in df.columns else None
    net_col = "净额" if "净额" in df.columns else None
    for i, row in df.iterrows():
        name = str(row.get(name_col, "")).strip()
        if not name:
            continue
        rows.append(SectorFlowRow(
            code=str(row.get("序号", i + 1)),
            name=name,
            change_pct=safe_float(row.get(chg_col)) if chg_col else 0.0,
            net_inflow_yi=safe_float(row.get(net_col)) if net_col else 0.0,
            board_type=board_type,
        ))
    return rows


def _fetch_via_akshare(board_type: str) -> List[SectorFlowRow]:
    if not AKSHARE_AVAILABLE:
        return []
    import akshare as ak

    try:
        with _no_proxy_env():
            if board_type == "industry":
                df = ak.stock_fund_flow_industry(symbol="即时")
            else:
                df = ak.stock_fund_flow_concept(symbol="即时")
    except Exception:
        return []
    return _rows_from_akshare_df(df, board_type)


def _fetch_via_eastmoney(board_type: str, page_size: int = 80) -> List[SectorFlowRow]:
    import requests

    fs = "m:90+t:2" if board_type == "industry" else "m:90+t:3"
    params = {
        "pn": "1",
        "pz": str(page_size),
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f62",
        "fs": fs,
        "fields": "f2,f3,f12,f14,f62",
    }
    diff: list = []
    with _no_proxy_env():
        for proxies in ({"http": None, "https": None}, None):
            try:
                r = requests.get(
                    CLIST_URL,
                    params=params,
                    headers=EM_HEADERS,
                    timeout=12,
                    proxies=proxies,
                )
                if r.status_code != 200:
                    continue
                diff = _normalize_clist_diff(r.json())
                if diff:
                    break
            except Exception:
                continue
        if not diff:
            text = _http_get(CLIST_URL, params=params, headers=EM_HEADERS, bypass_proxy=True)
            if text:
                try:
                    diff = _normalize_clist_diff(json.loads(text))
                except (json.JSONDecodeError, AttributeError):
                    diff = []

    rows: List[SectorFlowRow] = []
    for item in diff:
        if not isinstance(item, dict):
            continue
        name = str(item.get("f14", "")).strip()
        if not name:
            continue
        rows.append(SectorFlowRow(
            code=str(item.get("f12", "")),
            name=name,
            change_pct=safe_float(item.get("f3")),
            net_inflow_yi=safe_float(item.get("f62")) / 1e8,
            board_type=board_type,
        ))
    return rows


def _fetch_board_list(board_type: str, page_size: int = 80) -> List[SectorFlowRow]:
    rows = _fetch_via_akshare(board_type)
    if rows:
        return rows
    return _fetch_via_eastmoney(board_type, page_size)


def fetch_all_sector_flows() -> List[SectorFlowRow]:
    industry = _fetch_board_list("industry", 60)
    concept = _fetch_board_list("concept", 80)
    seen = set()
    merged: List[SectorFlowRow] = []
    for row in industry + concept:
        if row.name in seen:
            continue
        seen.add(row.name)
        merged.append(row)
    return merged


def aggregate_theme_flows(sectors: Optional[List[SectorFlowRow]] = None) -> List[ThemeFlowRow]:
    sectors = sectors if sectors is not None else fetch_all_sector_flows()
    buckets: Dict[str, dict] = {}

    for s in sectors:
        theme = map_sector_to_theme(s.name) or "其他"
        if theme not in buckets:
            buckets[theme] = {
                "net_inflow_yi": 0.0,
                "change_sum": 0.0,
                "count": 0,
                "sectors": [],
                "top_sector": "",
                "top_inflow": -1e18,
            }
        b = buckets[theme]
        b["net_inflow_yi"] += s.net_inflow_yi
        b["change_sum"] += s.change_pct
        b["count"] += 1
        b["sectors"].append(s.name)
        if s.net_inflow_yi > b["top_inflow"]:
            b["top_inflow"] = s.net_inflow_yi
            b["top_sector"] = s.name

    result: List[ThemeFlowRow] = []
    for theme, b in buckets.items():
        cnt = max(b["count"], 1)
        result.append(ThemeFlowRow(
            theme=theme,
            net_inflow_yi=round(b["net_inflow_yi"], 2),
            change_pct=round(b["change_sum"] / cnt, 2),
            sector_count=cnt,
            top_sector=b["top_sector"],
            sectors=b["sectors"][:8],
        ))
    result.sort(key=lambda x: x.net_inflow_yi, reverse=True)
    return result


def save_snapshot(themes: List[ThemeFlowRow]) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M:%S")
    path = SNAPSHOT_DIR / f"{today}.csv"
    rows = [{
        "date": today,
        "time": now,
        "theme": t.theme,
        "net_inflow_yi": t.net_inflow_yi,
        "change_pct": t.change_pct,
        "sector_count": t.sector_count,
    } for t in themes]
    df_new = pd.DataFrame(rows)
    if path.exists():
        df_old = pd.read_csv(path)
        df = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df = df_new
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def load_theme_trend(theme: str, days: int = 10) -> pd.DataFrame:
    if not SNAPSHOT_DIR.exists():
        return pd.DataFrame()
    files = sorted(SNAPSHOT_DIR.glob("*.csv"), reverse=True)[:days]
    parts = []
    for f in files:
        try:
            df = pd.read_csv(f)
            sub = df[df["theme"] == theme].copy()
            if not sub.empty:
                parts.append(sub)
        except Exception:
            continue
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    if "date" in out.columns and "time" in out.columns:
        out["datetime"] = out["date"].astype(str) + " " + out["time"].astype(str)
    return out.sort_values(["date", "time"] if "time" in out.columns else ["date"])


def load_latest_theme_snapshot() -> List[dict]:
    """
    读取最近一日快照中「最后一次刷新」的主题列表（按主力净流入降序）。
    不触发网络拉取，供工作台市场条使用。
    """
    if not SNAPSHOT_DIR.exists():
        return []
    files = sorted(SNAPSHOT_DIR.glob("*.csv"), reverse=True)
    if not files:
        return []
    df = pd.read_csv(files[0])
    if df is None or df.empty or "theme" not in df.columns:
        return []
    if "time" in df.columns:
        latest_time = str(df["time"].astype(str).iloc[-1])
        slice_df = df[df["time"].astype(str) == latest_time].copy()
    else:
        slice_df = df.copy()
        latest_time = ""
    if slice_df.empty:
        return []
    # 同一时刻可能重复行：按主题保留最后一条
    slice_df = slice_df.drop_duplicates(subset=["theme"], keep="last")
    slice_df["net_inflow_yi"] = pd.to_numeric(slice_df.get("net_inflow_yi"), errors="coerce").fillna(0)
    slice_df = slice_df.sort_values("net_inflow_yi", ascending=False)
    asof_date = str(slice_df["date"].iloc[0]) if "date" in slice_df.columns else files[0].stem
    asof = f"{asof_date} {latest_time}".strip()
    out: List[dict] = []
    for _, row in slice_df.iterrows():
        out.append({
            "theme": str(row.get("theme", "")),
            "net_inflow_yi": round(float(row.get("net_inflow_yi") or 0), 2),
            "change_pct": round(safe_float(row.get("change_pct")), 2),
            "asof": asof,
        })
    return out


def sectors_to_dataframe(sectors: List[SectorFlowRow]) -> pd.DataFrame:
    cols = ["板块代码", "板块名称", "涨跌幅%", "主力净流入(亿)", "类型", "映射主题"]
    if not sectors:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([{
        "板块代码": s.code,
        "板块名称": s.name,
        "涨跌幅%": s.change_pct,
        "主力净流入(亿)": round(s.net_inflow_yi, 2),
        "类型": "行业" if s.board_type == "industry" else "概念",
        "映射主题": map_sector_to_theme(s.name) or "其他",
    } for s in sectors])


def themes_to_dataframe(themes: List[ThemeFlowRow]) -> pd.DataFrame:
    cols = ["主题", "主力净流入(亿)", "平均涨跌幅%", "覆盖板块数", "代表板块"]
    if not themes:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([{
        "主题": t.theme,
        "主力净流入(亿)": t.net_inflow_yi,
        "平均涨跌幅%": t.change_pct,
        "覆盖板块数": t.sector_count,
        "代表板块": t.top_sector,
    } for t in themes])


RANK_CACHE_FILE = Path(__file__).parent.parent / "data" / "theme_flow_rank_cache.json"


def save_theme_rank_snapshot(themes: List[ThemeFlowRow]) -> None:
    """保存主题资金排名快照（供排名跃升预警对比）。"""
    ranks = {t.theme: i + 1 for i, t in enumerate(themes)}
    payload = {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "ranks": ranks}
    RANK_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RANK_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_theme_rank_snapshot() -> dict:
    if not RANK_CACHE_FILE.exists():
        return {}
    try:
        with open(RANK_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def detect_theme_rank_jumps(
    themes: List[ThemeFlowRow],
    rank_jump: int = 5,
    watch_themes: Optional[List[str]] = None,
) -> List[dict]:
    """
    对比上次排名，检测跃升/骤降。
    watch_themes 为空则监控全部主题。
    """
    prev = load_theme_rank_snapshot().get("ranks", {})
    current = {t.theme: i + 1 for i, t in enumerate(themes)}
    alerts: List[dict] = []

    for theme, rank in current.items():
        if watch_themes and theme not in watch_themes:
            continue
        if theme not in prev:
            continue
        delta = prev[theme] - rank
        if abs(delta) >= rank_jump:
            alerts.append({
                "theme": theme,
                "prev_rank": prev[theme],
                "curr_rank": rank,
                "delta": delta,
                "net_inflow_yi": next((t.net_inflow_yi for t in themes if t.theme == theme), 0),
            })

    if themes:
        save_theme_rank_snapshot(themes)
    return alerts


_theme_engine = None


class ThemeFlowEngine:
    def fetch(self, *, save: bool = True) -> dict:
        prev_ranks = load_theme_rank_snapshot().get("ranks") or {}
        sectors = fetch_all_sector_flows()
        themes = aggregate_theme_flows(sectors)
        from .theme_radar_insights import compute_rank_moves
        rank_moves = compute_rank_moves(themes, prev_ranks=prev_ranks)
        snapshot_path = None
        if save and themes:
            snapshot_path = str(save_snapshot(themes))
            save_theme_rank_snapshot(themes)
        source = "akshare" if sectors else "none"
        return {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sectors": sectors,
            "themes": themes,
            "snapshot_path": snapshot_path,
            "fetch_ok": bool(sectors),
            "source": source,
            "rank_moves": rank_moves,
            "prev_ranks": prev_ranks,
        }


def get_theme_flow_engine() -> ThemeFlowEngine:
    global _theme_engine
    if _theme_engine is None:
        _theme_engine = ThemeFlowEngine()
    return _theme_engine
