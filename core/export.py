"""
分析结果导出模块
================
将 AI 分析结果导出为 Word (.docx)、PDF (.pdf)、Excel (.xlsx) 格式。

依赖:
    - Word:  python-docx
    - PDF:   weasyprint (推荐) 或 reportlab
    - Excel: openpyxl

安装:
    pip install python-docx weasyprint openpyxl

使用方式:
    from core.export import export_single_analysis, export_multi_analysis

    result_bytes, filename = export_single_analysis(history_record, "word")
"""

import io
import re
from datetime import datetime
from typing import List, Tuple, Optional


# ============================================================
# Helpers
# ============================================================

def _sanitize_filename(name: str) -> str:
    """生成安全的文件名"""
    safe = re.sub(r'[<>:"/\\|?*]', '_', name)
    return safe.strip()[:80]


def _clean_markdown_for_text(text: str) -> str:
    """去除 Markdown 标记，保留纯文本"""
    # 去除代码块
    text = re.sub(r'```[\s\S]*?```', '[代码块]', text)
    # 去除行内代码
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # 去除标题标记
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # 去除粗体/斜体
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    # 去除链接
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    return text


def _markdown_to_plain_lines(text: str) -> List[str]:
    """将 Markdown 文本转为纯文本行列表"""
    lines = []
    for line in text.split("\n"):
        clean = _clean_markdown_for_text(line.strip())
        if clean:
            lines.append(clean)
    return lines


# ============================================================
# 决策仪表盘 (structured_result) 渲染
# ============================================================

_LEVEL_LABEL = {"info": "ℹ️", "warning": "⚠️", "danger": "❌"}


def _get_dashboard(record) -> Optional[dict]:
    """从记录中取出结构化决策仪表盘 dict（若有）。"""
    d = getattr(record, "structured_result", None)
    if callable(d):
        try:
            d = d()
        except Exception:
            d = None
    if isinstance(d, dict) and d.get("schema_version"):
        return d
    return None


def _dashboard_to_html(d: dict) -> str:
    """决策仪表盘 → HTML 片段（用于 PDF）。"""
    cc = d.get("core_conclusion", {}) or {}
    dp = d.get("data_perspective", {}) or {}
    sfv = d.get("signal_for_validation", {}) or {}
    op = d.get("observation_plan", {}) or {}
    risks = d.get("risk_watchlist", []) or []

    parts = ['<div class="dashboard"><h2>📋 决策仪表盘</h2>']

    stars = cc.get("rating_stars")
    if stars:
        parts.append(f'<p class="stars">{"★" * int(stars)} ({stars}/5)</p>')
    if cc.get("one_liner"):
        parts.append(f'<p class="oneliner">{cc["one_liner"]}</p>')

    suit = "、".join(cc.get("suitability") or []) or "—"
    ns = "、".join(cc.get("not_suitable") or []) or "—"
    parts.append(f'<p><b>✅ 适配：</b>{suit}　<b>⛔ 不适配：</b>{ns}</p>')

    if sfv:
        conf = sfv.get("confidence", 0) or 0
        parts.append(
            f'<p><b>🔍 观察信号：</b>{sfv.get("action","watch")} · '
            f'置信 {conf:.0%} · {sfv.get("horizon_days", 20)} 日</p>'
        )

    metrics = dp.get("metrics") or []
    if metrics:
        cells = "".join(
            f'<td><b>{m.get("label","—")}</b><br>{m.get("value","—")}'
            f'{" · " + m.get("badge") if m.get("badge") else ""}</td>'
            for m in metrics[:6]
        )
        parts.append(f'<table class="metrics"><tr>{cells}</tr></table>')
    if dp.get("valuation_context"):
        parts.append(f'<p class="ctx">📊 {dp["valuation_context"]}</p>')

    if risks:
        items = "".join(
            f'<li>{_LEVEL_LABEL.get(r.get("level","info"),"ℹ️")} '
            f'<b>{r.get("item","")}</b> — {r.get("detail","")}</li>'
            for r in risks[:6]
        )
        parts.append(f'<p><b>风险关注：</b></p><ul>{items}</ul>')

    if op.get("horizon") or op.get("conditions"):
        conds = "".join(f"<li>{c}</li>" for c in (op.get("conditions") or [])[:5])
        parts.append(
            f'<p><b>观察计划：</b>{op.get("horizon","")}</p><ul>{conds}</ul>'
        )

    attr = d.get("attribution") or {}
    attr_parts = [f"{k} {v:.0%}" for k, v in attr.items() if isinstance(v, (int, float))]
    if attr_parts:
        parts.append(f'<p class="ctx">归因权重：{" · ".join(attr_parts)}</p>')

    parts.append("</div><hr>")
    return "\n".join(parts)


def _dashboard_to_word(doc, d: dict):
    """决策仪表盘 → Word 段落。"""
    from docx.shared import Pt

    cc = d.get("core_conclusion", {}) or {}
    dp = d.get("data_perspective", {}) or {}
    sfv = d.get("signal_for_validation", {}) or {}
    op = d.get("observation_plan", {}) or {}
    risks = d.get("risk_watchlist", []) or []

    doc.add_heading("📋 决策仪表盘", level=1)

    stars = cc.get("rating_stars")
    if stars:
        p = doc.add_paragraph()
        p.add_run("★" * int(stars) + f" ({stars}/5)").bold = True
    if cc.get("one_liner"):
        doc.add_paragraph(cc["one_liner"])

    suit = "、".join(cc.get("suitability") or []) or "—"
    ns = "、".join(cc.get("not_suitable") or []) or "—"
    doc.add_paragraph(f"✅ 适配：{suit}    ⛔ 不适配：{ns}")

    if sfv:
        conf = sfv.get("confidence", 0) or 0
        doc.add_paragraph(
            f"🔍 观察信号：{sfv.get('action','watch')} · "
            f"置信 {conf:.0%} · {sfv.get('horizon_days', 20)} 日"
        )

    for m in (dp.get("metrics") or [])[:6]:
        badge = f" · {m.get('badge')}" if m.get("badge") else ""
        doc.add_paragraph(f"{m.get('label','—')}: {m.get('value','—')}{badge}", style="List Bullet")
    if dp.get("valuation_context"):
        doc.add_paragraph(f"📊 {dp['valuation_context']}")

    if risks:
        doc.add_paragraph("风险关注：")
        for r in risks[:6]:
            icon = _LEVEL_LABEL.get(r.get("level", "info"), "ℹ️")
            doc.add_paragraph(f"{icon} {r.get('item','')} — {r.get('detail','')}", style="List Bullet")

    if op.get("horizon") or op.get("conditions"):
        doc.add_paragraph(f"观察计划：{op.get('horizon','')}")
        for c in (op.get("conditions") or [])[:5]:
            doc.add_paragraph(c, style="List Bullet")

    doc.add_paragraph()


# ============================================================
# Word 导出
# ============================================================

def _export_word(record, fund_code: str = "") -> Tuple[bytes, str]:
    """导出为 Word (.docx)"""
    try:
        from docx import Document
        from docx.shared import Pt, Inches, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise ImportError("需要安装 python-docx: pip install python-docx")

    doc = Document()

    # 标题
    title = doc.add_heading("基金分析报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 元数据表
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fund_label = f"{record.fund_name}({record.fund_code})" if record.fund_code else fund_code or "全局分析"
    meta.add_run(f"基金: {fund_label}\n").font.size = Pt(11)
    meta.add_run(f"分析页面: {record.page_name}\n").font.size = Pt(11)
    meta.add_run(f"模型: {record.model}\n").font.size = Pt(11)
    meta.add_run(f"时间: {record.created_at}\n").font.size = Pt(11)
    if record.elapsed_seconds:
        meta.add_run(f"耗时: {record.elapsed_seconds:.1f}s\n").font.size = Pt(11)

    doc.add_paragraph()  # 空行

    # 决策仪表盘（若有结构化结果）
    _dash = _get_dashboard(record)
    if _dash:
        _dashboard_to_word(doc, _dash)

    # 分析内容
    lines = _markdown_to_plain_lines(record.result_content)
    for line in lines:
        if line.startswith("#"):
            level = min(3, len(re.match(r'^#+', line).group()))
            doc.add_heading(line.lstrip("#").strip(), level=level)
        elif line.startswith("- ") or line.startswith("* "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif re.match(r'^\d+[.)]\s', line):
            doc.add_paragraph(line, style="List Number")
        else:
            # 处理粗体标记
            if "**" in line:
                parts = line.split("**")
                p = doc.add_paragraph()
                for i, part in enumerate(parts):
                    r = p.add_run(part)
                    if i % 2 == 1:
                        r.bold = True
            else:
                doc.add_paragraph(line)

    # 页脚
    doc.add_paragraph()
    footer = doc.add_paragraph("— 本报告由基金智能分析系统自动生成，仅供参考 —")
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.runs[0].font.size = Pt(9)
    footer.runs[0].font.color.rgb = RGBColor(150, 150, 150)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    fname = _sanitize_filename(f"{fund_label}_分析报告") + ".docx"
    return buf.getvalue(), fname


# ============================================================
# PDF 导出
# ============================================================

def _export_pdf(record, fund_code: str = "") -> Tuple[bytes, str]:
    """导出为 PDF（HTML → PDF）"""
    try:
        from weasyprint import HTML
    except ImportError:
        raise ImportError("需要安装 weasyprint: pip install weasyprint")

    fund_label = f"{record.fund_name}({record.fund_code})" if record.fund_code else fund_code or "全局分析"

    _dash = _get_dashboard(record)
    dashboard_html = _dashboard_to_html(_dash) if _dash else ""

    # 构建 HTML
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; font-size: 12pt; line-height: 1.8; margin: 40px; color: #333; }}
  h1 {{ text-align: center; color: #1a365d; font-size: 18pt; margin-bottom: 10px; }}
  .meta {{ text-align: center; color: #64748b; font-size: 10pt; margin-bottom: 30px; border-bottom: 1px solid #e2e8f0; padding-bottom: 15px; }}
  h2 {{ color: #1a365d; font-size: 14pt; margin-top: 24px; }}
  h3 {{ color: #334155; font-size: 12pt; margin-top: 18px; }}
  ul, ol {{ margin-left: 20px; }}
  li {{ margin: 4px 0; }}
  pre {{ background: #f1f5f9; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 10pt; }}
  code {{ background: #f1f5f9; padding: 2px 4px; border-radius: 3px; font-size: 10pt; }}
  hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 20px 0; }}
  .footer {{ text-align: center; color: #94a3b8; font-size: 9pt; margin-top: 40px; border-top: 1px solid #e2e8f0; padding-top: 15px; }}
  .disclaimer {{ color: #94a3b8; font-size: 9pt; text-align: center; }}
  .dashboard {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; margin-bottom: 20px; }}
  .dashboard h2 {{ margin-top: 0; }}
  .dashboard .stars {{ color: #f59e0b; font-size: 14pt; margin: 4px 0; }}
  .dashboard .oneliner {{ background: #eff6ff; border-left: 3px solid #2563eb; padding: 8px 12px; border-radius: 4px; }}
  .dashboard .ctx {{ color: #64748b; font-size: 10pt; }}
  .dashboard table.metrics {{ width: 100%; border-collapse: collapse; margin: 8px 0; }}
  .dashboard table.metrics td {{ border: 1px solid #e2e8f0; padding: 6px 10px; font-size: 10pt; }}
  @page {{ margin: 30px; }}
</style>
</head>
<body>
<h1>基金分析报告</h1>
<div class="meta">
  <p>基金: {fund_label} | 分析页面: {record.page_name}</p>
  <p>模型: {record.model} | 时间: {record.created_at} | 耗时: {record.elapsed_seconds:.1f}s</p>
</div>
<hr>
{dashboard_html}
{_md_to_html(record.result_content)}
<div class="footer">
  <p class="disclaimer">— 本报告由基金智能分析系统自动生成，仅供参考，不构成投资建议 —</p>
</div>
</body>
</html>"""

    html = HTML(string=html_content)
    pdf_bytes = html.write_pdf()

    fname = _sanitize_filename(f"{fund_label}_分析报告") + ".pdf"
    return pdf_bytes, fname


def _md_to_html(md_text: str) -> str:
    """简易 Markdown → HTML 转换（正确关闭标签、处理嵌套列表）"""
    lines = md_text.split("\n")
    html_lines = []
    in_list = False
    list_type = None
    in_code_block = False
    indent_level = 0
    list_stack = []  # 跟踪嵌套列表层级: [(indent, list_type)]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                # 关闭所有嵌套列表
                while list_stack:
                    lt = list_stack.pop()
                    html_lines.append("</ul>" if lt == "ul" else "</ol>")
                in_list = False
            html_lines.append("<br>")
            continue

        current_indent = len(line) - len(line.lstrip())

        # 代码块
        if stripped.startswith("```"):
            if in_list:
                while list_stack:
                    lt = list_stack.pop()
                    html_lines.append("</ul>" if lt == "ul" else "</ol>")
                in_list = False
            if in_code_block:
                html_lines.append("</code></pre>")
                in_code_block = False
            else:
                html_lines.append("<pre><code>")
                in_code_block = True
            continue

        if in_code_block:
            html_lines.append(stripped)
            continue

        # 标题
        if stripped.startswith("### "):
            if in_list:
                while list_stack:
                    lt = list_stack.pop()
                    html_lines.append("</ul>" if lt == "ul" else "</ol>")
                in_list = False
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            if in_list:
                while list_stack:
                    lt = list_stack.pop()
                    html_lines.append("</ul>" if lt == "ul" else "</ol>")
                in_list = False
            html_lines.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            if in_list:
                while list_stack:
                    lt = list_stack.pop()
                    html_lines.append("</ul>" if lt == "ul" else "</ol>")
                in_list = False
            html_lines.append(f"<h1>{stripped[2:]}</h1>")
        # 无序列表
        elif stripped.startswith("- ") or stripped.startswith("* "):
            is_ul = True
            if not in_list:
                html_lines.append("<ul>")
                list_stack = [(current_indent, "ul")]
                in_list = True
            else:
                # 处理嵌套：当前缩进更深 → 开新层
                last_indent, _ = list_stack[-1] if list_stack else (0, "")
                if current_indent > last_indent + 1:
                    html_lines.append("<ul>")
                    list_stack.append((current_indent, "ul"))
                elif current_indent < last_indent:
                    # 退出嵌套层
                    while list_stack and list_stack[-1][0] > current_indent:
                        lt = list_stack.pop()[1]
                        html_lines.append("</ul>" if lt == "ul" else "</ol>")
            item = stripped[2:]
            item = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', item)
            html_lines.append(f"<li>{item}</li>")
        # 有序列表
        elif re.match(r'^\d+[.)]\s', stripped):
            if not in_list:
                html_lines.append("<ol>")
                list_stack = [(current_indent, "ol")]
                in_list = True
            else:
                last_indent, _ = list_stack[-1] if list_stack else (0, "")
                if current_indent > last_indent + 1:
                    html_lines.append("<ol>")
                    list_stack.append((current_indent, "ol"))
                elif current_indent < last_indent:
                    while list_stack and list_stack[-1][0] > current_indent:
                        lt = list_stack.pop()[1]
                        html_lines.append("</ul>" if lt == "ul" else "</ol>")
            item = re.sub(r'^\d+[.)]\s', '', stripped)
            html_lines.append(f"<li>{item}</li>")
        # 分隔线
        elif stripped == "---":
            if in_list:
                while list_stack:
                    lt = list_stack.pop()
                    html_lines.append("</ul>" if lt == "ul" else "</ol>")
                in_list = False
            html_lines.append("<hr>")
        # 普通段落
        else:
            if in_list:
                while list_stack:
                    lt = list_stack.pop()
                    html_lines.append("</ul>" if lt == "ul" else "</ol>")
                in_list = False
            html_lines.append(f"<p>{stripped}</p>")

    if in_code_block:
        html_lines.append("</code></pre>")
    if in_list:
        while list_stack:
            lt = list_stack.pop()
            html_lines.append("</ul>" if lt == "ul" else "</ol>")

    return "\n".join(html_lines)


# ============================================================
# Excel 导出
# ============================================================

def _export_excel(record, fund_code: str = "") -> Tuple[bytes, str]:
    """导出为 Excel (.xlsx) — 单条记录"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        raise ImportError("需要安装 openpyxl: pip install openpyxl")

    wb = Workbook()
    ws = wb.active
    ws.title = "分析报告"

    # 样式
    header_font = Font(name="微软雅黑", size=14, bold=True, color="1a365d")
    meta_font = Font(name="微软雅黑", size=10, color="64748b")
    section_font = Font(name="微软雅黑", size=12, bold=True, color="1a365d")
    body_font = Font(name="微软雅黑", size=10)
    header_fill = PatternFill(start_color="e2e8f0", end_color="e2e8f0", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="e2e8f0"),
        right=Side(style="thin", color="e2e8f0"),
        top=Side(style="thin", color="e2e8f0"),
        bottom=Side(style="thin", color="e2e8f0"),
    )

    fund_label = f"{record.fund_name}({record.fund_code})" if record.fund_code else fund_code or "全局分析"
    row = 1

    # 标题
    ws.merge_cells(f"A{row}:D{row}")
    cell = ws.cell(row=row, column=1, value="基金分析报告")
    cell.font = header_font
    cell.alignment = Alignment(horizontal="center")
    row += 2

    # 元数据
    meta_rows = [
        ["基金", fund_label, "分析页面", record.page_name],
        ["模型", record.model, "时间", record.created_at],
        ["耗时", f"{record.elapsed_seconds:.1f}s", "", ""],
    ]
    for mr in meta_rows:
        for ci, val in enumerate(mr):
            cell = ws.cell(row=row, column=ci + 1, value=val)
            cell.font = meta_font
            if ci % 2 == 0:
                cell.fill = header_fill
        row += 1
    row += 1

    # 分析内容
    lines = _markdown_to_plain_lines(record.result_content)
    for line in lines:
        if line.startswith("#"):
            cell = ws.cell(row=row, column=1, value=line.lstrip("#").strip())
            cell.font = section_font
            ws.merge_cells(f"A{row}:D{row}")
            row += 1
        elif line.startswith("- "):
            ws.cell(row=row, column=1, value="•")
            ws.cell(row=row, column=1).font = body_font
            ws.merge_cells(f"B{row}:D{row}")
            ws.cell(row=row, column=2, value=line[2:]).font = body_font
            row += 1
        else:
            ws.merge_cells(f"A{row}:D{row}")
            ws.cell(row=row, column=1, value=line).font = body_font
            row += 1

    # 列宽
    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 25
    ws.column_dimensions["C"].width = 25
    ws.column_dimensions["D"].width = 25

    # 页脚
    row += 2
    ws.merge_cells(f"A{row}:D{row}")
    cell = ws.cell(row=row, column=1, value="— 本报告由基金智能分析系统自动生成，仅供参考 —")
    cell.font = Font(name="微软雅黑", size=9, color="94a3b8")
    cell.alignment = Alignment(horizontal="center")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    fname = _sanitize_filename(f"{fund_label}_分析报告") + ".xlsx"
    return buf.getvalue(), fname


def _export_multi_excel(records, fund_code: str = "") -> Tuple[bytes, str]:
    """导出多条记录为 Excel"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        raise ImportError("需要安装 openpyxl: pip install openpyxl")

    wb = Workbook()
    ws = wb.active
    ws.title = "分析历史"

    header_font = Font(name="微软雅黑", size=12, bold=True, color="1a365d")
    header_fill = PatternFill(start_color="e2e8f0", end_color="e2e8f0", fill_type="solid")
    body_font = Font(name="微软雅黑", size=10)

    # 表头
    headers = ["日期", "页面", "基金代码", "基金名称", "模型", "耗时(s)", "分析摘要"]
    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill

    for ri, rec in enumerate(records, 2):
        values = [
            rec.created_at, rec.page_name, rec.fund_code,
            rec.fund_name, rec.model, round(rec.elapsed_seconds, 1),
            rec.preview[:200],
        ]
        for ci, val in enumerate(values, 1):
            ws.cell(row=ri, column=ci, value=val).font = body_font

    # 列宽
    for ci, w in enumerate([20, 18, 12, 16, 18, 10, 60], 1):
        ws.column_dimensions[chr(64 + ci)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    fname = _sanitize_filename(f"{fund_code or '多基金'}_分析历史") + ".xlsx"
    return buf.getvalue(), fname


# ============================================================
# 公共 API
# ============================================================

def export_single_analysis(record, format: str = "word") -> Tuple[bytes, str]:
    """
    导出单条分析结果。

    Args:
        record: AnalysisRecord 对象
        format: "word" | "pdf" | "excel"

    Returns:
        (bytes, filename) 元组
    """
    exporters = {
        "word": _export_word,
        "pdf": _export_pdf,
        "excel": _export_excel,
    }
    exporter = exporters.get(format)
    if not exporter:
        raise ValueError(f"不支持的格式: {format}，可选: word/pdf/excel")
    return exporter(record)


def export_multi_analysis(records, format: str = "excel", fund_code: str = "") -> Tuple[bytes, str]:
    """
    导出多条分析结果。

    注意：Word/PDF 格式仅导出第一条记录（单文档限制）。
    Excel 格式导出全部记录为一张表。

    Args:
        records: AnalysisRecord 列表
        format: "word" | "pdf" | "excel"
        fund_code: 基金代码（用于文件名）

    Returns:
        (bytes, filename) 元组
    """
    if not records:
        raise ValueError("无记录可导出")

    if format == "excel":
        return _export_multi_excel(records, fund_code)
    elif format == "word":
        return _export_word(records[0], fund_code)
    elif format == "pdf":
        return _export_pdf(records[0], fund_code)
    else:
        raise ValueError(f"不支持的格式: {format}")
