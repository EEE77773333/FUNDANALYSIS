"""
持仓穿透 & 行业暴露分析
======================
将基金持仓穿透到个股 → 映射申万一级行业 → 汇总行业暴露 →
对比基准 → 检测风格漂移。

使用方式:
    from core.holding_penetration import (
        map_stocks_to_sectors,
        calculate_sector_exposure,
        detect_style_drift,
        SECTOR_BENCHMARK_WEIGHTS,
    )
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

import pandas as pd
import numpy as np

from .data_fetcher import get_fetcher

logger = logging.getLogger(__name__)

# 缓存文件
_CACHE_DIR = Path(__file__).parent.parent / "data"
_CACHE_FILE = _CACHE_DIR / "stock_sector_map.json"

# 申万一级行业 → 沪深300基准权重（近似值，来源于中证指数公司 2024Q4）
SECTOR_BENCHMARK_WEIGHTS = {
    "银行": 13.5, "食品饮料": 12.8, "非银金融": 9.2, "电子": 8.5,
    "医药生物": 7.8, "电力设备": 7.5, "汽车": 5.2, "交通运输": 4.8,
    "公用事业": 3.9, "有色金属": 3.6, "家用电器": 3.4, "基础化工": 3.2,
    "机械设备": 3.0, "通信": 2.8, "计算机": 2.5, "国防军工": 2.2,
    "农林牧渔": 1.8, "传媒": 1.5, "建筑装饰": 1.2, "房地产": 1.0,
    "建筑材料": 0.8, "石油石化": 0.7, "钢铁": 0.6, "煤炭": 0.5,
    "商贸零售": 0.4, "社会服务": 0.3, "纺织服饰": 0.2, "环保": 0.1,
}


def _load_cache() -> dict:
    """加载本地股票→行业缓存"""
    if _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(data: dict):
    """保存股票→行业缓存"""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _fetch_full_stock_sector_map() -> Dict[str, str]:
    """
    从东方财富 API 获取全市场股票→行业映射（~5800只）。
    使用 _http_get 直连绕过代理。
    """
    from .data_fetcher import _http_get
    import json as _json

    result = {}
    page = 1
    max_pages = 60  # ~5800 stocks / 100 per page

    while page <= max_pages:
        url = (
            f"https://push2.eastmoney.com/api/qt/clist/get"
            f"?pn={page}&pz=100&po=1&np=1&fltt=2&invt=2"
            f"&fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
            f"&fields=f12,f14,f100"
        )
        try:
            text = _http_get(url, bypass_proxy=True)
            if not text:
                break
            data = _json.loads(text)
            items = data.get("data", {}).get("diff", [])
            if not items:
                break
            for item in items:
                name = str(item.get("f14", "")).strip()
                sector = str(item.get("f100", "")).strip()
                if name and sector and sector != "-" and sector != "nan":
                    # 提取申万一级行业: "电子 — 半导体" → "电子"
                    if " — " in sector:
                        sector = sector.split(" — ")[0].strip()
                    result[name] = sector
            page += 1
        except Exception:
            break

    return result


def map_stocks_to_sectors(stock_names: List[str], use_cache: bool = True) -> Dict[str, str]:
    """
    批量映射股票名称 → 申万一级行业。

    三层数据源:
        1. 内置静态映射表 (~300只最常见基金持仓股) — 即时
        2. 本地 JSON 缓存（过往 API 查询结果）
        3. 东方财富 API 全量拉取 — 后台补充

    Args:
        stock_names: 股票名称列表
        use_cache: 是否使用缓存

    Returns:
        {股票名称: 行业名称} 字典
    """
    from .stock_sectors import STOCK_SECTOR_MAP

    cache = _load_cache() if use_cache else {}
    result = {}
    uncached = []

    for name in stock_names:
        name = str(name).strip()
        if not name:
            continue
        # 优先静态映射表
        if name in STOCK_SECTOR_MAP:
            result[name] = STOCK_SECTOR_MAP[name]
        elif name in cache:
            result[name] = cache[name]
        else:
            uncached.append(name)

    if not uncached:
        return result

    # 尝试从东方财富 API 补充未命中项
    logger.info(f"静态映射未覆盖 {len(uncached)} 只股票，尝试 API 查询...")
    try:
        full_map = _fetch_full_stock_sector_map()
        if full_map:
            cache.update(full_map)
            _save_cache(cache)
            for name in uncached:
                result[name] = full_map.get(name, "其他")
            return result
    except Exception as e:
        logger.warning(f"API 查询失败: {e}")

    # API 不可用，未命中标记为"其他"
    for name in uncached:
        result[name] = "其他"
        cache[name] = "其他"
    _save_cache(cache)

    return result


def calculate_sector_exposure(
    holdings_list: List[pd.DataFrame],
    sector_map: Dict[str, str] = None,
) -> pd.DataFrame:
    """
    计算多期行业暴露矩阵。

    Args:
        holdings_list: 多个季度的持仓 DataFrame 列表，每项含 [股票名称, 占净值比例]
        sector_map: 预先计算的股票→行业映射（可选，自动获取）

    Returns:
        DataFrame: 行=季度, 列=行业, 值=该行业占净值比例之和
    """
    if not holdings_list:
        return pd.DataFrame()

    # 收集所有股票名称
    all_names = set()
    for df in holdings_list:
        if "股票名称" in df.columns:
            all_names.update(df["股票名称"].dropna().unique())

    # 获取行业映射
    if sector_map is None:
        sector_map = map_stocks_to_sectors(list(all_names))

    # 按季度汇总行业权重
    rows = []
    for df in holdings_list:
        if "股票名称" not in df.columns or "占净值比例" not in df.columns:
            continue
        quarter_label = str(df["季度"].iloc[0])[-8:] if "季度" in df.columns else "?"
        sector_weights: Dict[str, float] = defaultdict(float)
        for _, row in df.iterrows():
            name = str(row["股票名称"])
            weight = float(row["占净值比例"])
            sector = sector_map.get(name, "其他")
            sector_weights[sector] += weight
        sector_weights["季度"] = quarter_label
        rows.append(sector_weights)

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows).fillna(0).set_index("季度")
    # 列按总权重降序排列
    col_order = result.sum().sort_values(ascending=False).index.tolist()
    return result[col_order]


def calculate_sector_deviation(
    sector_exposure: pd.DataFrame,
    benchmark: Dict[str, float] = None,
) -> pd.DataFrame:
    """
    计算行业暴露相对于基准的超配/低配。

    Args:
        sector_exposure: calculate_sector_exposure 的输出
        benchmark: 基准行业权重字典

    Returns:
        DataFrame: 行=季度, 列=行业, 值=超配百分点（正值=超配）
    """
    if benchmark is None:
        benchmark = SECTOR_BENCHMARK_WEIGHTS

    if sector_exposure.empty:
        return pd.DataFrame()

    deviation = sector_exposure.copy()
    for sector in deviation.columns:
        bench_wt = benchmark.get(sector, 0)
        deviation[sector] = deviation[sector] - bench_wt

    return deviation


def detect_style_drift(
    holdings_list: List[pd.DataFrame],
    sector_map: Dict[str, str] = None,
) -> dict:
    """
    检测风格漂移。

    分析维度:
        1. 行业集中度趋势（HHI 变化）
        2. 持仓变化率（换手率代理指标）
        3. 漂移告警（行业权重偏离超过阈值）

    Returns:
        {
            "hhi_trend": [{"季度": "2024Q1", "HHI": 1250}, ...],
            "turnover_proxy": [{"季度": "2024Q1", "换手率%": 35}, ...],
            "drift_alerts": ["食品饮料大幅减仓 -8.2%", "电子大幅加仓 +5.1%"],
            "is_drifting": True,  # 是否存在显著漂移
            "drift_score": 0.65,  # 漂移程度 0-1
        }
    """
    if not holdings_list or len(holdings_list) < 2:
        return {"hhi_trend": [], "turnover_proxy": [], "drift_alerts": [], "is_drifting": False, "drift_score": 0}

    # 行业暴露
    exposure = calculate_sector_exposure(holdings_list, sector_map)
    if exposure.empty:
        return {"hhi_trend": [], "turnover_proxy": [], "drift_alerts": [], "is_drifting": False, "drift_score": 0}

    # 1. HHI 指数趋势（行业集中度）
    hhi_trend = []
    for quarter in exposure.index:
        weights = exposure.loc[quarter].values
        hhi = (weights ** 2).sum()
        hhi_trend.append({"季度": str(quarter), "HHI": round(float(hhi), 1)})

    # 2. 换手率代理（相邻季度持仓权重变化幅度的一半）
    turnover_proxy = []
    for i in range(1, len(exposure.index)):
        prev = exposure.iloc[i - 1].values
        curr = exposure.iloc[i].values
        # 补齐长度
        max_len = max(len(prev), len(curr))
        p = np.pad(prev, (0, max_len - len(prev)))
        c = np.pad(curr, (0, max_len - len(curr)))
        turnover = np.sum(np.abs(c - p)) / 2 * 100  # %
        turnover_proxy.append({
            "季度": str(exposure.index[i]),
            "换手率%": round(float(turnover), 1),
        })

    # 3. 漂移检测（最新vs最早的一期）
    first = exposure.iloc[0]
    last = exposure.iloc[-1]
    drift_alerts = []
    total_drift = 0
    for sector in exposure.columns:
        delta = last.get(sector, 0) - first.get(sector, 0)
        total_drift += abs(delta)
        if abs(delta) >= 5:  # 行业权重变化超过5个百分点
            direction = "加仓" if delta > 0 else "减仓"
            drift_alerts.append(f"{sector} 大幅{direction} {delta:+.1f}%")
        elif abs(delta) >= 3:
            direction = "加仓" if delta > 0 else "减仓"
            drift_alerts.append(f"{sector} {direction} {delta:+.1f}%")

    # 漂移评分
    drift_score = min(total_drift / 50, 1.0)  # 总漂移50个百分点=满分

    return {
        "hhi_trend": hhi_trend,
        "turnover_proxy": turnover_proxy,
        "drift_alerts": drift_alerts,
        "is_drifting": drift_score >= 0.4,
        "drift_score": round(drift_score, 2),
    }
