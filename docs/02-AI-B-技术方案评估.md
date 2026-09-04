# AI-B 技术方案评估

> 角色：资深后端工程师、分布式系统架构师、代码审查员（工程实现型模型）。独立评估，仅依据 `docs/00-原始需求.md`。

## 1. 推荐技术栈

| 组件 | 选型 | 职责 |
| --- | --- | --- |
| 后端框架 | Python 3.12 + FastAPI | 快速返回 202，路由、鉴权、参数校验、统一错误格式 |
| 工作流编排 | LangGraph | 多 Agent 节点编排、条件路由、interrupt/resume 人工挂起 |
| 数据库 | PostgreSQL 16 | 业务状态、审批、审计、幂等记录的最终事实源 |
| 缓存/队列 | Redis 7（Streams/PubSub/SETNX） | 异步任务队列、分布式锁、工作流 checkpoint、SSE 事件 |
| OCR | 本地 PaddleOCR（可切换 Mock） | 凭证文字识别 + 置信度 |
| LLM | Ollama/Qwen（可切换 Mock） | 情绪、实体、风险辅助判断（不参与金额计算） |
| 前端 | React + TypeScript + Vite + Ant Design + Zustand + TanStack Query + ECharts + SSE | 现代化 Dashboard |
| 测试/压测 | pytest + httpx、Locust | 单元/接口测试、并发压测 |

## 2. 运行时 Agent 划分

| Agent | 输入 | 输出 | 失败处理 |
| --- | --- | --- | --- |
| IntakeAgent | 案件请求（订单、金额、用户、诉求） | 校验结果、标准化字段 | 校验失败 → REJECTED/FAILED |
| EvidenceAgent | 凭证文件 | OCR 文本、字段、单字段与总体置信度 | 超时/低置信度 → 转人工 |
| FraudAgent | 订单历史、金额、证据完整度 | 欺诈分（0-100）、风险因子 | 异常 → 转人工 |
| SentimentAgent | 投诉文本、风险信号 | 情绪分、风险等级（LOW/MEDIUM/HIGH） | 异常 → 转人工 |
| DecisionPolicy | 上述结果 + 规则 | APPROVE / REJECT / HUMAN_REVIEW + 理由 | 确定性规则，不依赖模型 |

## 3. 状态机设计

七态状态机（以 PostgreSQL 为准）：

```
CREATED -> RUNNING -> SUSPENDED -> APPROVED -> COMPLETED
                        |  -> REJECTED
                        └-> FAILED / EXPIRED
```

合法流转：
- CREATED → RUNNING（入队）
- RUNNING → SUSPENDED（需人工）/ APPROVED（低风险自动）/ REJECTED / FAILED / COMPLETED
- SUSPENDED → APPROVED / REJECTED（主管审批 resume）→ COMPLETED
- APPROVED → COMPLETED（退款执行成功）
- 终态（COMPLETED/REJECTED/FAILED）不可再变更，非法流转返回明确错误。

## 4. 异步任务设计

```
FastAPI -> PostgreSQL(状态 CREATED) -> Redis Stream -> Worker(Consumer Group) -> LangGraph
```

- 创建接口只做校验+落库+发布，快速返回 `202`；长耗时 OCR/推理交给 Worker。
- 使用 Consumer Group（`refund-group`），消费失败进重试或死信流（`refund-dlq`）。
- 消息携带 `case_id`、`trace_id`。
- 同一案件由单一 Worker 推进（Consumer Group 保证单消费者 + 状态乐观锁）。
- Worker 可安全重启（未 ACK 消息不丢）。

## 5. 状态持久化

| 数据 | 存储 |
| --- | --- |
| 案件状态、审批记录、退款记录、审计日志、幂等记录、Agent 执行记录 | PostgreSQL |
| Redis Streams 队列、分布式锁、工作流 checkpoint、SSE 短期事件 | Redis |
| 挂起后恢复 | Redis checkpoint 恢复图上下文，最终状态仍写回 PostgreSQL |

## 6. 数据库和接口建议

核心表：`users`、`refund_cases`、`case_evidences`、`agent_runs`、`risk_assessments`、`review_tasks`、`idempotency_records`、`audit_logs`。

关键字段（不写完整代码）：
- `refund_cases`：case_id、order_id、user_id、amount_cent（整数分）、status、version、decision、decision_reason、trace_id、created_at、updated_at。
- `case_evidences`：id、case_id、file_name、file_hash、ocr_text、ocr_confidence、created_at。
- `agent_runs`：id、case_id、agent_name、status、input_summary、output_summary、started_at、finished_at、error。

主要 API：
- `POST /api/v1/auth/login`
- `POST /api/v1/cases`（202）
- `GET /api/v1/cases/{case_id}`
- `GET /api/v1/cases/{case_id}/events`
- `POST /api/v1/cases/{case_id}/decision`（审批，主管）
- `GET /api/v1/review-tasks`
- `GET /api/v1/health`

## 7. 幂等和并发控制

- `X-Idempotency-Key`：相同 key 返回首次结果；相同 key 不同 body 报错；不同 key 不能绕过案件状态校验。
- Redis 锁：`SET refund:approval:{case_id} {token} NX PX 10000`，释放用 Lua 校验 token 防误删。
- 数据库唯一约束：`idempotency_records.key` 唯一；`refund_cases.case_id` 唯一。
- 乐观锁：`UPDATE ... SET status=?, version=version+1 WHERE case_id=? AND version=?`，`expected_version` 防丢失更新。
- 三者共同保证重复审批与重复退款不会发生。

## 8. 模型和 OCR 的防御性设计

- 超时：Provider 统一带超时，超时/不可用 → 转人工。
- 置信度过低：`confidence < 阈值` → 转人工，不自动批准。
- 非法 JSON：解析失败重试一次，仍失败 → 转人工（SUSPENDED）。
- 模型不可用：安全降级，绝不允许自动批准。

## 9. 性能和部署风险

- 工单"QPS 200-1000、P95<300ms、错误率<0.1%"应对标"快速接口"（创建案件、查询、健康检查），不对标"完整模型链路"（OCR + LLM 数秒级）。
- 本地 OCR + 本地大模型同时运行对 CPU/内存压力大，单机 Docker 下难以同时达到 1000 QPS；需明确验收口径为"快速接口达标 + 异步完成吞吐量单独统计"。
- 建议：创建案件接口返回 202 异步化；查询接口加 Redis 缓存与索引；压测区分快速接口与异步流程。

## 10. 待人类确认的技术决策

- T1 金额阈值（默认 300 元）是否固定。
- T2 OCR 置信度阈值（建议 0.80）。
- T3 欺诈分阈值（建议 >=50 转人工、>=80 拒绝）。
- T4 模型异常是否允许自动批准（建议禁止，转人工）。
- T5 PostgreSQL/Redis 数据分工（建议 PG 为最终状态、Redis 存队列/锁/checkpoint）。
- T6 并发审批返回（建议 HTTP 409）。
- T7 状态机粒度（建议七态）。
- T8 验收口径（快速接口 P95 vs 全链路）。
- T9 数据库选型（PostgreSQL）。
