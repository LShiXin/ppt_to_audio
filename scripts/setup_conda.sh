#!/bin/bash
set -e

# ==========================================
# PPT转音频 AI工具 - 环境安装脚本
# ==========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONDA_PATH="$HOME/miniconda3"
ENV_NAME="ppt2video"

echo "=== PPT转音频 AI工具 - 环境安装 ==="
echo ""

# 1. 检查/安装 Miniconda
if [ ! -f "$CONDA_PATH/bin/conda" ]; then
    echo "[1/4] 安装 Miniconda..."
    wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
    bash /tmp/miniconda.sh -b -p "$CONDA_PATH"
    rm /tmp/miniconda.sh
else
    echo "[1/4] Miniconda 已安装"
fi

export PATH="$CONDA_PATH/bin:$PATH"

# 2. 接受 ToS 并创建环境
echo "[2/4] 创建 conda 环境 ($ENV_NAME)..."
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main 2>/dev/null || true
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r 2>/dev/null || true

if conda env list | grep -q "$ENV_NAME"; then
    echo "环境 $ENV_NAME 已存在，跳过创建"
else
    conda create -n "$ENV_NAME" python=3.12 -y
fi

# 3. 安装依赖
echo "[3/4] 安装 Python 依赖..."
conda run -n "$ENV_NAME" pip install -r "$SCRIPT_DIR/requirements.txt"
conda run -n "$ENV_NAME" pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126 2>/dev/null || \
    conda run -n "$ENV_NAME" pip install --pre torch torchaudio --index-url https://download.pytorch.org/whl/cu128
conda run -n "$ENV_NAME" pip install qwen-tts

# 安装系统 sox (需要sudo)
echo "   如果 sox 安装失败，请手动运行: sudo apt-get install -y sox"
conda install -n "$ENV_NAME" -c conda-forge sox -y 2>/dev/null || true

# 3.5. 安装 CUDA 工具链 (nvcc，flashinfer JIT 编译必需)
echo "[3.5/4] 安装 CUDA Toolkit (nvcc)..."
conda install -n "$ENV_NAME" -c nvidia cuda-toolkit=13.2.2 -y

# 3.6. 安装 vLLM-Omni（必须放在最后；vllm==0.26.0 与 vllm-omni==0.26.0 配对：
#      vllm 0.25 移除了 OmniRequest.num_in_flight_tokens 会推理崩溃，
#      vllm 0.24 缺少 vllm.entrypoints.scale_out 无法导入）
echo "[3.6/4] 安装 vLLM-Omni..."
conda run -n "$ENV_NAME" pip install vllm==0.26.0 vllm-omni==0.26.0 flashinfer-python==0.6.14 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout=1000

# 4. 下载模型
echo "[4/4] 下载 Qwen3-TTS 模型..."
if [ ! -d "$SCRIPT_DIR/models/Qwen3-TTS-12Hz-1.7B-CustomVoice" ]; then
    conda run -n "$ENV_NAME" modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
        --local_dir "$SCRIPT_DIR/models/Qwen3-TTS-12Hz-1.7B-CustomVoice"
else
    echo "模型已存在，跳过下载"
fi

echo ""
echo "=== 安装完成！==="
echo "启动命令: bash $SCRIPT_DIR/start_all.sh (应用 8003 + vLLM 8000)"
echo "不要使用 run.sh/run.py（端口 8000 会与 vLLM 冲突且不启用 vllm 后端）"
