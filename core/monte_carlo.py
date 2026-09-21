"""
蒙特卡洛投资组合模拟器
======================
对组合未来 N 年做 M 次随机模拟，输出财富分布、成功概率、VaR/CVaR。

核心特性:
    - 乔列斯基分解生成相关随机收益率
    - Fan Chart（p10/p25/p50/p75/p90 分位线）
    - 终值分布直方图 + 达成概率
    - VaR / CVaR 计算
    - 压力测试（预设极端场景）
    - 年度再平衡模拟

使用方式:
    from core.monte_carlo import MonteCarloSimulator

    sim = MonteCarloSimulator(returns_df)
    result = sim.run(years=20, simulations=5000, initial=100000, monthly=2000)
"""

import logging
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SimulationParams:
    """模拟参数"""
    years: int = 20
    simulations: int = 5000
    initial_value: float = 100000
    monthly_contribution: float = 2000
    target_value: float = 1000000
    inflation_rate: float = 0.025
    rebalance: str = "annual"       # "none" | "annual" | "quarterly"
    withdrawal_rate: float = 0.0     # 每年提取比例（退休场景）


@dataclass
class SimulationResult:
    """模拟结果"""
    params: SimulationParams
    percentiles: Dict[str, list]     # {p10, p25, p50, p75, p90} 财富路径
    final_values: np.ndarray         # 终值分布 (simulations,)
    success_probability: float
    var_95: float
    cvar_95: float
    median_terminal: float
    mean_terminal: float
    bankruptcy_prob: float
    years_to_target_median: Optional[float]


class MonteCarloSimulator:
    """
    蒙特卡洛投资组合模拟器。

    方法:
        run()                    — 标准模拟
        run_with_stress()        — 含压力测试的模拟
        run_with_rebalancing()   — 含定期再平衡
    """

    def __init__(self, returns_df: pd.DataFrame = None, weights: Dict[str, float] = None):
        """
        Args:
            returns_df: 日收益率 DataFrame（列=基金代码，索引=日期）
            weights: 持仓权重 {基金代码: 权重}
        """
        self.returns_df = returns_df
        self.weights = weights or {}
        self._annual_returns = None
        self._annual_vol = None
        self._corr_matrix = None

    def _prepare(self):
        """计算年化统计量 + 协方差矩阵"""
        if self.returns_df is None or self.returns_df.empty:
            raise ValueError("未提供收益率数据")

        codes = list(self.returns_df.columns)

        # 权重向量
        if self.weights:
            w = np.array([self.weights.get(c, 0) for c in codes])
            if w.sum() == 0:
                w = np.ones(len(codes)) / len(codes)
            else:
                w = w / w.sum()
        else:
            w = np.ones(len(codes)) / len(codes)

        self._weights = w
        self._codes = codes

        # 年化收益率 + 协方差矩阵
        daily_mean = self.returns_df.mean().values
        daily_cov = self.returns_df.cov().values

        self._annual_returns = daily_mean * 252
        self._annual_cov = daily_cov * 252
        self._corr_matrix = self.returns_df.corr().values

        # 组合年化统计量
        self._port_return = np.dot(w, self._annual_returns)
        self._port_vol = np.sqrt(np.dot(w.T, np.dot(self._annual_cov, w)))

    def _cholesky_correlated(self, n_periods: int, n_sims: int) -> np.ndarray:
        """
        乔列斯基分解生成相关随机收益率矩阵。

        Returns:
            (n_periods, n_assets, n_sims) 三维数组
        """
        n_assets = len(self._codes)
        mean = self._annual_returns  # (n_assets,)

        # 乔列斯基分解
        try:
            L = np.linalg.cholesky(self._annual_cov)
        except np.linalg.LinAlgError:
            eigvals, eigvecs = np.linalg.eigh(self._annual_cov)
            eigvals = np.maximum(eigvals, 1e-10)
            self._annual_cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
            L = np.linalg.cholesky(self._annual_cov)

        # 生成独立标准正态随机数: (n_periods, n_assets, n_sims)
        Z = np.random.normal(0, 1, size=(n_periods, n_assets, n_sims))

        # 相关收益率: r[t, i, s] = μ[i] + Σⱼ L[i,j] · Z[t, j, s]
        # L: (n_assets, n_assets), Z: (n_periods, n_assets, n_sims)
        # L_ij · Z_tjs → sum over j → output (n_periods, n_assets, n_sims)
        correlated = np.empty((n_periods, n_assets, n_sims))
        for t in range(n_periods):
            correlated[t] = mean.reshape(-1, 1) + L @ Z[t]  # (n_assets, n_sims)

        return correlated

    def run(self, params: SimulationParams = None) -> SimulationResult:
        """
        执行蒙特卡洛模拟。

        Args:
            params: 模拟参数，None 则使用默认值

        Returns:
            SimulationResult 含完整模拟数据
        """
        if params is None:
            params = SimulationParams()

        self._prepare()
        n_assets = len(self._codes)
        n_periods = params.years  # 年频模拟
        n_sims = params.simulations

        # 生成相关年收益率
        annual_returns = self._cholesky_correlated(n_periods, n_sims)  # (years, assets, sims)

        # 组合年收益率: Σ(w_i × r_i[t, i, s])
        port_annual = np.tensordot(self._weights, annual_returns, axes=(0, 1))  # (years, sims)

        # 财富路径模拟
        # wealth[t] = wealth[t-1] * (1 + r_t) + annual_contribution
        annual_contribution = params.monthly_contribution * 12
        wealth = np.zeros((n_periods + 1, n_sims))
        wealth[0] = params.initial_value

        for t in range(n_periods):
            # 年度提取（退休场景）
            withdrawal = params.withdrawal_rate * wealth[t]
            wealth[t + 1] = wealth[t] * (1 + port_annual[t]) + annual_contribution - withdrawal
            wealth[t + 1] = np.maximum(wealth[t + 1], 0)  # 不允许负财富

        # 通胀调整
        inflation_factor = (1 + params.inflation_rate) ** np.arange(n_periods + 1)
        real_wealth = wealth / inflation_factor[:, np.newaxis]

        # 分位数路径（名义财富）
        pcts = [10, 25, 50, 75, 90]
        percentiles = {}
        for p in pcts:
            percentiles[f"p{p}"] = np.percentile(wealth, p, axis=1).tolist()

        # 终值统计
        final_values = wealth[-1]
        real_final = real_wealth[-1]

        # 破产概率（基于名义财富，通胀调整前）
        min_wealth = np.min(wealth, axis=0)
        bankruptcy_prob = np.mean(min_wealth <= params.initial_value * 0.1)

        # 成功概率（达到目标）
        success_prob = np.mean(final_values >= params.target_value)

        # VaR / CVaR (95%置信度)
        sorted_final = np.sort(final_values)
        var_idx = int(n_sims * 0.05)
        var_95 = sorted_final[var_idx] - params.initial_value
        cvar_95 = np.mean(sorted_final[:var_idx]) - params.initial_value

        # 达到目标所需年数（中位数估计）
        years_to_target = None
        for t in range(1, n_periods + 1):
            if np.median(wealth[t]) >= params.target_value:
                years_to_target = t
                break

        return SimulationResult(
            params=params,
            percentiles=percentiles,
            final_values=final_values,
            success_probability=round(float(success_prob), 4),
            var_95=round(float(var_95), 2),
            cvar_95=round(float(cvar_95), 2),
            median_terminal=round(float(np.median(final_values)), 2),
            mean_terminal=round(float(np.mean(final_values)), 2),
            bankruptcy_prob=round(float(bankruptcy_prob), 4),
            years_to_target_median=years_to_target,
        )

    def run_with_stress(self, params: SimulationParams = None) -> dict:
        """
        含压力测试的模拟。

        预设场景:
            - baseline:   正常模拟
            - crash:      第3年发生-40%股灾
            - inflation:  年化通胀 6%（正常2.5%）
            - stagflation: 股灾 + 高通胀叠加
            - lost_decade: 前5年年化收益减半

        Returns:
            {scenario_name: SimulationResult}
        """
        if params is None:
            params = SimulationParams()

        self._prepare()

        results = {}

        # ---- Baseline ----
        results["baseline"] = self.run(params)

        # ---- 股灾场景 ----
        crash_params = SimulationParams(
            **{**params.__dict__}
        )
        # 在第3年插入-40%冲击
        results["crash"] = self._run_with_shock(
            crash_params, shock_year=3, shock_pct=-0.40
        )

        # ---- 高通胀场景 ----
        inflation_params = SimulationParams(
            **{**params.__dict__, "inflation_rate": 0.06}
        )
        results["inflation"] = self.run(inflation_params)

        # ---- 滞胀场景 ----
        stag_params = SimulationParams(
            **{**params.__dict__, "inflation_rate": 0.06}
        )
        results["stagflation"] = self._run_with_shock(
            stag_params, shock_year=3, shock_pct=-0.40
        )

        # ---- 失去的十年 ----
        lost_params = SimulationParams(
            **{**params.__dict__}
        )
        results["lost_decade"] = self._run_with_low_returns(
            lost_params, low_years=5, return_multiplier=0.5
        )

        return results

    def _run_with_shock(self, params: SimulationParams, shock_year: int, shock_pct: float) -> SimulationResult:
        """在指定年份插入市场冲击"""
        n_periods = params.years
        n_sims = params.simulations
        annual_returns = self._cholesky_correlated(n_periods, n_sims)
        port_annual = np.tensordot(self._weights, annual_returns, axes=(0, 1))

        # 在 shock_year 插入冲击
        if shock_year < n_periods:
            port_annual[shock_year] = shock_pct

        annual_contribution = params.monthly_contribution * 12
        wealth = np.zeros((n_periods + 1, n_sims))
        wealth[0] = params.initial_value

        for t in range(n_periods):
            withdrawal = params.withdrawal_rate * wealth[t]
            wealth[t + 1] = wealth[t] * (1 + port_annual[t]) + annual_contribution - withdrawal
            wealth[t + 1] = np.maximum(wealth[t + 1], 0)

        # 破产概率 — 必须在通胀调整前计算（基于名义财富）
        min_wealth_nominal = np.min(wealth, axis=0)
        bankruptcy_p = np.mean(min_wealth_nominal <= params.initial_value * 0.1)

        inflation_factor = (1 + params.inflation_rate) ** np.arange(n_periods + 1)
        wealth = wealth / inflation_factor[:, np.newaxis]

        final_values = wealth[-1]
        pcts = [10, 25, 50, 75, 90]
        percentiles = {f"p{p}": np.percentile(wealth, p, axis=1).tolist() for p in pcts}

        sorted_final = np.sort(final_values)
        var_idx = int(n_sims * 0.05)

        return SimulationResult(
            params=params,
            percentiles=percentiles,
            final_values=final_values,
            success_probability=round(float(np.mean(final_values >= params.target_value)), 4),
            var_95=round(float(sorted_final[var_idx] - params.initial_value), 2),
            cvar_95=round(float(np.mean(sorted_final[:var_idx]) - params.initial_value), 2),
            median_terminal=round(float(np.median(final_values)), 2),
            mean_terminal=round(float(np.mean(final_values)), 2),
            bankruptcy_prob=round(float(bankruptcy_p), 4),
            years_to_target_median=None,
        )

    def _run_with_low_returns(self, params, low_years: int, return_multiplier: float) -> SimulationResult:
        """前N年收益率打折"""
        n_periods = params.years
        n_sims = params.simulations
        annual_returns = self._cholesky_correlated(n_periods, n_sims)
        port_annual = np.tensordot(self._weights, annual_returns, axes=(0, 1))

        # 前 low_years 年收益打折
        port_annual[:low_years] *= return_multiplier

        annual_contribution = params.monthly_contribution * 12
        wealth = np.zeros((n_periods + 1, n_sims))
        wealth[0] = params.initial_value

        for t in range(n_periods):
            withdrawal = params.withdrawal_rate * wealth[t]
            wealth[t + 1] = wealth[t] * (1 + port_annual[t]) + annual_contribution - withdrawal
            wealth[t + 1] = np.maximum(wealth[t + 1], 0)

        # 破产概率 — 必须在通胀调整前计算（基于名义财富）
        min_wealth_nominal = np.min(wealth, axis=0)
        bankruptcy_p = np.mean(min_wealth_nominal <= params.initial_value * 0.1)

        inflation_factor = (1 + params.inflation_rate) ** np.arange(n_periods + 1)
        wealth = wealth / inflation_factor[:, np.newaxis]

        final_values = wealth[-1]
        pcts = [10, 25, 50, 75, 90]
        percentiles = {f"p{p}": np.percentile(wealth, p, axis=1).tolist() for p in pcts}

        sorted_final = np.sort(final_values)
        var_idx = int(n_sims * 0.05)

        return SimulationResult(
            params=params,
            percentiles=percentiles,
            final_values=final_values,
            success_probability=round(float(np.mean(final_values >= params.target_value)), 4),
            var_95=round(float(sorted_final[var_idx] - params.initial_value), 2),
            cvar_95=round(float(np.mean(sorted_final[:var_idx]) - params.initial_value), 2),
            median_terminal=round(float(np.median(final_values)), 2),
            mean_terminal=round(float(np.mean(final_values)), 2),
            bankruptcy_prob=round(float(bankruptcy_p), 4),
            years_to_target_median=None,
        )

    def run_with_rebalancing(self, params: SimulationParams = None) -> SimulationResult:
        """
        含年度再平衡的模拟。

        每年末将组合权重调回目标配置。
        """
        if params is None:
            params = SimulationParams()

        self._prepare()
        n_assets = len(self._codes)
        n_periods = params.years
        n_sims = params.simulations

        # 单个资产的年收益率
        annual_returns = self._cholesky_correlated(n_periods, n_sims)  # (years, assets, sims)

        annual_contribution = params.monthly_contribution * 12
        wealth = np.zeros((n_periods + 1, n_sims))
        wealth[0] = params.initial_value

        # 每项资产的市值
        asset_values = np.zeros((n_periods + 1, n_assets, n_sims))
        asset_values[0] = params.initial_value * self._weights.reshape(-1, 1)

        for t in range(n_periods):
            # 资产增长
            for a in range(n_assets):
                asset_values[t + 1, a] = asset_values[t, a] * (1 + annual_returns[t, a])

            # 新投入按目标权重分配
            contribution = annual_contribution - params.withdrawal_rate * wealth[t]
            asset_values[t + 1] += contribution * self._weights.reshape(-1, 1)

            # 组合总财富
            wealth[t + 1] = asset_values[t + 1].sum(axis=0)
            wealth[t + 1] = np.maximum(wealth[t + 1], 0)

            # 再平衡
            if params.rebalance != "none" and t < n_periods - 1:
                for s in range(n_sims):
                    if wealth[t + 1, s] > 0:
                        target_values = wealth[t + 1, s] * self._weights
                        asset_values[t + 1, :, s] = target_values

        inflation_factor = (1 + params.inflation_rate) ** np.arange(n_periods + 1)
        real_wealth = wealth / inflation_factor[:, np.newaxis]

        final_values = wealth[-1]
        pcts = [10, 25, 50, 75, 90]
        percentiles = {f"p{p}": np.percentile(wealth, p, axis=1).tolist() for p in pcts}

        sorted_final = np.sort(final_values)
        var_idx = int(n_sims * 0.05)

        return SimulationResult(
            params=params,
            percentiles=percentiles,
            final_values=final_values,
            success_probability=round(float(np.mean(final_values >= params.target_value)), 4),
            var_95=round(float(sorted_final[var_idx] - params.initial_value), 2),
            cvar_95=round(float(np.mean(sorted_final[:var_idx]) - params.initial_value), 2),
            median_terminal=round(float(np.median(final_values)), 2),
            mean_terminal=round(float(np.mean(final_values)), 2),
            bankruptcy_prob=round(float(np.mean(np.min(wealth, axis=0) <= params.initial_value * 0.1)), 4),
            years_to_target_median=None,
        )
