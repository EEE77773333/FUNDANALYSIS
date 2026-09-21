"""
分析历史持久化
==============
自动保存 AI 分析结果到 SQLite，支持历史浏览、时间对比和跨基金对比。

核心功能:
    - save(): 持久化分析结果
    - list_all(): 分页查询历史
    - get_time_series(): 单基金时间序列对比
    - compare_funds(): 多基金横向对比
    - wrap_analysis_stream(): 自动保存的分析流包装器（不修改 ui_components.py）

使用方式:
    # 方式1: 手动保存
    from core.history import get_history_manager
    hm = get_history_manager()
    hm.save("宏观行业研判", "", "", system_prompt, user_prompt, result, usage, elapsed, model)

    # 方式2: 使用包装器（替代 run_analysis_stream）
    from core.history import get_history_manager
    result = get_history_manager().wrap_analysis_stream(
        analyzer, system_prompt, user_prompt,
        page_name="宏观行业研判", fund_code="000001", fund_name="华夏成长",
        max_tokens=4096, temperature=0.3,
    )
"""

import hashlib
import json
from typing import Optional, List, Dict, Any, Generator

import streamlit as st

from .db import get_connection, now_iso, get_user_id


# ============================================================
# 数据类
# ============================================================

class AnalysisRecord:
    """分析历史记录"""

    def __init__(self, row):
        self.id = row["id"]
        self.page_name = row["page_name"]
        self.fund_code = row.get("fund_code", "")
        self.fund_name = row.get("fund_name", "")
        self.system_prompt_hash = row.get("system_prompt_hash", "")
        self.user_prompt_hash = row.get("user_prompt_hash", "")
        self.result_content = row.get("result_content", "")
        self.usage_json = row.get("usage_json", "{}")
        self.elapsed_seconds = float(row.get("elapsed_seconds", 0))
        self.model = row.get("model", "")
        self.created_at = row["created_at"]
        self.structured_result_json = row.get("structured_result_json", "") or ""

    @property
    def structured_result(self) -> Optional[dict]:
        if not self.structured_result_json:
            return None
        try:
            return json.loads(self.structured_result_json)
        except (json.JSONDecodeError, TypeError):
            return None

    @property
    def usage(self) -> dict:
        try:
            return json.loads(self.usage_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    @property
    def preview(self) -> str:
        """返回结果的前 200 字预览"""
        return self.result_content[:200] if self.result_content else ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "page_name": self.page_name,
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "preview": self.preview,
            "elapsed_seconds": self.elapsed_seconds,
            "model": self.model,
            "created_at": self.created_at,
        }


# ============================================================
# 历史管理器
# ============================================================

class HistoryManager:
    """分析历史持久化与查询"""

    @staticmethod
    def _hash(text: str) -> str:
        """对文本做 MD5 哈希"""
        return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:12]

    def save(
        self,
        page_name: str,
        fund_code: str,
        fund_name: str,
        system_prompt: str,
        user_prompt: str,
        result_content: str,
        usage: dict = None,
        elapsed_seconds: float = 0,
        model: str = "",
        structured_result: dict = None,
    ) -> int:
        """
        保存分析结果。

        Returns:
            int: 记录 ID
        """
        from .db import DB_MODE

        sp_hash = self._hash(system_prompt)
        up_hash = self._hash(user_prompt)
        uid = get_user_id()
        usage_s = json.dumps(usage or {}, ensure_ascii=False)
        struct_s = json.dumps(structured_result, ensure_ascii=False) if structured_result else ""
        ts = now_iso()

        with get_connection() as conn:
            if DB_MODE == "postgresql":
                row = conn.execute(
                    """INSERT INTO analysis_history
                       (user_id, page_name, fund_code, fund_name, system_prompt_hash, user_prompt_hash,
                        result_content, usage_json, elapsed_seconds, model, created_at, structured_result_json)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (
                        uid, page_name, fund_code, fund_name,
                        sp_hash, up_hash, result_content, usage_s,
                        elapsed_seconds, model, ts, struct_s,
                    ),
                ).fetchone()
                return int(row["id"] if row else 0)
            cursor = conn.execute(
                """INSERT INTO analysis_history
                   (user_id, page_name, fund_code, fund_name, system_prompt_hash, user_prompt_hash,
                    result_content, usage_json, elapsed_seconds, model, created_at, structured_result_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    uid, page_name, fund_code, fund_name,
                    sp_hash, up_hash, result_content, usage_s,
                    elapsed_seconds, model, ts, struct_s,
                ),
            )
            return int(cursor.lastrowid or 0)

    def get(self, record_id: int) -> Optional[AnalysisRecord]:
        """获取单条记录"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_history WHERE id = ? AND user_id = ?", (record_id, get_user_id())
            ).fetchone()
            return AnalysisRecord(row) if row else None

    def list_all(
        self,
        page_name: str = None,
        fund_code: str = None,
        search: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AnalysisRecord]:
        """
        分页查询。

        Args:
            page_name: 按页面名称筛选
            fund_code: 按基金代码筛选
            search: 全文搜索（搜索 result_content 和 fund_name）
            limit: 每页条数
            offset: 偏移量
        """
        conditions = ["user_id = ?"]
        params = [get_user_id()]

        if page_name:
            conditions.append("page_name = ?")
            params.append(page_name)
        if fund_code:
            conditions.append("fund_code = ?")
            params.append(fund_code)
        if search:
            conditions.append("(result_content LIKE ? OR fund_name LIKE ?)")
            kw = f"%{search}%"
            params.extend([kw, kw])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM analysis_history {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [AnalysisRecord(r) for r in rows]

    def count(self, page_name: str = None, fund_code: str = None) -> int:
        """获取总记录数"""
        conditions = ["user_id = ?"]
        params = [get_user_id()]
        if page_name:
            conditions.append("page_name = ?")
            params.append(page_name)
        if fund_code:
            conditions.append("fund_code = ?")
            params.append(fund_code)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM analysis_history {where}", params
            ).fetchone()
            return row["cnt"] if row else 0

    def get_for_fund(self, fund_code: str, limit: int = 20) -> List[AnalysisRecord]:
        """获取同基金的历史分析列表（时间序列）"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM analysis_history WHERE fund_code = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?",
                (fund_code, get_user_id(), limit),
            ).fetchall()
            return [AnalysisRecord(r) for r in rows]

    def compare_funds(self, fund_codes: List[str], page_name: str = None) -> Dict[str, AnalysisRecord]:
        """
        获取多只基金的最新分析记录用于横向对比。

        Returns:
            dict: {fund_code: AnalysisRecord}
        """
        if not fund_codes:
            return {}
        uid = get_user_id()
        ph = "?" if "sqlite" in str(type(get_user_id)) else "%s"
        placeholders = ", ".join(["?" for _ in fund_codes])
        with get_connection() as conn:
            # 单条 SQL：每只基金的最新一条记录
            if page_name:
                rows = conn.execute(
                    f"SELECT DISTINCT fund_code, * FROM analysis_history "
                    f"WHERE fund_code IN ({placeholders}) AND page_name = ? AND user_id = ? "
                    f"GROUP BY fund_code HAVING MAX(created_at)",
                    (*fund_codes, page_name, uid),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM analysis_history WHERE id IN ("
                    f"SELECT MAX(id) FROM analysis_history "
                    f"WHERE fund_code IN ({placeholders}) AND user_id = ? "
                    f"GROUP BY fund_code"
                    f")",
                    (*fund_codes, uid),
                ).fetchall()
            result = {}
            for row in rows:
                code = row.get("fund_code", "")
                if code:
                    result[code] = AnalysisRecord(row)
        return result

    def delete(self, record_id: int):
        """删除单条记录"""
        with get_connection() as conn:
            conn.execute("DELETE FROM analysis_history WHERE id = ? AND user_id = ?", (record_id, get_user_id()))

    def delete_older_than(self, days: int) -> int:
        """清理旧记录，返回删除条数"""
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM analysis_history WHERE created_at < ? AND user_id = ?", (cutoff, get_user_id())
            )
            return cursor.rowcount

    def get_page_names(self) -> List[str]:
        """获取所有出现过的页面名称"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT page_name FROM analysis_history WHERE user_id = ? ORDER BY page_name", (get_user_id(),)
            ).fetchall()
            return [r["page_name"] for r in rows]

    def get_all_fund_codes(self) -> List[str]:
        """获取所有出现过的基金代码"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT fund_code FROM analysis_history WHERE fund_code != '' AND user_id = ? ORDER BY fund_code", (get_user_id(),)
            ).fetchall()
            return [r["fund_code"] for r in rows]

    # ---- 流式分析包装器 ----

    def wrap_analysis_stream(
        self,
        analyzer,
        system_prompt: str,
        user_prompt: str,
        page_name: str = "",
        fund_code: str = "",
        fund_name: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        placeholder_label: str = "📝 分析报告",
    ) -> Optional[Dict[str, Any]]:
        """
        包装 run_analysis_stream，自动保存结果到历史。

        参数和返回值与 run_analysis_stream 完全一致，
        额外需要 page_name/fund_code/fund_name 用于历史索引。

        Returns:
            AnalysisResult dict（与 run_analysis_stream 同格式），
            额外包含 history_id 字段。
        """
        from .ui_components import run_analysis_stream

        result = run_analysis_stream(
            analyzer=analyzer,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            placeholder_label=placeholder_label,
        )

        if result and result.get("success"):
            try:
                history_id = self.save(
                    page_name=page_name,
                    fund_code=fund_code,
                    fund_name=fund_name,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    result_content=result.get("content", ""),
                    usage=result.get("usage", {}),
                    elapsed_seconds=result.get("elapsed_seconds", 0),
                    model=result.get("model", ""),
                )
                result["history_id"] = history_id
            except Exception:
                pass  # 历史保存失败不影响分析结果

        return result


# ============================================================
# 单例
# ============================================================

import threading

_history_manager: Optional[HistoryManager] = None
_history_manager_lock = threading.Lock()


def get_history_manager() -> HistoryManager:
    """获取 HistoryManager 全局单例（线程安全）"""
    global _history_manager
    if _history_manager is None:
        with _history_manager_lock:
            if _history_manager is None:
                _history_manager = HistoryManager()
    return _history_manager
