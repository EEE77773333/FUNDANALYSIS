"""
数据源注册与本地缓存
====================
对外提供两件事：

1. **数据源注册表** —— 列出当前环境有哪些可用数据源、各自优先级与不可用原因。
   用户可在「账户设置 → 行情数据源」里切换首选源。

2. **带 TTL 的本地缓存** —— 把行情结果落到本地 SQLite / PostgreSQL。
   这不是锦上添花，而是自部署体验的胜负手：
   用户量一多，所有人直连 AKShare / 天天基金，公共源很快限流甚至封 IP。
   本地缓存把「重复请求」挡在本地，既提速又保命。

使用方式:
    from core.data_sources import cached, list_available_sources, clear_cache

    nav = cached("nav:000001:3", ttl=1800, fn=fetcher.get_fund_nav_history, "000001", years=3)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_registry_lock = threading.Lock()
_registry = None  # MultiSourceFetcher 单例

# 关闭缓存的环境变量开关（调试 / 强制刷新时有用）
import os as _os
_CACHE_ENABLED = _os.getenv("DISABLE_QUOTE_CACHE", "").strip().lower() not in ("1", "true", "yes")


# ============================================================
# 数据源注册表
# ============================================================

def get_registry():
    """获取数据源协调器单例（延迟构建，避免导入期做重活）。"""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                from .fetchers import build_default_fetcher
                _registry = build_default_fetcher()
    return _registry


def list_available_sources() -> List[Dict[str, Any]]:
    """
    列出所有已注册数据源及其可用状态。

    Returns:
        [{"name","label","available","reason","priority","requires_token"}, ...]
    """
    try:
        return get_registry().get_all_sources()
    except Exception as e:
        logger.warning("数据源注册表构建失败: %s", e)
        return [{
            "name": "eastmoney", "label": "东方财富 / 天天基金直连",
            "available": True, "reason": "", "priority": 1, "requires_token": False,
        }]


def active_provider() -> str:
    """返回当前用户配置的首选数据源名。"""
    try:
        from .user_integrations import resolve_data_source_config
        return resolve_data_source_config().get("provider", "eastmoney")
    except Exception:
        return "eastmoney"


def get_source_status(provider: Optional[str] = None) -> Dict[str, Any]:
    """检查指定数据源是否可用，返回状态字典（供 UI 提示）。"""
    provider = provider or active_provider()
    for item in list_available_sources():
        if item["name"] == provider:
            return item
    return {"name": provider, "label": provider, "available": False,
            "reason": "未在注册表中找到该数据源", "priority": 99, "requires_token": False}


# ============================================================
# 序列化（支持 DataFrame）
# ============================================================

_DF_MARK = "__pandas_df__"


def _json_default(o: Any) -> Any:
    """
    把 numpy 标量等非原生类型转成 Python 原生类型。

    这一步很关键：如果直接 default=str，numpy.float64 会变成字符串 "3.14"，
    缓存命中后参与算术运算就会报错。所以必须按类型精确转换，而不是一律转字符串。
    """
    try:
        import numpy as np
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.bool_):
            return bool(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:
        pass
    if isinstance(o, (set, frozenset)):
        return list(o)
    return str(o)


def _serialize(value: Any) -> str:
    """把取数结果序列化成 JSON 字符串。DataFrame 走专门的转换分支。"""
    try:
        import pandas as pd
        if isinstance(value, pd.DataFrame):
            return json.dumps(
                {_DF_MARK: value.to_json(orient="split", date_format="iso")},
                ensure_ascii=False,
            )
        if isinstance(value, pd.Series):
            return json.dumps(
                {_DF_MARK: value.to_frame().to_json(orient="split", date_format="iso")},
                ensure_ascii=False,
            )
    except Exception:
        pass
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _deserialize(raw: str) -> Any:
    """反序列化。遇到 DataFrame 标记则还原成 DataFrame。"""
    obj = json.loads(raw)
    if isinstance(obj, dict) and _DF_MARK in obj:
        import pandas as pd
        from io import StringIO
        return pd.read_json(StringIO(obj[_DF_MARK]), orient="split")
    return obj


# ============================================================
# 缓存读写
# ============================================================

def _ph() -> str:
    from .db import DB_MODE
    return "%s" if DB_MODE == "postgresql" else "?"


def cache_get(key: str, ttl: Optional[int] = None) -> Tuple[bool, Any]:
    """
    读取缓存。

    Args:
        key: 缓存键
        ttl: 若给定，则额外校验写入时间是否在 ttl 秒内（用于同一 key 不同 ttl 的场景）

    Returns:
        (是否命中, 值)
    """
    if not _CACHE_ENABLED:
        return False, None
    try:
        from .db import get_connection
        ph = _ph()
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT payload, expires_at FROM quote_cache WHERE cache_key = {ph}",
                (key,),
            ).fetchone()
        if not row:
            return False, None
        payload = row["payload"] if hasattr(row, "keys") else row[0]
        expires_at = row["expires_at"] if hasattr(row, "keys") else row[1]
        if expires_at and time.time() > float(expires_at):
            return False, None
        return True, _deserialize(payload)
    except Exception as e:
        logger.debug("缓存读取失败 key=%s: %s", key, e)
        return False, None


def cache_set(key: str, value: Any, source: str = "", ttl: int = 300) -> None:
    """写入缓存（ttl 单位秒，<=0 表示不缓存）。"""
    if not _CACHE_ENABLED or ttl <= 0:
        return
    try:
        payload = _serialize(value)
        cache_set_raw(key, payload, source=source, ttl=ttl)
    except Exception as e:
        logger.debug("缓存写入失败 key=%s: %s", key, e)


def cache_set_raw(key: str, payload: str, source: str = "", ttl: int = 300) -> None:
    """直接写入已序列化好的 payload（供 cached() 复用，避免重复序列化）。"""
    if not _CACHE_ENABLED or ttl <= 0:
        return
    try:
        from .db import get_connection, now_iso
        expires_at = time.time() + int(ttl)
        ph = _ph()
        with get_connection() as conn:
            exists = conn.execute(
                f"SELECT 1 FROM quote_cache WHERE cache_key = {ph}", (key,)
            ).fetchone()
            if exists:
                conn.execute(
                    f"UPDATE quote_cache SET payload = {ph}, source = {ph}, "
                    f"expires_at = {ph}, created_at = {ph} WHERE cache_key = {ph}",
                    (payload, source, expires_at, now_iso(), key),
                )
            else:
                conn.execute(
                    f"INSERT INTO quote_cache (cache_key, payload, source, expires_at, created_at) "
                    f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph})",
                    (key, payload, source, expires_at, now_iso()),
                )
    except Exception as e:
        logger.debug("缓存写入失败 key=%s: %s", key, e)


def cache_invalidate(prefix: str) -> int:
    """按前缀清除缓存，返回清除条数。"""
    try:
        from .db import get_connection
        ph = _ph()
        with get_connection() as conn:
            cur = conn.execute(
                f"DELETE FROM quote_cache WHERE cache_key LIKE {ph}", (f"{prefix}%",)
            )
            return cur.rowcount or 0
    except Exception as e:
        logger.debug("缓存清除失败 prefix=%s: %s", prefix, e)
        return 0


def clear_cache() -> int:
    """清空全部行情缓存，返回清除条数。"""
    try:
        from .db import get_connection
        with get_connection() as conn:
            cur = conn.execute("DELETE FROM quote_cache")
            return cur.rowcount or 0
    except Exception as e:
        logger.debug("缓存清空失败: %s", e)
        return 0


def purge_expired() -> int:
    """清理已过期条目（可由定时任务或后台线程调用）。"""
    try:
        from .db import get_connection
        ph = _ph()
        with get_connection() as conn:
            cur = conn.execute(
                f"DELETE FROM quote_cache WHERE expires_at < {ph}", (time.time(),)
            )
            return cur.rowcount or 0
    except Exception as e:
        logger.debug("过期缓存清理失败: %s", e)
        return 0


def cache_stats() -> Dict[str, Any]:
    """缓存概况（供「账户设置」展示）。"""
    try:
        from .db import get_connection
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM quote_cache").fetchone()
            total_n = (total["c"] if hasattr(total, "keys") else total[0]) or 0
            ph = _ph()
            live = conn.execute(
                f"SELECT COUNT(*) AS c FROM quote_cache WHERE expires_at >= {ph}",
                (time.time(),),
            ).fetchone()
            live_n = (live["c"] if hasattr(live, "keys") else live[0]) or 0
        return {"total": int(total_n), "live": int(live_n), "expired": int(total_n - live_n),
                "enabled": _CACHE_ENABLED}
    except Exception:
        return {"total": 0, "live": 0, "expired": 0, "enabled": _CACHE_ENABLED}


# ============================================================
# 便捷包装
# ============================================================

def default_ttl() -> int:
    """用户配置的默认缓存时长。"""
    try:
        from .user_integrations import resolve_data_source_config
        return int(resolve_data_source_config().get("cache_ttl", 300) or 300)
    except Exception:
        return 300


def cached(key: str, fn: Callable, *args, ttl: Optional[int] = None, **kwargs) -> Any:
    """
    带缓存的取数调用。命中直接返回，未命中则执行 fn 并写回缓存。

    两条保证：
    1. **只缓存有内容的结果** —— 空结果不缓存，否则源站一次抖动会被缓存下来，
       放大成持续的空数据。
    2. **命中与未命中返回同构数据** —— 字典/列表结果在未命中时也走一次 JSON
       归一化，避免 numpy 标量在缓存命中后变成字符串、导致下游算术报错。

    Args:
        key: 缓存键
        fn: 实际取数函数
        ttl: 缓存秒数，None 则用用户配置的默认值
    """
    effective_ttl = default_ttl() if ttl is None else ttl

    hit, value = cache_get(key)
    if hit:
        return value

    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        logger.debug("取数失败 key=%s: %s", key, e)
        return None

    if not _has_content(result):
        return result

    try:
        payload = _serialize(result)
    except Exception as e:
        logger.debug("序列化失败，跳过缓存 key=%s: %s", key, e)
        return result

    source = ""
    try:
        source = get_registry().last_source or ""
    except Exception:
        pass
    cache_set_raw(key, payload, source=source, ttl=effective_ttl)

    # DataFrame 保持原对象返回（to_json 往返会改变 dtype，得不偿失）；
    # 字典/列表则返回归一化后的副本，确保与缓存命中路径完全一致。
    try:
        import pandas as pd
        if isinstance(result, (pd.DataFrame, pd.Series)):
            return result
    except Exception:
        pass

    try:
        return _deserialize(payload)
    except Exception:
        return result


def _has_content(value: Any) -> bool:
    """空结果不写缓存。"""
    if value is None:
        return False
    try:
        import pandas as pd
        if isinstance(value, (pd.DataFrame, pd.Series)):
            return not value.empty
    except Exception:
        pass
    if isinstance(value, (list, dict, str)):
        return len(value) > 0
    return True


# ============================================================
# 缓存装饰器
# ============================================================

# 各类数据的推荐 TTL（秒）。变化越慢的数据缓存越久。
TTL_REALTIME = None      # None = 用用户在「账户设置」里配置的值（默认 300）
TTL_DAILY_NAV = 3600     # 日线净值：当天内基本不变
TTL_VALUATION = 7200     # 指数估值：每日更新
TTL_SLOW = 86400         # 宏观 / 基金清单：月度或季度更新


def persistent_cache(prefix: str, ttl: Optional[int] = None):
    """
    给取数方法加一层跨进程持久化缓存。

    用法（装饰在方法上，注意放在 @timed_cache 外层）：
        @persistent_cache("nav", ttl=3600)
        @timed_cache(ttl=300, maxsize=32)
        def get_fund_nav_history(self, code, years=3): ...

    缓存键由方法参数决定；行情数据与用户无关，可安全共享。
    """
    import functools

    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            parts = [prefix]
            # args[0] 是 self，跳过以免把对象地址写进 key
            parts.extend(str(a) for a in args[1:])
            parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            key = ":".join(parts)
            effective = default_ttl() if ttl is TTL_REALTIME or ttl is None else ttl
            return cached(key, fn, *args, ttl=effective, **kwargs)

        # 暴露原始函数，便于需要绕过缓存时调用
        wrapper.__wrapped_no_cache__ = fn
        return wrapper

    return decorator
