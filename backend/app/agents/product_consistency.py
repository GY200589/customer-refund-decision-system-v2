"""ProductConsistencyAgent：商品一致性校验。

从投诉文本中提取商品信息，与订单实际购买商品比对。
即使校验失败也不阻断流程，由后续决策规则决定是否转人工。
"""


def run(state, deps):
    case_id = state["case_id"]
    complaint_text = state.get("complaint_text", "")
    order_id = state["order_id"]

    result = deps.product_consistency.check(complaint_text, order_id)

    deps.record_agent_run(
        case_id, "ProductConsistencyAgent", "SUCCESS",
        input_summary=f"order={order_id}",
        output_summary=f"match={result.is_match} risk={result.risk}",
    )
    deps.persist_case(
        case_id,
        product_match=result.is_match,
        claimed_product=result.claimed_product,
        purchased_product=result.purchased_product,
        product_consistency_risk=result.risk,
    )
    deps.publish_event(case_id, {
        "agent": "ProductConsistencyAgent",
        "status": "done",
        "match": result.is_match,
    })

    return {
        "product_match": result.is_match,
        "claimed_product": result.claimed_product,
        "purchased_product": result.purchased_product,
        "product_consistency_risk": result.risk,
    }