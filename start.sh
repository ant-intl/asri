#!/bin/bash
######################################################################
# start.sh
# 本地开发环境快速启动脚本
#
# 用法:
#   ./start.sh              # 构建前端并启动后端
#   ./start.sh dev          # 开发模式（前端热更新 + 后端）
#   ./start.sh backend      # 仅启动后端
#   ./start.sh --quick      # 跳过构建，直接启动后端
#   ./start.sh --setup      # 先运行 setup.sh 再启动
######################################################################

set -e

export SERVER_ENV=local

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
PORT=${2:-8000}

# 解析参数
case "${1:-}" in
    --quick)
        # 跳过构建直接启动
        start_backend
        exit 0
        ;;
    --setup)
        # 先运行 setup.sh
        if [ -f "$SCRIPT_DIR/setup.sh" ]; then
            bash "$SCRIPT_DIR/setup.sh"
        else
            echo "[错误] setup.sh 不存在"
            exit 1
        fi
        start_backend
        exit 0
        ;;
esac

# 检测操作系统
detect_os() {
    case "$(uname -s)" in
        Darwin)
            echo "macos"
            ;;
        Linux)
            echo "linux"
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

OS_TYPE=$(detect_os)

# 设置 Python 命令（优先使用虚拟环境）
if [ -d "$SCRIPT_DIR/venv" ]; then
    PYTHON_CMD="$SCRIPT_DIR/venv/bin/python3"
    DAPHNE_CMD="$SCRIPT_DIR/venv/bin/daphne"
elif [ -d "$SCRIPT_DIR/.venv" ]; then
    PYTHON_CMD="$SCRIPT_DIR/.venv/bin/python3"
    DAPHNE_CMD="$SCRIPT_DIR/.venv/bin/daphne"
else
    PYTHON_CMD="python3"
    DAPHNE_CMD="daphne"
fi

# 检查并释放端口（跨平台支持）
kill_port_if_in_use() {
    local port=$1
    local pids=""

    echo "[端口] 检测操作系统：$OS_TYPE"

    if [ "$OS_TYPE" = "macos" ]; then
        # macOS: 使用 lsof 查找占用端口的进程
        pids=$(lsof -t -i:$port 2>/dev/null || true)
    elif [ "$OS_TYPE" = "linux" ]; then
        # Linux: 优先使用 ss，fallback 到 netstat
        if command -v ss >/dev/null 2>&1; then
            pids=$(ss -tlnp 2>/dev/null | grep ":$port " | awk '{print $6}' | grep -oE 'pid=[0-9]+' | cut -d'=' -f2 | sort -u || true)
        elif command -v netstat >/dev/null 2>&1; then
            pids=$(netstat -tlnp 2>/dev/null | grep ":$port " | awk '{print $7}' | cut -d'/' -f1 | grep -o '[0-9]*' || true)
        elif command -v lsof >/dev/null 2>&1; then
            pids=$(lsof -t -i:$port 2>/dev/null || true)
        fi
    fi

    if [ -n "$pids" ]; then
        echo "[端口] 端口 $port 被占用，正在终止进程：$pids"

        # 根据操作系统选择 kill 命令
        if [ "$OS_TYPE" = "macos" ]; then
            # macOS: 直接使用 kill
            echo "$pids" | xargs kill -9 2>/dev/null || true
        elif [ "$OS_TYPE" = "linux" ]; then
            # Linux: 使用 fuser 或 kill
            if command -v fuser >/dev/null 2>&1; then
                fuser -k $port/tcp 2>/dev/null || true
            else
                echo "$pids" | xargs kill -9 2>/dev/null || true
            fi
        fi

        sleep 1
        echo "[端口] 端口 $port 已释放"
    else
        echo "[端口] 端口 $port 未被占用"
    fi
}

# 构建前端
build_frontend() {
    echo "[前端] 构建生产版本..."
    cd "$FRONTEND_DIR"
    npm install --silent
    npm run build

    # 同步 index.html 到 backend/templates/frontend/
    echo "[前端] 同步 index.html 到 backend/templates/frontend/..."
    mkdir -p "$SCRIPT_DIR/backend/templates/frontend/"
    cp "$SCRIPT_DIR/static/frontend/index.html" "$SCRIPT_DIR/backend/templates/frontend/index.html"

    echo "[前端] 构建完成 → static/frontend/"
}

# 启动后端服务
start_backend() {
    kill_port_if_in_use "$PORT"
    echo "[后端] 启动 Django 服务 (端口：$PORT)..."
    cd "$SCRIPT_DIR/backend"
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    $PYTHON_CMD manage.py migrate --noinput
    $PYTHON_CMD manage.py seed_data
    $DAPHNE_CMD -b 0.0.0.0 -p "$PORT" config.asgi:application
}

# 开发模式：前端热更新 + 后端
start_dev_mode() {
    echo "[启动] 开发模式..."

    kill_port_if_in_use 8000

    # 后台启动后端
    cd "$SCRIPT_DIR/backend"
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    $PYTHON_CMD manage.py migrate --noinput
    $PYTHON_CMD manage.py seed_data
    $DAPHNE_CMD -b 0.0.0.0 -p 8000 config.asgi:application &
    BACKEND_PID=$!

    echo "[后端] 已在后台启动 (PID: $BACKEND_PID, 端口：8000)"

    # 启动前端（热更新）
    cd "$FRONTEND_DIR"
    npm run dev

    # 清理
    trap "kill $BACKEND_PID 2>/dev/null" EXIT
}

# 根据参数选择启动模式
case "${1:-}" in
    dev)
        start_dev_mode
        ;;
    backend)
        start_backend
        ;;
    "")
        # 默认：构建前端并启动后端
        build_frontend
        start_backend
        ;;
    *)
        echo "用法：$0 [dev|backend|--quick|--setup]"
        echo ""
        echo "示例:"
        echo "  ./start.sh               # 构建前端并启动后端"
        echo "  ./start.sh dev           # 开发模式（前端热更新 + 后端）"
        echo "  ./start.sh backend       # 仅启动后端"
        echo "  ./start.sh --quick       # 跳过构建，直接启动"
        echo "  ./start.sh --setup       # 先 setup.sh 再启动"
        exit 1
        ;;
esac
