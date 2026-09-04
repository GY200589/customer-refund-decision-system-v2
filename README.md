# 客诉舆情退赔决策系统（多 Agent 协同）

一个基于 **FastAPI + LangGraph 多 Agent + PostgreSQL + Redis** 的客诉舆情退赔决策系统。
核心目标：用「确定性规则 + 可插拔真实模型」自动化退款决策，仅高风险案件转人工，全程幂等、可审计。

## 快速启动

```bash
# 1. 配置环境变量（首次）
cp .env.example .env   # 按需修改 JWT_SECRET 等

# 2. 一键启动（含构建）
docker compose up -d --build

# 3. 查看状态
docker compose ps
```

启动后：

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端 | http://localhost:5173 | React 管理端（nginx 反代 /api） |
| 后端 API | http://localhost:8001 | FastAPI（容器内 8000） |
| 健康检查 | http://localhost:8001/api/v1/health | — |

> 端口说明：后端宿主机映射为 `8001`（因本机 8000 已被其他服务占用），前端 `5173`。如需改回 8000，编辑 `docker-compose.yml` 的 `ports`。

**默认账号**（密码均为 `password123`）：

| 账号 | 角色 | 说明 |
|------|------|------|
| agent1 | 客服 | 可创建案件 |
| supervisor1 | 主管 | 可审批案件 |
| admin1 | 管理员 | 全部权限 + 系统管理（阈值/用户/审计/健康） |

## 端到端验证

```bash
# 真实调用运行中的服务，验证核心链路（16 项断言）
backend/.venv/Scripts/python.exe scripts/verify_e2e.py
```

验证覆盖：登录、低金额自动完成、高金额转人工并批准、越权 403、重复审批 409、幂等、列表查询。

```bash
# 真实 PaddleOCR 效果验证（生成收据图片/PDF -> 识别 -> 断言文本/置信度/字段）
backend/.venv/Scripts/python.exe scripts/verify_ocr.py
```

实时 OCR：上传凭证接口（`POST /api/v1/cases/upload`）保存后同步识别，返回
`ocr_text / ocr_confidence / ocr_fields`，前端自动回填空缺的订单号/金额。
本地启用真实识别：设置 `OCR_PROVIDER=paddle`（未安装 paddleocr 时自动回退 mock）。

## 测试

```bash
# 后端：47 个 pytest（单元 + 集成，需 Postgres/Redis）
cd backend && .venv/Scripts/python.exe -m pytest -q

# 前端：类型检查 + 构建
cd frontend && npm run build

# 压测（可选）
cd loadtest && locust -f locustfile.py --host http://localhost:8001 --users 20 --spawn-rate 5 --run-time 20s --headless --only-summary
```

> 测试环境隔离：本地 pytest 自动使用独立的测试库 `refund_test_db` 与 Redis `db 15`，
> 不会破坏正在运行的 Docker 开发栈（`refund_db` / `redis db0`），也避免 Worker 消费测试
> 消息导致状态竞争。可用 `TEST_DATABASE_URL` / `TEST_REDIS_URL` 覆盖默认值。

## 管理员接口（admin 角色）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/PUT | `/api/v1/admin/thresholds` | 查询/覆盖业务决策阈值（金额、OCR、欺诈分），运行时生效 |
| GET/POST | `/api/v1/admin/users` | 用户列表 / 新建用户 |
| PATCH | `/api/v1/admin/users/{id}` | 修改角色、姓名、启停、重置密码 |
| GET | `/api/v1/admin/audit-logs` | 审计日志查询（按案件号/操作人/动作过滤） |
| GET | `/api/v1/health` | 健康检查（探测数据库 + Redis 连通性） |

阈值决策优先级：运行时 DB 覆盖值 > 环境变量默认值；Worker 在每次决策时实时读取，
修改后无需重启即对新建案件生效。前端登录 `admin1` 后在「系统管理」页操作。

## 目录结构

```
├── backend/               # FastAPI + LangGraph 多 Agent 后端
│   ├── app/
│   │   ├── agents/        # 8 个 Agent 节点
│   │   ├── api/routes/    # auth / cases / review-tasks / admin / health
│   │   ├── domain/        # 状态机 / 异常
│   │   ├── policy/        # 确定性决策规则
│   │   ├── infrastructure/# Redis Streams / providers / 锁
│   │   ├── services/      # 幂等 / 锁 / 运行时阈值配置(config_store)
│   │   ├── workflow/      # LangGraph 图 / checkpoint
│   │   └── worker/        # Redis Stream 消费者
│   └── tests/             # pytest
├── frontend/              # React 18 + TS + AntD v5
│   └── src/               # pages / components / api
├── loadtest/              # Locust 压测
├── scripts/               # verify_e2e.py 等
├── docs/                  # 需求/架构/审计/总结/QA 文档
└── docker-compose.yml     # postgres / redis-stack / api / worker / frontend
```

## 核心设计

- **金额用整数「分」**：全链路 `amount_cent`，杜绝浮点误差。
- **7 状态机**：`CREATED→RUNNING→SUSPENDED→APPROVED→COMPLETED` + `REJECTED/FAILED`。
- **三重防重复扣款**：请求幂等键（含 user_id 隔离）+ 乐观锁（version）+ Redis 分布式锁。
- **人机协作断点续跑**：LangGraph `interrupt()` + Redis 持久化 checkpoint，API 与 Worker 跨进程恢复。
- **确定性 Mock + 真模型接口**：`Provider` 抽象层，`settings.*_provider` 切换 mock / paddle / ollama。
- **运行时阈值配置**：业务阈值默认来自环境变量，管理员可运行时覆盖（DB `system_config`），决策时实时读取。
- **最小权限访问**：客服仅能查看/订阅自己创建的案件（列表、详情、SSE 事件流一致）；主管/管理员可见全部；审批人不能审批自己创建的案子。

## 业务阈值（可配置）

| 规则 | 阈值 | 处置 |
|------|------|------|
| 金额 ≥ 300 元 | 30000 分 | 转人工 |
| OCR 置信度 < 0.80 | 0.80 | 转人工 |
| 欺诈分 ≥ 80 | 80 | 拒绝 |
| 欺诈分 ≥ 50 | 50 | 转人工 |
| 舆情 HIGH / 模型异常 | — | 转人工 |

## 真实验证记录（本会话实际运行）

- 后端 `pytest`：**47/47 通过**（含新增 admin / 幂等隔离 / SSE 鉴权 / 案件归属 / 健康检查 / 阈值配置测试）。
- 前端 `npm run build` + `tsc --noEmit`：通过（3044 模块）。
- Docker 全栈：5 服务 `Up (healthy)`，健康检查返回 `database`/`redis` 均 ok。
- 端到端脚本：**17/17 断言通过**（含新增「客服仅见本人案件」）。
- 管理员接口实测：阈值/用户/审计查询 200，客服越权 403。
- 测试环境已隔离（`refund_test_db` + Redis db15），不再污染运行中的 Docker 开发栈。

详见 `docs/` 下各报告与 `docs/面试QA库.md`（7 个真实修复案例）。
