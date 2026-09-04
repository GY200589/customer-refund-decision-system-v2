"""batch 模块数据模型"""
from pydantic import BaseModel, Field
from typing import Optional, List


class ApprovalRow(BaseModel):
    """单条审批记录"""
    case_id: str
    action: str  # "同意" / "拒绝"
    comment: Optional[str] = ""


class BatchApprovalResult(BaseModel):
    """批量审批汇总结果"""
    total: int
    approved: int
    rejected: int
    failed: int
    failures: List[dict] = Field(default_factory=list)


class BatchExportResponse(BaseModel):
    """导出响应"""
    filename: str
    rows: int
