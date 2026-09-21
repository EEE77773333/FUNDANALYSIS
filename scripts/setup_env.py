#!/usr/bin/env python3
"""
一键生成 .env 配置
==================
为自部署用户生成一份可直接使用的 .env，自动填好安全随机密钥。

设计原则：
- **不覆盖已存在的 .env**（除非显式加 --force），避免毁掉用户已有配置。
- 不猜测用户的 API Key —— 密钥这类私密信息必须用户自己填。
  生成的 .env 里 AI 相关项留空，用户可登录后在界面上配置（更友好）。
- 幂等：重复执行不会产生副作用。

用法:
    python scripts/setup_env.py            # 生成 .env（若已存在则跳过）
    python scripts/setup_env.py --force     # 覆盖重新生成
"""

from __future__ import annotations

import argparse
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"


def _random_secret(nbytes: int = 32) -> str:
    return secrets.token_hex(nbytes)


def _random_password(length: int = 20) -> str:
    """生成不含 shell/URL 特殊字符的强密码，避免写进 DATABASE_URL 时被转义。"""
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


TEMPLATE = """# ============================================================
# 基金智能分析系统 — 本地配置
# 本文件由 scripts/setup_env.py 自动生成：{stamp}
# 已加入 .gitignore，不会被提交到版本库。
# ============================================================

# ---- 运行形态 ----
# community = 开源自部署，不限次数，AI 用自己的 key
# cloud     = 托管运营版，按套餐计费
EDITION={edition}

# ---- 数据库 ----
# 留空 → SQLite 单机模式（data/fund_analysis.db），免登录直接用。
# Docker 部署时由 docker-compose 自动指向内置 postgres，无需在此填写。
# 云上自建请取消注释并改成实际地址：
# DATABASE_URL=postgresql://user:password@host:5432/fund_analysis

# Postgres 密码（仅 Docker 内置库使用）
DB_PASSWORD={db_password}

# ---- 会话安全（已自动生成随机值）----
JWT_SECRET={jwt_secret}
JWT_EXPIRY_HOURS=24

# ---- 默认管理员（仅多用户模式首次初始化时创建）----
# 留空则不创建管理员。多用户模式建议设置一个强密码。
# ADMIN_DEFAULT_PASSWORD=

# ---- AI 模型（留空即可，登录后在「账户设置 → 🔌 AI 与数据源」里配置）----
# 想在服务端一次性配好，就填下面这三项：
LLM_PRESET=
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=

# ---- 行情数据源 ----
DATA_PROVIDER=akshare
TUSHARE_TOKEN=
QUOTE_CACHE_TTL=300

# ---- 其他 ----
TZ=Asia/Shanghai
# APP_PORT=8501
# API_ACCESS_KEY={api_key}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 .env 配置文件")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 .env")
    parser.add_argument("--edition", default="community",
                        choices=["community", "cloud"],
                        help="运行形态（默认 community）")
    args = parser.parse_args()

    if ENV_FILE.exists() and not args.force:
        print(f"ℹ️  {ENV_FILE} 已存在，未做修改。")
        print("   如需重新生成，请加 --force（会覆盖现有配置，请先备份）。")
        return 0

    if ENV_FILE.exists() and args.force:
        backup = ENV_FILE.with_suffix(".env.bak")
        shutil.copy2(ENV_FILE, backup)
        print(f"📦 已备份原配置到 {backup.name}")

    from datetime import datetime
    content = TEMPLATE.format(
        stamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        edition=args.edition,
        db_password=_random_password(),
        jwt_secret=_random_secret(),
        api_key=_random_secret(16),
    )

    ENV_FILE.write_text(content, encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)
    except Exception:
        pass

    print(f"✅ 已生成 {ENV_FILE}")
    print("   已自动填入随机会话密钥与数据库密码。")
    print()
    print("下一步：")
    print("  Docker：  docker compose up -d")
    print("  本地：    pip install -r requirements.txt && streamlit run app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
