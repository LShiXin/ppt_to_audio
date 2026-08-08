#!/bin/bash
set -e

# ==========================================
# 部署到 /ppt_to_audio (需要 sudo)
# ==========================================

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="/ppt_to_audio"

echo "=== PPT转音频 AI工具 - 部署脚本 ==="
echo "源目录: $SOURCE_DIR"
echo "目标目录: $TARGET_DIR"
echo ""

if [ ! -d "$SOURCE_DIR/app" ]; then
    echo "错误: 请在项目根目录运行此脚本"
    exit 1
fi

echo "此脚本将把项目部署到 $TARGET_DIR"
echo "需要 sudo 权限。"
echo ""

# 移动整个项目
sudo cp -r "$SOURCE_DIR"/* "$TARGET_DIR"/
sudo chown -R liuzhipeng:liuzhipeng "$TARGET_DIR"

echo ""
echo "=== 部署完成！==="
echo ""
echo "下一步:"
echo "  cd $TARGET_DIR"
echo "  bash scripts/setup_conda.sh    # 安装环境 (如果尚未安装)"
echo "  bash run.sh                    # 启动服务"
