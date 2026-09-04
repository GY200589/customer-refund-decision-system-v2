from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    user: dict


class EvidenceIn(BaseModel):
    file_name: str
    file_hash: Optional[str] = None
    file_path: Optional[str] = None


class CaseCreateRequest(BaseModel):
    order_id: str
    amount_cent: int = Field(gt=0, description="退款金额，单位：分，禁止负值")
    currency: str = "CNY"
    complaint_text: str = ""
    risk_flags: dict = Field(default_factory=dict)
    evidence: list[EvidenceIn] = Field(default_factory=list)


class CaseCreateResponse(BaseModel):
    case_id: str
    status: str


class DecisionRequest(BaseModel):
    action: str  # APPROVE | REJECT
    comment: Optional[str] = None


class ThresholdUpdateRequest(BaseModel):
    """运行期阈值覆盖（字段均可选，仅更新提供的键）。"""

    amount_human_review_threshold_cent: Optional[int] = Field(None, gt=0, description="金额转人工阈值（分）")
    ocr_confidence_threshold: Optional[float] = Field(None, ge=0.0, le=1.0, description="OCR 置信度阈值")
    fraud_reject_threshold: Optional[int] = Field(None, ge=0, le=100, description="欺诈分拒绝阈值")
    fraud_review_threshold: Optional[int] = Field(None, ge=0, le=100, description="欺诈分复核阈值")

    # 安全配置（工单6）
    tool_filter_amount_max: Optional[int] = Field(None, gt=0, description="ToolFilter 金额上限（分）")
    critic_rule_enabled: Optional[bool] = Field(None, description="Critic 规则快速路开关")
    critic_llm_enabled: Optional[bool] = Field(None, description="Critic LLM 深度检测开关")
    dlp_enabled: Optional[bool] = Field(None, description="DLP 数据脱敏开关")

    # 价格偏差阈值（订单真实性校验）
    price_deviation_threshold_cent: Optional[int] = Field(None, gt=0, description="价格偏差阈值（分）")

    # 用户长期退款率阈值（与本次高比例申请组合判断）
    refund_rate_review_threshold: Optional[float] = Field(None, ge=0.0, le=1.0, description="退款率复核阈值（0~1）")
    refund_rate_reject_threshold: Optional[float] = Field(None, ge=0.0, le=1.0, description="退款率拒绝阈值（0~1）")


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern="^(agent|supervisor|admin|customer)$")
    display_name: str = Field(default="", max_length=64)


class UserUpdateRequest(BaseModel):
    role: Optional[str] = Field(None, pattern="^(agent|supervisor|admin|customer)$")
    display_name: Optional[str] = Field(None, max_length=64)
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8, max_length=128)


class OcrCorrectionRequest(BaseModel):
    ocr_text: str
    ocr_confidence: Optional[float] = 1.0


class UploadResponse(BaseModel):
    file_name: str
    file_path: str
    mime_type: str
    file_size: int
    # 实时 OCR 预览（上传即识别；OCR 失败不影响上传，字段为 None）
    ocr_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    ocr_fields: Optional[dict] = None


# ── 用户端（男装商城 + 退款 + 智能客服）──────────────────────────

class CustomerOrderItemIn(BaseModel):
    product_id: int
    size: str = Field(min_length=1, max_length=16)
    color: Optional[str] = Field(None, max_length=32)  # 缺省取商品主色
    quantity: int = Field(default=1, ge=1, le=10)


class CustomerOrderCreateRequest(BaseModel):
    items: list[CustomerOrderItemIn] = Field(min_length=1, max_length=20)


class CustomerRefundCreateRequest(BaseModel):
    item_id: Optional[int] = None  # 缺省=整单申请；用户端界面通常按商品明细提交
    amount_cent: Optional[int] = Field(None, gt=0)  # 缺省=采用服务端建议金额
    reason_code: str = "other"
    issue_severity: str = Field(default="moderate", pattern="^(minor|moderate|severe)$")
    description: str = Field(default="", max_length=1000)
    evidence: list[EvidenceIn] = Field(default_factory=list)


class AssistantRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    session_id: Optional[str] = Field(None, max_length=64)
    input_source: str = Field(default="text", pattern="^(text|voice)$")
    # 只有用户在知识库未命中后主动点击“转人工客服”才允许调用外部模型。
    use_model_fallback: bool = False
