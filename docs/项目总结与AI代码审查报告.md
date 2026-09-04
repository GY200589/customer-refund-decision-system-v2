# 项目总结与AI代码审查报告

> 任务四 · 交付物 · 2026-08-19
> 系统：客诉舆情退赔决策系统（多 Agent 协同）
> 代码生产方式：Loop Engineering 驱动 AI（Cursor/Gemini）生成，本人审核、联调、修复

---

## 第一部分 · 项目整体理解

### 1.1 一句话定位

构建一个「多 Agent 协同」的客诉舆情退赔决策系统：**确定性规则 + 可插拔真实模型**自动处理退款，**高风险案件强制转人工**，资金操作全程**幂等、防重、审计**。

### 1.2 系统架构

```
                     ┌────────────────────────────────────────┐
  用户 ──HTTP──▶ 前端(nginx/React, antd)                      │
                     │ /api                                   │
                     ▼                                        │
              FastAPI (JWT/RBAC/幂等/分布式锁)                 │
                     │ 写库 + 投递 Redis Stream（即返 202）      │
                     ▼                                        │
              Worker ──▶ LangGraph 多 Agent 工作流            │
                           intake → evidence(OCR) → fraud      │
                           → sentiment → decision              │
                           → human_review(interrupt) ─┐        │
                             ├─ APPROVE → execute_refund       │
                             └─ REJECT  → reject               │
                     │                                        │
              PostgreSQL(案件/审计)   Redis(checkpoint/Stream/锁)
```

关键点：**API 只写库 + 投递消息就返回**，重计算在 Worker 异步进行，因此建案接口毫秒级返回（实测平均 60ms）。API 与 Worker 通过 **Redis checkpointer** 共享工作流状态，实现跨进程的人机协作断点续跑。

### 1.3 多 Agent 职责

| Agent | 职责 | 输出 |
|-------|------|------|
| IntakeAgent | 订单/金额/字段校验 | 标准化输入 |
| EvidenceAgent | 凭证 OCR（Mock/Paddle） | 文本 + 置信度 |
| FraudAgent | 欺诈风险打分（Mock/LLM） | fraud_score |
| SentimentAgent | 舆情情绪分析（Mock/LLM） | sentiment_score + 风险等级 |
| DecisionPolicy | **确定性决策规则** | APPROVE / REJECT / HUMAN_REVIEW |
| HumanReview | 挂起状态机，等待主管 | interrupt 断点 |
| ExecuteRefund | 幂等退款执行 | refund_ref |
| Reject | 驳回终态 | REJECTED |

### 1.4 三大设计支柱

1. **金额用整数「分」**：全程 `amount_cent`（int），接口以「元」字符串展示，杜绝浮点误差——退款是资金操作，精度是底线。
2. **确定性决策 + 模型只做评分**：金额与「批准/拒绝/转人工」的裁决由确定性规则（阈值表）给出，LLM 只输出风险/情绪**评分**，且「模型异常/低置信度一律转人工，绝不自动通过」。
3. **人机协作断点续跑 + 三重防重复扣款**：LangGraph `interrupt()` + Redis 持久化 checkpoint；请求幂等键 + 乐观锁（version）+ Redis 分布式锁。

---

## 第二部分 · AI 代码审查：潜在 Bug / 并发问题与修复

本项目代码由 AI 通过 Loop Engineering 生成。AI 生成的代码在**单进程、串行、正常路径**下通常能跑通，但在**多进程、并发、冷启动、组件契约变化**等边界条件下会暴露潜在 Bug。以下 4 个案例均在本项目**真实发生并修复**，每个案例给出「AI 写的问题代码 → 根因 → 我的修复 → 修复后代码」。

---

### 案例 1：Redis checkpointer 静默回退内存 → 跨进程状态不一致（审批报 500）

**背景**：人工审批依赖「Worker 跑图到 `interrupt()` 挂起 → checkpoint 写入 Redis → API 用 `Command(resume=...)` 恢复」。API 与 Worker 必须**共用同一个 Redis checkpointer**。

**AI 写的问题代码（`workflow/checkpoint.py` 旧版）**：

```python
def build_checkpointer(use_redis: bool = True):
    if not use_redis:
        return MemorySaver()
    try:
        return RedisSaver(redis_url=settings.redis_url)
    except Exception:
        return MemorySaver()  # ← 静默降级！任何初始化异常都回退内存
```

**根因分析**：

- `redis-stack` 冷启动时，`redis-cli ping` 已返回 PONG（健康检查通过），但 `RedisJSON/RediSearch` 模块还在加载，此时 `setup()` 建索引会抛 `BusyLoadingError`。
- 旧代码把这一**瞬时故障**当成「Redis 不可用」，直接回退 `MemorySaver`。
- 后果：**Worker 写 Redis checkpoint，API 用内存 checkpoint**，两者状态分裂。审批时 API 的 `graph.invoke(Command(resume=...))` 找不到该 `thread_id` 的 checkpoint，从 intake 节点重跑，报 `KeyError: 'case_id'` → 前端显示「服务器内部错误」。

**我的修复**（`checkpoint.py` 现版）：失败先**重试 + 退避**，只有 test 环境允许回退内存，生产直接抛错交由容器重启重试，**绝不静默降级**：

```python
_REDIS_RETRY_ATTEMPTS = 10
_REDIS_RETRY_BACKOFF_SECONDS = 2.0

def build_checkpointer(use_redis: bool = True):
    if not use_redis:
        return MemorySaver()
    # ... 解析 RedisSaver 类 ...
    last_exc = None
    for attempt in range(1, _REDIS_RETRY_ATTEMPTS + 1):
        try:
            saver = redis_saver_cls(redis_url=settings.redis_url)
            saver.setup()
            logger.info("Redis checkpointer ready (attempt=%d)", attempt)
            return saver
        except Exception as exc:
            last_exc = exc
            time.sleep(_REDIS_RETRY_BACKOFF_SECONDS)
    if settings.app_env == "test":
        return MemorySaver()
    raise RuntimeError(f"Redis checkpointer unavailable after {_REDIS_RETRY_ATTEMPTS} attempts: {last_exc}")
```

**教训**：**降级边界必须显式**。「失败回退内存」在单进程里无害，在跨进程共享状态的多组件系统里是致命的状态分裂。生产环境宁可 fail-fast 让容器重启，也不能静默换存储后端。

---

### 案例 2：多 worker 并发 `create_all` 竞态 → UniqueViolation

**背景**：后端以 `uvicorn --workers 4` 多进程启动，每个 worker 启动时都会执行 `init_db()`。

**AI 写的问题代码（`db.py` 旧版）**：

```python
def init_db() -> None:
    Base.metadata.create_all(bind=engine)  # 4 个 worker 同时执行
```

**根因分析**：`create_all` 内部是「check-then-create」：先查表/枚举类型是否存在，不存在才 `CREATE`。4 个 worker 同时启动时，各自判定「`pg_type` / `pg_class` 不存在」并同时 `CREATE`，命中 PostgreSQL 唯一索引，抛：

```
UniqueViolation: duplicate key value violates unique constraint
  "pg_type_typname_nsp_index" / "pg_class_relname_nsp_index"
```

这是一个**典型的 check-then-act 竞态**（TOCTOU）。

**我的修复**（`db.py` 现版）：捕获 `IntegrityError` 重试即可自愈——因为冲突说明表已被别的 worker 建好：

```python
def init_db() -> None:
    last_exc = None
    for attempt in range(1, 6):
        try:
            Base.metadata.create_all(bind=engine)
            return
        except IntegrityError as exc:   # 并发 create_all 撞唯一索引，重试自愈
            last_exc = exc
            time.sleep(1)
    raise last_exc
```

**教训**：**「建表/迁移」这类 DDL 在多实例部署下天然有竞态**。演示可用重试兜底，生产应改用 Alembic 迁移（迁移带锁 + 版本表）而非 `create_all`。

---

### 案例 3：退款审批并发 —— 分布式锁 + 乐观锁 + 幂等的三重防护（对应「Redis 状态更新竞态」）

**竞态场景**：同一个 SUSPENDED 案件，两个主管**同时点「批准」**，或客户端重试 + 重复点击，若不做防护会**重复扣款（退款执行两次）**。这正是任务给出的「Redis 状态更新竞态 / Lost Update」在本系统的具体化。

本系统用**三层防护**闭环（均已落地）：

**① 请求幂等（防重放）** —— `services/idempotency.py`：

```python
def approval_key(actor_id, case_id, action, idempotency_key):
    raw = f"{actor_id}:{case_id}:{action}:{idempotency_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```
同键 + 同请求体哈希 → 直接返回缓存响应，不重复执行。

**② Redis 分布式锁（SET NX PX + Lua 原子释放）** —— `services/locks.py`：

```python
def acquire_lock(redis, key, ttl_ms=10000):
    token = uuid.uuid4().hex
    ok = redis.set(key, token, nx=True, px=ttl_ms)   # 原子抢锁
    return token if ok else None

def release_lock(redis, key, token):
    # Lua 脚本校验 token 再删，避免误删别的请求刚拿到的锁
    redis.eval(_RELEASE_SCRIPT, 1, key, token)
```

**③ 乐观锁（version 列 + 条件 UPDATE）** —— `container.py::Deps.transition`：

```python
result = db.execute(
    update(RefundCase)
    .where(RefundCase.case_id == case_id,
           RefundCase.status == from_status,
           RefundCase.version == case.version)     # 只有版本一致才更新
    .values(status=to_status, version=case.version + 1, ...)
)
if result.rowcount == 0:                            # 版本已变 → 别人改过
    raise ConcurrencyConflict(f"乐观锁失败: {case_id}")
```

审批接口把三者串起来（`api/routes/cases.py::decide_case`）：先查幂等 → `acquire_lock`（抢不到就 409）→ 校验状态仍为 SUSPENDED → 乐观锁流转 → 释放锁。

**我审查后指出的残余风险（已记录、当前可接受）**：`decide_case` 在**持锁期间**执行 `graph.invoke(resume)`（跑完 human_review + execute_refund），若图执行耗时超过锁 TTL（10s），锁会**提前过期**，理论上第二个并发审批可进入。当前由「乐观锁 + 状态校验 + 幂等键」兜底不会重复扣款，但**锁的语义已被破坏**。生产正确做法是「锁内只做状态流转，重计算/退款执行异步化」，或对长任务用**锁续期（watchdog）**。

**教训**：**锁的粒度 = 临界区大小**。把慢操作（图执行、外部调用）关进锁里，会让锁 TTL 与临界区时长脱节，导致锁形同虚设。

---

### 案例 4：前端状态灯 props 契约不一致 → 「黄灯闪烁」永不触发

**背景**：任务要求「状态灯」在 `SUSPENDED`（等待人工）时显示**黄灯闪烁**。AI 重构了 `AgentFlow` 组件后，调用方未同步。

**AI 写的问题代码（调用方与组件 props 不一致）**：

```tsx
// CaseDetail.tsx 旧版调用：
<AgentFlow runs={detail.agent_runs} terminal={...} />   // 传的是 terminal

// AgentFlow.tsx 旧版接收：
export default function AgentFlow({ runs, status, decision, refundStatus }) {
  // 用 status 判断 waiting，但 status 实际是 undefined！
  if (status === 'SUSPENDED') review = 'waiting'
}
```

**根因分析**：`AgentFlow` 期望 `status/decision/refundStatus`，调用方却传了旧版签名 `terminal`。JS/TS 下多余的 prop 被忽略、缺失的 prop 变 `undefined`，`status === 'SUSPENDED'` 恒为 false，**黄灯分支永不触发**——且 `dist/` 里还是旧的 Steps 步骤条构建产物，掩盖了问题。

**我的修复**（`CaseDetail.tsx` 现版）：对齐 props 契约，并给状态灯补上图例：

```tsx
<AgentFlow
  runs={detail.agent_runs}
  status={detail.status}
  decision={detail.decision}
  refundStatus={detail.refund_status}
/>
```

组件侧完整的状态灯语义（`AgentFlow.tsx` 现版）：

```tsx
const META = {
  done:    { color: '#52c41a', label: '已完成', symbol: '✓', anim: '' },
  error:   { color: '#ff4d4f', label: '失败',   symbol: '✕', anim: '' },
  running: { color: '#1677ff', label: '处理中', symbol: '',  anim: 'agent-pulse' }, // 呼吸
  waiting: { color: '#faad14', label: '等待人工', symbol: '!', anim: 'agent-blink' }, // 黄灯闪烁
  pending: { color: '#bfbfbf', label: '待执行', symbol: '',  anim: '' },
}
```

**教训**：**组件重构必须同步所有调用方**。根因是「组件公开契约（props 类型）没有被编译期强制」——若 `AgentFlow` 的 props 用 `interface` 显式声明并由调用方通过 `tsc` 校验，`terminal` 这个多余字段会直接报类型错。前端严格模式（`noUncheckedIndexedAccess` / 组件 props 强类型）是防这类「静默 undefined」的第一道闸。

---

## 第三部分 · AI 代码审查方法论小结

| 方法 | 说明 |
|------|------|
| **边界条件优先** | AI 代码在正常路径正确率高，缺陷集中在：多进程、并发、冷启动、降级、组件契约变化 |
| **跨进程共享状态要显式** | 案例 1：checkpoint 存储后端必须进程间一致，降级要 fail-fast 而非静默 |
| **check-then-act 必竞态** | 案例 2：DDL、状态读写都要考虑并发，用重试 / 乐观锁 / 原子操作收敛 |
| **锁的粒度 = 临界区** | 案例 3：慢操作不能关进锁里，锁 TTL 与临界区时长要匹配 |
| **契约要编译期强制** | 案例 4：类型系统是第一道闸，杜绝「静默 undefined」 |

> 其余 AI 生成代码的修复案例（依赖版本号臆造、`from_conn_string` 返回上下文管理器、interrupt 节点重入、测试跨会话污染、redis-stack 模块缺失、包内子模块未导出、相对导入层级错误等 7 项）见《面试QA库》第二部分。
