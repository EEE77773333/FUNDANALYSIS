"""
预警规则引擎
============
创建和管理 NAV/价格预警规则，定期评估触发条件，
自动推送高严重度预警通知。

预警类型:
    - nav_drop_pct:         净值较近期高点下跌超过 X%
    - drawdown_pct:         最大回撤超过 X%
    - consecutive_down_days: 连续下跌 N 天
    - underperform_benchmark: 跑输基准超过 X%（未来扩展）

严重度: high / medium / low

使用方式:
    from core.alert_engine import get_alert_engine

    ae = get_alert_engine()
    rid = ae.create_rule("回撤预警", "drawdown_pct", ["000001"], {"threshold": 0.15}, "high")
    triggers = ae.evaluate_all()
"""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from .db import get_connection, now_iso, get_user_id
from .data_fetcher import get_fetcher
from .utils import safe_float, calc_max_drawdown


# 支持的预警类型及参数说明
ALERT_TYPE_PARAMS = {
    "nav_drop_pct": {
        "threshold_pct": {"type": "number", "default": 5, "label": "下跌阈值 (%)"},
        "lookback_days": {"type": "number", "default": 60, "label": "回溯天数"},
    },
    "drawdown_pct": {
        "threshold_pct": {"type": "number", "default": 15, "label": "回撤阈值 (%)"},
    },
    "consecutive_down_days": {
        "days": {"type": "number", "default": 5, "label": "连续下跌天数"},
    },
    "intraday_nav_change_pct": {
        "threshold_pct": {"type": "number", "default": 3, "label": "盘中估值涨跌幅阈值 (%)"},
    },
    "theme_flow_rank_jump": {
        "rank_jump": {"type": "number", "default": 5, "label": "排名变动阈值（位）"},
    },
}

ALERT_TYPE_LABELS = {
    "nav_drop_pct": "📉 净值下跌",
    "drawdown_pct": "📊 回撤预警",
    "consecutive_down_days": "📅 连续下跌",
    "intraday_nav_change_pct": "📡 盘中估值异动",
    "theme_flow_rank_jump": "🌊 主题资金排名跃变",
}

SEVERITY_LABELS = {
    "high": "🔴 高",
    "medium": "🟡 中",
    "low": "🟢 低",
}


# ============================================================
# 数据类
# ============================================================

class AlertRule:
    """预警规则数据类"""

    def __init__(self, row):
        self.id = row["id"]
        self.name = row["name"]
        self.alert_type = row["alert_type"]
        fc = row.get("fund_codes_json", "[]")
        self.fund_codes: List[str] = fc if isinstance(fc, list) else json.loads(fc if isinstance(fc, str) else "[]")
        pm = row.get("parameters_json", "{}")
        self.parameters: dict = pm if isinstance(pm, dict) else json.loads(pm if isinstance(pm, str) else "{}")
        self.severity = row.get("severity", "medium")
        self.enabled = bool(row.get("enabled", 1))
        self.created_at = row["created_at"]

    @property
    def type_label(self) -> str:
        return ALERT_TYPE_LABELS.get(self.alert_type, self.alert_type)

    @property
    def severity_label(self) -> str:
        return SEVERITY_LABELS.get(self.severity, self.severity)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "alert_type": self.alert_type,
            "type_label": self.type_label,
            "fund_codes": self.fund_codes,
            "parameters": self.parameters,
            "severity": self.severity,
            "severity_label": self.severity_label,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }


class AlertTrigger:
    """触发记录数据类"""

    def __init__(self, row):
        self.id = row["id"]
        self.rule_id = row["rule_id"]
        self.fund_code = row["fund_code"]
        self.message = row["message"]
        self.severity = row.get("severity", "medium")
        self.triggered_at = row["triggered_at"]
        self.acknowledged = bool(row.get("acknowledged", 0))


# ============================================================
# 预警引擎
# ============================================================

class AlertEngine:
    """预警规则 CRUD + 评估引擎"""

    # ---- 规则 CRUD ----

    def create_rule(
        self,
        name: str,
        alert_type: str,
        fund_codes: List[str],
        parameters: dict = None,
        severity: str = "medium",
    ) -> int:
        """创建预警规则，返回规则 ID"""
        if alert_type not in ALERT_TYPE_PARAMS:
            raise ValueError(f"不支持的预警类型: {alert_type}")

        uid = get_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO alert_rules
                   (user_id, name, alert_type, fund_codes_json, parameters_json, severity, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    uid, name, alert_type,
                    json.dumps(fund_codes, ensure_ascii=False),
                    json.dumps(parameters or {}, ensure_ascii=False),
                    severity, now_iso(),
                ),
            )
            return cursor.lastrowid

    def get_rule(self, rule_id: int) -> Optional[AlertRule]:
        """获取单个规则"""
        uid = get_user_id()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM alert_rules WHERE id = ? AND user_id = ?", (rule_id, uid)
            ).fetchone()
            return AlertRule(row) if row else None

    def list_rules(self, enabled_only: bool = False) -> List[AlertRule]:
        """列出当前用户的所有规则"""
        uid = get_user_id()
        with get_connection() as conn:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM alert_rules WHERE user_id = ? AND enabled = 1 ORDER BY created_at DESC",
                    (uid,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alert_rules WHERE user_id = ? ORDER BY created_at DESC",
                    (uid,),
                ).fetchall()
            return [AlertRule(r) for r in rows]

    def update_rule(self, rule_id: int, **kwargs):
        """更新规则字段"""
        allowed = {"name", "alert_type", "severity", "fund_codes_json", "parameters_json"}
        updates = {}
        for k, v in kwargs.items():
            if k == "fund_codes":
                updates["fund_codes_json"] = json.dumps(v, ensure_ascii=False)
            elif k == "parameters":
                updates["parameters_json"] = json.dumps(v, ensure_ascii=False)
            elif k in allowed:
                updates[k] = v

        if not updates:
            return

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [rule_id]
        with get_connection() as conn:
            uid = get_user_id()
            values.append(uid)
            conn.execute(f"UPDATE alert_rules SET {set_clause} WHERE id = ? AND user_id = ?", values)

    def delete_rule(self, rule_id: int):
        """删除规则及其触发历史"""
        uid = get_user_id()
        with get_connection() as conn:
            conn.execute("DELETE FROM alert_triggers WHERE rule_id = ? AND user_id = ?", (rule_id, uid))
            conn.execute("DELETE FROM alert_rules WHERE id = ? AND user_id = ?", (rule_id, uid))

    def toggle_rule(self, rule_id: int, enabled: bool):
        """启用/禁用规则"""
        uid = get_user_id()
        with get_connection() as conn:
            conn.execute(
                "UPDATE alert_rules SET enabled = ? WHERE id = ? AND user_id = ?",
                (1 if enabled else 0, rule_id, uid),
            )

    # ---- 评估 ----

    def evaluate_rule(self, rule: AlertRule) -> List[AlertTrigger]:
        """
        评估单条规则，返回触发的预警列表。

        根据 rule.alert_type 分发到具体的评估函数。
        """
        evaluators = {
            "nav_drop_pct": self._evaluate_nav_drop,
            "drawdown_pct": self._evaluate_drawdown,
            "consecutive_down_days": self._evaluate_consecutive_down,
            "intraday_nav_change_pct": self._evaluate_intraday_nav,
            "theme_flow_rank_jump": self._evaluate_theme_flow_rank,
        }
        evaluator = evaluators.get(rule.alert_type)
        if not evaluator:
            return []

        return evaluator(rule)

    def _evaluate_nav_drop(self, rule: AlertRule) -> List[AlertTrigger]:
        """评估净值下跌预警"""
        threshold_pct = float(rule.parameters.get("threshold_pct", 5)) / 100
        lookback_days = int(rule.parameters.get("lookback_days", 60))

        triggers = []
        fetcher = get_fetcher()

        for code in rule.fund_codes:
            try:
                nav_df = fetcher.get_fund_nav_history(code, years=1)
                if nav_df is None or nav_df.empty:
                    continue

                nav_df = nav_df.sort_values("日期")
                recent_window = nav_df.tail(lookback_days)
                if len(recent_window) < 5:
                    continue

                recent_high = recent_window["单位净值"].max()
                latest_nav = recent_window["单位净值"].iloc[-1]
                drop_pct = (recent_high - latest_nav) / recent_high

                if drop_pct >= threshold_pct:
                    info = fetcher.get_fund_manager_info(code)
                    fund_name = info.get("基金名称", code) if info else code
                    message = (
                        f"{fund_name}({code}) 净值较近{lookback_days}日高点 "
                        f"下跌 {drop_pct * 100:.2f}%，超过阈值 {threshold_pct * 100:.1f}%\n"
                        f"近期高点净值: {recent_high:.4f}，最新净值: {latest_nav:.4f}"
                    )
                    triggers.append(self._save_trigger(rule.id, code, message, rule.severity))
            except Exception:
                continue

        return triggers

    def _evaluate_drawdown(self, rule: AlertRule) -> List[AlertTrigger]:
        """评估回撤预警"""
        threshold_pct = float(rule.parameters.get("threshold_pct", 15)) / 100

        triggers = []
        fetcher = get_fetcher()

        for code in rule.fund_codes:
            try:
                nav_df = fetcher.get_fund_nav_history(code, years=3)
                if nav_df is None or nav_df.empty:
                    continue

                nav_series = nav_df.sort_values("日期")["单位净值"]
                max_dd = calc_max_drawdown(nav_series)

                if abs(max_dd) >= threshold_pct:
                    info = fetcher.get_fund_manager_info(code)
                    fund_name = info.get("基金名称", code) if info else code
                    message = (
                        f"{fund_name}({code}) 历史最大回撤 {abs(max_dd) * 100:.2f}%，"
                        f"超过阈值 {threshold_pct * 100:.1f}%"
                    )
                    triggers.append(self._save_trigger(rule.id, code, message, rule.severity))
            except Exception:
                continue

        return triggers

    def _evaluate_consecutive_down(self, rule: AlertRule) -> List[AlertTrigger]:
        """评估连续下跌预警"""
        days_threshold = int(rule.parameters.get("days", 5))

        triggers = []
        fetcher = get_fetcher()

        for code in rule.fund_codes:
            try:
                nav_df = fetcher.get_fund_nav_history(code, years=1)
                if nav_df is None or nav_df.empty:
                    continue

                nav_df = nav_df.sort_values("日期")
                nav_df["down"] = nav_df["单位净值"].diff() < 0

                # 计算当前连续下跌天数
                consecutive = 0
                for is_down in reversed(nav_df["down"].tolist()):
                    if is_down:
                        consecutive += 1
                    else:
                        break

                if consecutive >= days_threshold:
                    info = fetcher.get_fund_manager_info(code)
                    fund_name = info.get("基金名称", code) if info else code
                    message = (
                        f"{fund_name}({code}) 已连续下跌 {consecutive} 天，"
                        f"超过阈值 {days_threshold} 天"
                    )
                    triggers.append(self._save_trigger(rule.id, code, message, rule.severity))
            except Exception:
                continue

        return triggers

    def _evaluate_intraday_nav(self, rule: AlertRule) -> List[AlertTrigger]:
        """盘中估值涨跌幅超阈值预警。"""
        threshold = float(rule.parameters.get("threshold_pct", 3))
        triggers = []
        from .intraday_nav import get_intraday_engine

        engine = get_intraday_engine()
        for code in rule.fund_codes:
            try:
                r = engine.estimate(code)
                pct = r.estimated_pct
                if abs(pct) < threshold:
                    continue
                name = r.fund_name or code
                message = (
                    f"{name}({code}) 盘中估值 {pct:+.2f}%（模式: {r.mode}），"
                    f"超过阈值 ±{threshold}%"
                )
                triggers.append(self._save_trigger(rule.id, code, message, rule.severity))
            except Exception:
                continue
        return triggers

    def _evaluate_theme_flow_rank(self, rule: AlertRule) -> List[AlertTrigger]:
        """主题资金排名跃升/骤降预警。"""
        rank_jump = int(rule.parameters.get("rank_jump", 5))
        watch = rule.fund_codes if rule.fund_codes else None
        triggers = []
        try:
            from .theme_flow import fetch_all_sector_flows, aggregate_theme_flows, detect_theme_rank_jumps
            themes = aggregate_theme_flows(fetch_all_sector_flows())
            if not themes:
                return []
            jumps = detect_theme_rank_jumps(themes, rank_jump=rank_jump, watch_themes=watch)
            for j in jumps:
                direction = "跃升" if j["delta"] > 0 else "骤降"
                message = (
                    f"主题「{j['theme']}」资金排名{direction} {abs(j['delta'])} 位"
                    f"（{j['prev_rank']} → {j['curr_rank']}），"
                    f"净流入 {j['net_inflow_yi']:+.2f} 亿"
                )
                triggers.append(self._save_trigger(rule.id, j["theme"], message, rule.severity))
        except Exception:
            pass
        return triggers

    def _save_trigger(self, rule_id: int, fund_code: str, message: str, severity: str) -> AlertTrigger:
        """保存触发记录到数据库"""
        uid = get_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO alert_triggers (rule_id, user_id, fund_code, message, severity, triggered_at, acknowledged) VALUES (?, ?, ?, ?, ?, ?, 0)",
                (rule_id, uid, fund_code, message, severity, now_iso()),
            )
            # 获取刚创建的记录
            row = conn.execute(
                "SELECT * FROM alert_triggers WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return AlertTrigger(row)

    def evaluate_all(self) -> List[AlertTrigger]:
        """
        评估所有已启用规则，返回全部触发记录。
        高严重度预警自动广播通知。
        """
        rules = self.list_rules(enabled_only=True)
        all_triggers = []

        for rule in rules:
            triggers = self.evaluate_rule(rule)
            all_triggers.extend(triggers)

        # 高严重度预警自动推送通知
        high_triggers = [t for t in all_triggers if t.severity == "high"]
        if high_triggers:
            self._broadcast_high_alerts(high_triggers)

        return all_triggers

    def _broadcast_high_alerts(self, triggers: List[AlertTrigger]):
        """向通知管理器广播高严重度预警（含降噪过滤）"""
        try:
            from .notifications import get_notification_manager
            from .notification_noise import get_noise_filter

            nm = get_notification_manager()
            nf = get_noise_filter()

            filtered = []
            for t in triggers:
                if nf.should_send(t.rule_id, t.fund_code, t.message, severity="high"):
                    filtered.append(t)
                    nf.record_send(t.rule_id, t.fund_code, t.message)

            if not filtered:
                return

            title = f"🚨 基金预警 - {len(filtered)} 条高严重度告警"
            content_lines = []
            for t in filtered:
                content_lines.append(f"- [{t.fund_code}] {t.message}")
            content = "\n".join(content_lines)
            nm.broadcast(title, content)
        except Exception:
            pass

    # ---- 触发历史 ----

    def get_triggers(
        self,
        rule_id: int = None,
        fund_code: str = None,
        acknowledged: bool = None,
        limit: int = 100,
    ) -> List[AlertTrigger]:
        """查询触发历史"""
        uid = get_user_id()
        conditions = ["user_id = ?"]
        params = [uid]

        if rule_id is not None:
            conditions.append("rule_id = ?")
            params.append(rule_id)
        if fund_code:
            conditions.append("fund_code = ?")
            params.append(fund_code)
        if acknowledged is not None:
            conditions.append("acknowledged = ?")
            params.append(1 if acknowledged else 0)

        where = f"WHERE {' AND '.join(conditions)}"
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM alert_triggers {where} ORDER BY triggered_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [AlertTrigger(r) for r in rows]

    def acknowledge_trigger(self, trigger_id: int):
        """确认单条预警"""
        uid = get_user_id()
        with get_connection() as conn:
            conn.execute(
                "UPDATE alert_triggers SET acknowledged = 1 WHERE id = ? AND user_id = ?",
                (trigger_id, uid),
            )

    def acknowledge_all(self, fund_code: str = None):
        """批量确认预警"""
        uid = get_user_id()
        with get_connection() as conn:
            if fund_code:
                conn.execute(
                    "UPDATE alert_triggers SET acknowledged = 1 WHERE user_id = ? AND fund_code = ? AND acknowledged = 0",
                    (uid, fund_code),
                )
            else:
                conn.execute(
                    "UPDATE alert_triggers SET acknowledged = 1 WHERE user_id = ? AND acknowledged = 0",
                    (uid,),
                )

    def get_trigger_stats(self) -> dict:
        """获取触发统计"""
        uid = get_user_id()
        with get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM alert_triggers WHERE user_id = ?", (uid,)
            ).fetchone()["cnt"]
            unack = conn.execute(
                "SELECT COUNT(*) as cnt FROM alert_triggers WHERE user_id = ? AND acknowledged = 0", (uid,)
            ).fetchone()["cnt"]
            by_severity = {}
            for row in conn.execute(
                "SELECT severity, COUNT(*) as cnt FROM alert_triggers WHERE user_id = ? GROUP BY severity", (uid,)
            ).fetchall():
                by_severity[row["severity"]] = row["cnt"]
            week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
            recent = conn.execute(
                "SELECT COUNT(*) as cnt FROM alert_triggers WHERE user_id = ? AND triggered_at >= ?",
                (uid, week_ago),
            ).fetchone()["cnt"]

        return {
            "total": total,
            "unacknowledged": unack,
            "by_severity": by_severity,
            "recent_7d": recent,
            "today": self.count_triggers_today(),
        }

    def count_triggers_today(self, acknowledged: bool = None) -> int:
        """统计今日触发数（按 UTC 日期前缀匹配 triggered_at）。"""
        uid = get_user_id()
        today = datetime.utcnow().strftime("%Y-%m-%d")
        conditions = ["user_id = ?", "triggered_at >= ?"]
        params: list = [uid, today]
        if acknowledged is not None:
            conditions.append("acknowledged = ?")
            params.append(1 if acknowledged else 0)
        where = " AND ".join(conditions)
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM alert_triggers WHERE {where}",
                tuple(params),
            ).fetchone()
        return int(row["cnt"] if row else 0)

    def get_triggers_grouped(
        self,
        acknowledged: bool = None,
        today_only: bool = False,
        limit: int = 100,
    ) -> List[dict]:
        """
        按 fund_code + message 前 60 字合并展示同类告警。
        返回 [{fund_code, message, severity, count, latest_at, ids, acknowledged}]
        """
        triggers = self.get_triggers(acknowledged=acknowledged, limit=limit * 3)
        if today_only:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            triggers = [t for t in triggers if (t.triggered_at or "").startswith(today)]

        groups: Dict[str, dict] = {}
        for t in triggers:
            key = f"{t.fund_code}|{(t.message or '')[:60]}"
            if key not in groups:
                groups[key] = {
                    "fund_code": t.fund_code,
                    "message": t.message,
                    "severity": t.severity,
                    "count": 1,
                    "latest_at": t.triggered_at,
                    "latest_id": t.id,
                    "ids": [t.id],
                    "acknowledged": t.acknowledged,
                }
            else:
                g = groups[key]
                g["count"] += 1
                g["ids"].append(t.id)
                if (t.triggered_at or "") > (g["latest_at"] or ""):
                    g["latest_at"] = t.triggered_at
                    g["severity"] = t.severity
                    g["latest_id"] = t.id
                g["acknowledged"] = g["acknowledged"] and t.acknowledged

        items = sorted(groups.values(), key=lambda x: x["latest_at"] or "", reverse=True)
        return items[:limit]

    def dismiss_trigger_ids(self, trigger_ids: List[int]) -> None:
        """批量忽略/确认。"""
        if not trigger_ids:
            return
        uid = get_user_id()
        with get_connection() as conn:
            for tid in trigger_ids:
                conn.execute(
                    "UPDATE alert_triggers SET acknowledged = 1 WHERE id = ? AND user_id = ?",
                    (tid, uid),
                )


# ============================================================
# 单例
# ============================================================

_alert_engine: Optional[AlertEngine] = None


def get_alert_engine() -> AlertEngine:
    """获取 AlertEngine 全局单例"""
    global _alert_engine
    if _alert_engine is None:
        _alert_engine = AlertEngine()
    return _alert_engine
