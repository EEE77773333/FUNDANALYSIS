"""
组合管理系统
============
投资组合的创建、持仓管理、数据导入和风险分析。

核心能力:
    - 组合 CRUD（增删改查）
    - 持仓管理（手动添加 + CSV/Excel 导入 + 权重调整）
    - 风险分析（集中度、回撤、相关性、综合指标）
    - 净值跟踪（合成净值序列 + 快照记录）

使用方式:
    from core.portfolio import get_portfolio_manager

    pm = get_portfolio_manager()
    pid = pm.create("我的基金组合", "长期定投策略")
    pm.add_holding(pid, "000001", 10000, 0.3)
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from .db import get_connection, now_iso, get_user_id
from .data_fetcher import get_fetcher
from .utils import (
    safe_float,
    safe_int,
    fmt_pct,
    calc_annualized_return,
    calc_max_drawdown,
    calc_sharpe_ratio,
    calc_annual_volatility,
    calc_win_rate,
)


# ============================================================
# 数据类
# ============================================================

class Portfolio:
    """组合数据类"""

    def __init__(self, row):
        # sqlite3.Row 不支持 .get()，统一转为 dict
        if not isinstance(row, dict):
            row = dict(row)
        self.id = row["id"]
        self.name = row["name"]
        self.description = row.get("description", "")
        self.created_at = row["created_at"]
        self.updated_at = row["updated_at"]
        self.holdings: List[Dict[str, Any]] = []
        self._holdings_loaded = False

    def load_holdings(self):
        """从数据库加载持仓"""
        if self._holdings_loaded:
            return
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM portfolio_holdings WHERE portfolio_id = ? ORDER BY weight DESC",
                (self.id,),
            ).fetchall()
            self.holdings = [dict(r) for r in rows]
        self._holdings_loaded = True

    @property
    def holding_count(self) -> int:
        if not self._holdings_loaded:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM portfolio_holdings WHERE portfolio_id = ?",
                    (self.id,),
                ).fetchone()
                return row["cnt"] if row else 0
        return len(self.holdings)

    @property
    def total_weight(self) -> float:
        if self._holdings_loaded:
            return sum(h.get("weight", 0) for h in self.holdings)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT SUM(weight) as total FROM portfolio_holdings WHERE portfolio_id = ?",
                (self.id,),
            ).fetchone()
            return safe_float(row["total"]) if row else 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "holding_count": self.holding_count,
            "total_weight": self.total_weight,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "holdings": self.holdings if self._holdings_loaded else [],
        }


# ============================================================
# 组合管理器
# ============================================================

class PortfolioManager:
    """组合 CRUD + 导入 + 风险分析"""

    # ---- CRUD ----

    def create(self, name: str, description: str = "") -> int:
        """创建新组合，返回组合 ID"""
        uid = get_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO portfolios (user_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (uid, name, description, now_iso(), now_iso()),
            )
            return cursor.lastrowid

    def get(self, portfolio_id: int) -> Optional[Portfolio]:
        """获取单个组合（含持仓）"""
        uid = get_user_id()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM portfolios WHERE id = ? AND user_id = ?", (portfolio_id, uid)
            ).fetchone()
            if not row:
                return None
            p = Portfolio(row)
            p.load_holdings()
            return p

    def list_all(self) -> List[Portfolio]:
        """列出当前用户的所有组合"""
        uid = get_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM portfolios WHERE user_id = ? ORDER BY updated_at DESC", (uid,)
            ).fetchall()
            return [Portfolio(r) for r in rows]

    def update(self, portfolio_id: int, name: str = None, description: str = None):
        """更新组合名称/描述"""
        fields = []
        values = []
        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if fields:
            fields.append("updated_at = ?")
            values.append(now_iso())
            values.append(portfolio_id)
            uid = get_user_id()
            with get_connection() as conn:
                conn.execute(
                    f"UPDATE portfolios SET {', '.join(fields)} WHERE id = ? AND user_id = ?",
                    values + [uid],
                )

    def delete(self, portfolio_id: int):
        """删除组合及其持仓和快照"""
        uid = get_user_id()
        with get_connection() as conn:
            conn.execute("DELETE FROM portfolio_nav_snapshots WHERE portfolio_id = ? AND user_id = ?", (portfolio_id, uid))
            conn.execute("DELETE FROM portfolio_holdings WHERE portfolio_id = ? AND user_id = ?", (portfolio_id, uid))
            conn.execute("DELETE FROM portfolios WHERE id = ? AND user_id = ?", (portfolio_id, uid))

    # ---- 持仓管理 ----

    def add_holding(
        self,
        portfolio_id: int,
        fund_code: str,
        amount: float = 0,
        weight: float = 0,
        purchase_date: str = "",
        notes: str = "",
    ):
        """添加持仓。自动通过 DataFetcher 解析基金名称"""
        fund_name = ""
        try:
            fetcher = get_fetcher()
            info = fetcher.get_fund_manager_info(fund_code)
            if info:
                fund_name = info.get("基金名称", "")
        except Exception:
            pass

        uid = get_user_id()
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO portfolio_holdings
                   (portfolio_id, user_id, fund_code, fund_name, amount, weight, purchase_date, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (portfolio_id, uid, fund_code, fund_name, amount, weight, purchase_date, notes),
            )
            conn.execute(
                "UPDATE portfolios SET updated_at = ? WHERE id = ?",
                (now_iso(), portfolio_id),
            )

    def remove_holding(self, portfolio_id: int, fund_code: str):
        """移除持仓"""
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM portfolio_holdings WHERE portfolio_id = ? AND fund_code = ?",
                (portfolio_id, fund_code),
            )
            conn.execute(
                "UPDATE portfolios SET updated_at = ? WHERE id = ?",
                (now_iso(), portfolio_id),
            )

    def update_holding(self, portfolio_id: int, fund_code: str, **kwargs):
        """更新持仓字段（amount, weight, notes 等）"""
        allowed = {"amount", "weight", "purchase_date", "notes", "fund_name"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [portfolio_id, fund_code]
        with get_connection() as conn:
            conn.execute(
                f"UPDATE portfolio_holdings SET {set_clause} WHERE portfolio_id = ? AND fund_code = ?",
                values,
            )
            conn.execute(
                "UPDATE portfolios SET updated_at = ? WHERE id = ?",
                (now_iso(), portfolio_id),
            )

    def get_holdings_df(self, portfolio_id: int) -> pd.DataFrame:
        """获取持仓 DataFrame"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM portfolio_holdings WHERE portfolio_id = ? ORDER BY weight DESC",
                (portfolio_id,),
            ).fetchall()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([dict(r) for r in rows])

    # ---- 导入 ----

    def import_from_dataframe(self, portfolio_id: int, df: pd.DataFrame) -> int:
        """
        从 DataFrame 导入持仓。自动匹配列名。

        Expected columns: fund_code (required), fund_name, amount, weight, purchase_date, notes
        使用 smart_import 的列名别名匹配（如果可用）。

        Returns: 导入的持仓数量
        """
        # 尝试使用 smart_import（如果已安装）
        try:
            from .smart_import import normalize_dataframe
            df = normalize_dataframe(df)
        except ImportError:
            # 回退：尝试基本列名匹配
            col_map = {}
            for col in df.columns:
                col_lower = str(col).lower().strip()
                if "代码" in col_lower or col_lower in ("fund_code", "code", "symbol", "fcode"):
                    col_map["fund_code"] = col
                elif "名称" in col_lower or col_lower in ("fund_name", "name", "fundname"):
                    col_map["fund_name"] = col
                elif "金额" in col_lower or col_lower in ("amount", "value", "market_value"):
                    col_map["amount"] = col
                elif "权重" in col_lower or col_lower in ("weight", "ratio", "pct", "allocation"):
                    col_map["weight"] = col
            if "fund_code" in col_map:
                rename_map = {v: k for k, v in col_map.items()}
                df = df.rename(columns=rename_map)

        if "fund_code" not in df.columns:
            raise ValueError("未找到基金代码列。请确保 CSV/Excel 包含「基金代码」或类似命名的列。")

        count = 0
        for _, row in df.iterrows():
            code = str(row.get("fund_code", "")).strip()
            if not code or code == "nan":
                continue
            # 确保6位数字
            code = code.zfill(6) if code.isdigit() and len(code) <= 6 else code
            name = str(row.get("fund_name", "")).strip() if "fund_name" in df.columns else ""
            if name == "nan":
                name = ""
            amount = safe_float(row.get("amount", 0))
            weight = safe_float(row.get("weight", 0))
            purchase_date = str(row.get("purchase_date", "")) if "purchase_date" in df.columns else ""
            notes = str(row.get("notes", "")) if "notes" in df.columns else ""

            self.add_holding(portfolio_id, code, amount, weight, purchase_date, notes)
            count += 1

        return count

    def import_from_csv(self, portfolio_id: int, file_content: bytes) -> int:
        """从 CSV 字节内容导入"""
        # 编码检测
        for enc in ["utf-8", "gbk", "gb2312", "utf-8-sig"]:
            try:
                df = pd.read_csv(pd.io.common.BytesIO(file_content), encoding=enc)
                break
            except (UnicodeDecodeError, TypeError):
                continue
        else:
            df = pd.read_csv(pd.io.common.BytesIO(file_content), encoding="utf-8", errors="replace")
        return self.import_from_dataframe(portfolio_id, df)

    def import_from_excel(self, portfolio_id: int, file_content: bytes, sheet_name=0) -> int:
        """从 Excel 字节内容导入（需要 openpyxl）"""
        try:
            df = pd.read_excel(pd.io.common.BytesIO(file_content), sheet_name=sheet_name)
        except ImportError:
            raise ImportError("需要安装 openpyxl: pip install openpyxl")
        return self.import_from_dataframe(portfolio_id, df)

    # ---- 风险分析 ----

    def _get_nav_for_funds(
        self, fund_codes: List[str], years: int = 3
    ) -> Dict[str, pd.DataFrame]:
        """批量获取多只基金的净值数据（并发）"""
        fetcher = get_fetcher()
        result = {}
        try:
            df_all = fetcher.batch_get_nav_and_info(fund_codes, years=years, max_workers=5)
            if df_all is not None and not df_all.empty:
                for code in fund_codes:
                    subset = df_all[df_all["基金代码"] == code]
                    if not subset.empty:
                        result[code] = subset
                return result
        except Exception:
            pass
        # 回退：逐只获取
        for code in fund_codes:
            try:
                nav_df = fetcher.get_fund_nav_history(code, years=years)
                if nav_df is not None and not nav_df.empty:
                    result[code] = nav_df
            except Exception:
                pass
        return result

    def _build_portfolio_nav(
        self, nav_dict: Dict[str, pd.DataFrame], weights: Dict[str, float]
    ) -> pd.Series:
        """
        构建加权合成净值序列。
        以最早的共同日期为起点，按权重加总每日收益率。
        """
        if not nav_dict or not weights:
            return pd.Series(dtype=float)

        # 收集所有基金的日收益率序列
        return_series = {}
        for code, nav_df in nav_dict.items():
            if code not in weights or weights[code] == 0:
                continue
            df = nav_df.copy()
            if "日期" not in df.columns or df.empty:
                continue
            df["日期"] = pd.to_datetime(df["日期"])
            df = df.sort_values("日期")
            if "单位净值" not in df.columns:
                continue
            df["return"] = df["单位净值"].pct_change()
            df = df.dropna(subset=["return"])
            df = df.set_index("日期")
            return_series[code] = df["return"]

        if not return_series:
            return pd.Series(dtype=float)

        # 合并所有收益率到统一日期索引
        all_returns = pd.DataFrame(return_series)
        all_returns = all_returns.dropna(how="all")

        # 加权平均收益率
        total_weight = sum(weights.get(c, 0) for c in all_returns.columns)
        if total_weight == 0:
            return pd.Series(dtype=float)

        weighted_return = pd.Series(0.0, index=all_returns.index)
        for col in all_returns.columns:
            w = weights.get(col, 0) / total_weight
            weighted_return += all_returns[col].fillna(0) * w

        # 累积收益率 → 净值（基准=1.0）
        portfolio_nav = (1 + weighted_return).cumprod()
        portfolio_nav.name = "组合净值"
        return portfolio_nav

    def analyze_concentration(self, portfolio_id: int) -> dict:
        """分析持仓集中度"""
        holdings_df = self.get_holdings_df(portfolio_id)
        if holdings_df.empty:
            return {
                "top3_weight": 0, "top5_weight": 0,
                "hhi_index": 0, "max_single_weight": 0,
                "fund_type_breakdown": {},
            }

        weights = holdings_df["weight"].fillna(0).tolist()
        sorted_weights = sorted(weights, reverse=True)
        top3 = sum(sorted_weights[:3])
        top5 = sum(sorted_weights[:5])
        max_single = sorted_weights[0] if sorted_weights else 0
        # HHI (Herfindahl-Hirschman Index)
        hhi = sum((w * 100) ** 2 for w in weights)

        # 获取基金类型分布
        fund_types = {}
        fetcher = get_fetcher()
        for _, row in holdings_df.iterrows():
            code = row["fund_code"]
            try:
                info = fetcher.get_fund_manager_info(code)
                if info:
                    ftype = info.get("基金类型", "未知")
                    fund_types[ftype] = fund_types.get(ftype, 0) + row.get("weight", 0)
            except Exception:
                pass

        return {
            "top3_weight": round(top3, 4),
            "top5_weight": round(top5, 4),
            "hhi_index": round(hhi, 1),
            "max_single_weight": round(max_single, 4),
            "fund_type_breakdown": fund_types,
        }

    def analyze_drawdown(self, portfolio_id: int, years: int = 3) -> dict:
        """计算组合最大回撤"""
        p = self.get(portfolio_id)
        if not p or not p.holdings:
            return {"max_drawdown": 0, "max_drawdown_days": 0, "current_drawdown": 0}

        weights = {h["fund_code"]: h.get("weight", 1) for h in p.holdings}
        nav_dict = self._get_nav_for_funds(list(weights.keys()), years=years)
        nav_series = self._build_portfolio_nav(nav_dict, weights)

        if nav_series.empty:
            return {"max_drawdown": 0, "max_drawdown_days": 0, "current_drawdown": 0}

        # 计算回撤序列
        rolling_max = nav_series.cummax()
        drawdown = (nav_series - rolling_max) / rolling_max

        max_dd = drawdown.min()
        # 最大回撤持续天数（近似）
        dd_end = drawdown.idxmin()
        dd_start = rolling_max[:dd_end].idxmax() if pd.notna(dd_end) else None
        dd_days = (dd_end - dd_start).days if dd_start and dd_end else 0
        current_dd = drawdown.iloc[-1] if len(drawdown) > 0 else 0

        return {
            "max_drawdown": round(float(max_dd), 4),
            "max_drawdown_days": int(dd_days),
            "current_drawdown": round(float(current_dd), 4),
        }

    def analyze_correlation(self, portfolio_id: int, years: int = 2) -> pd.DataFrame:
        """计算持仓基金之间的收益率相关性矩阵"""
        p = self.get(portfolio_id)
        if not p or len(p.holdings) < 2:
            return pd.DataFrame()

        codes = [h["fund_code"] for h in p.holdings]
        nav_dict = self._get_nav_for_funds(codes, years=years)

        # 收集每日收益率
        return_data = {}
        for code, nav_df in nav_dict.items():
            df = nav_df.copy()
            if "日期" not in df.columns or df.empty:
                continue
            df["日期"] = pd.to_datetime(df["日期"])
            df = df.sort_values("日期")
            if "单位净值" not in df.columns:
                continue
            df["return"] = df["单位净值"].pct_change()
            df = df.dropna(subset=["return"])
            return_data[code] = df.set_index("日期")["return"]

        if len(return_data) < 2:
            return pd.DataFrame()

        returns_df = pd.DataFrame(return_data).dropna()
        if returns_df.empty:
            return pd.DataFrame()

        corr = returns_df.corr()
        # 用基金名称替换代码作为标签
        name_map = {}
        for h in p.holdings:
            name_map[h["fund_code"]] = h.get("fund_name", h["fund_code"])[:8]
        corr = corr.rename(index=name_map, columns=name_map)
        return corr

    def compute_portfolio_metrics(self, portfolio_id: int) -> dict:
        """计算组合综合指标：年化收益、波动率、Sharpe 等"""
        p = self.get(portfolio_id)
        if not p or not p.holdings:
            return {}

        weights = {h["fund_code"]: h.get("weight", 1) for h in p.holdings}
        nav_dict = self._get_nav_for_funds(list(weights.keys()), years=3)
        nav_series = self._build_portfolio_nav(nav_dict, weights)

        if nav_series.empty:
            return {}

        returns = nav_series.pct_change().dropna()

        return {
            "annualized_return": round(calc_annualized_return(nav_series), 4),
            "annual_volatility": round(calc_annual_volatility(returns), 4),
            "sharpe_ratio": round(calc_sharpe_ratio(returns), 4),
            "max_drawdown": round(calc_max_drawdown(nav_series), 4),
            "win_rate": round(calc_win_rate(returns), 4),
        }

    # ---- 净值跟踪 ----

    def get_nav_series(self, portfolio_id: int, years: int = 3) -> pd.Series:
        """计算组合合成净值序列"""
        p = self.get(portfolio_id)
        if not p or not p.holdings:
            return pd.Series(dtype=float)

        weights = {h["fund_code"]: h.get("weight", 1) for h in p.holdings}
        nav_dict = self._get_nav_for_funds(list(weights.keys()), years=years)
        return self._build_portfolio_nav(nav_dict, weights)

    def save_nav_snapshot(self, portfolio_id: int, total_value: float):
        """保存当前净值快照"""
        # 计算当日收益率（相比最近一个快照）
        with get_connection() as conn:
            prev = conn.execute(
                "SELECT total_value FROM portfolio_nav_snapshots WHERE portfolio_id = ? ORDER BY date DESC LIMIT 1",
                (portfolio_id,),
            ).fetchone()
            daily_return = 0.0
            if prev and prev["total_value"] > 0:
                daily_return = (total_value - prev["total_value"]) / prev["total_value"]

            conn.execute(
                "INSERT INTO portfolio_nav_snapshots (portfolio_id, date, total_value, daily_return) VALUES (?, ?, ?, ?)",
                (portfolio_id, datetime.utcnow().strftime("%Y-%m-%d"), total_value, round(daily_return, 6)),
            )

    def get_nav_history(self, portfolio_id: int) -> pd.DataFrame:
        """获取已记录的快照历史"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT date, total_value, daily_return FROM portfolio_nav_snapshots WHERE portfolio_id = ? ORDER BY date",
                (portfolio_id,),
            ).fetchall()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([dict(r) for r in rows])


# ============================================================
# 单例
# ============================================================

import threading

_portfolio_manager: Optional[PortfolioManager] = None
_portfolio_manager_lock = threading.Lock()


def get_portfolio_manager() -> PortfolioManager:
    """获取 PortfolioManager 全局单例（线程安全）"""
    global _portfolio_manager
    if _portfolio_manager is None:
        with _portfolio_manager_lock:
            if _portfolio_manager is None:
                _portfolio_manager = PortfolioManager()
    return _portfolio_manager
