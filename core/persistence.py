"""
JSON 配置文件持久化
==================
用于通知配置、策略配置等人类可编辑的非关系型配置数据。
所有文件存储在 data/ 目录下。

使用方式:
    from core.persistence import load_json_config, save_json_config

    config = load_json_config("notification_config")
    config["channels"]["wechat"] = {"webhook_url": "https://..."}
    save_json_config("notification_config", config)
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict


DATA_DIR = Path(__file__).parent.parent / "data"


def _ensure_dir():
    """确保 data/ 目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_json_config(name: str) -> dict:
    """
    加载 JSON 配置文件。

    Args:
        name: 配置文件名（不含扩展名），如 "notification_config"

    Returns:
        dict: 配置数据，文件不存在时返回空字典
    """
    _ensure_dir()
    filepath = DATA_DIR / f"{name}.json"
    if not filepath.exists():
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, IOError):
        return {}


def save_json_config(name: str, data: dict):
    """
    原子写入 JSON 配置文件（先写临时文件再 rename）。

    Args:
        name: 配置文件名（不含扩展名）
        data: 要保存的配置字典
    """
    _ensure_dir()
    filepath = DATA_DIR / f"{name}.json"

    # 原子写入：先写临时文件，成功后再 rename
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(DATA_DIR),
        prefix=f".{name}_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp_path, str(filepath))
    except Exception:
        # 清理临时文件
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# ---- 用户级配置文件名 ----

def _user_config_name(base_name: str) -> str:
    """生成用户隔离的配置文件名"""
    try:
        from core.db import get_user_id
        uid = get_user_id()
        return f"{base_name}_user{uid}" if uid != 1 else base_name
    except Exception:
        return base_name


# ---- 常用配置的便捷函数 ----

def load_notification_config() -> dict:
    """加载通知配置（按用户隔离）"""
    return load_json_config(_user_config_name("notification_config"))


def save_notification_config(config: dict):
    """保存通知配置（按用户隔离）"""
    save_json_config(_user_config_name("notification_config"), config)


def load_strategy_overrides() -> dict:
    """加载用户策略覆盖 data/strategy_overrides.json"""
    return load_json_config("strategy_overrides")


def save_strategy_overrides(config: dict):
    """保存用户策略覆盖 data/strategy_overrides.json"""
    save_json_config("strategy_overrides", config)
