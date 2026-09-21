"""
AI 验证任务调度 — 每日自动跑批
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"
LAST_RUN_FILE = DATA_DIR / "evaluation_last_run.txt"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def last_run_date() -> Optional[str]:
    if not LAST_RUN_FILE.exists():
        return None
    try:
        return LAST_RUN_FILE.read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def run_daily_evaluation_if_due(*, force: bool = False) -> Optional[dict]:
    """
    每个自然日最多执行一次验证回填。
    Returns: 跑批结果 dict；若今日已跑则返回 None。
    """
    today = _today()
    if not force and last_run_date() == today:
        return None

    from .agent_memory import SignalEvaluator
    from .signal_evaluation import get_evaluation_manager

    legacy = SignalEvaluator().evaluate_pending_signals()
    batch = get_evaluation_manager().run_batch()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(today, encoding="utf-8")

    return {
        "date": today,
        "legacy": len(legacy),
        **batch,
    }
