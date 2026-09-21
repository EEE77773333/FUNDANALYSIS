"""
AI 建议多窗口事后验证引擎
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from .calibration_metrics import aggregate_metrics, brier_score, direction_hit, outcome_label
from .data_fetcher import get_fetcher
from .db import get_connection, get_user_id, now_iso
from .signals import VALID_ACTIONS, get_signal_manager

HORIZONS = [1, 3, 5, 10, 20]


class EvaluationRecord:
    def __init__(self, row):
        if not isinstance(row, dict):
            row = dict(row)
        self.id = row["id"]
        self.source_type = row["source_type"]
        self.source_id = row["source_id"]
        self.fund_code = row.get("fund_code", "")
        self.fund_name = row.get("fund_name", "")
        self.horizon_days = int(row.get("horizon_days") or 0)
        self.predicted_action = row.get("predicted_action", "hold")
        self.confidence = float(row.get("confidence") or 0)
        self.actual_return = float(row.get("actual_return") or 0)
        dh = row.get("direction_hit")
        self.direction_hit = None if dh is None else bool(dh)
        self.brier_score = float(row.get("brier_score") or 0)
        self.outcome = row.get("outcome", "")
        self.evaluated_at = row.get("evaluated_at", "")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "horizon_days": self.horizon_days,
            "predicted_action": self.predicted_action,
            "confidence": self.confidence,
            "actual_return": self.actual_return,
            "direction_hit": self.direction_hit,
            "brier_score": self.brier_score,
            "outcome": self.outcome,
            "evaluated_at": self.evaluated_at,
        }


def calc_horizon_return(nav_df: pd.DataFrame, start_date: str, horizon_days: int) -> Optional[float]:
    """按交易日计算 T+N 收益率。"""
    if nav_df is None or nav_df.empty:
        return None
    nav = nav_df.sort_values("日期").copy()
    nav["日期"] = pd.to_datetime(nav["日期"])
    start = pd.to_datetime(str(start_date)[:10])
    after = nav[nav["日期"] >= start]
    if len(after) <= horizon_days:
        return None
    start_nav = float(after["单位净值"].iloc[0])
    end_nav = float(after["单位净值"].iloc[horizon_days])
    if start_nav <= 0:
        return None
    return (end_nav - start_nav) / start_nav


class EvaluationManager:
    def _exists(self, source_type: str, source_id: int, horizon_days: int) -> bool:
        uid = get_user_id()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM signal_evaluations WHERE user_id=? AND source_type=? "
                "AND source_id=? AND horizon_days=?",
                (uid, source_type, source_id, horizon_days),
            ).fetchone()
            return row is not None

    def _save(
        self,
        source_type: str,
        source_id: int,
        fund_code: str,
        fund_name: str,
        horizon_days: int,
        action: str,
        confidence: float,
        actual_return: float,
    ) -> Optional[int]:
        if self._exists(source_type, source_id, horizon_days):
            return None
        hit = direction_hit(action, actual_return)
        outcome = outcome_label(action, actual_return)
        brier = brier_score(confidence, hit)
        uid = get_user_id()
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO signal_evaluations "
                "(user_id, source_type, source_id, fund_code, fund_name, horizon_days, "
                "predicted_action, confidence, actual_return, direction_hit, brier_score, "
                "outcome, evaluated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uid, source_type, source_id, fund_code, fund_name, horizon_days,
                    action, confidence, actual_return,
                    1 if hit is True else (0 if hit is False else None),
                    brier, outcome, now_iso(),
                ),
            )
            return cur.lastrowid

    def evaluate_signal(self, signal) -> List[int]:
        fetcher = get_fetcher()
        nav = fetcher.get_fund_nav_history(signal.fund_code, years=2)
        ids = []
        for h in HORIZONS:
            ret = calc_horizon_return(nav, signal.created_at, h)
            if ret is None:
                continue
            rid = self._save(
                "signal", signal.id, signal.fund_code, signal.fund_name,
                h, signal.action, signal.confidence, ret,
            )
            if rid:
                ids.append(rid)
        return ids

    def evaluate_analysis(self, record) -> List[int]:
        data = record.structured_result
        if not data or not record.fund_code:
            return []
        sfv = data.get("signal_for_validation") or {}
        action = str(sfv.get("action", "watch")).lower()
        if action not in VALID_ACTIONS:
            action = "watch"
        confidence = float(sfv.get("confidence") or 0.5)
        fetcher = get_fetcher()
        nav = fetcher.get_fund_nav_history(record.fund_code, years=2)
        ids = []
        for h in HORIZONS:
            ret = calc_horizon_return(nav, record.created_at, h)
            if ret is None:
                continue
            rid = self._save(
                "analysis", record.id, record.fund_code, record.fund_name,
                h, action, confidence, ret,
            )
            if rid:
                ids.append(rid)
        return ids

    def run_batch(self) -> dict:
        sm = get_signal_manager()
        from .history import get_history_manager

        hm = get_history_manager()
        created = 0
        skipped = 0
        errors = 0

        for sig in sm.list_all(limit=300):
            try:
                n = len(self.evaluate_signal(sig))
                created += n
                if n == 0:
                    skipped += 1
            except Exception:
                errors += 1

        for rec in hm.list_all(limit=200):
            if not rec.structured_result or not rec.fund_code:
                continue
            try:
                n = len(self.evaluate_analysis(rec))
                created += n
                if n == 0:
                    skipped += 1
            except Exception:
                errors += 1

        return {"created": created, "skipped": skipped, "errors": errors}

    def list_evaluations(
        self,
        *,
        source_type: Optional[str] = None,
        fund_code: Optional[str] = None,
        horizon_days: Optional[int] = None,
        limit: int = 200,
    ) -> List[EvaluationRecord]:
        uid = get_user_id()
        conds = ["user_id = ?"]
        params: list = [uid]
        if source_type:
            conds.append("source_type = ?")
            params.append(source_type)
        if fund_code:
            conds.append("fund_code = ?")
            params.append(fund_code)
        if horizon_days is not None:
            conds.append("horizon_days = ?")
            params.append(horizon_days)
        params.append(limit)
        where = " AND ".join(conds)
        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM signal_evaluations WHERE {where} "
                f"ORDER BY evaluated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [EvaluationRecord(r) for r in rows]

    def get_for_source(self, source_type: str, source_id: int) -> List[EvaluationRecord]:
        uid = get_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM signal_evaluations WHERE user_id=? AND source_type=? "
                "AND source_id=? ORDER BY horizon_days",
                (uid, source_type, source_id),
            ).fetchall()
        return [EvaluationRecord(r) for r in rows]

    def get_summary(self) -> dict:
        evs = self.list_evaluations(limit=5000)
        return aggregate_metrics([e.to_dict() for e in evs])

    def get_calibration_data(self) -> List[dict]:
        from .calibration_metrics import calibration_buckets
        evs = self.list_evaluations(limit=5000)
        decisive = [e.to_dict() for e in evs if e.direction_hit is not None]
        return calibration_buckets(decisive)

    def count_pending(self) -> dict:
        sm = get_signal_manager()
        from .history import get_history_manager
        hm = get_history_manager()

        pending_signals = 0
        for sig in sm.list_all(limit=300):
            existing = {e.horizon_days for e in self.get_for_source("signal", sig.id)}
            if len(existing) < len(HORIZONS):
                pending_signals += 1

        pending_analysis = 0
        for rec in hm.list_all(limit=200):
            if not rec.structured_result or not rec.fund_code:
                continue
            existing = {e.horizon_days for e in self.get_for_source("analysis", rec.id)}
            if len(existing) < len(HORIZONS):
                pending_analysis += 1

        return {
            "pending_signals": pending_signals,
            "pending_analysis": pending_analysis,
            "horizons": HORIZONS,
        }


_eval_manager: Optional[EvaluationManager] = None


def get_evaluation_manager() -> EvaluationManager:
    global _eval_manager
    if _eval_manager is None:
        _eval_manager = EvaluationManager()
    return _eval_manager
