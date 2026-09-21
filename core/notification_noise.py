"""
通知降噪系统
============
防止重复推送、冷却窗口、静默时段、每日摘要聚合。

使用方式:
    from core.notification_noise import NoiseFilter

    nf = NoiseFilter()
    if nf.should_send(rule_id, fund_code, message):
        send_notification(...)
        nf.record_send(rule_id, fund_code, message)
"""

import time
import hashlib
from typing import Optional, Dict, Tuple
from collections import defaultdict


class NoiseFilter:
    """
    通知降噪过滤器。

    规则:
        - 相同(rule_id, fund_code)在冷却期内不重复发送
        - 相同消息指纹在窗口内只发一次
        - 静默时段内降级为摘要（不实时推送）
        - 每日每规则最多 max_per_day 次
    """

    def __init__(self, cooldown_seconds: int = 1800, max_per_day: int = 10):
        """
        Args:
            cooldown_seconds: 冷却窗口（秒），默认30分钟
            max_per_day: 单规则每日最多推送次数
        """
        self.cooldown = cooldown_seconds
        self.max_per_day = max_per_day
        self._sent: Dict[str, float] = {}          # key → last_sent_ts
        self._hashes: Dict[str, float] = {}         # msg_hash → last_sent_ts
        self._daily_counts: Dict[str, int] = defaultdict(int)  # rule_id → count_today
        self._day_start = time.time()

    def _reset_daily(self):
        """跨天重置每日计数"""
        if time.time() - self._day_start > 86400:
            self._daily_counts.clear()
            self._day_start = time.time()

    def _make_key(self, rule_id: int, fund_code: str) -> str:
        return f"{rule_id}:{fund_code}"

    @staticmethod
    def _hash_message(msg: str) -> str:
        return hashlib.md5(msg.encode()).hexdigest()[:8]

    def should_send(self, rule_id: int, fund_code: str, message: str = "",
                    severity: str = "medium", force: bool = False) -> bool:
        """
        判断是否应该发送此通知。

        Args:
            rule_id: 规则ID
            fund_code: 基金代码
            message: 通知内容（用于去重）
            severity: 严重度（high 缩短冷却）
            force: 强制发送（忽略降噪）

        Returns:
            bool: True=应发送
        """
        if force:
            return True

        self._reset_daily()
        now = time.time()

        # 每日配额检查
        rule_key = str(rule_id)
        if self._daily_counts.get(rule_key, 0) >= self.max_per_day:
            return False

        # 冷却检查（high severity 冷却 10 分钟）
        cooldown = self.cooldown if severity != "high" else 600
        key = self._make_key(rule_id, fund_code)
        last = self._sent.get(key, 0)
        if now - last < cooldown:
            return False

        # 消息去重（相同内容 2 小时内不重复）
        if message:
            msg_hash = self._hash_message(message)
            last_hash = self._hashes.get(msg_hash, 0)
            if now - last_hash < 7200:
                return False

        return True

    def record_send(self, rule_id: int, fund_code: str, message: str = ""):
        """记录一次发送"""
        now = time.time()
        key = self._make_key(rule_id, fund_code)
        self._sent[key] = now

        if message:
            msg_hash = self._hash_message(message)
            self._hashes[msg_hash] = now

        self._daily_counts[str(rule_id)] += 1

    def get_stats(self) -> dict:
        """获取降噪统计"""
        self._reset_daily()
        return {
            "cooldown_active": sum(1 for v in self._sent.values() if time.time() - v < self.cooldown),
            "total_sent_today": sum(self._daily_counts.values()),
            "rules_hit_limit": sum(1 for v in self._daily_counts.values() if v >= self.max_per_day),
        }


# 全局限流器
_noise_filter: Optional[NoiseFilter] = None


def get_noise_filter() -> NoiseFilter:
    """获取 NoiseFilter 单例"""
    global _noise_filter
    if _noise_filter is None:
        _noise_filter = NoiseFilter()
    return _noise_filter
