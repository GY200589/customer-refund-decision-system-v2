# 面试 QA 库

> 面向「多 Agent 协同 + 退款决策」系统的面试复盘。以下修复案例均为本项目建设过程中**真实发生并解决**的问题。

## 一、高频必问

### Q1：为什么金额要用「分」（整数）而不是 float？
**A**：退款是资金操作，float 的二进制表示（如 `0.1 + 0.2 != 0.3`）会导致分毫差异，累加后产生账实不符。全链路用 `amount_cent`（int），仅在展示层换算成「元」字符串。这同时避免数据库浮点精度问题（PostgreSQL `numeric` 也可，但整数分语义更清晰、比较更安全）。

### Q2：如何保证「不会重复退款」？
**A**：三重防护：
1. **请求幂等**：`X-Idempotency-Key` + 请求体哈希，同一键重复请求直接返回缓存响应；
2. **分布式锁**：审批动作在 Redis 上 `SET NX PX` 抢锁，Lua 脚本比对 token 释放，防止并发审批；
3. **乐观锁**：`RefundCase.version` 列，`UPDATE ... WHERE version = ?`，行数 0 即抛 `ConcurrencyConflict`。

### Q3：多 Agent 之间如何编排与断点续跑？
**A**：LangGraph `StateGraph` 定义 8 个节点 + 条件边。关键在 `human_review` 节点用 `interrupt()` 挂起，checkpoint 持久化到 Redis（跨 API/Worker 进程共享）。主管审批时 API 用 `Command(resume={...})` 按 `thread_id=case_id` 恢复，从断点继续。

### Q4：模型给出高风险时，系统会直接拒绝还是转人工？
**A**：分级处置：`fraud >= 80` 直接拒绝；`fraud >= 50`、金额超阈值、OCR 置信度低、舆情 HIGH、**模型异常**，全部转人工。核心原则是「**模型绝不自动通过**」，宁可多一道人工，不可误退款。

### Q5：为什么用「确定性 Mock + 真模型接口」而非直接接大模型？
**A**：演示/测试需要可复现、无外部依赖；生产需要真实能力。通过 `Provider` 抽象层 + `settings.*_provider` 开关，两全其美：Mock 保证确定性，PaddleOCR/Ollama 接口保证可替换，未来无缝接入。

---

## 二、真实修复案例（含根因）

### 案例 1：`langgraph-checkpoint-redis` 版本号写错导致依赖无法安装
- **现象**：`pip install -r requirements.txt` 报 `No matching distribution found for langgraph-checkpoint-redis>=2.0.0`。
- **根因**：该包实际最新仅 `0.5.1`（版本号与 langgraph 主版本解耦），我凭经验臆造了 `>=2.0.0`。
- **修复**：改为 `>=0.5.0`。
- **教训**：**引依赖前先 `pip index versions <pkg>` 查真实版本**，不要照搬教程里的旧版本号。

### 案例 2：`RedisSaver.from_conn_string` 返回的是上下文管理器而非实例
- **现象**：`graph.compile(checkpointer=RedisSaver.from_conn_string(url))` 报 `TypeError: Invalid checkpointer provided`。
- **根因**：该版本的 `from_conn_string` 是 `@contextmanager`，返回 `_GeneratorContextManager`，不是 `RedisSaver`。
- **修复**：改为 `RedisSaver(redis_url=url)` 直接实例化，并额外调用 `saver.setup()`（因为 `__init__` 不建索引）。
- **教训**：**库的 API 变了，先 `inspect.signature` + 读源码确认返回值**，不要想当然。

### 案例 3：`human_review` 节点在 resume 时重入导致状态冲突
- **现象**：恢复审批时报 `ConcurrencyConflict: 期望 RUNNING, 实际 SUSPENDED`。
- **根因**：LangGraph 的 `interrupt()` 恢复时会**从头重跑当前节点**，节点顶部的 `transition(RUNNING→SUSPENDED)` 和 `create_review_task` 第二次执行时状态已变。
- **修复**：节点改为幂等——先查当前状态，仅当 `!= SUSPENDED` 才执行流转与建任务。
- **教训**：**使用 interrupt 的节点必须幂等**，因为副作用会被重复执行。

### 案例 4：测试跨会话污染（幂等键命中旧 case_id）
- **现象**：单跑通过，全量跑 `test_decision_flow_end_to_end` 失败，新案件状态莫名是 `SUSPENDED`。
- **根因**：幂等记录表 `IdempotencyRecord` 持久化在共享库，上一轮 pytest 的 `e2e-create` 键残留，新轮次建案时命中旧记录返回旧 case_id。
- **修复**：`db_setup` fixture 改为 session 开始时 `drop_all` + `create_all`，保证干净基线。
- **教训**：**集成测试必须隔离外部状态**，数据库/缓存都要在 fixture 里重置。

### 案例 5：`redis:7-alpine` 缺 RedisJSON 导致 checkpoint 写入失败
- **现象**：写 checkpoint 报 `unknown command 'JSON.SET'`，随后 `checkpoint_write: no such index`。
- **根因**：LangGraph 的 Redis 检查点依赖 RedisJSON + RediSearch 模块，`redis:7-alpine` 不带。
- **修复**：换 `redis/redis-stack-server`，且**不能覆盖 `command`**（否则 entrypoint 不加载模块）。
- **教训**：**选基础镜像前先确认功能模块**，`redis-stack` 与纯 `redis` 的能力差异很大。

### 案例 6：包内子模块未导入导致 `AttributeError`
- **现象**：`module 'app.agents' has no attribute 'intake'`。
- **根因**：`graph.py` 用 `agents.intake.run(...)`，但 `app/agents/__init__.py` 是空文件，子模块未显式导入。
- **修复**：在 `__init__.py` 显式 `from . import intake, evidence, ...`。
- **教训**：**依赖包内属性访问时，必须在 `__init__.py` 显式导出**，否则换解释器/时机就炸。

### 案例 7：相对导入层级写错
- **现象**：`ModuleNotFoundError: No module named 'app.infrastructure.config'`。
- **根因**：`providers/__init__.py` 写 `from ..config import settings`，但实际 `config` 在 `app/config.py`（需 `...config`）。
- **修复**：改为 `from ...config import settings`。
- **教训**：**相对导入点数量 = 从当前包向上跳的层级**，改了目录层级就要同步改导入。

---

## 三、架构 / 概念追问

### Q7：Redis Stream 消费者组 vs 简单 List，为什么选 Stream？
**A**：Stream 原生支持**消费者组**（多 Worker 水平扩容）、**消息确认**（`XACK`，至少一次投递）、**DLQ 兜底**（`move_to_dlq`），且能按 `>` 读取新消息。这些特性在订单/退款这种「不能丢、不能重复」的场景是刚需。

### Q8：乐观锁 vs 悲观锁（SELECT FOR UPDATE）怎么选？
**A**：退款审批是低冲突场景（同一案件并发审批概率低），乐观锁无锁开销、吞吐高，冲突时重试即可；悲观锁适合高冲突长事务。这里用「乐观锁 + 分布式锁」组合，兼顾性能与正确性。

### Q9：如何保证 Worker 与 API 进程共享工作流状态？
**A**：两者共用同一个 Redis checkpointer，`thread_id` 用 `case_id`。Worker 跑到 `interrupt()` 时状态落 Redis，API 用同一 `thread_id` 的 `Command(resume)` 恢复——进程间不共享内存也能协作。

### Q10：如果 LangGraph 的 checkpoint 服务不可用，系统如何降级？
**A**：`build_checkpointer` 先**重试 10 次（每次退避 2s）**，应对 redis-stack 冷启动的 `BusyLoadingError`；仍失败时，**test 环境回退 `MemorySaver`，生产直接抛错 fail-fast**（交由容器重启重试），**绝不静默回退内存**。因为内存 checkpoint 是进程内状态，API 与 Worker 各用各的内存，`thread_id` 对不上会从 intake 重跑、报 `KeyError`——这曾真实导致审批 500（详见《项目总结与AI代码审查报告》案例 1）。

---

## 四、任务四重点面试题（人机协作 / LLM 精度与性能 / 高并发压测）

### Q11：多 Agent 架构中「人工介入节点」如何做到不丢失状态？

**A**：靠「**图状态持久化 + 业务状态双写**」两条腿，缺一不可：

1. **LangGraph `interrupt()` 挂起**：`human_review` 节点在需要人工时调用 `interrupt()`，把当前图状态序列化到 **Redis checkpointer**，Worker 进程即可退出而不丢上下文。
2. **`thread_id = case_id` 对齐**：API 与 Worker 用同一个 `thread_id` 找 checkpoint，主管审批时 API 用 `Command(resume={"action":...})` 从断点继续——进程间不共享内存也能协作。
3. **业务状态落库（DB 是「事实源」）**：挂起时同时写 `RefundCase.status = SUSPENDED` + `ReviewTask` + `AuditLog`。即使 Redis checkpoint 意外丢失，DB 里「谁、哪单、挂起原因、审批意见」仍在，可据此重建/人工兜底，不会变成「悬空案件」。
4. **两个必须防的坑**（本项目真实踩过）：
   - **checkpointer 进程间不一致**：若 API 用内存、Worker 用 Redis，resume 会找不到 checkpoint 从 intake 重跑——所以生产绝不静默回退内存（Q10）。
   - **interrupt 节点要幂等**：LangGraph 恢复时会**重跑当前节点**，节点顶部的状态流转/建任务必须「先查再写」，否则第二次执行报 `ConcurrencyConflict`（案例 3）。

一句话：**内存里是「进度」，数据库里是「事实」**——checkpoint 保证断点续跑，DB 状态机保证业务不悬空、可审计。

### Q12：LLM 存在延迟和幻觉，如何做到退款金额计算的「高精度」+「高性能」？

**A**：核心原则是**「LLM 不碰钱」**——金额与裁决走确定性代码，LLM 只输出风险评分，且评分异常一律转人工。

**高精度（防幻觉）**：

- **金额从不经过 LLM**：金额以整数「分」（`amount_cent`）从订单/建案入参而来，全链路确定性代码流转，精度 = 整数运算精度，与模型无关。
- **裁决由确定性规则给出**：`DecisionPolicy` 按阈值表（金额 ≥30000 分转人工、fraud≥80 拒绝、OCR<0.80 转人工…）做 if/else，**不调用 LLM 做决策**。
- **模型输出结构化 + 置信度兜底**：LLM 只输出 `fraud_score/sentiment_score`，配合置信度阈值；**低置信度 / 模型异常 / 超时 → 转人工，绝不自动通过**。所以模型幻觉最坏结果是「多转一单人工」，而不会「错误放款」。

**高性能（降延迟）**：

- **异步解耦**：API 收案后仅「写库 + 投递 Redis Stream」即返回 202，LLM 推理在 Worker 异步进行——请求线程不被秒级推理阻塞（实测建案平均 60ms）。
- **Provider 分层**：`Provider` 抽象层按 `settings.*_provider` 切换 mock（确定性、毫秒）/ PaddleOCR / Ollama，演示可复现、生产可替换。
- **失败快速转人工（fail-safe）**：模型超时/异常不重试到底，而是立即转人工，保证不卡死也不冒险。

### Q13：QPS 300+ 压测时出现过哪些问题，如何用工具定位解决？

**A**：如实拆成「实测发现 + 面向 300+ 的瓶颈预案」两层。

**① 实测（Locust 20 并发，13 req/s，0 失败）暴露并解决的并发问题**：

| 问题 | 定位工具 | 根因 | 解决 |
|------|---------|------|------|
| 审批报 500（`KeyError: 'case_id'`） | Worker/API 日志（`Redis checkpointer init failed` 告警）+ 前端 500 堆栈 | redis-stack 冷启动 `BusyLoadingError` 触发 checkpointer 静默回退内存，跨进程状态分裂 | 重试 10 次 + 生产 fail-fast |
| 启动偶发 `UniqueViolation: pg_type_typname_nsp_index` | uvicorn 启动日志 | 4 worker 并发 `create_all` 的 check-then-create 竞态 | 捕获 `IntegrityError` 重试 |

**② 面向 300+ QPS 的瓶颈分析与工具**（扩容预案，尚未在 300+ 实测）：

- **登录接口 bcrypt ~340ms 是最大单点**：这是刻意昂贵以抗爆破，不能降 cost；高并发下用「登录态缓存/连接复用 + 网关限流」缓解，用 Locust 分接口统计确认。
- **DB 连接池耗尽**：`pool_size/max_overflow` 调优 + 上 PgBouncer；用 `pg_stat_activity` 看连接等待、`EXPLAIN ANALYZE` 找慢查询。
- **单 Worker 是工作流吞吐瓶颈**：Redis Stream 消费者组已就绪，多 Worker 水平扩容（`XACK` 至少一次投递 + DLQ 兜底）；用 `docker stats` + Worker 消费 lag（`XPENDING`）观察堆积。
- **锁 TTL 与临界区时长脱节**（案例 3 残余风险）：`decide_case` 持锁期间跑 `graph.invoke`，锁 10s TTL 可能提前过期——生产应「锁内只做状态流转、退款执行异步化」。
- **观测体系**：Locust（压测）→ `docker stats`（资源）→ Redis `INFO`/`MONITOR`（锁竞争、热点 key）→ `pg_stat_activity` + `EXPLAIN ANALYZE`（DB）→ 结构化日志 + trace_id（全链路）→ Prometheus/Grafana（面板告警）。
