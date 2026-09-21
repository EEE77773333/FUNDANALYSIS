"""
市场阶段检测
============
基于沪深300指数技术指标判断当前市场阶段。

阶段分类:
    - bull          — 牛市（趋势向上）
    - bear          — 熊市（趋势向下）
    - sideways      — 震荡（横盘整理）
    - accumulation  — 筑底（低位盘整）
    - distribution  — 筑顶（高位盘整）
    - unknown       — 数据不足

使用方式:
    from core.market_phase import get_phase_detector

    pd = get_phase_detector()
    phase = pd.detect("沪深300")
    context = pd.format_for_llm(phase)  # 可注入 AI prompt
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from .data_fetcher import get_fetcher
from .utils import safe_float


# 阶段标签
PHASE_LABELS = {
    "bull": "🐂 牛市",
    "bear": "🐻 熊市",
    "sideways": "↔️ 震荡",
    "accumulation": "📈 筑底",
    "distribution": "📉 筑顶",
    "unknown": "❓ 数据不足",
}


class MarketPhase:
    """市场阶段数据类"""

    def __init__(
        self,
        phase: str,
        confidence: float,
        indicators: dict,
        description: str,
    ):
        self.phase = phase
        self.confidence = confidence
        self.indicators = indicators
        self.description = description

    @property
    def label(self) -> str:
        return PHASE_LABELS.get(self.phase, self.phase)

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "label": self.label,
            "confidence": self.confidence,
            "indicators": self.indicators,
            "description": self.description,
        }


class PhaseDetector:
    """
    市场阶段检测器。
    以沪深300为主要参考指数，综合均线趋势、波动率、距极值距离判断。
    """

    def __init__(self):
        self.fetcher = get_fetcher()

    def detect(self, index_name: str = "沪深300") -> MarketPhase:
        """
        检测当前市场阶段。

        Args:
            index_name: 参考指数名称

        Returns:
            MarketPhase 对象
        """
        try:
            # 尝试用 efinance 获取指数日K
            import efinance as ef
            df = ef.stock.get_quote_history(index_name, beg="20220101")
        except Exception:
            try:
                nav = self.fetcher.get_index_valuation(index_name)
                if nav is None:
                    return MarketPhase("unknown", 0, {}, "无法获取指数数据")
                # 用估值数据间接推断
                if "PE百分位" not in nav or nav.get("提示"):
                    return MarketPhase("unknown", 0, {}, f"指数 {index_name} 估值数据暂不可用")
                pe_pct = safe_float(nav["PE百分位"])
                if pe_pct < 20:
                    return MarketPhase("accumulation", 0.6, {"PE百分位": pe_pct}, "PE处于历史低位，可能处于筑底阶段")
                elif pe_pct > 80:
                    return MarketPhase("distribution", 0.6, {"PE百分位": pe_pct}, "PE处于历史高位，需警惕回调风险")
                else:
                    return MarketPhase("sideways", 0.5, {"PE百分位": pe_pct}, "PE处于历史中位，市场方向不明")
            except Exception:
                return MarketPhase("unknown", 0, {}, "获取指数数据失败")

        if df is None or df.empty:
            return MarketPhase("unknown", 0, {}, "指数数据为空")

        close = df["收盘"].astype(float)
        if len(close) < 120:
            return MarketPhase("unknown", 0, {}, "数据不足（需要至少120个交易日）")

        # 计算指标
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        returns = close.pct_change().dropna()

        # 趋势得分
        trend_score = self._compute_trend_score(close, ma20, ma60)
        # 波动率
        vol_20d = returns.tail(20).std() * np.sqrt(244)
        # 距52周高低点
        high_52w = close.tail(250).max()
        low_52w = close.tail(250).min()
        latest = close.iloc[-1]
        dist_from_high = (high_52w - latest) / high_52w
        dist_from_low = (latest - low_52w) / low_52w

        indicators = {
            "latest_close": round(float(latest), 2),
            "ma20": round(float(ma20.iloc[-1]), 2) if pd.notna(ma20.iloc[-1]) else None,
            "ma60": round(float(ma60.iloc[-1]), 2) if pd.notna(ma60.iloc[-1]) else None,
            "trend_score": round(trend_score, 2),
            "volatility_20d": round(float(vol_20d), 4),
            "dist_from_52w_high": round(float(dist_from_high), 4),
            "dist_from_52w_low": round(float(dist_from_low), 4),
            "data_date": str(df.iloc[-1].get("日期", "")),
        }

        # 判定阶段
        phase, confidence, description = self._classify(
            trend_score, vol_20d, dist_from_high, dist_from_low, indicators
        )

        return MarketPhase(phase, confidence, indicators, description)

    def _compute_trend_score(
        self,
        close: pd.Series,
        ma20: pd.Series,
        ma60: pd.Series,
    ) -> float:
        """
        计算趋势得分 [-1, 1]
        - 正值表示上升趋势，负值表示下降趋势
        """
        latest = close.iloc[-1]
        score = 0.0

        # MA20 vs MA60
        if pd.notna(ma20.iloc[-1]) and pd.notna(ma60.iloc[-1]):
            if ma20.iloc[-1] > ma60.iloc[-1]:
                score += 0.3
            else:
                score -= 0.3

        # 价格 vs MA20
        if pd.notna(ma20.iloc[-1]):
            if latest > ma20.iloc[-1]:
                score += 0.2
            else:
                score -= 0.2

        # MA20 斜率
        if len(ma20) >= 10:
            slope = (ma20.iloc[-1] - ma20.iloc[-10]) / ma20.iloc[-10]
            score += np.clip(slope * 2, -0.3, 0.3)

        # MA60 斜率
        if len(ma60) >= 20:
            slope = (ma60.iloc[-1] - ma60.iloc[-20]) / ma60.iloc[-20]
            score += np.clip(slope * 2, -0.2, 0.2)

        return max(-1.0, min(1.0, score))

    def _classify(
        self,
        trend_score: float,
        volatility: float,
        dist_from_high: float,
        dist_from_low: float,
        indicators: dict,
    ) -> tuple:
        """分类判断"""
        # 牛市：趋势强向上
        if trend_score > 0.4 and dist_from_high < 0.1:
            return "bull", 0.8, "MA20位于MA60上方，价格接近52周高点，趋势强劲向上"
        # 熊市：趋势强向下
        elif trend_score < -0.4 and dist_from_low < 0.1:
            return "bear", 0.8, "MA20位于MA60下方，价格接近52周低点，趋势明显向下"
        # 筑底：低位但趋势开始转正
        elif dist_from_low < 0.15 and trend_score > -0.2:
            return "accumulation", 0.65, "价格处于低位区域，趋势有企稳迹象"
        # 筑顶：高位但趋势开始转负
        elif dist_from_high < 0.1 and trend_score < 0.2:
            return "distribution", 0.65, "价格处于高位区域，趋势动能减弱"
        # 高波动
        elif volatility > 0.35:
            return "sideways", 0.55, f"波动率较高（{volatility:.1%}），市场分歧加大"
        # 默认震荡
        else:
            return "sideways", 0.5, "均线缠绕，趋势方向不明"

    def get_multi_timeframe(self, index_name: str = "沪深300") -> dict:
        """
        多时间维度评估（预留接口）。
        返回短期/中期/长期的阶段判断。
        """
        phase = self.detect(index_name)
        return {
            "primary": phase.to_dict(),
            "description": phase.description,
        }

    def format_for_llm(self, phase: MarketPhase = None, index_name: str = "沪深300") -> str:
        """
        格式化为可注入 AI prompt 的 Markdown 段落。

        示例输出:
            ## 当前市场阶段
            - **阶段**: 🐂 牛市 (置信度: 80%)
            - **趋势得分**: 0.65
            - **波动率(20日)**: 18.5%
            - **距52周高点**: 3.2%
            - **距52周低点**: 28.1%
            - **判断依据**: MA20位于MA60上方...
        """
        if phase is None:
            phase = self.detect(index_name)

        if phase.phase == "unknown":
            return f"## 当前市场阶段\n数据不足，无法判断 {index_name} 市场阶段。\n"

        ind = phase.indicators
        lines = [
            "## 当前市场阶段",
            f"- **阶段**: {phase.label} (置信度: {phase.confidence:.0%})",
            f"- **参考指数**: {index_name}",
        ]
        if ind.get("latest_close"):
            lines.append(f"- **最新收盘**: {ind['latest_close']:.2f}")
        if ind.get("trend_score") is not None:
            lines.append(f"- **趋势得分**: {ind['trend_score']:.2f} ([-1, 1])")
        if ind.get("volatility_20d"):
            lines.append(f"- **波动率(20日)**: {ind['volatility_20d']:.1%}")
        if ind.get("dist_from_52w_high") is not None:
            lines.append(f"- **距52周高点**: {ind['dist_from_52w_high']:.1%}")
        if ind.get("dist_from_52w_low") is not None:
            lines.append(f"- **距52周低点**: {ind['dist_from_52w_low']:.1%}")
        lines.append(f"- **判断依据**: {phase.description}")
        lines.append("")

        return "\n".join(lines)

    def get_recommended_strategies(self, phase: MarketPhase = None) -> List[str]:
        """
        根据市场阶段推荐策略。

        Returns:
            list: 策略名称列表
        """
        if phase is None:
            phase = self.detect()

        mapping = {
            "bull": ["value_screening", "growth_quality"],
            "bear": ["defensive_allocation", "bond_ladder"],
            "sideways": ["bond_ladder", "value_screening"],
            "accumulation": ["value_screening"],
            "distribution": ["defensive_allocation"],
        }
        return mapping.get(phase.phase, ["bond_ladder"])


# ============================================================
# 单例
# ============================================================

_phase_detector: Optional[PhaseDetector] = None


def get_phase_detector() -> PhaseDetector:
    """获取 PhaseDetector 全局单例"""
    global _phase_detector
    if _phase_detector is None:
        _phase_detector = PhaseDetector()
    return _phase_detector
