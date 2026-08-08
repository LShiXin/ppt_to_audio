#!/usr/bin/env python3
"""Download Qwen3-TTS model from ModelScope."""
import sys
from pathlib import Path

MODEL_NAME = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
TARGET_DIR = Path(__file__).resolve().parent.parent / "models" / "Qwen3-TTS-12Hz-1.7B-CustomVoice"

if TARGET_DIR.exists() and list(TARGET_DIR.glob("*.safetensors")):
    print(f"模型已存在: {TARGET_DIR}")
    sys.exit(0)

print(f"正在下载模型 {MODEL_NAME} ...")
print(f"目标目录: {TARGET_DIR}")

from modelscope import snapshot_download
snapshot_download(MODEL_NAME, local_dir=str(TARGET_DIR))

print("模型下载完成！")
