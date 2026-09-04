#!/usr/bin/env bash
# 分阶压测：50 / 200 / 500 / 1000 并发用户，输出 CSV 与汇总报告。
#
# 前置：docker compose up -d 已运行；backend venv 已安装 locust。
# 用法：bash scripts/run_load_test.sh [BASE_URL] [RUN_TIME]
#   默认 BASE_URL=http://localhost:8001  RUN_TIME=60（秒）
set -u

BASE="${1:-http://localhost:8001}"
RUN_TIME="${2:-60}"
SPAWN_RATE=50

# 用绝对路径，避免 cd 相对遍历出错
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/backend/.venv/Scripts/python.exe"
LOCUST_DIR="$ROOT/loadtest"
REPORT_DIR="$ROOT/reports"
STAGES="50 200 500 1000"

mkdir -p "$REPORT_DIR"

echo "== 预生成 Token 池（避免登录风暴拉高 P95） =="
( cd "$LOCUST_DIR" && "$VENV" gen_tokens.py 60 15 "$BASE" ) || echo "  [WARN] Token 池生成失败"

echo "== 预生成挂起案件（场景 C 审批用） =="
( cd "$LOCUST_DIR" && "$VENV" seed_cases.py 300 "$BASE" ) || echo "  [WARN] 预生成失败，审批场景将跳过"

for USERS in $STAGES; do
  echo
  echo "=============================================================="
  echo "== 阶段：${USERS} 并发用户，持续 ${RUN_TIME}s =="
  echo "=============================================================="
  CSV_PREFIX="$REPORT_DIR/loadtest_${USERS}users"
  ( cd "$LOCUST_DIR" && "$VENV" -m locust \
      -f locustfile.py \
      --host "$BASE" \
      --users "$USERS" \
      --spawn-rate "$SPAWN_RATE" \
      --run-time "${RUN_TIME}s" \
      --headless \
      --csv "$CSV_PREFIX" 2>&1 | tail -35 )
  echo "== ${USERS} 用户阶段结束，CSV 已写入 ${CSV_PREFIX}_stats.csv =="
done

echo
echo "== 生成汇总报告 =="
"$VENV" "$ROOT/scripts/aggregate_load_test.py" "$REPORT_DIR"
