---
spec_status: locked
code_allowed: true
owner: 开发者
locked_at: 2026-08-18
---

# 需求与技术方案定稿

## 1. 产品定位

"多Agent协同客诉舆情退赔决策系统"：面向银行/证券/基金/保险/金融科技企业客诉场景，用多 Agent 协作自动完成凭证 OCR、欺诈与舆情风险研判、退赔金额决策，同时以 Human-in-the-loop 保证高风险/超限额案件人工安全接管，资金操作防重、可审计、可解释。MVP 定位为可容器化部署、可压测自证的全栈系统。

## 2. 用户角色和权限

| 角色 | 权限 |
| --- | --- |
| 客服（agent） | 登录、创建案件、查看案件详情/决策链路、上传凭证；不可审批 |
| 客服主管（supervisor） | 客服全部权限 + 审批/拒绝人工挂起案件、查看审批中心 |
| 系统管理员（admin） | 用户管理、阈值配置、审计查询、健康监控 |

权限实现：JWT（sub=user_id、role），RBAC 校验；申请人 ≠ 审批人；客户端不得自传权限。

## 3. MVP 功能范围

**必须实现：** JWT 登录与角色控制；案件创建/查询/详情；X-Idempotency-Key 防重；LangGraph 多 Agent 决策流（Intake/Evidence/Fraud/Sentiment/DecisionPolicy）；七态状态机 + 挂起恢复；OCR 文本与置信度；欺诈分与风险报告；人工审批面板（批准/拒绝/意见）；Redis 分布式锁 + 幂等 + 乐观锁；审计日志；SSE 事件推送；前端 Dashboard；Docker Compose + 健康检查 + 自启动；Locust 压测。

**延后：** 完整 RAG 政策检索（预留接口）；真实支付网关（MockRefundProvider）；Prometheus/Grafana 全量接入。

**不做：** 外部公开舆情采集；真实资金操作；强制依赖真实 PaddleOCR/Ollama 模型。

## 4. 非功能需求

- 金额用整数分，禁止浮点；禁止负金额。
- 快速接口 P95 < 300ms、错误率 < 0.1%（异步全链路单独统计）。
- 状态与审计以 PostgreSQL 为准；Redis 只做队列/锁/checkpoint/短期事件。
- 统一错误格式，不暴露堆栈。
- 敏感信息脱敏（日志不落身份证/手机号/支付凭证）。
- 所有写接口幂等、可重试、可补偿。

## 5. 核心业务流程

```
登录 → 新建退款申请(202) → 校验+落库+幂等 → Redis Stream → Worker → LangGraph
  → Intake(校验) → Evidence(OCR) → Fraud(欺诈) → Sentiment(情绪/舆情) → DecisionPolicy(规则)
  → [APPROVE 自动执行 | REJECT | HUMAN_REVIEW 挂起]
  → (挂起)主管审批 → resume → 退款执行(幂等) → COMPLETED
全程审计日志 + SSE 事件推送前端
```

## 6. 状态机和状态流转

```
CREATED -> RUNNING -> SUSPENDED -> APPROVED -> COMPLETED
                        | -> REJECTED
                        └-> FAILED
```

合法流转矩阵：CREATED→RUNNING；RUNNING→SUSPENDED/APPROVED/REJECTED/FAILED/COMPLETED；SUSPENDED→APPROVED/REJECTED；APPROVED→COMPLETED；终态不可再变。非法流转返回 409/422 明确错误，不静默覆盖。

## 7. Agent 职责和输入输出

| Agent | 输入 | 输出 |
| --- | --- | --- |
| IntakeAgent | 订单、金额、用户、诉求、凭证 | 校验结果、标准化字段 |
| EvidenceAgent | 凭证文件 | OCR 文本、置信度 |
| FraudAgent | 订单历史、金额、证据完整度 | 欺诈分(0-100)、风险因子 |
| SentimentAgent | 投诉文本、风险信号 | 情绪分、风险等级(LOW/MEDIUM/HIGH) |
| DecisionPolicy | 上述结果 | APPROVE/REJECT/HUMAN_REVIEW + reason |

工作流状态字段：case_id、amount_cent、evidence、ocr_confidence、fraud_score、sentiment_score、risk_level、decision、review_reason、errors、trace_id。

## 8. 异常处理策略

| 异常 | 策略 |
| --- | --- |
| OCR 超时/不可用 | 转人工 SUSPENDED |
| OCR 置信度 < 0.80 | 转人工 |
| 模型超时/不可用/非法 JSON | 重试一次，仍失败转人工 |
| Redis 不可用 | 快速接口报错重试；PG 为准，Worker 恢复续跑 |
| Worker 崩溃 | Consumer Group 未 ACK，重启续跑 |
| 重复审批 | 幂等 + 锁 + 乐观锁，其余 409 |
| 退款重复执行 | 独立退款幂等键 + 终态校验 |
| 退款执行失败 | 幂等落库 + 一致性校验 + 可重试不重复扣款 |

## 9. 数据库设计

核心表：
- `users`：id、username、password_hash、role、display_name、is_active、created_at。
- `refund_cases`：case_id(PK/uuid)、order_id、user_id、amount_cent、currency、status、version、decision、decision_reason、risk_level、trace_id、created_at、updated_at、review_comment。
- `case_evidences`：id、case_id、file_name、file_hash、ocr_text、ocr_confidence、created_at。
- `agent_runs`：id、case_id、agent_name、status、input_summary、output_summary、started_at、finished_at、error。
- `risk_assessments`：id、case_id、fraud_score、sentiment_score、risk_level、risk_factors(JSON)、rule_version、created_at。
- `review_tasks`：id、case_id、assigned_to、status、comment、decided_at。
- `idempotency_records`：id、key(唯一)、request_hash、response_body、status_code、created_at。
- `audit_logs`：id、case_id、actor_id、action、before_value(JSON)、after_value(JSON)、created_at。

金额字段 `amount_cent` 为 INTEGER（整数分）。迁移用 Alembic 可重复执行。

## 10. API 接口设计

- `POST /api/v1/auth/login` → {token, user}
- `POST /api/v1/cases` → 202 {case_id}（幂等键 X-Idempotency-Key）
- `GET /api/v1/cases/{case_id}` → 案件详情 + 决策链路
- `GET /api/v1/cases/{case_id}/events` → SSE 事件流
- `POST /api/v1/cases/{case_id}/decision` → 审批（主管，body: action=APPROVE|REJECT, comment）
- `GET /api/v1/review-tasks` → 待审批任务列表（主管）
- `GET /api/v1/health` → 健康检查

统一错误格式：`{"error": {"code": "...", "message": "..."}}`；409 表示并发冲突/非法状态，401 未登录，403 越权，404 不存在，422 参数错误。

## 11. Redis、消息队列和 Checkpoint 设计

- Stream：`refund:stream`（消费组 `refund-group`）、死信 `refund:stream:dlq`。
- 锁：`refund:approval:{case_id}`，SET NX PX 10000，Lua 校验 token 释放。
- Checkpoint：LangGraph `RedisSaver`（thread_id = case_id）保存图上下文，用于挂起恢复；最终状态仍写 PostgreSQL。
- 事件：SSE 通过 Redis Pub/Sub（`case:{case_id}:events`）或轮询 PG 事件表推送。

## 12. 幂等、分布式锁和审计设计

- 幂等键：`hash(actor_id + case_id + action + idempotency_key)`，命中返回首次结果；同 key 不同 body 报 422；不同 key 不能绕过状态校验。
- 锁：审批与退款动作各自独立锁；释放校验 token。
- 乐观锁：`WHERE version = :expected_version`，防丢失更新。
- 审计：所有状态变更、审批、退款执行记录 before/after + actor + 时间，写入 audit_logs。

## 13. 前端 Dashboard 需求

页面：登录页、案件工作台（列表 + 状态筛选）、新建退款申请、案件详情、Agent 节点状态流转图、OCR 识别文本与置信度、欺诈分/情绪分/风险报告、人工审核面板（批准/拒绝/意见）、审批中心、错误/加载/空数据/权限不足状态。

交互：SSE 实时刷新；按钮按案件状态与角色禁用；刷新后状态恢复；窄屏可用。

## 14. 两个核心联调场景

**场景一（超限额转人工）：** 350.00 元 → SUSPENDED → 主管批准 → APPROVED → COMPLETED。
**场景二（低金额低风险自动）：** 128.00 元 → 欺诈分 20、舆情 LOW → 自动 COMPLETED。

## 15. 测试验收标准

- 状态机非法流转报错；规则边界（正/负金额、阈值边界）。
- 未登录 401、客服越权审批 403。
- 幂等：相同 key 返回首次结果、同 key 不同 body 报错。
- 并发审批只一个成功，其余 409。
- 模型异常/低置信度转人工，不自动批准。
- Worker 重启恢复；两场景端到端通过。
- 快速接口 P95<300ms、错误率<0.1%（本机 Docker 单机如实记录）。

## 16. 1 人 1 周 WBS 拆解

| 阶段 | 任务 | 人日 |
| --- | --- | --- |
| 任务一 | 需求逆向澄清 + 三方对齐 + WBS 定稿 + 架构手册 | 1.5 |
| 任务二 | 后端骨架/状态机/DB + 认证 API + Streams Worker + LangGraph 工作流 + 提供者 + 幂等锁 + 测试 + 前端 | 3.0 |
| 任务三 | Docker Compose + 健康检查 + 自启动 + Locust 压测 + 压测报告 | 2.5 |
| 任务四 | 安全审计 + 项目总结 + 面试 QA | 1.0 |
| 合计 | | 8.0（含缓冲） |

## 17. 已确认事项和未决事项

**已确认：** 全部阈值（D-001~D-013）、PostgreSQL 选型、七态状态机、整数分、验收口径、Mock + 真模型接口策略。

**未决事项：** 无阻塞项。真实支付网关、真实 PaddleOCR/Ollama 模型接入、外部舆情采集为后续扩展，不阻塞 MVP 编码。
