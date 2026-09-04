# 客诉退赔决策系统 v2 · 实施计划

> 基于已批准的合并设计文档，分步实施计划
> 日期：2026-08-29

---

## 总体路线

```
第1步 ─ 复制项目 + 依赖对齐   (1-2h)
第2步 ─ 沙箱-批量审批落地      (4-6h)  ← 核心功能
第3步 ─ 评测落地               (2-3h)
第4步 ─ 优化改造               (2-3h)
第5步 ─ 合并验收               (2-3h)
```

---

## 第 1 步：复制项目 + 依赖对齐

### 1.1 复制项目目录

```bash
# 复制整个项目
cp -r "D:\桌面\多Agent 协同项目" "D:\d\客诉退赔决策系统-v2"
```

### 1.2 合并依赖

**操作**：在 `backend/requirements.txt` 末尾追加工单5 的依赖

**新增依赖**：
```
langfuse>=2.0.0
openpyxl>=3.1.0
python-docx>=1.0.0
e2b-code-interpreter>=0.1.0
tiktoken>=0.5.0
```

### 1.3 构建沙箱镜像

**Dockerfile.sandbox**（项目根目录）：
```dockerfile
FROM python:3.11-slim
WORKDIR /sandbox
COPY backend/app/sandbox/container_runner.py .
RUN pip install openpyxl==3.1.0 python-docx==1.0.0
ENTRYPOINT ["python", "container_runner.py"]
```

**构建**：
```bash
docker build -t sandbox-python:latest -f Dockerfile.sandbox .
```

### 1.4 验证

```bash
cd D:\d\客诉退赔决策系统-v2
docker compose up -d          # 启动 PostgreSQL + Redis
cd backend
pip install -r requirements.txt
python -m app.main            # 确认应用启动成功
```

---

## 第 2 步：沙箱-批量审批落地

### 2.1 移植 sandbox/ 模块（5 个文件）

从 `D:\桌面\Agent评测\src\sandbox\` 复制到 `backend/app/sandbox/`：

| 文件 | 源路径 | 目标路径 | 修改 |
|------|--------|----------|------|
| adapter.py | Agent评测/src/sandbox/adapter.py | backend/app/sandbox/adapter.py | 无需修改 |
| path_sanitizer.py | Agent评测/src/sandbox/path_sanitizer.py | backend/app/sandbox/path_sanitizer.py | 无需修改 |
| sandbox_manager.py | Agent评测/src/sandbox/sandbox_manager.py | backend/app/sandbox/sandbox_manager.py | 无需修改 |
| office_cli.py | Agent评测/src/sandbox/office_cli.py | backend/app/sandbox/office_cli.py | 无需修改 |
| container_office_cli.py | Agent评测/src/sandbox/container_office_cli.py | backend/app/sandbox/container_office_cli.py | 无需修改 |
| container_runner.py | Agent评测/src/sandbox/container_runner.py | backend/app/sandbox/container_runner.py | 无需修改 |

### 2.2 修改 config.py

在 `backend/app/config.py` 的 `Settings` 类中新增：

```python
# ── 沙箱配置 ──
SANDBOX_MODE: str = "off"  # on=真沙箱, off=宿主机直读
SANDBOX_IMAGE: str = "sandbox-python:latest"
```

### 2.3 新增 batch/ 模块（3 个文件 + 路由）

**文件 1：`backend/app/batch/models.py`**
```python
from pydantic import BaseModel
from typing import Optional, List

class ApprovalRow(BaseModel):
    case_id: str
    action: str  # "同意" / "拒绝"
    comment: Optional[str] = ""

class BatchApprovalResult(BaseModel):
    total: int
    approved: int
    rejected: int
    failed: int
    failures: List[dict] = []

class BatchExportResponse(BaseModel):
    filename: str
    rows: int
```

**文件 2：`backend/app/batch/exporter.py`**
```python
"""导出挂起订单为 Excel"""
import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from app.models import RefundCase

def export_suspended_cases(session) -> tuple[bytes, int]:
    """查库导出 SUSPENDED 状态的工单为 Excel 字节流"""
    cases = session.query(RefundCase).filter(
        RefundCase.status == "SUSPENDED"
    ).order_by(RefundCase.updated_at.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "挂起审批工单"

    # 表头
    headers = ["case_id", "order_id", "金额(元)", "风险分", "舆情等级", "审批动作", "审批意见"]
    header_fill = PatternFill("solid", fgColor="4472C4")
    header_font = Font(color="FFFFFF", bold=True)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font

    # 数据行
    for row, case in enumerate(cases, 2):
        ws.cell(row=row, column=1, value=case.case_id)
        ws.cell(row=row, column=2, value=case.order_id)
        ws.cell(row=row, column=3, value=case.amount_cent / 100)
        ws.cell(row=row, column=4, value=case.fraud_score)
        ws.cell(row=row, column=5, value=case.risk_level or "N/A")
        # 审批动作列留空（主管填写）
        # 审批意见列留空（主管填写）

    # 列宽
    ws.column_dimensions["A"].width = 36  # case_id
    ws.column_dimensions["B"].width = 20  # order_id
    ws.column_dimensions["C"].width = 12  # 金额
    ws.column_dimensions["D"].width = 10  # 风险分
    ws.column_dimensions["E"].width = 12  # 舆情等级
    ws.column_dimensions["F"].width = 14  # 审批动作
    ws.column_dimensions["G"].width = 30  # 审批意见

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue(), len(cases)
```

**文件 3：`backend/app/batch/parser.py`**
```python
"""沙箱解析审批后的 Excel"""
import json
import io
import os
import logging
from typing import List
from app.batch.models import ApprovalRow, BatchApprovalResult
from app.sandbox.sandbox_manager import SandboxLifecycleManager
from app.sandbox.office_cli import OfficeCLI
from app.sandbox.container_office_cli import ContainerOfficeCLI

logger = logging.getLogger(__name__)

def parse_approval_excel(file_content: bytes, sandbox_mode: str = "off") -> List[ApprovalRow]:
    """解析审批后的 Excel 文件

    sandbox_mode="on"  → Docker 沙箱隔离解析
    sandbox_mode="off" → 宿主机直接解析（漏洞基线，仅路径校验）
    """
    if sandbox_mode == "on":
        return _parse_in_sandbox(file_content)
    return _parse_direct(file_content)

def _parse_direct(file_content: bytes) -> List[ApprovalRow]:
    """宿主机直接解析（仅路径校验）"""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(file_content))
    ws = wb.active
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        case_id, _, _, _, _, action, comment = row
        if not case_id or not action:
            continue
        action = str(action).strip()
        if action not in ("同意", "拒绝"):
            logger.warning("跳过无效审批动作: %s", action)
            continue
        rows.append(ApprovalRow(
            case_id=str(case_id),
            action=action,
            comment=str(comment or ""),
        ))
    return rows

def _parse_in_sandbox(file_content: bytes) -> List[ApprovalRow]:
    """Docker 沙箱隔离解析"""
    # 临时写入文件供沙箱挂载
    import tempfile
    import uuid
    sandbox_dir = os.environ.get("SANDBOX_DIR", "/tmp/sandbox_work")
    os.makedirs(sandbox_dir, exist_ok=True)
    filename = f"approval_{uuid.uuid4().hex}.xlsx"
    filepath = os.path.join(sandbox_dir, filename)
    with open(filepath, "wb") as f:
        f.write(file_content)

    try:
        cli = ContainerOfficeCLI(sandbox_dir)
        result = cli.read_excel(filename)
        # 解析返回的 JSON
        data = json.loads(result) if isinstance(result, str) else result
        rows = []
        for item in data:
            if not item.get("case_id") or not item.get("审批动作"):
                continue
            action = str(item["审批动作"]).strip()
            if action not in ("同意", "拒绝"):
                continue
            rows.append(ApprovalRow(
                case_id=str(item["case_id"]),
                action=action,
                comment=str(item.get("审批意见", "") or ""),
            ))
        return rows
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)
```

**文件 4（新增路由）：`backend/app/api/routes/batch.py`**
```python
"""批量审批路由"""
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header
from app.batch.exporter import export_suspended_cases
from app.batch.parser import parse_approval_excel
from app.batch.executor import execute_batch_approval
from app.batch.models import BatchApprovalResult
from app.container import Deps
from app.dependencies import get_deps, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/batch", tags=["batch"])

@router.get("/export")
async def export_suspended(
    deps: Deps = Depends(get_deps),
    user: dict = Depends(get_current_user),
):
    """导出挂起订单为 Excel 文件"""
    from starlette.responses import StreamingResponse
    async with deps.session() as session:
        content, count = await session.run_sync(export_suspended_cases)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=suspended_cases.xlsx",
            "X-Total-Count": str(count),
        },
    )

@router.post("/upload", response_model=BatchApprovalResult)
async def upload_approval(
    file: UploadFile = File(...),
    operator: str = Header(...),
    deps: Deps = Depends(get_deps),
    user: dict = Depends(get_current_user),
):
    """上传审批结果并批量执行"""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "仅支持 .xlsx 文件")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB 限制
        raise HTTPException(400, "文件过大，最大 10MB")

    # 解析
    sandbox_mode = deps.settings.SANDBOX_MODE
    rows = parse_approval_excel(content, sandbox_mode)
    if not rows:
        raise HTTPException(400, "未找到有效审批记录")

    # 逐条执行
    result = await execute_batch_approval(rows, deps, operator)
    return result
```

### 2.4 在 main.py 注册新路由

```python
from app.api.routes import batch as batch_router
app.include_router(batch_router.router)
```

### 2.5 前端新增按钮

在 `frontend/src/pages/Dashboard.tsx` 中新增两个按钮：

```tsx
// 在状态筛选栏旁边添加
<Button type="primary" icon={<DownloadOutlined />} onClick={handleExport}>
  导出挂起订单
</Button>
<Upload
  accept=".xlsx"
  showUploadList={false}
  beforeUpload={handleUploadApproval}
>
  <Button icon={<UploadOutlined />}>上传审批结果</Button>
</Upload>
```

`handleExport` 调用 `GET /api/v1/batch/export` 下载文件。
`handleUploadApproval` 调用 `POST /api/v1/batch/upload` 上传文件并显示结果汇总。

### 2.6 验证清单

- [ ] 导出：有挂起单时导出正确，无挂起单时返回空表头
- [ ] 沙箱解析：SANDBOX_MODE=on 时用 Docker 解析，off 时直读
- [ ] 防重：同一单上传两次，第二次返回已处理
- [ ] 部分失败：A 单已处理、B 单正常，A 跳过 B 成功
- [ ] 汇总：批准/拒绝/失败 数量正确

---

## 第 3 步：评测落地

### 3.1 移植 telemetry/ 模块

从 `D:\桌面\Agent评测\src\telemetry\__init__.py` 复制到 `backend/app/telemetry/__init__.py`。

**注意**：原文件是单文件模块，直接复制即可。目录结构：

```
backend/app/telemetry/
├── __init__.py     # 移植自 Agent评测/src/telemetry/__init__.py
└── langfuse_backend.py  # 从 __init__.py 中拆出（可选，保持单文件也行）
```

### 3.2 新增 eval/ 模块

**文件 1：`backend/app/eval/dataset.py`**

定义 10 个退赔域 Golden Dataset，每个用例包含：
```python
{
    "name": "小额低风险",
    "input": {
        "amount_cent": 12800,
        "complaint_text": "商品有轻微划痕，申请退款",
        "evidence_present": True,
        "ocr_text": "商品照片显示轻微划痕",
        "ocr_confidence": 0.92,
        "risk_flags": {},
    },
    "expected": {
        "decision": "APPROVE",
        "fraud_score_range": (0, 30),
        "sentiment_score_range": (0, 30),
        "risk_level": "LOW",
    },
}
```

**文件 2：`backend/app/eval/judge/base.py`**

```python
from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseJudge(ABC):
    @abstractmethod
    def evaluate(self, case: dict, actual: dict) -> float:
        """评测单条用例，返回 0-100 分数"""
        ...

    def score_to_grade(self, score: float) -> str:
        if score >= 90: return "S"
        if score >= 80: return "A"
        if score >= 70: return "B"
        if score >= 60: return "C"
        return "D"

    def get_dimension_scores(self, case: dict, actual: dict) -> Dict[str, float]:
        """返回三维评分：决策正确性、金额边界安全、理由质量"""
        ...
```

**文件 3：`backend/app/eval/judge/llm_judge.py`**

```python
class LLMJudge(BaseJudge):
    """调用 DeepSeek API 进行三维评分"""
    def evaluate(self, case, actual):
        prompt = f"""作为退赔决策评测专家，请对以下案例进行评分。

案件信息：
{json.dumps(case, ensure_ascii=False)}

系统决策：
{json.dumps(actual, ensure_ascii=False)}

请从三个维度评分（每项 0-100）：
1. 决策正确性（权重 40%）：决策结果是否与期望一致
2. 金额边界安全（权重 30%）：有无误放高风险/误拒低风险
3. 理由质量（权重 30%）：决策依据是否充分可解释

输出 JSON 格式评分。"""
        ...
```

**文件 4：`backend/app/eval/run_eval.py`**

```python
"""评测入口：加载数据集 → 逐条运行 → 评分 → 生成报告"""
async def run_eval(deps, judge_type="mock") -> dict:
    dataset = load_dataset()
    judge = MockJudge() if judge_type == "mock" else LLMJudge()
    for case in dataset:
        state = build_state(case["input"])
        result = await graph.ainvoke(state)
        score = judge.evaluate(case, result)
        ...
    return report
```

### 3.3 配置 Langfuse

在 `config.py` 中新增 Langfuse 配置项：

```python
LANGFUSE_PUBLIC_KEY: str = ""
LANGFUSE_SECRET_KEY: str = ""
LANGFUSE_HOST: str = "https://cloud.langfuse.com"
```

### 3.4 验证清单

- [ ] 10 个 Golden 用例全部可运行
- [ ] 输出三维评分报告（JSON + 可读文本）
- [ ] MockJudge 离线可用，LLMJudge 在 API 可用时自动使用
- [ ] Langfuse Trace 异步上报，失败降级不阻塞

---

## 第 4 步：优化改造

### 4.1 新增 CombinedRiskProvider

**文件：`backend/app/infrastructure/providers/combined_risk.py`**

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class CombinedRiskResult:
    fraud_score: float
    fraud_features: List[str]
    sentiment_score: float
    risk_level: str  # LOW / MEDIUM / HIGH
    reasoning: str

class MockCombinedRiskProvider:
    """Mock 实现，同现有 MockRiskProvider + MockSentimentProvider 逻辑"""
    def assess(self, amount_cent, complaint_text, evidence_text, risk_flags) -> CombinedRiskResult:
        fraud_score = 0
        # 恶意关键词
        malicious = ["欺诈", "虚假", "恶意", "骗"]
        if any(k in complaint_text for k in malicious):
            fraud_score = 85
        elif not evidence_text:
            fraud_score = 60
        elif amount_cent >= 20000:
            fraud_score = 45
        else:
            fraud_score = 20

        sentiment_score = 0
        risk_level = "LOW"
        if "regulatory" in risk_flags or "escalation" in risk_flags:
            sentiment_score = 90
            risk_level = "HIGH"
        elif any(k in complaint_text for k in ["愤怒", "投诉", "威胁"]):
            sentiment_score = 55
            risk_level = "MEDIUM"
        else:
            sentiment_score = 20
            risk_level = "LOW"

        return CombinedRiskResult(
            fraud_score=float(fraud_score),
            fraud_features=[],
            sentiment_score=float(sentiment_score),
            risk_level=risk_level,
            reasoning="Mock analysis",
        )

class LLMCombinedRiskProvider:
    """LLM 实现，单次调用输出双维度"""
    def __init__(self, llm):
        self.llm = llm

    def assess(self, amount_cent, complaint_text, evidence_text, risk_flags) -> CombinedRiskResult:
        prompt = f"""分析以下退款申请，输出 JSON：
金额：{amount_cent/100}元
投诉：{complaint_text[:500]}
凭证：{evidence_text[:500]}
风险标记：{json.dumps(risk_flags)}

{{
  "fraud_score": 0-100,
  "fraud_features": ["..."],
  "sentiment_score": 0-100,
  "risk_level": "LOW|MEDIUM|HIGH",
  "reasoning": "..."
}}"""
        data = self.llm.complete_json(prompt)
        return CombinedRiskResult(**data)
```

### 4.2 新增 merged_risk 节点

**文件：`backend/app/workflow/nodes/merged_risk.py`**

```python
async def run_merged_risk(state, deps):
    """合并风险+舆情分析节点"""
    case_id = state["case_id"]
    try:
        result = await deps.combined_risk.assess(
            state["amount_cent"],
            state.get("complaint_text", ""),
            state.get("ocr_text", ""),
            state.get("risk_flags", {}),
        )
    except Exception as exc:
        deps.record_agent_run(case_id, "MergedRiskAgent", "FAILED", error=str(exc))
        return {"errors": [f"MergedRiskAgent: {exc}"], "fraud_score": 0, "sentiment_score": 0}

    deps.record_agent_run(case_id, "MergedRiskAgent", "SUCCESS",
        output_summary=f"fraud={result.fraud_score} sentiment={result.sentiment_score}")
    deps.publish_event(case_id, {"agent": "MergedRiskAgent", "status": "done",
        "fraud_score": result.fraud_score, "sentiment_score": result.sentiment_score})

    return {
        "fraud_score": result.fraud_score,
        "sentiment_score": result.sentiment_score,
        "risk_level": result.risk_level,
        "risk_factors": result.fraud_features,
    }
```

### 4.3 修改 graph.py

在 `build_graph()` 中：

```python
# 原：fraud → sentiment → decision
# 改：
builder.add_node("merged_risk", run_merged_risk)
builder.add_edge("evidence", "merged_risk")
builder.add_edge("merged_risk", "decision")
```

保留 fraud 和 sentiment 节点定义但注册为可选别名（兼容旧 checkpoint）。

### 4.4 修改 container.py

在 `Deps` 类中新增 `combined_risk` 属性：

```python
@property
def combined_risk(self):
    from app.infrastructure.providers.combined_risk import (
        MockCombinedRiskProvider, LLMCombinedRiskProvider
    )
    provider = self.settings.COMBINED_RISK_PROVIDER
    if provider == "llm":
        return LLMCombinedRiskProvider(self.llm)
    return MockCombinedRiskProvider()
```

### 4.5 验证清单

- [ ] 合并调用后 Token 数下降 ~40%
- [ ] 合并调用后时延下降（单次 LLM vs 两次串行）
- [ ] 并行化后整体时延额外下降 ≥40%（不含 LLM 推理时间）
- [ ] 原 fraud + sentiment 的后向兼容（checkpoint 恢复）
- [ ] 决策结果与优化前一致（diff 测试）

---

## 第 5 步：合并验收

### 5.1 核心场景联调

| 场景 | 操作 | 预期 |
|------|------|------|
| 小额秒退 | 创建 128 元、低风险单 | 直通 APPROVE→COMPLETED |
| 超300元挂起 | 创建 350 元单 | 进入 SUSPENDED，生成 ReviewTask |
| 审批恢复 | 主管审批通过 | 状态变为 COMPLETED |
| 高风险拒绝 | 风险分 0.9 单 | 直接 REJECTED |

### 5.2 沙箱逃逸测试

| 测试 | 输入 | 预期 |
|------|------|------|
| 恶意宏 | Excel 含 VBA 宏 | 沙箱内不执行，解析安全 |
| 公式注入 | 单元格含 `=CMD(...)` | 沙箱内不执行 |
| 路径穿越 | 文件名含 `../` | path_sanitizer 拦截 |
| 超大文件 | 100MB+ Excel | 沙箱内存限制 512m，OOM 安全降级 |
| 空文件 | 0 字节 Excel | 返回友好错误 |

### 5.3 评测报告

```bash
cd backend
python -m app.eval.run_eval --judge llm --output eval/reports/
```

### 5.4 压测

| 场景 | 指标 | 目标 |
|------|------|------|
| 批量审批 100 单 | 总耗时 | < 30s |
| 单次决策 | P95 时延 | < 5s |
| 并发 10 单 | 错误率 | 0% |

---

## 文件创建/修改汇总

| 步骤 | 操作 | 文件 |
|------|------|------|
| 1.2 | 修改 | backend/requirements.txt |
| 1.3 | 新建 | Dockerfile.sandbox |
| 2.1 | 新建 ×6 | backend/app/sandbox/* |
| 2.2 | 修改 | backend/app/config.py |
| 2.3 | 新建 | backend/app/batch/models.py |
| 2.3 | 新建 | backend/app/batch/exporter.py |
| 2.3 | 新建 | backend/app/batch/parser.py |
| 2.3 | 新建 | backend/app/batch/executor.py |
| 2.3 | 新建 | backend/app/api/routes/batch.py |
| 2.4 | 修改 | backend/app/main.py |
| 2.5 | 修改 | frontend/src/pages/Dashboard.tsx |
| 3.1 | 新建 ×2 | backend/app/telemetry/* |
| 3.2 | 新建 | backend/app/eval/dataset.py |
| 3.2 | 新建 | backend/app/eval/judge/base.py |
| 3.2 | 新建 | backend/app/eval/judge/llm_judge.py |
| 3.2 | 新建 | backend/app/eval/run_eval.py |
| 3.2 | 新建 | backend/app/eval/metrics.py |
| 3.3 | 修改 | backend/app/config.py |
| 4.1 | 新建 | backend/app/infrastructure/providers/combined_risk.py |
| 4.2 | 新建 | backend/app/workflow/nodes/merged_risk.py |
| 4.3 | 修改 | backend/app/workflow/graph.py |
| 4.4 | 修改 | backend/app/container.py |

**总计：新建 ~18 个文件，修改 ~6 个文件**