"""OrderVerifyAgent：订单真实性校验。

校验订单是否存在、金额是否匹配。即使校验失败也不阻断流程，
由后续决策规则决定是否转人工。
"""


def run(state, deps):
    case_id = state["case_id"]
    order_id = state["order_id"]

    result = deps.order_verify.verify(order_id)

    status = "SUCCESS" if result.is_valid else "FAILED"
    deps.record_agent_run(
        case_id, "OrderVerifyAgent", status,
        input_summary=f"order={order_id}",
        output_summary=f"valid={result.is_valid} amount={result.verified_amount_cent}",
    )
    deps.persist_case(
        case_id,
        is_verified_order=result.is_valid,
        order_verify_error=result.error if not result.is_valid else None,
        verified_order_amount=result.verified_amount_cent,
    )
    deps.publish_event(case_id, {
        "agent": "OrderVerifyAgent",
        "status": "done",
        "valid": result.is_valid,
    })

    return {
        "is_verified_order": result.is_valid,
        "order_verify_error": result.error if not result.is_valid else None,
        "verified_order_amount": result.verified_amount_cent,
    }