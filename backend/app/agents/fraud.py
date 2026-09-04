def run(state, deps):
    """FraudAgent：欺诈风险评分。模型异常时安全降级（分数置 0，由决策规则转人工）。"""
    case_id = state["case_id"]
    try:
        result = deps.risk.assess(
            state.get("order_id"),
            state["amount_cent"],
            state.get("evidence_present", False),
            state.get("complaint_text", ""),
            state.get("risk_flags") or {},
        )
    except Exception as exc:  # noqa: BLE001
        deps.record_agent_run(case_id, "FraudAgent", "FAILED", error=str(exc))
        return {"errors": [f"FraudAgent: {exc}"], "fraud_score": 0}

    deps.record_agent_run(case_id, "FraudAgent", "SUCCESS", output_summary=f"fraud={result.fraud_score}")
    deps.publish_event(case_id, {"agent": "FraudAgent", "status": "done", "fraud_score": result.fraud_score})
    return {"fraud_score": result.fraud_score, "risk_factors": result.risk_factors}
