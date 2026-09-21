"""
Agent 记忆系统 + 信号结果自动追踪
==================================
1. AgentMemory — 追踪 FAMAS Agent 历史分析准确率，满30样本后自我校准
2. SignalEvaluator — 根据实际净值变化自动评估信号准确率

使用方式:
    from core.agent_memory import AgentMemory, SignalEvaluator

    mem = AgentMemory("cost_analyzer")
    mem.record_accuracy(0.85)  # 记录一次分析的准确率
    calibrated_conf = mem.calibrate(0.90)  # 校准置信度

    evaluator = SignalEvaluator()
    results = evaluator.evaluate_pending_signals()
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict, List
from collections import defaultdict

import numpy as np

DATA_DIR = Path(__file__).parent.parent / "data"


class AgentMemory:
    """
    Agent 历史准确率记忆（按用户隔离）。

    每个 Agent 维护：
        - 最近 50 条准确率记录
        - 累积准确率（用于置信度校准）
        - 校准因子
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self._data = self._load()

    @staticmethod
    def _memory_file() -> Path:
        """获取当前用户的内存文件路径（动态计算，确保多用户隔离）"""
        try:
            from core.db import get_user_id
            uid = get_user_id()
            suffix = f"_user{uid}" if uid != 1 else ""
        except Exception:
            suffix = ""
        return DATA_DIR / f"agent_memory{suffix}.json"

    def _load(self) -> dict:
        """加载持久化记忆"""
        mf = self._memory_file()
        if mf.exists():
            try:
                with open(mf, "r") as f:
                    all_data = json.load(f)
                    return all_data.get(self.agent_name, {"scores": [], "total": 0, "count": 0})
            except Exception:
                pass
        return {"scores": [], "total": 0, "count": 0}

    def _save(self):
        """持久化到文件（按用户隔离）"""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        mf = self._memory_file()
        all_data = {}
        if mf.exists():
            try:
                with open(mf, "r") as f:
                    all_data = json.load(f)
            except Exception:
                pass
        all_data[self.agent_name] = self._data
        with open(mf, "w") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)

    def record_accuracy(self, score: float):
        """
        记录一次分析的准确率评分（0-1）。

        Args:
            score: 准确率（如 0.85 = 85% 的用户采纳率或信号正确率）
        """
        self._data["scores"].append(score)
        self._data["total"] += score
        self._data["count"] += 1

        # 保持窗口 50 条
        if len(self._data["scores"]) > 50:
            removed = self._data["scores"].pop(0)
            self._data["total"] -= removed
            self._data["count"] -= 1

        self._save()

    @property
    def avg_accuracy(self) -> float:
        """平均准确率"""
        if self._data["count"] < 1:
            return 0.5
        return self._data["total"] / self._data["count"]

    @property
    def sample_count(self) -> int:
        return self._data["count"]

    @property
    def is_calibrated(self) -> bool:
        """是否有足够样本进行校准（>=30）"""
        return self._data["count"] >= 30

    def calibrate(self, raw_confidence: float) -> float:
        """
        根据历史准确率校准置信度。

        公式: calibrated = raw_confidence × calibration_factor
        calibration_factor = avg_accuracy / 0.7 (以0.7为基准)

        Args:
            raw_confidence: 原始置信度 (0-1)

        Returns:
            校准后的置信度 (0-1)
        """
        if not self.is_calibrated:
            return raw_confidence

        # 校准因子：实际准确率 / 预期基准
        baseline = 0.7
        factor = self.avg_accuracy / baseline
        # 限制校准幅度在 0.5x ~ 1.5x
        factor = max(0.5, min(1.5, factor))

        calibrated = raw_confidence * factor
        return round(min(1.0, max(0.0, calibrated)), 4)

    def to_dict(self) -> dict:
        return {
            "agent": self.agent_name,
            "avg_accuracy": round(self.avg_accuracy, 4),
            "samples": self.sample_count,
            "calibrated": self.is_calibrated,
        }


class SignalEvaluator:
    """
    信号结果自动追踪器。

    根据信号创建后的实际净值变化，自动评估信号准确率。
    """

    def __init__(self):
        pass

    def evaluate_pending_signals(self) -> List[dict]:
        """
        评估所有未标记结果的信号。

        对每个 active/confirmed 信号：
            1. 获取信号创建以来的净值变化
            2. 对比信号方向（buy应该上涨，sell应该下跌）
            3. 自动标记 correct/wrong/partial

        Returns:
            [{signal_id, outcome, actual_return, reason}, ...]
        """
        from .signals import get_signal_manager, VALID_ACTIONS
        from .data_fetcher import get_fetcher

        sm = get_signal_manager()
        fetcher = get_fetcher()
        results = []

        # 获取所有未标记结果的 active/confirmed 信号
        signals = sm.list_all(limit=200)
        pending = [s for s in signals if not s.outcome and s.status in ("active", "confirmed")]

        for sig in pending:
            try:
                nav = fetcher.get_fund_nav_history(sig.fund_code, years=1)
                if nav is None or nav.empty:
                    continue

                nav = nav.sort_values("日期")
                # 找到信号日期之后的净值
                sig_date = sig.created_at[:10]
                after = nav[nav["日期"] >= sig_date]

                if len(after) < 5:
                    continue  # 数据不足

                start_nav = after["单位净值"].iloc[0]
                end_nav = after["单位净值"].iloc[-1]
                actual_return = (end_nav - start_nav) / start_nav

                # 判断信号是否正确
                outcome = self._judge(sig.action, actual_return)
                reason = (
                    f"信号创建后净值变化 {actual_return*100:+.2f}%，"
                    f"从 {start_nav:.4f} → {end_nav:.4f} ({len(after)}个交易日)"
                )

                sm.record_outcome(sig.id, outcome, reason)
                results.append({
                    "signal_id": sig.id,
                    "fund_code": sig.fund_code,
                    "action": sig.action,
                    "outcome": outcome,
                    "actual_return": round(actual_return, 4),
                    "reason": reason,
                })

            except Exception:
                continue

        return results

    @staticmethod
    def _judge(action: str, actual_return: float) -> str:
        """
        根据实际收益率判断信号结果。

        buy/add: 涨了→correct, 跌了→wrong
        sell/reduce: 跌了→correct, 涨了→wrong
        hold/watch: 波动<2%→correct, 否则→partial
        avoid: 跌了→correct, 涨了→wrong
        """
        bullish = action in ("buy", "add")
        bearish = action in ("sell", "reduce", "avoid")
        neutral = action in ("hold", "watch")

        if neutral:
            if abs(actual_return) < 0.02:
                return "correct"
            elif abs(actual_return) < 0.05:
                return "partial"
            else:
                return "wrong"

        if bullish:
            if actual_return > 0.03:
                return "correct"
            elif actual_return > -0.02:
                return "partial"
            else:
                return "wrong"

        if bearish:
            if actual_return < -0.03:
                return "correct"
            elif actual_return < 0.02:
                return "partial"
            else:
                return "wrong"

        return "partial"


def get_agent_memory(agent_name: str) -> AgentMemory:
    """快捷获取 Agent 记忆"""
    return AgentMemory(agent_name)
