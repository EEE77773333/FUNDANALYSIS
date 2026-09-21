"""
yfinance 数据源适配器
=====================
提供全球股票/指数行情、QDII 基金底层持仓数据。

需要: pip install yfinance
"""

import logging
from typing import Optional, Any
import pandas as pd

from . import DataSource

logger = logging.getLogger(__name__)

_YF_AVAILABLE = False
try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    pass

# 全球指数代码映射
GLOBAL_INDEX_MAP = {
    "标普500": "^GSPC",
    "纳斯达克100": "^NDX",
    "纳斯达克综合": "^IXIC",
    "道琼斯": "^DJI",
    "日经225": "^N225",
    "德国DAX": "^GDAXI",
    "英国富时100": "^FTSE",
    "恒生指数": "^HSI",
    "恒生科技": "^HSTECH",
    "印度Nifty50": "^NSEI",
    "越南VN30": "VN30.VN",
}


class YFinanceFetcher(DataSource):
    """yfinance 全球数据源（优先级 30，补充海外数据）"""

    def __init__(self):
        super().__init__("yfinance", priority=30)

    @property
    def is_available(self) -> bool:
        return _YF_AVAILABLE and self.enabled

    def fetch(self, method: str, **kwargs) -> Optional[Any]:
        handlers = {
            "stock_info": self._stock_info,
            "stock_history": self._stock_history,
            "index_valuation": self._index_valuation,
            "batch_stock_prices": self._batch_stock_prices,
        }
        handler = handlers.get(method)
        if handler:
            return handler(**kwargs)
        return None

    # ---- 单只股票信息 ----
    def _stock_info(self, symbol: str, **kwargs) -> Optional[dict]:
        """获取美股/港股/全球股票基本面信息"""
        try:
            ticker = yf.Ticker(self._normalize_symbol(symbol))
            info = ticker.info
            if info:
                return {
                    "名称": info.get("longName") or info.get("shortName", symbol),
                    "当前价格": info.get("currentPrice"),
                    "PE": info.get("trailingPE"),
                    "PB": info.get("priceToBook"),
                    "市值": info.get("marketCap"),
                    "行业": info.get("industry") or info.get("sector", ""),
                    "股息率": info.get("dividendYield"),
                    "52周最高": info.get("fiftyTwoWeekHigh"),
                    "52周最低": info.get("fiftyTwoWeekLow"),
                }
        except Exception as e:
            logger.debug(f"yfinance stock_info({symbol}): {e}")
        return None

    # ---- 股票历史行情 ----
    def _stock_history(self, symbol: str, period: str = "1y", **kwargs) -> Optional[pd.DataFrame]:
        """获取全球股票历史行情"""
        try:
            ticker = yf.Ticker(self._normalize_symbol(symbol))
            df = ticker.history(period=period)
            if df is not None and not df.empty:
                df = df.reset_index()
                df = df.rename(columns={
                    "Date": "日期", "Open": "开盘", "High": "最高",
                    "Low": "最低", "Close": "收盘", "Volume": "成交量",
                })
                df["日期"] = pd.to_datetime(df["日期"]).dt.tz_localize(None)
                return df
        except Exception as e:
            logger.debug(f"yfinance stock_history({symbol}): {e}")
        return None

    # ---- 全球指数估值 ----
    def _index_valuation(self, index_name: str, **kwargs) -> Optional[dict]:
        """获取全球指数 PE/PB（通过对应 ETF 反推）"""
        symbol = GLOBAL_INDEX_MAP.get(index_name)
        if not symbol:
            return None
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if info:
                pe = info.get("trailingPE")
                pb = info.get("priceToBook")
                if pe or pb:
                    return {
                        "指数名称": index_name,
                        "PE": pe,
                        "PB": pb,
                        "最新价格": info.get("regularMarketPrice", info.get("previousClose")),
                        "52周最高": info.get("fiftyTwoWeekHigh"),
                        "52周最低": info.get("fiftyTwoWeekLow"),
                    }
        except Exception:
            pass
        return None

    # ---- 批量股票行情 ----
    def _batch_stock_prices(self, symbols: list, **kwargs) -> Optional[pd.DataFrame]:
        """批量获取多只股票最新行情（用于 QDII 持仓穿透）"""
        try:
            normalized = [self._normalize_symbol(s) for s in symbols]
            tickers = yf.Tickers(" ".join(normalized))
            result = {}
            for sym in symbols:
                try:
                    t = tickers.tickers.get(self._normalize_symbol(sym))
                    if t:
                        info = t.info
                        result[sym] = {
                            "name": info.get("shortName", sym),
                            "price": info.get("currentPrice") or info.get("previousClose"),
                            "pe": info.get("trailingPE"),
                            "change_pct": info.get("regularMarketChangePercent"),
                        }
                except Exception:
                    pass
            return result if result else None
        except Exception as e:
            logger.debug(f"yfinance batch_stock_prices: {e}")
        return None

    # ---- 工具 ----
    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """标准化股票代码"""
        symbol = symbol.strip()
        # 港股加 .HK 后缀
        if symbol.isdigit() and len(symbol) <= 5:
            return f"{int(symbol):04d}.HK"
        # A股 → 不管（yfinance 不适用）
        return symbol
