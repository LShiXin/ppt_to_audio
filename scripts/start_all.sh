#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONDA_PATH="$HOME/miniconda3"
ENV_NAME="ppt2video"
CONDA_BIN="$CONDA_PATH/envs/$ENV_NAME/bin"

APP_PORT="${APP_PORT:-8003}"
VLLM_PORT="${VLLM_PORT:-8000}"
VLLM_OMNI_MODEL="${VLLM_OMNI_MODEL:-base}"

APP_LOG="$PROJECT_DIR/logs/app.log"
APP_PID_FILE="/tmp/ppt2audio_app.pid"

mkdir -p "$PROJECT_DIR/logs"

cleanup() {
    echo ""
    echo "=== 正在停止服务 ==="
    if [ -f "$APP_PID_FILE" ]; then
        kill "$(cat "$APP_PID_FILE")" 2>/dev/null && echo "项目服务已停止" || true
        rm -f "$APP_PID_FILE"
    fi
    pkill -9 -f "StageEngineCoreProc" 2>/dev/null || true
    pkill -9 -f "resource_tracker" 2>/dev/null || true
    echo "已清理 GPU 显存残留"
    exit 0
}

trap cleanup SIGINT SIGTERM

echo "=== PPT 转音频 + vLLM-Omni 启动脚本 ==="
echo "  Model: $VLLM_OMNI_MODEL"
echo ""

if [ ! -d "$CONDA_PATH/envs/$ENV_NAME/lib64/stubs" ]; then
    mkdir -p "$CONDA_PATH/envs/$ENV_NAME/lib64/stubs"
    ln -sf ../../targets/x86_64-linux/lib/stubs/libcuda.so \
        "$CONDA_PATH/envs/$ENV_NAME/lib64/stubs/libcuda.so" 2>/dev/null || true
    ln -sf ../../targets/x86_64-linux/lib/stubs/libnvidia-ml.so \
        "$CONDA_PATH/envs/$ENV_NAME/lib64/stubs/libnvidia-ml.so" 2>/dev/null || true
fi

echo "[1/1] 启动 PPT 转音频 + vLLM-Omni..."
echo "  Backend:  vllm_omni"
echo "  vLLM Port: $VLLM_PORT"
echo "  App Port:  $APP_PORT"
echo "  Log:       $APP_LOG"
echo ""

cd "$PROJECT_DIR" && \
TTS_BACKEND=vllm_omni \
VLLM_OMNI_BASE_URL="http://localhost:$VLLM_PORT" \
VLLM_PORT="$VLLM_PORT" \
VLLM_OMNI_MODEL="$VLLM_OMNI_MODEL" \
    $CONDA_BIN/python -m uvicorn app.main:app \
        --host 0.0.0.0 \
        --port "$APP_PORT" \
        > "$APP_LOG" 2>&1 &

APP_PID=$!
echo "$APP_PID" > "$APP_PID_FILE"

echo "  App PID: $APP_PID"
echo ""
echo "=== 启动中 ==="
echo "  vLLM-Omni 正在由应用启动..."
echo "  应用: http://localhost:$APP_PORT"
echo ""
echo "按 Ctrl+C 停止所有服务"

wait $APP_PID