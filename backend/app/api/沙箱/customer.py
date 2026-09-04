"""用户端路由（男装商城 + 退款 + 智能客服），仅 customer 角色可访问。

权限铁律（定稿 §6）：
- 全部接口 require_role("customer")；后台接口的角色清单不含 customer；
- 订单/退款/会话严格按本人过滤，他人订单按 404 处理（不泄露存在性）；
- 订单金额由服务端按 Product.price_cent 重算，不信任前端价格（C8）；
- 退款复用 case_service.create_case，幂等/DLP/审计/画像累计全部生效（§4.5）；
- 用户端只返回通俗状态，不暴露 fraud_score/Agent 细节/内部阈值。
"""
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from ...db import get_db
from ...deps import require_role
from ...infrastructure.providers import get_asr_provider
from ...infrastructure.providers.asr import ASRError
from ...models import CaseEvidence, IdempotencyRecord, Product, RefundCase, ShopOrder, ShopOrderItem, User
from ...schemas import AssistantRequest, CustomerOrderCreateRequest, CustomerRefundCreateRequest
from ...services import case_service
from ...services import refund_guard
from ...services.assistant import handle_query
from ...services.catalog import (
    CATEGORY_TREE,
    FRIENDLY_ORDER_STATUS,
    FRIENDLY_STATUS,
    MAIN_CATEGORY_LABELS,
    REASON_CODES,
    REASON_LABELS,
    SUB_CATEGORY_LABELS,
)
from ...services.uploads import MAX_UPLOAD_SIZE, save_upload, validate_uploaded_evidence
from ...services.idempotency import create_key

router = APIRouter()
customer_only = require_role("customer")

# 已占用可退额度的案件状态 / 处理中禁止重复申请的状态
_SETTLED_REFUND_STATUSES = ("APPROVED", "COMPLETED")
_PENDING_REFUND_STATUSES = ("CREATED", "RUNNING", "SUSPENDED")
_RESERVED_REFUND_STATUSES = _SETTLED_REFUND_STATUSES + _PENDING_REFUND_STATUSES


def _serialize_product(p: Product) -> dict:
    return {
        "id": p.id,
        "product_code": p.product_code,
        "name": p.name,
        "main_category": p.main_category,
        "main_category_label": MAIN_CATEGORY_LABELS.get(p.main_category, p.main_category),
        "sub_category": p.sub_category,
        "sub_category_label": SUB_CATEGORY_LABELS.get(p.sub_category, p.sub_category),
        "color": p.color,
        "sizes": p.sizes or [],
        "price_cent": p.price_cent,
        "price_yuan": f"{p.price_cent / 100:.2f}",
        "image_url": p.image_url,
        "fabric": p.fabric,
        "fit_notes": p.fit_notes,
        "description": p.description,
        "is_demo": p.is_demo,
    }


def _order_items(db: Session, order_ids: list[int]) -> dict[int, list[ShopOrderItem]]:
    if not order_ids:
        return {}
    items = db.query(ShopOrderItem).filter(ShopOrderItem.order_id.in_(order_ids)).all()
    grouped: dict[int, list[ShopOrderItem]] = {}
    for it in items:
        grouped.setdefault(it.order_id, []).append(it)
    return grouped


def _serialize_order(
    order: ShopOrder,
    items: list[ShopOrderItem],
    products: dict[int, Product] | None = None,
    user: User | None = None,
) -> dict:
    products = products or {}
    payment_no = f"PAY{order.order_no.removeprefix('SO')}"
    logistics_steps = [
        {"title": "付款成功", "description": "订单已进入仓库处理", "state": "finish"},
        {"title": "仓库出库", "description": "包裹已交给承运商", "state": "finish"},
    ]
    if order.status == "SHIPPED":
        logistics_steps.extend([
            {"title": "运输中", "description": "包裹正在送往收货城市", "state": "process"},
            {"title": "等待签收", "description": "预计 3-5 天送达", "state": "wait"},
        ])
        logistics_current = 2
        logistics_status = "运输中"
    else:
        logistics_steps.append(
            {"title": "已签收", "description": "商品已完成签收，可申请售后", "state": "finish"}
        )
        logistics_current = 2
        logistics_status = "已签收"

    return {
        "id": order.id,
        "order_no": order.order_no,
        "status": order.status,
        "status_label": FRIENDLY_ORDER_STATUS.get(order.status, order.status),
        "total_cent": order.total_cent,
        "total_yuan": f"{order.total_cent / 100:.2f}",
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items": [
            {
                "id": it.id,
                "product_id": it.product_id,
                "name": it.product_name,
                "sub_category": it.sub_category,
                "sub_category_label": SUB_CATEGORY_LABELS.get(it.sub_category, it.sub_category),
                "size": it.size,
                "color": it.color,
                "quantity": it.quantity,
                "unit_price_cent": it.unit_price_cent,
                "unit_price_yuan": f"{it.unit_price_cent / 100:.2f}",
                "line_total_cent": it.unit_price_cent * it.quantity,
                "line_total_yuan": f"{it.unit_price_cent * it.quantity / 100:.2f}",
                "image_url": products.get(it.product_id).image_url if products.get(it.product_id) else None,
            }
            for it in items
        ],
        "pricing": {
            "subtotal_cent": order.total_cent,
            "subtotal_yuan": f"{order.total_cent / 100:.2f}",
            "discount_cent": 0,
            "discount_yuan": "0.00",
            "freight_cent": 0,
            "freight_yuan": "0.00",
            "paid_cent": order.total_cent,
            "paid_yuan": f"{order.total_cent / 100:.2f}",
        },
        "payment": {
            "payment_no": payment_no,
            "method": "在线支付（模拟）",
            "status": "PAID",
            "status_label": "支付成功",
            "is_demo": True,
        },
        "recipient": {
            "name": user.display_name if user else "顾客小李",
            "phone": "138****6621",
            "address": "上海市浦东新区演示路 88 号（演示地址）",
            "is_demo": True,
        },
        "logistics": {
            "carrier": "顺丰速运（模拟）",
            "tracking_no": f"SF{order.order_no[-12:]}",
            "status_label": logistics_status,
            "current": logistics_current,
            "steps": logistics_steps,
            "is_demo": True,
        },
    }


def _refunded_cent(
    db: Session,
    order_no: str,
    order_item_id: int | None = None,
    *,
    reserve_pending: bool = False,
) -> int:
    """统计已退金额；校验可退额度时也预占正在处理的申请，防止重复退款。"""
    statuses = _RESERVED_REFUND_STATUSES if reserve_pending else _SETTLED_REFUND_STATUSES
    query = db.query(RefundCase).filter(
        RefundCase.order_id == order_no,
        RefundCase.source == "customer_portal",
        RefundCase.status.in_(statuses),
    )
    if order_item_id is not None:
        query = query.filter(RefundCase.order_item_id == order_item_id)
    return sum(c.amount_cent for c in query.all())


def _serialize_refund(c: RefundCase) -> dict:
    flags = c.risk_flags or {}
    return {
        "case_id": c.case_id,
        "order_no": c.order_id,
        "product_name": c.product_name,
        "sub_category": c.product_sub_category,
        "amount_cent": c.amount_cent,
        "amount_yuan": f"{c.amount_cent / 100:.2f}",
        "partial_refund": bool(flags.get("partial_refund")),
        "recommended_amount_cent": flags.get("recommended_amount_cent"),
        "recommended_amount_yuan": (
            f"{flags['recommended_amount_cent'] / 100:.2f}"
            if flags.get("recommended_amount_cent") is not None
            else None
        ),
        "issue_severity": flags.get("issue_severity"),
        "issue_severity_label": flags.get("issue_severity_label"),
        "status": c.status,
        "friendly_status": FRIENDLY_STATUS.get(c.status, c.status),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _refund_timeline(c: RefundCase) -> list[dict]:
    """给用户看的退款节点，只描述进度，不返回内部风控与 Agent 信息。"""
    created_at = c.created_at.isoformat() if c.created_at else None
    updated_at = c.updated_at.isoformat() if c.updated_at else created_at
    if c.status in ("REJECTED", "FAILED"):
        title = "审核未通过" if c.status == "REJECTED" else "处理失败"
        description = "申请未通过，请查看原因或联系客服" if c.status == "REJECTED" else "系统处理遇到问题，请联系客服"
        return [
            {"key": "submitted", "title": "已提交", "description": "退款申请已收到", "state": "finish", "at": created_at},
            {"key": "result", "title": title, "description": description, "state": "error", "at": updated_at},
        ]
    if c.status == "COMPLETED":
        return [
            {"key": "submitted", "title": "已提交", "description": "退款申请已收到", "state": "finish", "at": created_at},
            {"key": "review", "title": "资料核对", "description": "订单和凭证已完成核对", "state": "finish", "at": updated_at},
            {"key": "completed", "title": "退款完成", "description": "款项已原路退回", "state": "finish", "at": updated_at},
        ]
    if c.status == "APPROVED":
        return [
            {"key": "submitted", "title": "已提交", "description": "退款申请已收到", "state": "finish", "at": created_at},
            {"key": "review", "title": "审核通过", "description": "正在安排退款", "state": "finish", "at": updated_at},
            {"key": "completed", "title": "退款处理中", "description": "款项将原路退回", "state": "process", "at": None},
        ]
    if c.status == "SUSPENDED":
        return [
            {"key": "submitted", "title": "已提交", "description": "退款申请已收到", "state": "finish", "at": created_at},
            {"key": "review", "title": "人工核对", "description": "需要客服进一步确认，完成后会继续处理", "state": "process", "at": updated_at},
            {"key": "completed", "title": "处理完成", "description": "等待人工核对结束", "state": "wait", "at": None},
        ]
    return [
        {"key": "submitted", "title": "已提交", "description": "退款申请已收到", "state": "finish", "at": created_at},
        {"key": "review", "title": "资料核对", "description": "正在核对订单和凭证", "state": "process", "at": updated_at},
        {"key": "completed", "title": "处理完成", "description": "核对完成后会原路退款", "state": "wait", "at": None},
    ]


def _serialize_refund_detail(db: Session, c: RefundCase) -> dict:
    """退款详情专用返回体：保留用户关心的信息，隐藏内部评分与 Agent 运行数据。"""
    reason = "其他原因"
    description = c.complaint_text or "用户通过用户端提交退款申请"
    if description.startswith("【") and "】" in description:
        end = description.find("】")
        reason = description[1:end] or reason
        description = description[end + 1:] or "用户通过用户端提交退款申请"
    evidences = db.query(CaseEvidence).filter(CaseEvidence.case_id == c.case_id).order_by(CaseEvidence.id).all()
    return {
        **_serialize_refund(c),
        "product_id": c.product_id,
        "order_item_id": c.order_item_id,
        "reason": reason,
        "description": description,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "refund_status": c.refund_status,
        "refund_ref": c.refund_ref,
        "amount_explanation": (
            f"本次为部分退款，商品申请时可退 ¥{(c.risk_flags or {}).get('refundable_cent_at_request', c.amount_cent) / 100:.2f}"
            if (c.risk_flags or {}).get("partial_refund")
            else "本次按申请时可退额度处理"
        ),
        "timeline": _refund_timeline(c),
        "evidence": [
            {"evidence_id": e.id, "file_name": e.file_name, "uploaded_at": e.created_at.isoformat() if e.created_at else None}
            for e in evidences
        ],
        "friendly_explanation": {
            "CREATED": "申请已收到，我们正在核对订单和资料。",
            "RUNNING": "资料正在自动核对，请耐心等待。",
            "SUSPENDED": "系统需要客服再确认一下，确认后会继续处理。",
            "APPROVED": "申请已经通过，款项正在原路退回。",
            "COMPLETED": "退款已完成，到账时间以支付平台为准。",
            "REJECTED": "这次申请没有通过，可以查看订单详情或联系客服。",
            "FAILED": "处理没有完成，请稍后重试或联系客服。",
        }.get(c.status, "申请正在处理中。"),
    }


# ── 类目与商品 ────────────────────────────────────────────

@router.get("/categories")
def get_categories(user: User = Depends(customer_only)):
    return {"tree": CATEGORY_TREE, "reason_codes": [{"value": v, "label": l} for v, l in REASON_CODES]}


@router.get("/products")
def list_products(
    main_category: str = None,
    sub_category: str = None,
    q: str = None,
    page: int = 1,
    page_size: int = 12,
    db: Session = Depends(get_db),
    user: User = Depends(customer_only),
):
    query = db.query(Product).filter(Product.is_active.is_(True))
    if main_category:
        query = query.filter(Product.main_category == main_category)
    if sub_category:
        query = query.filter(Product.sub_category == sub_category)
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    total = query.count()
    page_size = max(1, min(page_size, 96))
    products = (
        query.order_by(Product.id)
        .offset((max(page, 1) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "page": page, "page_size": page_size, "items": [_serialize_product(p) for p in products]}


@router.get("/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_active.is_(True)).first()
    if product is None:
        raise HTTPException(404, "商品不存在")
    return _serialize_product(product)


# ── 模拟下单（服务端算价）──────────────────────────────────

@router.post("/orders", status_code=201)
def create_order(
    body: CustomerOrderCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(customer_only),
):
    product_ids = [it.product_id for it in body.items]
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()}

    prepared = []
    total = 0
    for it in body.items:
        p = products.get(it.product_id)
        if p is None or not p.is_active:
            raise HTTPException(404, f"商品不存在或已下架（product_id={it.product_id}）")
        if p.sizes and it.size not in p.sizes:
            raise HTTPException(422, f"{p.name} 无尺码 {it.size}")
        line = p.price_cent * it.quantity
        total += line
        prepared.append((p, it))

    order = ShopOrder(
        order_no=f"SO{datetime.now(timezone.utc):%Y%m%d%H%M%S}{uuid.uuid4().hex[:4].upper()}",
        customer_id=user.id,
        status="COMPLETED",  # 模拟支付即时完成，不接真实支付
        total_cent=total,  # 服务端按 price_cent 重算，不信任前端（C8）
    )
    db.add(order)
    db.flush()
    for p, it in prepared:
        db.add(
            ShopOrderItem(
                order_id=order.id,
                product_id=p.id,
                product_name=p.name,
                sub_category=p.sub_category,
                size=it.size,
                color=it.color or p.color,
                quantity=it.quantity,
                unit_price_cent=p.price_cent,
            )
        )
    db.commit()

    items = _order_items(db, [order.id]).get(order.id, [])
    return _serialize_order(order, items, products, user)


@router.get("/orders")
def list_orders(db: Session = Depends(get_db), user: User = Depends(customer_only)):
    orders = (
        db.query(ShopOrder)
        .filter(ShopOrder.customer_id == user.id)
        .order_by(ShopOrder.id.desc())
        .all()
    )
    grouped = _order_items(db, [o.id for o in orders])
    all_items = [item for order_items in grouped.values() for item in order_items]
    product_ids = {item.product_id for item in all_items}
    products = {
        product.id: product
        for product in db.query(Product).filter(Product.id.in_(product_ids)).all()
    } if product_ids else {}
    return [_serialize_order(o, grouped.get(o.id, []), products, user) for o in orders]


@router.get("/orders/{order_no}")
def get_order(order_no: str, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    order = db.query(ShopOrder).filter(ShopOrder.order_no == order_no).first()
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    items = _order_items(db, [order.id]).get(order.id, [])
    product_ids = {item.product_id for item in items}
    products = {
        product.id: product
        for product in db.query(Product).filter(Product.id.in_(product_ids)).all()
    } if product_ids else {}
    payload = _serialize_order(order, items, products, user)

    order_refunded = _refunded_cent(db, order_no)
    order_reserved = _refunded_cent(db, order_no, reserve_pending=True)
    payload["refunded_yuan"] = f"{order_refunded / 100:.2f}"
    payload["refundable_cent"] = max(order.total_cent - order_reserved, 0)
    payload["refundable_yuan"] = f"{payload['refundable_cent'] / 100:.2f}"
    for item_view in payload["items"]:
        reserved = _refunded_cent(db, order_no, order_item_id=item_view["id"], reserve_pending=True)
        item_view["refundable_cent"] = max(item_view["unit_price_cent"] * item_view["quantity"] - reserved, 0)
        item_view["refundable_yuan"] = f"{item_view['refundable_cent'] / 100:.2f}"
        item_view["has_active_refund"] = (
            db.query(RefundCase)
            .filter(
                RefundCase.order_id == order_no,
                RefundCase.order_item_id == item_view["id"],
                RefundCase.source == "customer_portal",
                RefundCase.status.in_(_PENDING_REFUND_STATUSES),
            )
            .first()
            is not None
        )
    payload["has_active_refund"] = (
        db.query(RefundCase)
        .filter(
            RefundCase.order_id == order_no,
            RefundCase.source == "customer_portal",
            RefundCase.status.in_(_PENDING_REFUND_STATUSES),
        )
        .first()
        is not None
    )
    return payload


# ── 退款（复用现有案件创建服务与多 Agent 决策链）─────────────


@router.get("/orders/{order_no}/refund-quote")
def get_refund_quote(
    order_no: str,
    item_id: int,
    reason_code: str = "other",
    issue_severity: str = "moderate",
    db: Session = Depends(get_db),
    user: User = Depends(customer_only),
):
    """返回服务端计算的建议退款金额，前端只负责展示，提交时会再次计算。"""
    order = db.query(ShopOrder).filter(ShopOrder.order_no == order_no).first()
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    item = (
        db.query(ShopOrderItem)
        .filter(ShopOrderItem.id == item_id, ShopOrderItem.order_id == order.id)
        .first()
    )
    if item is None:
        raise HTTPException(404, "订单中不存在该商品明细")
    if reason_code not in REASON_LABELS:
        raise HTTPException(422, "退款原因不在支持范围内")
    refundable = item.unit_price_cent * item.quantity - _refunded_cent(
        db, order_no, item.id, reserve_pending=True
    )
    if refundable <= 0:
        raise HTTPException(409, "该商品已无可退金额")
    return refund_guard.quote_refund(refundable, reason_code, issue_severity)

@router.post("/orders/{order_no}/refund", status_code=201)
def create_refund(
    order_no: str,
    body: CustomerRefundCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(customer_only),
    idempotency_key: str = Header(None, alias="X-Idempotency-Key"),
):
    order = db.query(ShopOrder).filter(ShopOrder.order_no == order_no).first()
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")

    # 相同幂等键的重复点击必须抵达共享建案服务，由它校验请求哈希并复用结果。
    existing_idempotency = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.key == create_key(user.id, idempotency_key))
        .first()
        if idempotency_key
        else None
    )
    is_idempotent_replay = existing_idempotency is not None

    item: ShopOrderItem | None = None
    if body.item_id is not None:
        item = (
            db.query(ShopOrderItem)
            .filter(ShopOrderItem.id == body.item_id, ShopOrderItem.order_id == order.id)
            .first()
        )
        if item is None:
            raise HTTPException(404, "订单中不存在该商品明细")
        if not is_idempotent_replay and (
            db.query(RefundCase)
            .filter(
                RefundCase.order_item_id == item.id,
                RefundCase.source == "customer_portal",
                RefundCase.status.in_(_PENDING_REFUND_STATUSES),
            )
            .first()
        ):
            raise HTTPException(409, "该商品已有正在处理的退款申请")
        refundable = item.unit_price_cent * item.quantity - _refunded_cent(
            db, order_no, item.id, reserve_pending=not is_idempotent_replay
        )
    else:
        if not is_idempotent_replay and (
            db.query(RefundCase)
            .filter(
                RefundCase.order_id == order_no,
                RefundCase.source == "customer_portal",
                RefundCase.status.in_(_PENDING_REFUND_STATUSES),
            )
            .first()
        ):
            raise HTTPException(409, "该订单已有正在处理的退款申请")
        refundable = order.total_cent - _refunded_cent(
            db, order_no, reserve_pending=not is_idempotent_replay
        )
        # 单商品整单退款也携带商品信息，便于客服详情、商品一致性校验与审计。
        order_items = _order_items(db, [order.id]).get(order.id, [])
        if len(order_items) == 1:
            item = order_items[0]

    if refundable <= 0:
        raise HTTPException(409, "该订单/商品已无可退金额")
    if body.reason_code not in REASON_LABELS:
        raise HTTPException(422, "退款原因不在支持范围内")
    quote = refund_guard.quote_refund(refundable, body.reason_code, body.issue_severity)
    amount = body.amount_cent if body.amount_cent is not None else quote["recommended_amount_cent"]
    if amount > refundable:
        raise HTTPException(422, f"退款金额 {amount} 分超过可退金额 {refundable} 分")

    evidence_payload = validate_uploaded_evidence(
        [e.model_dump() for e in body.evidence], user.id
    ) if body.evidence else []
    anti_abuse_flags = None
    if existing_idempotency:
        try:
            prior_case_id = json.loads(existing_idempotency.response_body or "{}").get("case_id")
            prior_case = db.query(RefundCase).filter(RefundCase.case_id == prior_case_id).first()
            anti_abuse_flags = (prior_case.risk_flags or {}).get("application_risk_snapshot") if prior_case else None
        except (TypeError, ValueError):
            anti_abuse_flags = None
    if not isinstance(anti_abuse_flags, dict):
        anti_abuse_flags = refund_guard.build_anti_abuse_flags(
            db,
            user=user,
            requested_cent=amount,
            refundable_cent=refundable,
            evidence=evidence_payload,
        )
    risk_flags = {
        "reason_code": body.reason_code,
        "evidence_required": body.reason_code not in refund_guard.EVIDENCE_OPTIONAL_REASONS,
        "issue_severity": quote["issue_severity"],
        "issue_severity_label": quote["issue_severity_label"],
        "refundable_cent_at_request": refundable,
        "recommended_amount_cent": quote["recommended_amount_cent"],
        "recommended_rate": quote["recommended_rate"],
        "partial_refund": amount < refundable,
        "amount_exceeds_recommendation": refund_guard.amount_exceeds_recommendation(
            amount, quote["recommended_amount_cent"]
        ),
        **anti_abuse_flags,
        # 幂等重放使用创建时画像，避免“首个请求本身”改变第二次请求哈希。
        "application_risk_snapshot": anti_abuse_flags,
    }

    reason_label = REASON_LABELS.get(body.reason_code, "其他")
    complaint_text = f"【{reason_label}】{body.description}" if body.description else f"【{reason_label}】用户通过用户端发起退款申请"

    product = None
    if item is not None:
        product = {
            "product_id": item.product_id,
            "product_name": item.product_name,
            "product_sub_category": item.sub_category,
        }

    # 单商品整单退款也绑定真实明细 ID。这样同一商品再次购买时，两个订单的售后记录完全隔离。
    effective_item_id = body.item_id if body.item_id is not None else (item.id if item is not None else None)
    resp = case_service.create_case(
        db,
        redis_client=request.app.state.redis,
        user=user,
        order_id=order_no,
        amount_cent=amount,
        complaint_text=complaint_text,
        risk_flags=risk_flags,
        evidence=evidence_payload,
        idempotency_key=idempotency_key,
        source="customer_portal",
        product=product,
        order_item_id=effective_item_id,
    )

    case = db.query(RefundCase).filter(RefundCase.case_id == resp["case_id"]).first()
    return {
        **resp,
        "order_no": order_no,
        "amount_cent": amount,
        "amount_yuan": f"{amount / 100:.2f}",
        "recommended_amount_cent": quote["recommended_amount_cent"],
        "recommended_amount_yuan": quote["recommended_amount_yuan"],
        "partial_refund": amount < refundable,
        "needs_manual_review": risk_flags["amount_exceeds_recommendation"],
        "friendly_status": FRIENDLY_STATUS.get(case.status, case.status) if case else "正在核对资料",
    }


@router.get("/refunds")
def list_my_refunds(db: Session = Depends(get_db), user: User = Depends(customer_only)):
    """本人退款案件，通俗状态展示（不暴露风险分与 Agent 细节）。"""
    cases = (
        db.query(RefundCase)
        .filter(RefundCase.user_id == user.id, RefundCase.source == "customer_portal")
        .order_by(RefundCase.id.desc())
        .all()
    )
    return [_serialize_refund(c) for c in cases]


@router.get("/refunds/{case_id}")
def get_my_refund_detail(case_id: str, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    """退款详情：严格限制为当前用户从用户端提交的案件。"""
    case = (
        db.query(RefundCase)
        .filter(
            RefundCase.case_id == case_id,
            RefundCase.user_id == user.id,
            RefundCase.source == "customer_portal",
        )
        .first()
    )
    if case is None:
        raise HTTPException(404, "退款记录不存在")
    return _serialize_refund_detail(db, case)


# ── 凭证上传 / 智能客服 / 语音 ──────────────────────────────

@router.post("/uploads", status_code=201)
def upload_evidence(
    file: UploadFile = File(...),
    amount_cent: int = 0,
    request: Request = None,
    db: Session = Depends(get_db),
    user: User = Depends(customer_only),
):
    """用户端凭证上传：保存后给出 OCR 预览，正式决策时仍会再次核验。"""
    saved = save_upload(file, user.id)
    if amount_cent <= 0 or request is None:
        return saved
    try:
        ocr = request.app.state.deps.ocr.extract(
            saved["file_name"], saved["file_path"], saved["file_hash"], amount_cent
        )
        detected = ocr.fields.get("amount_cent")
        if detected is None and ocr.fields.get("amount") is not None:
            detected = round(float(ocr.fields["amount"]) * 100)
        tolerance = max(100, int(amount_cent * 0.05))
        return {
            **saved,
            "ocr_text": ocr.text,
            "ocr_confidence": ocr.overall_confidence,
            "ocr_fields": ocr.fields,
            "ocr_amount_match": (
                abs(int(detected) - amount_cent) <= tolerance if detected is not None else None
            ),
        }
    except Exception:  # noqa: BLE001  OCR 失败不影响凭证上传
        return {**saved, "ocr_text": None, "ocr_confidence": None, "ocr_fields": None, "ocr_amount_match": None}


@router.post("/assistant")
def assistant(
    body: AssistantRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(customer_only),
):
    """咨询主入口：文字与语音转写共用同一意图识别 + RAG 流程（定稿 §4.6）。"""
    session_id = body.session_id or f"s-{user.id}-{uuid.uuid4().hex[:8]}"
    return handle_query(
        db,
        user,
        body.text,
        session_id,
        body.input_source,
        use_model_fallback=body.use_model_fallback,
        security=request.app.state.deps.security,
    )


@router.post("/voice/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...),
    user: User = Depends(customer_only),
):
    """语音转文字（定稿 §4.8）：真实 ASR Provider；未配置/失败返回 503，文字输入始终可用。"""
    audio = await file.read()
    if len(audio) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, f"音频过大，最大 {MAX_UPLOAD_SIZE // 1024 // 1024}MB")
    provider = get_asr_provider()
    try:
        result = provider.transcribe(audio, file.content_type or "audio/webm")
    except ASRError as exc:
        raise HTTPException(503, f"语音服务不可用：{exc}")
    return {**result, "input_source": "voice"}
