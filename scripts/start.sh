#!/usr/bin/env bash
# 一键启动全套服务（Linux/macOS / Git Bash）
set -e
BUILD_FLAG=""
[ "$1" = "--build" ] && BUILD_FLAG="--build"

echo "==> 启动客诉舆情退赔决策系统 ..."
docker compose up -d $BUILD_FLAG
docker compose ps
echo "前端: http://localhost:5173  后端: http://localhost:8001/api/v1/health"
