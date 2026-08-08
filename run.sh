#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONDA_PATH="$HOME/miniconda3"
ENV_NAME="ppt2video"

export PATH="$CONDA_PATH/bin:$CONDA_PATH/envs/$ENV_NAME/bin:$PATH"

cd "$SCRIPT_DIR"
echo "=== 启动 PPT转音频 AI工具 ==="
echo "访问: http://localhost:8000"
echo ""

conda run -n "$ENV_NAME" python run.py
