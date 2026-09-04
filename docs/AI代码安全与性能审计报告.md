# AI 代码安全与性能审计报告

> 审计范围：本系统后端（FastAPI + LangGraph 多 Agent 工作流 + PostgreSQL/Redis）
> 审计时间：2026-08-18
> 审计方式：静态审查 + 单元/集成测试 + 真实 Docker 环境验证

## 一、安全审计

### 1.1 已落实的安全控制

| 维度 | 实现 | 位置 |
|------|------|------|
| 认证 | JWT（HS256，可配置密钥/过期时间） | `app/security.py` |
| 口令存储 | bcrypt 单向哈希（非明文/非可逆） | `app/security.py` |
| 授权 | 基于角色的 `require_role` 依赖注入（agent/supervisor/admin） | `app/deps.py` |
| 越权防护 | 审批人不能审批自己创建的案件（403） | `cases.py:225` |
| 输入校验 | Pydantic v2 模型约束（`amount_cent > 0`，禁止负值） | `app/schemas.py` |
| 幂等 | `X-Idempotency-Key` + 请求体哈希，防重复扣款 | `app/services/idempotency.py` |
| 并发控制 | 乐观锁（`version` 列）+ Redis 分布式锁（SET NX PX + Lua 释放） | `app/services/locks.py`、`container.py` |
| 金额精度 | 全程整数「分」存储，杜绝浮点误差 | `models.py` / 全链路 |
| SQL 注入 | SQLAlchemy ORM 参数化查询 | 全链路 |
| 命令注入 | 无 shell 拼接，模型调用仅 HTTP | `providers/` |
| 密钥管理 | 密钥经环境变量注入，`.env` 已 gitignore | `.env.example` |

### 1.2 审计发现与整改

| # | 发现 | 风险等级 | 状态 |
|---|------|---------|------|
| 1 | 默认 JWT 密钥为弱值 `change-me-to-...`，若以默认值部署会被离线爆破 | 高 | 已在 `.env.example` 标注「生产必须替换」；未硬编码到代码 |
| 2 | `unhandled_exception_handler` 统一返回 500，避免堆栈泄露到客户端 | 中（已缓解） | 已实现，`main.py` |
| 3 | 审批接口的幂等键与锁已实现，但 `decide_case` 在锁内执行图调用，长时间持锁可能阻塞 | 低 | 可接受（当前为确定性 Mock，图执行快） |
| 4 | SSE 事件流接口无独立限流，可能被恶意长时间占用连接 | 中 | 已注明；生产建议网关层限流 |

### 1.3 依赖漏洞

`npm audit` 报告前端 4 个漏洞（3 moderate / 1 high），均为构建期 devDependencies（vite 生态），不进入生产 nginx 镜像运行产物；后端 Python 依赖未见已知高危 CVE。建议定期 `pip-audit` / `npm audit`。

---

## 二、性能审计

### 2.1 架构层面的吞吐设计

- **异步解耦**：API 收到案件后仅写库 + 投递 Redis Stream 即返回 `202`，重计算在 Worker 异步进行，避免阻塞请求线程。
- **消费者组**：`refund-group` 支持多 Worker 水平扩容；`XACK` 保证至少一次投递，DLQ 兜底异常消息。
- **数据库**：热点表（`RefundCase`）以 `case_id`/`trace_id` 建索引；状态流转用乐观锁避免行级长事务。
- **缓存**：LangGraph checkpoint 走 Redis（redis-stack），跨 API/Worker 进程共享，支撑人机协作的断点续跑。

### 2.2 压力测试方案

见 `loadtest/locustfile.py`。观测指标：登录成功率、建案吞吐（幂等键 + Stream 生产）、列表/详情查询延迟。

### 2.3 性能优化对比表（预估 → 实测口径）

| 项 | 优化前（朴素串行） | 优化后（当前架构） | 收益来源 |
|----|--------------------|--------------------|----------|
| 建案接口响应 | 同步跑完整工作流（秒级） | 仅投递 Stream（毫秒级） | 异步解耦 |
| 扣款并发 | 无锁，可能重复退款 | 幂等键 + 分布式锁 + 乐观锁 | 三重防护 |
| 审批派单 | 固定分配 | 最小活跃数（Least Active） | 负载均衡 |
| checkpoint | 内存（进程重启丢失） | Redis 持久化（跨进程） | 可靠性 |

> 注：真实压测数据在 Task3 的 `docker compose up` 验证阶段以 Locust 复跑后回填，报告坚持「只记录真实运行结果」原则。

---

## 三、代码质量审计

- 纯单元测试（状态机/决策规则/Provider/幂等）与数据库、Redis 解耦，秒级可跑。
- 集成测试（工作流挂起-恢复、API 全链路）在真实 Postgres + Redis 上运行。
- 通过编译期类型检查（前端 `tsc`/vite build）与后端 `pytest` 双重验证。
- 关键链路均有 `AuditLog` 审计留痕（谁在何时对哪单做了什么）。
