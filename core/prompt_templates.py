"""
提示词模板管理器
================
负责从 YAML 文件加载提示词模板，支持变量插值和参数验证。

设计原则:
- 提示词内容与代码分离（存储在 prompts/ 目录下的 YAML 文件）
- 支持 `{variable_name}` 格式的变量插值
- 提供参数元数据，便于前端动态生成表单
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .config import config

logger = logging.getLogger(__name__)


class PromptTemplate:
    """单个提示词模板的封装。"""

    def __init__(self, data: dict, file_path: str):
        self.name: str = data.get("name", "")
        self.title: str = data.get("title", "")
        self.category: str = data.get("category", "")
        self.order: int = data.get("order", 99)
        self.system_prompt: str = data.get("system_prompt", "")
        self.user_prompt_template: str = data.get("user_prompt_template", "")
        self.parameters: List[Dict[str, Any]] = data.get("parameters", [])
        self.file_path: str = file_path

    def render(
        self, params: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str]:
        """
        渲染提示词：将参数值填入模板中的 {placeholder} 占位符。

        Args:
            params: 参数值字典，如 {"index_name": "沪深300", "fund_data": "..."}
                    未提供的参数使用其 default 值

        Returns:
            (system_prompt, user_prompt): 填充后的 system + user 提示词对
        """
        params = params or {}

        # 构建完整的变量值字典（参数值 > 默认值）
        values: Dict[str, str] = {}
        for p in self.parameters:
            name = p.get("name", "")
            if name in params and params[name]:
                values[name] = str(params[name])
            elif "default" in p:
                values[name] = str(p["default"])

        # 填充模板
        system = self.system_prompt
        user = self.user_prompt_template

        try:
            user = user.format(**values)
        except KeyError as e:
            logger.warning(f"模板 {self.name} 缺少参数: {e}")
            # 对缺失的参数保留占位符
            for name in values:
                user = user.replace(f"{{{name}}}", values[name])

        return system.strip(), user.strip()

    def get_form_schema(self) -> List[Dict[str, Any]]:
        """
        获取参数表单 schema，供 Streamlit 前端动态生成输入控件。

        Returns:
            [{name, type, description, required, default, label}, ...]
        """
        schema = []
        for p in self.parameters:
            schema.append(
                {
                    "name": p.get("name", ""),
                    "type": p.get("type", "text"),
                    "description": p.get("description", ""),
                    "required": p.get("required", False),
                    "default": p.get("default", ""),
                    "label": p.get("description", p.get("name", "")),
                }
            )
        return schema

    def __repr__(self):
        return f"PromptTemplate(name='{self.name}', title='{self.title}')"


class PromptManager:
    """
    提示词管理器。

    功能:
    - 加载 prompts/ 目录下所有 YAML 模板
    - 按名称/类别检索模板
    - 渲染模板（变量插值）

    使用示例:
        pm = PromptManager()
        template = pm.get("macro_research")
        system, user = template.render({"macro_data": "CPI: 0.3%, PPI: -2.5%..."})
        # 发送 system + user 到 Claude API
    """

    def __init__(self, prompts_dir: Optional[Path] = None):
        self._prompts_dir = prompts_dir or config.prompts_dir
        self._templates: Dict[str, PromptTemplate] = {}
        self._load_all()

    def _load_all(self):
        """加载 prompts/ 目录下所有 YAML 文件。"""
        if not self._prompts_dir.exists():
            logger.warning(f"提示词目录不存在: {self._prompts_dir}")
            return

        yaml_files = sorted(self._prompts_dir.glob("*.yaml"))
        if not yaml_files:
            logger.warning(f"提示词目录下无 YAML 文件: {self._prompts_dir}")
            return

        for fpath in yaml_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                if not isinstance(data, dict):
                    logger.warning(f"跳过非字典格式的 YAML: {fpath}")
                    continue

                name = data.get("name", fpath.stem)
                template = PromptTemplate(data, str(fpath))
                self._templates[name] = template
                logger.info(f"已加载提示词模板: {name}")

            except yaml.YAMLError as e:
                logger.error(f"解析 YAML 失败 ({fpath}): {e}")
            except Exception as e:
                logger.error(f"加载模板失败 ({fpath}): {e}")

        logger.info(f"共加载 {len(self._templates)} 个提示词模板")

        # 同时索引 .md Agent Prompt 文件
        self._agent_prompts: Dict[str, str] = {}
        for md_path in sorted(self._prompts_dir.glob("*.md")):
            try:
                self._agent_prompts[md_path.stem] = md_path.read_text(encoding="utf-8")
            except Exception:
                pass

    def get(self, name: str) -> Optional[PromptTemplate]:
        """按名称获取 YAML 模板。"""
        return self._templates.get(name)

    def get_agent_prompt(self, name: str) -> str:
        """
        获取 Agent System Prompt（.md 文件）。

        Args:
            name: Agent 名称，如 'prospectus_analyzer', 'wealth_advisor'

        Returns:
            Agent 的 System Prompt 文本，未找到则返回空字符串
        """
        return self._agent_prompts.get(name, "")

    @property
    def agent_names(self) -> List[str]:
        """返回所有已加载的 Agent 名称列表。"""
        return sorted(self._agent_prompts.keys())

    @property
    def total_count(self) -> int:
        """YAML 模板 + MD Agent 总数。"""
        return len(self._templates) + len(self._agent_prompts)

    def list_all(self) -> List[PromptTemplate]:
        """列出所有模板（按 order 排序）。"""
        return sorted(self._templates.values(), key=lambda t: t.order)

    def list_by_category(self, category: str) -> List[PromptTemplate]:
        """按类别筛选模板。"""
        return sorted(
            [t for t in self._templates.values() if t.category == category],
            key=lambda t: t.order,
        )

    @property
    def categories(self) -> List[str]:
        """获取所有类别（去重）。"""
        seen = set()
        result = []
        for t in sorted(self._templates.values(), key=lambda t: t.order):
            if t.category not in seen:
                seen.add(t.category)
                result.append(t.category)
        return result

    @property
    def count(self) -> int:
        """已加载模板数量。"""
        return len(self._templates)

    def reload(self):
        """重新加载所有模板（开发调试用）。"""
        self._templates.clear()
        self._load_all()


# 全局单例
_manager_instance: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    """获取全局 PromptManager 实例。"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = PromptManager()
    return _manager_instance
