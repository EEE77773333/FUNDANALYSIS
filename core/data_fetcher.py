"""
数据采集层
==========
封装 AKShare 和天天基金 API，提供统一的基金数据获取接口。
数据主要来源: 天天基金网 (fund.eastmoney.com) via AKShare + 直接 HTTP 接口。

设计原则:
- 所有网络请求都带重试和超时保护
- 关键数据使用 LRU 缓存避免重复请求
- 返回统一的 DataFrame 格式便于 Streamlit 展示
"""

# ---- SSL 证书校验（默认开启；仅在 DISABLE_SSL_VERIFY 显式开启时关闭）----
# 某些 macOS + Python 环境证书链不全时可临时设置 DISABLE_SSL_VERIFY=1 绕过。
# 生产环境请勿开启，以免中间人攻击。
import os as _os
import ssl as _ssl
if _os.getenv("DISABLE_SSL_VERIFY", "").strip().lower() in ("1", "true", "yes"):
    try:
        _ssl._create_default_https_context = _ssl._create_unverified_context
    except AttributeError:
        pass

import logging
import time
import json
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional, Dict, List, Any, Tuple

import pandas as pd
import numpy as np
import requests

from .config import config
from .data_sources import (
    persistent_cache,
    TTL_DAILY_NAV,
    TTL_VALUATION,
    TTL_SLOW,
)
from .utils import (
    safe_float,
    fmt_pct,
    fmt_money,
    timed_cache,
    log_call,
    calc_annualized_return,
    calc_max_drawdown,
    calc_annual_volatility,
    calc_sharpe_ratio,
)

logger = logging.getLogger(__name__)

# ============================================================
# 常量定义
# ============================================================

# 基金类型映射（天天基金分类）
FUND_TYPE_MAP = {
    "股票型": "stock",
    "混合型": "hybrid",
    "债券型": "bond",
    "货币型": "money",
    "指数型": "index",
    "指数型-股票": "index_stock",
    "ETF": "etf",
    "ETF联接": "etf_link",
    "QDII": "qdii",
    "LOF": "lof",
    "FOF": "fof",
}

# 常见指数代码映射
INDEX_CODE_MAP = {
    "沪深300": "000300",
    "中证500": "000905",
    "中证1000": "000852",
    "创业板指": "399006",
    "科创50": "000688",
    "上证50": "000016",
    "中证红利": "000922",
    "中证全债": "H11001",
    "纳斯达克100": "NDX",
    "标普500": "SPX",
}

# 天天基金 API 基础 URL
EASTMONEY_FUND_DETAIL = "http://fund.eastmoney.com/pingzhongdata/{code}.js"
EASTMONEY_REALTIME_NAV = "http://fundgz.1234567.com.cn/js/{code}.js"
EASTMONEY_FUND_LIST = "http://fund.eastmoney.com/js/fundcode_search.js"

# HTTP 请求配置
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # 秒


def _safe_empty_df(columns: list) -> pd.DataFrame:
    """返回带正确列名的空 DataFrame，避免下游 pandas 操作崩溃。"""
    return pd.DataFrame(columns=columns)

# 数据源导入（可选，允许降级运行）
try:
    import akshare as ak

    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    logger.warning("AKShare 未安装，部分数据功能不可用。请运行: pip install akshare")

try:
    import efinance as ef

    EFINANCE_AVAILABLE = True
except ImportError:
    EFINANCE_AVAILABLE = False
    logger.debug("efinance 未安装（个股K线备选），请运行: pip install efinance")

try:
    import tushare as ts

    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False
    logger.debug("Tushare 未安装（基金持仓/宏观备选），请运行: pip install tushare")


# ============================================================
# HTTP 请求工具
# ============================================================


def _http_get(url: str, params: dict = None, headers: dict = None,
              bypass_proxy: bool = False) -> Optional[str]:
    """带重试机制的 HTTP GET 请求。"""
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "http://fund.eastmoney.com/",
    }
    if headers:
        default_headers.update(headers)

    # 代理配置：先尝试系统代理，失败后直连
    proxy_configs = [None]  # None = 使用系统默认
    if bypass_proxy:
        proxy_configs = [{"http": None, "https": None}]  # 直连
    else:
        proxy_configs = [None, {"http": None, "https": None}]  # 先代理，后直连

    last_error = None
    for proxies in proxy_configs:
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(
                    url, params=params, headers=default_headers,
                    timeout=REQUEST_TIMEOUT, proxies=proxies,
                )
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as e:
                last_error = e
                if not bypass_proxy and "proxy" in str(e).lower() and proxies is None:
                    # 代理错误，立即切换到直连模式
                    break
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))

    logger.error(f"请求最终失败: {url} — {last_error}")
    return None


def _parse_fund_detail_js(js_text: str) -> dict:
    """
    解析天天基金 `pingzhongdata/{code}.js` 返回的 JS 变量。
    该 JS 文件定义形如: var fS_name = "华夏成长"; var Data_netWorthTrend = [...];
    这里用正则提取关键变量。
    """
    import re

    result = {}

    # 提取单行变量 var xxx = "value";
    single_vars = re.findall(r'var\s+(\w+)\s*=\s*"(.*?)"', js_text)
    for k, v in single_vars:
        result[k] = v

    # 提取 JSON 数组
    array_vars = re.findall(
        r"var\s+(\w+)\s*=\s*(\[[\s\S]*?\]);", js_text
    )
    for k, v in array_vars:
        try:
            result[k] = json.loads(v)
        except json.JSONDecodeError:
            result[k] = v

    # 提取 Data_netWorthTrend（净值趋势）— 可能跨行
    nw_match = re.search(
        r"var\s+Data_netWorthTrend\s*=\s*(\[[\s\S]*?\]);", js_text
    )
    if nw_match:
        try:
            result["Data_netWorthTrend"] = json.loads(nw_match.group(1))
        except json.JSONDecodeError:
            pass

    # 提取 Data_ACWorthTrend（累计净值趋势）
    acw_match = re.search(
        r"var\s+Data_ACWorthTrend\s*=\s*(\[[\s\S]*?\]);", js_text
    )
    if acw_match:
        try:
            result["Data_ACWorthTrend"] = json.loads(acw_match.group(1))
        except json.JSONDecodeError:
            pass

    return result


# ============================================================
# DataFetcher 主类
# ============================================================


class DataFetcher:
    """
    基金数据获取器。

    同时使用 AKShare（主通道）和天天基金直接 API（补充通道），
    确保数据完整性和可靠性。

    使用示例:
        fetcher = DataFetcher()
        funds = fetcher.get_fund_list("股票型")
        nav = fetcher.get_fund_nav_history("000001", years=3)
        manager = fetcher.get_fund_manager_info("000001")
    """

    def __init__(self):
        self._ak_available = AKSHARE_AVAILABLE

        # 多源数据框架：复用统一注册表，避免两套数据源配置各说各话
        try:
            from .fetchers import build_default_fetcher
            self._msf = build_default_fetcher()
            self._sources_loaded = True
            ready = self._msf.get_available_sources()
            if ready:
                logger.info("数据源就绪: %s", ", ".join(ready))
        except Exception as e:
            logger.debug(f"多源框架初始化跳过: {e}")
            self._msf = None
            self._sources_loaded = False

    def _try_multi_source(self, method: str, **kwargs):
        """通过多源框架获取数据（自动 fallback）"""
        if self._msf and self._sources_loaded:
            return self._msf.fetch(method, **kwargs)
        return None

    def get_available_sources(self) -> list:
        """
        列出全部数据源及其状态。

        注意返回的是「全量含不可用项」的列表，便于 UI 把
        「装了但缺 token」「没装依赖」等状态如实展示。
        只要可用源名单请用 `get_available_source_names()`。
        """
        if self._msf:
            return self._msf.get_all_sources()
        return [{"name": "eastmoney", "label": "东方财富 / 天天基金直连",
                 "priority": 1, "enabled": True, "available": True, "reason": "",
                 "requires_token": False}]

    def get_available_source_names(self) -> list:
        """只返回当前可用的数据源名列表。"""
        if self._msf:
            return self._msf.get_available_sources()
        return ["eastmoney"]

    # ---- 基金列表 ----

    @persistent_cache("fundlist", ttl=TTL_SLOW)
    @timed_cache(ttl=600, maxsize=8)
    def get_all_funds_basic(self) -> pd.DataFrame:
        """
        获取全市场公募开放式基金基本信息。

        主通道：天天基金 direct API（基金代码、简称、类型、拼音）
        备用通道：AKShare（函数名随版本变动，作为补充）

        Returns:
            DataFrame 包含字段: 基金代码, 基金简称, 基金类型, 拼音缩写
        """
        # 主通道：天天基金 JS 文件（稳定接口，多年未变）
        df = self._get_fund_list_fallback()
        if not df.empty:
            return df

        # 备用通道：AKShare（尝试多个可能的函数名）
        if self._ak_available:
            for func_name in [
                "fund_open_fund_info_em",
                "fund_em_open_fund_info",
                "fund_aum_em",
            ]:
                try:
                    func = getattr(ak, func_name, None)
                    if func:
                        df = func()
                        if df is not None and not df.empty:
                            logger.info(f"AKShare.{func_name} 获取基金列表成功: {len(df)} 条")
                            return df
                except Exception as e:
                    logger.debug(f"AKShare.{func_name} 失败: {e}")

        return pd.DataFrame()

    def _get_fund_list_fallback(self) -> pd.DataFrame:
        """降级方案：直接从天天基金 JS 文件获取基金列表。"""
        text = _http_get(EASTMONEY_FUND_LIST)
        if not text:
            return pd.DataFrame()

        import re
        # 格式: var r = [["000001","HXCZ","华夏成长","混合型","HUAXIACZ"],...]
        match = re.search(r"var\s+r\s*=\s*(\[\[.*?\]\]);", text, re.DOTALL)
        if not match:
            return pd.DataFrame()

        try:
            data = json.loads(match.group(1))
            df = pd.DataFrame(
                data,
                columns=["基金代码", "拼音缩写", "基金简称", "基金类型", "全拼"],
            )
            return df
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"解析基金列表失败: {e}")
            return pd.DataFrame()

    def get_fund_list(self, fund_type: Optional[str] = None) -> pd.DataFrame:
        """
        获取基金列表，可按类型筛选。

        Args:
            fund_type: 基金类型，如 '股票型', '债券型', '混合型', '指数型-股票', 'QDII', 'ETF'
                       留空则返回全部

        Returns:
            pd.DataFrame
        """
        df = self.get_all_funds_basic()
        if df.empty:
            return df

        if fund_type:
            # 模糊匹配类型名称
            mask = df["基金类型"].str.contains(
                fund_type.replace("-", "|"), na=False, regex=True
            )
            df = df[mask]

        return df.reset_index(drop=True)

    def search_fund(self, keyword: str) -> pd.DataFrame:
        """通过关键词（代码或名称）搜索基金。"""
        df = self.get_all_funds_basic()
        if df.empty:
            return df

        mask = (
            df["基金代码"].str.contains(keyword, na=False)
            | df["基金简称"].str.contains(keyword, na=False)
            | df["拼音缩写"].str.contains(keyword.upper(), na=False)
        )
        return df[mask].reset_index(drop=True)

    # ---- 基金净值 ----

    @persistent_cache("nav", ttl=TTL_DAILY_NAV)
    @timed_cache(ttl=300, maxsize=32)
    def get_fund_nav_history(
        self, code: str, years: int = 3
    ) -> pd.DataFrame:
        """
        获取单只基金的历史净值数据。

        主通道：天天基金 direct API（pingzhongdata JS 文件）
        备用通道：AKShare

        Args:
            code: 基金代码（如 '000001'）
            years: 回溯年数

        Returns:
            DataFrame，包含 日期、单位净值、累计净值、日增长率 等
        """
        # 主通道：天天基金 JS（更稳定）
        df = self._get_nav_fallback(code, years)
        if not df.empty:
            return df

        # 备用通道：AKShare（尝试多个可能的函数名）
        if self._ak_available:
            for func_name in [
                "fund_open_fund_info_em",
                "fund_open_fund_hist_net_value",
                "fund_etf_fund_info_em",
            ]:
                try:
                    func = getattr(ak, func_name, None)
                    if func:
                        df = func(fund=code) if "fund" in func_name else func(code)
                        if df is not None and not df.empty:
                            df = self._normalize_nav_df(df)
                            cutoff = datetime.now() - timedelta(days=years * 365)
                            if "日期" in df.columns:
                                df["日期"] = pd.to_datetime(df["日期"])
                                df = df[df["日期"] >= cutoff]
                            logger.info(f"AKShare.{func_name} 获取净值成功: {len(df)} 条")
                            if "日期" in df.columns:
                                return df.sort_values("日期", ascending=False).reset_index(drop=True)
                            return df  # 兜底：无日期列时原样返回
                except Exception as e:
                    logger.debug(f"AKShare.{func_name}({code}) 失败: {e}")

        return _safe_empty_df(["日期", "单位净值"])

    # NAV 空安全常量
    NAV_COLUMNS = ["日期", "单位净值"]

    def _normalize_nav_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化净值 DataFrame 列名。"""
        col_map = {
            "净值日期": "日期",
            "单位净值": "单位净值",
            "累计净值": "累计净值",
            "日增长率": "日增长率",
            "申购状态": "申购状态",
            "赎回状态": "赎回状态",
        }
        # 只保留存在的列
        rename = {k: v for k, v in col_map.items() if k in df.columns}
        return df.rename(columns=rename)

    def _get_nav_fallback(self, code: str, years: int) -> pd.DataFrame:
        """降级：直接从天天基金 JS 获取净值。"""
        url = EASTMONEY_FUND_DETAIL.format(code=code)
        text = _http_get(url)
        if not text:
            return pd.DataFrame()

        detail = _parse_fund_detail_js(text)
        trend = detail.get("Data_netWorthTrend", [])
        if not trend:
            return pd.DataFrame()

        records = []
        for item in trend:
            if isinstance(item, dict):
                ts = item.get("x", 0)
                nav = item.get("y", None)
                if ts and nav is not None:
                    date = datetime.fromtimestamp(ts / 1000)
                    records.append(
                        {
                            "日期": date,
                            "单位净值": safe_float(nav),
                            "净值变动": item.get("equityReturn", None),
                        }
                    )

        df = pd.DataFrame(records)
        cutoff = datetime.now() - timedelta(days=years * 365)
        df = df[df["日期"] >= cutoff]
        return df.sort_values("日期", ascending=False).reset_index(drop=True)

    # ---- 实时估值 ----

    @persistent_cache("realtime")  # ttl=None → 用用户配置的实时行情缓存时长
    def get_realtime_estimate(self, code: str) -> Optional[Dict[str, Any]]:
        """
        获取基金实时估算净值（交易时段有效）。

        Args:
            code: 基金代码

        Returns:
            dict: {name, code, nav_time, estimated_nav, estimated_pct,
                   last_nav, last_nav_date, premium_pct}
        """
        url = EASTMONEY_REALTIME_NAV.format(code=code)
        # 天天基金实时估值接口返回 JSONP: jsonpgz({...});
        text = _http_get(url)
        if not text:
            return None

        import re
        match = re.search(r"jsonpgz\((\{.*?\})\)", text, re.DOTALL)
        if not match:
            return None

        try:
            data = json.loads(match.group(1))
            return {
                "基金代码": data.get("fundcode", code),
                "基金名称": data.get("name", ""),
                "估算时间": data.get("gztime", ""),
                "估算净值": safe_float(data.get("gsz", 0)),
                "估算涨幅%": safe_float(data.get("gszzl", 0)),
                "上一日净值": safe_float(data.get("dwjz", 0)),
                "上一日日期": data.get("jzrq", ""),
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"解析实时估值失败 ({code}): {e}")
            return None

    # ---- 基金经理 ----

    @persistent_cache("mgr", ttl=TTL_SLOW)
    @timed_cache(ttl=86400, maxsize=64)
    def get_fund_manager_info(self, code: str) -> Optional[Dict[str, Any]]:
        """
        获取基金经理详细信息。

        Args:
            code: 基金代码

        Returns:
            dict: {manager_name, tenure_days, fund_size, company, ...}
        """
        url = EASTMONEY_FUND_DETAIL.format(code=code)
        text = _http_get(url)
        if not text:
            return None

        detail = _parse_fund_detail_js(text)
        if not detail:
            return None

        # 提取基金经理相关字段
        manager_info = {
            "基金名称": detail.get("fS_name", ""),
            "基金代码": detail.get("fS_code", code),
            "基金经理": "",
            "任职起始日期": "",
            "基金公司": detail.get("fS_companyname", ""),
            "成立日期": detail.get("fS_buyedstartdate", ""),
            "最新规模": self._extract_fund_size(detail),
        }

        # 从 Data_fundSharesPositions 或 Data_currentFundManager 提取经理信息
        managers = detail.get("Data_currentFundManager", [])
        if managers:
            mgr = managers[0] if isinstance(managers[0], dict) else {}
            manager_info["基金经理"] = mgr.get("name", "")
            manager_info["任职起始日期"] = mgr.get("startDate", "")
            manager_info["从业年限"] = mgr.get("workTime", "")

        # 如果上面没提取到，尝试从 Data_fundSharesPositions 找
        if not manager_info["基金经理"]:
            positions = detail.get("Data_fundSharesPositions", [])
            # 这个字段结构因基金类型而异，做保守处理

        # 提取费率信息
        manager_info["管理费率%"] = safe_float(
            detail.get("fS_buyedRate", detail.get("fund_Rate", 0))
        )
        manager_info["托管费率%"] = safe_float(detail.get("fS_trusteeRate", 0))

        return manager_info

    def _extract_fund_size(self, detail: dict) -> str:
        """从基金详情中提取规模信息。"""
        # 尝试多个可能的字段
        size = detail.get("fS_fund_size", "")
        if not size:
            # 从 Data_assetAllocation 中获取最新规模
            allocation = detail.get("Data_assetAllocation", {})
            if allocation and "series" in allocation:
                for s in allocation.get("series", []):
                    if s.get("name") == "净资产(亿元)":
                        data = s.get("data", [])
                        if data:
                            return f"{data[-1]}亿元"
        return size

    # ---- 指数估值 ----

    @persistent_cache("valuation", ttl=TTL_VALUATION)
    @timed_cache(ttl=86400, maxsize=16)
    def get_index_valuation(self, index_name: str) -> Optional[Dict[str, Any]]:
        """
        获取指数估值数据（PE/PB 百分位）。

        数据来源:
            - PE/PB 历史序列: AKShare stock_index_pe_lg / stock_index_pb_lg (乐股数据，~5000行)
            - 股息率: csindex 官网数据（仅部分指数）

        Args:
            index_name: 指数名称，如 '沪深300', '中证500', '上证50'

        Returns:
            dict: {PE, PE百分位, PB, PB百分位, 股息率, 数据日期}
        """

        result = {
            "指数名称": index_name,
            "PE": None,
            "PE百分位": None,
            "PB": None,
            "PB百分位": None,
            "股息率": None,
            "数据日期": "",
        }

        def _calc_percentile(series, current_val):
            """计算当前值在历史序列中的分位点 (0-100)"""
            s = series.dropna()
            if len(s) < 10 or current_val is None or current_val <= 0:
                return None
            rank = (s < current_val).sum()
            return round(rank / len(s) * 100, 1)

        # ---- PE/PB 数据源1：乐股数据（长历史序列，仅支持沪深300/中证500/上证50）----
        lg_indices = {"沪深300", "中证500", "上证50"}

        if self._ak_available and index_name in lg_indices:
            # PE
            try:
                if hasattr(ak, "stock_index_pe_lg"):
                    pe_df = ak.stock_index_pe_lg(symbol=index_name)
                    if pe_df is not None and not pe_df.empty and len(pe_df) >= 10:
                        pe_df = pe_df.sort_values("日期")
                        latest = pe_df.iloc[-1]
                        pe_val = safe_float(latest.get("滚动市盈率", latest.get("静态市盈率", 0)))
                        result["PE"] = pe_val if pe_val > 0 else None
                        result["数据日期"] = str(latest.get("日期", ""))
                        pe_col = "滚动市盈率" if "滚动市盈率" in pe_df.columns else "静态市盈率"
                        result["PE百分位"] = _calc_percentile(pe_df[pe_col], result["PE"])
            except Exception as e:
                logger.warning(f"获取 PE(LG) 失败 ({index_name}): {e}")

            # PB
            try:
                if hasattr(ak, "stock_index_pb_lg"):
                    pb_df = ak.stock_index_pb_lg(symbol=index_name)
                    if pb_df is not None and not pb_df.empty and len(pb_df) >= 10:
                        pb_df = pb_df.sort_values("日期")
                        latest = pb_df.iloc[-1]
                        pb_val = safe_float(latest.get("市净率", 0))
                        result["PB"] = pb_val if pb_val > 0 else None
                        if not result["数据日期"]:
                            result["数据日期"] = str(latest.get("日期", ""))
                        result["PB百分位"] = _calc_percentile(pb_df["市净率"], result["PB"])
            except Exception as e:
                logger.warning(f"获取 PB(LG) 失败 ({index_name}): {e}")

        # ---- PE/PB 数据源2：csindex 官网（后备，较短历史但覆盖更广）----
        if result["PE"] is None and self._ak_available:
            index_code = INDEX_CODE_MAP.get(index_name, "")
            if index_code:
                try:
                    if hasattr(ak, "stock_zh_index_value_csindex"):
                        cs_df = ak.stock_zh_index_value_csindex(symbol=index_code)
                        if cs_df is not None and not cs_df.empty and len(cs_df) >= 5:
                            cs_df = cs_df.sort_values("日期")
                            latest = cs_df.iloc[-1]
                            pe_val = safe_float(latest.get("市盈率1", latest.get("市盈率2", 0)))
                            result["PE"] = pe_val if pe_val > 0 else None
                            if not result["数据日期"]:
                                result["数据日期"] = str(latest.get("日期", ""))
                            pe_col = "市盈率1" if "市盈率1" in cs_df.columns else "市盈率2"
                            result["PE百分位"] = _calc_percentile(cs_df[pe_col], result["PE"])
                except Exception:
                    pass  # csindex 不支持的指数静默跳过

        # ---- 股息率：csindex 官网数据 ----
        if self._ak_available and result["PE"] is not None:
            try:
                index_code = INDEX_CODE_MAP.get(index_name, "")
                if (index_code and not result.get("股息率")
                        and hasattr(ak, "stock_zh_index_value_csindex")):
                    cs_df = ak.stock_zh_index_value_csindex(symbol=index_code)
                    if cs_df is not None and not cs_df.empty:
                        latest = cs_df.iloc[-1]
                        div = safe_float(latest.get("股息率1", latest.get("股息率2", None)))
                        result["股息率"] = div if div and div > 0 else None
            except Exception:
                pass  # 股息率为可选数据，静默失败

        # ---- 全部失败 → 返回提示 ----
        if result["PE"] is None and result["PB"] is None:
            result["提示"] = "指数估值数据获取失败，请稍后重试"

        return result

    # ---- 基金持仓 ----

    @persistent_cache("holdings", ttl=TTL_SLOW)
    @timed_cache(ttl=86400, maxsize=32)
    def get_fund_holdings(self, code: str) -> Optional[pd.DataFrame]:
        """
        获取基金前十大重仓股。

        Args:
            code: 基金代码

        Returns:
            DataFrame: 股票代码、名称、占净值比例、持仓市值等（仅股票/混合型基金有效）
        """
        if self._ak_available:
            for func_name, kwargs in [
                ("fund_portfolio_hold_em", {"symbol": code, "date": str(datetime.now().year)}),
                ("fund_portfolio_hold_em", {"symbol": code}),
            ]:
                try:
                    func = getattr(ak, func_name, None)
                    if func:
                        df = func(**kwargs)
                        if df is not None and not df.empty:
                            # 标准化列名
                            col_map = {
                                "占净值比例": "占净值比例%", "持仓市值": "持仓市值(万)",
                            }
                            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
                            # 只返回前十大重仓股（季度数据包含全部持仓）
                            if len(df) > 10:
                                df = df.head(10)
                            return df
                except Exception as e:
                    logger.debug(f"AKShare.{func_name}({code}) 失败: {e}")

        # 备选方案2：Tushare（需配置 TUSHARE_TOKEN）
        if TUSHARE_AVAILABLE and config.tushare_token:
            try:
                pro = ts.pro_api(config.tushare_token)
                df = pro.fund_portfolio(ts_code=f"{code}.OF")
                if df is not None and not df.empty:
                    df = df.rename(columns={
                        "symbol": "股票代码", "name": "股票名称",
                        "ratio": "占净值比例%", "mkv": "持仓市值(万)",
                    })
                    # 取最新季度前10
                    df = df.sort_values("end_date", ascending=False).head(10)
                    return df[["股票代码","股票名称","占净值比例%","持仓市值(万)"]]
            except Exception as e:
                logger.debug(f"Tushare 获取持仓失败 ({code}): {e}")

        # 最终降级：通过详情 JS
        url = EASTMONEY_FUND_DETAIL.format(code=code)
        text = _http_get(url)
        if not text:
            return None

        detail = _parse_fund_detail_js(text)
        holdings = detail.get("Data_fundSharesPositions", [])
        if not holdings:
            return None

        records = []
        for h in holdings:
            if isinstance(h, dict):
                records.append(
                    {
                        "股票代码": h.get("GPCode", h.get("code", "")),
                        "股票名称": h.get("GPName", h.get("name", "")),
                        "占净值比例%": safe_float(
                            h.get("NetAssetRatio", h.get("ratio", 0))
                        ),
                        "持仓市值(万)": safe_float(
                            h.get("MarketValue", h.get("value", 0))
                        ),
                    }
                )

        return pd.DataFrame(records) if records else None

    # ---- 持仓收益增强 ----

    def enrich_holdings_with_returns(
        self, holdings_df: pd.DataFrame, quarter: str = "2025Q1"
    ) -> pd.DataFrame:
        """
        为持仓股票补充季度涨跌幅和近似贡献度。

        Args:
            holdings_df: get_fund_holdings 的返回值
            quarter: 季度标识，如 "2025Q1"

        Returns:
            增强后的 DataFrame，新增列: 季度涨跌幅%、近似贡献度%
        """
        if holdings_df is None or holdings_df.empty:
            return holdings_df

        # 自动推算最近一个完整季度
        today = datetime.now()
        current_q = (today.month - 1) // 3 + 1
        # 最近完整季度 = 上一个季度
        prev_q = current_q - 1
        prev_year = today.year
        if prev_q == 0:
            prev_q = 4
            prev_year -= 1
        # 季度月份范围
        q_start_month = (prev_q - 1) * 3 + 1
        q_end_month = prev_q * 3
        # 计算该月最后一天
        import calendar
        last_day = calendar.monthrange(prev_year, q_end_month)[1]
        start = f"{prev_year}-{q_start_month:02d}-01"
        end = f"{prev_year}-{q_end_month:02d}-{last_day:02d}"
        # 如果指定了 quarter 参数则优先使用（但不再需要硬编码映射表）

        df = holdings_df.copy()
        returns_list = []

        for _, row in df.iterrows():
            stock_code = str(row.get("股票代码", ""))
            if not stock_code or len(stock_code) < 6:
                returns_list.append(None)
                continue

            stock_return = None
            try:
                if stock_code.isdigit() and len(stock_code) == 6:
                    # 方案1：efinance（稳定，不依赖东方财富push2 API）
                    if EFINANCE_AVAILABLE:
                        try:
                            hist = ef.stock.get_quote_history(stock_code, beg=start, end=end)
                            if hist is not None and not hist.empty:
                                close_col = "收盘"
                                if close_col in hist.columns and len(hist) >= 2:
                                    first_close = float(hist[close_col].iloc[0])
                                    last_close = float(hist[close_col].iloc[-1])
                                    if first_close > 0:
                                        stock_return = (last_close - first_close) / first_close
                        except Exception:
                            pass

                    # 方案2：东方财富K线直连（efinance 不可用时的备选）
                    if stock_return is None:
                        secid = f"0.{stock_code}" if stock_code.startswith(("0","3")) else f"1.{stock_code}"
                        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
                        params = {
                            "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
                            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
                            "klt": "101", "fqt": "1",
                            "beg": start.replace("-",""), "end": end.replace("-",""),
                            "ut": "7eea3edcaed734bea9cbfc24409ed989",
                        }
                        text = _http_get(url, params=params)
                        if text:
                            import json as _json
                            data = _json.loads(text)
                            klines = data.get("data", {}).get("klines", [])
                            if klines and len(klines) >= 2:
                                first_close = float(klines[0].split(",")[2])
                                last_close = float(klines[-1].split(",")[2])
                                if first_close > 0:
                                    stock_return = (last_close - first_close) / first_close
                else:
                    returns_list.append(None)
                    continue
            except Exception:
                pass

            returns_list.append(stock_return)

        df["季度涨跌幅%"] = [f"{r*100:.2f}%" if r is not None else "N/A" for r in returns_list]

        # 近似贡献度 = 权重 × 涨跌幅
        contributions = []
        for i, row in df.iterrows():
            r = returns_list[i]
            w = safe_float(row.get("占净值比例%", 0)) / 100.0
            if r is not None:
                contributions.append(f"{r * w * 100:.3f}%")
            else:
                contributions.append("N/A")
        df["近似贡献度%"] = contributions

        return df

    # ---- 基金评级 ----

    def get_fund_rating(self, code: str) -> Optional[Dict[str, Any]]:
        """获取基金评级（晨星/济安金信等）。"""
        if self._ak_available:
            try:
                df = ak.fund_rating()
                if df is not None and not df.empty:
                    match = df[df["基金代码"].astype(str).str.strip() == code]
                    if not match.empty:
                        return match.iloc[0].to_dict()
            except Exception as e:
                logger.warning(f"获取评级失败 ({code}): {e}")
        return None

    # ---- 宏观指标 ----

    @persistent_cache("macro", ttl=TTL_SLOW)
    @timed_cache(ttl=86400, maxsize=4)
    def get_macro_indicators(self) -> Dict[str, Any]:
        """
        获取中国宏观经济核心指标（CPI/PPI/PMI/GDP/LPR等）。

        Returns:
            dict: 各类宏观指标的最新数据
        """
        result = {
            "数据更新时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "数据状态": "部分获取",
        }

        if self._ak_available or TUSHARE_AVAILABLE:
            indicators = {
                "cpi": ("macro_china_cpi_yearly", "CPI同比"),
                "ppi": ("macro_china_ppi_yearly", "PPI同比"),
                "pmi": ("macro_china_pmi", "制造业PMI"),
                "money_supply": ("macro_china_money_supply", "货币供应量"),
                "lpr": ("macro_china_lpr", "贷款市场报价利率"),
                "gdp": ("macro_china_gdp_yearly", "GDP同比"),
            }

            for key, (func_name, display_name) in indicators.items():
                try:
                    # AKShare 优先
                    if self._ak_available:
                        func = getattr(ak, func_name, None)
                        if func:
                            df = func()
                            if df is not None and not df.empty:
                                result[key] = {"名称": display_name, "最新数据": df.iloc[-1].to_dict()}
                                continue

                    # Tushare 备选
                    if TUSHARE_AVAILABLE and config.tushare_token:
                        pro = ts.pro_api(config.tushare_token)
                        tushare_map = {
                            "cpi": ("cn_cpi", "cpi"), "ppi": ("cn_ppi", "ppi"),
                            "pmi": ("cn_pmi", "pmi"),
                            "money_supply": ("cn_m", "m2"),
                            "lpr": ("cn_lpr", "lpr"),
                            "gdp": ("cn_gdp", "gdp"),
                        }
                        if key in tushare_map:
                            ts_df = getattr(pro, tushare_map[key][0])()
                            if ts_df is not None and not ts_df.empty:
                                result[key] = {"名称": display_name, "最新数据": ts_df.iloc[-1].to_dict()}
                                continue
                except Exception as e:
                    pass
                result[key] = {"名称": display_name, "状态": "数据获取中"}

        return result

    # ---- 多源数据增强 ----

    def get_full_holdings(self, code: str) -> Optional[pd.DataFrame]:
        """
        获取基金完整持仓（非仅前十大）。

        主通道: AKShare（前十大，天天基金限制）
        备用:   Tushare（完整持仓，需 token）
        """
        # 先尝试阿凯Share（仅前十大）
        df = self.get_fund_holdings(code)
        # 再尝试 Tushare 获取完整持仓
        full = self._try_multi_source("fund_holdings", fund_code=code)
        if full is not None and not full.empty:
            return full
        return df

    def get_fund_manager_history(self, code: str) -> Optional[dict]:
        """
        获取基金经理详细履历。

        主通道: Tushare（经理历史业绩）
        备用:   天天基金（基本信息）
        """
        result = self._try_multi_source("fund_manager", fund_code=code)
        if result:
            return result
        return self.get_fund_manager_info(code)

    def get_global_index_valuation(self, index_name: str) -> Optional[dict]:
        """
        获取全球指数估值（QDII 专用）。

        支持: 标普500/纳斯达克100/日经225/德国DAX/恒生指数 等
        """
        return self._try_multi_source("index_valuation", index_name=index_name)

    def get_overseas_stock_prices(self, symbols: list) -> Optional[dict]:
        """
        批量获取海外股票行情（QDII 持仓穿透专用）。

        Args:
            symbols: 股票代码列表，如 ["AAPL", "MSFT", "0700"]

        Returns:
            {symbol: {name, price, pe, change_pct}, ...}
        """
        return self._try_multi_source("batch_stock_prices", symbols=symbols)

    def get_available_data_sources(self) -> list:
        """列出当前可用的数据源及其状态"""
        return self.get_available_sources()

    # ---- 综合查询 ----

    def get_fund_comprehensive(
        self, code: str
    ) -> Dict[str, Any]:
        """
        基金综合信息查询：一次性获取净值+经理+持仓+评级+实时估值。

        Args:
            code: 基金代码

        Returns:
            dict: 包含所有信息的综合字典
        """
        return {
            "基金代码": code,
            "基金概况": self.get_fund_manager_info(code),
            "历史净值": self.get_fund_nav_history(code, years=3),
            "实时估值": self.get_realtime_estimate(code),
            "持仓明细": self.get_fund_holdings(code),
            "评级信息": self.get_fund_rating(code),
            "查询时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # ---- FAMAS 增强数据（持有人/多季度持仓/经理历史）----

    def _get_holder_structure(self, code: str) -> dict:
        """获取基金持有人结构（机构/个人比例、集中度）。"""
        if AKSHARE_AVAILABLE:
            try:
                df = ak.fund_hold_structure_em(symbol=code)
                if df is not None and not df.empty:
                    latest = df.iloc[-1].to_dict()
                    return {
                        "机构持有比例": f"{safe_float(latest.get('机构持有比例', 0)):.1f}%",
                        "个人持有比例": f"{safe_float(latest.get('个人持有比例', 0)):.1f}%",
                        "内部持有比例": f"{safe_float(latest.get('内部持有比例', 0)):.1f}%",
                        "最新报告期": str(latest.get('报告期', '')),
                    }
            except Exception:
                pass
        return {}

    def _get_multi_quarter_holdings(self, code: str, quarters: int = 4) -> list:
        """获取多季度前十大持仓（用于风格漂移和调仓分析）。"""
        data = []
        if AKSHARE_AVAILABLE:
            try:
                df = ak.fund_portfolio_hold_em(symbol=code, date=str(datetime.now().year))
                if df is not None and not df.empty and "季度" in df.columns:
                    q_list = sorted(df["季度"].dropna().unique())[-quarters:]
                    for q in q_list:
                        q_df = df[df["季度"]==q][["股票名称","占净值比例","持仓市值(万)"]]
                        q_df["占净值比例"] = q_df["占净值比例"].apply(safe_float)
                        data.append({
                            "季度": str(q)[-8:],
                            "持仓": q_df.to_dict(orient="records"),
                            "集中度": f"{q_df['占净值比例'].sum():.1f}%",
                        })
            except Exception:
                pass
        return data

    def _get_manager_history(self, code: str) -> dict:
        """获取基金经理变更历史。"""
        history = []
        if AKSHARE_AVAILABLE:
            try:
                df = ak.fund_announcement_personnel_em(symbol=code)
                if df is not None and not df.empty:
                    for _, row in df.head(10).iterrows():
                        history.append({
                            "公告日期": str(row.get('公告日期', '')),
                            "变更类型": str(row.get('变更类型', '')),
                            "变更前": str(row.get('变更前', '')),
                            "变更后": str(row.get('变更后', '')),
                        })
            except Exception:
                pass
        return {"变更记录": history} if history else {}

    # ---- 批量并发获取 ----

    def batch_get_nav_and_info(
        self, codes: list, years: int = 3, max_workers: int = 5
    ) -> pd.DataFrame:
        """
        并发获取多只基金的净值和基本信息（比顺序快 3-4 倍）。

        Args:
            codes: 基金代码列表
            years: 回溯年数
            max_workers: 并发线程数

        Returns:
            DataFrame: 基金代码、简称、最新净值、年化收益等
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _fetch_one(code):
            try:
                nav = self.get_fund_nav_history(code, years=years)
                info = self.get_fund_manager_info(code)
                if nav.empty or "单位净值" not in nav.columns:
                    return None
                nav_s = nav.sort_values("日期", ascending=True)["单位净值"].dropna()
                if len(nav_s) < 60:
                    return None
                ann_ret = calc_annualized_return(nav_s)
                return {
                    "基金代码": code,
                    "基金简称": info.get("基金名称", "") if info else "",
                    "最新净值": round(nav_s.iloc[-1], 4),
                    "年化收益率": round(ann_ret, 4),
                    "最大回撤": round(calc_max_drawdown(nav_s), 4),
                    "年化波动率": round(calc_annual_volatility(nav_s.pct_change().dropna()), 4),
                    "夏普比率": round(calc_sharpe_ratio(nav_s.pct_change().dropna()), 2),
                    "管理费率": safe_float(info.get("管理费率%", 0) if info else 0),
                    "基金经理": info.get("基金经理", "") if info else "",
                }
            except Exception:
                return None

        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_one, code): code for code in codes}
            for f in as_completed(futures):
                r = f.result()
                if r:
                    results.append(r)

        return pd.DataFrame(results) if results else pd.DataFrame()

    # ---- 基金筛选 ----

    def screen_funds(
        self,
        fund_type: Optional[str] = None,
        min_years: Optional[int] = None,
        max_drawdown: Optional[float] = None,
        min_return_annual: Optional[float] = None,
        max_fee_pct: Optional[float] = None,
        top_n: int = 20,
    ) -> pd.DataFrame:
        """
        多维度基金筛选。

        Args:
            fund_type: 基金类型
            min_years: 最少成立年数
            max_drawdown: 最大回撤上限（如 -0.20 表示回撤不超过20%）
            min_return_annual: 最低年化收益（如 0.10 表示年化≥10%）
            max_fee_pct: 最高管理费率
            top_n: 返回前N只基金

        Returns:
            筛选结果 DataFrame
        """
        basic = self.get_fund_list(fund_type)
        if basic.empty:
            return pd.DataFrame({"提示": ["未找到符合条件的基金"]})

        # 简化筛选：对前 top_n 只基金计算指标
        results = []
        for _, row in basic.head(top_n * 2).iterrows():
            code = str(row["基金代码"])
            nav = self.get_fund_nav_history(code, years=5)
            if nav.empty or len(nav) < 60:  # 至少60个交易日数据
                continue

            # 计算关键指标
            metrics = self._calc_fund_metrics_from_nav(nav)

            # 获取费率 + 成立日期
            info = self.get_fund_manager_info(code)
            fee = safe_float(info.get("管理费率%", 0)) if info else 0

            # 判断是否满足条件
            if min_years and info:
                from datetime import datetime
                est_date = str(info.get("成立日期", ""))
                if est_date and len(est_date) >= 8:
                    try:
                        est = datetime.strptime(est_date[:8], "%Y%m%d")
                        age = (datetime.now() - est).days / 365.25
                        if age < min_years:
                            continue
                    except ValueError:
                        pass
            if max_drawdown and metrics.get("最大回撤", -1) < max_drawdown:
                continue
            if min_return_annual and metrics.get("年化收益率", 0) < min_return_annual:
                continue
            if max_fee_pct and fee > max_fee_pct:
                continue

            results.append(
                {
                    "基金代码": code,
                    "基金简称": row.get("基金简称", ""),
                    "基金类型": row.get("基金类型", ""),
                    **metrics,
                    "管理费率%": fee,
                }
            )

            if len(results) >= top_n:
                break

        return (
            pd.DataFrame(results).sort_values("年化收益率", ascending=False)
            if results
            else pd.DataFrame({"提示": ["无基金满足当前筛选条件"]})
        )

    def _calc_fund_metrics_from_nav(
        self, nav_df: pd.DataFrame
    ) -> Dict[str, float]:
        """
        从净值序列计算基金核心指标。

        使用 .utils 中的函数进行计算。
        """
        from .utils import (
            calc_annualized_return,
            calc_max_drawdown,
            calc_sharpe_ratio,
            calc_annual_volatility,
            calc_calmar_ratio,
        )

        if nav_df.empty or "单位净值" not in nav_df.columns:
            return {}

        # 按日期升序排列
        df = nav_df.sort_values("日期", ascending=True)
        nav_series = df["单位净值"].dropna()

        if len(nav_series) < 20:
            return {}

        returns = nav_series.pct_change().dropna()

        return {
            "最新净值": round(nav_series.iloc[-1], 4),
            "年化收益率": round(calc_annualized_return(nav_series), 4),
            "年化波动率": round(calc_annual_volatility(returns), 4),
            "最大回撤": round(calc_max_drawdown(nav_series), 4),
            "夏普比率": round(calc_sharpe_ratio(returns), 2),
            "卡尔玛比率": round(calc_calmar_ratio(nav_series, returns), 2),
            "数据起始": df["日期"].iloc[0].strftime("%Y-%m-%d"),
            "数据截止": df["日期"].iloc[-1].strftime("%Y-%m-%d"),
        }


# 全局单例
_fetcher_instance: Optional[DataFetcher] = None


def get_fetcher() -> DataFetcher:
    """获取全局 DataFetcher 实例。"""
    global _fetcher_instance
    if _fetcher_instance is None:
        _fetcher_instance = DataFetcher()
    return _fetcher_instance
