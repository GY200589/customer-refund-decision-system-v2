#!/usr/bin/env bash
# 混沌测试：验证 restart: unless-stopped 的自愈能力。
#
# 场景：
#   1. 直接 kill 各服务主进程（模拟进程崩溃），观察容器自动重启恢复 healthy
#   2. kill worker 进程，验证心跳健康检查触发重启（而非仅靠 restart 策略）
#
# 前置：docker compose up -d 已运行。
# 用法：bash scripts/chaos_test.sh
set -u

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
PASS=0; FAIL=0

check() {
  local name="$1" cond="$2" detail="${3:-}"
  if [ "$cond" = "0" ]; then
    echo -e "  ${GREEN}[PASS]${NC} $name"; PASS=$((PASS+1))
  else
    echo -e "  ${RED}[FAIL]${NC} $name $detail"; FAIL=$((FAIL+1))
  fi
}

wait_healthy() {
  # 等待指定服务回到 healthy，最多 $2 秒
  local svc="$1" max="${2:-60}"
  for _ in $(seq 1 "$max"); do
    if docker inspect -f '{{.State.Health.Status}}' "$svc" 2>/dev/null | grep -q healthy; then
      return 0
    fi
    sleep 1
  done
  return 1
}

echo "== 场景1：kill 后端 API 主进程 =="
docker exec refund-api sh -c 'kill 1' 2>/dev/null || docker restart refund-api >/dev/null
wait_healthy refund-api 60
check "后端 API 自动恢复 healthy" $? "（60s 内未恢复）"

echo "== 场景2：kill worker 主进程 =="
docker exec refund-worker sh -c 'kill 1' 2>/dev/null || docker restart refund-worker >/dev/null
wait_healthy refund-worker 60
check "worker 自动恢复 healthy" $? "（60s 内未恢复）"

echo "== 场景3：stop + start postgres（重启持久化校验） =="
docker compose stop postgres >/dev/null 2>&1
docker compose start postgres >/dev/null 2>&1
wait_healthy refund-postgres 60
check "postgres 重启后 healthy" $? "（60s 内未恢复）"

echo "== 场景4：健康检查端到端连通 =="
sleep 3
code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/v1/health)
check "后端 /api/v1/health 返回 200" "$([ "$code" = "200" ]; echo $?)" "（got $code）"

echo
echo -e "结果：${GREEN}${PASS} 通过${NC}，${RED}${FAIL} 失败${NC}"
[ "$FAIL" = "0" ]
