"""意图识别与实体抽取单元测试（定稿 §4.6）。"""
from app.services.intent import recognize


def test_single_intent_refund_create():
    rec = recognize("我要退这条裤子")
    assert rec["intents"][0] == "refund_create"


def test_multi_intent_priority_order():
    # 退款创建 > 投诉：一句话两个意图都要保留，按优先级排序
    rec = recognize("收到的不是我买的黑色休闲裤，我想退款")
    assert "refund_create" in rec["intents"]
    assert "complaint" in rec["intents"]
    assert rec["intents"][0] == "refund_create"
    assert rec["entities"]["color"] == "黑色"
    assert rec["entities"]["product_type"] == "休闲裤"


def test_multi_intent_logistics_and_policy():
    rec = recognize("这条黑色休闲裤什么时候到？如果尺码不合适能不能退？")
    assert "logistics_query" in rec["intents"]
    assert "size_query" in rec["intents"]
    assert "return_policy_query" in rec["intents"]
    # 裸"退"被更具体的 return_policy_query 吸收，不应触发 refund_create
    assert "refund_create" not in rec["intents"]


def test_refund_status_conflict_resolution():
    # "退款进度" 不得同时命中 refund_create（泛化词"退款"被消解）
    rec = recognize("我的退款进度怎么样了")
    assert rec["intents"] == ["refund_status"]


def test_size_entity_height():
    rec = recognize("175的身高穿多大码")
    assert rec["intents"] == ["size_query"]
    assert rec["entities"]["size"] == "身高175"


def test_size_entity_numbered():
    rec = recognize("腰围2尺4穿31码的裤子可以吗")
    assert rec["entities"]["size"] == "31码"


def test_order_no_entity():
    rec = recognize("帮我查订单 SO2026090100001 到哪了")
    assert "order_query" in rec["intents"] or "logistics_query" in rec["intents"]
    assert rec["entities"]["order_no"] == "SO2026090100001"


def test_product_search_from_color_and_generic_type():
    rec = recognize("黑色的裤子")
    assert rec["intents"] == ["product_query"]
    assert rec["entities"] == {"color": "黑色", "product_type": "裤子"}


def test_detailed_product_search_entities():
    rec = recognize("灰色连帽拉链卫衣，重磅棉，宽松版型")
    assert rec["intents"][0] == "product_query"
    assert rec["entities"]["color"] == "灰色"
    assert rec["entities"]["product_type"] == "卫衣"


def test_refund_detail_with_order_number_is_not_refund_create():
    rec = recognize("查退款详情 SO2026090100002")
    assert rec["intents"][0] == "refund_status"
    assert "refund_create" not in rec["intents"]
    assert rec["entities"]["order_no"] == "SO2026090100002"


def test_other_intent_for_chitchat():
    rec = recognize("今天天气怎么样")
    assert rec["intents"] == ["other"]
    assert rec["confidence"] < 0.5


def test_empty_input_safe():
    rec = recognize("")
    assert rec["intents"] == ["other"]


def test_priority_total_order():
    # 意图列表必须按优先级排序（refund_create 最前，complaint 末段）
    rec = recognize("东西质量太差了，我要申请退款，还有帮我查下订单")
    intents = rec["intents"]
    assert intents.index("refund_create") < intents.index("complaint")
    assert "order_query" in intents
