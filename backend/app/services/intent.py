"""多意图识别（规则 + 词典优先，定稿 §4.6）。

设计要点：
- 一句话可返回多个意图，按 INTENT_PRIORITY 排序（退款创建 > 退款查询 > ...）；
- 词典是子串匹配，天然存在包含冲突（"退款进度" 含 "退款"），用冲突消解规则处理，
  避免高频短语误触发高优先级意图；
- 识别不确定时返回 other / 低置信度，由上层追问，不凭空生成订单或退款结果；
- 识别结果由调用方写入 AssistantMessage，供自动评测与复盘。
"""
import re

# 意图优先级：索引越小越先执行
INTENT_PRIORITY = [
    "refund_create",
    "refund_status",
    "order_query",
    "logistics_query",
    "size_query",
    "return_policy_query",
    "product_query",
    "category_query",
    "store_info_query",
    "complaint",
    "other",
]

INTENT_KEYWORDS: dict[str, list[str]] = {
    # 退款创建：需要明确的动作意图；裸"退款/退货"由冲突消解处理
    "refund_create": ["我要退", "申请退", "退款", "退货", "退了吧", "退掉", "退这", "给我退"],
    "refund_status": ["退款进度", "退款到哪", "退到哪", "退款状态", "退款详情", "退款记录", "退款案件", "退款结果", "我的退款", "退款处理", "到账"],
    "order_query": ["我的订单", "订单", "订单详情", "我买", "买的", "买了", "下单", "已购", "购买记录"],
    "logistics_query": ["物流", "快递", "什么时候到", "几天到", "多久到", "到哪儿", "送到", "到货", "发货", "送货"],
    "size_query": ["尺码", "尺寸", "码数", "穿多大", "多大码", "合身", "偏大", "偏小", "选码", "腰围"],
    "return_policy_query": ["能不能退", "可以退", "能退吗", "可退吗", "无理由", "退货政策", "退款规则", "几天内退", "政策", "规则"],
    "product_query": ["找衣服", "找裤子", "推荐", "有没有", "想买", "想看", "面料", "材质", "什么布", "纯棉", "重磅", "厚不厚", "透气", "保暖", "版型", "什么料", "起球"],
    "category_query": ["什么类型", "什么裤", "哪类", "分类", "属于什么", "还是", "区别"],
    "store_info_query": ["店名", "什么店", "你们是谁", "客服时间", "营业时间", "支付方式", "会扣款吗", "客服电话", "怎么联系"],
    "complaint": ["发错", "不是", "假货", "假冒", "破损", "破了", "坏了", "质量", "太差", "少件", "漏发", "开线", "色差"],
}

# 冲突消解：当高优先级意图的命中全部来自"泛化词"且更具体的意图也命中时，丢弃泛化命中。
# 例："退款进度" 命中 refund_create("退款") 与 refund_status("退款进度") → 只保留 refund_status。
_SUBSUMED_CREATE_HITS = {"退款", "退货", "给我退"}
_CONFLICT_PARENTS = ("refund_status", "return_policy_query")


def _extract_entities(text: str) -> dict:
    entities: dict = {}

    colors = ["黑色", "白色", "深灰", "浅灰", "灰色", "深蓝", "浅蓝", "蓝色", "卡其",
              "军绿", "绿色", "棕色", "藏蓝", "米色"]
    for color in colors:
        if color in text:
            entities["color"] = color
            break

    product_types = ["牛仔裤", "休闲长裤", "休闲裤", "西裤", "工装裤", "运动裤", "短裤", "七分裤", "长裤",
                     "衬衫", "T恤", "卫衣", "夹克", "羽绒服", "棉服", "裤子", "裤装", "上衣", "外套", "衣服"]
    for ptype in product_types:
        if ptype in text:
            entities["product_type"] = ptype
            break

    m = re.search(r"\bSO[A-Z0-9]{6,}\b", text, re.IGNORECASE)
    if m:
        entities["order_no"] = m.group(0).upper()

    # 当前案件号为 UUID；保留独立实体，避免把退款详情误当普通订单详情。
    m = re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", text, re.IGNORECASE)
    if m:
        entities["case_id"] = m.group(0).lower()

    m = re.search(r"(\d{2})\s*码", text)
    if m:
        entities["size"] = f"{m.group(1)}码"
    else:
        height = re.search(r"身高\s*(\d{3})", text) or re.search(r"(\d{3})\s*的?身高", text)
        if height:
            entities["size"] = f"身高{height.group(1)}"
        else:
            m = re.search(r"\b(X{0,2}S|[SML])\b", text)
            if m:
                entities["size"] = m.group(1)

    m = re.search(r"(\d+)\s*天", text)
    if m:
        entities["days"] = int(m.group(1))

    return entities


def recognize(text: str) -> dict:
    """识别输入文本，返回 {intents, entities, confidence}。"""
    text = (text or "").strip()
    if not text:
        return {"intents": ["other"], "entities": {}, "confidence": 0.1}

    hits: dict[str, list[str]] = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        matched = [kw for kw in keywords if kw in text]
        if matched:
            hits[intent] = matched

    # 冲突消解：refund_create 的命中全是泛化词，且更具体的查询意图命中 → 丢弃 refund_create
    if "refund_create" in hits and any(p in hits for p in _CONFLICT_PARENTS):
        if set(hits["refund_create"]) <= _SUBSUMED_CREATE_HITS:
            del hits["refund_create"]

    entities = _extract_entities(text)
    if not hits:
        # 只有颜色/商品词的自然搜索（如“黑色的裤子”）也应进入商品检索。
        if entities.get("color") or entities.get("product_type"):
            return {"intents": ["product_query"], "entities": entities, "confidence": 0.72}
        return {"intents": ["other"], "entities": entities, "confidence": 0.3}

    intents = sorted(hits.keys(), key=INTENT_PRIORITY.index)
    # 置信度：命中意图越多、命中词越多越确定（启发式，规则引擎口径内自洽）
    total_hits = sum(len(v) for v in hits.values())
    confidence = min(0.95, 0.55 + 0.12 * (len(intents) - 1) + 0.08 * total_hits)
    return {"intents": intents, "entities": entities, "confidence": round(confidence, 2)}
