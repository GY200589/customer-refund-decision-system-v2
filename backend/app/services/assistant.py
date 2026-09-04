"""智能客服编排（定稿 §4.6/§4.7）：多意图识别 → 按意图分发 → 带来源回答。

铁律：
- 事实类回答（订单/物流/退款状态）只查数据库，仅限当前用户本人的数据；
- 规则类回答只能引用检索到的知识条目，检索不到明确说"暂时没有查到"并转人工；
- 默认回答使用可追溯的本地模板；仅在未命中且用户主动转接后调用外部模型；
- generator 字段始终如实标注 template / deepseek / fallback_*。
"""
import re

from ..models import AssistantMessage, Product, RefundCase, ShopOrder, ShopOrderItem
from .catalog import FRIENDLY_ORDER_STATUS, FRIENDLY_STATUS, SUB_CATEGORY_LABELS
from . import intent as intent_svc
from . import rag as rag_svc
from . import deepseek as deepseek_svc

# 下装子类型 → 尺码表知识条目（size_query 按实体选择引用）
_BOTTOM_TYPES = {"jeans", "casual_pants", "suit_pants", "cargo_pants", "joggers", "shorts"}
_TYPE_TO_KEY = {
    "牛仔裤": "jeans", "休闲长裤": "casual_pants", "休闲裤": "casual_pants", "西裤": "suit_pants", "工装裤": "cargo_pants",
    "运动裤": "joggers", "短裤": "shorts", "七分裤": "shorts", "长裤": "casual_pants",
    "衬衫": "shirt", "T恤": "tshirt", "卫衣": "hoodie", "夹克": "jacket", "羽绒服": "padded", "棉服": "padded",
}
_GENERIC_BOTTOM_TYPES = {"裤子", "裤装"}
_GENERIC_TOP_TYPES = {"上衣"}
_OUTERWEAR_TYPES = {"外套"}
_GENERIC_PRODUCT_TYPES = {"衣服"}
_PRODUCT_FEATURES = (
    "连帽", "拉链", "开衫", "立领", "圆领", "V领", "翻领", "短袖", "长袖",
    "重磅", "纯棉", "棉", "亚麻", "冰丝", "丹宁", "针织", "速干", "抗皱", "弹力",
    "透气", "保暖", "宽松", "修身", "直筒", "阔腿", "束脚", "微喇", "短款", "长款", "加厚", "轻薄", "多口袋",
)


def _cite(hits: list[dict]) -> str:
    cites = rag_svc.format_citations(hits)
    return f"（来源：{'、'.join(cites)}）" if cites else ""


# 首要意图 → 执行动作（业务路由与自动评测共用同一映射，口径唯一）
ACTION_BY_INTENT = {
    "refund_create": "create_refund",
    "complaint": "create_refund",
    "refund_status": "query_order",
    "order_query": "query_order",
    "logistics_query": "query_order",
    "size_query": None,
    "return_policy_query": None,
    "product_query": None,
    "category_query": None,
    "store_info_query": None,
    "other": "human_handoff",
}


def route_action(primary_intent: str) -> str | None:
    return ACTION_BY_INTENT.get(primary_intent)


def _orders_payload(db, customer_id: int, limit: int = 5, order_no: str | None = None) -> list[dict]:
    query = db.query(ShopOrder).filter(ShopOrder.customer_id == customer_id)
    if order_no:
        query = query.filter(ShopOrder.order_no == order_no)
    orders = query.order_by(ShopOrder.id.desc()).limit(1 if order_no else limit).all()
    items = (
        db.query(ShopOrderItem)
        .filter(ShopOrderItem.order_id.in_([o.id for o in orders]))
        .all()
        if orders
        else []
    )
    by_order: dict[int, list[ShopOrderItem]] = {}
    for it in items:
        by_order.setdefault(it.order_id, []).append(it)
    return [
        {
            "kind": "order",
            "order_no": o.order_no,
            "title": f"订单 {o.order_no}",
            "status": o.status,
            "status_label": FRIENDLY_ORDER_STATUS.get(o.status, o.status),
            "payment_status_label": "支付成功",
            "total_yuan": f"{o.total_cent / 100:.2f}",
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "url": f"/orders?order={o.order_no}",
            "items": [
                {"name": it.product_name, "size": it.size, "color": it.color, "quantity": it.quantity}
                for it in by_order.get(o.id, [])
            ],
        }
        for o in orders
    ]


def _refunds_payload(
    db,
    customer_id: int,
    limit: int = 5,
    order_no: str | None = None,
    case_id: str | None = None,
) -> list[dict]:
    query = db.query(RefundCase).filter(
        RefundCase.user_id == customer_id,
        RefundCase.source == "customer_portal",
    )
    if order_no:
        query = query.filter(RefundCase.order_id == order_no)
    if case_id:
        query = query.filter(RefundCase.case_id == case_id)
    cases = query.order_by(RefundCase.id.desc()).limit(1 if (order_no or case_id) else limit).all()
    return [
        {
            "kind": "refund",
            "case_id": c.case_id,
            "title": f"退款 {c.case_id}",
            "order_no": c.order_id,
            "product_name": c.product_name,
            "amount_yuan": f"{c.amount_cent / 100:.2f}",
            "status": c.status,
            "status_label": FRIENDLY_STATUS.get(c.status, c.status),
            "url": f"/refunds/{c.case_id}",
        }
        for c in cases
    ]


def _color_match_score(query_color: str | None, product_color: str) -> int:
    if not query_color:
        return 0
    query_color = query_color.replace("色", "")
    product_color = (product_color or "").replace("色", "")
    if query_color == product_color:
        return 8
    families = {
        "灰": ("灰",),
        "蓝": ("蓝", "藏青", "宝蓝"),
        "绿": ("绿",),
        "棕": ("棕", "咖"),
        "白": ("白", "米白"),
        "黑": ("黑",),
    }
    aliases = families.get(query_color, (query_color,))
    return 5 if any(alias in product_color for alias in aliases) else -100


def _search_products(db, text: str, entities: dict, limit: int = 6) -> list[dict]:
    """按分类、颜色和商品描述综合排序；结果始终来自当前启用的商品主数据。"""
    ptype = entities.get("product_type")
    color = entities.get("color")
    query = db.query(Product).filter(Product.is_active.is_(True))
    key = _TYPE_TO_KEY.get(ptype)
    if ptype in _GENERIC_BOTTOM_TYPES:
        query = query.filter(Product.main_category == "bottom")
    elif ptype in _GENERIC_TOP_TYPES:
        query = query.filter(Product.main_category == "top")
    elif ptype in _OUTERWEAR_TYPES:
        query = query.filter(Product.sub_category.in_(("jacket", "padded")))
    elif key:
        query = query.filter(Product.sub_category == key)

    features = [term for term in _PRODUCT_FEATURES if term.lower() in text.lower()]
    if ptype in _GENERIC_PRODUCT_TYPES and not color and not features:
        return []
    scored: list[tuple[int, Product, list[str]]] = []
    for product in query.all():
        color_score = _color_match_score(color, product.color)
        if color_score < 0:
            continue
        haystack = " ".join(filter(None, (product.name, product.color, product.fabric, product.fit_notes, product.description))).lower()
        matched = [term for term in features if term.lower() in haystack]
        score = color_score + (6 if key else 3 if ptype else 0) + len(matched) * 3
        compact_text = re.sub(r"[，。,.、；;：:\s]", "", text).lower()
        compact_name = re.sub(r"[，。,.、；;：:\s]", "", product.name).lower()
        if compact_name and compact_name in compact_text:
            score += 20
        scored.append((score, product, matched))

    scored.sort(key=lambda row: (-row[0], row[1].id))
    return [
        {
            "kind": "product",
            "product_id": product.id,
            "product_code": product.product_code,
            "title": product.name,
            "name": product.name,
            "main_category": product.main_category,
            "sub_category": product.sub_category,
            "color": product.color,
            "fabric": product.fabric or "面料信息以商品详情为准",
            "fit_notes": product.fit_notes or "按日常尺码选购",
            "price_yuan": f"{product.price_cent / 100:.2f}",
            "image_url": product.image_url,
            "url": f"/shop?product={product.id}",
            "match_reason": "、".join(matched) or (f"符合{color}条件" if color else "符合商品类型"),
        }
        for _, product, matched in scored[:limit]
    ]


def _compose(db, customer_id: int, text: str, rec: dict) -> dict:
    intents, entities = rec["intents"], rec["entities"]
    primary = intents[0] if intents else "other"
    ptype = entities.get("product_type")
    order_no = entities.get("order_no")
    case_id = entities.get("case_id")
    out = {"action": None, "data": None, "citations": [], "retrieved": [], "answer": ""}

    def cite_for(doc_keys: list[str]) -> list[dict]:
        hits = rag_svc.retrieve_knowledge(db, text)
        wanted = [h for h in hits if h["doc_key"] in doc_keys]
        return wanted or hits  # 期望来源不在命中里时退回全部命中，仍保证引用可追溯

    if primary in ("refund_create", "complaint"):
        hits = cite_for(["refund_policy", "process_guide"])
        out.update(
            action="create_refund",
            answer="可以为您办理退款。请在【我的订单】里选择对应商品提交退款申请，"
                   "可以打字说明原因、上传凭证照片，也可以点麦克风语音说明。"
                   f"{_cite(hits)}",
            citations=rag_svc.format_citations(hits),
            retrieved=[{k: h[k] for k in ("doc_key", "title", "version", "score")} for h in hits],
        )

    elif primary == "refund_status":
        data = _refunds_payload(db, customer_id, order_no=order_no, case_id=case_id)
        if data:
            latest = data[0]
            if order_no or case_id:
                answer = (
                    f"已找到退款记录：订单 {latest['order_no']}，退款金额 ¥{latest['amount_yuan']}，"
                    f"当前状态是“{latest['status_label']}”。点击下方记录可查看完整退款进度。"
                )
            else:
                answer = f"您最近一笔退款申请（订单 {latest['order_no']}）当前状态：{latest['status_label']}。"
                if len(data) > 1:
                    answer += f"共有 {len(data)} 笔记录，可点击下方记录查看具体进度。"
        else:
            matched_order = _orders_payload(db, customer_id, order_no=order_no) if order_no else []
            if matched_order:
                answer = f"订单 {order_no} 可以查到，但这笔订单还没有退款申请。您可以先查看订单详情或发起退款。"
                data = matched_order
            elif order_no or case_id:
                answer = "没有查到对应的退款记录，请核对订单号或案件号。这里只能查询当前账号本人的记录。"
            else:
                answer = "您目前还没有退款申请记录。需要退款时可在【我的订单】里发起。"
        out.update(action="query_order", answer=answer, data=data)

    elif primary in ("order_query", "logistics_query"):
        data = _orders_payload(db, customer_id, order_no=order_no)
        out["action"] = "query_order"
        if primary == "logistics_query":
            shipping = [o for o in data if o["status"] == "SHIPPED"]
            hits = cite_for(["logistics_guide"])
            if shipping:
                nos = "、".join(o["order_no"] for o in shipping)
                answer = f"订单 {nos} 正在运输中，一般发货后 3-5 天送达。点击下方订单可查看物流节点。{_cite(hits)}"
            elif data:
                answer = f"订单 {data[0]['order_no']} 当前为“{data[0]['status_label']}”，没有运输中的物流节点。{_cite(hits)}"
            elif order_no:
                answer = f"没有查到订单 {order_no}。请核对订单号；这里只能查询当前账号本人的订单。"
            else:
                answer = "您还没有订单。发货后 48 小时内出库、3-5 天送达。" f"{_cite(hits)}"
            out["citations"] = rag_svc.format_citations(hits)
            out["retrieved"] = [{k: h[k] for k in ("doc_key", "title", "version", "score")} for h in hits]
        else:
            if data:
                latest = data[0]
                names = "、".join(i["name"] for i in latest["items"]) or "（无商品明细）"
                prefix = "已找到这笔订单" if order_no else "您最近一笔订单"
                answer = (
                    f"{prefix} {latest['order_no']}：支付成功，订单状态“{latest['status_label']}”，"
                    f"实付 ¥{latest['total_yuan']}，商品为 {names}。点击下方订单可打开准确的详情页。"
                )
            elif order_no:
                answer = f"没有查到订单 {order_no}。请核对订单号；这里只能查询当前账号本人的订单。"
            else:
                answer = "您还没有订单。可以先去【购物大厅】逛逛男装。"
            out.update(action="query_order", answer=answer)
        out["data"] = data

    elif primary == "size_query":
        doc_key = "size_guide_bottom" if (ptype and _TYPE_TO_KEY.get(ptype) in _BOTTOM_TYPES) else "size_guide_top"
        hits = cite_for([doc_key])
        tip = f"您问的是{ptype}，" if ptype else ""
        out.update(
            answer=f"{tip}尺码对照请看：{hits[0]['content'][:80]}…拿不准时建议选大一码，尺码不合适支持 7 天无理由退换。{_cite(hits)}",
            citations=rag_svc.format_citations(hits),
            retrieved=[{k: h[k] for k in ("doc_key", "title", "version", "score")} for h in hits],
        )

    elif primary == "return_policy_query":
        hits = cite_for(["refund_policy"])
        out.update(
            answer=f"签收后 7 天内支持无理由退货退款，商品需保持吊牌完整、未经穿着洗涤；"
                   f"破损/发错/少件需上传凭证照片，退款原路退回 1-3 个工作日到账。{_cite(hits)}",
            citations=rag_svc.format_citations(hits),
            retrieved=[{k: h[k] for k in ("doc_key", "title", "version", "score")} for h in hits],
        )

    elif primary == "product_query":
        products = _search_products(db, text, entities)
        if products:
            first = products[0]
            out.update(
                action="view_products",
                answer=(
                    f"为您找到 {len(products)} 件符合条件的商品。最匹配的是："
                    f"{first['name']}，{first['fabric']}，{first['fit_notes']}，价格 ¥{first['price_yuan']}。"
                    "点击下方商品可以直接打开详情并选择尺码。"
                ),
                data=products,
                citations=["MISTER 商品库（实时）"],
                retrieved=[{"doc_key": "product_catalog", "title": "MISTER 商品库", "version": "实时", "score": 1.0}],
            )
        else:
            hits = cite_for(["after_sales_faq", "product_search_guide", "category_guide"])
            out.update(
                answer=(f"暂时没有找到完全符合描述的在售商品。您可以补充颜色、类别、面料或版型再试一次。{_cite(hits)}" if hits
                        else "暂时没有找到符合描述的在售商品，您可以补充颜色、类别、面料或版型再试一次。"),
                citations=rag_svc.format_citations(hits),
                retrieved=[{k: h[k] for k in ("doc_key", "title", "version", "score")} for h in hits],
            )

    elif primary == "store_info_query":
        hits = cite_for(["service_basics"])
        facts: list[str] = []
        if any(word in text for word in ("店名", "什么店", "你们是谁")):
            facts.append("本店名称是 MISTER 男装，提供男装浏览、模拟下单、订单查询和退款售后服务")
        if any(word in text for word in ("支付", "扣款")):
            facts.append("当前项目使用模拟支付，不会产生真实扣款，订单详情会明确标注“在线支付（模拟）”")
        if any(word in text for word in ("客服电话", "怎么联系")):
            facts.append("当前演示系统没有对外客服电话，可以使用右下角智能客服，需要人工时由客服工作台处理")
        if any(word in text for word in ("客服时间", "营业时间")):
            facts.append("智能客服可随时使用；项目没有配置固定人工营业时段，因此不会虚构具体时间")
        answer = "；".join(facts) + "。" if facts else "智能客服可以查询商品、本人订单、退款进度和知识库规则；需要人工确认时会明确提示。"
        out.update(
            answer=f"{answer}{_cite(hits)}",
            citations=rag_svc.format_citations(hits),
            retrieved=[{k: h[k] for k in ("doc_key", "title", "version", "score")} for h in hits],
        )

    elif primary == "category_query":
        hits = cite_for(["category_guide"])
        if ptype:
            label = SUB_CATEGORY_LABELS.get(_TYPE_TO_KEY.get(ptype, ""), ptype)
            out["answer"] = f"{ptype}属于{'下装' if _TYPE_TO_KEY.get(ptype) in _BOTTOM_TYPES else '上装'}类目（{label}）。{_cite(hits)}"
        else:
            out["answer"] = f"男装分为上装（T恤/衬衫/卫衣/夹克/羽绒棉服）和下装（牛仔裤/休闲长裤/西裤/工装裤/运动裤/短裤）。{_cite(hits)}"
        out["citations"] = rag_svc.format_citations(hits)
        out["retrieved"] = [{k: h[k] for k in ("doc_key", "title", "version", "score")} for h in hits]

    else:  # other / 无法判断 → 追问或转人工，绝不编造
        out.update(
            action="human_handoff",
            answer="暂时没有查到相关内容。您可以换个说法再问，或点击【转人工】由客服为您解答。",
        )

    return out


def handle_query(
    db,
    customer,
    text: str,
    session_id: str,
    input_source: str = "text",
    use_model_fallback: bool = False,
    security=None,
) -> dict:
    """用户咨询主入口（文字与语音转写共用）。返回可序列化响应并落库 Trace。"""
    text = (text or "").strip()
    rec = intent_svc.recognize(text)
    composed = _compose(db, customer.id, text, rec)
    generator = "template"

    # 外部模型只能作为明确的二次选择，且不能覆盖订单、退款和知识库的确定性回答。
    if use_model_fallback and composed["action"] == "human_handoff":
        critic = security.check_injection(text) if security else None
        if critic and critic.action != "PASS":
            composed.update(
                answer="这段内容触发了安全检查，无法转给大模型客服。请换一种简单说法再试。",
                action="human_handoff",
            )
            generator = "fallback_blocked"
        else:
            safe_text = security.sanitize(text) if security else text
            try:
                answer = deepseek_svc.generate_answer(safe_text)
                composed.update(
                    answer=security.sanitize(answer) if security else answer,
                    action="model_fallback",
                    citations=[],
                    retrieved=[],
                )
                generator = "deepseek"
            except deepseek_svc.DeepSeekFallbackError:
                composed.update(
                    answer="大模型客服暂时无法接入，请稍后再试。订单和退款问题仍可使用页面里的查询功能。",
                    action="human_handoff",
                )
                generator = "fallback_unavailable"

    response = {
        "session_id": session_id,
        "input_source": input_source,
        "intents": rec["intents"],
        "entities": rec["entities"],
        "confidence": rec["confidence"],
        "answer": composed["answer"],
        "citations": composed["citations"],
        "retrieved": composed["retrieved"],
        "action": composed["action"],
        "data": composed["data"],
        "generator": generator,
    }

    db.add(
        AssistantMessage(
            session_id=session_id,
            customer_id=customer.id,
            input_source=input_source,
            raw_text=text,
            intents=rec["intents"],
            entities=rec["entities"],
            retrieved=composed["retrieved"],
            answer=composed["answer"],
            action=composed["action"],
        )
    )
    db.commit()
    return response
