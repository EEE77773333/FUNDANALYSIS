#!/usr/bin/env bash
# ============================================================
# 基金智能分析系统 — 一键启动脚本
#
# 用法：
#     ./quickstart.sh              # 自动选择 Docker（装了就用 Docker）
#     ./quickstart.sh docker       # 强制用 Docker
#     ./quickstart.sh local        # 强制用本地 Python（SQLite 单机模式）
#
# 脚本做的事：
#     1. 检查运行环境（Docker 还是 Python）
#     2. 首次运行时生成 .env（含随机密钥）
#     3. 启动服务并等待就绪
#     4. 打印访问地址
# ============================================================

set -euo pipefail

cd "$(dirname "$0")"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { printf "${BLUE}▸${NC} %s\n" "$1"; }
ok()    { printf "${GREEN}✅${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}⚠️${NC}  %s\n" "$1"; }
fail()  { printf "${RED}❌${NC} %s\n" "$1"; }

MODE="${1:-auto}"
PORT="${APP_PORT:-8501}"

echo ""
echo "  🏦  基金智能分析系统 — 一键部署"
echo "  ────────────────────────────────────────"
echo ""

# ---------- 模式选择 ----------
if [ "$MODE" = "auto" ]; then
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        MODE="docker"
    elif command -v python3 >/dev/null 2>&1; then
        MODE="local"
    else
        fail "未检测到 Docker 或 Python3，请先安装其中之一。"
        exit 1
    fi
fi

# ---------- 生成 .env ----------
if [ ! -f .env ]; then
    info "首次运行，正在生成 .env（自动填入随机密钥）…"
    if command -v python3 >/dev/null 2>&1; then
        python3 scripts/setup_env.py
    else
        warn "未找到 python3，跳过 .env 生成（将使用内置默认值启动）。"
    fi
else
    info "检测到已有 .env，沿用现有配置。"
fi

# ---------- 启动 ----------
case "$MODE" in
  docker)
    if ! command -v docker >/dev/null 2>&1; then
        fail "未检测到 Docker，请改用：./quickstart.sh local"
        exit 1
    fi
    info "使用 Docker 启动（应用 + PostgreSQL）…"
    docker compose up -d --build

    info "等待服务就绪（首次启动需构建镜像并安装依赖，约 2~5 分钟）…"
    for i in $(seq 1 60); do
        if curl -fsS "http://localhost:${PORT}/_stcore/health" >/dev/null 2>&1; then
            ok "服务已就绪"
            break
        fi
        if [ "$i" -eq 60 ]; then
            warn "等待超时。可查看日志排查：docker compose logs -f app"
        fi
        sleep 5
    done

    echo ""
    ok "启动完成"
    echo "    访问地址 : http://localhost:${PORT}"
    echo "    查看日志 : docker compose logs -f app"
    echo "    停止服务 : docker compose down"
    ;;

  local)
    if ! command -v python3 >/dev/null 2>&1; then
        fail "未检测到 python3，请先安装 Python 3.10+。"
        exit 1
    fi
    info "使用本地 Python 启动（SQLite 单机模式，零配置）…"

    if [ ! -d ".venv" ]; then
        info "创建虚拟环境 .venv …"
        python3 -m venv .venv
    fi
    # shellcheck disable=SC1091
    source .venv/bin/activate

    info "安装依赖（首次较慢，请耐心等待）…"
    pip install -q --upgrade pip
    pip install -q -r requirements.txt

    echo ""
    ok "依赖就绪，启动中…"
    echo "    访问地址 : http://localhost:${PORT}"
    echo "    停止服务 : 按 Ctrl+C"
    echo ""
    exec streamlit run app.py --server.port "${PORT}"
    ;;

  *)
    fail "未知模式：$MODE（可选 docker / local / auto）"
    exit 1
    ;;
esac
