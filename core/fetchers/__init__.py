"""
多源数据采集框架
================
按优先级依次尝试多个数据源，主源失败自动降级到备用源。

设计要点：
- 每个数据源实现同一套 `fetch(method, **kwargs)` 协议，方法名统一为
  fund_list / fund_nav / realtime / holdings / macro / news 等语义化名称。
- 数据源「可用性」由依赖安装情况与所需 token 决定，未装依赖的源自动跳过而非报错。
- 降级链对上层透明：调用方只管 `msf.fetch("fund_nav", fund_code=...)`。

使用方式:
    from core.fetchers import MultiSourceFetcher

    msf = MultiSourceFetcher()
    nav = msf.fetch("fund_nav", fund_code="000001", years=3)
"""

import logging
import threading
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# 重入保护：记录本线程正在取数的 (数据源, 方法名)。
# 某些数据源实现内部会回调 MultiSourceFetcher（例如「先本地取、失败再走多源」），
# 若不加保护，一旦形成环就会无限递归直到栈溢出。
_inflight = threading.local()


def _guard_set() -> set:
    s = getattr(_inflight, "keys", None)
    if s is None:
        s = set()
        _inflight.keys = s
    return s


class DataSource:
    """
    单个数据源抽象基类。

    子类需要：
    - 覆写 `fetch(method, **kwargs)` 实现具体取数
    - 可选覆写 `is_available`（默认由子类在 `__init__` 中设置 `self._available`）
    """

    def __init__(
        self,
        name: str,
        priority: int,
        label: str = "",
        requires_token: bool = False,
        token_hint: str = "",
    ):
        self.name = name
        self.priority = priority            # 越小越优先
        self.label = label or name
        self.requires_token = requires_token
        self.token_hint = token_hint
        self.enabled = True
        self._last_error = None
        self._available = True

    def fetch(self, method: str, **kwargs) -> Optional[Any]:
        """子类实现具体的数据获取逻辑。取不到数据应返回 None，而不是抛异常。"""
        raise NotImplementedError

    @property
    def is_available(self) -> bool:
        """依赖装好、token 齐备且未被禁用时才算可用。"""
        return self.enabled and self._available

    @property
    def unavailable_reason(self) -> str:
        """不可用原因（供 UI 展示）。"""
        if not self.enabled:
            return "已被手动禁用"
        return getattr(self, "_unavailable_reason", "") or "依赖未满足"

    def set_available(self, ok: bool, reason: str = "") -> None:
        self._available = bool(ok)
        if reason:
            self._unavailable_reason = reason

    def __repr__(self):
        return f"DataSource({self.name}, priority={self.priority}, available={self.is_available})"


class MultiSourceFetcher:
    """
    多源数据协调器。

    使用方式:
        msf = MultiSourceFetcher()
        msf.register(akshare_source)
        msf.register(tushare_source)

        result = msf.fetch("fund_nav", fund_code="000001", years=3)
        # → 先尝试 akshare，失败自动 fallback tushare

        batch = msf.batch_fetch("fund_nav", [{"fund_code": "000001"}])
    """

    def __init__(self):
        self._sources: List[DataSource] = []
        self._last_source: Optional[str] = None

    def register(self, source: DataSource):
        """注册一个数据源（同名的会替换）"""
        self._sources = [s for s in self._sources if s.name != source.name]
        self._sources.append(source)
        self._sources.sort(key=lambda s: s.priority)

    def unregister(self, name: str):
        """移除一个数据源"""
        self._sources = [s for s in self._sources if s.name != name]

    @property
    def last_source(self) -> Optional[str]:
        """最近一次成功取数的数据源名（供 UI 展示数据来源）。"""
        return self._last_source

    def fetch(self, method: str, **kwargs) -> Optional[Any]:
        """
        依次尝试所有数据源，返回第一个成功的结果。

        Args:
            method: 语义化方法名（fund_nav / fund_holdings / macro_cpi …）
            **kwargs: 传递给各数据源的参数
        """
        for source in self._sources:
            if not source.is_available:
                continue
            guard_key = (source.name, method)
            if guard_key in _guard_set():
                # 本线程已在为该方法取数 → 跳过，避免自调用形成环
                logger.debug(f"[{source.name}] {method} 重入被拦截")
                continue
            try:
                _guard_set().add(guard_key)
                result = source.fetch(method, **kwargs)
                if _has_content(result):
                    self._last_source = source.name
                    return result
            except Exception as e:
                source._last_error = str(e)
                logger.debug(f"[{source.name}] {method} 失败: {e}")
                continue
            finally:
                _guard_set().discard(guard_key)
        return None

    def batch_fetch(self, method: str, items: List[dict], max_workers: int = 5) -> List[dict]:
        """
        并发批量获取。

        Args:
            method: 方法名
            items: 参数列表 [{fund_code: "000001", years: 3}, ...]
            max_workers: 并发数

        Returns:
            [{index, result, source, error}, ...]
        """
        results: List[Optional[dict]] = [None] * len(items)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.fetch, method, **kwargs): i
                for i, kwargs in enumerate(items)
            }
            for future in as_completed(futures):
                i = futures[future]
                try:
                    results[i] = {
                        "index": i, "result": future.result(),
                        "source": self._last_source, "error": None,
                    }
                except Exception as e:
                    results[i] = {"index": i, "result": None, "source": None, "error": str(e)}

        return [r for r in results if r is not None]

    def get_available_sources(self) -> List[str]:
        """列出已注册且可用的数据源名（注意：返回名字列表，供 UI 下拉使用）"""
        return [s.name for s in self._sources if s.is_available]

    def get_all_sources(self) -> List[Dict[str, Any]]:
        """列出所有数据源及其状态（含不可用原因）"""
        return [
            {
                "name": s.name,
                "label": s.label,
                "priority": s.priority,
                "enabled": s.enabled,
                "available": s.is_available,
                "reason": "" if s.is_available else s.unavailable_reason,
                "requires_token": s.requires_token,
            }
            for s in self._sources
        ]


def _has_content(result: Any) -> bool:
    """
    判断取数结果是否算「成功」。

    空 DataFrame / 空列表 / 空字典都视为失败，以便继续降级到下一个源。
    """
    if result is None:
        return False
    try:
        import pandas as pd
        if isinstance(result, pd.DataFrame):
            return not result.empty
        if isinstance(result, pd.Series):
            return not result.empty
    except Exception:
        pass
    if isinstance(result, (list, dict, str)):
        return len(result) > 0
    return True


# ============================================================
# 内置数据源实现
# ============================================================

class EastmoneySource(DataSource):
    """
    东方财富 / 天天基金直连（纯 HTTP，零额外依赖）。

    这是本系统实际的主力通道：通过 fund.eastmoney.com 的公开接口取净值、
    实时估值、基金列表与持仓，不依赖任何第三方库，因此在任何环境都可用。
    """

    def __init__(self):
        super().__init__("eastmoney", priority=1, label="东方财富 / 天天基金直连")
        self.set_available(True)

    def fetch(self, method: str, **kwargs) -> Optional[Any]:
        from .. import data_fetcher as df

        fetcher = df.get_fetcher()
        handlers = {
            "fund_list": lambda **kw: fetcher.get_fund_list(kw.get("fund_type")),
            "fund_nav": lambda **kw: fetcher.get_fund_nav_history(
                kw.get("fund_code", ""), years=int(kw.get("years", 3) or 3)
            ),
            "realtime": lambda **kw: fetcher.get_realtime_estimate(kw.get("fund_code", "")),
            "holdings": lambda **kw: fetcher.get_fund_holdings(kw.get("fund_code", "")),
            "fund_manager": lambda **kw: fetcher.get_fund_manager_info(kw.get("fund_code", "")),
            "index_valuation": lambda **kw: fetcher.get_index_valuation(kw.get("index_name", "")),
            "macro": lambda **kw: fetcher.get_macro_indicators(),
            "rating": lambda **kw: fetcher.get_fund_rating(kw.get("fund_code", "")),
        }
        handler = handlers.get(method)
        if handler is None:
            return None
        return handler(**kwargs)


class AkshareSource(DataSource):
    """
    AKShare 数据源（免 token，覆盖面最广）。

    仅用于补充东财直连拿不到的数据（如行业板块、部分宏观序列）。
    AKShare 依赖较重且接口偶有变更，故优先级低于直连通道。
    """

    def __init__(self):
        super().__init__("akshare", priority=2, label="AKShare（免费免 token）")
        self._ak = None
        try:
            import akshare as ak
            self._ak = ak
            self.set_available(True)
        except ImportError:
            self.set_available(False, "未安装：pip install akshare")

    def fetch(self, method: str, **kwargs) -> Optional[Any]:
        ak = self._ak
        if ak is None:
            return None
        handlers = {
            "fund_list": lambda **kw: ak.fund_name_em(),
            "fund_nav": lambda **kw: ak.fund_open_fund_info_em(
                symbol=kw.get("fund_code", ""), indicator="单位净值走势"
            ),
            "sector_board": lambda **kw: ak.stock_sector_spot(indicator="行业"),
            "macro_cpi": lambda **kw: ak.macro_china_cpi_monthly(),
            "macro_ppi": lambda **kw: ak.macro_china_ppi_yearly(),
            "macro_pmi": lambda **kw: ak.macro_china_pmi_yearly(),
        }
        handler = handlers.get(method)
        if handler is None:
            return None
        try:
            return handler(**kwargs)
        except Exception as e:
            logger.debug(f"[akshare] {method} 失败: {e}")
            return None


class BaostockSource(DataSource):
    """
    Baostock 数据源（免 token，日线为主）。

    适合做长周期指数与个股日线回测，稳定性好但数据品类较窄。
    """

    def __init__(self):
        super().__init__("baostock", priority=30, label="Baostock（免费免 token）")
        self._bs = None
        try:
            import baostock as bs
            self._bs = bs
            self.set_available(True)
        except ImportError:
            self.set_available(False, "未安装：pip install baostock")

    def fetch(self, method: str, **kwargs) -> Optional[Any]:
        if self._bs is None:
            return None
        if method != "index_daily":
            return None
        try:
            import pandas as pd
            from datetime import datetime, timedelta

            code = kwargs.get("index_code", "")
            bs_code = code if "." in code else f"sh.{code}"
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=365 * int(kwargs.get("years", 3) or 3))).strftime("%Y-%m-%d")

            self._bs.login()
            try:
                rs = self._bs.query_history_k_data_plus(
                    bs_code, "date,close", start_date=start, end_date=end, frequency="d"
                )
                rows = []
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    return None
                df = pd.DataFrame(rows, columns=["日期", "收盘"])
                df["收盘"] = pd.to_numeric(df["收盘"], errors="coerce")
                return df
            finally:
                self._bs.logout()
        except Exception as e:
            logger.debug(f"[baostock] index_daily 失败: {e}")
            return None


def build_default_fetcher(token: str = "") -> MultiSourceFetcher:
    """
    构建默认数据源降级链。

    顺序：东财直连 → AKShare → Tushare（需 token）→ Baostock → yfinance

    所有数据源都会被注册（包括当前不可用的），这样配置界面能把
    「装了但缺 token」「压根没装依赖」等状态如实展示给用户，
    而不是让它们凭空消失。取数时不可用的源会被自动跳过。
    """
    msf = MultiSourceFetcher()
    msf.register(EastmoneySource())
    msf.register(AkshareSource())

    try:
        from .tushare_fetcher import TushareFetcher
        msf.register(TushareFetcher())
    except Exception as e:
        logger.debug(f"Tushare 数据源注册失败: {e}")

    msf.register(BaostockSource())

    try:
        from .yfinance_fetcher import YFinanceFetcher
        msf.register(YFinanceFetcher())
    except Exception as e:
        logger.debug(f"yfinance 数据源注册失败: {e}")

    return msf
