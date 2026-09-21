"""
决策信号追踪系统
================
"""

import json
from typing import Optional, List, Dict, Any

from .db import get_connection, now_iso, get_user_id


VALID_ACTIONS = ["buy", "add", "hold", "reduce", "sell", "watch", "avoid"]
VALID_STATUSES = ["active", "confirmed", "rejected", "expired"]
VALID_OUTCOMES = ["correct", "wrong", "partial"]

ACTION_LABELS = {
    "buy": "🟢 买入", "add": "🔵 增持", "hold": "⚪ 持有",
    "reduce": "🟡 减仓", "sell": "🔴 卖出", "watch": "👀 观望", "avoid": "⛔ 规避",
}
ACTION_SEVERITY = {
    "buy": "high", "add": "medium", "hold": "low",
    "reduce": "medium", "sell": "high", "watch": "low", "avoid": "medium",
}


class Signal:
    def __init__(self, row):
        self.id = row["id"]
        self.fund_code = row["fund_code"]
        self.fund_name = row.get("fund_name", "")
        self.action = row["action"]
        self.confidence = float(row.get("confidence", 0))
        self.score = float(row.get("score", 0))
        self.reason = row.get("reason", "")
        self.status = row.get("status", "active")
        self.outcome = row.get("outcome")
        self.resolution_note = row.get("resolution_note", "")
        self.source_analysis_id = row.get("source_analysis_id")
        self.created_at = row["created_at"]
        self.resolved_at = row.get("resolved_at")

    @property
    def action_label(self): return ACTION_LABELS.get(self.action, self.action)
    @property
    def severity(self): return ACTION_SEVERITY.get(self.action, "low")

    def to_dict(self):
        return {
            "id": self.id, "fund_code": self.fund_code, "fund_name": self.fund_name,
            "action": self.action, "action_label": self.action_label,
            "confidence": self.confidence, "score": self.score, "reason": self.reason,
            "status": self.status, "outcome": self.outcome,
            "resolution_note": self.resolution_note,
            "source_analysis_id": self.source_analysis_id,
            "created_at": self.created_at, "resolved_at": self.resolved_at,
        }


class SignalManager:
    def create(self, fund_code, fund_name, action, confidence=0, score=0,
               reason="", source_analysis_id=None) -> int:
        if action not in VALID_ACTIONS:
            raise ValueError(f"无效的动作: {action}")
        uid = get_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO signals (user_id, fund_code, fund_name, action, confidence, "
                "score, reason, status, source_analysis_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (uid, fund_code, fund_name, action, confidence, score, reason,
                 source_analysis_id, now_iso()),
            )
            return cursor.lastrowid

    def get(self, signal_id: int) -> Optional[Signal]:
        uid = get_user_id()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM signals WHERE id = ? AND user_id = ?", (signal_id, uid)
            ).fetchone()
            return Signal(row) if row else None

    def list_all(self, status=None, fund_code=None, action=None, outcome=None,
                 limit=50, offset=0) -> List[Signal]:
        uid = get_user_id()
        conditions = ["user_id = ?"]
        params = [uid]
        if status:
            conditions.append("status = ?"); params.append(status)
        if fund_code:
            conditions.append("fund_code = ?"); params.append(fund_code)
        if action:
            conditions.append("action = ?"); params.append(action)
        if outcome:
            conditions.append("outcome = ?"); params.append(outcome)
        where = "WHERE " + " AND ".join(conditions)
        params.extend([limit, offset])
        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM signals {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [Signal(r) for r in rows]

    def update_status(self, signal_id: int, status: str):
        if status not in VALID_STATUSES:
            raise ValueError(f"无效的状态: {status}")
        uid = get_user_id()
        with get_connection() as conn:
            conn.execute(
                "UPDATE signals SET status = ?, resolved_at = ? WHERE id = ? AND user_id = ?",
                (status, now_iso(), signal_id, uid),
            )

    def record_outcome(self, signal_id: int, outcome: str, resolution_note: str = ""):
        if outcome not in VALID_OUTCOMES:
            raise ValueError(f"无效的结果: {outcome}")
        uid = get_user_id()
        with get_connection() as conn:
            conn.execute(
                "UPDATE signals SET outcome = ?, resolution_note = ?, resolved_at = ? "
                "WHERE id = ? AND user_id = ?",
                (outcome, resolution_note, now_iso(), signal_id, uid),
            )

    def get_statistics(self) -> dict:
        uid = get_user_id()
        with get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM signals WHERE user_id = ?", (uid,)
            ).fetchone()["cnt"]
            by_action = {}
            for row in conn.execute(
                "SELECT action, COUNT(*) as cnt FROM signals WHERE user_id = ? GROUP BY action", (uid,)
            ).fetchall():
                by_action[row["action"]] = row["cnt"]
            by_status = {}
            for row in conn.execute(
                "SELECT status, COUNT(*) as cnt FROM signals WHERE user_id = ? GROUP BY status", (uid,)
            ).fetchall():
                by_status[row["status"]] = row["cnt"]
            correct = conn.execute(
                "SELECT COUNT(*) as cnt FROM signals WHERE user_id = ? AND outcome = 'correct'", (uid,)
            ).fetchone()["cnt"]
            wrong = conn.execute(
                "SELECT COUNT(*) as cnt FROM signals WHERE user_id = ? AND outcome = 'wrong'", (uid,)
            ).fetchone()["cnt"]
            partial = conn.execute(
                "SELECT COUNT(*) as cnt FROM signals WHERE user_id = ? AND outcome = 'partial'", (uid,)
            ).fetchone()["cnt"]
            resolved_total = correct + wrong + partial
            accuracy = correct / resolved_total if resolved_total > 0 else 0
            avg_conf = conn.execute(
                "SELECT AVG(confidence) as avg FROM signals WHERE user_id = ?", (uid,)
            ).fetchone()["avg"] or 0
        return {
            "total": total, "by_action": by_action, "by_status": by_status,
            "correct": correct, "wrong": wrong, "partial": partial,
            "resolved_total": resolved_total,
            "accuracy": round(accuracy, 4),
            "avg_confidence": round(float(avg_conf), 4),
        }

    def extract_from_analysis(self, analysis_text, fund_code, fund_name="",
                              source_analysis_id=None) -> List[int]:
        from .ai_analyzer import get_analyzer
        prompt = f"""从以下基金分析报告中提取投资操作建议，输出 JSON 数组。

报告内容:
{analysis_text[:4000]}

请提取所有可识别的操作建议，每条包含:
- action: buy/add/hold/reduce/sell/watch/avoid
- confidence: 0.0-1.0
- score: 0-10
- reason: 一句话理由

仅输出 JSON 数组: [{{"action": "buy", "confidence": 0.8, "score": 7, "reason": "..."}}]"""
        try:
            analyzer = get_analyzer()
            response = analyzer.quick_chat(prompt, max_tokens=1024)
            js = response.find("["); je = response.rfind("]") + 1
            if js >= 0 and je > js:
                data = json.loads(response[js:je])
                ids = []
                for item in data:
                    if not isinstance(item, dict): continue
                    action = str(item.get("action", "hold")).strip().lower()
                    if action not in VALID_ACTIONS: action = "hold"
                    try: conf = float(item.get("confidence", 0.5))
                    except (ValueError, TypeError): conf = 0.5
                    try: sc = float(item.get("score", 5.0))
                    except (ValueError, TypeError): sc = 5.0
                    reason = str(item.get("reason", ""))[:500]
                    sid = self.create(fund_code, fund_name, action, conf, sc, reason, source_analysis_id)
                    ids.append(sid)
                return ids
        except (json.JSONDecodeError, Exception):
            pass
        return []


_signal_manager: Optional[SignalManager] = None

def get_signal_manager() -> SignalManager:
    global _signal_manager
    if _signal_manager is None:
        _signal_manager = SignalManager()
    return _signal_manager
