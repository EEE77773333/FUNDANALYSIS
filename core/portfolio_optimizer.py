"""
马科维茨均值-方差优化器
======================
基于组合基金的历史收益率，通过 scipy.optimize 求解最优配置权重。

优化目标:
    - max_sharpe:        最大化 Sharpe ratio
    - min_volatility:    最小化波动率
    - efficient_frontier: 生成有效前沿曲线
    - risk_parity:       风险平价（等风险贡献）

使用方式:
    from core.portfolio_optimizer import PortfolioOptimizer

    po = PortfolioOptimizer()
    result = po.optimize_max_sharpe(returns_df)
    curve = po.efficient_frontier(returns_df, points=50)
"""

import logging
from typing import Optional, Dict, List, Tuple

import pandas as pd
import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


class PortfolioOptimizer:
    """马科维茨均值-方差优化器"""

    def __init__(self, risk_free_rate: float = 0.025):
        self.rf = risk_free_rate

    # ---- 内部计算 ----

    @staticmethod
    def _portfolio_stats(weights, returns_df):
        """计算给定权重的组合统计量"""
        w = np.array(weights)
        # 年化收益（假设日收益率）
        mean_returns = returns_df.mean()
        cov = returns_df.cov()

        port_return = np.dot(w, mean_returns)
        port_vol = np.sqrt(np.dot(w.T, np.dot(cov, w)))

        # 年化（252交易日）
        ann_return = port_return * 252
        ann_vol = port_vol * np.sqrt(252)

        return ann_return, ann_vol

    @staticmethod
    def _sharpe_ratio(weights, returns_df, rf=0.025):
        """Sharpe ratio（负值 → 最小化 = 最大化 Sharpe）"""
        ret, vol = PortfolioOptimizer._portfolio_stats(weights, returns_df)
        if vol == 0:
            return 0
        return -(ret - rf) / vol  # 取负号用于最小化

    @staticmethod
    def _portfolio_volatility(weights, returns_df):
        """组合波动率"""
        _, vol = PortfolioOptimizer._portfolio_stats(weights, returns_df)
        return vol

    def _risk_contribution(self, weights, returns_df):
        """计算每个资产的风险贡献"""
        w = np.array(weights)
        cov = returns_df.cov()
        port_vol = np.sqrt(np.dot(w.T, np.dot(cov, w)))

        # 边际风险贡献
        mrc = np.dot(cov, w) / port_vol
        # 各资产风险贡献
        rc = w * mrc
        # 风险贡献比例
        rc_pct = rc / rc.sum()
        return rc, rc_pct

    def _risk_parity_objective(self, weights, returns_df):
        """风险平价目标函数：最小化风险贡献的方差"""
        _, rc_pct = self._risk_contribution(weights, returns_df)
        n = len(weights)
        target = 1.0 / n
        return np.sum((rc_pct - target) ** 2)

    # ---- 权重约束 ----

    def _constraints(self, n):
        """权重约束：和为1"""
        return {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}

    def _bounds(self, n, min_weight=0.0, max_weight=1.0):
        """权重边界：每只基金0-100%"""
        return tuple((min_weight, max_weight) for _ in range(n))

    # ---- 优化方法 ----

    def optimize_max_sharpe(
        self,
        returns_df: pd.DataFrame,
        min_weight: float = 0.0,
        max_weight: float = 0.5,
    ) -> dict:
        """
        最大化 Sharpe ratio。

        Returns:
            {
                "weights": {"000001": 0.30, ...},
                "annualized_return": 0.12,
                "annualized_volatility": 0.15,
                "sharpe_ratio": 0.63,
            }
        """
        n = len(returns_df.columns)
        initial_guess = np.ones(n) / n

        result = minimize(
            self._sharpe_ratio,
            initial_guess,
            args=(returns_df, self.rf),
            method="SLSQP",
            bounds=self._bounds(n, min_weight, max_weight),
            constraints=self._constraints(n),
        )

        if result.success:
            ret, vol = self._portfolio_stats(result.x, returns_df)
            weights = {returns_df.columns[i]: round(float(result.x[i]), 4)
                       for i in range(n) if result.x[i] > 0.001}
            return {
                "weights": weights,
                "annualized_return": round(float(ret), 4),
                "annualized_volatility": round(float(vol), 4),
                "sharpe_ratio": round(float((ret - self.rf) / vol) if vol > 0 else 0, 4),
                "success": True,
            }
        else:
            return {"success": False, "error": result.message}

    def optimize_min_volatility(
        self,
        returns_df: pd.DataFrame,
        min_weight: float = 0.0,
        max_weight: float = 0.5,
    ) -> dict:
        """最小化波动率"""
        n = len(returns_df.columns)
        initial_guess = np.ones(n) / n

        result = minimize(
            self._portfolio_volatility,
            initial_guess,
            args=(returns_df,),
            method="SLSQP",
            bounds=self._bounds(n, min_weight, max_weight),
            constraints=self._constraints(n),
        )

        if result.success:
            ret, vol = self._portfolio_stats(result.x, returns_df)
            weights = {returns_df.columns[i]: round(float(result.x[i]), 4)
                       for i in range(n) if result.x[i] > 0.001}
            return {
                "weights": weights,
                "annualized_return": round(float(ret), 4),
                "annualized_volatility": round(float(vol), 4),
                "sharpe_ratio": round(float((ret - self.rf) / vol) if vol > 0 else 0, 4),
                "success": True,
            }
        else:
            return {"success": False, "error": result.message}

    def optimize_risk_parity(
        self,
        returns_df: pd.DataFrame,
        min_weight: float = 0.0,
        max_weight: float = 0.5,
    ) -> dict:
        """风险平价（等风险贡献）"""
        n = len(returns_df.columns)
        initial_guess = np.ones(n) / n

        result = minimize(
            self._risk_parity_objective,
            initial_guess,
            args=(returns_df,),
            method="SLSQP",
            bounds=self._bounds(n, min_weight, max_weight),
            constraints=self._constraints(n),
        )

        if result.success:
            ret, vol = self._portfolio_stats(result.x, returns_df)
            weights = {returns_df.columns[i]: round(float(result.x[i]), 4)
                       for i in range(n) if result.x[i] > 0.001}
            return {
                "weights": weights,
                "annualized_return": round(float(ret), 4),
                "annualized_volatility": round(float(vol), 4),
                "sharpe_ratio": round(float((ret - self.rf) / vol) if vol > 0 else 0, 4),
                "success": True,
            }
        else:
            return {"success": False, "error": result.message}

    def efficient_frontier(
        self,
        returns_df: pd.DataFrame,
        points: int = 50,
        min_weight: float = 0.0,
    ) -> dict:
        """
        生成有效前沿曲线数据。

        方法：对目标收益率从最低到最高采样，对每个点求解最小波动率。

        Returns:
            {
                "frontier": [{"return": 0.05, "volatility": 0.12, "weights": {...}}, ...],
                "max_sharpe": {...},
                "min_volatility": {...},
            }
        """
        n = len(returns_df.columns)

        # 先找最小波动和最大收益的边界
        min_vol_result = self.optimize_min_volatility(returns_df, min_weight=min_weight)
        max_sharpe_result = self.optimize_max_sharpe(returns_df, min_weight=min_weight)

        if not min_vol_result.get("success") or not max_sharpe_result.get("success"):
            return {"frontier": [], "error": "优化失败"}

        # 收益率范围
        min_ret = min_vol_result["annualized_return"]
        max_ret = returns_df.mean().max() * 252  # 最高单资产年化收益

        frontier = []
        # 范围从 min_ret 以下扩展到 max_ret 以上，正确处理负收益率
        ret_low = min(min_ret * 1.05, min_ret * 0.95)
        ret_high = max(max_ret * 1.05, max_ret * 0.95)
        for target_ret in np.linspace(ret_low, ret_high, points):
            constraints = [
                {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
                {"type": "eq", "fun": lambda w, r=target_ret:
                    PortfolioOptimizer._portfolio_stats(w, returns_df)[0] - r},
            ]

            result = minimize(
                self._portfolio_volatility,
                np.ones(n) / n,
                args=(returns_df,),
                method="SLSQP",
                bounds=self._bounds(n, min_weight, 0.5),
                constraints=constraints,
            )

            if result.success:
                ret, vol = self._portfolio_stats(result.x, returns_df)
                frontier.append({
                    "return": round(float(ret), 4),
                    "volatility": round(float(vol), 4),
                })

        # 确保有效前沿单调（去除被支配的点）
        frontier.sort(key=lambda p: p["volatility"])
        valid = []
        max_ret_so_far = -999
        for p in frontier:
            if p["return"] > max_ret_so_far:
                valid.append(p)
                max_ret_so_far = p["return"]

        return {
            "frontier": valid,
            "max_sharpe": {
                "return": max_sharpe_result["annualized_return"],
                "volatility": max_sharpe_result["annualized_volatility"],
                "sharpe": max_sharpe_result["sharpe_ratio"],
            },
            "min_volatility": {
                "return": min_vol_result["annualized_return"],
                "volatility": min_vol_result["annualized_volatility"],
            },
        }

    def compare_allocations(
        self,
        returns_df: pd.DataFrame,
        current_weights: Dict[str, float],
        min_weight: float = 0.0,
    ) -> dict:
        """
        对比当前配置 vs 三种优化配置。

        Returns:
            {
                "current": {stats},
                "max_sharpe": {stats},
                "min_volatility": {stats},
                "risk_parity": {stats},
            }
        """
        n = len(returns_df.columns)
        codes = returns_df.columns.tolist()

        # 当前配置的统计量
        w_current = np.array([current_weights.get(c, 0) for c in codes])
        if w_current.sum() == 0:
            w_current = np.ones(n) / n
        else:
            w_current = w_current / w_current.sum()
        ret_c, vol_c = self._portfolio_stats(w_current, returns_df)
        current = {
            "weights": {c: round(float(w_current[i]), 4) for i, c in enumerate(codes)},
            "annualized_return": round(float(ret_c), 4),
            "annualized_volatility": round(float(vol_c), 4),
            "sharpe_ratio": round(float((ret_c - self.rf) / vol_c) if vol_c > 0 else 0, 4),
        }

        max_sharpe = self.optimize_max_sharpe(returns_df, min_weight=min_weight)
        min_vol = self.optimize_min_volatility(returns_df, min_weight=min_weight)
        risk_parity = self.optimize_risk_parity(returns_df, min_weight=min_weight)

        return {
            "current": current,
            "max_sharpe": max_sharpe,
            "min_volatility": min_vol,
            "risk_parity": risk_parity,
        }
