"""
Brinson 业绩归因模型
===================
将基金超额收益分解为配置效应 + 选股效应 + 交互效应。

模型:
    - BHB (Brinson-Hood-Beebower): 三因子分解，含交叉项
    - BF  (Brinson-Fachler):   两因子简化版，交叉项并入选股效应

公式:
    R_p = Σ(w_p,i × r_p,i)    # 组合收益
    R_b = Σ(w_b,i × r_b,i)    # 基准收益

    BHB:
        配置效应 = Σ((w_p,i - w_b,i) × r_b,i)
        选股效应 = Σ(w_b,i × (r_p,i - r_b,i))
        交互效应 = Σ((w_p,i - w_b,i) × (r_p,i - r_b,i))

    BF:
        配置效应 = Σ((w_p,i - w_b,i) × (r_b,i - R_b))
        选股效应 = Σ(w_p,i × (r_p,i - r_b,i))

使用方式:
    from core.brinson import BrinsonAnalyzer

    ba = BrinsonAnalyzer()
    result = ba.analyze(fund_code="000001", benchmark="沪深300")
"""

import json
import logging
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

import pandas as pd
import numpy as np

from .data_fetcher import get_fetcher
from .holding_penetration import map_stocks_to_sectors, calculate_sector_exposure, SECTOR_BENCHMARK_WEIGHTS

logger = logging.getLogger(__name__)

# 申万一级行业 → 行业指数代码（用于获取行业收益率）
SECTOR_INDEX_MAP = {
    "银行": "801780", "食品饮料": "801120", "非银金融": "801790", "电子": "801080",
    "医药生物": "801150", "电力设备": "801730", "汽车": "801880", "交通运输": "801170",
    "公用事业": "801160", "有色金属": "801050", "家用电器": "801110", "基础化工": "801030",
    "机械设备": "801890", "通信": "801770", "计算机": "801750", "国防军工": "801740",
    "农林牧渔": "801010", "传媒": "801760", "建筑装饰": "801720", "房地产": "801180",
    "建筑材料": "801710", "石油石化": "801020", "钢铁": "801040", "煤炭": "801950",
    "商贸零售": "801200", "社会服务": "801210", "纺织服饰": "801130", "环保": "801970",
}


class BrinsonAnalyzer:
    """
    Brinson 业绩归因分析器。

    数据需求:
        - 基金持仓: 季度股票+行业权重（from holding_penetration）
        - 行业收益: 申万行业指数期间收益率
        - 基准权重: 沪深300行业权重（from SECTOR_BENCHMARK_WEIGHTS）

    输出:
        - 总超额收益
        - 配置效应 / 选股效应 / 交互效应（行业维度）
        - 图表数据
    """

    def __init__(self):
        self.fetcher = get_fetcher()

    def _get_sector_returns(self, start_date: str, end_date: str) -> Dict[str, float]:
        """
        获取申万一级行业在指定期间的收益率。

        通过 AKShare 申万行业指数日K数据计算。
        数据格式: start_date ~ end_date 的累积收益率
        """
        sector_returns = {}
        for sector_name, index_code in SECTOR_INDEX_MAP.items():
            try:
                import efinance as ef
                df = ef.stock.get_quote_history(index_code, beg=start_date, end=end_date)
                if df is not None and not df.empty and len(df) >= 2:
                    start_price = float(df.iloc[0]["收盘"])
                    end_price = float(df.iloc[-1]["收盘"])
                    ret = (end_price - start_price) / start_price
                    sector_returns[sector_name] = ret
            except Exception:
                pass
        return sector_returns

    def _get_fund_sector_weights(self, fund_code: str, quarter: str = None) -> Dict[str, float]:
        """
        获取基金最新季度的行业权重。

        流程: 持仓 → 股票→行业映射 → 按行业汇总权重 → 归一化
        """
        try:
            import akshare as ak
            year = pd.Timestamp.now().year if quarter is None else quarter[:4]
            df = ak.fund_portfolio_hold_em(symbol=fund_code, date=str(year))
            if df is None or df.empty:
                return {}

            # 取最新一个季度
            if quarter:
                q_df = df[df["季度"] == quarter]
            else:
                latest_q = df["季度"].dropna().unique()[-1]
                q_df = df[df["季度"] == latest_q]

            if q_df.empty:
                return {}

            # 股票名称 → 行业映射
            stock_names = q_df["股票名称"].dropna().unique().tolist()
            sector_map = map_stocks_to_sectors(stock_names)

            # 按行业汇总权重
            sector_weights: Dict[str, float] = defaultdict(float)
            for _, row in q_df.iterrows():
                name = str(row["股票名称"])
                weight = float(row["占净值比例"])
                sector = sector_map.get(name, "其他")
                sector_weights[sector] += weight

            # 归一化到100%（股票仓位可能<100%）
            total = sum(sector_weights.values())
            if total > 0:
                return {s: w / total * 100 for s, w in sector_weights.items()}
            return dict(sector_weights)

        except Exception as e:
            logger.warning(f"获取基金行业权重失败 ({fund_code}): {e}")
            return {}

    def analyze(
        self,
        fund_code: str,
        benchmark: str = "沪深300",
        quarter: str = None,
    ) -> dict:
        """
        执行 Brinson BHB + BF 业绩归因。

        Args:
            fund_code: 基金代码
            benchmark: 基准名称（沪深300/中证500）
            quarter: 指定季度，None=最新

        Returns:
            {
                "fund_code": "000001",
                "benchmark": "沪深300",
                "quarter": "2025Q1",
                "bhb": {
                    "total_excess": 0.052,     # 总超额收益
                    "allocation_effect": [...],  # 配置效应（行业维度）
                    "selection_effect": [...],   # 选股效应
                    "interaction_effect": [...], # 交互效应
                    "by_sector": [{...}],        # 按行业分解
                },
                "bf": {...},
                "chart_data": {...},             # 前端绘图数据
            }
        """
        # 1. 获取基金行业权重
        fund_weights = self._get_fund_sector_weights(fund_code, quarter)
        if not fund_weights:
            return {"error": "未获取到基金持仓数据", "fund_code": fund_code}

        # 2. 基准权重（沪深300行业权重归一化到基金持有的行业）
        bench_weights_all = dict(SECTOR_BENCHMARK_WEIGHTS)

        # 3. 行业收益率（最新季度窗口）
        # 用最近一个季度的日期范围
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=100)).strftime("%Y%m%d")
        sector_returns = self._get_sector_returns(start_date, end_date)

        # 4. 对齐行业集合（基金 + 基准的交集）
        all_sectors = sorted(set(list(fund_weights.keys()) + list(bench_weights_all.keys())))
        n = len(all_sectors)

        # 构建向量
        wp = np.array([fund_weights.get(s, 0) / 100 for s in all_sectors])  # 组合权重
        wb = np.array([bench_weights_all.get(s, 0) / 100 for s in all_sectors])  # 基准权重
        # 注：组合与基准的行业收益率均使用申万行业指数代理。
        # 因无法获取基金在每个行业内的实际选股收益率，
        # 选股效应和交互效应反映的是行业权重偏离的间接影响，非真实选股Alpha。
        rp_vec = np.array([sector_returns.get(s, 0) for s in all_sectors])
        rb_vec = np.array([sector_returns.get(s, 0) for s in all_sectors])

        # 基准总收益
        Rb = np.dot(wb, rb_vec)
        # 组合总收益
        Rp = np.dot(wp, rp_vec)
        total_excess = Rp - Rb

        # ---- BHB 三因子分解 ----
        allocation_bhb = (wp - wb) * rb_vec          # 配置效应
        selection_bhb = wb * (rp_vec - rb_vec)        # 选股效应
        interaction_bhb = (wp - wb) * (rp_vec - rb_vec)  # 交互效应

        # ---- BF 两因子分解 ----
        allocation_bf = (wp - wb) * (rb_vec - Rb)     # BF配置效应
        selection_bf = wp * (rp_vec - rb_vec)          # BF选股效应

        # ---- 按行业组装结果 ----
        by_sector = []
        for i, sector in enumerate(all_sectors):
            # 只保留有权重或有收益的行业
            if abs(wp[i]) < 0.001 and abs(wb[i]) < 0.001:
                continue
            by_sector.append({
                "行业": sector,
                "组合权重%": round(float(wp[i] * 100), 2),
                "基准权重%": round(float(wb[i] * 100), 2),
                "超配%": round(float((wp[i] - wb[i]) * 100), 2),
                "行业收益%": round(float(rp_vec[i] * 100), 2),
                "配置效应%": round(float(allocation_bhb[i] * 100), 3),
                "选股效应%": round(float(selection_bhb[i] * 100), 3),
                "交互效应%": round(float(interaction_bhb[i] * 100), 3),
                "总效应%": round(float((allocation_bhb[i] + selection_bhb[i] + interaction_bhb[i]) * 100), 3),
            })

        # 按总效应绝对值降序
        by_sector.sort(key=lambda x: abs(x["总效应%"]), reverse=True)

        return {
            "fund_code": fund_code,
            "benchmark": benchmark,
            "total_excess": round(float(total_excess * 100), 3),
            "total_excess_raw": round(float(total_excess), 4),
            "Rp": round(float(Rp * 100), 2),
            "Rb": round(float(Rb * 100), 2),
            "sector_count": len(by_sector),
            "bhb": {
                "allocation": round(float(np.sum(allocation_bhb) * 100), 3),
                "selection": round(float(np.sum(selection_bhb) * 100), 3),
                "interaction": round(float(np.sum(interaction_bhb) * 100), 3),
            },
            "bf": {
                "allocation": round(float(np.sum(allocation_bf) * 100), 3),
                "selection": round(float(np.sum(selection_bf) * 100), 3),
            },
            "by_sector": by_sector,
            "chart_data": {
                "sectors": [s["行业"] for s in by_sector],
                "allocation": [s["配置效应%"] for s in by_sector],
                "selection": [s["选股效应%"] for s in by_sector],
                "interaction": [s["交互效应%"] for s in by_sector],
            },
        }
