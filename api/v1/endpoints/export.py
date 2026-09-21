"""导出接口 — Word / PDF / Excel"""

import io
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional
from api.deps import get_history_manager

router = APIRouter()

_media_types = {
    "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_extensions = {"word": ".docx", "pdf": ".pdf", "excel": ".xlsx"}


@router.get("/analysis/{record_id}")
async def export_analysis(
    record_id: int,
    format: str = Query("word", description="word / pdf / excel"),
):
    """导出单条分析结果"""
    if format not in _media_types:
        raise HTTPException(status_code=400, detail=f"不支持的格式: {format}，可选: word/pdf/excel")

    hm = get_history_manager()
    rec = hm.get(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="记录不存在")

    try:
        from core.export import export_single_analysis
        file_bytes, filename = export_single_analysis(rec, format)
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"导出模块依赖缺失: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=_media_types[format],
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/fund/{fund_code}")
async def export_fund_analyses(
    fund_code: str,
    format: str = Query("excel", description="word / pdf / excel"),
    limit: int = Query(10, ge=1, le=50),
):
    """导出一只基金的多条分析记录"""
    if format not in _media_types:
        raise HTTPException(status_code=400, detail=f"不支持的格式: {format}")

    hm = get_history_manager()
    records = hm.get_for_fund(fund_code, limit=limit)
    if not records:
        raise HTTPException(status_code=404, detail="该基金暂无分析记录")

    try:
        from core.export import export_multi_analysis
        file_bytes, filename = export_multi_analysis(records, format, fund_code)
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"导出模块依赖缺失: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=_media_types[format],
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
