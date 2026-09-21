"""
YAML 策略引擎
=============
加载预置和自定义 YAML 策略模板，驱动 AI 执行规则化基金筛选。

策略文件位置:
    - strategies/          — 系统预置策略（随项目分发）
    - data/strategies/     — 用户自定义策略（通过 UI 创建）

策略 YAML 格式见 strategies/ 目录下的示例文件。

使用方式:
    from core.strategy_engine import get_strategy_loader, StrategyExecutor

    loader = get_strategy_loader()
    strategy = loader.get("bond_ladder")
    executor = StrategyExecutor(strategy)
    result = executor.execute_screen(fund_list_context, market_phase="falling_rates")
"""

import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any

from .data_fetcher import get_fetcher
from .ai_analyzer import get_analyzer


# ============================================================
# 数据类
# ============================================================

class Strategy:
    """从 YAML 解析的策略"""

    def __init__(self, data: dict, filepath: str):
        self.name = data.get("name", Path(filepath).stem)
        self.display_name = data.get("display_name", self.name)
        self.description = data.get("description", "")
        self.category = data.get("category", "general")
        self.instructions = data.get("instructions", "")
        self.required_tools = data.get("required_tools", [])
        self.market_regimes = data.get("market_regimes", [])
        self.default_priority = data.get("default_priority", 50)
        self.filepath = filepath

        # 判断来源
        if "data/strategies" in filepath:
            self.source = "user"
        else:
            self.source = "system"

    @property
    def category_label(self) -> str:
        labels = {
            "fixed_income": "🔵 固收",
            "active_equity": "🔴 主动权益",
            "asset_allocation": "🟡 资产配置",
            "index": "🟢 指数",
            "general": "⚪ 通用",
        }
        return labels.get(self.category, "⚪ 通用")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "category_label": self.category_label,
            "market_regimes": self.market_regimes,
            "source": self.source,
            "filepath": self.filepath,
        }

    def format_as_prompt_context(self) -> str:
        """将策略指令格式化为可注入 AI prompt 的 Markdown"""
        parts = [
            f"## 策略: {self.display_name}",
            f"**类别**: {self.category_label}",
            f"**适用市场阶段**: {', '.join(self.market_regimes) if self.market_regimes else '通用'}",
            "",
            self.instructions,
        ]
        return "\n".join(parts)


# ============================================================
# 策略加载器
# ============================================================

class StrategyLoader:
    """加载和管理 YAML 策略文件"""

    def __init__(self):
        self._strategies: Dict[str, Strategy] = {}
        self._strategies_dir = Path(__file__).parent.parent / "strategies"
        self._user_dir = Path(__file__).parent.parent / "data" / "strategies"
        self.reload()

    def reload(self):
        """重新加载所有策略"""
        self._strategies = {}
        # 系统策略
        if self._strategies_dir.exists():
            for fpath in self._strategies_dir.glob("*.yaml"):
                self._load_file(fpath)
        # 用户策略（优先级更高，覆盖同名系统策略）
        self._user_dir.mkdir(parents=True, exist_ok=True)
        for fpath in self._user_dir.glob("*.yaml"):
            self._load_file(fpath)

    def _load_file(self, fpath: Path):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data and isinstance(data, dict) and "name" in data:
                strategy = Strategy(data, str(fpath))
                self._strategies[strategy.name] = strategy
        except Exception:
            pass  # 解析失败则跳过

    def list_all(self, category: str = None) -> List[Strategy]:
        """列出所有策略，可按类别过滤"""
        strategies = list(self._strategies.values())
        if category:
            strategies = [s for s in strategies if s.category == category]
        return sorted(strategies, key=lambda s: s.default_priority)

    def get(self, name: str) -> Optional[Strategy]:
        """按名称获取策略"""
        return self._strategies.get(name)

    def get_categories(self) -> List[str]:
        """获取所有策略类别"""
        cats = set()
        for s in self._strategies.values():
            cats.add(s.category)
        return sorted(cats)

    def save_custom_strategy(self, strategy_data: dict):
        """
        保存用户自定义策略。

        Args:
            strategy_data: 包含 name, display_name, description, category,
                           instructions 等字段的字典
        """
        name = strategy_data.get("name", "custom")
        fpath = self._user_dir / f"{name}.yaml"
        with open(fpath, "w", encoding="utf-8") as f:
            yaml.dump(strategy_data, f, allow_unicode=True, default_flow_style=False)
        self.reload()

    def delete_custom_strategy(self, name: str):
        """删除用户自定义策略"""
        fpath = self._user_dir / f"{name}.yaml"
        if fpath.exists():
            fpath.unlink()
            self.reload()


# ============================================================
# 策略执行器
# ============================================================

class StrategyExecutor:
    """
    使用 AI 执行策略筛选。
    将策略规则 + 基金列表 + 市场阶段组合成 prompt，调用 AI 进行分析。
    """

    def __init__(self, strategy: Strategy):
        self.strategy = strategy

    def build_screening_prompt(self, fund_list_context: str, market_phase: str = "") -> tuple:
        """
        构建筛选 prompt。

        Args:
            fund_list_context: 基金列表的文本描述（从 fetcher 获取）
            market_phase: 当前市场阶段描述（可选，用于策略匹配）

        Returns:
            (system_prompt, user_prompt) 元组
        """
        system_prompt = f"""你是一位专业的基金筛选专家。请严格按照以下策略规则筛选基金。

{self.strategy.format_as_prompt_context()}

请严格按照策略规则对候选基金进行评分和排名。输出结构化 JSON 格式的筛选结果。"""

        user_prompt = f"""## 候选基金列表
{fund_list_context}

## 当前市场环境
{market_phase if market_phase else '未指定（通用市场环境）'}

请按策略规则对以上基金进行筛选、评分和排序，返回 JSON 结果。"""

        return system_prompt, user_prompt

    def execute_screen(
        self,
        fund_list_context: str,
        market_phase: str = "",
    ) -> dict:
        """
        执行 AI 策略筛选。

        Returns:
            {
                "success": bool,
                "content": str,        # AI 分析原文
                "error": str,          # 错误信息（如果失败）
            }
        """
        system_prompt, user_prompt = self.build_screening_prompt(
            fund_list_context, market_phase
        )

        try:
            analyzer = get_analyzer()
            result = analyzer.analyze(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=4096,
                temperature=0.3,
            )
            return result
        except Exception as e:
            return {"success": False, "content": "", "error": str(e)}


# ============================================================
# 单例
# ============================================================

_strategy_loader: Optional[StrategyLoader] = None


def get_strategy_loader() -> StrategyLoader:
    """获取 StrategyLoader 全局单例"""
    global _strategy_loader
    if _strategy_loader is None:
        _strategy_loader = StrategyLoader()
    return _strategy_loader
