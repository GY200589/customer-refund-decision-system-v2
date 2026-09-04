"""MergedRiskAgent — 合并欺诈评分与情绪分析

替代原 FraudAgent + SentimentAgent，一次调用 CombinedRiskProvider，
减少 LLM 调用次数（成本优化）。
"""
def run(state, deps):
    """MergedRiskAgent：合并评估欺诈风险与舆情情绪。模型异常时安全降级。"""
    case_id = state["case_id"]
    try:
        flags = state.get("risk_flags") or {}
        # 可免凭证的标准售后（如尺码不合适）不应因“没有图片”被当作欺诈。
        evidence_present = state.get("evidence_present", True) or not flags.get("evidence_required", True)
        result = deps.combined_risk.assess(
            state.get("order_id"),
            state["amount_cent"],
            state.get("complaint_text", ""),
            flags,
            evidence_present=evidence_present,
        )
    except Exception as exc:  # noqa: BLE001
        deps.record_agent_run(case_id, "MergedRiskAgent", "FAILED", error=str(exc))
        return {
            "errors": [f"MergedRiskAgent: {exc}"],
            "fraud_score": 0,
            "sentiment_score": 0,
            "risk_level": "LOW",
        }

    # 行为画像采用确定性兜底，不依赖 Mock/LLM 是否理解内部风险字段。
    flags = state.get("risk_flags") or {}
    abuse_categories: list[tuple[str, int]] = []
    if flags.get("cross_account_evidence_reuse"):
        abuse_categories.append(("凭证跨账号复用", 70))
    elif flags.get("duplicate_evidence"):
        abuse_categories.append(("同一凭证重复提交", 55))
    if flags.get("refund_velocity_24h") or flags.get("refund_velocity_7d"):
        # 频次只能说明需要观察，不能单独证明欺诈；与高额/复用凭证等信号叠加时再升级。
        abuse_categories.append(("短期退款申请较频繁", 25))
    if flags.get("repeated_high_ratio"):
        abuse_categories.append(("连续申请高比例退款", 60))
    if abuse_categories:
        result.fraud_score = max(result.fraud_score, max(score for _, score in abuse_categories))
        if len(abuse_categories) >= 2:
            result.fraud_score = max(result.fraud_score, 85)
        for label, _ in abuse_categories:
            if label not in result.risk_factors:
                result.risk_factors.append(label)

    deps.record_agent_run(
        case_id, "MergedRiskAgent", "SUCCESS",
        output_summary=f"fraud={result.fraud_score} sentiment={result.sentiment_score}",
    )
    deps.publish_event(case_id, {
        "agent": "MergedRiskAgent",
        "status": "done",
        "fraud_score": result.fraud_score,
        "sentiment_score": result.sentiment_score,
        "risk_level": result.risk_level,
    })
    return {
        "fraud_score": result.fraud_score,
        "sentiment_score": result.sentiment_score,
        "risk_level": result.risk_level,
        "risk_factors": result.risk_factors,
    }
