from langgraph.types import interrupt


def run(state, deps):
    """HumanReview：转人工，挂起状态机并通过 interrupt() 暂停图，等待主管审批后恢复。

    LangGraph 在 resume 时会从头重新执行本节点，因此状态流转与任务创建必须幂等：
    仅在尚未挂起时执行 transition / create_review_task。
    """
    case_id = state["case_id"]
    reason = state.get("decision_reason", "需人工审核")
    current = deps.get_case_status(case_id)
    if current != "SUSPENDED":
        deps.transition(case_id, current, "SUSPENDED", decision="HUMAN_REVIEW", decision_reason=reason)
        deps.create_review_task(case_id)
    deps.publish_event(case_id, {"agent": "HumanReview", "status": "suspended", "reason": reason})

    resume = interrupt({"case_id": case_id, "reason": reason})
    action = (resume or {}).get("action", "REJECT")
    comment = (resume or {}).get("comment", "")
    return {"decision": action, "review_comment": comment}
