#!/bin/bash
######################################################################
# setup.sh — ASRI 一键安装脚本
#
# 用法:
#   ./setup.sh              # 完整安装（venv + pip + npm + migrate + seed）
#   ./setup.sh --quick      # 仅初始化数据库（跳过 venv/pip/npm）
#   ./setup.sh --help       # 帮助信息
#
# 功能:
#   1. 创建 Python 虚拟环境
#   2. 安装 Python 依赖
#   3. 安装前端依赖并构建
#   4. 运行数据库迁移
#   5. 创建默认种子数据
######################################################################

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# ── 颜色定义 ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── 帮助信息 ─────────────────────────────────────────────────────
show_help() {
    cat <<EOF
ASRI 一键安装脚本

用法:
  ./setup.sh              完整安装（默认）
  ./setup.sh --quick      仅初始化数据库（跳过依赖安装）
  ./setup.sh --help       显示帮助信息

说明:
  完整安装会依次执行：
    1. 创建 Python 虚拟环境
    2. 安装 Python 依赖
    3. 安装前端依赖并构建
    4. 运行数据库迁移
    5. 创建默认种子数据
EOF
    exit 0
}

# ── 参数解析 ─────────────────────────────────────────────────────
QUICK_MODE=false
for arg in "$@"; do
    case "$arg" in
        --help|-h) show_help ;;
        --quick)   QUICK_MODE=true ;;
        *)         warn "未知参数: $arg" ;;
    esac
done

# ── 检查 Python ──────────────────────────────────────────────────
check_python() {
    if command -v python3 &>/dev/null; then
        PYTHON=$(command -v python3)
    elif command -v python &>/dev/null; then
        PYTHON=$(command -v python)
    else
        error "未找到 Python，请安装 Python 3.10+"
        exit 1
    fi

    PY_VERSION=$($PYTHON --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
    info "检测到 Python: $($PYTHON --version 2>&1)"

    # 检查 Python 版本 >= 3.10
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -lt 3 ] || [ "$PY_MAJOR" -eq 3 -a "$PY_MINOR" -lt 10 ]; then
        error "需要 Python 3.10+，当前版本: $PY_VERSION"
        exit 1
    fi
}

# ── 检查 Node.js ─────────────────────────────────────────────────
check_node() {
    if ! command -v node &>/dev/null; then
        error "未找到 Node.js，请安装 Node.js 18+"
        exit 1
    fi
    info "检测到 Node.js: $(node --version 2>&1)"
}

# ── 创建 / 激活虚拟环境 ──────────────────────────────────────────
setup_venv() {
    if [ -d "$SCRIPT_DIR/.venv" ]; then
        info "虚拟环境已存在: .venv"
    else
        info "创建虚拟环境..."
        $PYTHON -m venv "$SCRIPT_DIR/.venv"
    fi

    # 激活虚拟环境
    source "$SCRIPT_DIR/.venv/bin/activate"
    info "虚拟环境已激活"
}

# ── 安装 Python 依赖 ─────────────────────────────────────────────
install_python_deps() {
    info "安装 Python 依赖..."
    cd "$BACKEND_DIR"
    pip install -r requirements.txt
    info "Python 依赖安装完成"
}

# ── 安装前端依赖并构建 ───────────────────────────────────────────
build_frontend() {
    info "安装前端依赖..."
    cd "$FRONTEND_DIR"
    npm install --silent

    info "构建前端..."
    npm run build

    # 同步 index.html 到 backend/templates/frontend/
    info "同步 index.html..."
    mkdir -p "$BACKEND_DIR/templates/frontend/"
    cp "$SCRIPT_DIR/static/frontend/index.html" "$BACKEND_DIR/templates/frontend/index.html"

    info "前端构建完成"
}

# ── 运行数据库迁移 ───────────────────────────────────────────────
run_migrations() {
    info "运行数据库迁移..."
    cd "$BACKEND_DIR"
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    python manage.py migrate --noinput
    info "数据库迁移完成"
}

# ── 创建种子数据 ─────────────────────────────────────────────────
seed_data() {
    info "创建默认种子数据..."
    cd "$BACKEND_DIR"
    python manage.py seed_data
    info "种子数据创建完成"
}

# ── 打印完成信息 ─────────────────────────────────────────────────
print_summary() {
    echo ""
    info "========================================"
    info "  ASRI 安装完成！"
    info "========================================"
    echo ""
    info "启动服务:  ./start.sh"
    info "开发模式:  ./start.sh dev"
    echo ""
    info "默认租户 Token: asri-dev-token"
    info "默认租户 ID:    default"
    echo ""
    info "配置 LLM Provider:"
    info "  访问 Admin 页面 → Models → 添加 LLM Provider"
    info "  或访问 http://127.0.0.1:8000/admin/ 配置"
    echo ""
}

# ══════════════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════════════

echo ""
info "ASRI 安装开始"
echo ""

check_python
check_node

if [ "$QUICK_MODE" = false ]; then
    setup_venv
    install_python_deps
    build_frontend
fi

run_migrations
seed_data
print_summary
