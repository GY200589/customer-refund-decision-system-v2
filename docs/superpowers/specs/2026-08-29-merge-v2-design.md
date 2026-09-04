# 客诉退赔决策系统 v2 · 合并设计文档

> 将工单5「Agent 评测、成本优化与本地沙箱安全协作系统」三大核心能力并入工单1「客诉舆情退赔决策系统」
>
> 版本：v1.0 | 日期：2026-08-29 | 状态：待实施

---

## 1. 架构总览

### 1.1 合并策略

本方案采用**单主体全合并**策略：以工单1（客诉退赔决策系统）为唯一主体仓库，工单5的三大能力作为增强模块迁入，原工单5项目保持不动。

```
工单1 仓库 (D:\d\多Agent 协同项目)
  │
  ├── 原有模块 ─── 保持不变
  │
  ├── 新增模块 ─── 从工单5 迁入/适配
  │   ├── batch/        ← 批量审批（Excel 导出/解析/唤醒）
  │   ├── sandbox/      ← 移植工单5 的 CubeSandbox 适配层
  │   ├── eval/         ← 移植并适配 Golden Dataset + LLM-judge
  │   └── telemetry/    ← 移植 Langfuse 链路追踪
  │
  ├── 改造模块
  │   ├── workflow/     ← Fraud + Sentiment 合并为一次 LLM 调用 + 并行化
  │   └── frontend/     ← 新增「导出挂起订单」「上传审批结果」按钮
  │
  └── 依赖更新
      ├── backend/requirements.txt  ← 新增 langfuse, openpyxl, python-docx, e2b-code-interpreter
      └── docker-compose.yml        ← 新增沙箱镜像（python:3.11-slim）
```

### 1.2 目录结构（目标）

```
backend/app/
├── __init__.py
├── main.py                     # FastAPI 入口（注册新路由）
├── config.py                   # 新增 SANDBOX_MODE 等配置项
├── container.py                # Deps 容器（新增 batch/sandbox/eval 依赖）
├── models.py                   # 不变
├── schemas.py                  # 不变
├── api/
│   └── routes/
│       ├── cases.py            # 不变
│       ├── review_tasks.py     # 不变
│       ├── admin.py            # 不变
│       └── batch.py            # ← 新增：批量审批路由
├── workflow/
│   ├── graph.py                # 改造：Fraud+Sentiment 合并为 merged_risk 节点
│   ├── state.py                # 改造：新增 merged_risk 字段
│   ├── checkpoint.py           # 不变
│   └── nodes/                  # ← 新增：节点函数独立目录
│       ├── __init__.py
│       ├── intake.py           # 不变
│       ├── evidence.py         # 不变
│       ├── fraud.py            # 改造：与 sentiment 合并
│       ├── sentiment.py        # 改造：与 fraud 合并
│       ├── merged_risk.py      # ← 新增：合并后的风险+舆情节点
│       ├── decision.py         # 不变
│       ├── human_review.py     # 不变
│       ├── execute.py          # 不变
│       └── reject.py           # 不变
├── batch/                      # ← 新增模块：批量审批
│   ├── __init__.py
│   ├── exporter.py             # 导出挂起订单为 Excel
│   ├── parser.py               # 沙箱解析审批后的 Excel
│   ├── executor.py             # 批量 resume_workflow + 汇总
│   └── models.py               # 审批结果 Pydantic 模型
├── sandbox/                    # ← 新增模块：沙箱适配（移植自工单5）
│   ├── __init__.py
│   ├── adapter.py              # SandboxAdapter ABC
│   ├── path_sanitizer.py       # 路径净化
│   ├── sandbox_manager.py      # SandboxLifecycleManager
│   ├── office_cli.py           # OfficeCLI（进程内）
│   ├── container_office_cli.py # ContainerOfficeCLI（Docker）
│   └── container_runner.py     # 容器内脚本
├── eval/                       # ← 新增模块：评测
│   ├── __init__.py
│   ├── dataset.py              # 10 个退赔域 Golden Dataset
│   ├── judge/
│   │   ├── __init__.py
│   │   ├── base.py             # BaseJudge ABC
│   │   ├── mock_judge.py       # MockJudge
│   │   └── llm_judge.py        # LLMJudge（调用 DeepSeek）
│   ├── metrics.py              # 指标计算
│   └── run_eval.py             # 评测入口
├── telemetry/                  # ← 新增模块：链路追踪
│   ├── __init__.py             # Tracer, SpanContext, TraceContext
│   ├── langfuse_backend.py     # LangfuseBackend（异步线程）
│   └── file_backend.py         # FileBackend 降级
└── infrastructure/
    └── providers/
        ├── __init__.py         # 改造：新增 get_combined_risk_provider
        ├── risk.py             # 不变（保留，可选回退）
        ├── sentiment.py        # 不变（保留，可选回退）
        └── combined_risk.py    # ← 新增：合并风险+舆情 LLM 调用
```

---

## 2. 模块设计详述

### 2.1 沙箱-批量审批（batch/ + sandbox/）

#### 批量审批流程图

```
Dashboard「导出挂起订单」
      │
      ▼
batch/exporter.py
  - 查库 RefundCase.status = SUSPENDED
  - 用 openpyxl 生成 Excel（含工单号/金额/风险分/空白审批列）
  - 返回文件流供前端下载
      │
      ▼
主管在 WPS/Excel 中逐行填写「同意/拒绝」+ 意见
      │
      ▼
Dashboard「上传审批结果」
      │
      ▼
batch/parser.py
  - 接收前端上传的 Excel 文件
  - SANDBOX_MODE=on → 用 ContainerOfficeCLI 在 Docker 沙箱内解析
  - SANDBOX_MODE=off → 用 OfficeCLI 直读（宿主机，漏洞基线）
  - 返回 List[ApprovalResult]
      │
      ▼
batch/executor.py
  - 逐条调用 resume_workflow(case_id, action, comment, operator)
  - 三层防重：幂等键 + 分布式锁 + 状态前置校验
  - 部分失败处理：跳过已处理单，不整体回滚
  - 返回汇总：批准 x 笔 / 拒绝 y 笔 / 失败 z 笔
```

#### 设计要点

| 要点 | 方案 |
|------|------|
| 沙箱使用 | 仅「解析回传 Excel」这一步在沙箱内执行，导出是纯输出 |
| 沙箱模式 | `SANDBOX_MODE` 环境变量：`on`（真沙箱） / `off`（宿主机直读，用于对比验证） |
| 防重防线 | 同单笔审批：幂等键(SHA256) + Redis SETNX 锁 + 状态前置校验 |
| 部分失败 | 逐条执行，某单已被他人处理则跳过，记录到汇总失败列表 |
| 审批唤醒 | 复用 `deps.transition() + graph.invoke(Command(resume=...))` |
| 仅读不写 | 沙箱只读解析 Excel，不写回。沙箱容器 `--read-only` 挂载 |

#### 导出 Excel 字段

| 列 | 性质 | 内容 |
|----|------|------|
| case_id | 只读（系统填） | 挂起工单唯一标识 |
| order_id | 只读（系统填） | 订单号 |
| 金额(元) | 只读（系统填） | 申请退款金额 |
| 风险分 | 只读（系统填） | fraud_score |
| 舆情等级 | 只读（系统填） | risk_level (HIGH/MEDIUM/LOW) |
| 审批动作 | 主管填 | 枚举：同意 / 拒绝 |
| 审批意见 | 主管填 | 自由文本（可选） |

#### 容器安全配置（沿用工单5）

```bash
docker run --rm \
  --network none \
  --read-only \
  --user 1000:1000 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --cpus 1.0 \
  --memory 512m \
  -v /sandbox/work_dir:/sandbox:rw \
  sandbox-image \
  python /sandbox/runner.py
```

### 2.2 评测（eval/）

#### 架构

```
eval/
├── dataset.py             # 10 个退赔域 Golden Dataset（硬编码 + JSON 加载）
├── judge/
│   ├── base.py            # BaseJudge: evaluate() → float, get_dimension_scores()
│   ├── mock_judge.py      # MockJudge: 确定性评分，离线可用
│   └── llm_judge.py       # LLMJudge: 调用 DeepSeek API 三维评分
├── metrics.py             # average_score, median_score, pass_rate, grade_distribution
└── run_eval.py            # 入口：加载数据 → 逐条评测 → 生成报告
```

#### 10 个 Golden Dataset（退赔域）

| # | 场景 | 关键变量 | 期望决策 |
|---|------|----------|----------|
| 1 | 小额低风险 | 金额 128 元、风险分 0.1、OCR 高置信 | APPROVE |
| 2 | 超300元限额 | 金额 350 元、凭证清晰 | HUMAN_REVIEW |
| 3 | 高风险恶意退款 | 风险分 0.9、高频退款 | REJECT |
| 4 | OCR 低置信 | 置信度 < 0.5、凭证模糊 | HUMAN_REVIEW |
| 5 | OCR 中等置信 | 置信度 0.5~0.7 | HUMAN_REVIEW |
| 6 | 舆情升级 HIGH | 舆情分高、投诉情绪激烈 | HUMAN_REVIEW |
| 7 | 中风险区间 | 风险分 0.2~0.5 | HUMAN_REVIEW |
| 8 | 空凭证 | 无图片/无描述 | HUMAN_REVIEW |
| 9 | 金额超实付 | 申请额 > 实付额 | 接口拒绝（422） |
| 10 | 正常小额退货 | 金额 99 元、凭证清晰、低风险 | APPROVE |

#### LLM-as-a-judge 三维评分

| 维度 | 权重 | 说明 |
|------|------|------|
| 决策正确性 | 40% | approve/reject/human-review 判得对不对 |
| 金额边界安全 | 30% | 有无误放高风险单 / 误拒低风险单 |
| 理由质量 | 30% | 决策依据是否充分可解释 |

#### Langfuse 集成

- 评测结果上报到 cloud.langfuse.com
- 异步非阻塞上报（线程队列 + 指数退避重试 3 次）
- 失败降级：缓存到 `logs/traces/failed_buffer.jsonl`

### 2.3 优化（workflow/ 改造）

#### 当前问题

```
intake → evidence → fraud(LLM) → sentiment(LLM) → decision → ...
                      ↑两次独立LLM调用，内容重复↓
          都传 description + evidence_text，Token 浪费 40-50%
```

#### 改造方案

```
intake → evidence → merged_risk(单次LLM) → decision → ...
                      ↑
              一次调用输出 {fraud_score, sentiment_score, risk_level, risk_factors, reasoning}
```

#### 新增文件

**`backend/app/infrastructure/providers/combined_risk.py`**:

```python
class CombinedRiskProvider:
    """合并风险+舆情分析，单次 LLM 调用输出双维度"""
    def assess(self, amount_cent, complaint_text, evidence_text, risk_flags) -> CombinedRiskResult:
        prompt = f"""分析以下退款申请：
金额：{amount_cent/100}元
投诉：{complaint_text}
凭证：{evidence_text}
风险标记：{risk_flags}

请输出 JSON：
{{
  "fraud_score": 0-100,
  "fraud_features": ["...", "..."],
  "sentiment_score": 0-100,
  "risk_level": "LOW|MEDIUM|HIGH",
  "reasoning": "..."
}}"""
        return self.llm.complete_json(prompt)
```

**`backend/app/workflow/nodes/merged_risk.py`**:

```python
async def run_merged_risk(state, deps):
    """合并风险+舆情节点，并行内部子任务"""
    # 并行执行：OCR 文本处理 + 风控/舆情合并分析
    evidence_text = state.get("ocr_text", "")
    complaint_text = state.get("complaint_text", "")
    risk_flags = state.get("risk_flags", {})

    result = await asyncio.gather(
        deps.combined_risk.assess(
            state["amount_cent"], complaint_text, evidence_text, risk_flags
        ),
        return_exceptions=True,
    )
    # ... 处理结果，返回合并后的 state 更新
```

#### 改造收益

| 指标 | 优化前 | 优化后 | 收益 |
|------|--------|--------|------|
| LLM 调用次数 | 2 次（Fraud + Sentiment） | 1 次（合并输出） | Token ↓~40-50% |
| 串行时延 | 两次串行 LLM | 一次 LLM 调用 | 时延砍半 |
| 并行收益 | 无 | fraud/sentiment 并行 → 0 额外等待 | 时延 ↓≥40% |

### 2.4 链路追踪（telemetry/）

#### 移植策略

工单5 的 telemetry 模块已是通用实现，**无需修改**即可直接迁入：

- `Tracer` 单例：全局 trace 管理器
- `SpanContext` / `TraceContext`：span 上下文模型
- `LangfuseBackend`：异步线程队列 + 指数退避重试 + 缓存降级
- `FileBackend` / `NullBackend`：降级方案

#### 集成点

在 `workflow/graph.py` 的每个节点函数中埋点：

```python
with tracer.span("fraud", span_type="llm", input={...}):
    result = deps.risk.assess(...)
```

在 `backend/app/main.py` 的 lifespan 中初始化：

```python
tracer = Tracer(backend=LangfuseBackend(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    host=settings.langfuse_host or "https://cloud.langfuse.com",
))
```

---

## 3. 配置变更

### `backend/app/config.py` 新增字段

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `SANDBOX_MODE` | str | "off" | 沙箱模式 on/off |
| `SANDBOX_IMAGE` | str | "sandbox-python:latest" | 沙箱镜像名 |
| `LANGFUSE_PUBLIC_KEY` | str | "" | Langfuse 公钥 |
| `LANGFUSE_SECRET_KEY` | str | "" | Langfuse 密钥 |
| `LANGFUSE_HOST` | str | "https://cloud.langfuse.com" | Langfuse 地址 |
| `EVAL_ENABLED` | bool | False | 是否启用评测能力 |
| `COMBINED_RISK_PROVIDER` | str | "mock" | 合并风险提供者（mock/llm） |

### `backend/requirements.txt` 新增依赖

```
langfuse>=2.0.0
openpyxl>=3.1.0
python-docx>=1.0.0
e2b-code-interpreter>=0.1.0
tiktoken>=0.5.0
```

---

## 4. 实施步骤

### 第 1 步：复制项目 + 依赖对齐

```
1. 复制 D:\d\多Agent 协同项目 → D:\d\客诉退赔决策系统-v2
2. 合并 requirements.txt 新增依赖
3. docker compose up -d 验证原项目可运行
4. 构建沙箱镜像 docker build -t sandbox-python -f Dockerfile.sandbox .
```

### 第 2 步：沙箱-批量审批落地

```
1. 移植 sandbox/ 模块（5 个文件）
2. 修改 config.py 新增 SANDBOX_MODE 配置
3. 新增 batch/ 模块（3 个文件 + 路由）
4. 前端新增「导出挂起订单」「上传审批结果」按钮
5. 全链路测试：导出→填写→上传→批量审批→汇总
```

### 第 3 步：评测落地

```
1. 移植 telemetry/ 模块
2. 新增 eval/ 模块（10 个 Golden 用例 + 三维评分）
3. 配置 Langfuse 云服务
4. 运行评测：python -m eval.run_eval --judge llm
```

### 第 4 步：优化改造

```
1. 新增 combined_risk.py 合并风险提供者
2. 新增 merged_risk.py 合并节点
3. 修改 graph.py 替换 fraud+sentiment 为 merged_risk
4. 对比测试：优化前后 Token 数与时延
```

### 第 5 步：合并验收

```
1. 两大核心场景联调：超300元挂起 / 小额秒退
2. 批量审批 + 沙箱逃逸测试
3. 评测报告 + 压测报告
```

---

## 5. 验收标准映射

| 能力 | 验收红线 | 验证方式 |
|------|----------|----------|
| 沙箱 | Excel 解析 100% 在沙箱内完成；off/on 可切换；抵御恶意 Excel/宏/注入/路径穿越 | 沙箱逃逸测试套件 |
| 评测 | 10 个 Golden 用例全量可跑；输出三维评分报告；Langfuse Trace 异步非阻塞 | 运行 `run_eval.py` |
| 优化 | Token ↓~40%；时延 ↓≥40%（不含 LLM 推理与沙箱冷启动） | 对比测试脚本 |
| 批量审批 | 三层防重生效；部分失败汇总不整体回滚 | 批量审批测试套件 |
| 兼容 | 原两大核心场景不回归 | 联调测试 |

---

## 6. 边界情况与错误处理

| 场景 | 处理方式 |
|------|----------|
| 沙箱容器不可用 | 降级为 OfficeCLI 进程内解析（路径校验兜底） |
| 上传 Excel 格式错误 | 返回友好错误提示，不尝试解析 |
| 审批单已被他人处理 | 跳过该单，记入汇总失败列表，不整体回滚 |
| Excel 中出现同一单多行 | 幂等键去重，只处理第一行 |
| LLM 调用超时/失败 | Mock 降级返回默认值，记录错误日志 |
| Langfuse 上报失败 | 缓存到本地文件，后续重试 |
| 导出时无挂起订单 | 返回空 Excel（含表头，无数据行） |
| 超大 Excel（>1000 行） | 分批处理，每批 100 行，防止超时 |