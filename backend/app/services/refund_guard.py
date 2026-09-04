"""退款金额建议与反滥用画像。

金额建议是可解释的确定性规则，不由大模型直接决定；风险画像只提供信号，
最终批准、挂起或拒绝仍由 DecisionPolicy 统一裁决。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import CaseEvidence, RefundCase, ShopOrder, User


SEVERITY_LABELS = {"minor": "轻微", "moderate": "中度", "severe": "严重"}

# 尺码不合适属于标准退换场景，用户可以直接提交，不强制上传图片；
# 质量、破损、少件等事实争议仍需要凭证来保护双方权益。
EVIDENCE_OPTIONAL_REASONS = {"size"}

# 不同问题的补偿基线。尺码不合适、发错商品等通常需要退货，因此建议按可退金额处理；
# 轻微质量瑕疵则优先部分补偿，避免无差别全额退款。
_RECOMMEND_RATES = {
    "damaged": {"minor": 20, "moderate": 60, "severe": 100},
    "quality": {"minor": 15, "moderate": 50, "severe": 100},
    "not_as_described": {"minor": 20, "moderate": 50, "severe": 100},
    "logistics": {"minor": 10, "moderate": 30, "severe": 100},
    "missing": {"minor": 30, "moderate": 60, "severe": 100},
    "other": {"minor": 15, "moderate": 40, "severe": 80},
    "size": {"minor": 100, "moderate": 100, "severe": 100},
    "wrong_item": {"minor": 100, "moderate": 100, "severe": 100},
}


def quote_refund(refundable_cent: int, reason_code: str, issue_severity: str) -> dict:
    """根据可退额度、原因与严重程度计算建议金额。"""
    refundable_cent = max(int(refundable_cent), 0)
    severity = issue_severity if issue_severity in SEVERITY_LABELS else "moderate"
    rates = _RECOMMEND_RATES.get(reason_code, _RECOMMEND_RATES["other"])
    rate = rates[severity]
    recommended = min(refundable_cent, max(1, refundable_cent * rate // 100)) if refundable_cent else 0
    is_partial = recommended < refundable_cent
    if is_partial:
        explanation = f"{SEVERITY_LABELS[severity]}问题建议补偿商品可退金额的 {rate}%"
    else:
        explanation = "该情况建议按当前可退金额处理；实际退款仍需通过订单与凭证核验"
    return {
        "refundable_cent": refundable_cent,
        "refundable_yuan": f"{refundable_cent / 100:.2f}",
        "recommended_amount_cent": recommended,
        "recommended_amount_yuan": f"{recommended / 100:.2f}",
        "recommended_rate": rate,
        "issue_severity": severity,
        "issue_severity_label": SEVERITY_LABELS[severity],
        "is_partial": is_partial,
        "explanation": explanation,
    }


def amount_exceeds_recommendation(requested_cent: int, recommended_cent: int) -> bool:
    """允许少量录入误差，明显超过建议金额时强制人工复核。"""
    tolerance = max(500, int(recommended_cent * 0.10))
    return requested_cent > recommended_cent + tolerance


def customer_refund_profile(db: Session, user_id: int) -> dict:
    """按购物订单计算退款画像，避免用“退款成功数 / 退款申请数”虚高风险。"""
    total_orders = db.query(ShopOrder).filter(ShopOrder.customer_id == user_id).count()
    refunded_orders = (
        db.query(func.count(func.distinct(RefundCase.order_id)))
        .filter(
            RefundCase.user_id == user_id,
            RefundCase.source == "customer_portal",
            RefundCase.refund_status == "EXECUTED",
        )
        .scalar()
        or 0
    )
    rejected_requests = (
        db.query(RefundCase)
        .filter(
            RefundCase.user_id == user_id,
            RefundCase.source == "customer_portal",
            RefundCase.status == "REJECTED",
        )
        .count()
    )
    return {
        "total_orders": total_orders,
        "refunded_orders": int(refunded_orders),
        "rejected_requests": rejected_requests,
        "refund_rate": refunded_orders / total_orders if total_orders else 0.0,
    }


def refresh_customer_refund_profile(db: Session, user: User) -> dict:
    """刷新用户画像字段，供工作流判断和主管端展示使用。"""
    profile = customer_refund_profile(db, user.id)
    user.total_cases = profile["total_orders"]
    user.refund_count = profile["refunded_orders"]
    user.reject_count = profile["rejected_requests"]
    user.refund_rate = profile["refund_rate"]
    db.add(user)
    return profile


def build_anti_abuse_flags(
    db: Session,
    *,
    user: User,
    requested_cent: int,
    refundable_cent: int,
    evidence: list[dict],
) -> dict:
    """生成短期频次、连续高比例申请和凭证复用信号。"""
    now = datetime.now(timezone.utc)
    history = (
        db.query(RefundCase)
        .filter(RefundCase.user_id == user.id, RefundCase.source == "customer_portal")
        .all()
    )
    recent_24h = sum(1 for case in history if case.created_at and case.created_at >= now - timedelta(days=1))
    recent_7d = sum(1 for case in history if case.created_at and case.created_at >= now - timedelta(days=7))
    recent_30d = [case for case in history if case.created_at and case.created_at >= now - timedelta(days=30)]
    requested_ratio = requested_cent / refundable_cent if refundable_cent > 0 else 1.0
    prior_high_ratio = sum(
        1
        for case in recent_30d
        if float((case.risk_flags or {}).get("requested_ratio", 0.0)) >= 0.80
    )

    hashes = {str(item.get("file_hash")) for item in evidence if item.get("file_hash")}
    duplicate_count = 0
    cross_account_reuse = False
    if hashes:
        prior_evidence = db.query(CaseEvidence).filter(CaseEvidence.file_hash.in_(hashes)).all()
        duplicate_count = len(prior_evidence)
        if prior_evidence:
            case_ids = {item.case_id for item in prior_evidence}
            owners = {
                row.user_id
                for row in db.query(RefundCase).filter(RefundCase.case_id.in_(case_ids)).all()
            }
            cross_account_reuse = any(owner != user.id for owner in owners)

    profile = customer_refund_profile(db, user.id)
    return {
        "requested_ratio": round(requested_ratio, 4),
        "recent_refunds_24h": recent_24h,
        "recent_refunds_7d": recent_7d,
        "recent_refunds_30d": len(recent_30d),
        "prior_high_ratio_refunds_30d": prior_high_ratio,
        "refund_velocity_24h": recent_24h >= 4,
        "refund_velocity_7d": recent_7d >= 8,
        "repeated_high_ratio": requested_ratio >= 0.80 and prior_high_ratio >= 2,
        "duplicate_evidence": duplicate_count > 0,
        "duplicate_evidence_count": duplicate_count,
        "cross_account_evidence_reuse": cross_account_reuse,
        "refund_profile_total_orders": profile["total_orders"],
        "refund_profile_refunded_orders": profile["refunded_orders"],
        "refund_profile_rate": round(profile["refund_rate"], 4),
    }
