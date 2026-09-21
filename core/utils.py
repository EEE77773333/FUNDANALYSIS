"""
工具函数
========
提供缓存装饰器、金融指标计算、数据格式化等通用工具。
"""

import time
import hashlib
import json
from datetime import datetime
from functools import wraps, lru_cache
from typing import Any, Dict, Optional, Callable

import numpy as np
import pandas as pd


# ============================================================
# 数值安全转换
# ============================================================


def safe_float(value: Any, default: float = 0.0) -> float:
    """安全转换为 float，失败时返回默认值。"""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """安全转换为 int，失败时返回默认值。"""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# ============================================================
# 格式化
# ============================================================


def fmt_pct(value: float, decimals: int = 2) -> str:
    """格式化百分比。

    Examples:
        fmt_pct(0.1523)  -> '+15.23%'
        fmt_pct(-0.052)  -> '-5.20%'
    """
    if value is None or np.isnan(value):
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.{decimals}f}%"


def fmt_money(value: float, unit: str = "亿") -> str:
    """格式化金额。

    Examples:
        fmt_money(123456789) -> '1.23亿'
        fmt_money(50000000, '万') -> '5000.00万'
    """
    if value is None:
        return "N/A"
    if unit == "亿":
        return f"{value / 1e8:.2f}亿"
    elif unit == "万":
        return f"{value / 1e4:.2f}万"
    else:
        return f"{value:,.2f}"


def fmt_date(date_str: str, fmt: str = "%Y-%m-%d") -> str:
    """标准化日期格式。"""
    if not date_str:
        return ""
    try:
        dt = pd.to_datetime(date_str)
        return dt.strftime(fmt)
    except (ValueError, TypeError):
        return str(date_str)


# ============================================================
# 金融指标计算
# ============================================================


def calc_annualized_return(
    nav_series: pd.Series, trading_days: int = 244
) -> float:
    """
    计算年化收益率。

    Args:
        nav_series: 单位净值序列（按日期升序）
        trading_days: 年交易日数（A股约244天，基金约252天）

    Returns:
        年化收益率（小数形式，如 0.15 表示 15%）
    """
    if len(nav_series) < 2:
        return 0.0

    total_return = (nav_series.iloc[-1] / nav_series.iloc[0]) - 1
    years = len(nav_series) / trading_days
    if years <= 0:
        return 0.0

    annualized = (1 + total_return) ** (1 / years) - 1
    return annualized


def calc_annual_volatility(
    returns: pd.Series, trading_days: int = 244
) -> float:
    """
    计算年化波动率。

    Args:
        returns: 日收益率序列
        trading_days: 年交易日数

    Returns:
        年化波动率（小数形式）
    """
    if len(returns) < 2:
        return 0.0
    daily_std = returns.std()
    return daily_std * np.sqrt(trading_days)


def calc_max_drawdown(nav_series: pd.Series) -> float:
    """
    计算最大回撤。

    Args:
        nav_series: 单位净值序列

    Returns:
        最大回撤（负数形式，如 -0.20 表示最大回撤 20%）
    """
    if len(nav_series) < 2:
        return 0.0

    cumulative_max = nav_series.cummax()
    drawdowns = (nav_series - cumulative_max) / cumulative_max
    return float(drawdowns.min())


def calc_sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.025,
    trading_days: int = 244,
) -> float:
    """
    计算夏普比率。

    Args:
        returns: 日收益率序列
        risk_free_rate: 无风险利率（默认 2.5%，约等于10年期国债收益率）
        trading_days: 年交易日数

    Returns:
        夏普比率
    """
    if len(returns) < 2:
        return 0.0

    daily_rf = risk_free_rate / trading_days
    excess_returns = returns - daily_rf

    if excess_returns.std() == 0:
        return 0.0

    return float(
        excess_returns.mean() / excess_returns.std() * np.sqrt(trading_days)
    )


def calc_calmar_ratio(
    nav_series: pd.Series, returns: pd.Series
) -> float:
    """
    计算卡尔玛比率（年化收益率 / |最大回撤|）。

    用于衡量每单位最大回撤能带来的收益，值越高越好。
    """
    annual_return = calc_annualized_return(nav_series)
    max_dd = abs(calc_max_drawdown(nav_series))

    if max_dd == 0:
        return 0.0

    return annual_return / max_dd


def calc_sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.025,
    trading_days: int = 244,
) -> float:
    """
    计算索提诺比率（只惩罚下行波动）。

    夏普比率惩罚所有波动，索提诺只惩罚下跌波动，更适合评估追求正收益的基金。
    """
    if len(returns) < 2:
        return 0.0

    daily_rf = risk_free_rate / trading_days
    excess_returns = returns - daily_rf
    downside_returns = excess_returns[excess_returns < 0]

    if len(downside_returns) < 2 or downside_returns.std() == 0:
        return 0.0

    downside_std = downside_returns.std() * np.sqrt(trading_days)
    annual_excess = excess_returns.mean() * trading_days

    return float(annual_excess / downside_std) if downside_std != 0 else 0.0


def calc_win_rate(returns: pd.Series) -> float:
    """计算胜率（正收益天数占比）。"""
    if len(returns) == 0:
        return 0.0
    return float((returns > 0).sum() / len(returns))


def calc_beta(
    fund_returns: pd.Series, benchmark_returns: pd.Series
) -> float:
    """
    计算 Beta 系数（相对基准的系统性风险）。

    Beta > 1: 比基准波动更大（进攻型）
    Beta < 1: 比基准更稳健（防守型）
    """
    if len(fund_returns) < 2 or len(benchmark_returns) < 2:
        return 1.0

    # 对齐长度
    min_len = min(len(fund_returns), len(benchmark_returns))
    f = fund_returns.iloc[-min_len:]
    b = benchmark_returns.iloc[-min_len:]

    cov = np.cov(f, b)[0][1]
    var = np.var(b)

    return float(cov / var) if var != 0 else 1.0


def calc_alpha(
    fund_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = 0.025,
    trading_days: int = 244,
) -> float:
    """
    计算 Jensen's Alpha（超额收益）。

    Alpha > 0: 基金跑赢基准（基金经理有选股/择时能力）
    Alpha < 0: 基金跑输基准
    """
    beta = calc_beta(fund_returns, benchmark_returns)
    fund_annual = fund_returns.mean() * trading_days
    benchmark_annual = benchmark_returns.mean() * trading_days

    # CAPM: E(Rf) = Rf + Beta * (E(Rm) - Rf)
    expected_return = risk_free_rate + beta * (benchmark_annual - risk_free_rate)

    return float(fund_annual - expected_return)


def calc_all_metrics(
    nav_series: pd.Series,
    benchmark_nav: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """
    一次性计算所有常用基金评价指标。

    Args:
        nav_series: 基金净值序列（按日期升序）
        benchmark_nav: 基准净值序列（可选，用于计算 Alpha/Beta）

    Returns:
        dict: 包含所有指标的字典
    """
    if nav_series.empty or len(nav_series) < 20:
        return {"错误": "数据不足，至少需要20个交易日的数据"}

    returns = nav_series.pct_change().dropna()
    nav_clean = nav_series.dropna()

    metrics = {
        "年化收益率": round(calc_annualized_return(nav_clean), 4),
        "年化波动率": round(calc_annual_volatility(returns), 4),
        "最大回撤": round(calc_max_drawdown(nav_clean), 4),
        "夏普比率": round(calc_sharpe_ratio(returns), 2),
        "索提诺比率": round(calc_sortino_ratio(returns), 2),
        "卡尔玛比率": round(calc_calmar_ratio(nav_clean, returns), 2),
        "胜率": round(calc_win_rate(returns), 4),
        "最新净值": round(nav_clean.iloc[-1], 4),
        "数据天数": len(nav_clean),
    }

    if benchmark_nav is not None and len(benchmark_nav) >= len(nav_clean):
        bench_returns = benchmark_nav.pct_change().dropna()
        metrics["Beta"] = round(calc_beta(returns, bench_returns), 2)
        metrics["Alpha"] = round(
            calc_alpha(returns, bench_returns), 4
        )

    return metrics


# ============================================================
# 缓存工具
# ============================================================


def timed_cache(ttl: int = 300, maxsize: int = 128):
    """
    带 TTL（Time-To-Live）的内存缓存装饰器。

    与 @lru_cache 不同，此装饰器会定期刷新缓存，避免返回过期数据。

    Args:
        ttl: 缓存生存时间（秒）
        maxsize: 最大缓存条目数

    Usage:
        @timed_cache(ttl=600, maxsize=64)
        def get_expensive_data(param):
            ...
    """

    def decorator(func: Callable):
        cache: Dict[str, tuple] = {}  # {key: (timestamp, result)}

        @wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            key_parts = [func.__name__]
            key_parts.extend(str(a) for a in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = hashlib.md5("|".join(key_parts).encode()).hexdigest()

            now = time.time()

            # 检查缓存
            if cache_key in cache:
                ts, result = cache[cache_key]
                if now - ts < ttl:
                    return result

            # 执行函数并缓存
            result = func(*args, **kwargs)
            cache[cache_key] = (now, result)

            # LRU 淘汰
            if len(cache) > maxsize:
                oldest_key = min(cache.items(), key=lambda x: x[1][0])[0]
                del cache[oldest_key]

            return result

        # 暴露缓存管理方法
        wrapper._cache = cache  # type: ignore
        wrapper.clear_cache = lambda: cache.clear()  # type: ignore

        return wrapper

    return decorator


def log_call(func: Callable) -> Callable:
    """记录函数调用日志的装饰器（用于调试）。"""
    import logging

    logger = logging.getLogger(func.__module__)

    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start
            logger.debug(
                f"{func.__name__} 完成 — 耗时 {elapsed:.2f}s"
            )
            return result
        except Exception as e:
            elapsed = time.time() - start
            logger.error(
                f"{func.__name__} 失败 — 耗时 {elapsed:.2f}s — {e}"
            )
            raise

    return wrapper


# ============================================================
# 数据类型判断
# ============================================================


def classify_fund_risk(fund_type: str) -> str:
    """
    根据基金类型返回风险等级。

    Returns:
        '低风险' | '中低风险' | '中风险' | '中高风险' | '高风险'
    """
    fund_type_lower = fund_type.lower() if fund_type else ""

    if any(kw in fund_type_lower for kw in ["货币", "货币型", "短债"]):
        return "低风险"
    elif any(kw in fund_type_lower for kw in ["债券", "债基", "纯债"]):
        return "中低风险"
    elif any(kw in fund_type_lower for kw in ["混合", "平衡"]):
        return "中风险"
    elif any(kw in fund_type_lower for kw in ["指数", "etf"]):
        return "中高风险"
    elif any(kw in fund_type_lower for kw in ["股票", "qdii", "海外"]):
        return "高风险"
    else:
        return "中风险"


def classify_fund_style(holdings_df: pd.DataFrame) -> str:
    """
    根据持仓特征判断基金投资风格。

    Returns:
        '大盘成长' | '大盘价值' | '中盘成长' | '中盘价值' |
        '小盘成长' | '小盘价值' | '均衡' | '无法判断'
    """
    if holdings_df is None or holdings_df.empty:
        return "无法判断"

    # 基于前十大重仓股集中度判断
    concentration = holdings_df["占净值比例%"].sum() if "占净值比例%" in holdings_df.columns else 0

    # 简化版风格判断（完整版需要个股的市值和估值数据）
    if concentration > 60:
        style = "集中持有"
    elif concentration > 40:
        style = "适度集中"
    else:
        style = "分散持有"

    return style


# ============================================================
# JSON 序列化辅助
# ============================================================


class NumpyEncoder(json.JSONEncoder):
    """处理 numpy 类型的 JSON 编码器。"""

    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Timestamp):
            return obj.strftime("%Y-%m-%d")
        if isinstance(obj, datetime):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        return super().default(obj)


def df_to_dict(df: pd.DataFrame) -> list:
    """将 DataFrame 转换为可 JSON 序列化的字典列表。"""
    if df is None or df.empty:
        return []
    return json.loads(df.to_json(orient="records", force_ascii=False))


def safe_json_dumps(obj: Any, indent: int = 2) -> str:
    """安全 JSON 序列化（处理 numpy/pandas 类型）。"""
    return json.dumps(obj, ensure_ascii=False, cls=NumpyEncoder, indent=indent)
