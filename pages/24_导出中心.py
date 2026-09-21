"""
导出中心 - 页面 24
================
将 AI 分析结果导出为 Word (.docx)、PDF (.pdf)、Excel (.xlsx) 格式。
支持单条报告导出和多条历史批量导出。

依赖安装:
    pip install python-docx weasyprint openpyxl

使用说明:
  1. 单条导出：从历史记录中选择，选择格式，点击下载
  2. 批量导出：筛选基金代码，选择多条记录，批量导出为 Excel
  3. 当前分析导出：在分析页面执行后，跳转到此处导出
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import base64

from core.config import config
from core.ui_components import (
    render_page_header,
    render_sidebar_config,
    render_top_toolbar,
    show_info_box,
    show_error,
    init_page_state,
    safe_run,
    section_header,
)
from core.history import get_history_manager


# ============================================================
# Page Config
# ============================================================
init_page_state({
    "export_selected_ids": [],
})


# ============================================================
# Helpers
# ============================================================

def _check_deps(format_name):
    """检查导出依赖是否安装"""
    checks = {
        "word": ("python-docx", "pip install python-docx"),
        "pdf": ("weasyprint", "pip install weasyprint"),
        "excel": ("openpyxl", "pip install openpyxl"),
    }
    pkg, install_cmd = checks.get(format_name, ("", ""))
    try:
        __import__(pkg.replace("-", "_"))
        return True, ""
    except ImportError:
        return False, install_cmd


def get_download_link(file_bytes, filename, mime_type):
    """生成下载链接"""
    b64 = base64.b64encode(file_bytes).decode()
    return f'<a href="data:{mime_type};base64,{b64}" download="{filename}" class="download-btn">⬇️ 下载 {filename}</a>'


def render_single_export():
    """单条导出 Tab"""
    hm = get_history_manager()
    records = hm.list_all(limit=100)

    if not records:
        st.info("📭 暂无分析历史记录。请先执行分析。")
        return

    # 选择记录
    sel_id = st.selectbox(
        "选择分析记录",
        [r.id for r in records],
        format_func=lambda rid: next(
            (f"[{r.created_at}] {r.page_name} - {r.fund_code or '全局'}" for r in records if r.id == rid),
            str(rid),
        ),
        key="export_record_sel",
    )

    rec = hm.get(sel_id) if sel_id else None

    if rec:
        # 预览
        with st.expander(f"📄 {rec.page_name} — {rec.created_at}", expanded=True):
            st.markdown(rec.result_content[:1000])

        if rec.structured_result:
            st.caption("📋 该记录含结构化决策仪表盘，Word/PDF 导出将自动嵌入 schema 卡片区")

        st.divider()

        # 格式选择
        format_choice = st.radio(
            "选择导出格式",
            ["word (.docx)", "pdf (.pdf)", "excel (.xlsx)"],
            horizontal=True,
            key="export_format",
        )

        format_key = format_choice.split()[0]  # "word", "pdf", "excel"

        # 检查依赖
        ok, install_cmd = _check_deps(format_key)
        if not ok:
            st.warning(f"⚠️ 需要安装 {format_key} 导出依赖: `{install_cmd}`")
            return

        if st.button("🚀 生成并下载", use_container_width=True, type="primary"):
            with st.spinner(f"正在生成 {format_choice} ..."):
                try:
                    from core.export import export_single_analysis
                    file_bytes, filename = export_single_analysis(rec, format_key)

                    mime_map = {
                        "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "pdf": "application/pdf",
                        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    }

                    st.success(f"✅ 文件已生成: {filename} ({len(file_bytes) / 1024:.1f} KB)")
                    st.download_button(
                        label=f"⬇️ 下载 {filename}",
                        data=file_bytes,
                        file_name=filename,
                        mime=mime_map[format_key],
                        use_container_width=True,
                    )
                except Exception as e:
                    st.error(f"导出失败: {e}")


def render_batch_export():
    """批量导出 Tab"""
    hm = get_history_manager()

    # 筛选
    col1, col2 = st.columns(2)
    with col1:
        fund_code = st.text_input("基金代码（可选）", placeholder="留空=全部", key="batch_fund_code")
    with col2:
        limit = st.number_input("最大记录数", 5, 200, 50)

    if st.button("🔍 查询记录", key="batch_query"):
        records = hm.list_all(fund_code=fund_code.strip() or None, limit=limit)
        st.session_state["batch_records"] = records

    records = st.session_state.get("batch_records", [])
    if records:
        st.caption(f"共 {len(records)} 条记录")

        # 预览表格
        preview_data = []
        for r in records:
            preview_data.append({
                "ID": r.id,
                "日期": r.created_at[:16],
                "页面": r.page_name[:15],
                "基金": r.fund_code or "-",
                "名称": (r.fund_name or "-")[:10],
                "模型": r.model[:15],
                "预览": r.preview[:60],
            })

        import pandas as pd
        st.dataframe(pd.DataFrame(preview_data), use_container_width=True, height=200)

        # 导出格式
        format_choice = st.radio(
            "导出格式",
            ["excel (.xlsx) — 推荐批量", "word (.docx)", "pdf (.pdf)"],
            horizontal=True,
            key="batch_format",
        )

        format_key = format_choice.split()[0]

        ok, install_cmd = _check_deps(format_key)
        if not ok:
            st.warning(f"⚠️ 需要安装依赖: `{install_cmd}`")
            return

        if st.button("📦 批量导出", use_container_width=True, type="primary"):
            with st.spinner(f"正在生成 {format_choice} ..."):
                try:
                    from core.export import export_multi_analysis
                    file_bytes, filename = export_multi_analysis(records, format_key, fund_code or "多基金")

                    mime_map = {
                        "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "pdf": "application/pdf",
                        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    }

                    st.success(f"✅ 文件已生成: {filename} ({len(file_bytes) / 1024:.1f} KB)")
                    st.download_button(
                        label=f"⬇️ 下载 {filename}",
                        data=file_bytes,
                        file_name=filename,
                        mime=mime_map[format_key],
                        use_container_width=True,
                    )
                except Exception as e:
                    st.error(f"导出失败: {e}")
    else:
        st.info("👆 输入筛选条件后点击「查询记录」")


def render_dependency_status():
    """依赖状态 Tab"""
    section_header("导出依赖状态")

    # (发行包名, 导入名, 安装命令) —— 两者常不一致，例如 python-docx 的导入名是 docx，
    # 之前用 pkg.replace("-","_") 推导导入名，导致已安装的 Word 库被误报为「未安装」。
    deps = {
        "Word (.docx)": ("python-docx", "docx", "pip install python-docx"),
        "PDF (.pdf)": ("weasyprint", "weasyprint", "pip install weasyprint"),
        "Excel (.xlsx)": ("openpyxl", "openpyxl", "pip install openpyxl"),
    }

    from importlib.metadata import PackageNotFoundError, version

    for name, (dist, import_name, install_cmd) in deps.items():
        ver = None
        try:
            ver = version(dist)
        except PackageNotFoundError:
            # 少数环境发行包元数据缺失，退回按导入名探测
            try:
                mod = __import__(import_name)
                ver = getattr(mod, "__version__", "已安装")
            except ImportError:
                ver = None
        if ver:
            st.success(f"✅ {name}: {ver}")
        else:
            st.error(f"❌ {name}: 未安装 — `{install_cmd}`")

    st.divider()
    st.caption("导出功能需要至少安装一种格式的支持库。Word + Excel 推荐用于日常使用。")


# ============================================================
# Main
# ============================================================

def main():
    render_page_header(
        title="导出中心",
        icon="📤",
        description="将 AI 分析结果导出为 Word (.docx)、PDF (.pdf)、Excel (.xlsx) 格式",
        help_text="使用说明：1. 选择分析记录 2. 选择导出格式 3. 点击下载。批量导出支持多条记录汇总为Excel。",
        accent_color="#0891B2",
    )

    sidebar_config = render_sidebar_config(show_ai_config=False)
    render_top_toolbar()

    tab1, tab2, tab3 = st.tabs([
        "📄 单条导出",
        "📦 批量导出",
        "🔧 依赖状态",
    ])

    with tab1:
        render_single_export()

    with tab2:
        render_batch_export()

    with tab3:
        render_dependency_status()


if __name__ == "__main__":
    main()
