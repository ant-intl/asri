#!/usr/bin/env bash
set -uo pipefail

# ============================================================
# ASRI Voice Agent Startup Script
#
# Usage:
#   ./start.sh                 # Start main pipeline + Python client
#   ./start.sh --with-epos     # Also start EPOS tool services (internal)
#   ./start.sh --frontend      # Use frontend Web UI instead of Python client
#   ./start.sh --no-client     # Only start server, no client
#   ./start.sh --config <path> # Specify config file (default: configs/asri-voice.yaml)
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---- Color output ----
info() { printf "\033[0;34m[INFO]\033[0m %s\n" "$*"; }
ok()   { printf "\033[0;32m[ OK ]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
err()  { printf "\033[0;31m[ERR ]\033[0m %s\n" "$*"; }

# ---- Cleanup trap ----
PIDS=()
cleanup() {
    echo ""
    info "Shutting down all services..."
    for pid in "${PIDS[@]:-}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    ok "All services stopped"
}
trap cleanup EXIT INT TERM

# ---- Argument parsing ----
SKIP_EPOS=true
USE_FRONTEND=false
NO_CLIENT=false
CONFIG_FILE="configs/asri-voice.yaml"

while [ $# -gt 0 ]; do
    case "$1" in
        --with-epos)  SKIP_EPOS=false; shift ;;
        --frontend)   USE_FRONTEND=true; shift ;;
        --no-client)  NO_CLIENT=true; shift ;;
        --config)     CONFIG_FILE="$2"; shift 2 ;;
        --help|-h)
            echo "ASRI Voice Agent Startup"
            echo ""
            echo "Usage: ./start.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --with-epos     Also start EPOS tool services (internal use)"
            echo "  --frontend      Use frontend Web UI (default: Python client)"
            echo "  --no-client     Skip client startup"
            echo "  --config <path> Specify config file (default: configs/asri-voice.yaml)"
            echo "  -h, --help      Show this help"
            echo ""
            echo "Available configs:"
            echo "  configs/asri-voice.yaml              - Default config (OpenAI-compatible backends)"
            echo "  configs/asri-voice.example.yaml      - Example config with all OpenAI services"
            exit 0
            ;;
        *)
            warn "Unknown argument: $1 (ignored)"
            shift
            ;;
    esac
done

# ============================================================
# Step 0: Check prerequisites
# ============================================================
info "Checking prerequisites..."

if ! command -v uv &>/dev/null; then
    err "uv not installed"
    echo "  Please install: brew install uv"
    exit 1
fi

if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${LLM_API_KEY:-}" ]; then
    warn "No LLM API key found in OPENAI_API_KEY or LLM_API_KEY"
    echo "  Set via: export OPENAI_API_KEY=\"<your-key>\""
    echo "  Or configure via Django Admin / YAML config file."
fi

ok "Prerequisites OK"

# ============================================================
# Step 1: Install dependencies
# ============================================================
info "Installing dependencies (uv sync)..."
if uv sync --quiet 2>/dev/null; then
    ok "Dependencies ready"
else
    err "uv sync failed, please run 'uv sync' manually"
    exit 1
fi

# ============================================================
# Step 2: Start EPOS tool services
# ============================================================
if [ "$SKIP_EPOS" = false ]; then
    info "Starting EPOS tool services..."

    # --- Knowledge search service (port 8001) ---
    if lsof -i :8001 -t &>/dev/null; then
        warn "Port 8001 already in use, skipping knowledge service"
    else
        info "Starting knowledge search service (port 8001)..."
        PORT=8001 uv run --with fastapi --with uvicorn --with sentence-transformers --with numpy \
            python services/epos_knowledge_service/app.py &>/tmp/epos_kb.log &
        _pid=$!
        PIDS+=($_pid)
        ok "Knowledge service PID: $_pid"
    fi

    # --- Order query service (port 8002) ---
    if lsof -i :8002 -t &>/dev/null; then
        warn "Port 8002 already in use, skipping query service"
    else
        info "Starting order query service (port 8002)..."
        PORT=8002 \
        EXCEL_PATH="$SCRIPT_DIR/services/epos_query_service/New Master List.xlsx" \
        uv run --with fastapi --with uvicorn --with pandas --with openpyxl \
            python services/epos_query_service/app.py &>/tmp/epos_q.log &
        _pid=$!
        PIDS+=($_pid)
        ok "Query service PID: $_pid"
    fi

    # Wait for EPOS (first run downloads embedding models, may be slow)
    info "Waiting for EPOS services..."
    for i in $(seq 1 20); do
        sleep 1
        kb_ready=false; q_ready=false
        curl -sf http://localhost:8001/health &>/dev/null && kb_ready=true
        curl -sf http://localhost:8002/health &>/dev/null && q_ready=true
        if $kb_ready && $q_ready; then
            ok "EPOS services ready"
            break
        fi
        if [ "$i" -eq 20 ]; then
            warn "EPOS services still starting (first run downloads models), continuing..."
            warn "Logs: /tmp/epos_kb.log  /tmp/epos_q.log"
        fi
    done
fi

# ============================================================
# Step 3: Verify config file
# ============================================================
if [ ! -f "$CONFIG_FILE" ]; then
    err "Config file not found: $CONFIG_FILE"
    exit 1
fi
info "Using config: $CONFIG_FILE"

# ============================================================
# Step 4: Start main pipeline
# ============================================================
if lsof -i :8765 -t &>/dev/null; then
    warn "Port 8765 already in use, skipping main pipeline"
else
    info "Starting main pipeline..."
    uv run python asri_voice/main.py --config "$CONFIG_FILE" &
    PIPELINE_PID=$!
    PIDS+=($PIPELINE_PID)
    ok "Pipeline PID: $PIPELINE_PID"

    info "Waiting for pipeline..."
    PIPELINE_READY=false
    for i in $(seq 1 60); do
        sleep 1
        if ! kill -0 "$PIPELINE_PID" 2>/dev/null; then
            err "Pipeline process exited, check logs above"
            exit 1
        fi
        if lsof -i :8765 -t &>/dev/null; then
            ok "Pipeline ready (ws://localhost:8765)"
            PIPELINE_READY=true
            break
        fi
    done
    if [ "$PIPELINE_READY" = false ]; then
        err "Pipeline not ready within 60s, aborting"
        err "Possible causes: TTS service unavailable / dependency failure / port conflict"
        exit 1
    fi
fi

# ============================================================
# Summary
# ============================================================
echo ""
ok "========== All services started =========="
echo "  RealtimeServer:  ws://localhost:8765"
[ "$SKIP_EPOS" = false ] && {
    echo "  EPOS Knowledge:   http://localhost:8001"
    echo "  EPOS Query:       http://localhost:8002"
}
if [ "$USE_FRONTEND" = true ] && [ "$NO_CLIENT" = false ]; then
    echo "  Frontend:         http://localhost:5173"
fi
echo ""
echo "  Press Ctrl+C to stop all services"
echo ""

# ============================================================
# Step 5: Start client (foreground, requires stdin)
# ============================================================
if [ "$NO_CLIENT" = false ]; then
    if [ "$USE_FRONTEND" = true ]; then
        info "Starting frontend Web UI..."
        cd frontend
        if [ ! -d node_modules ]; then
            info "First run, installing frontend dependencies..."
            npm install --silent
        fi
        cd "$SCRIPT_DIR"
        ok "Frontend starting (http://localhost:5173), press Ctrl+C to stop"
        cd frontend && exec npm run dev
    else
        info "Starting Python client..."
        ok "Python client starting, press Enter to stop"
        uv run python listen_and_play_realtime.py
    fi
else
    echo "  Press Ctrl+C to stop all services"
    # No client: wait for background processes
    wait
fi
