"""
基金智能分析系统 — 核心模块
===============================

本系统整合五大类基金分析提示词，对接天天基金/东方财富实时数据，
通过 DeepSeek / Claude AI 进行智能分析，帮助投资者完成从宏观研判到微观选基的完整决策闭环。

AI 提供商：DeepSeek（默认）/ Anthropic Claude（备用）

模块说明:
- config: 系统配置管理
- data_fetcher: 数据采集（AKShare + 天天基金API）
- ai_analyzer: AI 分析引擎（DeepSeek/Claude 统一接口）
- prompt_templates: 提示词模板管理
- utils: 工具函数（缓存、指标计算、格式化）
"""

__version__ = "1.0.0"
__author__ = "Fund Analysis System"

# ============================================================
# macOS: 让 WeasyPrint (PDF 导出) 能定位 Homebrew 安装的
# Pango / Cairo / GLib(libgobject) 等原生库。
# Homebrew 默认把库装在 /opt/homebrew/lib (Apple Silicon)
# 或 /usr/local/lib (Intel)，这些目录不在 dyld 默认搜索路径中。
# 必须在任何 `import weasyprint` 之前设置。
# ============================================================
import os as _os
import sys as _sys

if _sys.platform == "darwin":
    _lib_dirs = "/opt/homebrew/lib:/usr/local/lib"
    _cur = _os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if _lib_dirs not in _cur:
        _os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
            f"{_lib_dirs}:{_cur}" if _cur else _lib_dirs
        )

from .config import Config
from .data_fetcher import DataFetcher
from .ai_analyzer import AIAnalyzer
from .prompt_templates import PromptManager

__all__ = ["Config", "DataFetcher", "AIAnalyzer", "PromptManager"]
