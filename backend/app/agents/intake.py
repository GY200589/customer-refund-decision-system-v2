def run(state, deps):
    """IntakeAgent：校验订单、金额、必填字段，标准化输入。"""
    case_id = state["case_id"]
    amount = state.get("amount_cent")
    order_id = state.get("order_id")
    if not order_id:
        raise ValueError("订单号缺失")
    if amount is None or amount <= 0:
        raise ValueError("金额非法（必须为正整数分）")
    deps.record_agent_run(
        case_id, "IntakeAgent", "SUCCESS",
        input_summary=f"order={order_id} amount={amount}",
        output_summary="字段校验通过",
    )
    deps.publish_event(case_id, {"agent": "IntakeAgent", "status": "done"})
    return {}
