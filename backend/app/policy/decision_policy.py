"""确定性退款决策规则引擎。

大模型只负责抽取与风险辅助判断，最终 APPROVE / REJECT / HUMAN_REVIEW
由本模块的确定性规则计算，保证可复算、可解释、可审计。
"""
from dataclasses import dataclass
from typing import Optional

from ..config import settings

APPROVE = "APPROVE"
REJECT = "REJECT"
HUMAN_REVIEW = "HUMAN_REVIEW"

# 高风险舆情信号：任一为真即升级人工
HIGH_RISK_FLAGS = (
    "regulatory_escalation",   # 监管转办
    "litigation",              # 诉讼
    "media_exposure",          # 媒体曝光
    "privacy_breach",          # 隐私泄露
    "group_complaint",         # 群体性投诉
)


@dataclass
class DecisionInput:
    amount_cent: int
    ocr_confidence: Optional[float]
    fraud_score: int
    sentiment_score: int
    risk_level: str
    risk_flags: Optional[dict]
    evidence_present: bool

    # 是否已人工修正 OCR
    ocr_corrected: bool = False

    # 订单真实性校验
    is_verified_order: bool = True
    order_verify_error: Optional[str] = None
    verified_order_amount: Optional[int] = None

    # 商品一致性校验
    product_match: bool = True
    product_consistency_risk: str = "LOW"

    # 用户长期退款率（反薅羊毛画像；需与本次高比例申请组合判断）
    refund_rate: float = 0.0


@dataclass
class DecisionResult:
    decision: str
    reason: str


def decide(inp: DecisionInput, thresholds: Optional[dict] = None) -> DecisionResult:
    # 阈值优先级：调用方注入（运行时 DB 覆盖）> 环境变量默认值
    th = thresholds or {}
    amount_thr = th.get("amount_human_review_threshold_cent", settings.amount_human_review_threshold_cent)
    ocr_thr = th.get("ocr_confidence_threshold", settings.ocr_confidence_threshold)
    fraud_reject_thr = th.get("fraud_reject_threshold", settings.fraud_reject_threshold)
    fraud_review_thr = th.get("fraud_review_threshold", settings.fraud_review_threshold)
    refund_rate_review_thr = th.get("refund_rate_review_threshold", settings.refund_rate_review_threshold)
    refund_rate_reject_thr = th.get("refund_rate_reject_threshold", settings.refund_rate_reject_threshold)
    flags = inp.risk_flags or {}

    # 1. 证据不足
    evidence_required = flags.get("evidence_required", True)
    if not inp.evidence_present and evidence_required:
        return DecisionResult(HUMAN_REVIEW, "证据不足，需补充凭证，不生成确定性退赔结论")

    # 2. 订单验证失败 → 转人工
    if not inp.is_verified_order:
        msg = f"订单验证失败: {inp.order_verify_error or '未知错误'}"
        return DecisionResult(HUMAN_REVIEW, msg)

    # 3. 价格偏差超阈值 → 转人工
    price_deviation_thr = th.get("price_deviation_threshold_cent", settings.price_deviation_threshold_cent)
    if inp.verified_order_amount is not None and inp.amount_cent > inp.verified_order_amount + price_deviation_thr:
        return DecisionResult(
            HUMAN_REVIEW,
            f"退款金额 {inp.amount_cent} 分超出订单金额 {inp.verified_order_amount} 分 + 偏差阈值 {price_deviation_thr} 分",
        )

    # 4. 商品不匹配 → 转人工
    if not inp.product_match:
        return DecisionResult(HUMAN_REVIEW, "投诉商品与订单商品不匹配，转人工核实")

    # 5. 退款画像不能单独定罪：历史退款率高且本次又申请 80% 以上才升级。
    if flags.get("ocr_amount_mismatch"):
        amounts = flags.get("ocr_detected_amounts_cent") or []
        return DecisionResult(HUMAN_REVIEW, f"OCR 凭证金额 {amounts} 与申请金额 {inp.amount_cent} 分不一致，转人工核实")
    if flags.get("ocr_order_mismatch"):
        return DecisionResult(HUMAN_REVIEW, "OCR 凭证订单号与申请订单不一致，转人工核实")
    if flags.get("amount_exceeds_recommendation"):
        return DecisionResult(
            HUMAN_REVIEW,
            f"申请金额 {inp.amount_cent} 分明显超过系统建议金额 {flags.get('recommended_amount_cent')} 分，转人工核实",
        )

    # 反薅羊毛强信号先按欺诈分处理：多项叠加可拒绝，单项可疑转人工。
    if inp.fraud_score >= fraud_reject_thr:
        return DecisionResult(REJECT, f"欺诈分 {inp.fraud_score} 达到拒绝阈值 {fraud_reject_thr}")
    if inp.fraud_score >= fraud_review_thr:
        return DecisionResult(HUMAN_REVIEW, f"欺诈分 {inp.fraud_score} 达到复核阈值 {fraud_review_thr}")

    requested_ratio = float(flags.get("requested_ratio", 0.0) or 0.0)
    high_ratio_request = requested_ratio >= 0.80
    if inp.refund_rate >= refund_rate_reject_thr and high_ratio_request:
        return DecisionResult(
            REJECT,
            f"用户长期退款率 {inp.refund_rate:.0%} 且本次申请比例 {requested_ratio:.0%}，疑似职业薅羊毛",
        )
    if inp.refund_rate >= refund_rate_review_thr and high_ratio_request:
        return DecisionResult(
            HUMAN_REVIEW,
            f"用户长期退款率 {inp.refund_rate:.0%} 且本次申请比例 {requested_ratio:.0%}，转人工核实",
        )

    # 6. 金额超阈值 → 必定人工审核
    if inp.amount_cent > amount_thr:
        return DecisionResult(HUMAN_REVIEW, f"金额超过阈值 {amount_thr} 分，转人工审核")

    # 6. 舆情高风险信号
    for flag in HIGH_RISK_FLAGS:
        if flags.get(flag):
            return DecisionResult(HUMAN_REVIEW, f"存在高风险舆情信号: {flag}，升级人工处理")

    # 7. OCR 置信度过低 → 不自动批准（除非已人工修正）
    if inp.evidence_present and (inp.ocr_confidence is None or inp.ocr_confidence < ocr_thr):
        if inp.ocr_corrected:
            pass  # 已人工修正，跳过 OCR 置信度检查
        else:
            return DecisionResult(HUMAN_REVIEW, "OCR 置信度过低，转人工复核")

    # 9. 情绪/舆情等级
    if inp.risk_level == "HIGH":
        return DecisionResult(HUMAN_REVIEW, "舆情风险等级为 HIGH，转人工")

    return DecisionResult(APPROVE, "金额和风险校验通过，自动批准")
