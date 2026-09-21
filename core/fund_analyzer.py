"""
基金深度分析器
==============
晨星九宫格风格箱 · 四机构评级 · 好买性价比评分
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from .data_fetcher import get_fetcher, AKSHARE_AVAILABLE

# ============================================================
# 一、多机构评级获取
# ============================================================

def get_multi_agency_ratings() -> pd.DataFrame:
    """
    获取四机构评级数据：晨星 + 上海证券 + 招商证券 + 济安金信。

    Returns:
        DataFrame: 基金代码、简称、四机构评级(1-5)、5星评级家数
    """
    if not AKSHARE_AVAILABLE:
        return pd.DataFrame()

    import akshare as ak
    try:
        df = ak.fund_rating_all()
        if df is not None and not df.empty:
            df = df.rename(columns={
                "代码": "基金代码", "简称": "基金简称",
                "晨星评级": "晨星", "上海证券": "上海证券",
                "招商证券": "招商证券", "济安金信": "济安金信",
                "5星评级家数": "五星家数", "基金经理": "基金经理",
                "基金公司": "基金公司", "手续费": "手续费", "类型": "基金类型",
            })
            # 转换评分为数值
            for col in ["晨星", "上海证券", "招商证券", "济安金信"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
    except Exception:
        pass
    return pd.DataFrame()


def get_fund_ratings_by_code(code: str) -> Dict[str, Any]:
    """获取单只基金的多机构评级。"""
    df = get_multi_agency_ratings()
    if df.empty:
        return {}
    match = df[df["基金代码"].astype(str).str.zfill(6) == code]
    if match.empty:
        return {}
    row = match.iloc[0]
    return {
        "晨星": int(row["晨星"]) if pd.notna(row.get("晨星")) else None,
        "上海证券": int(row["上海证券"]) if pd.notna(row.get("上海证券")) else None,
        "招商证券": int(row["招商证券"]) if pd.notna(row.get("招商证券")) else None,
        "济安金信": int(row["济安金信"]) if pd.notna(row.get("济安金信")) else None,
        "五星家数": int(row["五星家数"]) if pd.notna(row.get("五星家数")) else 0,
        "综合评分": _calc_rating_score(row),
    }


def _calc_rating_score(row) -> float:
    """计算综合评级分（加权平均，忽略NaN）。"""
    scores = []
    for col in ["晨星", "上海证券", "招商证券", "济安金信"]:
        v = row.get(col)
        if pd.notna(v) and v > 0:
            scores.append(float(v))
    return round(np.mean(scores), 1) if scores else 0


# ============================================================
# 二、晨星九宫格风格箱
# ============================================================

STYLE_BOX = {
    ("大盘", "价值"): "大盘价值",
    ("大盘", "均衡"): "大盘均衡",
    ("大盘", "成长"): "大盘成长",
    ("中盘", "价值"): "中盘价值",
    ("中盘", "均衡"): "中盘均衡",
    ("中盘", "成长"): "中盘成长",
    ("小盘", "价值"): "小盘价值",
    ("小盘", "均衡"): "小盘均衡",
    ("小盘", "成长"): "小盘成长",
}


def classify_style_box(code: str) -> Dict[str, Any]:
    """
    基于持仓数据将基金分类到晨星九宫格。

    分类逻辑：
    - 市值维度：重仓股平均市值 → 大盘(>500亿) / 中盘(100-500亿) / 小盘(<100亿)
    - 估值维度：重仓股平均PE分位 → 价值(<30%分位) / 均衡(30-70%) / 成长(>70%)

    Returns:
        {"style": "大盘成长", "market_cap": "大盘", "valuation": "成长",
         "avg_mcap": 850亿, "avg_pe_pct": 75%, "confidence": "高"}
    """
    fetcher = get_fetcher()
    holdings = fetcher.get_fund_holdings(code)
    if holdings is None or holdings.empty:
        return {"style": "数据不足", "confidence": "无"}

    # 获取每只重仓股的市值和PE
    mcap_values = []
    pe_values = []

    for _, row in holdings.iterrows():
        stock_code = str(row.get("股票代码", ""))
        if not stock_code or len(stock_code) < 6:
            continue
        weight = float(row.get("占净值比例%", 0))
        if weight <= 0:
            continue

        # 获取个股基本信息
        try:
            import akshare as ak
            info = ak.stock_individual_info_em(symbol=stock_code)
            if info is not None and not info.empty:
                info_dict = dict(zip(info["item"], info["value"]))
                total_mv = float(info_dict.get("总市值", 0)) / 1e8  # 转为亿
                pe = float(info_dict.get("市盈率-动态", 0))
                if total_mv > 0:
                    mcap_values.append((total_mv, weight))
                if pe > 0:
                    pe_values.append((pe, weight))
        except Exception:
            pass

    if not mcap_values:
        return {"style": "数据不足", "confidence": "低"}

    # 加权平均市值
    total_w = sum(w for _, w in mcap_values)
    avg_mcap = sum(m * w for m, w in mcap_values) / total_w if total_w > 0 else 0

    # 市值分类
    if avg_mcap > 500:
        mcap_class = "大盘"
    elif avg_mcap > 100:
        mcap_class = "中盘"
    else:
        mcap_class = "小盘"

    # 加权平均PE
    if pe_values:
        pe_total_w = sum(w for _, w in pe_values)
        avg_pe = sum(p * w for p, w in pe_values) / pe_total_w
        # 简化：PE>50=成长，PE<20=价值
        if avg_pe > 50:
            val_class = "成长"
        elif avg_pe > 20:
            val_class = "均衡"
        else:
            val_class = "价值"
    else:
        val_class = "均衡"

    style = STYLE_BOX.get((mcap_class, val_class), f"{mcap_class}{val_class}")
    confidence = "高" if len(mcap_values) >= 5 else "中" if len(mcap_values) >= 3 else "低"

    return {
        "style": style,
        "market_cap": mcap_class,
        "valuation": val_class,
        "avg_mcap_亿": round(avg_mcap, 1),
        "avg_pe": round(avg_pe, 1) if pe_values else None,
        "样本数": len(mcap_values),
        "confidence": confidence,
    }


def style_box_card(style_info: dict) -> str:
    """生成风格箱HTML卡片。"""
    style = style_info.get("style", "未知")
    box = style_info.get("market_cap", "?") + "×" + style_info.get("valuation", "?")
    return (
        f'<span style="display:inline-block;padding:4px 12px;border-radius:6px;'
        f'background:#3B82F620;color:#3B82F6;font-weight:600;margin-right:8px;">'
        f'📦 {style}</span>'
    )


# ============================================================
# 三、好买基金性价比评分
# ============================================================

def calc_howbuy_score(code: str) -> Dict[str, Any]:
    """
    计算好买风格的性价比综合评分（0-100分）。

    评分维度：
    - 收益能力 (35%)：3年年化超额收益
    - 风控能力 (30%)：最大回撤 + 下行波动
    - 费率效率 (15%)：综合费率越低越好
    - 经理稳定性 (10%)：任职年限
    - 规模适配 (10%)：规模在策略舒适区

    Returns:
        {"total": 78.5, "收益": 28.0, "风控": 22.5, "费率": 12.0, "经理": 8.0, "规模": 8.0}
    """
    from .utils import calc_annualized_return, calc_max_drawdown, calc_sortino_ratio, safe_float

    fetcher = get_fetcher()
    nav = fetcher.get_fund_nav_history(code, years=3)
    info = fetcher.get_fund_manager_info(code)

    if nav.empty or "单位净值" not in nav.columns:
        return {"total": 0, "error": "无净值数据"}

    nav_s = nav.sort_values("日期", ascending=True)["单位净值"].dropna()
    rets = nav_s.pct_change().dropna()

    if len(nav_s) < 100:
        return {"total": 0, "error": "数据不足"}

    # 收益维度 (满分35)
    ann_ret = calc_annualized_return(nav_s)
    excess = max(0, ann_ret - 0.025)  # 超额收益 vs 2.5%无风险
    return_score = min(35, excess * 100 * 0.7)  # 简化映射

    # 风控维度 (满分30)
    max_dd = calc_max_drawdown(nav_s)
    sortino = calc_sortino_ratio(rets)
    dd_score = max(0, 15 - abs(max_dd) * 50)  # 回撤越小越好
    sortino_score = min(15, sortino * 7.5)  # 索提诺映射
    risk_score = dd_score + sortino_score

    # 费率维度 (满分15)
    fee = safe_float(info.get("管理费率%", 1.5) if info else 1.5)
    fee_score = max(0, 15 - fee * 10)  # 费率越低越好

    # 经理维度 (满分10)
    tenure = safe_float(str(info.get("从业年限", "3")).replace("年", "")) if info else 3
    mgr_score = min(10, tenure * 2)  # 5年=满分

    # 规模维度 (满分10)
    size_str = info.get("最新规模", "0") if info else "0"
    import re
    m = re.search(r'([\d.]+)', str(size_str))
    scale = float(m.group(1)) if m else 0
    if 20 <= scale <= 100:
        scale_score = 10
    elif 10 <= scale <= 150:
        scale_score = 7
    else:
        scale_score = 4

    total = return_score + risk_score + fee_score + mgr_score + scale_score

    return {
        "total": round(total, 1),
        "收益能力": round(return_score, 1),
        "风控能力": round(risk_score, 1),
        "费率效率": round(fee_score, 1),
        "经理稳定": round(mgr_score, 1),
        "规模适配": round(scale_score, 1),
        "等级": _score_grade(total),
    }


def _score_grade(total: float) -> str:
    if total >= 80: return "🏅 卓越"
    if total >= 65: return "🥈 优秀"
    if total >= 50: return "🥉 良好"
    if total >= 35: return "⚪ 一般"
    return "🔴 待观察"
