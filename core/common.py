"""
公共导入模块
============
集中导出页面常用组件，每个页面只需 1-2 行导入。

用法:
    from core.common import *             # 导入全部
    from core.common import fetcher, analyzer, pm  # 按需导入
"""

# 数据
from .data_fetcher import get_fetcher

# AI 引擎
from .ai_analyzer import get_analyzer

# 提示词
from .prompt_templates import get_prompt_manager

# UI 组件（全部导出）
from .ui_components import (
    render_page_header,
    render_sidebar_config,
    render_analysis_button,
    render_metrics_row,
    show_token_usage,
    show_elapsed_time,
    show_error,
    show_warning_box,
    show_info_box,
    show_dataframe,
    render_status_badge,
    render_risk_badge,
    render_param_form,
    check_api_ready,
    safe_run,
    run_analysis_stream,
    init_page_state,
)

# 工具
from .utils import (
    fmt_pct,
    fmt_money,
    safe_float,
    safe_int,
    calc_annualized_return,
    calc_max_drawdown,
    calc_sharpe_ratio,
    calc_annual_volatility,
    calc_sortino_ratio,
    calc_calmar_ratio,
    calc_win_rate,
    calc_alpha,
    calc_beta,
    calc_all_metrics,
)

# 懒加载的单例实例
fetcher = get_fetcher()
analyzer = get_analyzer()
pm = get_prompt_manager()

__all__ = [
    "fetcher", "analyzer", "pm",
    "get_fetcher", "get_analyzer", "get_prompt_manager",
]
