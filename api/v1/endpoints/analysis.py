"""AI 分析接口"""

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from api.deps import get_analyzer, get_prompt_manager, get_history_manager

router = APIRouter()


class AnalyzeRequest(BaseModel):
    fund_code: str = Field("", description="基金代码")
    fund_name: str = Field("", description="基金名称")
    template_name: str = Field(..., description="提示词模板名称")
    context: Dict[str, Any] = Field(default_factory=dict, description="分析上下文数据")
    max_tokens: int = Field(4096, ge=512, le=32768)
    temperature: float = Field(0.3, ge=0.0, le=2.0)
    model: Optional[str] = Field(None, description="模型名称（可选，覆盖默认）")
    structured: bool = Field(False, description="是否同时返回结构化决策仪表盘 JSON")


class AnalyzeResponse(BaseModel):
    success: bool
    content: str
    model: str
    elapsed_seconds: float
    usage: Optional[Dict[str, int]] = None
    history_id: Optional[int] = None
    structured_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.post("/run", response_model=AnalyzeResponse)
async def run_analysis(req: AnalyzeRequest):
    """执行 AI 分析"""
    pm = get_prompt_manager()
    template = pm.get(req.template_name)
    if not template:
        raise HTTPException(status_code=400, detail=f"未找到模板: {req.template_name}")

    try:
        system_prompt, user_prompt = template.render(req.context)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"模板渲染失败: {e}")

    analyzer = get_analyzer()
    if req.model:
        # 验证模型名并在必要时切换 provider
        from core.model_router import MODEL_REGISTRY
        entry = MODEL_REGISTRY.get(req.model)
        if entry:
            analyzer.switch_model(provider=entry.provider, model=req.model)
        else:
            # 未知模型，仅设置模型名（由 analyzer 自行处理）
            analyzer.switch_model(model=req.model)

    # 结构化输出：在 system prompt 末尾追加 JSON 指令
    if req.structured:
        from core.decision_extractor import DECISION_JSON_INSTRUCTION
        system_prompt = system_prompt.rstrip() + "\n" + DECISION_JSON_INSTRUCTION

    try:
        result = analyzer.analyze(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
    except Exception as e:
        return AnalyzeResponse(success=False, content="", model=analyzer.model,
                               elapsed_seconds=0, error=str(e))

    # 解析结构化决策仪表盘
    structured_result = None
    content = result.get("content", "")
    if req.structured and result.get("success") and content:
        from core.decision_extractor import split_markdown_and_dashboard, merge_with_meta
        body, dashboard = split_markdown_and_dashboard(content)
        if dashboard:
            structured_result = merge_with_meta(
                dashboard,
                page_name=f"API:{req.template_name}",
                fund_code=req.fund_code,
                fund_name=req.fund_name,
                model=result.get("model", ""),
                markdown_fallback=body,
            )

    # 保存历史
    history_id = None
    if result.get("success"):
        try:
            hm = get_history_manager()
            history_id = hm.save(
                page_name=f"API:{req.template_name}",
                fund_code=req.fund_code,
                fund_name=req.fund_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                result_content=content,
                usage=result.get("usage", {}),
                elapsed_seconds=result.get("elapsed_seconds", 0),
                model=result.get("model", ""),
                structured_result=structured_result,
            )
        except TypeError:
            # 兼容旧签名（无 structured_result 参数）
            hm = get_history_manager()
            history_id = hm.save(
                page_name=f"API:{req.template_name}",
                fund_code=req.fund_code,
                fund_name=req.fund_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                result_content=content,
                usage=result.get("usage", {}),
                elapsed_seconds=result.get("elapsed_seconds", 0),
                model=result.get("model", ""),
            )
        except Exception:
            pass

    return AnalyzeResponse(
        success=result.get("success", False),
        content=content,
        model=result.get("model", ""),
        elapsed_seconds=result.get("elapsed_seconds", 0),
        usage=result.get("usage"),
        history_id=history_id,
        structured_result=structured_result,
        error=result.get("error"),
    )


@router.get("/templates")
async def list_templates():
    """列出所有可用的分析模板"""
    pm = get_prompt_manager()
    templates = pm.list_all()
    return {
        "total": len(templates),
        "items": [
            {"name": t._data.get("name", ""), "description": t._data.get("description", "")}
            for t in templates
        ],
    }


@router.post("/chat")
async def quick_chat(
    prompt: str = Query(..., description="对话内容"),
    max_tokens: int = Query(1024, ge=128, le=8192),
):
    """快速对话（简短问答）"""
    analyzer = get_analyzer()
    try:
        response = analyzer.quick_chat(prompt, max_tokens=max_tokens)
        return {"success": True, "response": response}
    except Exception as e:
        return {"success": False, "error": str(e)}
