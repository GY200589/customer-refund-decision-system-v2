"""启动种子数据：默认账号、男装演示商品、预置演示订单、客服知识库。

幂等：全部按唯一键（username / product_code / order_no / doc_key）先查后插，
多 worker 并发启动时的唯一键冲突按"已被其他 worker 完成"回滚处理。

用户提供的商品 JSON 与 RAG Markdown 存在时会幂等更新，缺失时保留内置演示数据，
保证离线测试和 Docker 首次启动都能运行。
"""
import json
import re
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import SessionLocal
from .models import KnowledgeDocument, Product, ShopOrder, ShopOrderItem, User
from .auth import hash_password

DEFAULT_PASSWORD = "password123"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_USERS = [
    ("agent1", "agent", "客服小王"),
    ("supervisor1", "supervisor", "主管老张"),
    ("admin1", "admin", "管理员"),
    ("customer1", "customer", "顾客小李"),  # 用户端演示账号（预置订单见 DEMO_ORDERS）
]

# ── 男装演示商品（上装 5 类 + 下装 6 类，共 13 个）──
# 分类以人工标签为准；真实图片到位后回填 image_url 并将 is_demo 置 False（定稿 §4.3）。
DEMO_PRODUCTS = [
    dict(product_code="TOP-TS-001", name="纯棉圆领短袖T恤", main_category="top", sub_category="tshirt",
         color="黑色", sizes=["M", "L", "XL", "XXL"], price_cent=7900, fabric="100% 纯棉",
         fit_notes="版型偏常规，按平时码选购", description="基础款圆领短袖，面料厚实不透"),
    dict(product_code="TOP-TS-002", name="冰感速干短袖T恤", main_category="top", sub_category="tshirt",
         color="白色", sizes=["M", "L", "XL"], price_cent=9900, fabric="聚酯纤维速干面料",
         fit_notes="微宽松，运动通勤皆宜", description="夏季速干，出汗不粘身"),
    dict(product_code="TOP-SH-001", name="纯棉免烫白衬衫", main_category="top", sub_category="shirt",
         color="白色", sizes=["M", "L", "XL", "XXL"], price_cent=12900, fabric="免烫纯棉",
         fit_notes="修身版型，偏瘦可小一码", description="商务休闲两用，机洗免熨烫"),
    dict(product_code="TOP-HD-001", name="加绒连帽卫衣", main_category="top", sub_category="hoodie",
         color="深灰", sizes=["L", "XL", "XXL"], price_cent=19900, fabric="抓绒内里",
         fit_notes="偏宽松，潮牌版型", description="秋冬内搭外套两穿"),
    dict(product_code="TOP-JK-001", name="经典飞行夹克", main_category="top", sub_category="jacket",
         color="军绿", sizes=["M", "L", "XL"], price_cent=39900, fabric="涤棉混纺",
         fit_notes="版型偏挺括，按身高选码", description="春秋外套，罗纹收口"),
    dict(product_code="TOP-PD-001", name="轻薄羽绒服", main_category="top", sub_category="padded",
         color="藏蓝", sizes=["L", "XL", "XXL"], price_cent=49900, fabric="90% 白鸭绒",
         fit_notes="轻薄可折叠，内穿卫衣建议大一码", description="轻便保暖，可压缩收纳"),
    dict(product_code="BTM-JE-001", name="经典直筒牛仔裤", main_category="bottom", sub_category="jeans",
         color="深蓝", sizes=["29", "30", "31", "32", "33", "34"], price_cent=19900, fabric="纯棉丹宁",
         fit_notes="直筒版型，腰围按码数对应腰尺", description="经典丹宁，耐穿耐洗"),
    dict(product_code="BTM-JE-002", name="修身小脚牛仔裤", main_category="bottom", sub_category="jeans",
         color="浅蓝", sizes=["29", "30", "31", "32"], price_cent=21900, fabric="弹力丹宁",
         fit_notes="修身小脚，腿粗建议大一码", description="含弹力，贴身不紧绷"),
    dict(product_code="BTM-CP-001", name="休闲直筒长裤", main_category="bottom", sub_category="casual_pants",
         color="卡其", sizes=["30", "31", "32", "33"], price_cent=17900, fabric="棉锦斜纹",
         fit_notes="直筒宽松，日常通勤", description="非丹宁日常长裤，四季可穿"),
    dict(product_code="BTM-SP-001", name="商务垂感西裤", main_category="bottom", sub_category="suit_pants",
         color="深灰", sizes=["30", "31", "32", "34"], price_cent=23900, fabric="垂感聚酯混纺",
         fit_notes="正装版型，配西装衬衫", description="免烫垂感，商务场合"),
    dict(product_code="BTM-CG-001", name="多口袋工装裤", main_category="bottom", sub_category="cargo_pants",
         color="军绿", sizes=["30", "32", "34"], price_cent=18900, fabric="厚实帆布",
         fit_notes="宽松多袋，户外风格", description="侧边大口袋，耐磨帆布"),
    dict(product_code="BTM-JG-001", name="针织束脚运动裤", main_category="bottom", sub_category="joggers",
         color="黑色", sizes=["L", "XL", "XXL"], price_cent=12900, fabric="针织毛圈",
         fit_notes="束脚抽绳，居家运动", description="宽松束脚，柔软亲肤"),
    dict(product_code="BTM-SC-001", name="工装多袋短裤", main_category="bottom", sub_category="shorts",
         color="军绿", sizes=["30", "32", "34"], price_cent=8900, fabric="帆布",
         fit_notes="膝盖以上，夏季户外", description="多口袋设计，透气耐磨"),
]

# ── 预置演示订单（customer1）──
# 剧本（定稿 §10.1）：A 运输中（物流咨询演示）；B 已完成（"尺码不合适"退款演示，
# 上传凭证→低风险自动通过）；C 已完成多商品（部分退款 + 发错转人工演示）。
DEMO_ORDERS = [
    dict(order_no="SO2026090100001", status="SHIPPED",
         items=[("BTM-JE-001", "31")]),
    dict(order_no="SO2026090100002", status="COMPLETED",
         items=[("BTM-CP-001", "32")]),
    dict(order_no="SO2026090100003", status="COMPLETED",
         items=[("TOP-HD-001", "L"), ("BTM-SC-001", "32")]),
]

# ── 客服知识库（演示草稿版，doc_key 固定；正式规则由用户材料替换内容）──
KNOWLEDGE_DOCS = [
    ("refund_policy", "售后规则", "refund_policy",
     "自营男装商品支持签收后 7 天无理由退货退款。申请退款需在签收后 7 天内提交，"
     "商品需保持吊牌完整、未经穿着洗涤。退款凭证要求：提供订单号；商品破损、发错货、"
     "少件需拍照上传凭证，尺码不合适无需照片但商品需保持完好。以下情形不支持无理由退款："
     "商品已洗涤或穿着影响二次销售、定制类商品。退款金额按支付原路退回，一般 1-3 个工作日到账。"
     "超过 7 天、材料不全或系统提示需进一步核实的申请会转人工审核。"),
    ("process_guide", "退款流程说明", "process",
     "退款流程：进入我的订单，选择商品点击申请退款，填写退款原因（可打字描述、上传凭证照片，"
     "也可点麦克风语音说退款原因）。提交后系统自动核对资料：风险较低、材料齐全的申请会自动通过，"
     "金额较大、材料不全或需要进一步核实的申请会转人工客服确认。审批通过后退款原路退回，"
     "1-3 个工作日到账。可随时在我的退款页面查看处理进度。"),
    ("size_guide_top", "上装尺码表", "size_guide",
     "上装尺码对照：S 适合身高 160-165、体重 90-105 斤；M 适合身高 165-170、体重 105-120 斤；"
     "L 适合身高 170-175、体重 120-135 斤；XL 适合身高 175-180、体重 135-150 斤；"
     "XXL 适合身高 180-185、体重 150-165 斤。卫衣偏宽松可按平时码，衬衫修身偏瘦建议小一码，"
     "羽绒服内穿建议大一码。尺码不合适支持 7 天无理由退换。"),
    ("size_guide_bottom", "下装尺码表", "size_guide",
     "下装码数对照：29码适合腰围2尺2、身高165-170、体重100-110斤；30码适合腰围2尺3、"
     "身高170-175、体重110-120斤；31码适合腰围2尺4、体重120-130斤；32码适合腰围2尺5、"
     "体重130-140斤；33码适合腰围2尺6、体重140-150斤；34码适合腰围2尺7、体重150-160斤。"
     "牛仔裤按腰围选码，运动裤按身高选L/XL。拿不准两个码之间时建议选大一码，尺码不合适可无理由退换。"),
    ("logistics_guide", "物流与发货说明", "logistics",
     "下单后 48 小时内发货，默认快递 3-5 天送达，偏远地区 5-7 天。订单状态分为待发货、运输中、已签收。"
     "发货后可在我的订单查看物流进度。演示环境中物流信息为模拟数据。"),
    ("category_guide", "男装分类标准", "category",
     "男装分为上装和下装两大类。上装包括：T 恤（无扣无领圆领 V 领）、衬衫（有领前襟一排扣）、"
     "卫衣（抓绒面料套头或连帽）、夹克（拉链或按扣的春秋外套）、羽绒棉服（冬季厚外套）。"
     "下装包括：牛仔裤（丹宁布料带铆钉）、休闲长裤（非丹宁的日常长裤）、西裤（正装垂感面料）、"
     "工装裤（侧边大口袋帆布厚实）、运动裤（针织面料束脚口）、短裤（裤长在膝盖以上）。"
     "七分裤按长度属性标注，归入短裤或对应长裤类别。"),
    ("ocr_guide", "凭证识别失败怎么办", "ocr_guide",
     "凭证照片识别失败时：请确认照片清晰、光线充足，支持 jpg、png、pdf 格式，单张不超过 10MB。"
     "识别失败不影响提交申请，可以手动填写退款金额后提交，也可以不上传凭证直接提交文字说明，"
     "系统会在人工审核阶段由客服补充核对。"),
    ("risk_explain", "为什么我的申请转人工了", "risk_explain",
     "以下情形会转人工客服进一步确认：退款金额较大、凭证材料不齐全、同一商品重复申请、"
     "或系统检测到需要人工核实的风险信号。转人工是为了保障您的账号和资金安全，"
     "人工确认一般在 24 小时内完成，处理结果可以在我的退款页面查看。"),
]

MAIN_CATEGORY_MAP = {"上装": "top", "下装": "bottom"}
SUB_CATEGORY_MAP = {
    "T恤": "tshirt", "衬衫": "shirt", "卫衣": "hoodie", "夹克": "jacket",
    "羽绒棉服": "padded", "牛仔裤": "jeans", "休闲长裤": "casual_pants",
    "西裤": "suit_pants", "工装裤": "cargo_pants", "运动裤": "joggers", "短裤": "shorts",
}


def _first_existing(configured: str, candidates: list[Path]) -> Path | None:
    paths = ([Path(configured)] if configured else []) + candidates
    return next((path for path in paths if path.is_file()), None)


def _load_catalog_products() -> list[dict]:
    """把人工标签表转成 Product 字段；价格、标题、图片沿用采集值，补齐字段保留演示标记。"""
    source = _first_existing(
        settings.catalog_data_path,
        [
            Path("/app/catalog_data/商品标签表.json"),
            PROJECT_ROOT / "男装" / "商品标签表.json",
        ],
    )
    if source is None:
        return []
    try:
        rows = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []

    products: list[dict] = []
    for row in rows:
        main = MAIN_CATEGORY_MAP.get(str(row.get("一级分类", "")).strip())
        sub = SUB_CATEGORY_MAP.get(str(row.get("二级分类", "")).strip())
        image_name = Path(str(row.get("图片文件名", ""))).name
        product_id = str(row.get("商品ID") or Path(image_name).stem.replace("SKU_", "")).strip()
        if not main or not sub or not product_id or not image_name:
            continue
        sizes = [value.strip() for value in str(row.get("尺码", "")).split("/") if value.strip()]
        fabric = str(row.get("面料/版型", "")).strip()
        length = str(row.get("长度", "")).strip()
        products.append(
            {
                "product_code": f"SKU-{product_id}",
                "name": str(row.get("商品名") or row.get("原始商品标题") or f"男装商品 {product_id}").strip(),
                "main_category": main,
                "sub_category": sub,
                "color": str(row.get("颜色") or "以图片为准").strip(),
                "sizes": sizes or ["M", "L", "XL"],
                "price_cent": int(round(float(row.get("价格（元）") or 0) * 100)),
                "image_url": f"/products/{image_name}",
                "fabric": fabric or None,
                "fit_notes": "；".join(value for value in (length, fabric) if value) or "按日常尺码选购",
                "description": str(row.get("一句话") or row.get("原始商品标题") or "演示男装商品").strip(),
                "is_demo": True,
                "is_active": True,
            }
        )
    return products


def _markdown_h2(markdown: str, number: str) -> str:
    match = re.search(rf"^##\s+{re.escape(number)}、.*?(?=^##\s+|\Z)", markdown, re.MULTILINE | re.DOTALL)
    return match.group(0).strip() if match else ""


def _markdown_h3(section: str, number: str) -> str:
    match = re.search(rf"^###\s+{re.escape(number)}\s+.*?(?=^###\s+|\Z)", section, re.MULTILINE | re.DOTALL)
    return match.group(0).strip() if match else ""


def _load_knowledge_docs() -> list[tuple[str, str, str, str]]:
    """按业务主题读取正式 Markdown；不导入末尾的“索引建议”等编写说明。"""
    source = _first_existing(
        settings.knowledge_base_path,
        [
            Path("/app/knowledge/客服知识库-RAG.md"),
            PROJECT_ROOT / "RAG" / "data" / "客服知识库-RAG.md",
        ],
    )
    if source is None:
        return []
    try:
        markdown = source.read_text(encoding="utf-8-sig")
    except OSError:
        return []

    refund = _markdown_h2(markdown, "一")
    sizes = _markdown_h2(markdown, "二")
    logistics = _markdown_h2(markdown, "三")
    faq = _markdown_h2(markdown, "四")
    after_sales = _markdown_h2(markdown, "五")
    ocr = _markdown_h2(markdown, "六")
    risk = _markdown_h2(markdown, "七")
    assistant_queries = _markdown_h2(markdown, "九")
    candidates = [
        ("refund_policy", "退换货规则", "refund_policy", refund),
        ("size_guide_top", "上装尺码推荐", "size_guide", "\n\n".join(filter(None, [_markdown_h3(sizes, "2.1"), _markdown_h3(sizes, "2.3")]))),
        ("size_guide_bottom", "下装尺码推荐", "size_guide", "\n\n".join(filter(None, [_markdown_h3(sizes, "2.2"), _markdown_h3(sizes, "2.3")]))),
        ("logistics_guide", "物流与发货说明", "logistics", logistics),
        ("process_guide", "退款申请与到账流程", "process", faq),
        ("after_sales_faq", "常见售后问题及解决办法", "after_sales", after_sales),
        ("ocr_guide", "凭证识别失败与补充材料", "ocr_guide", ocr),
        ("risk_explain", "高风险转人工说明", "risk_explain", risk),
        ("product_search_guide", "商品搜索与推荐口径", "product_search", _markdown_h3(assistant_queries, "9.1")),
        ("order_query_guide", "订单与退款查询口径", "order_query", "\n\n".join(filter(None, [
            _markdown_h3(assistant_queries, "9.2"),
            _markdown_h3(assistant_queries, "9.3"),
        ]))),
        ("service_basics", "MISTER 男装基本信息", "service_basics", _markdown_h3(assistant_queries, "9.4")),
    ]
    return [item for item in candidates if item[3]]


def _seed_users(db) -> None:
    for username, role, display in DEFAULT_USERS:
        if db.query(User).filter(User.username == username).first():
            continue
        db.add(
            User(
                username=username,
                password_hash=hash_password(DEFAULT_PASSWORD),
                role=role,
                display_name=display,
            )
        )


def _seed_products(db) -> None:
    for spec in DEMO_PRODUCTS:
        if db.query(Product).filter(Product.product_code == spec["product_code"]).first():
            continue
        db.add(Product(**spec, is_demo=True, is_active=True))

    imported = _load_catalog_products()
    if not imported:
        return
    db.flush()
    for spec in imported:
        product = db.query(Product).filter(Product.product_code == spec["product_code"]).first()
        if product is None:
            db.add(Product(**spec))
            continue
        # 标签表是商品主数据来源；重复启动更新内容而不产生重复 SKU。
        for field, value in spec.items():
            setattr(product, field, value)

    # 真实图片目录到位后不再在商城展示旧占位商品，但保留它们供既有演示订单复算。
    legacy_codes = [spec["product_code"] for spec in DEMO_PRODUCTS]
    for product in db.query(Product).filter(Product.product_code.in_(legacy_codes)).all():
        product.is_active = False


def _seed_shop_orders(db) -> None:
    customer = db.query(User).filter(User.username == "customer1").first()
    if customer is None:
        return
    products = {p.product_code: p for p in db.query(Product).all()}
    for spec in DEMO_ORDERS:
        if db.query(ShopOrder).filter(ShopOrder.order_no == spec["order_no"]).first():
            continue
        total = 0
        items: list[ShopOrderItem] = []
        for code, size in spec["items"]:
            p = products.get(code)
            if p is None:  # 商品种子缺失时跳过该明细，不阻塞启动
                continue
            total += p.price_cent
            items.append(
                ShopOrderItem(
                    product_id=p.id,
                    product_name=p.name,
                    sub_category=p.sub_category,
                    size=size,
                    color=p.color,
                    quantity=1,
                    unit_price_cent=p.price_cent,
                )
            )
        order = ShopOrder(
            order_no=spec["order_no"],
            customer_id=customer.id,
            status=spec["status"],
            total_cent=total,
        )
        db.add(order)
        db.flush()
        for item in items:
            item.order_id = order.id
            db.add(item)


def _seed_knowledge(db) -> None:
    for doc_key, title, category, content in KNOWLEDGE_DOCS:
        if db.query(KnowledgeDocument).filter(KnowledgeDocument.doc_key == doc_key).first():
            continue
        db.add(
            KnowledgeDocument(
                doc_key=doc_key,
                title=title,
                category=category,
                content=content,
                version="v1",
                enabled=True,
            )
        )

    db.flush()
    for doc_key, title, category, content in _load_knowledge_docs():
        document = db.query(KnowledgeDocument).filter(KnowledgeDocument.doc_key == doc_key).first()
        if document is None:
            db.add(
                KnowledgeDocument(
                    doc_key=doc_key,
                    title=title,
                    category=category,
                    content=content,
                    version="kb-v1",
                    enabled=True,
                )
            )
            continue
        document.title = title
        document.category = category
        document.content = content
        document.version = "kb-v1"


def seed_defaults() -> None:
    with SessionLocal() as db:
        try:
            _seed_users(db)
            _seed_products(db)
            _seed_shop_orders(db)
            _seed_knowledge(db)
            db.commit()
        except IntegrityError:
            # 多 uvicorn worker 并发启动时可能同时插入同一批种子；唯一键冲突
            # 视为已由其他 worker 完成初始化，回滚即可。
            db.rollback()
