from ..policy.decision_policy import DecisionInput, decide


def run(state, deps):
    """DecisionPolicy：确定性规则引擎计算最终决策，不依赖大模型。"""
    case_id = state["case_id"]
    fraud_score = state.get("fraud_score", 0)
    sentiment_score = state.get("sentiment_score", 0)
    risk_level = state.get("risk_level", "LOW")
    risk_factors = state.get("risk_factors") or []

    user_id = state.get("user_id")
    refund_rate = deps.get_user_refund_rate(user_id) if user_id else 0.0

    inp = DecisionInput(
        amount_cent=state["amount_cent"],
        ocr_confidence=state.get("ocr_confidence"),
        ocr_corrected=state.get("ocr_corrected", False),
        fraud_score=fraud_score,
        sentiment_score=sentiment_score,
        risk_level=risk_level,
        risk_flags=state.get("risk_flags") or {},
        evidence_present=state.get("evidence_present", False),
        is_verified_order=state.get("is_verified_order", True),
        order_verify_error=state.get("order_verify_error"),
        verified_order_amount=state.get("verified_order_amount"),
        product_match=state.get("product_match", True),
        product_consistency_risk=state.get("product_consistency_risk", "LOW"),
        refund_rate=refund_rate,
    )
    thresholds = deps.get_thresholds()
    result = decide(inp, thresholds=thresholds)

    deps.persist_risk(case_id, fraud_score, sentiment_score, risk_level, risk_factors)
    deps.persist_case(
        case_id,
        decision=result.decision,
        decision_reason=result.reason,
        fraud_score=fraud_score,
        sentiment_score=sentiment_score,
        risk_level=risk_level,
        refund_rate=refund_rate,
        ocr_confidence=state.get("ocr_confidence"),
        risk_flags=state.get("risk_flags") or {},
    )
    deps.record_agent_run(case_id, "DecisionPolicy", "SUCCESS", output_summary=result.decision)
    deps.publish_event(case_id, {"agent": "DecisionPolicy", "status": "done", "decision": result.decision, "reason": result.reason})
    return {"decision": result.decision, "decision_reason": result.reason}
