"""
主题归并配置 — 东财板块/概念 → 基金可观察主题
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml

_TAXONOMY_PATH = Path(__file__).parent.parent / "data" / "theme_taxonomy.yaml"


@lru_cache(maxsize=1)
def load_taxonomy() -> Dict[str, dict]:
    if not _TAXONOMY_PATH.exists():
        return {}
    with open(_TAXONOMY_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("themes") or {}


def get_theme_names() -> List[str]:
    return list(load_taxonomy().keys())


def map_sector_to_theme(sector_name: str) -> Optional[str]:
    """将东财板块名称映射到主题。"""
    name = (sector_name or "").strip()
    if not name:
        return None
    for theme, cfg in load_taxonomy().items():
        sectors = cfg.get("sectors") or []
        keywords = cfg.get("keywords") or []
        for s in sectors:
            if s in name or name in s:
                return theme
        for kw in keywords:
            if kw in name:
                return theme
    return None


def theme_sector_map() -> Dict[str, List[str]]:
    """主题 → 配置的板块名列表（归并审计用）。"""
    out: Dict[str, List[str]] = {}
    for theme, cfg in load_taxonomy().items():
        out[theme] = list(cfg.get("sectors") or [])
    return out


def get_theme_representatives(theme: str) -> List[dict]:
    """主题配置的代表基金列表 [{code, name, kind}]。"""
    cfg = load_taxonomy().get(theme) or {}
    reps = cfg.get("representatives") or []
    out = []
    for r in reps:
        if not isinstance(r, dict):
            continue
        code = str(r.get("code", "")).zfill(6)
        if not code.isdigit():
            continue
        out.append({
            "code": code,
            "name": str(r.get("name") or code),
            "kind": str(r.get("kind") or "index"),
        })
    return out[:3]


def reload_taxonomy() -> Dict[str, dict]:
    load_taxonomy.cache_clear()
    return load_taxonomy()
