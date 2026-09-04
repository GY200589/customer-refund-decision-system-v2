def run(state, deps):
    """Reject：驳回，流转至 REJECTED 终态。"""
    case_id = state["case_id"]
    current = deps.get_case_status(case_id)
    if current != "REJECTED":
        deps.transition(case_id, current, "REJECTED", review_comment=state.get("review_comment"))
    deps.refresh_user_refund_rate(state.get("user_id"))
    deps.publish_event(case_id, {"agent": "Reject", "status": "rejected"})
    return {}
