"""
FastAPI 后端服务入口
====================
独立的 API 服务，与 Streamlit 前端共享 core 模块。

启动方式:
    python server.py
    uvicorn server:app --host 0.0.0.0 --port 8502 --reload
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from api import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8502, reload=True)
