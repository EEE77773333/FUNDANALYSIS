"""
Jinja2 报告模板引擎
===================
将分析结果渲染为品牌化专业报告。

模板:
    - report_markdown.j2 — 完整 Markdown 报告（PC/Web）
    - report_brief.j2    — 精简版（移动端/微信）

使用方式:
    from core.report_renderer import ReportRenderer

    renderer = ReportRenderer()
    markdown = renderer.render("markdown", {
        "title": "基金分析报告",
        "fund_name": "华夏成长混合",
        "fund_code": "000001",
        "analysis_content": "...",
    })
"""

from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class ReportRenderer:
    """
    报告渲染器。

    支持模板:
        - markdown: 完整 Markdown 报告
        - brief:    精简版
        - wechat:   微信适配版（纯文本+emoji）
    """

    def __init__(self):
        self._templates = {
            "markdown": self._template_markdown,
            "brief": self._template_brief,
            "wechat": self._template_wechat,
        }

    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """
        渲染报告。

        Args:
            template_name: "markdown" | "brief" | "wechat"
            context: 模板变量

        Returns:
            渲染后的文本
        """
        renderer = self._templates.get(template_name, self._template_markdown)
        return renderer(context)

    # ============================================================
    # 内置模板（纯 Python，无需 Jinja2 依赖）
    # ============================================================

    @staticmethod
    def _template_markdown(ctx: dict) -> str:
        """完整 Markdown 报告"""
        title = ctx.get("title", "基金分析报告")
        fund = ctx.get("fund_name", "")
        code = ctx.get("fund_code", "")
        content = ctx.get("analysis_content", "")
        model = ctx.get("model", "")
        elapsed = ctx.get("elapsed_seconds", 0)
        date_str = ctx.get("date", datetime.now().strftime("%Y-%m-%d %H:%M"))

        parts = [
            f"# {title}",
            "",
            f"**基金**: {fund} ({code})" if fund else "",
            f"**生成时间**: {date_str}",
            f"**模型**: {model} | **耗时**: {elapsed:.1f}s" if model else "",
            "",
            "---",
            "",
            content,
            "",
            "---",
            "",
            f"*本报告由基金智能分析系统自动生成 · {date_str}*",
            "*⚠️ 仅供参考，不构成投资建议*",
        ]
        return "\n".join(p for p in parts if p is not None)

    @staticmethod
    def _template_brief(ctx: dict) -> str:
        """精简版报告"""
        title = ctx.get("title", "分析摘要")
        fund = ctx.get("fund_name", "")
        content = ctx.get("analysis_content", "")[:800]

        parts = [
            f"## {title}",
            f"**{fund}**" if fund else "",
            "",
            content,
            "",
            "---",
            "⚠️ 仅供参考 · 基金投资需谨慎",
        ]
        return "\n".join(p for p in parts if p is not None)

    @staticmethod
    def _template_wechat(ctx: dict) -> str:
        """微信适配版（纯文本 + emoji）"""
        title = ctx.get("title", "基金分析")
        fund = ctx.get("fund_name", "")
        code = ctx.get("fund_code", "")
        content = ctx.get("analysis_content", "")

        # 提取前 600 字并去除 Markdown 标记
        import re
        text = content[:600]
        text = re.sub(r'#{1,6}\s+', '', text)
        text = re.sub(r'\*\*([^*]+)\*\*', r'【\1】', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)

        parts = [
            f"📊 {title}",
            f"🏦 {fund} ({code})" if fund else "",
            "",
            text,
            "",
            "— 基金智能分析系统",
        ]
        return "\n".join(p for p in parts if p is not None)
