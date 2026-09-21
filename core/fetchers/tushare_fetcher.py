"""
Tushare 数据源适配器
====================
提供 A 股财务数据、基金完整持仓、经理业绩等增强数据。

需要: pip install tushare
配置: 
    - 自部署用户：.env 中设置 TUSHARE_TOKEN=your_token
    - 云托管用户：在「账户设置 → 行情数据源」里填写自己的 token

设计说明：
    token 在**每次取数时动态解析**，而不是在模块导入时固化。
    否则用户在界面上填完 token 必须重启进程才生效，体验很差。
"""

import logging
from typing import Optional, Any
import pandas as pd

from . import DataSource

logger = logging.getLogger(__name__)

try:
    import tushare as ts
    _TS_PKG_AVAILABLE = True
except ImportError:
    ts = None
    _TS_PKG_AVAILABLE = False


def _resolve_token() -> str:
    """
    按优先级取当前生效的 Tushare token：
    用户账户配置（BYOK）> .env
    """
    try:
        from core.user_integrations import resolve_data_source_config
        token = (resolve_data_source_config() or {}).get("tushare_token", "")
        if token:
            return str(token).strip()
    except Exception:
        pass
    try:
        from core.config import config
        return str(getattr(config, "tushare_token", "") or "").strip()
    except Exception:
        return ""


class TushareFetcher(DataSource):
    """Tushare 数据源（优先级 20，作为东财与 AKShare 的增强/补充通道）"""

    def __init__(self):
        super().__init__(
            "tushare",
            priority=20,
            label="Tushare（需 token，数据质量更好）",
            requires_token=True,
            token_hint="在 tushare.pro 免费注册后于个人中心获取 token",
        )
        self._pro_client = None
        self._pro_token = None

    @property
    def is_available(self) -> bool:
        if not self.enabled:
            return False
        if not _TS_PKG_AVAILABLE:
            return False
        return bool(_resolve_token())

    @property
    def unavailable_reason(self) -> str:
        if not self.enabled:
            return "已被手动禁用"
        if not _TS_PKG_AVAILABLE:
            return "未安装：pip install tushare"
        if not _resolve_token():
            return "未配置 token（可在「账户设置 → 行情数据源」填写）"
        return ""

    @property
    def pro(self):
        """按当前生效 token 获取 pro 客户端（token 变了会自动重建）。"""
        token = _resolve_token()
        if not token:
            return None
        if self._pro_client is None or self._pro_token != token:
            self._pro_client = ts.pro_api(token)
            self._pro_token = token
            logger.info("Tushare 数据源已就绪（token 尾号 …%s）", token[-4:])
        return self._pro_client

    def fetch(self, method: str, **kwargs) -> Optional[Any]:
        pro = self.pro
        if pro is None:
            return None
        handlers = {
            "fund_nav": self._fund_nav,
            "fund_holdings": self._fund_holdings,
            "fund_manager": self._fund_manager,
            "stock_financials": self._stock_financials,
            "index_daily": self._index_daily,
            "macro_cpi": self._macro_cpi,
            "macro_ppi": self._macro_ppi,
            "macro_money": self._macro_money,
        }
        handler = handlers.get(method)
        if handler is None:
            return None
        try:
            return handler(pro=pro, **kwargs)
        except Exception as e:
            logger.debug(f"[tushare] {method} 失败: {e}")
            return None

    # ---- 基金净值 ----
    def _fund_nav(self, pro, fund_code: str, years: int = 3, **kwargs) -> Optional[pd.DataFrame]:
        """获取基金净值历史（Tushare 通常有更长历史）"""
        try:
            df = pro.fund_nav(ts_code=fund_code + ".OF")
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "nav_date": "日期", "unit_nav": "单位净值",
                    "accum_nav": "累计净值",
                })
                df["日期"] = pd.to_datetime(df["日期"])
                return df.sort_values("日期")
        except Exception as e:
            logger.debug(f"Tushare fund_nav 失败: {e}")
        return None

    # ---- 基金持仓（完整，非仅前十大） ----
    def _fund_holdings(self, pro, fund_code: str, **kwargs) -> Optional[pd.DataFrame]:
        """获取基金全部持仓（Tushare 提供完整持仓，东财/天天基金仅前十大）"""
        try:
            df = pro.fund_portfolio(ts_code=fund_code + ".OF")
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "stock_code": "股票代码", "stock_name": "股票名称",
                    "mkv": "持仓市值", "amount": "持股数量",
                    "stk_mkv_ratio": "占净值比例",
                })
                df["占净值比例"] = pd.to_numeric(df["占净值比例"], errors="coerce")
                return df
        except Exception as e:
            logger.debug(f"Tushare fund_portfolio 失败: {e}")
        return None

    # ---- 基金经理 ----
    def _fund_manager(self, pro, fund_code: str, **kwargs) -> Optional[dict]:
        """获取基金经理详细履历"""
        try:
            df = pro.fund_manager(ts_code=fund_code + ".OF")
            if df is not None and not df.empty:
                row = df.iloc[0]
                return {
                    "基金经理": row.get("name", ""),
                    "任职起始": str(row.get("begin_date", "")),
                    "任职天数": int(row.get("days", 0)),
                    "历史回报": float(row.get("return_rate", 0)) if row.get("return_rate") else None,
                    "管理规模": float(row.get("fund_size", 0)) if row.get("fund_size") else None,
                }
        except Exception:
            pass
        return None

    # ---- 底层股票财务数据 ----
    def _stock_financials(self, pro, stock_code: str, **kwargs) -> Optional[dict]:
        """获取底层持仓股票的财务指标"""
        try:
            df = pro.fina_indicator(ts_code=stock_code)
            if df is not None and not df.empty:
                latest = df.iloc[0]
                return {
                    "ROE": float(latest.get("roe", 0)),
                    "ROA": float(latest.get("roa", 0)),
                    "毛利率": float(latest.get("grossprofit_margin", 0)),
                    "净利率": float(latest.get("netprofit_margin", 0)),
                    "资产负债率": float(latest.get("debt_to_assets", 0)),
                }
        except Exception:
            pass
        return None

    # ---- 指数日线 ----
    def _index_daily(self, pro, index_code: str, **kwargs) -> Optional[pd.DataFrame]:
        """获取指数日线数据"""
        try:
            code_map = {
                "000300": "000300.SH", "000905": "000905.SH",
                "000016": "000016.SH", "399006": "399006.SZ",
            }
            ts_code = code_map.get(index_code, index_code + ".SH")
            df = pro.index_daily(ts_code=ts_code)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
        return None

    # ---- 宏观指标 ----
    def _macro_cpi(self, pro, **kwargs) -> Optional[pd.DataFrame]:
        try: return pro.cn_cpi()
        except Exception: return None

    def _macro_ppi(self, pro, **kwargs) -> Optional[pd.DataFrame]:
        try: return pro.cn_ppi()
        except Exception: return None

    def _macro_money(self, pro, **kwargs) -> Optional[pd.DataFrame]:
        try: return pro.cn_m()
        except Exception: return None
