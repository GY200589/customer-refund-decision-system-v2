# Loop 报告：构建 · 测试 · Docker 验证（真实运行记录）

> 阶段：Task2 测试 → 前端构建 → Docker 全栈 → 端到端 → 压测
> 时间：2026-08-18

## 一、实际执行内容（诚实记录）

### 1. 后端依赖安装与单元测试
- 在 `backend/.venv`（Python 3.11.15）安装 requirements。
- **发现并修复 7 个真实问题**（详见 `docs/面试QA库.md`）：
  1. `langgraph-checkpoint-redis>=2.0.0` 版本号不存在 → 改 `>=0.5.0`。
  2. `providers/__init__.py` 相对导入层级错误 → `...config`。
  3. `app/agents/__init__.py` 空文件 → 显式导入子模块。
  4. `RedisSaver.from_conn_string` 返回上下文管理器 → 直接实例化 + `setup()`。
  5. `human_review` 节点 resume 重入冲突 → 幂等守卫。
  6. 测试跨会话幂等键污染 → fixture `drop_all`。
  7. `redis:7-alpine` 缺 RedisJSON → `redis-stack-server` 且不覆盖 command。
- 结果：**30/30 pytest 通过**（20 单元 + 10 集成）。

### 2. 前端构建
- `npm install` + `npm run build` 通过（3043 模块，产物 ~1.1MB / gzip 348KB）。
- 仅 chunk > 500KB 警告（非阻断）。

### 3. Docker 全栈
- `docker compose up -d --build` 构建并启动 5 服务。
- **端口冲突**：本机 8000 已被 `rag_api` 容器占用 → 后端改映射 `8001:8000`（未动他人容器）。
- 结果：`postgres/redis/api/worker/frontend` 全部 `Up`，api/postgres/redis `healthy`。

### 4. 端到端验证（`scripts/verify_e2e.py`）
- 16/16 断言通过：登录、低金额自动完成、高金额转人工并批准、agent 越权 403、重复审批 409、幂等、列表。
- Worker 日志确认：`done, decision=APPROVE` 与 `suspended for human review` 均正常。

### 5. 压测（Locust headless）
- 20 并发 / 20 秒：259 请求，**0 失败**；建案均值 60ms，列表 13ms，登录 340ms（bcrypt 刻意慢）。

## 二、诚实声明 / 已知边界

- 压测为**单机 20 并发短时**，用于功能与基础吞吐验证，非极限压测。
- 默认 JWT 密钥为占位值，生产必须替换（已注明）。
- 前端 `npm audit` 报 4 个构建期 devDependencies 漏洞（不进生产镜像），未处理。
- 集成测试依赖真实 Postgres/Redis（Docker 提供），纯单元测试无外部依赖。

## 三、结论

系统已在真实 Docker 环境中完成「构建 → 启动 → 测试 → 端到端 → 压测」全链路验证，核心业务链路（自动退赔 / 转人工审批 / 越权拦截 / 幂等 / 防重复退款）全部通过。
