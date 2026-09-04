from typing import Optional, TypedDict


class WorkflowState(TypedDict, total=False):
    case_id: str
    trace_id: str
    user_id: int                      # 申请人 ID，用于反薅羊毛画像查询
    order_id: str
    amount_cent: int
    complaint_text: str
    risk_flags: dict
    evidence: list
    evidence_present: bool
    ocr_text: str
    ocr_confidence: Optional[float]
    ocr_corrected: bool               # 是否已人工修正 OCR
    ocr_amounts_cent: list[int]       # 凭证中识别出的金额
    ocr_amount_match: Optional[bool]  # 有金额时与申请金额是否一致
    ocr_order_match: Optional[bool]   # 有订单号时与申请订单是否一致
    fraud_score: int
    sentiment_score: int
    risk_level: str
    risk_factors: list
    decision: str
    decision_reason: str
    review_comment: str
    refund_ref: str
    errors: list

    # 订单真实性校验
    is_verified_order: bool
    order_verify_error: str
    verified_order_amount: int       # 从订单系统返回的真实订单金额（分）

    # 商品一致性校验
    product_match: bool
    claimed_product: str              # 投诉中提及的商品描述
    purchased_product: str            # 订单中的实际购买商品
    product_consistency_risk: str     # HIGH / MEDIUM / LOW
