"""
盘中估值引擎 — 重仓穿透 + ETF 联接追踪
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .data_fetcher import get_fetcher
from .etf_linkage_map import is_link_fund, resolve_underlying_etf
from .quote_provider import get_realtime_quotes
from .utils import safe_float

SNAPSHOT_DIR = Path(__file__).parent.parent / "data" / "intraday_snapshots"


@dataclass
class HoldingContribution:
    code: str
    name: str
    weight_pct: float
    change_pct: float
    contribution_pct: float


@dataclass
class IntradayNavResult:
    fund_code: str
    fund_name: str
    mode: str  # holdings_penetration | etf_linkage | official_fallback
    base_nav: float
    estimated_nav: float
    estimated_pct: float
    confidence: str  # high | medium | low
    updated_at: str
    official_estimate: Optional[Dict[str, Any]] = None
    underlying_etf: Optional[str] = None
    contributions: List[HoldingContribution] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "mode": self.mode,
            "base_nav": self.base_nav,
            "estimated_nav": self.estimated_nav,
            "estimated_pct": self.estimated_pct,
            "confidence": self.confidence,
            "updated_at": self.updated_at,
            "official_estimate": self.official_estimate,
            "underlying_etf": self.underlying_etf,
            "contributions": [
                {
                    "code": c.code,
                    "name": c.name,
                    "weight_pct": c.weight_pct,
                    "change_pct": c.change_pct,
                    "contribution_pct": c.contribution_pct,
                }
                for c in self.contributions
            ],
            "note": self.note,
        }


class IntradayNavEngine:
    """基金盘中估值计算。"""

    def __init__(self):
        self.fetcher = get_fetcher()

    def estimate(self, fund_code: str) -> IntradayNavResult:
        code = str(fund_code).strip().zfill(6)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        official = self.fetcher.get_realtime_estimate(code)
        info = self.fetcher.get_fund_manager_info(code) or {}
        fund_name = info.get("基金名称", official.get("基金名称", "") if official else "")

        base_nav = 0.0
        if official:
            base_nav = safe_float(official.get("上一日净值", 0))
        if base_nav <= 0:
            nav = self.fetcher.get_fund_nav_history(code, years=1)
            if nav is not None and not nav.empty and "单位净值" in nav.columns:
                base_nav = safe_float(nav.sort_values("日期")["单位净值"].iloc[-1])

        if base_nav <= 0:
            return IntradayNavResult(
                fund_code=code,
                fund_name=fund_name,
                mode="official_fallback",
                base_nav=0,
                estimated_nav=0,
                estimated_pct=0,
                confidence="low",
                updated_at=now,
                official_estimate=official,
                note="无法获取基准净值",
            )

        # ETF 联接优先
        if is_link_fund(fund_name):
            linked = resolve_underlying_etf(code, fund_name)
            if linked:
                etf_code, etf_name, reason = linked
                quotes = get_realtime_quotes([etf_code])
                q = quotes.get(etf_code)
                if q:
                    pct = q["change_pct"]
                    est_nav = base_nav * (1 + pct / 100)
                    return IntradayNavResult(
                        fund_code=code,
                        fund_name=fund_name,
                        mode="etf_linkage",
                        base_nav=base_nav,
                        estimated_nav=round(est_nav, 4),
                        estimated_pct=round(pct, 2),
                        confidence="high",
                        updated_at=now,
                        official_estimate=official,
                        underlying_etf=f"{etf_name}({etf_code})",
                        contributions=[
                            HoldingContribution(
                                code=etf_code,
                                name=etf_name,
                                weight_pct=100.0,
                                change_pct=round(pct, 2),
                                contribution_pct=round(pct, 2),
                            )
                        ],
                        note=f"ETF联接穿透 · {reason}",
                    )

        # 重仓股穿透
        holdings = self.fetcher.get_fund_holdings(code)
        if holdings is not None and not holdings.empty:
            result = self._estimate_from_holdings(
                code, fund_name, base_nav, holdings, official, now
            )
            if result:
                return result

        # 回退官方估算
        if official:
            est_nav = safe_float(official.get("估算净值", 0))
            pct = safe_float(official.get("估算涨幅%", 0))
            return IntradayNavResult(
                fund_code=code,
                fund_name=fund_name,
                mode="official_fallback",
                base_nav=base_nav,
                estimated_nav=est_nav or base_nav,
                estimated_pct=pct,
                confidence="medium",
                updated_at=now,
                official_estimate=official,
                note="使用天天基金官方盘中估算",
            )

        return IntradayNavResult(
            fund_code=code,
            fund_name=fund_name,
            mode="official_fallback",
            base_nav=base_nav,
            estimated_nav=base_nav,
            estimated_pct=0,
            confidence="low",
            updated_at=now,
            note="无持仓数据且无官方估算",
        )

    def _estimate_from_holdings(
        self,
        code: str,
        fund_name: str,
        base_nav: float,
        holdings: pd.DataFrame,
        official: Optional[dict],
        now: str,
    ) -> Optional[IntradayNavResult]:
        weight_col = None
        for c in ("占净值比例%", "占净值比例"):
            if c in holdings.columns:
                weight_col = c
                break
        if not weight_col:
            return None

        code_col = "股票代码" if "股票代码" in holdings.columns else None
        name_col = "股票名称" if "股票名称" in holdings.columns else None
        if not code_col:
            return None

        rows = []
        for _, row in holdings.iterrows():
            w = safe_float(row.get(weight_col, 0))
            if w <= 0:
                continue
            # AKShare 有时返回 0-1 有时 0-100
            if w <= 1:
                w *= 100
            sc = str(row.get(code_col, "")).strip()
            if not sc or sc == "nan":
                continue
            sc = sc.zfill(6) if sc.isdigit() else sc
            rows.append({
                "code": sc,
                "name": str(row.get(name_col, sc)) if name_col else sc,
                "weight": w,
            })

        if not rows:
            return None

        total_weight = sum(r["weight"] for r in rows)
        if total_weight < 30:
            return None

        stock_codes = [r["code"] for r in rows]
        quotes = get_realtime_quotes(stock_codes)

        contributions: List[HoldingContribution] = []
        weighted_chg = 0.0
        covered_weight = 0.0

        for r in rows:
            q = quotes.get(r["code"])
            if not q:
                continue
            w_norm = r["weight"] / total_weight
            chg = q["change_pct"]
            contrib = w_norm * chg
            weighted_chg += contrib
            covered_weight += r["weight"]
            contributions.append(
                HoldingContribution(
                    code=r["code"],
                    name=q.get("name") or r["name"],
                    weight_pct=round(r["weight"], 2),
                    change_pct=round(chg, 2),
                    contribution_pct=round(contrib, 3),
                )
            )

        if not contributions:
            return None

        coverage = covered_weight / total_weight if total_weight else 0
        confidence = "high" if coverage >= 0.7 else ("medium" if coverage >= 0.4 else "low")
        est_pct = weighted_chg
        est_nav = base_nav * (1 + est_pct / 100)

        note = f"重仓穿透 · 覆盖权重 {covered_weight:.1f}% / 披露 {total_weight:.1f}%"
        if official:
            off_pct = safe_float(official.get("估算涨幅%", 0))
            note += f" · 官方估算 {off_pct:+.2f}%"

        return IntradayNavResult(
            fund_code=code,
            fund_name=fund_name,
            mode="holdings_penetration",
            base_nav=base_nav,
            estimated_nav=round(est_nav, 4),
            estimated_pct=round(est_pct, 2),
            confidence=confidence,
            updated_at=now,
            official_estimate=official,
            contributions=sorted(contributions, key=lambda x: -abs(x.contribution_pct)),
            note=note,
        )


_engine: Optional[IntradayNavEngine] = None


def save_intraday_snapshot(result: IntradayNavResult) -> None:
    """将一次估值结果落盘为分钟级快照 CSV：data/intraday_snapshots/{code}/{date}.csv。"""
    if result.base_nav <= 0:
        return
    day = result.updated_at[:10]
    code_dir = SNAPSHOT_DIR / result.fund_code
    code_dir.mkdir(parents=True, exist_ok=True)
    fpath = code_dir / f"{day}.csv"
    is_new = not fpath.exists()
    with fpath.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["time", "estimated_nav", "estimated_pct", "mode", "confidence"])
        writer.writerow([
            result.updated_at,
            result.estimated_nav,
            result.estimated_pct,
            result.mode,
            result.confidence,
        ])


def load_intraday_snapshots(fund_code: str, day: Optional[str] = None) -> pd.DataFrame:
    """读取某基金某日的分时快照。day 默认今日。"""
    code = str(fund_code).strip().zfill(6)
    day = day or datetime.now().strftime("%Y-%m-%d")
    fpath = SNAPSHOT_DIR / code / f"{day}.csv"
    if not fpath.exists():
        return pd.DataFrame(columns=["time", "estimated_nav", "estimated_pct", "mode", "confidence"])
    df = pd.read_csv(fpath)
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"]).sort_values("time")
    return df


def get_intraday_engine() -> IntradayNavEngine:
    global _engine
    if _engine is None:
        _engine = IntradayNavEngine()
    return _engine
