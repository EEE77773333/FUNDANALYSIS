"""
组合赛道聚类 + 再平衡对账引擎
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from collections import defaultdict

from .data_fetcher import get_fetcher
from .holding_penetration import map_stocks_to_sectors
from .theme_taxonomy import load_taxonomy, map_sector_to_theme


BALANCE_PRESETS = {
    "松": 0.3,
    "中": 0.5,
    "紧": 0.8,
}


@dataclass
class FundTrackInfo:
    fund_code: str
    fund_name: str
    portfolio_weight: float
    primary_track: str
    track_shares: Dict[str, float] = field(default_factory=dict)
    mapping_source: str = "name"  # name | holdings | mixed


@dataclass
class TrackRow:
    track: str
    current_weight: float
    target_weight: float
    deviation: float
    fund_count: int
    representative_code: str
    representative_name: str
    theme_flow_yi: Optional[float] = None
    funds: List[str] = field(default_factory=list)


@dataclass
class RebalanceAction:
    action: str  # add | reduce | hold
    track: str
    fund_code: str
    fund_name: str
    current_weight_pct: float
    suggested_delta_pct: float
    reason: str


def themes_from_fund_name(fund_name: str) -> List[str]:
    name = (fund_name or "").strip()
    if not name:
        return []
    matched = []
    for theme, cfg in load_taxonomy().items():
        for kw in (cfg.get("keywords") or []) + (cfg.get("sectors") or []):
            if kw in name:
                matched.append(theme)
                break
    return matched


def themes_from_holdings(fund_code: str) -> Dict[str, float]:
    """基金持仓穿透 → 主题权重（归一化到 1）。"""
    fetcher = get_fetcher()
    df = fetcher.get_fund_holdings(fund_code)
    if df is None or df.empty:
        return {}
    if "股票名称" not in df.columns:
        return {}

    weight_col = "占净值比例" if "占净值比例" in df.columns else None
    if not weight_col:
        return {}

    names = df["股票名称"].dropna().astype(str).tolist()
    sector_map = map_stocks_to_sectors(names)
    theme_w: Dict[str, float] = defaultdict(float)

    for _, row in df.iterrows():
        stock = str(row.get("股票名称", "")).strip()
        if not stock:
            continue
        w = float(row.get(weight_col) or 0)
        sector = sector_map.get(stock, "其他")
        theme = map_sector_to_theme(sector) or "其他"
        theme_w[theme] += w

    total = sum(theme_w.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in theme_w.items()}


def resolve_fund_tracks(fund_code: str, fund_name: str) -> Tuple[Dict[str, float], str, str]:
    """
    解析单基金的主题归属。
    Returns: (track_shares, primary_track, mapping_source)
    """
    holding_themes = themes_from_holdings(fund_code)
    name_themes = themes_from_fund_name(fund_name)

    if holding_themes:
        if name_themes:
            merged: Dict[str, float] = defaultdict(float)
            for t, w in holding_themes.items():
                merged[t] += w * 0.7
            for t in name_themes:
                merged[t] += 0.3 / len(name_themes)
            total = sum(merged.values())
            shares = {k: v / total for k, v in merged.items()}
            primary = max(shares, key=shares.get)
            return shares, primary, "mixed"
        primary = max(holding_themes, key=holding_themes.get)
        return holding_themes, primary, "holdings"

    if name_themes:
        share = 1.0 / len(name_themes)
        shares = {t: share for t in name_themes}
        return shares, name_themes[0], "name"

    return {"其他": 1.0}, "其他", "name"


def cluster_portfolio(holdings: List[dict]) -> List[FundTrackInfo]:
    """组合持仓 → 基金级赛道映射。"""
    result: List[FundTrackInfo] = []
    for h in holdings:
        code = str(h.get("fund_code", "")).strip().zfill(6)
        name = str(h.get("fund_name", "") or code)
        w = float(h.get("weight") or 0)
        if w > 1:
            w = w / 100.0
        shares, primary, src = resolve_fund_tracks(code, name)
        result.append(FundTrackInfo(
            fund_code=code,
            fund_name=name,
            portfolio_weight=w,
            primary_track=primary,
            track_shares=shares,
            mapping_source=src,
        ))
    return result


def aggregate_tracks(fund_infos: List[FundTrackInfo]) -> Dict[str, dict]:
    """汇总赛道当前权重与成分基金。"""
    buckets: Dict[str, dict] = {}
    for fi in fund_infos:
        for track, share in fi.track_shares.items():
            if track not in buckets:
                buckets[track] = {
                    "weight": 0.0,
                    "funds": [],
                    "fund_weights": defaultdict(float),
                }
            contrib = fi.portfolio_weight * share
            buckets[track]["weight"] += contrib
            buckets[track]["funds"].append(fi.fund_code)
            buckets[track]["fund_weights"][fi.fund_code] += contrib

    return buckets


def compute_target_weights(
    current: Dict[str, float],
    balance_strength: float,
) -> Dict[str, float]:
    """
    目标权重 = (1-α)*当前 + α*等权，α = balance_strength。
    仅对当前有暴露的赛道分配。
    """
    tracks = [t for t, w in current.items() if w > 1e-6]
    if not tracks:
        return {}
    n = len(tracks)
    equal = 1.0 / n
    alpha = max(0.0, min(1.0, balance_strength))
    targets = {}
    for t in tracks:
        cur = current.get(t, 0.0)
        targets[t] = (1 - alpha) * cur + alpha * equal
    total = sum(targets.values())
    if total <= 0:
        return targets
    return {k: v / total for k, v in targets.items()}


def _theme_flow_lookup() -> Dict[str, float]:
    try:
        from .theme_flow import aggregate_theme_flows, fetch_all_sector_flows
        themes = aggregate_theme_flows(fetch_all_sector_flows())
        return {t.theme: t.net_inflow_yi for t in themes}
    except Exception:
        return {}


def apply_flow_tilt(
    targets: Dict[str, float],
    flow_map: Dict[str, float],
    *,
    cap: float = 0.02,
) -> Dict[str, float]:
    """
    按主题资金净流入对目标权重做有界微调后重新归一。
    净流入为正的赛道最多 +cap，为负最多 -cap；无资金数据的赛道不动。
    """
    if not targets or not flow_map:
        return targets
    flows = {t: flow_map.get(t) for t in targets if flow_map.get(t) is not None}
    if not flows:
        return targets
    max_abs = max(abs(v) for v in flows.values()) or 1.0
    tilted = {}
    for t, w in targets.items():
        f = flows.get(t)
        if f is None:
            tilted[t] = w
        else:
            adj = cap * (f / max_abs)  # 归一到 [-cap, cap]
            tilted[t] = max(0.0, w + adj)
    total = sum(tilted.values())
    if total <= 0:
        return targets
    return {k: v / total for k, v in tilted.items()}


def build_track_rows(
    fund_infos: List[FundTrackInfo],
    balance_strength: float,
    *,
    include_flow: bool = True,
    flow_tilt: bool = False,
    flow_tilt_cap: float = 0.02,
) -> List[TrackRow]:
    buckets = aggregate_tracks(fund_infos)
    current = {t: b["weight"] for t, b in buckets.items()}
    targets = compute_target_weights(current, balance_strength)
    flow_map = _theme_flow_lookup() if (include_flow or flow_tilt) else {}
    if flow_tilt and flow_map:
        targets = apply_flow_tilt(targets, flow_map, cap=flow_tilt_cap)

    rows: List[TrackRow] = []
    for track, b in buckets.items():
        cur = current.get(track, 0.0)
        tgt = targets.get(track, 0.0)
        fw = b["fund_weights"]
        rep_code = max(fw, key=fw.get) if fw else ""
        rep_name = rep_code
        for fi in fund_infos:
            if fi.fund_code == rep_code:
                rep_name = fi.fund_name
                break
        rows.append(TrackRow(
            track=track,
            current_weight=round(cur, 4),
            target_weight=round(tgt, 4),
            deviation=round(cur - tgt, 4),
            fund_count=len(set(b["funds"])),
            representative_code=rep_code,
            representative_name=rep_name,
            theme_flow_yi=flow_map.get(track),
            funds=sorted(set(b["funds"])),
        ))
    rows.sort(key=lambda x: x.current_weight, reverse=True)
    return rows


def generate_rebalance_actions(
    fund_infos: List[FundTrackInfo],
    track_rows: List[TrackRow],
    threshold: float = 0.03,
) -> List[RebalanceAction]:
    """生成赛道级再平衡建议（偏离 > threshold 触发）。"""
    actions: List[RebalanceAction] = []
    fund_map = {f.fund_code: f for f in fund_infos}

    for row in track_rows:
        dev_pct = row.deviation * 100
        if abs(dev_pct) < threshold * 100:
            actions.append(RebalanceAction(
                action="hold",
                track=row.track,
                fund_code=row.representative_code,
                fund_name=row.representative_name,
                current_weight_pct=row.current_weight * 100,
                suggested_delta_pct=0.0,
                reason=f"偏离 {dev_pct:+.1f}%，在阈值内",
            ))
            continue

        if dev_pct > 0:
            action = "reduce"
            reason = f"超配 {dev_pct:+.1f}%（当前 {row.current_weight*100:.1f}% → 目标 {row.target_weight*100:.1f}%）"
        else:
            action = "add"
            reason = f"低配 {dev_pct:+.1f}%（当前 {row.current_weight*100:.1f}% → 目标 {row.target_weight*100:.1f}%）"

        for code in row.funds:
            fi = fund_map.get(code)
            if not fi:
                continue
            share = fi.track_shares.get(row.track, 0)
            if share <= 0:
                continue
            delta = -row.deviation * share * 100 if action == "reduce" else (-row.deviation) * share * 100
            actions.append(RebalanceAction(
                action=action,
                track=row.track,
                fund_code=code,
                fund_name=fi.fund_name,
                current_weight_pct=fi.portfolio_weight * 100,
                suggested_delta_pct=round(delta, 2),
                reason=reason,
            ))

    return actions


def apply_target_weights(
    portfolio_id: int,
    fund_infos: List[FundTrackInfo],
    track_rows: List[TrackRow],
) -> int:
    """
    按目标赛道权重回写组合持仓权重（按主题内当前占比拆分）。
    Returns: 更新的持仓条数。
    """
    from .portfolio import get_portfolio_manager

    target_map = {r.track: r.target_weight for r in track_rows}
    buckets = aggregate_tracks(fund_infos)
    new_weights: Dict[str, float] = defaultdict(float)

    for track, b in buckets.items():
        tgt = target_map.get(track, 0.0)
        fw = b["fund_weights"]
        track_total = sum(fw.values())
        if track_total <= 0:
            continue
        for code, w in fw.items():
            new_weights[code] += tgt * (w / track_total)

    pm = get_portfolio_manager()
    updated = 0
    for code, w in new_weights.items():
        pm.update_holding(portfolio_id, code, weight=round(w, 4))
        updated += 1
    return updated


def analyze_portfolio(
    holdings: List[dict],
    *,
    balance_strength: float = 0.5,
    deviation_threshold: float = 0.03,
    include_flow: bool = True,
    flow_tilt: bool = False,
    flow_tilt_cap: float = 0.02,
) -> dict:
    fund_infos = cluster_portfolio(holdings)
    track_rows = build_track_rows(
        fund_infos,
        balance_strength,
        include_flow=include_flow,
        flow_tilt=flow_tilt,
        flow_tilt_cap=flow_tilt_cap,
    )
    actions = generate_rebalance_actions(fund_infos, track_rows, deviation_threshold)
    total_w = sum(fi.portfolio_weight for fi in fund_infos)
    return {
        "fund_infos": fund_infos,
        "track_rows": track_rows,
        "actions": actions,
        "total_weight": round(total_w, 4),
        "balance_strength": balance_strength,
        "deviation_threshold": deviation_threshold,
        "flow_tilt": flow_tilt,
    }


_engine = None


class TrackRebalanceEngine:
    def analyze(self, holdings: List[dict], **kwargs) -> dict:
        return analyze_portfolio(holdings, **kwargs)

    def apply(self, portfolio_id: int, result: dict) -> int:
        return apply_target_weights(
            portfolio_id,
            result["fund_infos"],
            result["track_rows"],
        )


def get_track_rebalance_engine() -> TrackRebalanceEngine:
    global _engine
    if _engine is None:
        _engine = TrackRebalanceEngine()
    return _engine
