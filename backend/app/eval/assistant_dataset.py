"""客服 Golden Dataset — 覆盖意图、RAG 检索、语音和动作路由的持续评测集。

与退款决策评测（golden_dataset/dataset.py，13 条）口径分离，互不影响。
字段约定：
- expected_intents / expected_action / expected_entities 存在才参与对应指标；
- expected_sources 存在才参与 RAG 检索指标；
- input_source=voice 的用例为"语音转写文本"模拟（真实 ASR 接入后由转写结果替换），
  用于对比语音与文字输入的意图识别一致性。
"""


def load_assistant_dataset() -> list[dict]:
    cases: list[dict] = []

    def add(case_id, query, *, intents=None, entities=None, sources=None, action=..., source="text"):
        case = {"id": case_id, "query": query, "input_source": source}
        if intents is not None:
            case["expected_intents"] = intents
        if entities:
            case["expected_entities"] = entities
        if sources is not None:
            case["expected_sources"] = sources
        if action is not ...:
            case["expected_action"] = action
        cases.append(case)

    # ── 意图识别（20 条）──
    add("intent-001", "我要退这条裤子", intents=["refund_create"], action="create_refund")
    add("intent-002", "收到的不是我买的黑色休闲裤，我想退款",
        intents=["refund_create", "complaint", "order_query"],
        entities={"color": "黑色", "product_type": "休闲裤"}, action="create_refund")
    add("intent-003", "这条黑色休闲裤什么时候到",
        intents=["logistics_query"], entities={"color": "黑色", "product_type": "休闲裤"}, action="query_order")
    add("intent-004", "我的退款到哪了", intents=["refund_status"], action="query_order")
    add("intent-005", "175的身高穿多大码", intents=["size_query"], entities={"size": "身高175"})
    add("intent-006", "牛仔裤属于什么类型", intents=["category_query"], entities={"product_type": "牛仔裤"})
    add("intent-007", "这件衬衫是什么面料", intents=["product_query"], entities={"product_type": "衬衫"})
    add("intent-008", "7天内可以退货吗", intents=["return_policy_query"], entities={"days": 7})
    add("intent-009", "衣服会起球吗", intents=["product_query"])
    add("intent-010", "快递几天能到", intents=["logistics_query"], action="query_order")
    add("intent-011", "这条裤子破损了我要退款", intents=["refund_create", "complaint"], action="create_refund")
    add("intent-012", "工装裤是哪类", intents=["category_query"], entities={"product_type": "工装裤"})
    add("intent-013", "帮我查一下我的订单", intents=["order_query"], action="query_order")
    add("intent-014", "什么面料透气", intents=["product_query"])
    add("intent-015", "卫衣是什么类型", intents=["category_query"], entities={"product_type": "卫衣"})
    add("intent-016", "我要申请退款，商家发错货了", intents=["refund_create", "complaint"], action="create_refund")
    add("intent-017", "退款什么时候能到账", intents=["refund_status"], action="query_order")
    add("intent-018", "这个衬衫是纯棉的吗", intents=["product_query"], entities={"product_type": "衬衫"})
    add("intent-019", "下装有哪些分类", intents=["category_query"])
    add("intent-020", "今天天气怎么样", intents=["other"], action="human_handoff")
    add("intent-021", "黑色的裤子", intents=["product_query"], entities={"color": "黑色", "product_type": "裤子"})
    add("intent-022", "灰色连帽拉链卫衣，重磅棉，宽松版型",
        intents=["product_query"], entities={"color": "灰色", "product_type": "卫衣"})
    add("intent-023", "查询订单 SO2026090100001 的详情",
        intents=["order_query"], entities={"order_no": "SO2026090100001"}, action="query_order")
    add("intent-024", "查询退款详情 SO2026090100002",
        intents=["refund_status"], entities={"order_no": "SO2026090100002"}, action="query_order")
    add("intent-025", "你们店名是什么", intents=["store_info_query"])

    # ── RAG 检索（10 条，只考检索与引用，不考意图）──
    add("rag-001", "多久可以退货退款", sources=["refund_policy"])
    add("rag-002", "尺码不合适怎么办", sources=["size_guide_top", "size_guide_bottom"])
    add("rag-003", "腰围2尺5穿多大码", sources=["size_guide_bottom"])
    add("rag-004", "什么时候发货几天能到", sources=["logistics_guide"])
    add("rag-005", "牛仔裤和休闲裤怎么分类", sources=["category_guide"])
    add("rag-006", "凭证照片识别失败怎么办", sources=["ocr_guide"])
    add("rag-007", "为什么我的退款转人工了", sources=["risk_explain"])
    add("rag-008", "退款多久能到账", sources=["refund_policy", "process_guide"])
    add("rag-009", "无理由退货有什么条件", sources=["refund_policy"])
    add("rag-010", "运动裤尺码怎么选", sources=["size_guide_bottom"])
    add("rag-011", "商品搜索怎么按颜色和面料推荐", sources=["product_search_guide"])
    add("rag-012", "输入订单号怎么查订单详情", sources=["order_query_guide"])
    add("rag-013", "MISTER 男装使用什么支付方式会真实扣款吗", sources=["service_basics"])

    # ── 语音转写文本（5 条，input_source=voice）──
    add("voice-001", "这条裤子小了我要退了重新买", intents=["refund_create"], action="create_refund", source="voice")
    add("voice-002", "我买的牛仔裤到哪儿了什么时候送到",
        intents=["order_query", "logistics_query"], entities={"product_type": "牛仔裤"},
        action="query_order", source="voice")
    add("voice-003", "帮我看看退款处理得怎么样了", intents=["refund_status"], action="query_order", source="voice")
    add("voice-004", "这件夹克厚不厚冬天能穿吗", intents=["product_query"], entities={"product_type": "夹克"}, source="voice")
    add("voice-005", "收到的短袖不是我要的黑色T恤",
        intents=["complaint"], entities={"color": "黑色", "product_type": "T恤"}, action="create_refund", source="voice")

    # ── 动作触发（5 条）──
    add("action-001", "你们的东西太差了", intents=["complaint"], action="create_refund")
    add("action-002", "我要退昨天买的那条西裤",
        intents=["refund_create", "order_query"], entities={"product_type": "西裤"}, action="create_refund")
    add("action-003", "查一下我的退款进度", intents=["refund_status"], action="query_order")
    add("action-004", "短裤和七分裤的区别是什么", intents=["category_query"], entities={"product_type": "短裤"})
    add("action-005", "我能无理由退货吗", intents=["return_policy_query"])

    return cases
