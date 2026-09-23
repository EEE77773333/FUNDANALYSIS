"""
数据库持久化层（SQLite / PostgreSQL 双模式）
============================================
通过环境变量 DATABASE_URL 自动切换后端：

    - 未设置 → SQLite (data/fund_analysis.db)，单用户模式
    - 设置 → PostgreSQL，多用户模式

使用方式:
    from core.db import get_connection, get_user_id, DB_MODE

    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM portfolios WHERE user_id = ?", (get_user_id(),))
"""

import os
import json
import threading as _threading
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

# ---- 数据目录 ----
# 可用 DATA_DIR 环境变量覆盖，方便容器部署时把数据挂到卷上
DATA_DIR = Path(os.getenv("DATA_DIR") or (Path(__file__).parent.parent / "data"))

# 确保 .env 已加载（db.py 可能在 config.py 之前被导入）
try:
    from dotenv import load_dotenv
    _env_paths = [Path(__file__).parent.parent / ".env", Path.cwd() / ".env"]
    for _p in _env_paths:
        if _p.exists():
            load_dotenv(_p)
except ImportError:
    pass

# ---- 数据库模式检测 ----
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_MODE = "postgresql" if DATABASE_URL else "sqlite"

# PostgreSQL：DATABASE_URL 已设置时必须可用，禁止静默降级到 SQLite（避免双库脑裂）
_PG_AVAILABLE = False
if DB_MODE == "postgresql":
    try:
        import psycopg2
        import psycopg2.pool
        import psycopg2.extras
        test_conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
        test_conn.close()
        _PG_AVAILABLE = True
    except Exception as e:
        raise RuntimeError(
            f"PostgreSQL 连接失败，已禁止降级到 SQLite。"
            f"请检查 DATABASE_URL / 数据库服务是否可用。"
            f"原始错误: {e}"
        ) from e

# ---- PostgreSQL 连接池 ----
_pg_pool = None
_pg_pool_lock = _threading.Lock()

# ---- SQLite 路径 ----
DB_PATH = DATA_DIR / "fund_analysis.db"

_initialized = False
_init_lock = _threading.Lock()

# ---- 当前用户 ID ----
_current_user_id: Optional[int] = None
_user_id_lock = _threading.Lock()


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 连接管理
# ============================================================

def _get_pg_pool():
    """获取或创建 PostgreSQL 连接池"""
    global _pg_pool
    if _pg_pool is None:
        with _pg_pool_lock:
            if _pg_pool is None:
                _pg_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=2, maxconn=15, dsn=DATABASE_URL,
                )
    return _pg_pool


class _PgCursor:
    """psycopg2 cursor wrapper — 模拟 sqlite3 的 execute() 返回 self 的链式调用"""
    def __init__(self, cur, pgconn):
        self._cur = cur
        self._pgconn = pgconn

    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        self._cur.execute(sql, params)
        return self  # 支持链式: conn.execute(...).fetchone()

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return self._cur.lastrowid


@contextmanager
def get_connection():
    """
    获取数据库连接（自动适配 SQLite / PostgreSQL）。

    统一接口：conn.execute(sql, params).fetchone()/.fetchall()
    """
    if DB_MODE == "postgresql":
        pool = _get_pg_pool()
        pgconn = pool.getconn()
        cur = pgconn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        wrapper = _PgCursor(cur, pgconn)
        try:
            yield wrapper
            pgconn.commit()
        except Exception:
            pgconn.rollback()
            raise
        finally:
            cur.close()
            pool.putconn(pgconn)
    else:
        import sqlite3
        _ensure_data_dir()
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = _sqlite_row_factory
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ============================================================
# SQL 占位符适配
# ============================================================

def _ph() -> str:
    """返回当前数据库的 SQL 占位符：SQLite='?', PG='%s'"""
    return "%s" if DB_MODE == "postgresql" else "?"


class CompatRow(dict):
    """
    SQLite 查询结果行，行为对齐 PostgreSQL 的 RealDictCursor。

    **为什么需要它**
        SQLite 默认的 sqlite3.Row 只支持下标访问，没有 `.get()`；
        而 PostgreSQL 用 RealDictCursor 返回的是真 dict，`.get()` 可用。
        这导致同一段代码在单机版（SQLite）和云端版（PG）表现不一致 ——
        本项目历史上「AI 用量计数永远为 0」正是因此静默失败。

        本类在 dict 的基础上补回 sqlite3.Row 的两项能力：
          - 整数下标访问 row[0]
          - 迭代时产出「值」而非「键」（与 sqlite3.Row 一致）

        因此它严格兼容 sqlite3.Row 的所有用法，同时让 `.get()` 可用。
    """

    __slots__ = ("_values",)

    def __init__(self, cursor, row):
        self._values = tuple(row)
        super().__init__(
            {desc[0]: row[idx] for idx, desc in enumerate(cursor.description or ())}
        )

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def __iter__(self):
        # 保持 sqlite3.Row 语义：迭代产出行内的值
        return iter(self._values)

    def __len__(self):
        return len(self._values)


def _sqlite_row_factory(cursor, row):
    return CompatRow(cursor, row)


def _auto_increment() -> str:
    """返回自增主键语法"""
    return "SERIAL PRIMARY KEY" if DB_MODE == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _json_type() -> str:
    """返回 JSON 列类型"""
    return "JSONB" if DB_MODE == "postgresql" else "TEXT"


# ============================================================
# 用户上下文
# ============================================================

def set_user_id(user_id: int):
    """设置当前线程的用户 ID（由认证中间件调用）"""
    global _current_user_id
    _current_user_id = user_id


def get_user_id() -> int:
    """
    获取当前用户 ID。

    - 多用户模式: 从认证中间件设置的上下文获取
    - 单用户模式: 返回 1（默认用户）
    """
    # 先检查 Streamlit session
    try:
        import streamlit as st
        if hasattr(st, "session_state") and "user" in st.session_state:
            uid = st.session_state["user"].get("id")
            if uid:
                return uid
    except Exception:
        pass

    # 再检查线程本地
    if _current_user_id is not None:
        return _current_user_id

    # 默认：单用户
    return 1


# ============================================================
# 工具函数
# ============================================================

def now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def execute(conn, sql: str, params: tuple = None):
    """
    统一的 SQL 执行接口。
    """
    return conn.execute(sql, params or ())


# ============================================================
# 建表
# ============================================================

def _apply_schema_migrations(conn):
    """补建缺失表/列（支持 PG 热重载后增量迁移）。"""
    exec_sql = lambda s, p=None: execute(conn, s, p)
    AI = _auto_increment()
    JT = _json_type()

    table_exists = False
    if DB_MODE == "postgresql":
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'signal_evaluations' LIMIT 1"
        ).fetchone()
        table_exists = bool(row)
    else:
        try:
            conn.execute("SELECT id FROM signal_evaluations LIMIT 1")
            table_exists = True
        except Exception:
            table_exists = False

    if not table_exists:
        exec_sql(f"""
            CREATE TABLE IF NOT EXISTS signal_evaluations (
                id {AI},
                user_id INT DEFAULT 1,
                source_type TEXT NOT NULL,
                source_id INT NOT NULL,
                fund_code TEXT DEFAULT '',
                fund_name TEXT DEFAULT '',
                horizon_days INT NOT NULL,
                predicted_action TEXT DEFAULT 'hold',
                confidence REAL DEFAULT 0,
                actual_return REAL DEFAULT 0,
                direction_hit INT DEFAULT NULL,
                brier_score REAL DEFAULT 0,
                outcome TEXT DEFAULT '',
                evaluated_at TEXT NOT NULL
            )
        """)
        for s in (
            "CREATE INDEX IF NOT EXISTS idx_signal_eval_user ON signal_evaluations(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_signal_eval_source ON signal_evaluations(source_type, source_id)",
        ):
            try:
                if DB_MODE == "postgresql":
                    exec_sql(s)
                else:
                    conn.execute(s)
            except Exception:
                pass

    col_exists = False
    if DB_MODE == "postgresql":
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'analysis_history' AND column_name = 'structured_result_json' LIMIT 1"
        ).fetchone()
        col_exists = bool(row)
    else:
        try:
            conn.execute("SELECT structured_result_json FROM analysis_history LIMIT 1")
            col_exists = True
        except Exception:
            col_exists = False

    if not col_exists:
        try:
            if DB_MODE == "postgresql":
                exec_sql("ALTER TABLE analysis_history ADD COLUMN structured_result_json TEXT DEFAULT ''")
            else:
                conn.execute("ALTER TABLE analysis_history ADD COLUMN structured_result_json TEXT DEFAULT ''")
        except Exception:
            pass

    # 修正历史 bug：自助注册用户曾落到列默认配额 100，与免费版 10 次/天（core/middleware.py
    # QUOTA_MAP["free"]["ai_analysis"]）不一致。此处硬编码而非跨模块 import，避免 db.py
    # 自身初始化阶段与 middleware.py 顶层 `from core.db import DB_MODE` 形成循环导入。
    _FREE_TIER_AI_LIMIT = 10
    try:
        ph = "%s" if DB_MODE == "postgresql" else "?"
        exec_sql(
            f"UPDATE users SET api_calls_limit = {ph} WHERE tier = 'free' AND api_calls_limit = 100",
            (_FREE_TIER_AI_LIMIT,),
        )
    except Exception:
        pass

    # 同上：UserRepo.set_tier() 早期只更新 tier 列、不同步 api_calls_limit，导致该列与
    # 实际档位长期脱节（如 pro 用户仍显示 10）。拦截逻辑以 QUOTA_MAP 为准不受影响，
    # 但 get_usage / 每日简报等展示路径会读到旧值。此处按档位回填，SQL 与
    # QUOTA_MAP[*]["ai_analysis"] 保持一致（幂等：已一致的行走 WHERE 过滤掉）。
    _TIER_AI_LIMIT_CASE = (
        "CASE tier "
        "WHEN 'free' THEN 10 "
        "WHEN 'plus' THEN 40 "
        "WHEN 'pro' THEN 100 "
        "WHEN 'enterprise' THEN 99999 "
        "ELSE api_calls_limit END"
    )
    try:
        exec_sql(
            f"UPDATE users SET api_calls_limit = {_TIER_AI_LIMIT_CASE} "
            f"WHERE api_calls_limit <> {_TIER_AI_LIMIT_CASE}"
        )
    except Exception:
        pass

    # ---- 档位升级申请（托管版：用户在工作台/受限页一键申请，管理员在用户管理页处理） ----
    exec_sql(f"""
        CREATE TABLE IF NOT EXISTS tier_upgrade_requests (
            id {AI},
            user_id INT NOT NULL,
            email TEXT DEFAULT '',
            display_name TEXT DEFAULT '',
            current_tier TEXT DEFAULT 'free',
            requested_tier TEXT DEFAULT 'pro',
            note TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            handled_at TEXT DEFAULT '',
            handled_by TEXT DEFAULT ''
        )
    """)
    for s in (
        "CREATE INDEX IF NOT EXISTS idx_tier_req_user ON tier_upgrade_requests(user_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_tier_req_status ON tier_upgrade_requests(status, created_at)",
    ):
        try:
            if DB_MODE == "postgresql":
                exec_sql(s)
            else:
                conn.execute(s)
        except Exception:
            pass

    # ---- 个人工作台：收藏 / 偏好 / 最近访问 ----
    exec_sql(f"""
        CREATE TABLE IF NOT EXISTS user_favorites (
            id {AI},
            user_id INT NOT NULL,
            fund_code TEXT NOT NULL,
            fund_name TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(user_id, fund_code)
        )
    """)
    exec_sql(f"""
        CREATE TABLE IF NOT EXISTS user_prefs (
            user_id INT PRIMARY KEY,
            color_mode TEXT DEFAULT 'light',
            prefs_json TEXT DEFAULT '{{}}',
            updated_at TEXT NOT NULL
        )
    """)
    exec_sql(f"""
        CREATE TABLE IF NOT EXISTS user_recent (
            id {AI},
            user_id INT NOT NULL,
            kind TEXT NOT NULL,
            ref_key TEXT NOT NULL,
            title TEXT DEFAULT '',
            visited_at TEXT NOT NULL,
            UNIQUE(user_id, kind, ref_key)
        )
    """)
    for s in (
        "CREATE INDEX IF NOT EXISTS idx_user_favorites_user ON user_favorites(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_user_recent_user ON user_recent(user_id, visited_at)",
    ):
        try:
            if DB_MODE == "postgresql":
                exec_sql(s)
            else:
                conn.execute(s)
        except Exception:
            pass

    # monitoring_watchlist.group_name
    if DB_MODE == "postgresql":
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'monitoring_watchlist' AND column_name = 'group_name' LIMIT 1"
        ).fetchone()
        has_group = bool(row)
    else:
        try:
            conn.execute("SELECT group_name FROM monitoring_watchlist LIMIT 1")
            has_group = True
        except Exception:
            has_group = False
    if not has_group:
        try:
            if DB_MODE == "postgresql":
                exec_sql("ALTER TABLE monitoring_watchlist ADD COLUMN group_name TEXT DEFAULT ''")
            else:
                conn.execute("ALTER TABLE monitoring_watchlist ADD COLUMN group_name TEXT DEFAULT ''")
        except Exception:
            pass

    # 只读分享链接
    exec_sql(f"""
        CREATE TABLE IF NOT EXISTS share_links (
            id {AI},
            token TEXT NOT NULL UNIQUE,
            user_id INT NOT NULL,
            history_id INT NOT NULL,
            title TEXT DEFAULT '',
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            view_count INT DEFAULT 0,
            revoked INT DEFAULT 0
        )
    """)
    for s in (
        "CREATE INDEX IF NOT EXISTS idx_share_links_token ON share_links(token)",
        "CREATE INDEX IF NOT EXISTS idx_share_links_user ON share_links(user_id)",
    ):
        try:
            if DB_MODE == "postgresql":
                exec_sql(s)
            else:
                conn.execute(s)
        except Exception:
            pass

    # ---- 用户自有集成配置（BYOK：自带 LLM 密钥 / 自带行情数据源）----
    # llm_json : {"preset","base_url","api_key","model","protocol"}；api_key 落库前会被掩码返回
    # data_json: {"provider","tushare_token","cache_ttl"}
    exec_sql(f"""
        CREATE TABLE IF NOT EXISTS user_integrations (
            user_id INT PRIMARY KEY,
            llm_json {JT} DEFAULT '{{}}',
            data_json {JT} DEFAULT '{{}}',
            updated_at TEXT NOT NULL
        )
    """)

    # ---- 本地行情缓存（带 TTL，降低对公共数据源的请求压力）----
    # payload 固定用 TEXT 存 JSON 字符串，避免 SQLite(TEXT) 与 PG(JSONB) 的写入形态差异。
    # expires_at 必须是双精度：PG 的 REAL 只有 4 字节，存 Unix 时间戳会丢精度导致过期判断失准。
    FT = "DOUBLE PRECISION" if DB_MODE == "postgresql" else "REAL"
    exec_sql(f"""
        CREATE TABLE IF NOT EXISTS quote_cache (
            cache_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            source TEXT DEFAULT '',
            expires_at {FT} NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    try:
        if DB_MODE == "postgresql":
            exec_sql("CREATE INDEX IF NOT EXISTS idx_quote_cache_exp ON quote_cache(expires_at)")
        else:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quote_cache_exp ON quote_cache(expires_at)")
    except Exception:
        pass


def ensure_schema():
    """每次导入时执行增量迁移（不依赖 _initialized）。"""
    with get_connection() as conn:
        _apply_schema_migrations(conn)


def init_db():
    """
    初始化数据库：创建所有表。
    幂等操作——可重复调用。线程安全。
    """
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return

    _ensure_data_dir()
    AI = _auto_increment()
    JT = _json_type()

    with get_connection() as conn:
        exec_sql = lambda s, p=None: execute(conn, s, p)

        # ---- 用户表 ----
        exec_sql(f"""
            CREATE TABLE IF NOT EXISTS users (
                id {AI},
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(100) DEFAULT '',
                tier VARCHAR(20) DEFAULT 'free',
                tier_expires_at TEXT DEFAULT NULL,
                api_calls_today INT DEFAULT 0,
                api_calls_limit INT DEFAULT 100,
                api_calls_today_date TEXT DEFAULT '',
                is_active INT DEFAULT 1,
                last_login_at TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # 创建默认用户
        try:
            # 单用户模式：本地用户（免登录）
            row = conn.execute(
                "SELECT id FROM users WHERE email = 'local@fund.local'"
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO users (email, password_hash, display_name, tier, api_calls_limit, created_at, updated_at) "
                    "VALUES ('local@fund.local', '', '本地用户', 'enterprise', 99999, ?, ?)",
                    (now_iso(), now_iso()),
                )
            # 多用户模式：默认管理员（密码取自环境变量 ADMIN_DEFAULT_PASSWORD）
            # 未设置时不创建默认管理员，避免弱口令后门。
            admin_pw = os.getenv("ADMIN_DEFAULT_PASSWORD", "").strip()
            row2 = conn.execute(
                "SELECT id FROM users WHERE email = 'admin@fund.local'"
            ).fetchone()
            if not row2 and admin_pw:
                from core.auth import AuthManager
                admin_hash = AuthManager.hash_password(admin_pw)
                conn.execute(
                    "INSERT INTO users (email, password_hash, display_name, tier, api_calls_limit, created_at, updated_at) "
                    "VALUES ('admin@fund.local', ?, '管理员', 'enterprise', 99999, ?, ?)",
                    (admin_hash, now_iso(), now_iso()),
                )
        except Exception:
            pass

        # ---- 组合管理 ----
        exec_sql(f"""
            CREATE TABLE IF NOT EXISTS portfolios (
                id {AI},
                user_id INT DEFAULT 1,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        exec_sql(f"""
            CREATE TABLE IF NOT EXISTS portfolio_holdings (
                id {AI},
                portfolio_id INT NOT NULL,
                user_id INT DEFAULT 1,
                fund_code TEXT NOT NULL,
                fund_name TEXT DEFAULT '',
                amount REAL DEFAULT 0,
                weight REAL DEFAULT 0,
                purchase_date TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                FOREIGN KEY (portfolio_id) REFERENCES portfolios(id) ON DELETE CASCADE
            )
        """)

        exec_sql(f"""
            CREATE TABLE IF NOT EXISTS portfolio_nav_snapshots (
                id {AI},
                portfolio_id INT NOT NULL,
                user_id INT DEFAULT 1,
                date TEXT NOT NULL,
                total_value REAL NOT NULL,
                daily_return REAL DEFAULT 0,
                FOREIGN KEY (portfolio_id) REFERENCES portfolios(id) ON DELETE CASCADE
            )
        """)

        # ---- 决策信号 ----
        exec_sql(f"""
            CREATE TABLE IF NOT EXISTS signals (
                id {AI},
                user_id INT DEFAULT 1,
                fund_code TEXT NOT NULL,
                fund_name TEXT DEFAULT '',
                action TEXT NOT NULL,
                confidence REAL DEFAULT 0,
                score REAL DEFAULT 0,
                reason TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                outcome TEXT DEFAULT NULL,
                resolution_note TEXT DEFAULT '',
                source_analysis_id INT DEFAULT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT DEFAULT NULL
            )
        """)

        # ---- 预警规则 ----
        exec_sql(f"""
            CREATE TABLE IF NOT EXISTS alert_rules (
                id {AI},
                user_id INT DEFAULT 1,
                name TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                fund_codes_json {JT} DEFAULT '[]',
                parameters_json {JT} DEFAULT '{{}}',
                severity TEXT DEFAULT 'medium',
                enabled INT DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        exec_sql(f"""
            CREATE TABLE IF NOT EXISTS alert_triggers (
                id {AI},
                rule_id INT NOT NULL,
                user_id INT DEFAULT 1,
                fund_code TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT DEFAULT 'medium',
                triggered_at TEXT NOT NULL,
                acknowledged INT DEFAULT 0,
                FOREIGN KEY (rule_id) REFERENCES alert_rules(id) ON DELETE CASCADE
            )
        """)

        # ---- 分析历史 ----
        exec_sql(f"""
            CREATE TABLE IF NOT EXISTS analysis_history (
                id {AI},
                user_id INT DEFAULT 1,
                page_name TEXT NOT NULL,
                fund_code TEXT DEFAULT '',
                fund_name TEXT DEFAULT '',
                system_prompt_hash TEXT DEFAULT '',
                user_prompt_hash TEXT DEFAULT '',
                result_content TEXT DEFAULT '',
                usage_json {JT} DEFAULT '{{}}',
                elapsed_seconds REAL DEFAULT 0,
                model TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)

        # ---- 监控列表持久化 ----
        exec_sql(f"""
            CREATE TABLE IF NOT EXISTS monitoring_watchlist (
                id {AI},
                user_id INT DEFAULT 1,
                fund_code TEXT NOT NULL,
                fund_name TEXT DEFAULT '',
                added_at TEXT NOT NULL,
                UNIQUE(user_id, fund_code)
            )
        """)

        # ---- AI 验证快照（多窗口 T+N）----
        exec_sql(f"""
            CREATE TABLE IF NOT EXISTS signal_evaluations (
                id {AI},
                user_id INT DEFAULT 1,
                source_type TEXT NOT NULL,
                source_id INT NOT NULL,
                fund_code TEXT DEFAULT '',
                fund_name TEXT DEFAULT '',
                horizon_days INT NOT NULL,
                predicted_action TEXT DEFAULT 'hold',
                confidence REAL DEFAULT 0,
                actual_return REAL DEFAULT 0,
                direction_hit INT DEFAULT NULL,
                brier_score REAL DEFAULT 0,
                outcome TEXT DEFAULT '',
                evaluated_at TEXT NOT NULL
            )
        """)

        # ---- 索引 ----
        idx_sqls = [
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
            "CREATE INDEX IF NOT EXISTS idx_portfolios_user ON portfolios(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_signals_user ON signals(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_signals_fund_code ON signals(fund_code)",
            "CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status)",
            "CREATE INDEX IF NOT EXISTS idx_alert_rules_user ON alert_rules(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_alert_triggers_rule ON alert_triggers(rule_id)",
            "CREATE INDEX IF NOT EXISTS idx_alert_triggers_ack ON alert_triggers(acknowledged)",
            "CREATE INDEX IF NOT EXISTS idx_analysis_history_user ON analysis_history(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_analysis_history_page ON analysis_history(page_name)",
            "CREATE INDEX IF NOT EXISTS idx_analysis_history_fund ON analysis_history(fund_code)",
            "CREATE INDEX IF NOT EXISTS idx_analysis_history_created ON analysis_history(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_portfolio_holdings_pid ON portfolio_holdings(portfolio_id)",
            "CREATE INDEX IF NOT EXISTS idx_signal_eval_user ON signal_evaluations(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_signal_eval_source ON signal_evaluations(source_type, source_id)",
        ]
        for s in idx_sqls:
            try:
                if DB_MODE == "postgresql":
                    exec_sql(s)
                else:
                    conn.execute(s)
            except Exception:
                pass

        # ---- 迁移：为旧表补加 user_id 列 ----
        # 注意：PG 下用 information_schema 判断列是否存在，不能用 try/SELECT 探测——
        # 一旦 SELECT 因列不存在报错，当前事务会被标记为 aborted，后续所有语句都会
        # 抛 InFailedSqlTransaction，直到显式 ROLLBACK（SQLite 无此限制）。
        _migrate_tables = [
            "portfolios", "portfolio_holdings", "portfolio_nav_snapshots",
            "signals", "alert_rules", "alert_triggers", "analysis_history",
        ]
        for t in _migrate_tables:
            if DB_MODE == "postgresql":
                row = conn.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = %s AND column_name = 'user_id' LIMIT 1",
                    (t,),
                ).fetchone()
                has_col = bool(row)
            else:
                try:
                    conn.execute(f"SELECT user_id FROM {t} LIMIT 1")
                    has_col = True
                except Exception:
                    has_col = False
            if not has_col:
                try:
                    if DB_MODE == "postgresql":
                        exec_sql(f"ALTER TABLE {t} ADD COLUMN user_id INT DEFAULT 1")
                    else:
                        conn.execute(f"ALTER TABLE {t} ADD COLUMN user_id INT DEFAULT 1")
                except Exception:
                    pass

        # 迁移：为 users 表补加 api_calls_today_date 列
        if DB_MODE == "postgresql":
            row = conn.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name = 'api_calls_today_date' LIMIT 1"
            ).fetchone()
            has_col = bool(row)
        else:
            try:
                conn.execute("SELECT api_calls_today_date FROM users LIMIT 1")
                has_col = True
            except Exception:
                has_col = False
        if not has_col:
            try:
                if DB_MODE == "postgresql":
                    exec_sql("ALTER TABLE users ADD COLUMN api_calls_today_date TEXT DEFAULT ''")
                else:
                    conn.execute("ALTER TABLE users ADD COLUMN api_calls_today_date TEXT DEFAULT ''")
            except Exception:
                pass

        _apply_schema_migrations(conn)

    _initialized = True


# 模块导入时自动初始化 + 增量迁移（热重载安全）
init_db()
ensure_schema()
