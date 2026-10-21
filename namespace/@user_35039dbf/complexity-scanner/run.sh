#!/bin/bash

# Complexity Scanner 运行脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo "错误: 未找到 Node.js，请先安装 Node.js 18+"
    exit 1
fi

# 检查 Node.js 版本
NODE_VERSION=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "错误: Node.js 版本过低，需要 18+，当前版本: $(node -v)"
    exit 1
fi

# 首次运行时安装依赖
if [ ! -d "node_modules" ]; then
    echo "首次运行，正在安装依赖..."
    npm install --silent 2>&1
    if [ $? -ne 0 ]; then
        echo "错误: 依赖安装失败"
        exit 1
    fi
fi

# 编译 TypeScript（如果 dist 不存在或源码更新）
if [ ! -d "dist" ] || [ "src" -nt "dist" ]; then
    npx tsc --silent 2>&1
fi

# 运行 complexity-scanner
node dist/index.js "$@"
