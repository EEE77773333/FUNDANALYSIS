"""
FastAPI 应用工厂
================
创建和配置 FastAPI 应用实例，注册路由、中间件、异常处理。
"""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

import os

from api.v1.router import router as v1_router
from api.deps import verify_api_key


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""
    app = FastAPI(
        title="基金智能分析系统 API",
        description="基金数据查询、AI 分析、组合管理、预警通知的 RESTful API",
        version="2.2.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — 允许来源由环境变量 CORS_ALLOW_ORIGINS 控制（逗号分隔），默认不允许跨域
    origins_env = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    allow_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由（全部 /api/v1/* 需通过 API Key 鉴权）
    app.include_router(v1_router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])

    # 健康检查（根路径，免鉴权，供负载均衡探活）
    @app.get("/")
    async def root():
        return {"service": "基金智能分析系统 API", "version": "2.2.0", "status": "running"}

    return app
