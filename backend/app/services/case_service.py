"""案件创建服务：客服后台与用户端退款共用的唯一建案入口。

定稿 §4.5 硬约束：用户端退款不得复制决策逻辑。所有来源（客服 console /
用户端 portal）统一走本函数，幂等、DLP、审计、用户画像累计、Stream 投递
全部在此生效；差异仅体现在 source 与商品扩展字段上。
"""
import json

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import AuditLog, CaseEvidence, IdempotencyRecord, RefundCase, User
from .idempotency import compute_request_hash, create_key
from .refund_guard import refresh_customer_refund_profile


def create_case(
    db: Session,
    *,
    redis_client,
    user: User,
    order_id: str,
    amount_cent: int,
    currency: str = "CNY",
    complaint_text: str = "",
    risk_flags: dict | None = None,
    evidence: list[dict] | None = None,
    idempotency_key: str = "",
    source: str = "agent_console",
    product: dict | None = None,
    order_item_id: int | None = None,
) -> dict:
    """创建退款案件并投递决策流。

    - source: agent_console（客服后台）/ customer_portal（用户端退款）
    - product: 可选 {"product_id","product_name","product_sub_category"}，用户端案件携带
    - order_item_id: 用户端部分退款关联的 shop_order_items.id；整单为 None
    """
    if not idempotency_key:
        raise HTTPException(400, "缺少 X-Idempotency-Key")

    risk_flags = risk_flags or {}
    evidence = evidence or []

    # 幂等哈希覆盖全部业务字段：相同 key 但来源/商品/金额不同 → 422
    request_payload = {
        "order_id": order_id,
        "amount_cent": amount_cent,
        "currency": currency,
        "complaint_text": complaint_text,
        "risk_flags": risk_flags,
        "evidence": evidence,
        "source": source,
        "product": product or {},
        "order_item_id": order_item_id,
    }
    request_hash = compute_request_hash(request_payload)
    idem_key = create_key(user.id, idempotency_key)

    existing = db.query(IdempotencyRecord).filter(IdempotencyRecord.key == idem_key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(422, "相同幂等键但请求体不一致")
        return json.loads(existing.response_body or "{}")

    # DLP 入站脱敏：投诉文本中的敏感信息脱敏后再存储
    from ..security import SecurityProvider  # 局部导入避免循环依赖

    sanitized_text = SecurityProvider().sanitize(complaint_text) if complaint_text else ""

    case = RefundCase(
        order_id=order_id,
        user_id=user.id,
        amount_cent=amount_cent,
        currency=currency,
        complaint_text=sanitized_text,
        risk_flags=risk_flags,
        status="CREATED",
        source=source,
        order_item_id=order_item_id,
        **({"product_id": product["product_id"],
            "product_name": product["product_name"],
            "product_sub_category": product["product_sub_category"]} if product else {}),
    )
    db.add(case)
    db.flush()  # 获取 case_id / trace_id

    # 用户端退款率按“已退款订单 / 购物订单”计算；后台案件保留原案件画像口径。
    if source == "customer_portal" and user.role == "customer":
        refresh_customer_refund_profile(db, user)
    else:
        user.total_cases += 1
        user.refund_rate = user.refund_count / user.total_cases if user.total_cases > 0 else 0.0
        db.add(user)

    for ev in evidence:
        db.add(
            CaseEvidence(
                case_id=case.case_id,
                file_name=ev.get("file_name", ""),
                file_hash=ev.get("file_hash"),
                file_path=ev.get("file_path"),
            )
        )

    db.add(
        AuditLog(
            case_id=case.case_id,
            actor_id=user.id,
            action="case:created",
            after_value={
                "amount_cent": amount_cent,
                "order_id": order_id,
                "source": source,
                **({"product_name": product["product_name"]} if product else {}),
            },
        )
    )
    if source == "customer_portal" and risk_flags:
        db.add(
            AuditLog(
                case_id=case.case_id,
                actor_id=None,
                action="refund:guard_evaluated",
                after_value={
                    "requested_amount_cent": amount_cent,
                    "refundable_cent": risk_flags.get("refundable_cent_at_request"),
                    "recommended_amount_cent": risk_flags.get("recommended_amount_cent"),
                    "issue_severity": risk_flags.get("issue_severity"),
                    "amount_exceeds_recommendation": risk_flags.get("amount_exceeds_recommendation"),
                    "anti_abuse_signals": {
                        key: risk_flags.get(key)
                        for key in (
                            "refund_velocity_24h",
                            "refund_velocity_7d",
                            "repeated_high_ratio",
                            "duplicate_evidence",
                            "cross_account_evidence_reuse",
                        )
                    },
                },
            )
        )

    resp = {"case_id": case.case_id, "status": "CREATED"}
    db.add(
        IdempotencyRecord(
            key=idem_key,
            request_hash=request_hash,
            response_body=json.dumps(resp, ensure_ascii=False),
            status_code=201,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(IdempotencyRecord).filter(IdempotencyRecord.key == idem_key).first()
        if existing and existing.request_hash != request_hash:
            raise HTTPException(422, "相同幂等键但请求体不一致")
        if existing:
            return json.loads(existing.response_body or "{}")
        raise

    from ..infrastructure import streams

    streams.publish_case(redis_client, case.case_id, case.trace_id)
    return resp
