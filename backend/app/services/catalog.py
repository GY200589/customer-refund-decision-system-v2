"""用户端常量：类目树、通俗状态映射（定稿 §4.5，含 APPROVED / C1）、退款原因码。"""

# 男装分类树（与商品种子数据、知识库 category_guide 保持同一套口径）
CATEGORY_TREE = [
    {
        "key": "top",
        "label": "上装",
        "children": [
            {"key": "tshirt", "label": "T恤"},
            {"key": "shirt", "label": "衬衫"},
            {"key": "hoodie", "label": "卫衣"},
            {"key": "jacket", "label": "夹克"},
            {"key": "padded", "label": "羽绒棉服"},
        ],
    },
    {
        "key": "bottom",
        "label": "下装",
        "children": [
            {"key": "jeans", "label": "牛仔裤"},
            {"key": "casual_pants", "label": "休闲长裤"},
            {"key": "suit_pants", "label": "西裤"},
            {"key": "cargo_pants", "label": "工装裤"},
            {"key": "joggers", "label": "运动裤"},
            {"key": "shorts", "label": "短裤"},
        ],
    },
]

SUB_CATEGORY_LABELS = {
    child["key"]: child["label"]
    for node in CATEGORY_TREE
    for child in node["children"]
}
MAIN_CATEGORY_LABELS = {node["key"]: node["label"] for node in CATEGORY_TREE}

# 系统状态 → 用户端通俗文案（完整覆盖状态机，含 APPROVED；不暴露内部风险分）
FRIENDLY_STATUS = {
    "CREATED": "正在核对资料",
    "RUNNING": "正在核对资料",
    "SUSPENDED": "需要人工进一步确认",
    "APPROVED": "审批已通过，正在退款",
    "COMPLETED": "退款已完成",
    "REJECTED": "本次申请未通过",
    "FAILED": "系统处理失败，请联系客服",
}

# 订单状态 → 用户端文案
FRIENDLY_ORDER_STATUS = {
    "SHIPPED": "运输中",
    "COMPLETED": "已完成",
}

# 退款原因码（用户端表单下拉）
REASON_CODES = [
    ("damaged", "商品破损"),
    ("quality", "商品质量问题"),
    ("wrong_item", "发错商品"),
    ("size", "尺码不合适"),
    ("logistics", "物流问题"),
    ("not_as_described", "与描述不符"),
    ("missing", "少件/漏发"),
    ("other", "其他"),
]
REASON_LABELS = dict(REASON_CODES)
