def run(state, deps):
    """ExecuteRefund：批准后退款执行（幂等），并流转至 COMPLETED。"""
    case_id = state["case_id"]

    # Tool-calling 参数校验
    validation = deps.security.validate_tool_call(
        tool_name="execute_refund",
        params={"case_id": case_id, "amount_cent": state["amount_cent"]},
    )
    if not validation.valid:
        deps.record_agent_run(case_id, "ToolFilter", "BLOCKED", error=validation.reason)
        from ..models import AuditLog
        from ..db import SessionLocal
        with SessionLocal() as db:
            db.add(AuditLog(
                case_id=case_id, actor_id=None,
                action="toolfilter:blocked",
                after_value={"reason": validation.reason},
            ))
            db.commit()
        raise ValueError(f"Tool-calling 被拦截: {validation.reason}")

    current = deps.get_case_status(case_id)

    if current == "COMPLETED":
        # Worker 重试或消息重复投递时直接返回，避免重复退款。
        return {}
    if current != "APPROVED":
        deps.transition(case_id, current, "APPROVED", review_comment=state.get("review_comment"))

    if not deps.is_refund_executed(case_id):
        refund_ref = deps.refund.execute(case_id, state["amount_cent"], f"refund:{case_id}")
        deps.mark_refund_executed(case_id, refund_ref)
        deps.publish_event(case_id, {"agent": "ExecuteRefund", "status": "refunded", "refund_ref": refund_ref})

    deps.transition(case_id, "APPROVED", "COMPLETED")
    deps.refresh_user_refund_rate(state.get("user_id"))
    deps.publish_event(case_id, {"agent": "ExecuteRefund", "status": "completed"})
    return {"refund_ref": f"mock-refund-{case_id}"}
