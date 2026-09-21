"""
智能导入工具
============
解析 CSV/Excel/剪贴板/自由文本中的基金代码和名称，
自动映射列名、批量解析、校验基金代码有效性。

使用方式:
    from core.smart_import import parse_csv, normalize_dataframe, batch_resolve_and_validate

    # 解析上传的 CSV
    df = parse_csv(file_bytes)
    df = normalize_dataframe(df)

    # 从自由文本提取基金代码
    codes = extract_fund_codes_from_text("推荐: 000001, 110011, 还有华夏成长")
"""

import re
import io
import pandas as pd
from typing import Optional, List, Dict, Tuple

from .data_fetcher import get_fetcher


# ============================================================
# 列名别名映射
# ============================================================

FUND_CODE_ALIASES = [
    "fund_code", "基金代码", "code", "代码", "fundcode", "fund id",
    "fcode", "symbol", "ticker", "secid", "基金编号", "产品代码",
    "fund", "基金",
]
FUND_NAME_ALIASES = [
    "fund_name", "基金名称", "name", "名称", "fundname", "简称",
    "product", "产品名称", "证券名称", "基金简称",
]
AMOUNT_ALIASES = [
    "amount", "金额", "持仓金额", "市值", "market_value", "value",
    "position", "holding", "investment", "投入", "成本", "买入金额",
    "money", "总市值",
]
WEIGHT_ALIASES = [
    "weight", "权重", "占比", "ratio", "percentage", "pct", "allocation",
    "weight_pct", "配置比例", "仓位", "持仓占比", "投资比例",
]


# ============================================================
# 列名检测与规范化
# ============================================================

def _match_column(col: str, aliases: List[str]) -> bool:
    """检查列名是否匹配任一别名"""
    col_lower = str(col).lower().strip()
    col_clean = col_lower.replace(" ", "").replace("_", "").replace("-", "")
    for alias in aliases:
        alias_clean = alias.lower().replace(" ", "").replace("_", "").replace("-", "")
        if col_clean == alias_clean:
            return True
        # 部分匹配（列名包含别名关键词）
        if len(alias_clean) >= 3 and alias_clean in col_clean:
            return True
    return False


def detect_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """
    检测 DataFrame 中的列名映射。

    Args:
        df: 原始 DataFrame

    Returns:
        dict: {"fund_code": "原始列名", "fund_name": "原始列名", ...}
              未匹配的键值为 None
    """
    result = {
        "fund_code": None,
        "fund_name": None,
        "amount": None,
        "weight": None,
    }

    for col in df.columns:
        if result["fund_code"] is None and _match_column(col, FUND_CODE_ALIASES):
            result["fund_code"] = col
        elif result["fund_name"] is None and _match_column(col, FUND_NAME_ALIASES):
            result["fund_name"] = col
        elif result["amount"] is None and _match_column(col, AMOUNT_ALIASES):
            result["amount"] = col
        elif result["weight"] is None and _match_column(col, WEIGHT_ALIASES):
            result["weight"] = col

    return result


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    根据别名检测结果规范化 DataFrame 列名。

    Renames detected columns to canonical names:
    fund_code, fund_name, amount, weight

    Args:
        df: 原始 DataFrame

    Returns:
        pd.DataFrame: 重命名后的 DataFrame
    """
    mapping = detect_columns(df)
    rename_map = {}
    for canonical, original in mapping.items():
        if original is not None:
            rename_map[original] = canonical

    if rename_map:
        df = df.rename(columns=rename_map)

    return df


# ============================================================
# 文件解析
# ============================================================

def parse_csv(file_content: bytes) -> pd.DataFrame:
    """
    解析 CSV 字节内容，自动检测编码。

    Args:
        file_content: CSV 文件字节内容

    Returns:
        pd.DataFrame
    """
    for enc in ["utf-8", "gbk", "gb2312", "utf-8-sig", "gb18030"]:
        try:
            return pd.read_csv(io.BytesIO(file_content), encoding=enc)
        except (UnicodeDecodeError, TypeError):
            continue

    # 最终回退
    return pd.read_csv(io.BytesIO(file_content), encoding="utf-8", errors="replace")


def parse_excel(file_content: bytes, sheet_name=0) -> pd.DataFrame:
    """
    解析 Excel (.xlsx) 字节内容。

    需要安装 openpyxl: pip install openpyxl

    Args:
        file_content: Excel 文件字节内容
        sheet_name: 工作表名称或索引
    """
    try:
        return pd.read_excel(io.BytesIO(file_content), sheet_name=sheet_name)
    except ImportError:
        raise ImportError(
            "需要安装 openpyxl 来解析 Excel 文件。\n"
            "请运行: pip install openpyxl"
        )


def parse_clipboard_text(text: str) -> pd.DataFrame:
    """
    解析剪贴板文本（制表符分隔 / 空格分隔）。

    Args:
        text: 剪贴板文本

    Returns:
        pd.DataFrame
    """
    if not text.strip():
        return pd.DataFrame()

    # 尝试制表符分隔
    if "\t" in text:
        try:
            return pd.read_csv(io.StringIO(text), sep="\t")
        except Exception:
            pass

    # 尝试多种分隔符
    for sep in [",", ";", r"\s+"]:
        try:
            return pd.read_csv(io.StringIO(text), sep=sep)
        except Exception:
            continue

    # 单列文本（每行一个基金代码或名称）
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if lines:
        return pd.DataFrame(lines, columns=["fund_code"])

    return pd.DataFrame()


# ============================================================
# 文本提取
# ============================================================

def extract_fund_codes_from_text(text: str) -> List[str]:
    """
    从自由文本中提取 6 位基金代码。

    匹配模式：连续的 6 位数字（基金代码标准格式）。

    Args:
        text: 任意文本

    Returns:
        list: 去重的基金代码列表
    """
    # 匹配6位数字
    pattern = r"\b(\d{6})\b"
    matches = re.findall(pattern, text)
    # 去重并保持顺序
    seen = set()
    result = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def resolve_name_to_code(name: str) -> Optional[Dict[str, str]]:
    """
    根据基金名称（完整或部分）搜索基金代码。

    Args:
        name: 基金名称

    Returns:
        dict: {"code": "...", "name": "..."} 或 None
    """
    fetcher = get_fetcher()
    try:
        df = fetcher.search_fund(name)
        if df is not None and not df.empty:
            row = df.iloc[0]
            return {
                "code": str(row.get("基金代码", "")).zfill(6),
                "name": str(row.get("基金名称", name)),
            }
    except Exception:
        pass
    return None


def batch_resolve_and_validate(
    codes_or_names: List[str],
) -> Tuple[List[Dict[str, str]], List[str]]:
    """
    批量解析基金代码/名称，返回有效和无效列表。

    Args:
        codes_or_names: 混合的基金代码和名称列表

    Returns:
        (resolved, unresolved):
        - resolved: [{"code": "000001", "name": "华夏成长", "type": "混合型"}, ...]
        - unresolved: 未能解析的字符串列表
    """
    resolved = []
    unresolved = []

    fetcher = get_fetcher()

    for item in codes_or_names:
        item = str(item).strip()
        if not item:
            continue

        # 如果看起来像代码（6位数字）
        if re.match(r"^\d{6}$", item):
            try:
                info = fetcher.get_fund_manager_info(item)
                if info:
                    resolved.append({
                        "code": item,
                        "name": info.get("基金名称", item),
                        "type": info.get("基金类型", "未知"),
                    })
                else:
                    unresolved.append(item)
            except Exception:
                unresolved.append(item)
        else:
            # 按名称搜索
            result = resolve_name_to_code(item)
            if result:
                code = result["code"]
                try:
                    info = fetcher.get_fund_manager_info(code)
                    resolved.append({
                        "code": code,
                        "name": info.get("基金名称", result["name"]) if info else result["name"],
                        "type": info.get("基金类型", "未知") if info else "未知",
                    })
                except Exception:
                    resolved.append({
                        "code": code,
                        "name": result["name"],
                        "type": "未知",
                    })
            else:
                unresolved.append(item)

    return resolved, unresolved
